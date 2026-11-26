"""
Find models with a newer version on CivitAI, on the same base model.

The rule is the gallery's update flag (:func:`civitscraper.html.context.update_available`):
a remote version counts only when it is newer than every local version of the
model on its base model, so a new SDXL release never "updates" an SD 1.5 copy.
Local versions are grouped by CivitAI model across every scanned folder.
"""

import logging
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple

from ..scanner.discovery import find_model_files, load_cached_metadata
from ..scanner.sidecar import bookkeeping
from .decisions import UpdateDecisions
from .variant import local_entry

logger = logging.getLogger(__name__)

FREE = "free"
EARLY_ACCESS = "early_access"
PAID = "paid"
GENERATION_ONLY = "generation_only"
GONE = "gone"

ACCESS_LABELS = {
    EARLY_ACCESS: "early access",
    PAID: "paid (Buzz)",
    GENERATION_ONLY: "generation only, no download",
    GONE: "no longer on CivitAI",
}

ADAPTER_TYPES = {"LORA", "LOCON", "LYCORIS", "DORA"}


@dataclass
class Root:
    """A configured input path."""

    path: str
    type: str
    patterns: List[str]

    def contains(self, path: str) -> bool:
        """Whether ``path`` lies inside this root."""
        try:
            return os.path.commonpath([self.path, os.path.abspath(path)]) == self.path
        except ValueError:
            return False


def configured_roots(config: Dict[str, Any]) -> List[Root]:
    """Every ``input_paths`` entry with a path."""
    roots = []
    for entry in (config.get("input_paths") or {}).values():
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        path = os.path.abspath(os.path.expanduser(str(entry["path"])))
        patterns = list(entry.get("patterns") or ["*.safetensors"])
        roots.append(Root(path, str(entry.get("type") or ""), patterns))
    return roots


def outermost(roots: List[Root], path: str, types: Optional[set] = None) -> Optional[Root]:
    """Return the outermost configured root that contains ``path`` (optionally of ``types``)."""
    found = [r for r in roots if r.contains(path) and (types is None or r.type.upper() in types)]
    return min(found, key=lambda r: len(r.path)) if found else None


def scan_patterns(roots: List[Root], path: str) -> List[str]:
    """Patterns of every root that contains ``path`` (what a scan would pick up there)."""
    patterns: List[str] = []
    for root in roots:
        if root.contains(path):
            patterns.extend(p for p in root.patterns if p not in patterns)
    return patterns


def access_state(version: Dict[str, Any], now: Optional[float] = None) -> Tuple[str, Optional[str]]:
    """Whether a version can be downloaded with an API key: ``(state, until)``."""
    usage = version.get("usageControl")
    if usage and usage != "Download":
        return GENERATION_ONLY, None
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now if now is not None else time.time()))
    ends = version.get("earlyAccessEndsAt")
    if isinstance(ends, str) and ends > stamp:
        return EARLY_ACCESS, ends
    if version.get("availability") == "EarlyAccess":
        return EARLY_ACCESS, ends if isinstance(ends, str) else None
    paid = version.get("paidAccess")
    if isinstance(paid, dict):
        until = paid.get("endsAt")
        if paid.get("permanent") or not isinstance(until, str) or until > stamp:
            return PAID, until if isinstance(until, str) else None
    return FREE, None


@dataclass
class Candidate:
    """A model with a newer version on the same base model."""

    model_id: Any
    model_name: str
    model_type: str
    base_model: str
    anchor: str  # the local file of the newest local version on this base
    anchor_meta: Dict[str, Any]
    local_version: Dict[str, Any]
    newer: List[Dict[str, Any]]  # sibling dicts, newest first
    patterns: List[str]
    root: Optional[Root]
    lora_root: Optional[Root]
    target: Dict[str, Any] = field(default_factory=dict)
    # A version for another base model you use (an addition, not an update)
    cross_base: bool = False
    from_base: str = ""
    # SHA256 of every local file of the model (a "new" version with one of these
    # files is a re-upload of what you have)
    local_hashes: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        """Offer the newest version by default."""
        if not self.target and self.newer:
            self.target = self.newer[0]


def _local_hashes(members: List[Tuple[str, Dict[str, Any]]]) -> FrozenSet[str]:
    """SHA256 of each local file, from its sidecar entry."""
    hashes = set()
    for path, meta in members:
        entry = local_entry(meta, os.path.basename(path))
        sha = (entry.get("hashes") or {}).get("SHA256")
        if isinstance(sha, str) and sha:
            hashes.add(sha.lower())
    return frozenset(hashes)


def _created(meta: Dict[str, Any]) -> str:
    return str(meta.get("createdAt") or "")


