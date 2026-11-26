"""
Where each model file belongs.

A *root* is a configured input path for one kind of model (``Lora/``, ``unet/``,
...). Below a root, the first directory level is the *base folder*
(``Lora/SDXL``); anything deeper is the user's own categories (``style``,
``character``), which a move keeps.

Which base folder holds which base model is learned from the files that already
have CivitAI labels: a folder stands for a base model when most of its labelled
files are of that base. ``sorting.base_folders`` and remembered rules override it.
"""

import logging
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..scanner.discovery import is_within
from .classifier import (
    BROKEN,
    CONFLICT,
    INFERRED,
    LABELLED,
    UNKNOWN,
    Classifier,
    Verdict,
)
from .fingerprint import CHECKPOINT, EMBEDDING, FAMILY_ADAPTER, TEXT_ENCODER, VAE

logger = logging.getLogger(__name__)

FOLDER_MAJORITY = 0.6
FOLDER_MIN_FILES = 3

# input_paths ``type`` -> kind family
ROOT_TYPES = {
    "lora": FAMILY_ADAPTER,
    "locon": FAMILY_ADAPTER,
    "lycoris": FAMILY_ADAPTER,
    "checkpoint": CHECKPOINT,
    "textualinversion": EMBEDDING,
    "vae": VAE,
    "textencoder": TEXT_ENCODER,
}

# Names used in config (``sorting.base_folders``) for each kind family
FAMILY_NAMES = {
    FAMILY_ADAPTER: "lora",
    CHECKPOINT: "checkpoint",
    VAE: "vae",
    TEXT_ENCODER: "text_encoder",
    EMBEDDING: "embedding",
}
_NAME_FAMILIES = {name: family for family, name in FAMILY_NAMES.items()}

# Kinds that are reported but never moved (shared across base models, rarely labelled)
REPORT_ONLY_FAMILIES = frozenset({VAE, TEXT_ENCODER})

# Root folder names a checkpoint prefers when its base has no folder anywhere yet
_BUNDLED_ROOT_NAMES = ("stable-diffusion", "checkpoints")
_DIFFUSION_ROOT_NAMES = ("unet", "diffusion_models", "diffusion-models")

# File states
OK = "ok"
MISPLACED = "misplaced"
UNSORTED = "unsorted"
WRONG_ROOT = "wrong_root"
STATE_CONFLICT = "conflict"
STATE_UNKNOWN = "unknown"
STATE_BROKEN = "broken"
KEPT = "kept"

# CivitAI's catch-all base model says nothing about where a file belongs.
IGNORED_BASES = frozenset({"other"})

ACTIONABLE = (MISPLACED, UNSORTED, WRONG_ROOT, STATE_CONFLICT, STATE_UNKNOWN)


def normalize_name(name: str) -> str:
    """Folder name for comparison: lower case, letters and digits only."""
    return re.sub(r"[^0-9a-z]", "", name.lower())


def folder_name_for(base: str) -> str:
    """Make a folder name for a base model that has none yet."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", base).strip(" .")
    return name or "Other"


@dataclass(frozen=True)
class Root:
    """A configured input path for one kind family."""

    path: str
    family: str
    path_id: str

    @property
    def report_only(self) -> bool:
        """VAE and text encoder roots are reported, never sorted."""
        return self.family in REPORT_ONLY_FAMILIES

    @property
    def label(self) -> str:
        """Folder name of the root."""
        return os.path.basename(os.path.normpath(self.path)) or self.path


@dataclass
class Option:
    """One possible move for a file."""

    key: str  # "move", "civitai" or "file"
    base: str
    family: str
    root: Root
    target: str
    new_folder: bool = False
    cross_root: bool = False

    @property
    def report_only(self) -> bool:
        """Target lies in a report-only root."""
        return self.root.report_only

    @property
    def target_dir(self) -> str:
        """Directory the file moves to."""
        return os.path.dirname(self.target)


@dataclass
class Suggestion:
    """A file's place: where it is, what it is, where it could go."""

    verdict: Verdict
    state: str
    root: Optional[Root]
    folder: Optional[str]  # current base folder (first level below the root)
    folder_base: Optional[str]  # base model that folder stands for
    options: List[Option] = field(default_factory=list)
    reason: str = ""

    @property
    def path(self) -> str:
        """Model file path."""
        return self.verdict.path

    @property
    def actionable(self) -> bool:
        """Worth a question: the file seems to be in the wrong place."""
        return self.state in ACTIONABLE

    @property
    def confident(self) -> bool:
        """Safe for ``--yes``: one move inside the root, into an existing folder."""
        if self.state not in (MISPLACED, UNSORTED) or len(self.options) != 1:
            return False
        option = self.options[0]
        if option.new_folder or option.cross_root or option.report_only:
            return False
        verdict = self.verdict
        if verdict.status == LABELLED:
            return True
        return verdict.status == INFERRED and verdict.confidence == "high"


