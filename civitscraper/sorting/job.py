"""
The ``sort-models`` job: report misfiled models, walk through them, move them.

Run it in a terminal for the walk-through, with ``--yes`` to move only the
confident cases without asking, with ``--dry-run`` for the report alone, and
with ``--undo`` to move the last run's models back.
"""

import logging
import os
import sys
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..api.domains import build_model_url, get_domain_settings, is_nsfw
from ..config.loader import merge_configs
from ..html.context import _version_index_cache
from .analysis import Analysis, analyze
from .classifier import Item
from .decisions import KEEP, Decisions, decisions_path, file_key
from .fingerprint import CHECKPOINT, EMBEDDING, LOHA, LOKR, LORA, TEXT_ENCODER, VAE
from .krita import KritaReferences, krita_running
from .layout import (
    FAMILY_NAMES,
    KEPT,
    MISPLACED,
    OK,
    STATE_BROKEN,
    STATE_CONFLICT,
    STATE_UNKNOWN,
    UNSORTED,
    WRONG_ROOT,
    Option,
    Suggestion,
)
from .mover import Journal, Mover, pending_journals, plan_move

logger = logging.getLogger(__name__)

KIND_LABELS = {
    LORA: "LoRA",
    LOKR: "LoKr",
    LOHA: "LoHa",
    CHECKPOINT: "checkpoint",
    VAE: "VAE",
    TEXT_ENCODER: "text encoder",
    EMBEDDING: "embedding",
}
STATE_LABELS = {
    OK: "in place",
    KEPT: "kept by you",
    MISPLACED: "in another base model's folder",
    UNSORTED: "not in a base model folder",
    WRONG_ROOT: "in the wrong model folder",
    STATE_CONFLICT: "CivitAI and the file disagree",
    STATE_UNKNOWN: "not recognised",
    STATE_BROKEN: "broken or incomplete",
}
_ORDER = {MISPLACED: 0, UNSORTED: 1, WRONG_ROOT: 2, STATE_CONFLICT: 3, STATE_UNKNOWN: 4}

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


class _Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def accent(self, text: str) -> str:
        return self._wrap("36", text)

    def warn(self, text: str) -> str:
        return self._wrap("33", text)


