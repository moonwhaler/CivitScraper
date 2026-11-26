"""Analyse a library: fingerprints, classification, learned layout, suggestions."""

import json
import logging
import os
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from ..scanner.discovery import find_model_files, get_metadata_path
from .classifier import LABELLED, Classifier, Item, Verdict
from .decisions import KEEP, Decisions, decisions_path, file_key
from .fingerprint import fingerprint
from .layout import KEPT, STATE_CONFLICT, Layout, Root, Suggestion, roots_from_config

logger = logging.getLogger(__name__)


@dataclass
class Analysis:
    """Everything the sort job and the gallery need to know."""

    roots: List[Root]
    classifier: Classifier
    layout: Layout
    decisions: Decisions
    suggestions: List[Suggestion] = field(default_factory=list)
    keys: Dict[str, Optional[str]] = field(default_factory=dict)

    def by_path(self) -> Dict[str, Suggestion]:
        """Suggestions keyed by normalized path."""
        return {os.path.normcase(os.path.abspath(s.path)): s for s in self.suggestions}


def _load_sidecar(path: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sidecar = get_metadata_path(path, config)
    try:
        with open(sidecar, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def collect_items(config: Dict[str, Any], roots: List[Root]) -> List[Item]:
    """Every model file below the roots, fingerprinted, with its sidecar."""
    seen = set()
    items: List[Item] = []
    found = find_model_files(config, [r.path_id for r in roots], True)
    for files in found.values():
        for path in files:
            key = os.path.normcase(os.path.abspath(path))
            if key in seen:
                continue
            seen.add(key)
            items.append(Item(path, fingerprint(path), _load_sidecar(path, config)))
    return items


def overridden(verdict: Verdict, base: str, family: str) -> Verdict:
    """Replace a verdict by the user's remembered answer."""
    return replace(verdict, status=LABELLED, base=base, family=family, confidence="high")


def display_root(roots: List[Root]) -> str:
    """Return the roots' common parent; paths are shown relative to it."""
    parents = [os.path.dirname(r.path) for r in roots]
    if not parents:
        return ""
    try:
        return os.path.commonpath(parents)
    except ValueError:  # different drives
        return ""


def describe(suggestion: Suggestion) -> str:
    """One line on why a file looks misplaced."""
    verdict = suggestion.verdict
    if suggestion.state == STATE_CONFLICT:
        return f"CivitAI says {verdict.base}, the file looks like {verdict.file_base}"
    if verdict.status == LABELLED:
        return f"CivitAI says {verdict.base}"
    return f"The file looks like {verdict.base}"


def gallery_flags(config: Dict[str, Any], path_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Misplaced models for the gallery: normalized model path -> ``{to, why}``.

    ``to`` is the suggested folder relative to the roots' common parent (None for
    a conflict, which has two answers). Files the user chose to keep, broken
    files and VAE/text encoder suggestions are not flagged.
    """
    analysis = analyze(config, path_ids)
    base = display_root(analysis.roots)
    flags: Dict[str, Dict[str, Any]] = {}
    for suggestion in analysis.suggestions:
        if not suggestion.actionable or not suggestion.options:
            continue
        if any(option.report_only for option in suggestion.options):
            continue
        if suggestion.state == STATE_CONFLICT:
            to = None
        else:
            target_dir = suggestion.options[0].target_dir
            to = os.path.relpath(target_dir, base).replace(os.sep, "/") if base else target_dir
        flags[os.path.normcase(os.path.abspath(suggestion.path))] = {
            "to": to,
            "why": describe(suggestion),
        }
    return flags


def analyze(
    config: Dict[str, Any], path_ids: List[str], decisions: Optional[Decisions] = None
) -> Analysis:
    """Classify every file of the given input paths and suggest where it belongs."""
    roots = roots_from_config(config, path_ids)
    decisions = decisions or Decisions(decisions_path(config))
    items = collect_items(config, roots)
    classifier = Classifier(items)
    verdicts = classifier.classify_all()
    overrides = (config.get("sorting") or {}).get("base_folders") or {}
    layout = Layout(roots, classifier, verdicts, overrides, decisions.rules)
    analysis = Analysis(roots, classifier, layout, decisions)

    for verdict in verdicts:
        key = file_key(verdict.item, config) if decisions.files else None
        analysis.keys[verdict.path] = key
        decision = decisions.get(key)
        if decision and decision.get("decision") == KEEP:
            suggestion = layout.suggest(verdict)
            if suggestion.actionable:
                suggestion.state = KEPT
                suggestion.options = []
            analysis.suggestions.append(suggestion)
            continue
        if decision and decision.get("base") and decision.get("family"):
            verdict = overridden(verdict, str(decision["base"]), str(decision["family"]))
        analysis.suggestions.append(layout.suggest(verdict))
    return analysis
