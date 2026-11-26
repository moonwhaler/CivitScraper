"""
Move a model with everything that belongs to it, safely.

- **Never overwrites.** Every target is checked before the first move, and each
  move is atomic no-clobber (:func:`civitscraper.utils.fs.move_no_clobber`). Nothing
  is ever deleted; a move to another filesystem is refused, not copied.
- **Journaled.** Before a model is touched, its planned moves go to a journal in
  ``<cache_dir>/sort-journal/`` (a subdirectory: the API cache prunes only
  top-level files). An interrupted run is finished on the next one.
- **Undoable.** ``--undo`` moves the models of the last run back, recomputing what
  belongs to each model *now* (a later fetch may have added previews).
"""

import glob
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..organization.operations import FileOperationHandler
from ..scanner.discovery import get_html_path, get_image_path, get_metadata_path
from ..utils.fs import atomic_write, move_no_clobber
from ..utils.hash_cache import get_hash_cache

logger = logging.getLogger(__name__)

RECENT_SECONDS = 5 * 60
_SYNC_JOURNAL_SUFFIX = ".civitscraper-sync.json"
_LEGACY_SUFFIXES = (
    ".preview.png",
    ".preview.jpg",
    ".preview.jpeg",
    ".preview.webp",
    ".civitai.info",
)

RUNNING = "running"
DONE = "done"
UNDONE = "undone"


SORT_JOURNALS = "sort-journal"


def journal_dir(config: Dict[str, Any], subdir: str = SORT_JOURNALS) -> str:
    """Return the directory holding a job's journals (sort runs by default)."""
    cache_dir = (config.get("scanner") or {}).get("cache_dir", ".civitscraper_cache")
    return os.path.join(os.path.abspath(os.path.expanduser(cache_dir)), subdir)