class SortJob:
    """Interactive auto-sort of model files."""

    def __init__(
        self,
        config: Dict[str, Any],
        job_name: str,
        job_config: Dict[str, Any],
        run_job: Optional[Callable[[str], bool]] = None,
        input_fn: InputFn = input,
        output_fn: Optional[OutputFn] = None,
        interactive: Optional[bool] = None,
    ):
        """Set up the job; ``input_fn``/``output_fn`` replace the terminal in tests."""
        self.config = merge_configs(config, job_config)
        self.job_name = job_name
        self.job_config = job_config
        self.run_job = run_job
        self.input = input_fn
        self.print: OutputFn = output_fn or (lambda text: print(text, flush=True))
        self.dry_run = bool(config.get("dry_run"))
        self.yes = bool(config.get("yes"))
        self.undo_mode = bool(config.get("undo"))
        if interactive is None:
            interactive = sys.stdin.isatty() and sys.stdout.isatty()
        self.interactive = interactive and not self.dry_run and not self.yes
        self.style = _Style(output_fn is None and sys.stdout.isatty())
        self.mover = Mover(self.config, dry_run=self.dry_run)
        self.decisions = Decisions(decisions_path(self.config))
        self.journal: Optional[Journal] = None
        self.krita_renames: List[Tuple[str, str]] = []
        self.stats: Counter = Counter()
        self.display_root = ""

    # --- Helpers --------------------------------------------------------------

    def _paths(self) -> List[str]:
        paths = self.job_config.get("paths")
        if paths:
            return list(paths)
        return list((self.config.get("input_paths") or {}).keys())

    def rel(self, path: str) -> str:
        """Return a path relative to the library for display."""
        if self.display_root:
            try:
                return os.path.relpath(path, self.display_root)
            except ValueError:
                pass
        return path

    def ask(self, prompt: str, valid: str, default: str) -> str:
        """Ask until the answer is one of ``valid``."""
        while True:
            try:
                answer = self.input(prompt).strip().lower()
            except EOFError:
                return "q"
            if not answer:
                return default
            if answer[0] in valid:
                return answer[0]
            self.print(f"  Please answer one of: {', '.join(valid)}")

    # --- Entry point ----------------------------------------------------------

    def run(self) -> bool:
        """Run the job."""
        try:
            self._recover()
            if self.undo_mode:
                return self._undo()
            analysis = analyze(self.config, self._paths(), self.decisions)
            roots = [r.path for r in analysis.roots]
            if roots:
                parents = [os.path.dirname(r) for r in roots]
                self.display_root = os.path.commonpath(parents) if len(parents) > 1 else parents[0]
            self._report(analysis)
            todo = sorted(
                (
                    s
                    for s in analysis.suggestions
                    if s.actionable and s.options and not any(o.report_only for o in s.options)
                ),
                key=lambda s: (_ORDER.get(s.state, 9), not s.confident, s.path.lower()),
            )
            unanswerable = [s for s in analysis.suggestions if s.actionable and not s.options]
            if todo:
                if self.interactive:
                    self._walk(todo, analysis)
                elif self.yes:
                    self._auto(todo)
                else:
                    self.print("")
                    self.print(
                        "Report only. Run in a terminal to review the moves, or with --yes "
                        "to move the confident ones."
                    )
            if unanswerable and self.interactive:
                self.print(
                    self.style.dim(
                        f"{len(unanswerable)} file(s) could not be placed; see the report."
                    )
                )
            self._finish()
            return True
        except KeyboardInterrupt:
            self.print("\nStopped. Moves done so far are kept (undo with --undo).")
            self._finish()
            return True

    # --- Report ---------------------------------------------------------------

    def _report(self, analysis: Analysis) -> None:
        s = self.style
        counts = Counter(x.state for x in analysis.suggestions)
        self.print(s.bold(f"Sorting {len(analysis.suggestions)} model files"))
        for state in (
            OK,
            KEPT,
            MISPLACED,
            UNSORTED,
            WRONG_ROOT,
            STATE_CONFLICT,
            STATE_UNKNOWN,
            STATE_BROKEN,
        ):
            if counts.get(state):
                self.print(f"  {counts[state]:>5}  {STATE_LABELS[state]}")
        self.print("")
        self.print(s.bold("Folders and the base models they hold"))
        for root in analysis.roots:
            stats = analysis.layout.folder_stats.get(root, {})
            mapping = analysis.layout.folder_base.get(root, {})
            if not mapping:
                continue
            note = s.dim("  (reported only, never moved)") if root.report_only else ""
            self.print(f"  {self.rel(root.path)}{note}")
            for folder in sorted(mapping, key=str.lower):
                base = mapping[folder]
                _, count, total = stats.get(folder, (base, 0, 0))
                detail = f"{count} of {total} labelled" if total else "from your settings"
                self.print(f"    {folder:<20} {s.accent(base)}  {s.dim(detail)}")
        for suggestion in analysis.suggestions:
            if suggestion.state == STATE_BROKEN:
                self.print("")
                self.print(s.warn(f"Broken: {self.rel(suggestion.path)} ({suggestion.reason})"))
        report_only = [
            x
            for x in analysis.suggestions
            if x.actionable and any(o.report_only for o in x.options)
        ]
        for suggestion in report_only:
            option = suggestion.options[0]
            self.print(
                s.dim(
                    f"Not moved (VAE/text encoder): {self.rel(suggestion.path)} "
                    f"might belong in {self.rel(option.target_dir)}"
                )
            )
        for suggestion in analysis.suggestions:
            if suggestion.actionable and not suggestion.options:
                self.print(s.dim(f"No target: {self.rel(suggestion.path)} ({suggestion.reason})"))
        actionable = [x for x in analysis.suggestions if x.actionable and x.options]
        if not actionable:
            self.print("")
            self.print("Everything is where it belongs.")
            return
        if not self.interactive:
            self.print("")
            self.print(s.bold("Suggested moves"))
            for suggestion in actionable:
                for option in suggestion.options:
                    tag = " (confident)" if suggestion.confident else ""
                    self.print(
                        f"  {self.rel(suggestion.path)}\n    -> {self.rel(option.target)}"
                        f"  [{STATE_LABELS[suggestion.state]}{tag}]"
                    )
                for n, url in enumerate(self._links(suggestion.verdict.item)):
                    self.print(f"       {url if n == 0 else s.dim(url)}")

    # --- Evidence -------------------------------------------------------------

    def _evidence(self, suggestion: Suggestion, analysis: Analysis) -> List[str]:
        v = suggestion.verdict
        s = self.style
        lines = []
        item = v.item
        if item.civitai_base:
            lines.append(f"  CivitAI    {item.civitai_base} · {item.civitai_type or '?'}")
            for n, url in enumerate(self._links(item)):
                lines.append(f"  {'Page' if n == 0 else '':<10} {url if n == 0 else s.dim(url)}")
        else:
            lines.append(f"  CivitAI    {s.dim('no data')}")
        vote = v.vote
        if vote:
            family = item.fingerprint.family or ""
            vote_family = analysis.classifier.structural_family(family, vote.base)
            # Built-alike base models only matter when CivitAI does not settle it.
            ambiguous = len(vote_family) > 1 and item.civitai_base != vote.base
            counted = vote_family if ambiguous else frozenset({vote.base})
            support = sum(analysis.classifier.support(family, b) for b in counted)
            if item.civitai_base in counted:
                support -= 1  # the file itself
            kind = KIND_LABELS.get(item.fingerprint.kind, item.fingerprint.kind)
            group = "/".join(sorted(counted))
            text = (
                f"{vote.base} · {vote.similarity:.0%} like your {support} labelled "
                f"{group} {kind} file(s)"
            )
            if vote.runner_up and vote.runner_up[0] not in vote_family:
                text += s.dim(f" (next: {vote.runner_up[0]} {vote.runner_up[1]:.0%})")
            lines.append(f"  Structure  {text}")
            if ambiguous:
                alike = ", ".join(sorted(vote_family))
                lines.append(
                    s.dim(
                        f"             {alike} are built alike: the file cannot " "tell them apart"
                    )
                )
        elif item.fingerprint.kind:
            lines.append(f"  Structure  {KIND_LABELS.get(item.fingerprint.kind, 'not recognised')}")
        hints = item.fingerprint.hints
        shown = [
            f"{k}={hints[k]}"
            for k in ("ss_base_model_version", "modelspec.architecture", "gguf.architecture")
            if k in hints
        ]
        if "trainer" in hints:
            shown.append(hints["trainer"])
        if shown:
            lines.append(f"  Header     {' · '.join(shown)}")
        return lines

    def _links(self, item: Item) -> List[str]:
        """Return the CivitAI pages of the file's version, its routed domain first."""
        meta = item.metadata or {}
        model_id = (meta.get("parentModel") or {}).get("id") or meta.get("modelId")
        version_id = meta.get("id")
        if not model_id or not version_id:
            return []
        domains, threshold, _ = get_domain_settings(self.config)
        nsfw = is_nsfw(meta, threshold)
        return [
            build_model_url(model_id, version_id, nsfw, domains),
            build_model_url(model_id, version_id, not nsfw, domains),
        ]

    def _describe(self, option: Option, plan_companions: int) -> str:
        extra = f"  (+{plan_companions} file(s))" if plan_companions else ""
        flags = []
        if option.new_folder:
            flags.append("new folder")
        if option.cross_root:
            flags.append("other model folder")
        flag = self.style.warn(f"  [{', '.join(flags)}]") if flags else ""
        return f"{self.rel(option.target)}{extra}{flag}"

    # --- Walk-through ---------------------------------------------------------

    def _walk(self, todo: List[Suggestion], analysis: Analysis) -> None:
        s = self.style
        batch: Dict[Tuple[str, str], str] = {}  # (source dir, target dir) -> "y"
        total = len(todo)
        for n, suggestion in enumerate(todo, 1):
            option = suggestion.options[0]
            key = (os.path.dirname(suggestion.path), option.target_dir)
            if suggestion.state != STATE_CONFLICT and batch.get(key) == "y":
                self._move(suggestion, option)
                continue

            v = suggestion.verdict
            kind = KIND_LABELS.get(v.item.fingerprint.kind, "model")
            self.print("")
            self.print(
                f"{s.dim(f'[{n}/{total}]')} {s.bold(self.rel(suggestion.path))}  "
                f"{s.dim(f'({kind} · {STATE_LABELS[suggestion.state]})')}"
            )
            for line in self._evidence(suggestion, analysis):
                self.print(line)

            if suggestion.state == STATE_CONFLICT:
                answer = self._ask_conflict(suggestion)
            else:
                plan = plan_move(suggestion.path, option.target, self.config)
                self.print(f"  Move to    {self._describe(option, max(plan.companions, 0))}")
                if plan.problem:
                    self.print(s.warn(f"  Cannot move: {plan.problem}"))
                    self.stats["blocked"] += 1
                    continue
                default = "n" if suggestion.state == STATE_UNKNOWN else "y"
                src_folder = self._folder_label(key[0], suggestion)
                dst_folder = self._folder_label(key[1], suggestion, option)
                choices = (
                    f"[y] move  [n] keep here  [s] skip  [o] other folder  "
                    f"[a] all {src_folder} → {dst_folder}  [q] quit"
                )
                self.print(s.dim(f"  {choices}"))
                answer = self.ask(f"  > [{default}] ", "ynsoaq", default)
                if answer == "a":
                    batch[key] = "y"
                    answer = "y"
                if answer == "y":
                    self._move(suggestion, option)
                elif answer == "o":
                    self._other_folder(suggestion, option)
            if answer == "q":
                break
            if answer == "n":
                self.decisions.remember(
                    analysis.keys.get(suggestion.path) or self._key(suggestion),
                    KEEP,
                    os.path.basename(suggestion.path),
                )
                self.stats["kept"] += 1
            elif answer == "s":
                self.stats["skipped"] += 1

    def _folder_label(
        self, directory: str, suggestion: Suggestion, option: Optional[Option] = None
    ) -> str:
        root = option.root if option else suggestion.root
        if root is None:
            return os.path.basename(directory)
        rel = os.path.relpath(directory, root.path).replace(os.sep, "/")
        return root.label if rel == "." else rel

    def _key(self, suggestion: Suggestion) -> Optional[str]:
        return file_key(suggestion.verdict.item, self.config)

    def _ask_conflict(self, suggestion: Suggestion) -> str:
        s = self.style
        v = suggestion.verdict
        by_key = {o.key: o for o in suggestion.options}
        letters = []
        for key, letter, who in (("civitai", "c", "CivitAI"), ("file", "f", "the file")):
            option = by_key.get(key)
            if option:
                kind = FAMILY_NAMES.get(option.family, option.family)
                self.print(
                    f"  [{letter}] follow {who} ({option.base}, {kind}) → "
                    f"{self._describe(option, 0)}"
                )
                letters.append(letter)
            else:
                base = v.base if key == "civitai" else v.file_base
                self.print(s.dim(f"      {who} says {base}: it is already in the right folder"))
        self.print(s.dim("  [n] keep here  [s] skip  [q] quit"))
        answer = self.ask("  > [s] ", "".join(letters) + "nsq", "s")
        if answer in ("c", "f"):
            option = by_key["civitai" if answer == "c" else "file"]
            self.decisions.remember(
                self._key(suggestion),
                "base",
                os.path.basename(suggestion.path),
                base=option.base,
                family=option.family,
            )
            self._move(suggestion, option)
        return answer

    def _other_folder(self, suggestion: Suggestion, option: Option) -> None:
        root = option.root
        answer = self.input(
            f"  Folder inside {self.rel(root.path)}/ (e.g. "
            f"{os.path.relpath(option.target_dir, root.path)}): "
        ).strip()
        answer = answer.strip("/\\")
        if not answer or ".." in answer.replace("\\", "/").split("/"):
            self.print("  Skipped.")
            self.stats["skipped"] += 1
            return
        target = os.path.join(root.path, answer, os.path.basename(suggestion.path))
        first = answer.replace("\\", "/").split("/")[0]
        if option.base and first != os.path.relpath(option.target_dir, root.path).split(os.sep)[0]:
            remember = self.ask(f"  Remember: {option.base} goes in {first}? [y/N] ", "yn", "n")
            if remember == "y":
                self.decisions.add_rule(
                    FAMILY_NAMES.get(root.family, root.family), option.base, first
                )
        moved = Option(
            option.key,
            option.base,
            option.family,
            root,
            target,
            new_folder=not os.path.isdir(os.path.dirname(target)),
            cross_root=option.cross_root,
        )
        self._move(suggestion, moved)

    def _auto(self, todo: List[Suggestion]) -> None:
        confident = [x for x in todo if x.confident]
        self.print("")
        self.print(
            f"Moving {len(confident)} confident suggestion(s); "
            f"{len(todo) - len(confident)} need a decision in the walk-through."
        )
        for suggestion in confident:
            self._move(suggestion, suggestion.options[0])

    # --- Moving ---------------------------------------------------------------

    def _move(self, suggestion: Suggestion, option: Option) -> None:
        plan = plan_move(suggestion.path, option.target, self.config)
        if plan.problem:
            self.print(self.style.warn(f"  Not moved: {self.rel(suggestion.path)}: {plan.problem}"))
            self.stats["blocked"] += 1
            return
        if self.journal is None and not self.dry_run:
            self.journal = Journal.create(self.config)
        error = self.mover.apply(plan, self.journal) if self.journal else None
        if error:
            self.print(self.style.warn(f"  Not moved: {error} (nothing changed)"))
            self.stats["failed"] += 1
            return
        verb = "Would move" if self.dry_run else "Moved"
        self.print(
            f"  {verb} {self.rel(plan.source)} → {self.rel(plan.target)}"
            + (f" with {plan.companions} file(s)" if plan.companions else "")
        )
        for left in plan.left_behind:
            self.print(self.style.warn(f"  Left in place (unknown file): {self.rel(left)}"))
        self.stats["moved"] += 1
        root = suggestion.root
        if root and option.root is root and root.family == "adapter":
            self.krita_renames.append(
                (os.path.relpath(plan.source, root.path), os.path.relpath(plan.target, root.path))
            )

    # --- Finish ---------------------------------------------------------------

    def _krita(self) -> int:
        if not self.krita_renames or self.dry_run:
            return 0
        krita = KritaReferences(self.config)
        if not krita.available:
            return 0
        if krita_running():
            if not self.interactive:
                self.print(
                    self.style.warn(
                        "Krita is running: its LoRA references were not "
                        "updated. Close Krita and run the sort job again."
                    )
                )
                return 0
            answer = self.ask(
                "Krita is running and may overwrite the change. Update its LoRA "
                "references anyway? [y/N] ",
                "yn",
                "n",
            )
            if answer != "y":
                return 0
        changed = krita.rewrite(self.krita_renames)
        if self.journal is not None:
            self.journal.data.setdefault("krita", []).extend(
                [list(pair) for pair in self.krita_renames]
            )
        return changed

    def _finish(self) -> None:
        krita_changed = self._krita()
        self.decisions.save()
        self.mover.hash_cache.save()
        if self.journal is not None:
            self.journal.finish()
        moved = self.stats["moved"]
        if moved and not self.dry_run:
            self._regenerate()
        self.print("")
        parts = [f"{moved} moved" if not self.dry_run else "dry run, nothing moved"]
        for key, label in (
            ("kept", "kept"),
            ("skipped", "skipped"),
            ("blocked", "blocked"),
            ("failed", "failed"),
        ):
            if self.stats[key]:
                parts.append(f"{self.stats[key]} {label}")
        if krita_changed:
            parts.append(f"{krita_changed} Krita reference(s) updated")
        self.print(self.style.bold("Done: " + ", ".join(parts)))
        if moved and not self.dry_run:
            self.print(self.style.dim("Undo with: civitscraper -j " + self.job_name + " --undo"))

    def _regenerate(self) -> None:
        _version_index_cache.invalidate()
        sorting = self.config.get("sorting") or {}
        name = sorting.get("regenerate_job")
        jobs = self.config.get("jobs") or {}
        if not name and "regenerate-html" in jobs:
            name = "regenerate-html"
        if not name or name not in jobs or self.run_job is None:
            self.print(
                self.style.dim(
                    "Pages and gallery were not rebuilt: set "
                    "sorting.regenerate_job to a cached HTML job."
                )
            )
            return
        self.print(f"Rebuilding pages and gallery ({name}) ...")
        if not self.run_job(name):
            self.print(self.style.warn(f"Job {name} failed; run it again to fix links."))

    # --- Recovery and undo ----------------------------------------------------

    def _recover(self) -> None:
        if self.dry_run:
            return
        for path in pending_journals(self.config):
            journal = Journal.load(path)
            for message in self.mover.recover(journal):
                self.print(self.style.warn(message))
            self.print(
                self.style.dim(
                    "Krita references of interrupted moves are not updated; "
                    "Krita picks the new paths up on its next model refresh."
                )
            )

    def _undo(self) -> bool:
        journal = Journal.latest(self.config)
        if journal is None:
            self.print("Nothing to undo.")
            return True
        self.print(self.style.bold(f"Undoing sort run {os.path.basename(journal.path)}"))
        krita_pairs = [tuple(p) for p in journal.data.get("krita") or []]
        restored, problems = self.mover.undo(journal)
        for now_at, back_at in restored:
            verb = "Would move back" if self.dry_run else "Moved back"
            self.print(f"  {verb} {os.path.basename(now_at)} → {back_at}")
        for problem in problems:
            self.print(self.style.warn(f"  Not moved back: {problem}"))
        if krita_pairs and not self.dry_run:
            krita = KritaReferences(self.config)
            if krita.available and not (krita_running() and not self.interactive):
                restored_names = {os.path.basename(a) for _, a in restored}
                pairs = [
                    (new, old)
                    for old, new in krita_pairs
                    if os.path.basename(old) in restored_names
                ]
                changed = krita.rewrite(pairs)
                if changed:
                    self.print(f"  {changed} Krita reference(s) restored")
        if restored and not self.dry_run:
            self.stats["moved"] = 0
            self._regenerate()
        self.print(
            self.style.bold(
                f"Done: {len(restored)} moved back" + (f", {len(problems)} not" if problems else "")
            )
        )
        return not problems
