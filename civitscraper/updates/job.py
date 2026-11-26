"""
The ``download-updates`` job: offer newer versions of your models and download them.

In a terminal it walks through every model with a newer version on the same base
model and asks first, then downloads what you chose one file at a time, so you
can leave while it runs. ``--yes`` downloads only free updates below
``updates.auto_max_size_mb`` and keeps the old versions; without a terminal (and
with ``--dry-run``) it only reports. ``--undo`` reverts the last run.

After the downloads it runs the fetch job (sidecars, previews, pages, gallery)
and the trigger sync, and only then archives or trashes the old versions you
chose to replace, so you are never left without a working version.
"""

import html
import logging
import os
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import nh3

from ..api.client import CivitAIClient
from ..api.exceptions import CivitAIError, ClientError
from ..config.loader import merge_configs
from ..html.context import _version_index_cache
from ..jobs.lora_sync import trigger_string, trigger_words_of
from ..scanner.discovery import has_metadata, load_cached_metadata
from ..sorting.fingerprint import CHECKPOINT, FAMILY_ADAPTER, fingerprint
from ..sorting.krita import KritaReferences, krita_running
from ..sorting.mover import (
    DONE,
    UNDONE,
    Journal,
    Mover,
    _missing_dirs,
    _remove_empty,
    _sync_journal,
    companions,
    pending_journals,
    plan_move,
)
from ..utils import trash as trash_module
from ..utils.hash_cache import get_hash_cache
from ..utils.fs import move_no_clobber
from ..utils.terminal import InputFn, OutputFn, Style, ask, human_size, version_links
from . import downloader as dl
from .bases import UsedBases, used_bases
from .candidates import (
    ACCESS_LABELS,
    ADAPTER_TYPES,
    FREE,
    GONE,
    Candidate,
    access_state,
    configured_roots,
    find_candidates,
    scan_patterns,
)
from .decisions import SAME_FILE, UpdateDecisions
from .variant import describe_file, matches_patterns, rank_files

logger = logging.getLogger(__name__)

UPDATE_JOURNALS = "update-journal"
KEEP, ARCHIVE, TRASH = "keep", "archive", "trash"
DEFAULT_AUTO_MAX_MB = 2048
DEFAULT_MIN_FREE_GB = 5
GB = 1024**3
CHECKPOINT_HINT_BYTES = 3 * GB
ADAPTER_HINT_BYTES = int(1.5 * GB)

# Journal entry states of one download
PLANNED, DOWNLOADED, FAILED, ABANDONED = "planned", "downloaded", "failed", "abandoned"


@dataclass
class Offer:
    """One candidate with the version and file that would be downloaded."""

    candidate: Candidate
    sibling: Dict[str, Any]
    version: Dict[str, Any] = field(default_factory=dict)
    access: str = FREE
    until: Optional[str] = None
    files: List[Dict[str, Any]] = field(default_factory=list)
    file: Optional[Dict[str, Any]] = None
    target: Optional[str] = None
    problem: Optional[str] = None
    same_file: bool = False
    new_folder: bool = False
    cross_root: bool = False
    kind_hint: Optional[str] = None

    @property
    def size(self) -> int:
        """Size of the chosen file in bytes."""
        return _file_size(self.file)

    @property
    def downloadable(self) -> bool:
        """Free, with a file that fits the folder and a free target name."""
        return self.access == FREE and self.file is not None and not self.problem


def _file_size(entry: Optional[Dict[str, Any]]) -> int:
    try:
        return int(float((entry or {}).get("sizeKB") or 0) * 1024)
    except (TypeError, ValueError):
        return 0