def pending_journals(config: Dict[str, Any], subdir: str = SORT_JOURNALS) -> List[str]:
    """Journals of runs that were interrupted."""
    result = []
    for path in sorted(glob.glob(os.path.join(journal_dir(config, subdir), "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                if json.load(f).get("state") == RUNNING:
                    result.append(path)
        except (OSError, ValueError):
            continue
    return result


@dataclass
class Plan:
    """What moving one model involves."""

    source: str
    target: str
    moves: List[Tuple[str, str]] = field(default_factory=list)  # model first
    left_behind: List[str] = field(default_factory=list)
    problem: Optional[str] = None

    @property
    def companions(self) -> int:
        """Number of files moving with the model."""
        return len(self.moves) - 1


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _sync_journal(path: str, config: Dict[str, Any]) -> str:
    probe = get_image_path(path, config, "preview1", ".jpeg")
    stem = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(os.path.dirname(probe), f".{stem}{_SYNC_JOURNAL_SUFFIX}")


def companions(path: str, config: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    Files that belong to the model at ``path`` and where they go when it moves.

    Returns ``(source, kind)`` pairs: ``metadata``, ``html``, ``preview<N>`` or
    ``extra`` (files next to the model named ``<file>.*`` or ``<stem>.preview.*``).
    The model file itself does not need to exist (used to find what was left behind).
    """
    found: List[Tuple[str, str]] = []
    for related, kind, index in FileOperationHandler(config).get_related_files(path):
        found.append((related, f"preview{index}" if kind == "preview" else kind))
    directory = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    extras = [f"{name}.rgthree-info.json"] + [stem + s for s in _LEGACY_SUFFIXES]
    taken = {os.path.normcase(os.path.abspath(p)) for p, _ in found}
    for extra in extras:
        candidate = os.path.join(directory, extra)
        if os.path.isfile(candidate) and os.path.normcase(candidate) not in taken:
            found.append((candidate, "extra"))
    return found


def companion_target(source: str, kind: str, new_path: str, config: Dict[str, Any]) -> str:
    """Where a companion goes once its model lives at ``new_path``."""
    if kind == "metadata":
        return get_metadata_path(new_path, config)
    if kind == "html":
        return get_html_path(new_path, config)
    if kind.startswith("preview"):
        ext = os.path.splitext(source)[1]
        return get_image_path(new_path, config, kind, ext)
    return os.path.join(os.path.dirname(os.path.abspath(new_path)), os.path.basename(source))


def _busy_reason(path: str) -> Optional[str]:
    try:
        if time.time() - os.path.getmtime(path) < RECENT_SECONDS:
            return "modified in the last few minutes (still downloading?)"
    except OSError:
        return "cannot be read"
    directory = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    for other in names:
        partial = other.startswith(stem + ".") or other.startswith(f".{name}")
        if other.endswith(".part") and partial:
            return f"a download is in progress or failed next to it ({other})"
    return None


def plan_move(source: str, target: str, config: Dict[str, Any], check_busy: bool = True) -> Plan:
    """Work out every move for one model; ``problem`` says why it cannot move."""
    plan = Plan(source, target)
    if not os.path.isfile(source):
        plan.problem = "file not found"
        return plan
    if _same(source, target):
        plan.problem = "already there"
        return plan
    if check_busy:
        busy = _busy_reason(source)
        if busy:
            plan.problem = busy
            return plan
    if os.path.lexists(_sync_journal(source, config)):
        plan.problem = "unfinished preview update; run the fetch job first"
        return plan

    plan.moves.append((source, target))
    for path, kind in companions(source, config):
        destination = companion_target(path, kind, target, config)
        if not _same(path, destination):
            plan.moves.append((path, destination))

    destinations = set()
    for src, dst in plan.moves:
        key = os.path.normcase(os.path.abspath(dst))
        if key in destinations:
            plan.problem = f"two files would land on {dst}"
            return plan
        destinations.add(key)
        if os.path.lexists(dst):
            plan.problem = f"target exists: {dst}"
            return plan

    moved = {os.path.normcase(os.path.abspath(s)) for s, _ in plan.moves}
    stem = os.path.splitext(os.path.basename(source))[0]
    directory = os.path.dirname(os.path.abspath(source))
    try:
        for other in sorted(os.listdir(directory)):
            full = os.path.join(directory, other)
            if (
                other.startswith(stem + ".")
                and os.path.normcase(full) not in moved
                and os.path.isfile(full)
                and not other.endswith(".part")
            ):
                plan.left_behind.append(full)
    except OSError:
        pass
    return plan


def _missing_dirs(directory: str) -> List[str]:
    """Directories ``makedirs(directory)`` would create, outermost first."""
    missing = []
    current = os.path.abspath(directory)
    while not os.path.isdir(current):
        missing.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return list(reversed(missing))


def _remove_empty(dirs: List[str]) -> None:
    for directory in reversed(dirs):
        try:
            os.rmdir(directory)  # only succeeds when empty
        except OSError:
            pass


class Journal:
    """One sort run's record of moves."""

    def __init__(self, path: str, data: Optional[Dict[str, Any]] = None):
        """Wrap journal data (a new running journal when None)."""
        self.path = path
        self.data = data or {
            "version": 1,
            "state": RUNNING,
            "started": int(time.time()),
            "models": [],
            "krita": [],
        }

    @classmethod
    def create(cls, config: Dict[str, Any], subdir: str = SORT_JOURNALS) -> "Journal":
        """Start a new journal file."""
        directory = journal_dir(config, subdir)
        os.makedirs(directory, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(directory, f"{stamp}.json")
        n = 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(directory, f"{stamp}-{n}.json")
        return cls(path)

    @classmethod
    def load(cls, path: str) -> "Journal":
        """Read a journal file."""
        with open(path, "r", encoding="utf-8") as f:
            return cls(path, json.load(f))

    @classmethod
    def latest(
        cls, config: Dict[str, Any], state: str = DONE, subdir: str = SORT_JOURNALS
    ) -> Optional["Journal"]:
        """Return the newest journal in ``state``."""
        pattern = os.path.join(journal_dir(config, subdir), "*.json")
        for path in sorted(glob.glob(pattern), reverse=True):
            try:
                journal = cls.load(path)
            except (OSError, ValueError):
                continue
            if journal.data.get("state") == state:
                return journal
        return None

    def save(self) -> None:
        """Write the journal."""
        atomic_write(self.path, json.dumps(self.data, indent=1))

    @property
    def models(self) -> List[Dict[str, Any]]:
        """Moved models, in order."""
        models: List[Dict[str, Any]] = self.data.setdefault("models", [])
        return models

    def finish(self, state: str = DONE) -> None:
        """Mark the run finished."""
        self.data["state"] = state
        self.data["finished"] = int(time.time())
        self.save()


class Mover:
    """Carry out planned moves, journaled; undo and recover earlier runs."""

    def __init__(self, config: Dict[str, Any], dry_run: bool = False):
        """Set up moves for ``config``; ``dry_run`` plans without touching files."""
        self.config = config
        self.dry_run = dry_run
        self.hash_cache = get_hash_cache(config)

    def _do(self, moves: List[Tuple[str, str]], created: List[str]) -> Optional[str]:
        """Move all, or none: on failure the moves done so far are reversed."""
        done: List[Tuple[str, str]] = []
        try:
            for src, dst in moves:
                for directory in _missing_dirs(os.path.dirname(dst)):
                    os.mkdir(directory)
                    created.append(directory)
                move_no_clobber(src, dst)
                done.append((src, dst))
        except OSError as e:
            for src, dst in reversed(done):
                try:
                    move_no_clobber(dst, src)
                except OSError as back:
                    logger.error(f"Could not move {dst} back to {src}: {back}")
            _remove_empty(created)
            del created[:]
            return f"{e.strerror or e}: {getattr(e, 'filename', '') or ''}".strip(": ")
        return None

    def apply(self, plan: Plan, journal: Journal) -> Optional[str]:
        """Move one model. Returns None on success, else why nothing was moved."""
        if plan.problem:
            return plan.problem
        if self.dry_run:
            return None
        entry: Dict[str, Any] = {
            "source": plan.source,
            "target": plan.target,
            "moves": [list(m) for m in plan.moves],
            "created_dirs": [],
            "status": RUNNING,
        }
        journal.models.append(entry)
        journal.save()
        created: List[str] = []
        error = self._do(plan.moves, created)
        entry["created_dirs"] = created
        entry["status"] = "failed" if error else DONE
        if error:
            entry["error"] = error
        else:
            self.hash_cache.rekey(plan.source, plan.target)
        journal.save()
        return error

    def recover(self, journal: Journal) -> List[str]:
        """
        Finish an interrupted run.

        A model that already moved gets the rest of its files; one that did not
        move stays where it is.
        """
        messages = []
        for entry in journal.models:
            if entry.get("status") != RUNNING:
                continue
            source, target = entry["source"], entry["target"]
            if os.path.isfile(target) and not os.path.lexists(source):
                remaining = [
                    (path, companion_target(path, kind, target, self.config))
                    for path, kind in companions(source, self.config)
                ]
                remaining = [(s, d) for s, d in remaining if not os.path.lexists(d)]
                created = entry.setdefault("created_dirs", [])
                error = self._do(remaining, created)
                entry["status"] = "failed" if error else DONE
                self.hash_cache.rekey(source, target)
                messages.append(
                    f"Finished interrupted move of {os.path.basename(source)}"
                    + (f" (problem: {error})" if error else "")
                )
            else:
                entry["status"] = "rolled_back"
                messages.append(f"Interrupted move of {os.path.basename(source)} had not started")
        journal.finish(DONE)
        self.hash_cache.save()
        return messages

    def undo(
        self, journal: Journal, finish: bool = True
    ) -> Tuple[List[Tuple[str, str]], List[str]]:
        """
        Move every model of ``journal`` back.

        Returns:
            ``(restored, problems)``: restored ``(now_at, back_at)`` model paths, and
            messages for models that could not go back
        """
        restored: List[Tuple[str, str]] = []
        problems: List[str] = []
        for entry in reversed(journal.models):
            if entry.get("status") != DONE:
                continue
            source, target = entry["source"], entry["target"]
            plan = plan_move(target, source, self.config, check_busy=False)
            if plan.problem:
                problems.append(f"{os.path.basename(target)}: {plan.problem}")
                continue
            if self.dry_run:
                restored.append((target, source))
                continue
            created: List[str] = []
            error = self._do(plan.moves, created)
            if error:
                problems.append(f"{os.path.basename(target)}: {error}")
                continue
            self.hash_cache.rekey(target, source)
            _remove_empty(entry.get("created_dirs") or [])
            entry["status"] = UNDONE
            restored.append((target, source))
        if not self.dry_run:
            if finish:
                journal.finish(UNDONE if not problems else DONE)
            self.hash_cache.save()
        return restored, problems
