"""Shared evidence checks for the first frozen-runtime learning experiment."""

from __future__ import annotations

from importlib.metadata import version
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
from typing import Any

import numpy as np

from .environment import OrebitEnv
from .seeds import manifest_runtime_project, observation_sha256, runtime_provenance, validate_manifest


PACKAGE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = PACKAGE / "seed_manifest.json"
DEFAULT_RUN = PACKAGE / "ppo_baseline"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    def reject(value):
        raise ValueError(f"Non-finite JSON constant: {value}")

    result = json.loads(path.read_bytes(), object_pairs_hook=unique, parse_constant=reject)
    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return result


def load_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[dict[str, Any], str, Path]:
    before = file_sha256(path)
    manifest = read_json(path)
    if file_sha256(path) != before:
        raise ValueError("Seed manifest changed while loading")
    validate_manifest(manifest)
    return manifest, before, manifest_runtime_project(manifest)


def verify_runtime(manifest: dict[str, Any], project: Path) -> dict[str, Any]:
    """Read-only provenance check; this never starts a game episode."""
    with OrebitEnv(path=project) as env:
        actual = runtime_provenance(env)
    if actual != manifest["provenance"]:
        raise ValueError("Pinned runtime/source provenance differs from the seed manifest")
    return actual


def validate_start(env: OrebitEnv, observation: np.ndarray, info: dict[str, Any], entry: dict[str, Any]) -> None:
    if not env.observation_space.contains(observation) or not np.isfinite(observation).all():
        raise ValueError("Episode reset returned an invalid normalized observation")
    if info.get("seed") != entry["seed"] or info.get("steps") != 0 or info.get("physics_ticks") != 0:
        raise ValueError("Episode did not reset to the requested seed and clock origin")
    if info.get("reason") != "running" or info.get("backend") != "Box2D" or info.get("physics_hz") != 50:
        raise ValueError("Episode reset is not a running Box2D 50 Hz start")
    if observation_sha256(observation) != entry["observation_sha256"]:
        raise ValueError(f"Initial observation differs from manifest for seed {entry['seed']}")
    if info.get("target_cell") != entry["target_cell"] or info.get("start_position") != entry["start_position"]:
        raise ValueError("Episode target or starting position differs from the fixed manifest")


def software_versions() -> dict[str, str]:
    return {"python": platform.python_version(), **{
        name: version(name) for name in ("gymnasium", "numpy", "stable-baselines3", "torch")
    }}


def code_hashes(*names: str) -> dict[str, str]:
    return {name: file_sha256(PACKAGE / name) for name in names}


def publish_json(path: Path, record: dict[str, Any]) -> None:
    """Publish a complete report without replacing any existing evidence."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
