"""
Decide each model file's real kind and base model.

Two independent sources are combined:

- **CivitAI**: the sidecar's ``model.type`` and ``baseModel``. The sidecar was
  matched by the file's hash, so it describes this exact file, but the base model
  is picked by the uploader and is sometimes wrong.
- **The file itself**: its tensor layout is compared with the files the library
  already has CivitAI labels for (k nearest neighbours, Jaccard similarity of the
  fingerprint tokens). Header training metadata (``ss_base_model_version``) is
  used as a hint once the labelled files show which base a value stands for.

Base models built on the same architecture (fine-tunes, renamed releases) cannot be
told apart by structure; they form a *structural family*, and structure then only
speaks for the family.
"""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from .fingerprint import (
    CHECKPOINT,
    EMBEDDING,
    FAMILY_ADAPTER,
    VAE,
    Fingerprint,
    similarity,
)

logger = logging.getLogger(__name__)

# Calibrated on a 618-file library (leave-one-out: 615 correct, the 3 misses were
# the only file of their base model).
K_NEIGHBOURS = 5
CONFIDENT_SHARE = 0.8
CONFIDENT_SIMILARITY = 0.5
MIN_SUPPORT = 3
HIGH_SHARE = 0.95
HIGH_SIMILARITY = 0.8
FAMILY_SIMILARITY = 0.9
FAMILY_FRACTION = 0.5
HINT_EXCLUSIVE = 0.95
HINT_MIN_FILES = 2

# Verdicts
LABELLED = "labelled"
CONFLICT = "conflict"
INFERRED = "inferred"
UNKNOWN = "unknown"
BROKEN = "broken"

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

CIVITAI_KINDS = {
    "lora": FAMILY_ADAPTER,
    "locon": FAMILY_ADAPTER,
    "lycoris": FAMILY_ADAPTER,
    "dora": FAMILY_ADAPTER,
    "checkpoint": CHECKPOINT,
    "textualinversion": EMBEDDING,
    "vae": VAE,
}

_HINT_KEYS = ("ss_base_model_version", "modelspec.architecture", "gguf.architecture")


def civitai_family(model_type: Any) -> Optional[str]:
    """Kind family of a CivitAI ``model.type`` (None for types not sorted)."""
    return CIVITAI_KINDS.get(str(model_type or "").lower())


def has_civitai_data(metadata: Optional[Dict[str, Any]]) -> bool:
    """Tell whether a sidecar comes from CivitAI (Forge-only ones have no model id)."""
    if not metadata:
        return False
    return bool(metadata.get("modelId") or metadata.get("id"))


@dataclass(frozen=True)
class Item:
    """A model file with its fingerprint and sidecar (None when it has none)."""

    path: str
    fingerprint: Fingerprint
    metadata: Optional[Dict[str, Any]] = None

    @property
    def civitai_base(self) -> Optional[str]:
        """Base model from the CivitAI sidecar (None without CivitAI data)."""
        if not has_civitai_data(self.metadata):
            return None
        base = (self.metadata or {}).get("baseModel")
        return str(base) if base else None

    @property
    def civitai_type(self) -> Optional[str]:
        """Model type from the CivitAI sidecar (None without CivitAI data)."""
        if not has_civitai_data(self.metadata):
            return None
        model_type = ((self.metadata or {}).get("model") or {}).get("type")
        return str(model_type) if model_type else None


@dataclass(frozen=True)
class Vote:
    """What the nearest labelled files say about a file's base model."""

    base: str
    share: float
    similarity: float
    support: int
    runner_up: Optional[Tuple[str, float]] = None

    @property
    def confident(self) -> bool:
        """Strong enough to stand on its own."""
        return (
            self.share >= CONFIDENT_SHARE
            and self.similarity >= CONFIDENT_SIMILARITY
            and self.support >= MIN_SUPPORT
        )


