"""
Pick the file of a new version that matches the one you have.

A version can offer several files: fp16 and fp32, full and pruned, safetensors
and pickle, GGUF quantizations. The new file should be the same variant as the
local one (format first, then GGUF quantization, precision and size), and it must
have an extension the folder is scanned for, or the next scan would not see it.
"""

import fnmatch
import os
import re
from typing import Any, Dict, List, Optional


def is_model_file(entry: Dict[str, Any]) -> bool:
    """Whether a file entry is the model itself (Model, Pruned Model, Diffusion Model…)."""
    kind = str(entry.get("type") or "").lower()
    return "model" in kind and "training" not in kind


_QUANT = re.compile(
    r"(?<![A-Za-z0-9])(Q[2-8]_K(?:_[SML])?|Q[2-8]_[01]|F16|BF16|F32)(?![A-Za-z0-9])"
)


def gguf_quant(name: str) -> Optional[str]:
    """Return the GGUF quantization named in a filename (``Q8_0``, ``Q4_K_M``…)."""
    match = _QUANT.search(name.upper())
    return match.group(1) if match else None


def local_entry(metadata: Dict[str, Any], local_name: str) -> Dict[str, Any]:
    """Return the sidecar's file entry for the local file (by name, else the primary one)."""
    files = [f for f in (metadata.get("files") or []) if isinstance(f, dict)]
    for entry in files:
        if entry.get("name") == local_name:
            return entry
    for entry in files:
        if entry.get("primary"):
            return entry
    return files[0] if files else {}


def matches_patterns(name: str, patterns: List[str]) -> bool:
    """Whether a filename matches any of a folder's scan patterns."""
    if not patterns:
        return True
    return any(fnmatch.fnmatch(name.lower(), p.lower()) for p in patterns)


def candidate_files(version: Dict[str, Any], patterns: List[str]) -> List[Dict[str, Any]]:
    """Model files of a version that the folder's scan patterns accept."""
    result = []
    for entry in version.get("files") or []:
        if not isinstance(entry, dict) or not is_model_file(entry):
            continue
        name = os.path.basename(str(entry.get("name") or ""))
        if name and matches_patterns(name, patterns):
            result.append(entry)
    return result


def _meta(entry: Dict[str, Any], key: str) -> Any:
    return (entry.get("metadata") or {}).get(key)


def score(entry: Dict[str, Any], local: Dict[str, Any], local_name: str) -> int:
    """How closely a file matches the local one (higher is closer)."""
    name = str(entry.get("name") or "")
    points = 0
    local_format = _meta(local, "format")
    if local_format and _meta(entry, "format") == local_format:
        points += 8
    if os.path.splitext(name)[1].lower() == os.path.splitext(local_name)[1].lower():
        points += 8
    local_quant = gguf_quant(local_name)
    if local_quant and gguf_quant(name) == local_quant:
        points += 4
    if _meta(local, "fp") and _meta(entry, "fp") == _meta(local, "fp"):
        points += 2
    if _meta(local, "size") and _meta(entry, "size") == _meta(local, "size"):
        points += 1
    if _meta(entry, "format") == "PickleTensor" and local_format != "PickleTensor":
        points -= 16
    return points


def rank_files(
    version: Dict[str, Any], metadata: Dict[str, Any], local_name: str, patterns: List[str]
) -> List[Dict[str, Any]]:
    """Files of ``version`` best match first (empty when none fits the folder)."""
    local = local_entry(metadata, local_name)
    files = candidate_files(version, patterns)
    return sorted(
        files,
        key=lambda e: (score(e, local, local_name), bool(e.get("primary"))),
        reverse=True,
    )


def describe_file(entry: Dict[str, Any]) -> str:
    """``SafeTensor fp16 pruned``-style label of a file."""
    parts = [str(_meta(entry, "format") or os.path.splitext(str(entry.get("name")))[1][1:])]
    quant = gguf_quant(str(entry.get("name") or ""))
    if quant:
        parts.append(quant)
    if _meta(entry, "fp"):
        parts.append(str(_meta(entry, "fp")))
    if _meta(entry, "size") == "pruned" or entry.get("type") == "Pruned Model":
        parts.append("pruned")
    return " ".join(p for p in parts if p and p != "None")
