"""
Structural fingerprint of a model file, read from its header only.

Safetensors files start with an 8-byte length and a JSON header listing every
tensor's name and shape, plus optional training metadata (``__metadata__``). GGUF
files carry the same in a binary key/value header. Nothing beyond the header is
read, and pickle-based formats (``.pt``, ``.ckpt``, ``.bin``) are never opened:
unpickling runs code.
"""

import json
import logging
import os
import re
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_HEADER_BYTES = 100 * 1024 * 1024
MAX_GGUF_ITEMS = 100_000

# Kinds
LORA = "lora"
LOKR = "lokr"
LOHA = "loha"
CHECKPOINT = "checkpoint"
VAE = "vae"
TEXT_ENCODER = "text_encoder"
EMBEDDING = "embedding"
UNKNOWN = "unknown"

ADAPTER_KINDS = frozenset({LORA, LOKR, LOHA})

# Kind family: what folder type a kind belongs in.
FAMILY_ADAPTER = "adapter"


def kind_family(kind: Optional[str]) -> Optional[str]:
    """Adapters share one family; other known kinds are their own family."""
    if kind in ADAPTER_KINDS:
        return FAMILY_ADAPTER
    if kind in (CHECKPOINT, VAE, TEXT_ENCODER, EMBEDDING):
        return kind
    return None


# Tokens that say how a tensor is stored, not which module it belongs to.
_DROP_TOKENS = frozenset(
    {
        "lora",
        "unet",
        "transformer",
        "diffusion",
        "model",
        "base",
        "te",
        "text",
        "encoder",
        "down",
        "up",
        "a",
        "b",
        "alpha",
        "weight",
        "bias",
        "lokr",
        "hada",
        "dora",
        "scale",
        "diff",
        "w1",
        "w2",
        "w1a",
        "w1b",
        "w2a",
        "w2b",
        "t1",
        "t2",
        "default",
        "lycoris",
        "oft",
        "blocks",
        "magnitude",
        "vector",
    }
)
_SPLIT = re.compile(r"[._]")
_MIN_DIM = 256
_TOP_DIMS = 3
_MIN_CHECKPOINT_TENSORS = 100

_BUNDLED_PREFIXES = (
    "first_stage_model.",
    "cond_stage_model.",
    "conditioner.",
    "text_encoders.",
    "vae.",
)
_TEXT_ENCODER_MARKERS = (
    "embed_tokens",
    "token_embedding",
    "shared.weight",
    "text_model.",
    "lm_head",
    "language_model.",
    "wte.weight",
)
_TEXT_ENCODER_PREFIXES = (
    "model.",
    "text_model.",
    "encoder.",
    "shared.",
    "transformer.",
    "lm_head",
    "mtp.",
    "visual.",
    "language_model.",
    "text_encoders.",
    "embeddings.",
)
_EMBEDDING_KEYS = frozenset({"emb_params", "clip_l", "clip_g", "string_to_token"})


@dataclass(frozen=True)
class Fingerprint:
    """What a model file's header says about it."""

    path: str
    kind: str = UNKNOWN
    tokens: FrozenSet[str] = frozenset()
    hints: Dict[str, str] = field(default_factory=dict)
    bundled: bool = False
    tensor_count: int = 0
    broken: Optional[str] = None  # why the file cannot be read (0 bytes, bad header)
    header_bytes: bytes = b""  # raw header, for a content-based identity

    @property
    def family(self) -> Optional[str]:
        """Kind family of the file; all adapters share one."""
        return kind_family(self.kind)