@dataclass
class Verdict:
    """The classifier's answer for one file."""

    item: Item
    status: str
    base: Optional[str] = None  # the base model the file is sorted by
    family: Optional[str] = None  # kind family the file is sorted by
    confidence: str = LOW
    vote: Optional[Vote] = None
    hint: Optional[str] = None
    hint_base: Optional[str] = None
    structural_family: FrozenSet[str] = frozenset()
    # Conflicts: what the file itself says, when it disagrees with CivitAI.
    file_base: Optional[str] = None
    file_family: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        """Model file path."""
        return self.item.path


class Classifier:
    """Classify every file of a library against its labelled files."""

    def __init__(self, items: List[Item]):
        """Learn from the labelled files among ``items``."""
        self.items = items
        self._pool: Dict[str, List[Item]] = defaultdict(list)
        self._support: Dict[Tuple[str, str], int] = Counter()
        for item in items:
            family = item.fingerprint.family
            base = item.civitai_base
            if family and base and not item.fingerprint.broken:
                self._pool[family].append(item)
                self._support[(family, base)] += 1
        self._family_of: Dict[Tuple[str, str], FrozenSet[str]] = {}
        self._build_families()
        self._hint_bases = self._learn_hints()

    # --- Learning -----------------------------------------------------------------

    def _neighbours(self, item: Item, family: str) -> List[Tuple[float, Item]]:
        tokens = item.fingerprint.tokens
        scored = [
            (similarity(tokens, other.fingerprint.tokens), other)
            for other in self._pool.get(family, [])
            if other.path != item.path
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored

    def _build_families(self) -> None:
        """Union base models whose files cannot be told apart by structure."""
        for family, pool in self._pool.items():
            parent: Dict[str, str] = {}

            def find(base: str) -> str:
                parent.setdefault(base, base)
                while parent[base] != base:
                    parent[base] = parent[parent[base]]
                    base = parent[base]
                return base

            by_base: Dict[str, List[Item]] = defaultdict(list)
            for item in pool:
                by_base[str(item.civitai_base)].append(item)
                find(str(item.civitai_base))

            for base, files in by_base.items():
                twins: Counter = Counter()
                for item in files:
                    neighbours = self._neighbours(item, family)
                    if not neighbours:
                        continue
                    sim, nearest = neighbours[0]
                    other = str(nearest.civitai_base)
                    if other != base and sim >= FAMILY_SIMILARITY:
                        twins[other] += 1
                for other, count in twins.items():
                    if count >= FAMILY_FRACTION * len(files):
                        parent[find(base)] = find(other)

            groups: Dict[str, set] = defaultdict(set)
            for base in by_base:
                groups[find(base)].add(base)
            for members in groups.values():
                frozen = frozenset(members)
                if len(frozen) > 1:
                    logger.debug(f"Structurally identical base models: {sorted(frozen)}")
                for base in members:
                    self._family_of[(family, base)] = frozen

    def _learn_hints(self) -> Dict[str, str]:
        """Header hint value -> base model, when the labelled files agree on it."""
        seen: Dict[str, Counter] = defaultdict(Counter)
        for pool in self._pool.values():
            for item in pool:
                hint = self.hint_of(item.fingerprint)
                if hint:
                    seen[hint][str(item.civitai_base)] += 1
        mapping = {}
        for hint, bases in seen.items():
            base, count = bases.most_common(1)[0]
            total = sum(bases.values())
            if total >= HINT_MIN_FILES and count >= HINT_EXCLUSIVE * total:
                mapping[hint] = base
        return mapping

    # --- Queries ------------------------------------------------------------------

    @staticmethod
    def hint_of(fp: Fingerprint) -> Optional[str]:
        """Return the header's base model hint, lower case."""
        for key in _HINT_KEYS:
            value = fp.hints.get(key)
            if value:
                return value.lower()
        return None

    def structural_family(self, family: Optional[str], base: Optional[str]) -> FrozenSet[str]:
        """Return the base models structurally identical to ``base`` (with ``base``)."""
        if not base:
            return frozenset()
        if not family:
            return frozenset({base})
        return self._family_of.get((family, base), frozenset({base}))

    def support(self, family: str, base: str) -> int:
        """Return how many labelled files of ``base`` the kind family has."""
        return int(self._support.get((family, base), 0))

    def bases(self, family: str) -> List[str]:
        """Labelled base models of a kind family, most files first."""
        counts = Counter({b: n for (f, b), n in self._support.items() if f == family})
        return [b for b, _ in counts.most_common()]

    def vote(self, item: Item) -> Optional[Vote]:
        """Ask the nearest labelled files of the same kind which base this file is."""
        family = item.fingerprint.family
        if not family or not item.fingerprint.tokens:
            return None
        neighbours = self._neighbours(item, family)[:K_NEIGHBOURS]
        neighbours = [(s, o) for s, o in neighbours if s > 0]
        if not neighbours:
            return None
        weights: Dict[str, float] = defaultdict(float)
        best_sim: Dict[str, float] = {}
        for sim, other in neighbours:
            base = str(other.civitai_base)
            weights[base] += sim
            best_sim[base] = max(best_sim.get(base, 0.0), sim)
        total = sum(weights.values())
        ranked = sorted(weights.items(), key=lambda pair: pair[1], reverse=True)
        base = ranked[0][0]
        runner_up = (ranked[1][0], ranked[1][1] / total) if len(ranked) > 1 else None
        # Votes inside one structural family count for the winner's family.
        family_bases = self.structural_family(family, base)
        family_weight = sum(w for b, w in ranked if b in family_bases)
        return Vote(
            base=base,
            share=family_weight / total,
            similarity=best_sim[base],
            support=sum(self.support(family, b) for b in family_bases),
            runner_up=runner_up,
        )

    def classify(self, item: Item) -> Verdict:
        """Combine CivitAI data, structure and header hints into a verdict."""
        fp = item.fingerprint
        if fp.broken:
            return Verdict(item, BROKEN, notes=[fp.broken])

        civitai_base = item.civitai_base
        civitai_kind = civitai_family(item.civitai_type)
        file_family = fp.family
        vote = self.vote(item) if file_family else None
        hint = self.hint_of(fp)
        hint_base = self._hint_bases.get(hint) if hint else None

        verdict = Verdict(item, UNKNOWN, vote=vote, hint=hint, hint_base=hint_base)

        if civitai_base:
            family = civitai_kind or file_family
            verdict.base = civitai_base
            verdict.structural_family = self.structural_family(family, civitai_base)
            if civitai_kind and file_family and civitai_kind != file_family:
                verdict.status = CONFLICT
                verdict.family = civitai_kind
                verdict.file_family = file_family
                verdict.file_base = vote.base if vote and vote.confident else civitai_base
                return verdict
            if (
                vote
                and vote.confident
                and civitai_base not in self.structural_family(file_family, vote.base)
            ):
                verdict.status = CONFLICT
                verdict.family = family
                verdict.file_family = family
                verdict.file_base = vote.base
                return verdict
            verdict.status = LABELLED
            verdict.family = family
            verdict.confidence = HIGH
            return verdict

        verdict.family = file_family
        if not file_family:
            verdict.notes.append("file kind not recognised")
            return verdict

        if vote and vote.confident:
            family_bases = self.structural_family(file_family, vote.base)
            if hint_base and hint_base not in family_bases:
                verdict.base = vote.base
                verdict.notes.append(f"header says {hint_base}")
                return verdict
            verdict.status = INFERRED
            verdict.base = vote.base
            verdict.structural_family = family_bases
            single = len(family_bases) == 1
            strong = hint_base == vote.base or (
                vote.share >= HIGH_SHARE and vote.similarity >= HIGH_SIMILARITY
            )
            verdict.confidence = HIGH if single and strong else MEDIUM
            return verdict

        if hint_base and (not vote or vote.base in self.structural_family(file_family, hint_base)):
            verdict.status = INFERRED
            verdict.base = hint_base
            verdict.structural_family = self.structural_family(file_family, hint_base)
            verdict.confidence = MEDIUM
            return verdict

        verdict.base = vote.base if vote else hint_base
        if verdict.base:
            verdict.structural_family = self.structural_family(file_family, verdict.base)
        return verdict

    def classify_all(self) -> List[Verdict]:
        """Classify every item."""
        return [self.classify(item) for item in self.items]
