"""
The base models you use, learned from your folders (like the sort job).

A base model counts as used when one of your adapter or checkpoint folders holds
it: a folder where most labelled files are of that base, a ``sorting.base_folders``
entry, or a folder rule you saved in the sort walk-through. ``updates.base_models``
adds bases (a list, or ``{add: [...], skip: [...]}``) or leaves some out.

The layout learned here also says where a version for another base model goes:
that base's folder, with your category folders kept.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set

from ..sorting.analysis import Analysis, analyze
from ..sorting.fingerprint import CHECKPOINT, FAMILY_ADAPTER
from ..sorting.layout import IGNORED_BASES, normalize_name

logger = logging.getLogger(__name__)

_FAMILIES = (FAMILY_ADAPTER, CHECKPOINT)


@dataclass
class UsedBases:
    """Base models you use, and the folder layout they were learned from."""

    bases: FrozenSet[str] = frozenset()
    analysis: Optional[Analysis] = None
    learned: Set[str] = field(default_factory=set)

    def __contains__(self, base: object) -> bool:
        """Whether ``base`` is a base model you use."""
        return isinstance(base, str) and base in self.bases


def _setting(config: Dict[str, Any]) -> Dict[str, List[str]]:
    raw = (config.get("updates") or {}).get("base_models")
    if isinstance(raw, list):
        return {"add": [str(b) for b in raw], "skip": []}
    if isinstance(raw, dict):
        return {
            "add": [str(b) for b in raw.get("add") or []],
            "skip": [str(b) for b in raw.get("skip") or []],
        }
    return {"add": [], "skip": []}


def used_bases(config: Dict[str, Any], analysis: Optional[Analysis] = None) -> UsedBases:
    """
    Learn the base models you use from every configured input path.

    Args:
        config: Configuration (all ``input_paths`` are looked at)
        analysis: An analysis over all input paths to reuse, if there is one
    """
    if analysis is None:
        path_ids = list((config.get("input_paths") or {}).keys())
        analysis = analyze(config, path_ids)
    layout = analysis.layout
    learned: Set[str] = set()
    for root in analysis.roots:
        if root.family not in _FAMILIES:
            continue
        for base in {str(v.base) for v in layout.verdicts if v.base}:
            if layout.folder_for(root, base):
                learned.add(base)
        for (family, base), _folder in getattr(layout, "_fixed", {}).items():
            if family == root.family and layout.folder_for(root, base):
                learned.add(base)
    setting = _setting(config)
    skip = {normalize_name(b) for b in setting["skip"]}
    bases = {b for b in learned | set(setting["add"]) if normalize_name(b) not in skip}
    bases = {b for b in bases if b.lower() not in IGNORED_BASES}
    return UsedBases(frozenset(bases), analysis, learned)
