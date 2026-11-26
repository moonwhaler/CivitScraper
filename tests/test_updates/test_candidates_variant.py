"""Finding updates (same base model, decisions) and picking the matching file."""

from civitscraper.updates.candidates import (
    EARLY_ACCESS,
    FREE,
    GENERATION_ONLY,
    PAID,
    access_state,
    find_candidates,
)
from civitscraper.updates.decisions import UpdateDecisions, decisions_path
from civitscraper.updates.variant import gguf_quant, rank_files

from .conftest import sibling, write_model


def candidates(config):
    found, counts = find_candidates(config, ["lora"], UpdateDecisions.for_config(config))
    return {c.model_id: c for c in found}, counts


def test_newer_versions_on_the_same_base_only(library):
    config, *_ = library
    found, _ = candidates(config)
    assert set(found) == {100, 300}  # 200 is up to date
    foo = found[100]
    assert [s["id"] for s in foo.newer] == [13, 12]  # the SDXL v14 is not an update
    assert foo.target["id"] == 13


def test_declining_a_version_also_declines_older_ones(library):
    config, *_ = library
    decisions = UpdateDecisions.for_config(config)
    decisions.decline(100, sibling(13, "2026-03-01"), "foo")
    decisions.save()
    found, counts = candidates(config)
    assert 100 not in found and counts["declined"] == 1
    assert decisions_path(config).endswith("update-decisions.json")


def test_ignored_models_and_removed_models_are_skipped(library):
    config, models, *_ = library
    decisions = UpdateDecisions.for_config(config)
    decisions.ignore_model(300, "baz")
    decisions.save()
    write_model(
        models / "Lora" / "Flux" / "gone.safetensors",
        41,
        400,
        "Flux.1 D",
        [sibling(41, "2026-01-01"), sibling(42, "2026-02-01")],
        "2026-01-01",
        civitscraper={"removed": {"what": "model"}},
    )
    found, counts = candidates(config)
    assert set(found) == {100} and counts["ignored"] == 1


def test_access_states():
    assert access_state({})[0] == FREE
    assert access_state({"earlyAccessEndsAt": "2099-01-01T00:00:00Z"}) == (
        EARLY_ACCESS,
        "2099-01-01T00:00:00Z",
    )
    assert access_state({"earlyAccessEndsAt": "2000-01-01T00:00:00Z"})[0] == FREE
    assert access_state({"paidAccess": {"permanent": True, "endsAt": None}})[0] == PAID
    assert access_state({"usageControl": "Generation"})[0] == GENERATION_ONLY


def _files(*entries):
    return {"files": [dict(type=t, name=n, primary=p, metadata=m) for n, t, p, m in entries]}


def test_the_same_variant_as_the_local_file_wins():
    local = {
        "files": [
            {
                "name": "a.safetensors",
                "metadata": {"format": "SafeTensor", "fp": "fp16", "size": "pruned"},
            }
        ]
    }
    version = _files(
        ("b_fp32.safetensors", "Model", True, {"format": "SafeTensor", "fp": "fp32"}),
        (
            "b_fp16.safetensors",
            "Pruned Model",
            False,
            {"format": "SafeTensor", "fp": "fp16", "size": "pruned"},
        ),
        ("b.pt", "Model", False, {"format": "PickleTensor", "fp": "fp16", "size": "pruned"}),
        ("train.zip", "Training Data", False, {}),
    )
    ranked = rank_files(version, local, "a.safetensors", ["*.safetensors", "*.pt"])
    assert [f["name"] for f in ranked] == ["b_fp16.safetensors", "b_fp32.safetensors", "b.pt"]


def test_gguf_quantization_and_folder_patterns():
    local = {"files": [{"name": "m-Q4_K_M.gguf", "metadata": {"format": "GGUF"}}]}
    version = _files(
        ("n-Q8_0.gguf", "Diffusion Model", True, {"format": "GGUF"}),
        ("n-Q4_K_M.gguf", "Diffusion Model", False, {"format": "GGUF"}),
        ("n.safetensors", "Model", False, {"format": "SafeTensor"}),
    )
    ranked = rank_files(version, local, "m-Q4_K_M.gguf", ["*.safetensors", "*.gguf"])
    assert ranked[0]["name"] == "n-Q4_K_M.gguf"
    assert gguf_quant("x-q4_k_m.gguf") == "Q4_K_M"
    # A folder scanned for safetensors only never gets a GGUF file
    only = rank_files(version, local, "m-Q4_K_M.gguf", ["*.safetensors"])
    assert [f["name"] for f in only] == ["n.safetensors"]