def roots_from_config(config: Dict[str, Any], path_ids: List[str]) -> List[Root]:
    """List the configured roots of the job's paths; nested roots collapse outward."""
    input_paths = config.get("input_paths", {}) or {}
    roots: List[Root] = []
    for path_id in path_ids:
        path_config = input_paths.get(path_id)
        if not isinstance(path_config, dict) or not isinstance(path_config.get("path"), str):
            continue
        family = ROOT_TYPES.get(str(path_config.get("type", "")).lower())
        if not family:
            logger.debug(f"Input path {path_id}: type not sorted")
            continue
        path = os.path.abspath(os.path.expanduser(path_config["path"]))
        if not os.path.isdir(path):
            continue
        roots.append(Root(path, family, path_id))

    kept: List[Root] = []
    for root in roots:
        outer = [
            other
            for other in roots
            if other is not root
            and other.family == root.family
            and is_within(root.path, other.path)
            and (
                os.path.normcase(other.path) != os.path.normcase(root.path)
                or roots.index(other) < roots.index(root)
            )
        ]
        if not outer:
            kept.append(root)
    return kept


class Layout:
    """Learned folder layout of every root, plus the targets it implies."""

    def __init__(
        self,
        roots: List[Root],
        classifier: Classifier,
        verdicts: List[Verdict],
        overrides: Optional[Dict[str, Any]] = None,
        rules: Optional[Dict[str, Dict[str, str]]] = None,
    ):
        """Learn the folder layout of ``roots`` from ``verdicts``."""
        self.roots = roots
        self.classifier = classifier
        self.verdicts = verdicts
        # (family, base) -> folder name, from config and remembered rules
        self._fixed: Dict[Tuple[str, str], str] = {}
        # Overrides given as one name for every root: they only map a folder that
        # exists, so a root kept flat (no base folders) stays unsorted by design.
        self._generic: set = set()
        self._load_overrides(overrides or {})
        for family_name, mapping in (rules or {}).items():
            family = _NAME_FAMILIES.get(family_name, family_name)
            for base, folder in (mapping or {}).items():
                if isinstance(folder, str) and folder:
                    self._fixed[(family, base)] = folder
        # root -> folder name -> base model
        self.folder_base: Dict[Root, Dict[str, str]] = {}
        # root -> folder name -> (count of majority base, labelled files)
        self.folder_stats: Dict[Root, Dict[str, Tuple[str, int, int]]] = {}
        self._learn()

    # --- Configuration --------------------------------------------------------

    def _load_overrides(self, overrides: Dict[str, Any]) -> None:
        for base, value in overrides.items():
            if isinstance(value, str):
                for family in FAMILY_NAMES:
                    self._fixed[(family, str(base))] = value
                    self._generic.add((family, str(base)))
            elif isinstance(value, dict):
                for family_name, folder in value.items():
                    named = _NAME_FAMILIES.get(str(family_name))
                    if named and isinstance(folder, str) and folder:
                        self._fixed[(named, str(base))] = folder

    # --- Learning -------------------------------------------------------------

    def root_of(self, path: str) -> Optional[Root]:
        """Return the most specific root containing ``path``."""
        containing = [r for r in self.roots if is_within(path, r.path)]
        return max(containing, key=lambda r: len(r.path)) if containing else None

    @staticmethod
    def folder_of(path: str, root: Root) -> Optional[str]:
        """First directory level below the root (None for files in the root itself)."""
        rel = os.path.relpath(os.path.dirname(os.path.abspath(path)), root.path)
        parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
        return parts[0] if parts else None

    def existing_folders(self, root: Root) -> List[str]:
        """List the visible directories of a root."""
        try:
            return sorted(
                name
                for name in os.listdir(root.path)
                if not name.startswith(".") and os.path.isdir(os.path.join(root.path, name))
            )
        except OSError:
            return []

    def _learn(self) -> None:
        counts: Dict[Root, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        for verdict in self.verdicts:
            if verdict.status != LABELLED or not verdict.base:
                continue
            root = self.root_of(verdict.path)
            if not root or verdict.family != root.family:
                continue
            folder = self.folder_of(verdict.path, root)
            if folder:
                counts[root][folder][verdict.base] += 1

        for root in self.roots:
            mapping: Dict[str, str] = {}
            stats: Dict[str, Tuple[str, int, int]] = {}
            for folder, bases in counts.get(root, {}).items():
                base, count = bases.most_common(1)[0]
                total = sum(bases.values())
                stats[folder] = (base, count, total)
                if total >= FOLDER_MIN_FILES and count >= FOLDER_MAJORITY * total:
                    mapping[folder] = base
            # Overrides and rules name folders explicitly.
            existing = {normalize_name(f): f for f in self.existing_folders(root)}
            for (family, base), folder in self._fixed.items():
                if family != root.family:
                    continue
                actual = existing.get(normalize_name(folder))
                if actual is None and (family, base) in self._generic:
                    continue
                # An explicit folder stands for that base (and others may share it).
                mapping.setdefault(actual or folder, base)
            self.folder_base[root] = mapping
            self.folder_stats[root] = stats

    # --- Queries --------------------------------------------------------------

    def folder_for(self, root: Root, base: str) -> Optional[str]:
        """Return the folder of ``root`` holding ``base`` (None if it has none yet)."""
        fixed = self._fixed.get((root.family, base))
        existing = {normalize_name(f): f for f in self.existing_folders(root)}
        if fixed:
            return existing.get(normalize_name(fixed), fixed)
        candidates = [f for f, b in self.folder_base.get(root, {}).items() if b == base]
        if not candidates:
            return None
        stats = self.folder_stats.get(root, {})
        return max(candidates, key=lambda f: (stats.get(f, ("", 0, 0))[1], f))

    def folder_accepts(self, root: Root, folder: Optional[str], base: str) -> bool:
        """Whether ``base`` belongs in ``folder`` (its own folder or one fixed to it)."""
        if not folder:
            return False
        if self.folder_base.get(root, {}).get(folder) == base:
            return True
        fixed = self._fixed.get((root.family, base))
        return fixed is not None and normalize_name(fixed) == normalize_name(folder)

    def proposed_folder(self, root: Root, base: str) -> str:
        """Name for a new base folder: the one this base uses elsewhere, else its name."""
        existing = {normalize_name(f): f for f in self.existing_folders(root)}
        for other in self.roots:
            if other is root:
                continue
            for folder, mapped in self.folder_base.get(other, {}).items():
                if mapped == base:
                    return existing.get(normalize_name(folder), folder)
        name = folder_name_for(base)
        return existing.get(normalize_name(name), name)

    def roots_for(self, family: str) -> List[Root]:
        """Return the roots of a kind family."""
        return [r for r in self.roots if r.family == family]

    def target_root(self, family: str, base: str, bundled: bool) -> Optional[Root]:
        """Root a file of ``family``/``base`` moves to from another root."""
        roots = self.roots_for(family)
        if not roots:
            return None
        with_base = [r for r in roots if self.folder_for(r, base)]
        if with_base:
            return with_base[0]
        preferred = _BUNDLED_ROOT_NAMES if bundled else _DIFFUSION_ROOT_NAMES
        for root in roots:
            if root.label.lower() in preferred:
                return root
        return roots[0]

    @staticmethod
    def _match_dirs(start: str, parts: List[str]) -> str:
        """Join ``parts`` under ``start``, reusing existing directories case-insensitively."""
        current = start
        for part in parts:
            try:
                names = {
                    n.lower(): n
                    for n in os.listdir(current)
                    if os.path.isdir(os.path.join(current, n))
                }
            except OSError:
                names = {}
            current = os.path.join(current, names.get(part.lower(), part))
        return current

    def option(
        self, key: str, path: str, root: Root, family: str, base: str, bundled: bool
    ) -> Optional[Option]:
        """Where ``path`` goes when it is a ``family`` file of ``base``."""
        name = os.path.basename(path)
        if family == root.family:
            folder = self.folder_for(root, base)
            new_folder = folder is None
            folder = folder or self.proposed_folder(root, base)
            rel = os.path.relpath(os.path.dirname(os.path.abspath(path)), root.path)
            parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
            rest = parts[1:]  # categories below the current base folder
            target_dir = self._match_dirs(os.path.join(root.path, folder), rest)
            if new_folder:
                new_folder = not os.path.isdir(os.path.join(root.path, folder))
            return Option(key, base, family, root, os.path.join(target_dir, name), new_folder)

        target_root = self.target_root(family, base, bundled)
        if target_root is None:
            return None
        folder = self.folder_for(target_root, base) or self.proposed_folder(target_root, base)
        target_dir = os.path.join(target_root.path, folder)
        return Option(
            key,
            base,
            family,
            target_root,
            os.path.join(target_dir, name),
            new_folder=not os.path.isdir(target_dir),
            cross_root=True,
        )

    def suggest(self, verdict: Verdict) -> Suggestion:
        """Decide where the file of ``verdict`` belongs."""
        root = self.root_of(verdict.path)
        folder = self.folder_of(verdict.path, root) if root else None
        folder_base = self.folder_base.get(root, {}).get(folder) if root and folder else None
        suggestion = Suggestion(verdict, OK, root, folder, folder_base)
        if root is None:
            suggestion.reason = "not inside a configured root"
            return suggestion
        bundled = verdict.item.fingerprint.bundled

        if verdict.status == BROKEN:
            suggestion.state = STATE_BROKEN
            suggestion.reason = "; ".join(verdict.notes) or "unreadable file"
            return suggestion

        if verdict.status == CONFLICT:
            suggestion.state = STATE_CONFLICT
            for key, family, base in (
                ("civitai", verdict.family, verdict.base),
                ("file", verdict.file_family, verdict.file_base),
            ):
                if not family or not base:
                    continue
                if family == root.family and self.folder_accepts(root, folder, base):
                    continue  # already where this reading puts it
                option = self.option(key, verdict.path, root, family, base, bundled)
                if option:
                    suggestion.options.append(option)
            if not suggestion.options:
                suggestion.state = OK
            return suggestion

        family, base = verdict.family, verdict.base
        if base and base.lower() in IGNORED_BASES:
            base = None
        if not family or not base:
            # Nothing speaks against the current folder. Only files that are not
            # sorted yet (root level, unmapped folder) are worth a question.
            if verdict.status == UNKNOWN and not root.report_only and not folder_base:
                suggestion.state = STATE_UNKNOWN
                suggestion.reason = "; ".join(verdict.notes) or "kind or base model not recognised"
            return suggestion

        if family == root.family:
            if self.folder_accepts(root, folder, base):
                return suggestion
            # Structure alone cannot tell family members apart: a file without
            # CivitAI data in a folder of its structural family stays.
            if (
                verdict.status != LABELLED
                and folder_base
                and folder_base in (verdict.structural_family or {base})
            ):
                return suggestion
            if not folder_base and not self.folder_base.get(root):
                return suggestion  # this root is not sorted by base model at all
            state = MISPLACED if folder_base else UNSORTED
        else:
            state = WRONG_ROOT

        if verdict.status == UNKNOWN:
            state = STATE_UNKNOWN
        option = self.option("move", verdict.path, root, family, base, bundled)
        if option is None:
            suggestion.state = state
            suggestion.reason = f"no {FAMILY_NAMES.get(family, family)} folder configured"
            return suggestion
        suggestion.state = state
        suggestion.options.append(option)
        return suggestion