def _tensor_kind(names: List[str]) -> Tuple[str, bool]:
    """Detect the kind from tensor names; second value: bundled checkpoint."""
    lowered = [n.lower() for n in names]
    adapters: Counter = Counter()
    for name in lowered:
        if "lora_down" in name or "lora_up" in name or ".lora_a" in name or ".lora_b" in name:
            adapters[LORA] += 1
        elif "lokr_w" in name:
            adapters[LOKR] += 1
        elif "hada_w" in name:
            adapters[LOHA] += 1
    if adapters:
        return adapters.most_common(1)[0][0], False

    if names and len(names) <= 8:
        roots = {n.split(".", 1)[0] for n in lowered}
        if roots <= _EMBEDDING_KEYS | {"string_to_param"} or any(
            n.startswith("string_to_param") for n in lowered
        ):
            return EMBEDDING, False

    total = len(lowered)
    if any(m in name for name in lowered for m in _TEXT_ENCODER_MARKERS):
        language = sum(1 for n in lowered if n.startswith(_TEXT_ENCODER_PREFIXES))
        if language >= 0.9 * total:
            return TEXT_ENCODER, False

    def head(name: str) -> str:
        return ".".join(name.split(".")[:2])

    dec = sum(1 for n in lowered if "decoder" in head(n) or "vocoder" in head(n))
    enc = sum(1 for n in lowered if "encoder" in head(n) and "decoder" not in head(n))
    # Encoder/decoder pairs, decoder-only (tiny) VAEs and audio VAEs with a vocoder.
    if total and dec >= 0.1 * total and (enc + dec) >= 0.6 * total:
        return VAE, False

    if total >= _MIN_CHECKPOINT_TENSORS:
        bundled = any(n.startswith(_BUNDLED_PREFIXES) for n in lowered) and any(
            "diffusion_model" in n for n in lowered
        )
        return CHECKPOINT, bundled
    return UNKNOWN, False


def _tokens(shapes: Dict[str, List[int]]) -> FrozenSet[str]:
    """Collect normalized module names plus the dominant large dimensions."""
    modules = set()
    dims: Counter = Counter()
    for name, shape in shapes.items():
        parts = [
            t for t in _SPLIT.split(name.lower()) if t and not t.isdigit() and t not in _DROP_TOKENS
        ]
        modules.add("m:" + ".".join(parts))
        for d in shape:
            if isinstance(d, int) and d >= _MIN_DIM:
                dims[d] += 1
    top = [d for d, _ in dims.most_common(_TOP_DIMS)]
    return frozenset(modules | {f"d:{d}" for d in top})


