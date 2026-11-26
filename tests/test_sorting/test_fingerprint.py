"""Header fingerprints: kinds, hints, broken files, no pickles."""

import struct

from civitscraper.sorting.fingerprint import (
    CHECKPOINT,
    EMBEDDING,
    LOKR,
    LORA,
    TEXT_ENCODER,
    UNKNOWN,
    VAE,
    fingerprint,
    similarity,
)

from .conftest import alpha_lora, beta_lora, checkpoint, text_encoder, vae, write_safetensors


def test_kinds_are_detected(tmp_path):
    cases = {
        "lora": (alpha_lora(), LORA),
        "peft": (beta_lora(), LORA),
        "lokr": ({f"lycoris_blocks_{i}_attn.lokr_w1": [4, 4] for i in range(4)}, LOKR),
        "ckpt": (checkpoint(), CHECKPOINT),
        "vae": (vae(), VAE),
        "te": (text_encoder(), TEXT_ENCODER),
        "emb": ({"emb_params": [4, 768]}, EMBEDDING),
        "tiny": ({"diffusion_model.txtfusion.norm.weight": [2048]}, UNKNOWN),
    }
    for name, (tensors, kind) in cases.items():
        fp = fingerprint(write_safetensors(tmp_path / f"{name}.safetensors", tensors))
        assert fp.kind == kind, name
        assert fp.broken is None


def test_bundled_checkpoint(tmp_path):
    tensors = checkpoint()
    tensors["first_stage_model.decoder.conv_in.weight"] = [512, 4, 3, 3]
    fp = fingerprint(write_safetensors(tmp_path / "full.safetensors", tensors))
    assert fp.kind == CHECKPOINT and fp.bundled


def test_hints_from_training_metadata(tmp_path):
    meta = {"ss_base_model_version": "alpha_v1", "software": '{"name": "ai-toolkit"}'}
    fp = fingerprint(write_safetensors(tmp_path / "a.safetensors", alpha_lora(), meta))
    assert fp.hints["ss_base_model_version"] == "alpha_v1"
    assert fp.hints["trainer"] == "ai-toolkit"


def test_empty_and_garbage_files_are_broken(tmp_path):
    (tmp_path / "empty.safetensors").write_bytes(b"")
    (tmp_path / "bad.safetensors").write_bytes(struct.pack("<Q", 10) + b"not json!!")
    (tmp_path / "huge.safetensors").write_bytes(struct.pack("<Q", 2**40) + b"x" * 10)
    for name in ("empty", "bad", "huge"):
        assert fingerprint(str(tmp_path / f"{name}.safetensors")).broken, name


def test_pickle_formats_are_never_opened(tmp_path, monkeypatch):
    path = tmp_path / "model.ckpt"
    path.write_bytes(b"\x80\x04" + b"x" * 100)
    opened = []
    real_open = open

    def spy(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy)
    fp = fingerprint(str(path))
    assert fp.kind == UNKNOWN and not fp.tokens and fp.broken is None
    assert str(path) not in opened


def _gguf(tensors, arch="alpha"):
    def string(s):
        b = s.encode()
        return struct.pack("<Q", len(b)) + b

    out = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), 1)
    out += string("general.architecture") + struct.pack("<I", 8) + string(arch)
    for name, shape in tensors.items():
        out += string(name) + struct.pack("<I", len(shape))
        out += b"".join(struct.pack("<Q", d) for d in shape) + struct.pack("<IQ", 1, 0)
    return out + b"\0" * 32


def test_gguf_header(tmp_path):
    path = tmp_path / "model.gguf"
    path.write_bytes(_gguf(checkpoint()))
    fp = fingerprint(str(path))
    assert fp.kind == CHECKPOINT
    assert fp.hints["gguf.architecture"] == "alpha"


def test_same_architecture_is_similar(tmp_path):
    a1 = fingerprint(write_safetensors(tmp_path / "a1.safetensors", alpha_lora(1)))
    a2 = fingerprint(write_safetensors(tmp_path / "a2.safetensors", alpha_lora(2)))
    b1 = fingerprint(write_safetensors(tmp_path / "b1.safetensors", beta_lora(1)))
    assert similarity(a1.tokens, a2.tokens) > 0.7
    assert similarity(a1.tokens, b1.tokens) < 0.1
