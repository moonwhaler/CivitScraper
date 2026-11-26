"""A synthetic library with outdated models, a fake CivitAI API and a fake storage server."""

import hashlib
import json
import os
import time

import pytest

from civitscraper.api.exceptions import ClientError

OLD = time.time() - 3600
API = "https://civitai.com/api/v1"


def blob(version_id, size=4096):
    """Deterministic file content of a version."""
    seed = hashlib.sha256(str(version_id).encode()).digest()
    return (seed * (size // len(seed) + 1))[:size]


def file_entry(version_id, name, content, file_id=None, primary=True, fp="fp16", **meta):
    file_id = file_id or version_id * 10
    return {
        "id": file_id,
        "name": name,
        "type": "Model",
        "primary": primary,
        "sizeKB": len(content) / 1024,
        "hashes": {"SHA256": hashlib.sha256(content).hexdigest().upper()},
        "metadata": {"format": "SafeTensor", "fp": fp, "size": "full", **meta},
        "downloadUrl": f"https://civitai.com/api/download/models/{version_id}?fileId={file_id}",
    }


def write_model(path, version_id, model_id, base, siblings, created, name="v1", **extra):
    """A local model file plus its CivitAI sidecar."""
    content = blob(version_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    os.utime(path, (OLD, OLD))
    meta = {
        "id": version_id,
        "modelId": model_id,
        "name": name,
        "baseModel": base,
        "createdAt": created,
        "model": {"name": f"Model {model_id}", "type": "LORA", "nsfw": False},
        "files": [file_entry(version_id, os.path.basename(path), content)],
        "trainedWords": ["old trigger"],
        "siblingVersions": siblings,
    }
    meta.update(extra)
    with open(os.path.splitext(path)[0] + ".json", "w") as f:
        json.dump(meta, f)
    return str(path)


def sibling(version_id, created, base="Flux.1 D", name=None):
    return {
        "id": version_id,
        "name": name or f"v{version_id}",
        "baseModel": base,
        "createdAt": created,
        "downloadCount": 1,
        "isCurrent": False,
    }


class FakeClient:
    """Enough of CivitAIClient for the update job."""

    def __init__(self, versions, api_key="KEY"):
        self.versions = versions
        self.api_key = api_key
        self.base_url = API
        self.user_agent = "test"
        self.download_rate_limiter = None

    def get_model_version(self, version_id, force_refresh=False):
        if version_id not in self.versions:
            raise ClientError(404, "not found")
        return self.versions[version_id]


class Response:
    def __init__(self, status, headers=None, body=b"", drop_after=None):
        self.status_code = status
        self.headers = headers or {}
        self.body = body
        self.drop_after = drop_after
        self.text = body.decode("latin-1") if status >= 400 else ""

    def json(self):
        return json.loads(self.body or b"{}")

    def iter_content(self, chunk_size=1):
        import requests

        sent = 0
        for i in range(0, len(self.body), 512):
            if self.drop_after is not None and sent >= self.drop_after:
                raise requests.ConnectionError("connection reset")
            chunk = self.body[i : i + 512]
            sent += len(chunk)
            yield chunk

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """CivitAI's download endpoint (redirect) and a Range-capable storage host."""

    def __init__(self, files):
        self.files = files  # file id -> bytes
        self.headers = {}
        self.calls = []
        self.api_status = {}  # file id -> status code instead of a redirect
        self.drop_once = {}  # file id -> bytes after which the connection drops once
        self.ignore_range = False
        self.body_override = {}

    def get(self, url, headers=None, allow_redirects=True, stream=False, timeout=None):
        headers = {k: v for k, v in (headers or {}).items() if v is not None}
        merged = {**self.headers, **headers}
        self.calls.append((url, merged))
        if url.startswith("https://civitai.com/api/download/"):
            file_id = int(url.split("fileId=")[1])
            status = self.api_status.get(file_id)
            if status:
                return Response(status, body=json.dumps({"message": f"HTTP {status}"}).encode())
            if merged.get("Authorization") != "Bearer KEY":
                return Response(401, body=b'{"message": "log in"}')
            return Response(307, {"Location": f"https://storage.example/f/{file_id}?sig=1"})
        file_id = int(url.split("/f/")[1].split("?")[0])
        body = self.body_override.get(file_id, self.files[file_id])
        start = 0
        rng = merged.get("Range")
        if rng and not self.ignore_range:
            start = int(rng.split("=")[1].rstrip("-"))
            part = body[start:]
            resp = Response(
                206,
                {
                    "Content-Range": f"bytes {start}-{len(body) - 1}/{len(body)}",
                    "Content-Length": str(len(part)),
                },
                part,
            )
        else:
            resp = Response(200, {"Content-Length": str(len(body))}, body)
        drop = self.drop_once.pop(file_id, None)
        if drop is not None:
            resp.drop_after = drop
        return resp


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Models with updates; returns (config, models dir, client, session)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    models = tmp_path / "models"
    lora = models / "Lora"
    # Model 100: local v1 (Flux), remote v2 and v3 newer on Flux, v4 on SDXL (other base)
    sibs = [
        sibling(11, "2026-01-01"),
        sibling(12, "2026-02-01"),
        sibling(13, "2026-03-01"),
        sibling(14, "2026-04-01", base="SDXL 1.0"),
    ]
    write_model(
        lora / "Flux" / "style" / "foo_v1.safetensors", 11, 100, "Flux.1 D", sibs, "2026-01-01"
    )
    # Model 200: up to date
    write_model(
        lora / "Flux" / "concept" / "bar.safetensors",
        21,
        200,
        "Flux.1 D",
        [sibling(21, "2026-01-01")],
        "2026-01-01",
    )
    # Model 300: newer version is early access
    write_model(
        lora / "Flux" / "concept" / "baz.safetensors",
        31,
        300,
        "Flux.1 D",
        [sibling(31, "2026-01-01"), sibling(32, "2026-05-01")],
        "2026-01-01",
    )

    contents = {12: blob(12, 8192), 13: blob(13, 6000), 32: blob(32)}
    versions = {
        12: {
            "id": 12,
            "name": "v12",
            "files": [file_entry(12, "foo_v2.safetensors", contents[12])],
            "trainedWords": ["new trigger"],
        },
        13: {
            "id": 13,
            "name": "v13",
            "trainedWords": ["new trigger"],
            "description": "<p>Better <b>hands</b></p>",
            "files": [
                file_entry(13, "foo_v3_fp32.safetensors", blob(13, 7000), file_id=131, fp="fp32"),
                file_entry(13, "foo_v3.safetensors", contents[13], file_id=130, primary=False),
            ],
        },
        32: {
            "id": 32,
            "name": "v32",
            "files": [file_entry(32, "baz_v2.safetensors", contents[32])],
            "earlyAccessEndsAt": "2099-01-01T00:00:00.000Z",
        },
    }
    files = {120: contents[12], 130: contents[13], 131: blob(13, 7000), 320: contents[32]}
    config = {
        "api": {"base_url": API, "key": "KEY", "max_retries": 2, "batch": {"retry_delay": 0}},
        "input_paths": {"lora": {"path": str(lora), "type": "LORA", "patterns": ["*.safetensors"]}},
        "jobs": {
            "fetch-all": {"type": "scan-paths", "paths": ["lora"]},
            "regenerate-html": {"type": "scan-paths", "use_cached_metadata": True},
            "updates": {"type": "download-updates", "paths": ["lora"]},
        },
        "scanner": {"cache_dir": str(tmp_path / "cache")},
        "updates": {"min_free_gb": 0},
        "sorting": {"krita": {"enabled": False}},
        "_config_dir": str(tmp_path),
    }
    return config, models, FakeClient(versions), FakeSession(files)


def tree(root):
    """Every file under ``root`` with its content hash (for exact before/after checks)."""
    result = {}
    for directory, _, names in os.walk(root):
        for name in names:
            path = os.path.join(directory, name)
            with open(path, "rb") as f:
                result[os.path.relpath(path, root)] = hashlib.sha256(f.read()).hexdigest()
    return result