def _plain(text: Any, limit: int = 200) -> str:
    """Return a version description as one line of plain text."""
    if not isinstance(text, str) or not text.strip():
        return ""
    cleaned = html.unescape(nh3.clean(text, tags=set()))
    line = " ".join(cleaned.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _sha256(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    value = ((entry or {}).get("hashes") or {}).get("SHA256")
    return value.lower() if isinstance(value, str) and value else None


class UpdateJob:
    """Interactive download of newer model versions."""

    def __init__(
        self,
        config: Dict[str, Any],
        job_name: str,
        job_config: Dict[str, Any],
        api_client: CivitAIClient,
        run_job: Optional[Callable[[str], bool]] = None,
        input_fn: InputFn = input,
        output_fn: Optional[OutputFn] = None,
        interactive: Optional[bool] = None,
        downloader: Optional[dl.Downloader] = None,
    ):
        """Set up the job; ``input_fn``/``output_fn``/``downloader`` replace I/O in tests."""
        self.config = merge_configs(config, job_config)
        self.job_name = job_name
        self.job_config = job_config
        self.client = api_client
        self.run_job = run_job
        self.input = input_fn
        self.print: OutputFn = output_fn or (lambda text: print(text, flush=True))
        self.dry_run = bool(config.get("dry_run"))
        self.yes = bool(config.get("yes"))
        self.undo_mode = bool(config.get("undo"))
        if interactive is None:
            interactive = sys.stdin.isatty() and sys.stdout.isatty()
        self.interactive = interactive and not self.dry_run and not self.yes
        self.show_progress = output_fn is None and sys.stdout.isatty()
        self.style = Style(output_fn is None and sys.stdout.isatty())
        self.settings: Dict[str, Any] = self.config.get("updates") or {}
        self.decisions = UpdateDecisions.for_config(self.config, read_only=self.dry_run)
        self.roots = configured_roots(self.config)
        self.mover = Mover(self.config, dry_run=self.dry_run)
        self.hash_cache = get_hash_cache(self.config)
        self.journal: Optional[Journal] = None
        self.stats: Counter = Counter()
        self.downloaded_bytes = 0
        self.display_root = ""
        self._downloader = downloader
        self.no_archive: Dict[str, str] = {}
        self.used: Optional[UsedBases] = None
        self.reserved: set = set()  # targets planned in this run

    # --- Helpers --------------------------------------------------------------

    def _paths(self) -> List[str]:
        paths = self.job_config.get("paths")
        if paths:
            return list(paths)
        return list((self.config.get("input_paths") or {}).keys())

    def rel(self, path: str) -> str:
        """Return a path relative to the library, for display."""
        if self.display_root:
            try:
                return os.path.relpath(path, self.display_root)
            except ValueError:
                pass
        return path

    def ask(self, prompt: str, valid: str, default: str) -> str:
        """Ask until the answer is one of ``valid``."""
        return ask(self.input, self.print, prompt, valid, default)

    @property
    def downloader(self) -> dl.Downloader:
        """Create the file downloader on first use."""
        if self._downloader is None:
            api = self.config.get("api") or {}
            batch = api.get("batch") or {}
            host = urlparse(str(self.client.base_url)).hostname or "civitai.com"
            self._downloader = dl.Downloader(
                self.client.api_key,
                host,
                user_agent=str(self.client.user_agent),
                timeout=float(api.get("timeout", 30)),
                max_retries=int(api.get("max_retries", 3)),
                retry_delay=float(batch.get("retry_delay", 2000)) / 1000.0,
                rate_limiter=getattr(self.client, "download_rate_limiter", None),
            )
        return self._downloader

    def _journal(self) -> Journal:
        if self.journal is None:
            self.journal = Journal.create(self.config, UPDATE_JOURNALS)
            self.journal.data.setdefault("downloads", [])
            self.journal.data.setdefault("trashed", [])
            self.journal.save()
        return self.journal

    def _entries(self) -> List[Dict[str, Any]]:
        if self.journal is None:
            return []
        entries: List[Dict[str, Any]] = self.journal.data.setdefault("downloads", [])
        return entries

    # --- Entry point ----------------------------------------------------------

    def run(self) -> bool:
        """Run the job."""
        try:
            self._set_display_root()
            if self.undo_mode:
                return self._undo()
            queue = self._recover()
            if not self.client.api_key:
                self.print(
                    self.style.warn(
                        "No CivitAI API key (api.key or CIVITAI_API_KEY): CivitAI only lets "
                        "logged-in users download, so this run only reports."
                    )
                )
            self.used = self._used_bases()
            candidates, counts = find_candidates(
                self.config,
                self._paths(),
                self.decisions,
                used_bases=self.used.bases if self.used else None,
            )
            for entry in queue:
                if entry.get("target"):
                    self.reserved.add(os.path.normcase(str(entry["target"])))
            queued = {(e.get("model_id"), e.get("base")) for e in queue}
            candidates = [c for c in candidates if (c.model_id, c.base_model) not in queued]
            same = [c for c in candidates if not c.cross_base]
            cross = [c for c in candidates if c.cross_base]
            offers = [self._offer(c, c.target) for c in same]
            self._report(offers, counts, cross)
            todo = [o for o in offers if o.downloadable]
            self._check_archive(todo)
            if (todo or cross) and self.client.api_key:
                if self.interactive:
                    planned, stopped = self._walk(todo)
                    queue.extend(planned)
                    if cross and not stopped:
                        queue.extend(self._walk_cross(cross))
                elif self.yes:
                    queue.extend(self._auto(todo))
                elif not self.dry_run:
                    self.print("")
                    self.print(
                        "Report only. Run in a terminal to choose the downloads, or with "
                        "--yes to download the small free updates."
                    )
            self.decisions.save()
            if queue and not self.dry_run:
                self._download(queue)
            self._after()
            self._finish()
            return True
        except KeyboardInterrupt:
            self.print("")
            self.print(
                "Stopped. Finished downloads are kept; a partial download is resumed on "
                "the next run (undo with --undo)."
            )
            self.decisions.save()
            self.hash_cache.save()
            if self.journal is not None:
                self.journal.save()
            return True

    def _set_display_root(self) -> None:
        inputs = self.config.get("input_paths") or {}
        paths = [
            os.path.abspath(os.path.expanduser(str(inputs[i]["path"])))
            for i in self._paths()
            if isinstance(inputs.get(i), dict) and inputs[i].get("path")
        ]
        if paths:
            parents = [os.path.dirname(p) for p in paths]
            try:
                self.display_root = os.path.commonpath(parents)
            except ValueError:
                self.display_root = ""

    def _used_bases(self) -> Optional[UsedBases]:
        try:
            return used_bases(self.config)
        except Exception as e:  # versions for other bases are an extra; never fail on them
            logger.warning(f"Could not learn which base models you use: {e}")
            logger.debug("Traceback:", exc_info=True)
            return None

    # --- Offers ---------------------------------------------------------------

    def _offer(self, candidate: Candidate, sibling: Dict[str, Any]) -> Offer:
        """Load ``sibling`` and pick its file; re-uploads of your files fall to the next."""
        newer = candidate.newer
        start = next((i for i, s in enumerate(newer) if s.get("id") == sibling.get("id")), 0)
        offer = self._load_offer(candidate, sibling)
        for later in newer[start + 1 :]:
            if not offer.same_file:
                break
            offer = self._load_offer(candidate, later)
        if offer.same_file:
            offer.problem = "the same file as one you have"
        return offer

    def _load_offer(self, candidate: Candidate, sibling: Dict[str, Any]) -> Offer:
        offer = Offer(candidate, sibling)
        try:
            offer.version = self.client.get_model_version(int(sibling["id"])) or {}
        except ClientError as e:
            if e.status_code == 404:
                offer.access = GONE
                return offer
            offer.problem = f"could not load the version from CivitAI ({e})"
            return offer
        except (CivitAIError, ValueError, TypeError, KeyError) as e:
            offer.problem = f"could not load the version from CivitAI ({e})"
            return offer
        offer.access, offer.until = access_state(offer.version)
        # Ranked over every pattern: a cross-base file may belong in another folder.
        ranked = rank_files(
            offer.version, candidate.anchor_meta, os.path.basename(candidate.anchor), []
        )
        offer.files = [e for e in ranked if self._fits(offer, e)]
        if not offer.files:
            offer.problem = "no file of this version can go in this folder"
            return offer
        self._choose_file(offer, offer.files[0])
        sha = _sha256(offer.file)
        if sha and sha in candidate.local_hashes:
            offer.same_file = True
            self.decisions.decline(
                candidate.model_id, sibling, candidate.model_name, reason=SAME_FILE
            )
            self.stats["same_file"] += 1
        return offer

    def _kind_hint(self, offer: Offer, entry: Dict[str, Any]) -> Optional[str]:
        """Return what a file looks like when its size does not fit its model type."""
        size = _file_size(entry)
        kind = offer.candidate.model_type.upper()
        try:
            anchor_size = os.path.getsize(offer.candidate.anchor)
        except OSError:
            anchor_size = 0
        if kind in ADAPTER_TYPES and size >= CHECKPOINT_HINT_BYTES and size >= 4 * anchor_size:
            return CHECKPOINT
        if kind == "CHECKPOINT" and 0 < size <= ADAPTER_HINT_BYTES:
            return FAMILY_ADAPTER
        return None

    def _directory(self, offer: Offer, entry: Dict[str, Any]) -> Tuple[str, bool, bool]:
        """Return ``(folder, new folder, other model folder)`` for a file of the offer."""
        c = offer.candidate
        anchor_dir = os.path.dirname(os.path.abspath(c.anchor))
        hint = self._kind_hint(offer, entry)
        if not c.cross_base and not hint:
            return anchor_dir, False, False
        layout = self.used.analysis.layout if self.used and self.used.analysis else None
        root = layout.root_of(c.anchor) if layout else None
        if layout is None or root is None:
            return anchor_dir, False, False
        family = hint or root.family
        name = os.path.basename(str(entry.get("name") or "model"))
        option = layout.option(
            "", os.path.join(anchor_dir, name), root, family, c.base_model, False
        )
        if option is None:
            return anchor_dir, False, False
        return os.path.dirname(option.target), option.new_folder, option.cross_root

    def _fits(self, offer: Offer, entry: Dict[str, Any]) -> bool:
        """Whether the folder the file would go to is scanned for its extension."""
        directory, _, _ = self._directory(offer, entry)
        patterns = scan_patterns(self.roots, os.path.join(directory, "x"))
        return matches_patterns(os.path.basename(str(entry.get("name") or "")), patterns)

    def _choose_file(self, offer: Offer, entry: Dict[str, Any]) -> None:
        offer.file = entry
        offer.problem = None
        offer.kind_hint = self._kind_hint(offer, entry)
        directory, _, offer.cross_root = self._directory(offer, entry)
        offer.new_folder = not os.path.isdir(directory)
        self._name_in(offer, directory)

    def _name_in(self, offer: Offer, directory: str) -> None:
        """Pick a free file name in ``directory`` (never one planned in this run)."""
        name = os.path.basename(str((offer.file or {}).get("name") or ""))
        stem, ext = os.path.splitext(name)
        for option in (name, f"{stem}_v{offer.sibling.get('id')}{ext}"):
            path = os.path.join(directory, option)
            if not os.path.lexists(path) and os.path.normcase(path) not in self.reserved:
                offer.target = path
                return
        offer.target = None
        offer.problem = f"{name} already exists in {self.rel(directory)}"

    # --- Report ---------------------------------------------------------------

    def _report(
        self, offers: List[Offer], counts: Counter, cross: Optional[List[Candidate]] = None
    ) -> None:
        s = self.style
        cross = cross or []
        same_file = [o for o in offers if o.same_file]
        offers = [o for o in offers if not o.same_file]
        ready = [o for o in offers if o.downloadable]
        locked = [o for o in offers if o.access not in (FREE, GONE)]
        total = sum(o.size for o in ready)
        self.print("")
        parts = [f"{len(offers)} model(s) with a newer version on the same base model"]
        if ready:
            parts.append(f"{len(ready)} to download ({human_size(total)})")
        if locked:
            parts.append(f"{len(locked)} early access or paid")
        remembered = counts["declined"] + counts["ignored"]
        if remembered:
            parts.append(f"{remembered} declined or ignored earlier")
        if same_file:
            parts.append(f"{len(same_file)} identical to a file you have")
        self.print(s.bold("Updates: ") + " · ".join(parts))
        if not offers:
            self.print(s.dim("  Everything is up to date."))
        if cross:
            by_base = Counter(c.base_model for c in cross)
            listed = ", ".join(f"{b} {n}" for b, n in by_base.most_common())
            self.print(
                s.bold("Also for base models you use: ")
                + f"{len(cross)} version(s) on {len({c.model_id for c in cross})} model(s) "
                + s.dim(f"({listed})")
            )
        if locked:
            self.print("")
            self.print(s.bold("Not downloadable yet (offered once they are free):"))
            for offer in locked:
                label = ACCESS_LABELS.get(offer.access, offer.access)
                until = f" until {offer.until[:10]}" if offer.until else ""
                self.print(
                    f"  {self.rel(offer.candidate.anchor)}  {offer.sibling.get('name')} · "
                    f"{label}{until}"
                )
                for link in self._links(offer):
                    self.print(s.dim(f"    {link}"))
        problems = [o for o in offers if o.access == FREE and o.problem]
        gone = [o for o in offers if o.access == GONE]
        for offer in problems + gone:
            reason = offer.problem or ACCESS_LABELS[GONE]
            self.print(s.warn(f"  Skipped {self.rel(offer.candidate.anchor)}: {reason}"))
        if ready and not self.interactive:
            self.print("")
            verb = "Would download" if self.dry_run else "Available"
            for offer in ready:
                self.print(
                    f"  {verb}: {self.rel(offer.candidate.anchor)} → "
                    f"{os.path.basename(str(offer.target))} · {offer.sibling.get('name')} · "
                    f"{human_size(offer.size)}"
                )

    def _links(self, offer: Offer) -> List[str]:
        return version_links(
            self.config,
            offer.candidate.model_id,
            offer.sibling.get("id"),
            offer.candidate.anchor_meta,
        )

    # --- Walk-through ---------------------------------------------------------

    def _card(self, index: int, total: int, offer: Offer) -> None:
        s = self.style
        c = offer.candidate
        local = c.local_version
        self.print("")
        self.print(
            s.bold(f"[{index}/{total}] {self.rel(c.anchor)}")
            + s.dim(f"   ({c.model_type or 'model'} · {c.base_model})")
        )
        self.print(f"  You have  {local.get('name')} · {str(local.get('createdAt') or '')[:10]}")
        more = len(c.newer) - 1
        extra = s.dim(f"   ({more} more newer version(s): [v])") if more > 0 else ""
        self.print(
            f"  New       {offer.sibling.get('name')} · "
            f"{str(offer.sibling.get('createdAt') or '')[:10]} · {human_size(offer.size)} · "
            f"{describe_file(offer.file or {})}{extra}"
        )
        notes = _plain(offer.version.get("description"))
        if notes:
            self.print(f"  Notes     {notes}")
        new_words = trigger_words_of(offer.version) or []
        old_words = trigger_words_of(c.anchor_meta) or []
        if new_words or old_words:
            line = trigger_string(new_words) or "(none)"
            if trigger_string(old_words) != trigger_string(new_words):
                line += s.dim(f"  (was: {trigger_string(old_words) or 'none'})")
            self.print(f"  Triggers  {line}")
        links = self._links(offer)
        if links:
            self.print(f"  Links     {'  '.join(links)}")
        self.print(f"  Save as   {self.rel(str(offer.target))}")
        part = dl.part_path(str(offer.target))
        if os.path.isfile(part):
            self.print(
                s.dim(f"            ({human_size(os.path.getsize(part))} already downloaded)")
            )

    def _walk(self, todo: List[Offer]) -> Tuple[List[Dict[str, Any]], bool]:
        planned: List[Dict[str, Any]] = []
        total = len(todo)
        stopped = False
        for index, offer in enumerate(todo, 1):
            while True:
                self._card(index, total, offer)
                keys = ["[y] download", "[n] not this version", "[i] ignore this model"]
                valid = "ynisq"
                if len(offer.candidate.newer) > 1:
                    keys.append("[v] other version")
                    valid += "v"
                if len(offer.files) > 1:
                    keys.append("[f] other file")
                    valid += "f"
                keys += ["[s] skip", "[q] quit"]
                answer = self.ask("  " + "  ".join(keys) + " ", valid, "s")
                if answer == "v":
                    offer = self._pick_version(offer)
                    continue
                if answer == "f":
                    self._pick_file(offer)
                    continue
                break
            if answer == "q":
                stopped = True
                break
            if answer == "y":
                if not offer.downloadable:
                    self.print(
                        self.style.warn(f"  Cannot download: {offer.problem or offer.access}")
                    )
                    continue
                root = offer.candidate.root.path if offer.candidate.root else None
                archive = bool(root) and root not in self.no_archive
                planned.append(self._entry(offer, self._ask_old(archive)))
            elif answer == "n":
                self.decisions.decline(
                    offer.candidate.model_id, offer.sibling, offer.candidate.model_name
                )
                self.stats["declined"] += 1
                self._offer_part_cleanup(offer)
            elif answer == "i":
                self.decisions.ignore_model(offer.candidate.model_id, offer.candidate.model_name)
                self.stats["ignored"] += 1
                self._offer_part_cleanup(offer)
            else:
                self.stats["skipped"] += 1
        return planned, stopped

    def _walk_cross(self, cross: List[Candidate]) -> List[Dict[str, Any]]:
        """Versions for other base models you use: asked one by one, loaded lazily."""
        s = self.style
        planned: List[Dict[str, Any]] = []
        self.print("")
        self.print(
            s.bold("Also available for base models you use")
            + s.dim("  ([b] never for this base · [x] skip all the rest)")
        )
        total = len(cross)
        declined_bases: set = set()
        for index, candidate in enumerate(cross, 1):
            if (candidate.model_id, candidate.base_model) in declined_bases:
                continue
            offer = self._offer(candidate, candidate.target)
            if not offer.downloadable:
                reason = offer.problem or ACCESS_LABELS.get(offer.access, offer.access)
                self.print(
                    s.dim(
                        f"[{index}/{total}] {candidate.model_name} · "
                        f"{candidate.base_model}: {reason}"
                    )
                )
                continue
            while True:
                self._cross_card(index, total, offer)
                keys = [
                    "[y] download",
                    "[n] not this version",
                    f"[b] never for {candidate.base_model}",
                ]
                valid = "ynbiosxq"
                if len(candidate.newer) > 1:
                    keys.append("[v] other version")
                    valid += "v"
                if len(offer.files) > 1:
                    keys.append("[f] other file")
                    valid += "f"
                keys += [
                    "[o] other folder",
                    "[i] ignore this model (also its updates)",
                    "[s] skip",
                    "[x] skip the rest",
                    "[q] quit",
                ]
                answer = self.ask("  " + "  ".join(keys) + " ", valid, "s")
                if answer == "v":
                    offer = self._pick_version(offer)
                    continue
                if answer == "f":
                    self._pick_file(offer)
                    continue
                if answer == "o":
                    self._other_folder(offer)
                    continue
                break
            if answer in "xq":
                break
            if answer == "y":
                if not offer.downloadable:
                    self.print(s.warn(f"  Cannot download: {offer.problem or offer.access}"))
                    continue
                planned.append(self._entry(offer, KEEP))
            elif answer == "n":
                self.decisions.decline(candidate.model_id, offer.sibling, candidate.model_name)
                self.stats["declined"] += 1
                self._offer_part_cleanup(offer)
            elif answer == "b":
                # The newest version on that base: the cascade hides every older one too.
                self.decisions.decline(candidate.model_id, candidate.newer[0], candidate.model_name)
                declined_bases.add((candidate.model_id, candidate.base_model))
                self.stats["declined"] += 1
                self._offer_part_cleanup(offer)
            elif answer == "i":
                self.decisions.ignore_model(candidate.model_id, candidate.model_name)
                declined_bases.update(
                    (candidate.model_id, b) for b in (self.used.bases if self.used else ())
                )
                self.stats["ignored"] += 1
                self._offer_part_cleanup(offer)
            else:
                self.stats["skipped"] += 1
        return planned

    def _cross_card(self, index: int, total: int, offer: Offer) -> None:
        s = self.style
        c = offer.candidate
        self.print("")
        self.print(
            s.bold(f"[{index}/{total}] {c.model_name} · also for {c.base_model}")
            + s.dim(f"   (you have: {self.rel(c.anchor)} · {c.from_base})")
        )
        more = len(c.newer) - 1
        extra = s.dim(f"   ({more} more on {c.base_model}: [v])") if more > 0 else ""
        self.print(
            f"  Version   {offer.sibling.get('name')} · "
            f"{str(offer.sibling.get('createdAt') or '')[:10]} · {human_size(offer.size)} · "
            f"{describe_file(offer.file or {})}{extra}"
        )
        if offer.kind_hint:
            label = "a full checkpoint" if offer.kind_hint == CHECKPOINT else "a LoRA"
            self.print(s.warn(f"  Note      looks like {label} (size), not a {c.model_type}"))
        notes = _plain(offer.version.get("description"))
        if notes:
            self.print(f"  Notes     {notes}")
        words = trigger_words_of(offer.version)
        if words:
            self.print(f"  Triggers  {trigger_string(words)}")
        links = self._links(offer)
        if links:
            self.print(f"  Links     {'  '.join(links)}")
        flags = []
        if offer.new_folder:
            flags.append("new folder")
        if offer.cross_root:
            flags.append("other model folder")
        flag = s.warn(f"   [{', '.join(flags)}]") if flags else ""
        self.print(f"  Save as   {self.rel(str(offer.target))}{flag}")

    def _other_folder(self, offer: Offer) -> None:
        try:
            answer = self.input(
                f"    Folder (relative to {self.display_root or 'the library'}, Enter to cancel): "
            ).strip()
        except EOFError:
            return
        if not answer:
            return
        folder = os.path.abspath(os.path.join(self.display_root or os.getcwd(), answer))
        if not any(r.contains(os.path.join(folder, "x")) for r in self.roots):
            self.print(self.style.warn("    Not inside one of your model folders."))
            return
        name = os.path.basename(str((offer.file or {}).get("name") or ""))
        if not matches_patterns(name, scan_patterns(self.roots, os.path.join(folder, "x"))):
            self.print(self.style.warn("    That folder is not scanned for this file type."))
            return
        self._name_in(offer, folder)
        offer.new_folder = not os.path.isdir(folder)
        offer.cross_root = False

    def _ask_old(self, archive: bool = True) -> str:
        options = [("k", "keep")]
        if archive:
            options.append(("a", "archive"))
        if trash_module.supported():
            options.append(("t", "trash"))
        keys = "  ".join(f"[{key}] {label}" for key, label in options)
        answer = self.ask(
            f"  Old version after download: {keys}  (default k) ",
            "".join(key for key, _ in options),
            "k",
        )
        return {"k": KEEP, "a": ARCHIVE, "t": TRASH}[answer]

    def _pick_version(self, offer: Offer) -> Offer:
        newer = offer.candidate.newer
        for n, sibling in enumerate(newer, 1):
            mark = " ←" if sibling.get("id") == offer.sibling.get("id") else ""
            self.print(
                f"    {n}) {sibling.get('name')} · {str(sibling.get('createdAt') or '')[:10]}{mark}"
            )
        choice = self._number(len(newer))
        if choice is None:
            return offer
        return self._offer(offer.candidate, newer[choice])

    def _pick_file(self, offer: Offer) -> None:
        for n, entry in enumerate(offer.files, 1):
            mark = " ←" if entry is offer.file else ""
            self.print(
                f"    {n}) {entry.get('name')} · {human_size(_file_size(entry))} · "
                f"{describe_file(entry)}{mark}"
            )
        choice = self._number(len(offer.files))
        if choice is not None:
            self._choose_file(offer, offer.files[choice])

    def _number(self, count: int) -> Optional[int]:
        try:
            answer = self.input(f"    Number (1-{count}, Enter to cancel): ").strip()
        except EOFError:
            return None
        if answer.isdigit() and 1 <= int(answer) <= count:
            return int(answer) - 1
        return None

    def _offer_part_cleanup(self, offer: Offer) -> None:
        part = dl.part_path(str(offer.target)) if offer.target else None
        if part and os.path.isfile(part):
            size = human_size(os.path.getsize(part))
            if self.ask(f"  Delete the partial download ({size})? [y/N] ", "yn", "n") == "y":
                os.remove(part)

    def _auto(self, todo: List[Offer]) -> List[Dict[str, Any]]:
        cap = int(self.settings.get("auto_max_size_mb", DEFAULT_AUTO_MAX_MB)) * 1024 * 1024
        chosen = [o for o in todo if o.size and o.size <= cap]
        self.print("")
        self.print(
            f"Downloading {len(chosen)} free update(s) up to {human_size(cap)}; "
            f"{len(todo) - len(chosen)} larger one(s) wait for the walk-through."
        )
        return [self._entry(o, KEEP) for o in chosen]

    def _entry(self, offer: Offer, old_action: str) -> Dict[str, Any]:
        c = offer.candidate
        file = offer.file or {}
        entry = {
            "model_id": c.model_id,
            "model": c.model_name,
            "version_id": offer.sibling.get("id"),
            "version": offer.sibling.get("name"),
            "url": dl.download_url(file, offer.sibling.get("id"), str(self.client.base_url)),
            "target": offer.target,
            "size": offer.size or None,
            "sha256": _sha256(file),
            "old": c.anchor,
            "old_action": old_action,
            "lora_root": c.lora_root.path if c.lora_root else None,
            "root": c.root.path if c.root else None,
            "base": c.base_model,
            "cross_base": c.cross_base,
            "status": PLANNED,
        }
        if offer.target:
            self.reserved.add(os.path.normcase(offer.target))
        return entry

    # --- Downloads ------------------------------------------------------------

    def _download(self, queue: List[Dict[str, Any]]) -> None:
        journal = self._journal()
        entries = self._entries()
        for entry in queue:
            if entry not in entries:
                entries.append(entry)
        journal.save()
        total = sum(int(e.get("size") or 0) for e in queue)
        self.print("")
        self.print(self.style.bold(f"Downloading {len(queue)} file(s), {human_size(total)}"))
        for entry in queue:
            if not self._download_one(entry):
                break
            journal.save()
        journal.save()
        self.hash_cache.save()

    def _download_one(self, entry: Dict[str, Any]) -> bool:
        """Download one entry; False stops the remaining downloads."""
        target = str(entry["target"])
        name = os.path.basename(target)
        size = int(entry.get("size") or 0)
        part = dl.part_path(target)
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        min_free = float(self.settings.get("min_free_gb", DEFAULT_MIN_FREE_GB)) * GB
        created = entry.setdefault("created_dirs", [])
        try:
            for directory in _missing_dirs(os.path.dirname(target)):
                os.mkdir(directory)
                created.append(directory)
        except OSError as e:
            entry["status"] = FAILED
            entry["error"] = f"cannot create the folder: {e}"
            self.stats["failed"] += 1
            self.print(self.style.warn(f"  Skipped {name}: cannot create its folder ({e})"))
            _remove_empty(created)
            return True
        free = shutil.disk_usage(os.path.dirname(target)).free
        if size and free < (size - have) + min_free:
            entry["status"] = FAILED
            entry["error"] = "not enough disk space"
            self.stats["failed"] += 1
            self.print(
                self.style.warn(
                    f"  Skipped {name}: needs {human_size(size - have)} and "
                    f"{human_size(min_free)} spare, {human_size(free)} free"
                )
            )
            _remove_empty(created)
            return True
        progress = _Progress(name, self.show_progress)
        result = self.downloader.download(
            str(entry["url"]), target, size or None, entry.get("sha256"), progress
        )
        progress.done()
        if result.ok:
            entry["status"] = DOWNLOADED
            entry["verified"] = result.verified
            try:
                if result.sha256:
                    self.hash_cache.put(target, "sha256", os.stat(target), result.sha256)
            except OSError:
                pass
            self.stats["downloaded"] += 1
            self.downloaded_bytes += size
            check = "verified" if result.verified else "size checked, CivitAI has no SHA256"
            self.print(f"  Downloaded {self.rel(target)} ({human_size(size)}, {check})")
            return True
        entry["status"] = FAILED
        entry["error"] = result.message
        self.stats["failed"] += 1
        if not os.path.exists(part):
            _remove_empty(created)
        if result.status == dl.UNAUTHORIZED:
            self.print(
                self.style.warn(
                    f"  CivitAI refused the API key ({result.message}). Check api.key; "
                    "the remaining downloads are skipped."
                )
            )
            return False
        if result.status == dl.EARLY_ACCESS:
            self.print(self.style.warn(f"  {name}: {result.message or 'early access'}"))
        else:
            self.print(self.style.warn(f"  Failed {name}: {result.message or result.status}"))
        return True

    # --- After the downloads --------------------------------------------------

    def _after_jobs(self) -> List[str]:
        configured = self.settings.get("after_jobs")
        jobs = self.config.get("jobs") or {}
        if isinstance(configured, list):
            return [str(n) for n in configured if n in jobs]
        names: List[str] = []
        fetch = next(
            (
                n
                for n, j in jobs.items()
                if isinstance(j, dict)
                and j.get("type") == "scan-paths"
                and not j.get("use_cached_metadata")
            ),
            None,
        )
        if fetch:
            names.append(fetch)
        names += [
            n
            for n, j in jobs.items()
            if isinstance(j, dict) and j.get("type") == "sync-lora-triggers"
        ]
        return names

    def _after(self) -> None:
        if self.dry_run or self.journal is None:
            return
        entries = [e for e in self._entries() if e.get("status") == DOWNLOADED]
        unfetched = [e for e in entries if not e.get("fetched")]
        for entry in unfetched:
            if not entry.get("kind_checked"):
                self._check_kind(entry)
                entry["kind_checked"] = True
        if unfetched:
            self.hash_cache.save()
            names = self._after_jobs()
            if names and self.run_job is not None:
                self.print("")
                for name in names:
                    self.print(f"Running {name} for the new files ...")
                    if not self.run_job(name):
                        self.print(self.style.warn(f"Job {name} failed."))
            else:
                self.print(
                    self.style.dim(
                        "No fetch job to run: set updates.after_jobs, then run it to get "
                        "the new files' pages."
                    )
                )
            for entry in unfetched:
                entry["fetched"] = True
            self.journal.save()
        replaced: List[Dict[str, Any]] = []
        for entry in entries:
            if entry.get("old_action", KEEP) == KEEP or entry.get("old_done"):
                continue
            target = str(entry["target"])
            if not has_metadata(target, self.config):
                self.print(
                    self.style.warn(
                        f"  Kept {self.rel(str(entry['old']))}: the new file has no "
                        "CivitAI data yet (run the fetch job, then decide again)"
                    )
                )
                entry["old_done"] = "kept"
                continue
            if self._replace_old(entry):
                replaced.append(entry)
            self.journal.save()
        if replaced:
            self._krita(replaced)
            self._regenerate()

    def _check_kind(self, entry: Dict[str, Any]) -> None:
        """Move a download whose header shows another model type to the right folder."""
        target = str(entry["target"])
        layout = self.used.analysis.layout if self.used and self.used.analysis else None
        if layout is None or not os.path.isfile(target):
            return
        root = layout.root_of(target)
        print_ = fingerprint(target)
        family = print_.family
        if root is None or family not in (FAMILY_ADAPTER, CHECKPOINT) or family == root.family:
            return
        option = layout.option(
            "", target, root, family, str(entry.get("base") or ""), print_.bundled
        )
        label = "a checkpoint" if family == CHECKPOINT else "a LoRA"
        if option is None or os.path.lexists(option.target):
            self.print(
                self.style.warn(
                    f"  {self.rel(target)} is {label}; no free place for it "
                    "(the sort job will report it)"
                )
            )
            return
        if not self.interactive:
            self.print(
                self.style.warn(
                    f"  {self.rel(target)} is {label}; left in place (run the sort job)"
                )
            )
            return
        answer = self.ask(
            f"  {self.rel(target)} is {label}. Move it to "
            f"{self.rel(os.path.dirname(option.target))}? [Y/n] ",
            "yn",
            "y",
        )
        if answer != "y":
            return
        created = entry.setdefault("created_dirs", [])
        try:
            for directory in _missing_dirs(os.path.dirname(option.target)):
                os.mkdir(directory)
                created.append(directory)
            move_no_clobber(target, option.target)
        except OSError as e:
            self.print(self.style.warn(f"  Not moved: {e}"))
            return
        # Not a Mover move: undo trashes the file where it is now (entry["target"]).
        self.hash_cache.rekey(target, option.target)
        entry["target"] = option.target
        self.print(f"  Moved to {self.rel(option.target)}")
        if self.journal is not None:
            self.journal.save()

    def _archive_base(self, root_path: str) -> str:
        """Return the archive folder for models of the input path ``root_path``."""
        configured = self.settings.get("archive_dir")
        if configured:
            path = os.path.expandvars(os.path.expanduser(str(configured)))
            if not os.path.isabs(path):
                path = os.path.join(str(self.config.get("_config_dir") or os.getcwd()), path)
            return os.path.abspath(path)
        return os.path.join(os.path.dirname(root_path), "_archive")

    def _archive_problem(self, root_path: str) -> Optional[str]:
        """Return why archiving cannot work for ``root_path``, or None."""
        base = self._archive_base(root_path)
        target = os.path.join(base, os.path.basename(root_path))
        inside = [r.path for r in self.roots if r.contains(target)]
        if inside:
            return f"the archive folder {base} is inside a scanned folder ({inside[0]})"
        try:
            same_drive = _device(base) == _device(root_path)
        except OSError:
            same_drive = True
        if not same_drive:
            return (
                f"the archive folder {base} is on another drive than {root_path} "
                "(archiving moves files, it never copies them)"
            )
        return None

    def _check_archive(self, offers: List[Offer]) -> None:
        """Find input paths whose models cannot be archived; warn once."""
        self.no_archive = {}
        for root in {o.candidate.root.path for o in offers if o.candidate.root}:
            problem = self._archive_problem(root)
            if problem:
                self.no_archive[root] = problem
                self.print(self.style.warn(f"Archiving is off: {problem}."))

    def _archive_target(self, old: str, root_path: Optional[str]) -> Tuple[Optional[str], str]:
        if not root_path:
            return None, "not inside a configured folder"
        problem = self._archive_problem(root_path)
        if problem:
            return None, problem
        base = self._archive_base(root_path)
        target = os.path.join(base, os.path.basename(root_path), os.path.relpath(old, root_path))
        return target, ""

    def _replace_old(self, entry: Dict[str, Any]) -> bool:
        old = str(entry["old"])
        action = entry.get("old_action")
        if action == ARCHIVE:
            target, why = self._archive_target(old, entry.get("root"))
            plan = plan_move(old, target, self.config) if target else None
            if plan is None or plan.problem:
                reason = why if plan is None else plan.problem
                self.print(self.style.warn(f"  Kept {self.rel(old)}: {reason}"))
                entry["old_done"] = "kept"
                return False
            error = self.mover.apply(plan, self._journal())
            if error:
                self.print(self.style.warn(f"  Kept {self.rel(old)}: {error}"))
                entry["old_done"] = "kept"
                return False
            entry["old_done"] = ARCHIVE
            entry["archived_to"] = plan.target
            self.stats["archived"] += 1
            self.print(f"  Archived {self.rel(old)} → {plan.target} with {plan.companions} file(s)")
            return True
        if action == TRASH:
            if os.path.lexists(_sync_journal(old, self.config)):
                self.print(self.style.warn(f"  Kept {self.rel(old)}: unfinished preview update"))
                entry["old_done"] = "kept"
                return False
            files = [old] + [path for path, _ in companions(old, self.config)]
            trashed = self._journal().data.setdefault("trashed", [])
            try:
                for path in files:
                    where, info = trash_module.trash(path)
                    trashed.append({"original": path, "trashed": where, "info": info})
                    self.hash_cache.rekey(path, where)
            except OSError as e:
                self.print(self.style.warn(f"  Could not trash all of {self.rel(old)}: {e}"))
                gone = not os.path.lexists(old)
                entry["old_done"] = TRASH if gone else "kept"
                return gone
            entry["old_done"] = TRASH
            self.stats["trashed"] += 1
            self.print(f"  Moved {self.rel(old)} and {len(files) - 1} file(s) to the Trash")
            return True
        return False

    def _krita(self, replaced: List[Dict[str, Any]]) -> None:
        if not (self.settings.get("krita") or {}).get("enabled", True):
            return
        pairs: List[Tuple[str, str]] = []
        replacements: List[Tuple[str, str, Optional[str]]] = []
        for entry in replaced:
            root = entry.get("lora_root")
            if not root:
                continue
            old_rel = os.path.relpath(str(entry["old"]), root)
            new_rel = os.path.relpath(str(entry["target"]), root)
            meta = load_cached_metadata(str(entry["target"]), self.config) or {}
            words = trigger_words_of(meta)
            pairs.append((old_rel, new_rel))
            replacements.append((old_rel, new_rel, trigger_string(words) if words else None))
        if not pairs:
            return
        krita = KritaReferences(self.config)
        if not krita.available:
            return
        if krita_running():
            if not self.interactive:
                self.print(
                    self.style.warn(
                        "Krita is running: its LoRA references still point at the old "
                        "versions. Close Krita before the next run to have them updated."
                    )
                )
                return
            answer = self.ask(
                "Krita is running and may overwrite the change. Point its LoRA references "
                "at the new versions anyway? [y/N] ",
                "yn",
                "n",
            )
            if answer != "y":
                return
        records = krita.replace_entries(replacements)
        changed = krita.rewrite(pairs, files=krita.style_files())
        journal = self._journal()
        journal.data.setdefault("krita_entries", []).extend(records)
        journal.data.setdefault("krita", []).extend([list(p) for p in pairs])
        journal.save()
        self.stats["krita"] += len(records) + changed

    def _regenerate(self) -> None:
        _version_index_cache.invalidate()
        name = (self.config.get("sorting") or {}).get("regenerate_job")
        jobs = self.config.get("jobs") or {}
        if not name and "regenerate-html" in jobs:
            name = "regenerate-html"
        if not name or name not in jobs or self.run_job is None:
            return
        self.print(f"Rebuilding pages and gallery ({name}) ...")
        if not self.run_job(name):
            self.print(self.style.warn(f"Job {name} failed; run it again to fix links."))

    def _finish(self) -> None:
        self.decisions.save()
        self.hash_cache.save()
        if self.journal is not None:
            unfinished = [
                e
                for e in self._entries()
                if e.get("status") == PLANNED
                or (
                    e.get("status") == DOWNLOADED
                    and e.get("old_action", KEEP) != KEEP
                    and not e.get("old_done")
                )
            ]
            if unfinished:
                self.journal.save()
            else:
                self.journal.finish(DONE)
        s = self.stats
        self.print("")
        if self.dry_run:
            parts = ["dry run, nothing downloaded"]
        else:
            parts = [f"{s['downloaded']} downloaded"]
            if s["downloaded"]:
                parts[0] += f" ({human_size(self.downloaded_bytes)})"
        for key, label in (
            ("failed", "failed"),
            ("archived", "old version(s) archived"),
            ("trashed", "old version(s) trashed"),
            ("declined", "declined"),
            ("ignored", "model(s) ignored"),
            ("skipped", "skipped"),
            ("krita", "Krita reference(s) updated"),
        ):
            if s[key]:
                parts.append(f"{s[key]} {label}")
        self.print(self.style.bold("Done: " + ", ".join(parts)))
        if s["downloaded"] and not self.dry_run:
            self.print(self.style.dim("Undo with: civitscraper -j " + self.job_name + " --undo"))

    # --- Recovery and undo ----------------------------------------------------

    def _recover(self) -> List[Dict[str, Any]]:
        """Adopt an interrupted run: resume its downloads, finish its replacements."""
        if self.dry_run:
            return []
        paths = pending_journals(self.config, UPDATE_JOURNALS)
        if not paths:
            return []
        for older in paths[:-1]:
            Journal.load(older).finish(DONE)
        self.journal = Journal.load(paths[-1])
        pending = [e for e in self._entries() if e.get("status") == PLANNED]
        if not pending:
            return []
        have = sum(
            os.path.getsize(dl.part_path(str(e["target"])))
            for e in pending
            if os.path.isfile(dl.part_path(str(e["target"])))
        )
        total = sum(int(e.get("size") or 0) for e in pending)
        self.print(
            self.style.bold(
                f"{len(pending)} interrupted download(s) ({human_size(have)} of "
                f"{human_size(total)})."
            )
        )
        if self.interactive:
            resume = self.ask("Resume them now? [Y/n] ", "yn", "y") == "y"
        else:
            resume = self.yes
        if resume:
            return pending
        for entry in pending:
            entry["status"] = ABANDONED
        if self.interactive:
            parts = [
                dl.part_path(str(e["target"]))
                for e in pending
                if os.path.isfile(dl.part_path(str(e["target"])))
            ]
            if (
                parts
                and self.ask(
                    f"Delete the partial download(s) ({human_size(have)})? [y/N] ", "yn", "n"
                )
                == "y"
            ):
                for part in parts:
                    os.remove(part)
        elif not self.yes:
            for entry in pending:
                entry["status"] = PLANNED  # report-only runs leave them for later
            self.print(self.style.dim("Run in a terminal to resume them."))
        self.journal.save()
        return []

    def _undo(self) -> bool:
        journal = Journal.latest(self.config, DONE, UPDATE_JOURNALS)
        if journal is None:
            self.print("Nothing to undo.")
            return True
        self.journal = journal
        self.print(self.style.bold(f"Undoing update run {os.path.basename(journal.path)}"))
        problems: List[str] = []
        # Krita first: its references still name the new files
        krita_pairs = [tuple(p) for p in journal.data.get("krita") or []]
        records = journal.data.get("krita_entries") or []
        if (krita_pairs or records) and not self.dry_run:
            krita = KritaReferences(self.config)
            if krita.available and not (krita_running() and not self.interactive):
                krita.restore_entries(records)
                krita.rewrite([(n, o) for o, n in krita_pairs], files=krita.style_files())
                self.print("  Krita references restored")
        # The downloads (and the pages the fetch made for them) go to the Trash
        for entry in reversed(self._entries()):
            if entry.get("status") != DOWNLOADED:
                continue
            target = str(entry["target"])
            if not os.path.lexists(target):
                continue
            files = [target] + [p for p, _ in companions(target, self.config)]
            if self.dry_run:
                self.print(f"  Would move {self.rel(target)} to the Trash")
                continue
            if not trash_module.supported():
                problems.append(f"{self.rel(target)}: no Trash here, delete it yourself")
                continue
            try:
                for path in files:
                    trash_module.trash(path)
            except OSError as e:
                problems.append(f"{self.rel(target)}: {e}")
                continue
            entry["status"] = UNDONE
            self.print(f"  Moved {self.rel(target)} to the Trash")
        # Archived old versions come back
        restored, move_problems = self.mover.undo(journal, finish=False)
        for _, back_at in restored:
            self.print(f"  {'Would move' if self.dry_run else 'Moved'} back {self.rel(back_at)}")
        problems += move_problems
        # Trashed old versions come back
        for record in reversed(journal.data.get("trashed") or []):
            if record.get("restored"):
                continue
            if self.dry_run:
                self.print(f"  Would restore {self.rel(record['original'])} from the Trash")
                continue
            try:
                trash_module.restore(record["trashed"], record["info"], record["original"])
                self.hash_cache.rekey(record["trashed"], record["original"])
                record["restored"] = True
                self.print(f"  Restored {self.rel(record['original'])} from the Trash")
            except OSError as e:
                problems.append(f"{self.rel(record['original'])}: {e}")
        for problem in problems:
            self.print(self.style.warn(f"  Not undone: {problem}"))
        if not self.dry_run:
            journal.finish(UNDONE if not problems else DONE)
            self.hash_cache.save()
            self._regenerate()
        self.print(self.style.bold("Done" + (f": {len(problems)} problem(s)" if problems else "")))
        return not problems


def _device(path: str) -> int:
    """Device of ``path``, or of its nearest existing parent."""
    current = os.path.abspath(path)
    while not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.stat(current).st_dev


class _Progress:
    """A one-line progress display, throttled to four updates a second."""

    def __init__(self, name: str, enabled: bool):
        self.name = name if len(name) <= 40 else name[:39] + "…"
        self.enabled = enabled
        self.started = time.monotonic()
        self.last = 0.0
        self.first: Optional[int] = None
        self.shown = False

    def __call__(self, done: int, total: int) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if self.first is None:
            self.first = done
        if now - self.last < 0.25 and done < total:
            return
        self.last = now
        elapsed = max(now - self.started, 1e-6)
        speed = (done - (self.first or 0)) / elapsed
        eta = ""
        if speed > 0 and total > done:
            seconds = int((total - done) / speed)
            eta = f"  ETA {seconds // 60}:{seconds % 60:02d}"
        sys.stdout.write(
            f"\r  {self.name}  {human_size(done)}/{human_size(total)}  "
            f"{human_size(speed)}/s{eta}\033[K"
        )
        sys.stdout.flush()
        self.shown = True

    def done(self) -> None:
        if self.shown:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