def find_candidates(
    config: Dict[str, Any],
    path_ids: List[str],
    decisions: UpdateDecisions,
    recursive: bool = True,
    used_bases: Optional[Iterable[str]] = None,
) -> Tuple[List[Candidate], Counter]:
    """
    Find update candidates among the models of ``path_ids``.

    With ``used_bases``, versions for those other base models (ones you have no
    local version of for that model) are candidates too, marked ``cross_base``:
    the newest version on each such base, whatever its date.

    Returns:
        ``(candidates, counts)``; counts has ``declined`` and ``ignored``
    """
    other_bases = set(used_bases or ())
    roots = configured_roots(config)
    counts: Counter = Counter()
    seen: set = set()
    groups: Dict[Any, List[Tuple[str, Dict[str, Any]]]] = {}
    for files in find_model_files(config, path_ids, recursive).values():
        for path in files:
            key = os.path.normcase(os.path.abspath(path))
            if key in seen:
                continue
            seen.add(key)
            meta = load_cached_metadata(path, config)
            if not isinstance(meta, dict) or not meta.get("modelId") or not meta.get("files"):
                continue
            if bookkeeping(meta).get("removed"):
                continue
            groups.setdefault(meta["modelId"], []).append((path, meta))

    candidates: List[Candidate] = []
    for model_id, members in groups.items():
        local_ids = {meta.get("id") for _, meta in members}
        hashes = _local_hashes(members)
        siblings: Dict[Any, Dict[str, Any]] = {}
        for _, meta in members:
            for sibling in meta.get("siblingVersions") or []:
                if isinstance(sibling, dict) and sibling.get("id") not in local_ids:
                    siblings.setdefault(sibling.get("id"), sibling)
        if not siblings:
            continue
        newest_local: Dict[Any, Tuple[str, Dict[str, Any]]] = {}
        for path, meta in members:
            base = meta.get("baseModel")
            if base not in newest_local or _created(meta) > _created(newest_local[base][1]):
                newest_local[base] = (path, meta)
        for base, (anchor, meta) in newest_local.items():
            newer = [
                s
                for s in siblings.values()
                if s.get("baseModel") == base and str(s.get("createdAt") or "") > _created(meta)
            ]
            if not newer:
                continue
            if decisions.is_ignored(model_id):
                counts["ignored"] += 1
                continue
            offered = [s for s in newer if not decisions.is_declined(model_id, s)]
            if not offered:
                counts["declined"] += 1
                continue
            offered.sort(key=lambda s: str(s.get("createdAt") or ""), reverse=True)
            model = meta.get("model") or {}
            parent = meta.get("parentModel") or {}
            candidates.append(
                Candidate(
                    model_id=model_id,
                    model_name=str(model.get("name") or parent.get("name") or model_id),
                    model_type=str(model.get("type") or parent.get("type") or ""),
                    base_model=str(base or ""),
                    anchor=anchor,
                    anchor_meta=meta,
                    local_version={
                        "id": meta.get("id"),
                        "name": meta.get("name"),
                        "createdAt": meta.get("createdAt"),
                    },
                    newer=offered,
                    patterns=scan_patterns(roots, anchor),
                    root=outermost(roots, anchor),
                    lora_root=outermost(roots, anchor, ADAPTER_TYPES),
                    local_hashes=hashes,
                )
            )
        if other_bases and not decisions.is_ignored(model_id):
            candidates.extend(
                _cross_base(
                    model_id, members, siblings, newest_local, other_bases, decisions, roots
                )
            )
    candidates.sort(key=lambda c: (c.cross_base, c.model_type != "LORA", c.model_name.lower()))
    return candidates, counts


def _cross_base(
    model_id: Any,
    members: List[Tuple[str, Dict[str, Any]]],
    siblings: Dict[Any, Dict[str, Any]],
    newest_local: Dict[Any, Tuple[str, Dict[str, Any]]],
    other_bases: set,
    decisions: UpdateDecisions,
    roots: List[Root],
) -> List[Candidate]:
    """Candidates for base models you use that this model has no local version of."""
    anchor, meta = max(members, key=lambda m: _created(m[1]))
    model = meta.get("model") or {}
    parent = meta.get("parentModel") or {}
    found = []
    by_base: Dict[str, List[Dict[str, Any]]] = {}
    for sibling in siblings.values():
        base = sibling.get("baseModel")
        if isinstance(base, str) and base in other_bases and base not in newest_local:
            by_base.setdefault(base, []).append(sibling)
    for base, versions in sorted(by_base.items()):
        offered = [s for s in versions if not decisions.is_declined(model_id, s)]
        if not offered:
            continue
        offered.sort(key=lambda s: str(s.get("createdAt") or ""), reverse=True)
        found.append(
            Candidate(
                model_id=model_id,
                model_name=str(model.get("name") or parent.get("name") or model_id),
                model_type=str(model.get("type") or parent.get("type") or ""),
                base_model=base,
                anchor=anchor,
                anchor_meta=meta,
                local_version={
                    "id": meta.get("id"),
                    "name": meta.get("name"),
                    "createdAt": meta.get("createdAt"),
                },
                newer=offered,
                patterns=scan_patterns(roots, anchor),
                root=outermost(roots, anchor),
                lora_root=outermost(roots, anchor, ADAPTER_TYPES),
                cross_base=True,
                from_base=str(meta.get("baseModel") or ""),
                local_hashes=_local_hashes(members),
            )
        )
    return found
