"""Synthetic model libraries for the sorting tests (header-only safetensors files)."""

import json
import os
import struct
import time

import pytest

OLD = time.time() - 3600


def write_safetensors(path, tensors, metadata=None, mtime=OLD):
    """A safetensors file with the given tensor names/shapes (data is filler)."""
    header = {name: {"dtype": "F16", "shape": shape, "data_offsets": [0, 0]}
              for name, shape in tensors.items()}
    if metadata:
        header["__metadata__"] = metadata
    raw = json.dumps(header).encode()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(raw)) + raw + b"\0" * 64)
    os.utime(path, (mtime, mtime))
    return str(path)


def alpha_lora(seed=0):
    """Architecture 'Alpha': kohya-style names, width 2048."""
    t = {}
    for i in range(6):
        for mod in ("attn_q_proj", "attn_k_proj", "attn_v_proj", "attn_out_proj", "mlp_fc1",
                    "mlp_fc2", "norm1_linear", "norm2_linear", "adaln_mod"):
            t[f"lora_unet_blocks_{i}_{mod}.lora_down.weight"] = [16, 2048]
            t[f"lora_unet_blocks_{i}_{mod}.lora_up.weight"] = [2048, 16]
            t[f"lora_unet_blocks_{i}_{mod}.alpha"] = []
    if seed:
        t[f"lora_unet_blocks_0_extra{seed}.lora_down.weight"] = [8, 2048]
    return t


def beta_lora(seed=0):
    """Architecture 'Beta': PEFT-style names, width 3072."""
    t = {}
    for i in range(6):
        for mod in ("attention.to_q", "attention.to_k", "attention.to_v", "attention.to_out",
                    "feed_forward.w1", "feed_forward.w3", "adaln", "refiner.proj", "cap.embed"):
            t[f"diffusion_model.layers.{i}.{mod}.lora_A.weight"] = [16, 3072]
            t[f"diffusion_model.layers.{i}.{mod}.lora_B.weight"] = [3072, 16]
    if seed:
        t[f"diffusion_model.layers.0.extra{seed}.lora_A.weight"] = [8, 3072]
    return t


def delta_lora():
    """An architecture nobody has labels for."""
    return {f"transformer.h.{i}.mixer.in_proj.lora_A.weight": [8, 1536] for i in range(8)}


def checkpoint(width=2048):
    return {f"model.diffusion_model.blocks.{i}.attn.qkv.weight": [width * 3, width]
            for i in range(120)}


def vae():
    t = {f"encoder.down.{i}.conv.weight": [128, 128, 3, 3] for i in range(10)}
    t.update({f"decoder.up.{i}.conv.weight": [128, 128, 3, 3] for i in range(10)})
    return t


def text_encoder():
    t = {"model.embed_tokens.weight": [151000, 2560]}
    t.update({f"model.layers.{i}.self_attn.q_proj.weight": [2560, 2560] for i in range(36)})
    return t


def sidecar(model_path, base, model_type="LORA", version_id=None, **extra):
    """Write a CivitAI sidecar next to the model."""
    stem = os.path.splitext(model_path)[0]
    vid = version_id or abs(hash(model_path)) % 10**8
    data = {"id": vid, "modelId": vid + 1, "baseModel": base, "name": "v1",
            "model": {"name": os.path.basename(stem), "type": model_type},
            "files": [{"name": os.path.basename(model_path),
                       "hashes": {"SHA256": f"{vid:064x}"}}], **extra}
    with open(stem + ".json", "w") as f:
        json.dump(data, f)
    os.utime(stem + ".json", (OLD, OLD))
    return stem + ".json"


def companions(model_path, previews=2, html=True):
    stem = os.path.splitext(model_path)[0]
    made = []
    if html:
        with open(stem + ".html", "w") as f:
            f.write("<html></html>")
        made.append(stem + ".html")
    for n in range(1, previews + 1):
        ext = ".mp4" if n == 2 else ".jpeg"
        with open(f"{stem}.preview{n}{ext}", "wb") as f:
            f.write(f"preview {n}".encode())
        made.append(f"{stem}.preview{n}{ext}")
    return made


@pytest.fixture
def library(tmp_path):
    """
    models/Lora/{Alpha/style, Beta/concept, pre-sort}, models/unet/alpha, models/VAE

    Labelled: 4 Alpha LoRAs in Alpha/style, 4 Beta LoRAs in Beta/concept,
    2 Alpha checkpoints in unet/alpha.
    """
    models = tmp_path / "models"
    lora = models / "Lora"
    for n in range(4):
        p = write_safetensors(lora / "Alpha" / "style" / f"alpha{n}.safetensors", alpha_lora(n))
        sidecar(p, "Alpha", version_id=100 + n)
        p = write_safetensors(lora / "Beta" / "concept" / f"beta{n}.safetensors", beta_lora(n))
        sidecar(p, "Beta", version_id=200 + n)
    for n in range(2):
        p = write_safetensors(models / "unet" / "alpha" / f"ck{n}.safetensors", checkpoint())
        sidecar(p, "Alpha", "Checkpoint", version_id=300 + n)
    (models / "VAE").mkdir(parents=True)
    write_safetensors(models / "VAE" / "ae.safetensors", vae())
    config = {
        "input_paths": {
            "lora": {"path": str(lora), "type": "LORA", "patterns": ["*.safetensors"]},
            "unet": {"path": str(models / "unet"), "type": "Checkpoint",
                     "patterns": ["*.safetensors"]},
            "vae": {"path": str(models / "VAE"), "type": "VAE", "patterns": ["*.safetensors"]},
        },
        "scanner": {"cache_dir": str(tmp_path / "cache")},
        "sorting": {"decisions_file": str(tmp_path / "decisions.json"),
                    "krita": {"enabled": False}},
        "jobs": {"sort": {"type": "sort-models", "paths": ["lora", "unet", "vae"]}},
        "output": {"metadata": {"html": {"enabled": True}}},
    }
    return config, models


def tree(root):
    """Every file below root: relative path -> (inode, bytes)."""
    result = {}
    for dirpath, _, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            with open(full, "rb") as f:
                result[os.path.relpath(full, root)] = (os.stat(full).st_ino, f.read())
    return result


def dirs(root):
    return sorted(os.path.relpath(d, root) for d, _, _ in os.walk(root))
