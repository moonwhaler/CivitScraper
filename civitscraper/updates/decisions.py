"""
Remembered answers of the update walk-through.

"Not this version" is stored per version and also covers the older versions in
between (same model and base model, created no later), so declining v3 does not
bring back v2 on the next run. "Ignore this model" is stored per model.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Iterable, Optional, Set

from ..utils.fs import atomic_write

logger = logging.getLogger(__name__)

_FORMAT_VERSION = 1
SAME_FILE = "same_file"


def decisions_path(config: Dict[str, Any]) -> str:
    """``updates.decisions_file``, relative to the config file's directory."""
    configured = (config.get("updates") or {}).get("decisions_file") or "update-decisions.json"
    path = os.path.expanduser(str(configured))
    if not os.path.isabs(path):
        base = config.get("_config_dir") or os.getcwd()
        path = os.path.join(str(base), path)
    return os.path.abspath(path)


class UpdateDecisions:
    """Declined versions and ignored models, persisted as JSON."""

    def __init__(self, path: str, read_only: bool = False):
        """Load the decisions file (missing is fine); ``read_only`` never writes it."""
        self.path = path
        self.read_only = read_only
        self.versions: Dict[str, Dict[str, Any]] = {}
        self.models: Dict[str, Dict[str, Any]] = {}
        self._dirty = False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            logger.warning(f"Ignoring unreadable update decisions {path}: {e}")
            return
        if isinstance(data, dict):
            if isinstance(data.get("versions"), dict):
                self.versions = data["versions"]
            if isinstance(data.get("models"), dict):
                self.models = data["models"]

    @classmethod
    def for_config(cls, config: Dict[str, Any], read_only: bool = False) -> "UpdateDecisions":
        """Load the decisions of ``config``."""
        return cls(decisions_path(config), read_only)

    def decline(
        self, model_id: Any, version: Dict[str, Any], name: str, reason: Optional[str] = None
    ) -> None:
        """
        Remember "not this version" (and the older ones on its base model).

        With ``reason="same_file"`` (the version is a re-upload of a file you have)
        only this exact version is hidden, never the ones before it.
        """
        self.versions[str(version.get("id"))] = {
            "decision": "no",
            **({"reason": reason} if reason else {}),
            "model": model_id,
            "base": version.get("baseModel"),
            "created": version.get("createdAt"),
            "name": name,
            "at": int(time.time()),
        }
        self._dirty = True

    def ignore_model(self, model_id: Any, name: str) -> None:
        """Remember "never offer updates for this model"."""
        self.models[str(model_id)] = {"decision": "ignore", "name": name, "at": int(time.time())}
        self._dirty = True

    def is_ignored(self, model_id: Any) -> bool:
        """Whether updates of the model are ignored."""
        return model_id is not None and str(model_id) in self.models

    def is_declined(self, model_id: Any, version: Dict[str, Any]) -> bool:
        """Whether ``version`` (a sibling dict) was declined, directly or by a newer one."""
        if self.is_ignored(model_id):
            return True
        if str(version.get("id")) in self.versions:
            return True
        created = version.get("createdAt") or version.get("created_at") or ""
        base = version.get("baseModel", version.get("base_model"))
        for entry in self.versions.values():
            if entry.get("reason") == SAME_FILE:
                continue
            if str(entry.get("model")) != str(model_id) or entry.get("base") != base:
                continue
            if created and (entry.get("created") or "") >= created:
                return True
        return False

    def declined_ids(self, model_id: Any, versions: Iterable[Dict[str, Any]]) -> Set[Any]:
        """Version ids among gallery ``versions`` that are declined (for the update flag)."""
        result: Set[Any] = set()
        for version in versions:
            if version.get("is_local"):
                continue
            probe = {
                "id": version.get("version_id"),
                "createdAt": version.get("created_at"),
                "baseModel": version.get("base_model"),
            }
            if self.is_declined(model_id, probe):
                result.add(version.get("version_id"))
        return result

    def save(self) -> None:
        """Write the decisions file if anything changed."""
        if not self._dirty or self.read_only:
            return
        payload = json.dumps(
            {"version": _FORMAT_VERSION, "versions": self.versions, "models": self.models},
            indent=2,
            sort_keys=True,
        )
        atomic_write(self.path, payload + "\n")
        self._dirty = False


def load_if_present(config: Dict[str, Any]) -> Optional[UpdateDecisions]:
    """Load the decisions of ``config`` when its file exists (for the gallery)."""
    path = decisions_path(config)
    return UpdateDecisions(path) if os.path.isfile(path) else None