def _hints(metadata: Dict[str, Any]) -> Dict[str, str]:
    hints: Dict[str, str] = {}
    for key in ("ss_base_model_version", "modelspec.architecture", "ss_network_module"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            hints[key] = value.strip()[:120]
    software = metadata.get("software")
    if isinstance(software, str):
        try:
            name = json.loads(software).get("name")
        except (ValueError, AttributeError):
            name = None
        if isinstance(name, str):
            hints["trainer"] = name[:60]
    return hints


def _fingerprint_safetensors(path: str) -> Fingerprint:
    with open(path, "rb") as f:
        raw = f.read(8)
        if len(raw) < 8:
            return Fingerprint(path, broken="empty or truncated file")
        (length,) = struct.unpack("<Q", raw)
        if length <= 0 or length > MAX_HEADER_BYTES:
            return Fingerprint(path, broken="invalid safetensors header")
        data = f.read(length)
    if len(data) < length:
        return Fingerprint(path, broken="truncated safetensors header")
    try:
        header = json.loads(data)
    except ValueError:
        return Fingerprint(path, broken="unreadable safetensors header")
    if not isinstance(header, dict):
        return Fingerprint(path, broken="unreadable safetensors header")
    metadata = header.pop("__metadata__", None) or {}
    shapes = {k: v.get("shape", []) if isinstance(v, dict) else [] for k, v in header.items()}
    kind, bundled = _tensor_kind(list(shapes))
    return Fingerprint(
        path,
        kind=kind,
        tokens=_tokens(shapes),
        hints=_hints(metadata if isinstance(metadata, dict) else {}),
        bundled=bundled,
        tensor_count=len(shapes),
        header_bytes=data,
    )


# --- GGUF -------------------------------------------------------------------------

_GGUF_SCALARS = {
    0: "<B",
    1: "<b",
    2: "<H",
    3: "<h",
    4: "<I",
    5: "<i",
    6: "<f",
    7: "<?",
    10: "<Q",
    11: "<q",
    12: "<d",
}


class _Reader:
    def __init__(self, f):
        self.f = f
        self.consumed = bytearray()

    def read(self, n: int) -> bytes:
        if n < 0 or n > MAX_HEADER_BYTES or len(self.consumed) + n > MAX_HEADER_BYTES:
            raise ValueError("GGUF header too large")
        data: bytes = self.f.read(n)
        if len(data) < n:
            raise ValueError("truncated GGUF header")
        self.consumed.extend(data)
        return data

    def unpack(self, fmt: str) -> Any:
        return struct.unpack(fmt, self.read(struct.calcsize(fmt)))[0]

    def string(self) -> str:
        return self.read(self.unpack("<Q")).decode("utf-8", "replace")

    def value(self, vtype: int) -> Any:
        if vtype in _GGUF_SCALARS:
            return self.unpack(_GGUF_SCALARS[vtype])
        if vtype == 8:
            return self.string()
        if vtype == 9:
            item_type = self.unpack("<I")
            count = self.unpack("<Q")
            if count > MAX_GGUF_ITEMS * 10:
                raise ValueError("GGUF array too large")
            items = [self.value(item_type) for _ in range(count)]
            return items if item_type == 8 and count <= 16 else None
        raise ValueError(f"unknown GGUF value type {vtype}")


def _fingerprint_gguf(path: str) -> Fingerprint:
    with open(path, "rb") as f:
        r = _Reader(f)
        try:
            if r.read(4) != b"GGUF":
                return Fingerprint(path, broken="invalid GGUF header")
            version = r.unpack("<I")
            count_fmt = "<I" if version == 1 else "<Q"
            tensor_count = r.unpack(count_fmt)
            kv_count = r.unpack(count_fmt)
            if tensor_count > MAX_GGUF_ITEMS or kv_count > MAX_GGUF_ITEMS:
                return Fingerprint(path, broken="invalid GGUF header")
            metadata: Dict[str, Any] = {}
            for _ in range(kv_count):
                key = r.string()
                metadata[key] = r.value(r.unpack("<I"))
            shapes: Dict[str, List[int]] = {}
            for _ in range(tensor_count):
                name = r.string()
                n_dims = r.unpack("<I")
                if n_dims > 8:
                    raise ValueError("invalid GGUF tensor")
                dims = [r.unpack("<Q") for _ in range(n_dims)]
                r.unpack("<I")  # tensor type
                r.unpack("<Q")  # offset
                shapes[name] = dims
        except (ValueError, struct.error) as e:
            return Fingerprint(path, broken=f"unreadable GGUF header ({e})")
    kind, bundled = _tensor_kind(list(shapes))
    hints = {}
    arch = metadata.get("general.architecture")
    if isinstance(arch, str):
        hints["gguf.architecture"] = arch[:60]
    return Fingerprint(
        path,
        kind=kind,
        tokens=_tokens(shapes),
        hints=hints,
        bundled=bundled,
        tensor_count=len(shapes),
        header_bytes=bytes(r.consumed),
    )


def fingerprint(path: str) -> Fingerprint:
    """
    Read a model file's header.

    Returns a Fingerprint whose ``broken`` is set when the file is empty or its
    header cannot be read. Formats without a readable header (pickles) get kind
    ``unknown`` and no tokens.
    """
    ext = os.path.splitext(path)[1].lower()
    try:
        if os.path.getsize(path) <= 8:
            return Fingerprint(path, broken="empty or truncated file")
        if ext == ".safetensors":
            return _fingerprint_safetensors(path)
        if ext == ".gguf":
            return _fingerprint_gguf(path)
    except OSError as e:
        return Fingerprint(path, broken=f"unreadable ({e.strerror or e})")
    return Fingerprint(path)


def similarity(a: FrozenSet[str], b: FrozenSet[str]) -> float:
    """Jaccard similarity of two token sets."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
