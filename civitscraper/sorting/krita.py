"""
Keep Krita AI Diffusion's references to moved LoRAs working.

Krita stores LoRAs by their path relative to the LoRA folder
(``SDXL/concept/x.safetensors``), in ``database/loras.json`` and in the LoRA lists
of its styles (``styles/*.json``). After a move, every JSON string that *exactly*
equals an old relative path is replaced by the new one; nothing else is touched.
A timestamped backup of each changed file is written first.
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ..utils.fs import atomic_write

logger = logging.getLogger(__name__)


def _default_loras_file(config: Dict[str, Any]) -> Optional[str]:
    for job in (config.get("jobs") or {}).values():
        if isinstance(job, dict) and job.get("type") == "sync-lora-triggers":
            loras_file = job.get("loras_file")
            if isinstance(loras_file, str) and loras_file:
                return loras_file
    return None


def krita_running() -> bool:
    """Whether a Krita process is running (Linux /proc; False elsewhere)."""
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as f:
                if f.read().strip().lower().startswith("krita"):
                    return True
        except OSError:
            continue
    return False


def _variants(rel: str) -> List[str]:
    forward = rel.replace("\\", "/")
    return [forward, forward.replace("/", "\\")]


def _replace(value: Any, mapping: Dict[str, str]) -> Tuple[Any, int]:
    if isinstance(value, str):
        if value in mapping:
            return mapping[value], 1
        return value, 0
    if isinstance(value, list):
        changed = 0
        out = []
        for item in value:
            new, n = _replace(item, mapping)
            out.append(new)
            changed += n
        return out, changed
    if isinstance(value, dict):
        changed = 0
        result = {}
        for key, item in value.items():
            new, n = _replace(item, mapping)
            result[key] = new
            changed += n
        return result, changed
    return value, 0


def _indent(text: str) -> int:
    match = re.search(r"\n( +)\S", text)
    return len(match.group(1)) if match else 2


class KritaReferences:
    """Krita's LoRA database and styles."""

    def __init__(self, config: Dict[str, Any]):
        """Read the Krita settings (``sorting.krita``)."""
        settings = (config.get("sorting") or {}).get("krita") or {}
        self.enabled = bool(settings.get("enabled", True))
        loras_file = settings.get("loras_file") or _default_loras_file(config)
        self.loras_file = os.path.expanduser(loras_file) if loras_file else None
        styles_dir = settings.get("styles_dir")
        if not styles_dir and self.loras_file:
            styles_dir = os.path.join(os.path.dirname(os.path.dirname(self.loras_file)), "styles")
        self.styles_dir = os.path.expanduser(styles_dir) if styles_dir else None

    @property
    def available(self) -> bool:
        """Krita integration enabled and its LoRA database found."""
        return self.enabled and bool(self.loras_file) and os.path.isfile(str(self.loras_file))

    def files(self) -> List[str]:
        """Return Krita's JSON files that can reference LoRAs."""
        result = []
        if self.loras_file and os.path.isfile(self.loras_file):
            result.append(self.loras_file)
        if self.styles_dir and os.path.isdir(self.styles_dir):
            result.extend(
                os.path.join(self.styles_dir, n)
                for n in sorted(os.listdir(self.styles_dir))
                if n.endswith(".json")
            )
        return result

    def style_files(self) -> List[str]:
        """Return Krita's style files (``files()`` without ``loras.json``)."""
        return [p for p in self.files() if p != self.loras_file]

    def rewrite(
        self,
        renames: List[Tuple[str, str]],
        dry_run: bool = False,
        files: Optional[List[str]] = None,
    ) -> int:
        """
        Replace old relative LoRA paths by new ones.

        Args:
            renames: ``(old_rel, new_rel)`` pairs, relative to the LoRA folder
            dry_run: Count only
            files: Only these Krita files (default: ``loras.json`` and every style)

        Returns:
            Number of references changed
        """
        mapping: Dict[str, str] = {}
        for old, new in renames:
            for old_variant, new_variant in zip(_variants(old), _variants(new)):
                mapping[old_variant] = new_variant
        if not mapping:
            return 0
        stamp = time.strftime("%Y%m%d-%H%M%S")
        total = 0
        for path in self.files() if files is None else files:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                data = json.loads(text)
            except (OSError, ValueError) as e:
                logger.warning(f"Skipping unreadable Krita file {path}: {e}")
                continue
            new_data, changed = _replace(data, mapping)
            if not changed:
                continue
            total += changed
            if dry_run:
                continue
            atomic_write(f"{path}.bak-{stamp}", text)
            payload = json.dumps(new_data, indent=_indent(text), ensure_ascii=False)
            atomic_write(path, payload + ("\n" if text.endswith("\n") else ""))
            logger.info(f"Updated {changed} LoRA reference(s) in {path}")
        return total

    # --- Replacing one LoRA by another (update downloads) ---------------------

    def _load_loras(self) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
        if not self.available:
            return None
        try:
            with open(str(self.loras_file), "r", encoding="utf-8") as f:
                text = f.read()
            data = json.loads(text)
        except (OSError, ValueError) as e:
            logger.warning(f"Skipping unreadable Krita file {self.loras_file}: {e}")
            return None
        return (text, data) if isinstance(data, list) else None

    def _save_loras(self, text: str, data: List[Dict[str, Any]]) -> None:
        path = str(self.loras_file)
        atomic_write(f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}", text)
        payload = json.dumps(data, indent=_indent(text), ensure_ascii=False)
        atomic_write(path, payload + ("\n" if text.endswith("\n") else ""))

    def replace_entries(
        self, replacements: List[Tuple[str, str, Optional[str]]]
    ) -> List[Dict[str, Any]]:
        """
        Point ``loras.json`` entries of old LoRA files at their new versions.

        The old entry keeps its settings (strength, triggers…) and takes the new
        file's id; when Krita already has an entry for the new file, the settings
        it lacks are copied into it and the old entry is removed. A ``name`` is only
        changed while it is still Krita's default (the path without extension).

        Args:
            replacements: ``(old_rel, new_rel, trigger string or None)``

        Returns:
            Undo records: ``{"old": entry before, "new_id": .., "new_before": entry or None}``
        """
        loaded = self._load_loras()
        if loaded is None or not replacements:
            return []
        text, data = loaded
        records: List[Dict[str, Any]] = []
        for old_rel, new_rel, triggers in replacements:
            old_ids = set(_variants(old_rel))
            old = next((e for e in data if e.get("id") in old_ids), None)
            if old is None:
                continue
            new_ids = set(_variants(new_rel))
            existing = next((e for e in data if e.get("id") in new_ids), None)
            sep = "\\" if "\\" in str(old.get("id")) else "/"
            new_id = new_rel.replace("\\", "/").replace("/", sep)
            records.append(
                {
                    "old": json.loads(json.dumps(old)),
                    "new_id": new_id,
                    "new_before": json.loads(json.dumps(existing)) if existing else None,
                }
            )
            if existing is None:
                default_name = os.path.splitext(str(old.get("id")))[0]
                old["id"] = new_id
                if old.get("name") == default_name:
                    old["name"] = os.path.splitext(new_id)[0]
                target = old
            else:
                metadata = existing.setdefault("metadata", {})
                for key, value in (old.get("metadata") or {}).items():
                    metadata.setdefault(key, value)
                data.remove(old)
                target = existing
            if triggers:
                target.setdefault("metadata", {})["lora_triggers"] = triggers
        if records:
            self._save_loras(text, data)
            logger.info(f"Pointed {len(records)} Krita LoRA entr(ies) at new versions")
        return records

    def restore_entries(self, records: List[Dict[str, Any]]) -> int:
        """Undo :meth:`replace_entries` from its records."""
        loaded = self._load_loras()
        if loaded is None or not records:
            return 0
        text, data = loaded
        restored = 0
        for record in reversed(records):
            new_id = record.get("new_id")
            data[:] = [e for e in data if e.get("id") != new_id]
            if record.get("new_before"):
                data.append(record["new_before"])
            old = record.get("old")
            if old and not any(e.get("id") == old.get("id") for e in data):
                data.append(old)
                restored += 1
        if restored:
            self._save_loras(text, data)
        return restored
