"""Generate or replay a fixed, real-runtime playable-start manifest; never train.

Run ``python -m orebit_rl.seeds`` once, then use ``--verify`` to replay it.
Candidate indices are zero based. Only ``--revalidate-partial`` may migrate a
complete schema-1 partial scan; it preserves that evidence and replays every ID.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np

from .environment import Action, MINERAL_NAMES, OrebitEnv, OrebitError
from .snapshot import validate_snapshot


DEFAULT_MANIFEST = Path(__file__).with_name("seed_manifest.json")
REPOSITORY = Path(__file__).resolve().parents[1]
SPLIT_COUNTS = {"train": 200, "validation": 50, "test": 100}
MAX_CANDIDATES = 1000
# A scan plus full replay plus the three benchmark resets stays below 1,000.
DEFAULT_CANDIDATES = 498
SOLVER_DECISIONS = 300
NAMESPACE = "orebit-rl-seeds-v1"
SETUP_REJECTIONS = {
    "No collision-clear shallow natural mineral with room above it for the authored player body": "natural_spawn_unavailable",
    "Natural spawn did not settle grounded directly above target ore": "natural_spawn_unsettled",
}
GENERATOR = {
    "namespace": NAMESPACE,
    "candidate_algorithm": "SHA256(ASCII(namespace + ':' + decimal(candidate_index))); first 4 bytes big-endian & 0x7fffffff",
    "candidate_index_start": 0,
    "duplicate_rule": "reject repeated seed without a runtime reset; first occurrence wins",
    "split_rule": "accepted order: first 200 train, next 50 validation, next 100 test",
    "observation_hash": "SHA256 of C-order IEEE754 float32 little-endian normalized initial observation bytes",
    "solver": {"action": "DOWN", "max_decisions": SOLVER_DECISIONS, "reset_options": {"max_steps": SOLVER_DECISIONS}},
}


class ManifestError(RuntimeError):
    """Invalid evidence or a manifest that cannot be faithfully replayed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def candidate_seed(candidate_index: int) -> int:
    _require(type(candidate_index) is int and candidate_index >= 0, "Candidate index must be a nonnegative integer")
    digest = hashlib.sha256(f"{NAMESPACE}:{candidate_index}".encode("ascii")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def observation_sha256(observation: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(observation, dtype="<f4").tobytes(order="C")).hexdigest()


def runtime_provenance(env: OrebitEnv) -> dict[str, Any]:
    """Fingerprint actual executable, native physics, authored data and protocol.

    No absolute filesystem paths or timestamps enter the fingerprint. Private
    environment launch selection is used intentionally so this identifies the
    same binary that reset launches, rather than a separately guessed executable.
    """
    binary = Path(env._command[0] if env._command else env._find_godot()).resolve()
    result = subprocess.run([str(binary), "--version"], check=True, capture_output=True,
                            text=True, timeout=env.timeout)
    godot_version = result.stdout.strip()
    _require(bool(godot_version), "Godot --version returned no version")
    project = env.path
    sources = {
        f"orebit_rl/{name}": Path(__file__).with_name(name)
        for name in ("environment.py", "__init__.py", "requirements.txt", "seeds.py", "snapshot.py")
    }
    for name in ("project.godot", "main.tscn"):
        sources[f"godot/{name}"] = project / name
    for directory, patterns in (
        ("scripts", ("*.gd", "*.gdshader", "*.uid")),
        ("scenes", ("*.tscn",)),
        ("data", ("*.res", "*.json")),
        ("animations", ("*.json",)),
        ("addons", ("*.gdextension", "*.so", "*.dll", "*.wasm", "*.dylib", "*.macos.template_release")),
    ):
        root = project / directory
        for pattern in patterns:
            for path in root.rglob(pattern):
                if path.is_file():
                    sources[f"godot/{path.relative_to(project).as_posix()}"] = path
    # Native-extension and class registries participate in actual script loading.
    for name in ("extension_list.cfg", "global_script_class_cache.cfg"):
        registry = project / ".godot" / name
        _require(registry.is_file(), f"Godot runtime registry {name} is missing; import the project first")
        sources[f"godot/.godot/{name}"] = registry
    _require(any(name.endswith(".gdextension") for name in sources), "No native extension configuration found")
    snapshot = validate_snapshot(project) if (project.parent / "snapshot.json").is_file() else None
    provenance = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "packages": {name: version(name) for name in ("gymnasium", "numpy", "stable-baselines3")},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "godot_version": godot_version,
        "godot_sha256": _file_sha256(binary),
        "source_sha256": {name: _file_sha256(path) for name, path in sorted(sources.items())},
        "runtime_snapshot_sha256": snapshot["fingerprint_sha256"] if snapshot is not None else None,
    }
    provenance["fingerprint_sha256"] = hashlib.sha256(_canonical(provenance)).hexdigest()
    return provenance


def _check_observation(env: OrebitEnv, observation: np.ndarray) -> None:
    _require(isinstance(observation, np.ndarray) and observation.dtype == np.float32
             and observation.shape == (677,) and bool(np.isfinite(observation).all())
             and env.observation_space.contains(observation), "Runtime returned an invalid normalized observation")


def _check_runtime(info: dict[str, Any]) -> None:
    _require(info["backend"] == "Box2D" and info["backend_class"] == "Box2DDirectSpaceState2D"
             and info["physics_hz"] == 50 and info["modal_rule"] == "dismiss_transmissions_only",
             "Runtime backend, fixed clock, or modal rule differs from the supported worker")
    _require(type(info["physics_ticks"]) is int and info["physics_ticks"] >= 0
             and math.isclose(info["simulated_seconds"], info["physics_ticks"] / 50, rel_tol=0, abs_tol=1e-9),
             "Runtime physics clock is inconsistent")


def _check_start(env: OrebitEnv, observation: np.ndarray, info: dict[str, Any], seed: int) -> None:
    _check_observation(env, observation)
    _check_runtime(info)
    raw = info["raw_observation"]
    _require(info["seed"] == seed and info["steps"] == 0 and info["physics_ticks"] == 0
             and info["reason"] == "running", "Reset did not return the requested fresh running start")
    _require(raw["scene"] == "Game" and raw["paused"] is False and raw["grounded"] is True
             and raw["digging"] is False, "Reset is not an unpaused grounded nondigging Game start")
    _require(raw["hp"] == raw["max_hp"] > 0 and raw["fuel"] == raw["max_fuel"] > 0,
             "Reset must have positive full stock health and fuel")
    _require(set(raw["cargo"]) == set(MINERAL_NAMES) and all(count == 0 for count in raw["cargo"].values())
             and raw["cargo_weight"] == 0, "Reset cargo is not empty")
    _require(info["start_position"] == raw["position"], "Reset start_position disagrees with actual player position")
    target = info["target_cell"]
    center = raw["tile_center"]
    _require(isinstance(target, list) and len(target) == 2 and all(type(value) is int for value in target)
             and target[0] >= 1 and 6 <= target[1] <= 40, "Reset target is not a shallow natural selector cell")
    x, y = target[0] - center[0] + 4, target[1] - center[1] + 4
    _require(0 <= x < 9 and 0 <= y < 9 and raw["tiles"][y][x] == 3,
             "Reset target is not a natural mineral in the local patch")


def _outcome(info: dict[str, Any], terminated: bool, truncated: bool) -> dict[str, Any]:
    raw = info["raw_observation"]
    return {"decisions": info["steps"], "physics_ticks": info["physics_ticks"],
            "simulated_seconds": info["simulated_seconds"], "reason": info["reason"],
            "terminated": terminated, "truncated": truncated,
            "cargo": raw["cargo"], "hp": raw["hp"], "fuel": raw["fuel"]}


def evaluate_candidate(env: OrebitEnv, seed: int, candidate_index: int) -> tuple[bool, dict[str, Any]]:
    """One reset only; reject natural setup failures, never infrastructure errors."""
    base = {"seed": seed, "candidate_index": candidate_index}
    try:
        observation, info = env.reset(seed=seed, options={"max_steps": SOLVER_DECISIONS})
    except OrebitError as error:
        # Only the first exception line can establish a recognized worker error;
        # log content must never turn a crash/timeout into a rejected game seed.
        first_line = str(error).splitlines()[0]
        for message, reason in SETUP_REJECTIONS.items():
            if first_line == f"Orebit reset failed: RuntimeError: Worker error: {message}":
                return False, {**base, "reason": reason}
        raise
    _check_start(env, observation, info, seed)
    entry = {**base, "target_cell": info["target_cell"], "start_position": info["start_position"],
             "observation_sha256": observation_sha256(observation)}
    previous_ticks = 0
    for decision in range(1, SOLVER_DECISIONS + 1):
        observation, reward, terminated, truncated, info = env.step(Action.DOWN)
        _check_observation(env, observation)
        _check_runtime(info)
        _require(info["seed"] == seed and info["steps"] == decision, "Scripted runtime seed/decision counter changed")
        delta = info["physics_ticks"] - previous_ticks
        _require((1 <= delta <= 5) if terminated or truncated else delta == 5,
                 "Scripted decision did not advance the fixed physics clock")
        previous_ticks = info["physics_ticks"]
        _require(info["reason"] in {"running", "success", "fuel", "death", "scene", "timeout"},
                 "Runtime returned an unsupported terminal reason")
        if terminated or truncated:
            outcome = _outcome(info, terminated, truncated)
            raw = info["raw_observation"]
            success = (terminated and not truncated and info["reason"] == "success"
                       and sum(raw["cargo"].values()) >= 1 and raw["hp"] > 0 and raw["fuel"] > 0)
            if success:
                _require(reward > 0, "Actual collection did not earn a positive terminal reward")
                return True, {**entry, "scripted_outcome": outcome}
            _require(info["reason"] != "running", "Runtime ended without a terminal reason")
            return False, {**base, "reason": f"scripted_unsolvable:{info['reason']}", "scripted_outcome": outcome}
        _require(info["reason"] == "running", "Runtime reports terminal reason without terminal flags")
    # The configured worker must truncate at decision 300, not silently continue.
    raise ManifestError("Worker did not enforce the scripted decision limit")


def _keys(value: Any, expected: set[str], label: str) -> None:
    _require(isinstance(value, dict) and set(value) == expected, f"Invalid {label} fields")


def _hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _validate_outcome(outcome: Any, *, accepted: bool) -> None:
    _keys(outcome, {"decisions", "physics_ticks", "simulated_seconds", "reason", "terminated", "truncated", "cargo", "hp", "fuel"}, "scripted outcome")
    _require(type(outcome["decisions"]) is int and 1 <= outcome["decisions"] <= SOLVER_DECISIONS
             and type(outcome["physics_ticks"]) is int
             and 5 * (outcome["decisions"] - 1) < outcome["physics_ticks"] <= 5 * outcome["decisions"], "Invalid scripted decision/tick counts")
    _require(type(outcome["terminated"]) is bool and type(outcome["truncated"]) is bool
             and outcome["terminated"] != outcome["truncated"], "Invalid scripted terminal flags")
    for name in ("simulated_seconds", "hp", "fuel"):
        _require(type(outcome[name]) in (int, float) and math.isfinite(outcome[name]), f"Invalid scripted {name}")
    _require(math.isclose(outcome["simulated_seconds"], outcome["physics_ticks"] / 50, rel_tol=0, abs_tol=1e-9), "Invalid scripted simulated duration")
    _keys(outcome["cargo"], set(MINERAL_NAMES), "mineral cargo")
    _require(all(type(count) is int and count >= 0 for count in outcome["cargo"].values()), "Invalid mineral cargo counts")
    _require(outcome["reason"] in {"success", "fuel", "death", "scene", "timeout"}, "Invalid scripted terminal reason")
    _require(outcome["truncated"] == (outcome["reason"] == "timeout"), "Terminal flags disagree with scripted reason")
    if outcome["reason"] == "timeout":
        _require(outcome["decisions"] == SOLVER_DECISIONS, "Timeout precedes configured decision limit")
    actual_success = (outcome["reason"] == "success" and outcome["terminated"] and not outcome["truncated"]
                      and sum(outcome["cargo"].values()) >= 1 and outcome["hp"] > 0 and outcome["fuel"] > 0)
    _require(actual_success == accepted, "Scripted outcome does not support its acceptance status")


def _validate_scan_evidence(manifest: dict[str, Any], *, snapshot_provenance: bool) -> None:
    """Validate recorded derivation and outcomes without claiming current provenance."""
    generator = manifest["generator"]
    _keys(generator, set(GENERATOR) | {"max_candidates"}, "generator")
    _require({key: generator[key] for key in GENERATOR} == GENERATOR, "Unsupported candidate derivation, split order or solver")
    cap = generator["max_candidates"]
    _require(type(cap) is int and 1 <= cap <= MAX_CANDIDATES, "Invalid candidate cap")
    count = manifest["candidate_count"]
    _require(type(count) is int and 350 <= count <= cap, "Invalid candidate count")
    provenance = manifest["provenance"]
    provenance_keys = {"python_version", "python_implementation", "packages", "platform", "godot_version",
                       "godot_sha256", "source_sha256", "fingerprint_sha256"}
    _keys(provenance, provenance_keys | ({"runtime_snapshot_sha256"} if snapshot_provenance else set()), "provenance")
    if snapshot_provenance:
        _require(provenance["runtime_snapshot_sha256"] is None or _hash(provenance["runtime_snapshot_sha256"]),
                 "Invalid runtime snapshot fingerprint")
    _keys(provenance["packages"], {"gymnasium", "numpy", "stable-baselines3"}, "package versions")
    _keys(provenance["platform"], {"system", "release", "machine"}, "platform")
    _require(all(isinstance(value, str) and value for value in
                 [provenance["python_version"], provenance["python_implementation"], provenance["godot_version"],
                  *provenance["packages"].values(), *provenance["platform"].values()]), "Invalid runtime version metadata")
    _require(_hash(provenance["godot_sha256"]) and isinstance(provenance["source_sha256"], dict)
             and bool(provenance["source_sha256"]) and all(isinstance(name, str) and not Path(name).is_absolute()
             and ".." not in Path(name).parts and _hash(digest) for name, digest in provenance["source_sha256"].items()), "Invalid source fingerprints")
    _require(provenance["fingerprint_sha256"] == hashlib.sha256(_canonical({key: value for key, value in provenance.items() if key != "fingerprint_sha256"})).hexdigest(), "Provenance fingerprint is corrupt")
    _keys(manifest["splits"], set(SPLIT_COUNTS), "splits")
    accepted = []
    for split, size in SPLIT_COUNTS.items():
        entries = manifest["splits"][split]
        _require(isinstance(entries, list) and len(entries) == size, f"Expected exactly {size} {split} entries")
        for entry in entries:
            _keys(entry, {"seed", "candidate_index", "target_cell", "start_position", "observation_sha256", "scripted_outcome"}, "accepted entry")
            _require(_hash(entry["observation_sha256"]), "Invalid initial observation fingerprint")
            target, position = entry["target_cell"], entry["start_position"]
            _require(isinstance(target, list) and len(target) == 2 and all(type(value) is int for value in target)
                     and target[0] >= 1 and 6 <= target[1] <= 40, "Invalid shallow ore target")
            _require(isinstance(position, list) and len(position) == 2 and all(type(value) in (int, float) and math.isfinite(value) for value in position), "Invalid start position")
            _validate_outcome(entry["scripted_outcome"], accepted=True)
            accepted.append(entry)
    _require(isinstance(manifest["rejections"], list), "Rejections must be an array")
    rejected = manifest["rejections"]
    for entry in rejected:
        _require(isinstance(entry, dict), "Invalid rejected entry")
        reason = entry.get("reason")
        scripted = isinstance(reason, str) and reason.startswith("scripted_unsolvable:")
        _keys(entry, {"seed", "candidate_index", "reason"} | ({"scripted_outcome"} if scripted else set()), "rejected entry")
        _require(reason in {*SETUP_REJECTIONS.values(), "duplicate_seed"} or scripted, "Unknown rejection reason")
        if scripted:
            _validate_outcome(entry["scripted_outcome"], accepted=False)
            _require(reason == f"scripted_unsolvable:{entry['scripted_outcome']['reason']}", "Scripted rejection reason disagrees with its outcome")
    all_entries = accepted + rejected
    _require(len(all_entries) == count, "Candidate scan contains missing or extra entries")
    indices = []
    for entry in all_entries:
        index = entry["candidate_index"]
        _require(type(index) is int and 0 <= index < count and type(entry["seed"]) is int
                 and entry["seed"] == candidate_seed(index), "Candidate derivation does not match the recorded seed/index")
        indices.append(index)
    _require(len(set(indices)) == count, "Candidate indices are not unique and contiguous")
    _require([entry["candidate_index"] for entry in accepted] == sorted(entry["candidate_index"] for entry in accepted), "Accepted split order changed")
    _require([entry["candidate_index"] for entry in rejected] == sorted(entry["candidate_index"] for entry in rejected), "Rejection order changed")
    _require(accepted[-1]["candidate_index"] == count - 1, "Candidate scan continued after the required 350 accepted starts")
    seen = set()
    for entry in sorted(all_entries, key=lambda item: item["candidate_index"]):
        duplicate = entry["seed"] in seen
        _require(duplicate == (entry.get("reason") == "duplicate_seed"), "Duplicate candidate handling changed")
        seen.add(entry["seed"])
    _require(len({entry["seed"] for entry in accepted}) == 350, "Accepted splits overlap")


def _runtime_project_name(project: Path) -> str:
    project = project.resolve()
    _require(project.is_relative_to(REPOSITORY), "Runtime project must be inside the repository")
    return project.relative_to(REPOSITORY).as_posix()


def manifest_runtime_project(manifest: dict[str, Any], explicit: Path | None = None) -> Path:
    """Select the pinned project, refusing overrides to a different runtime."""
    pinned = (REPOSITORY / manifest["runtime_project"]).resolve()
    _require(pinned.is_relative_to(REPOSITORY), "Pinned runtime project escapes the repository")
    if explicit is not None:
        selected = explicit.expanduser().resolve()
        if not (selected / "project.godot").is_file() and (selected / "godot" / "project.godot").is_file():
            selected = selected / "godot"
        _require(selected == pinned, "--path must match the manifest's pinned runtime_project")
    return pinned


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Validate schema 2; schema-1 evidence is migration input only."""
    _keys(manifest, {"schema_version", "generator", "provenance", "runtime_project", "revalidation",
                     "candidate_count", "rejections", "splits"}, "manifest")
    _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 2, "Unsupported manifest schema")
    project = manifest["runtime_project"]
    _require(isinstance(project, str) and project and not Path(project).is_absolute()
             and ".." not in Path(project).parts and Path(project).as_posix() == project,
             "Invalid repository-relative runtime project")
    _validate_scan_evidence(manifest, snapshot_provenance=True)
    audit = manifest["revalidation"]
    if audit is not None:
        _keys(audit, {"original_partial_sha256", "original_provenance_fingerprint_sha256",
                      "candidate_evaluations", "reset_evaluations", "changed_record_count",
                      "changed_candidate_indices"}, "revalidation audit")
        _require(_hash(audit["original_partial_sha256"]) and _hash(audit["original_provenance_fingerprint_sha256"]),
                 "Invalid original evidence fingerprint")
        _require(_hash(manifest["provenance"]["runtime_snapshot_sha256"]), "Revalidation requires a frozen runtime snapshot")
        resets = manifest["candidate_count"] - sum(entry.get("reason") == "duplicate_seed" for entry in manifest["rejections"])
        _require(type(audit["candidate_evaluations"]) is int and audit["candidate_evaluations"] == manifest["candidate_count"]
                 and type(audit["reset_evaluations"]) is int and audit["reset_evaluations"] == resets,
                 "Revalidation did not replay the full candidate scan")
        changed = audit["changed_candidate_indices"]
        _require(isinstance(changed, list) and all(type(index) is int and 0 <= index < manifest["candidate_count"] for index in changed)
                 and changed == sorted(set(changed)) and type(audit["changed_record_count"]) is int
                 and audit["changed_record_count"] == len(changed), "Invalid changed-record audit")


def _load_json(path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result, f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ManifestError(f"Non-finite JSON constant: {value}")

    return json.loads(path.read_bytes(), object_pairs_hook=unique, parse_constant=reject_constant)


def _load_revalidation_source(path: Path) -> dict[str, Any]:
    source = _load_json(path)
    fields = {"schema_version", "generator", "provenance", "candidate_count", "rejections", "splits",
              "status", "completed_candidates", "reset_evaluations"}
    _require(isinstance(source, dict) and set(source) in (fields, fields | {"error"}), "Invalid partial evidence fields")
    _require(type(source["schema_version"]) is int and source["schema_version"] == 1
             and source["status"] == "incomplete", "Revalidation requires explicit schema-1 partial evidence")
    _validate_scan_evidence(source, snapshot_provenance=False)
    _require(type(source["completed_candidates"]) is int and source["completed_candidates"] == source["candidate_count"],
             "Partial scan has unfinished candidates; full-scan evidence is required")
    resets = source["candidate_count"] - sum(entry.get("reason") == "duplicate_seed" for entry in source["rejections"])
    _require(type(source["reset_evaluations"]) is int and source["reset_evaluations"] == resets,
             "Partial scan reset accounting is incomplete")
    if "error" in source:
        _keys(source["error"], {"type", "candidate"}, "partial error")
        _require(isinstance(source["error"]["type"], str) and bool(source["error"]["type"]), "Invalid partial error type")
        _keys(source["error"]["candidate"], {"seed", "candidate_index"}, "partial error candidate")
        candidate = source["error"]["candidate"]
        _require(type(candidate["candidate_index"]) is int and candidate["candidate_index"] == source["candidate_count"] - 1
                 and type(candidate["seed"]) is int and candidate["seed"] == candidate_seed(candidate["candidate_index"]),
                 "Partial failure did not follow the completed scan")
    return source


def _publish_json(path: Path, value: dict[str, Any], *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)  # Atomic, exclusive publication; never overwrite.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _summary(manifest: dict[str, Any], *, mode: str, reset_evaluations: int) -> dict[str, Any]:
    return {"mode": mode, "candidate_count": manifest["candidate_count"],
            "counts": {split: len(entries) for split, entries in manifest["splits"].items()},
            "rejected": len(manifest["rejections"]), "reset_evaluations": reset_evaluations}


def _progress(completed: int, accepted: int, rejected: int, reset_evaluations: int) -> None:
    if completed % 25 == 0:
        print(json.dumps({"completed_candidates": completed, "accepted": accepted,
                          "rejected": rejected, "reset_evaluations": reset_evaluations}), flush=True)


def generate_manifest(path: Path, max_candidates: int, project: Path | None = None) -> dict[str, Any]:
    _require(not path.exists(), f"Manifest already exists: {path}; use --verify (no overwrite is permitted)")
    partial = path.with_suffix(".partial.json")
    _require(not partial.exists(), f"Partial evidence already exists: {partial}; preserve it before a new generation run")
    manifest = {"schema_version": 2, "generator": {**GENERATOR, "max_candidates": max_candidates},
                "provenance": {}, "runtime_project": "", "revalidation": None,
                "candidate_count": 0, "rejections": [], "splits": {split: [] for split in SPLIT_COUNTS}}
    reset_evaluations = 0
    completed = 0
    accepted = 0
    current = None
    seen = set()
    with OrebitEnv(path=project) as env:
        try:
            manifest["runtime_project"] = _runtime_project_name(env.path)
            manifest["provenance"] = runtime_provenance(env)
            for index in range(max_candidates):
                seed = candidate_seed(index)
                current = {"seed": seed, "candidate_index": index}
                manifest["candidate_count"] = index + 1
                if seed in seen:
                    passed, entry = False, {**current, "reason": "duplicate_seed"}
                else:
                    reset_evaluations += 1
                    passed, entry = evaluate_candidate(env, seed, index)
                seen.add(seed)
                if passed:
                    for split, size in SPLIT_COUNTS.items():
                        if len(manifest["splits"][split]) < size:
                            manifest["splits"][split].append(entry)
                            break
                    accepted += 1
                else:
                    manifest["rejections"].append(entry)
                completed += 1
                _publish_json(partial, {**manifest, "status": "incomplete", "completed_candidates": completed,
                                       "reset_evaluations": reset_evaluations}, replace=True)
                _progress(completed, accepted, len(manifest["rejections"]), reset_evaluations)
                if accepted == 350:
                    break
            _require(accepted == 350, f"Candidate cap exhausted: {manifest['candidate_count']} candidates, {accepted}/350 playable starts")
            env.close()
            # Detect edits during the scan rather than publishing mixed-runtime evidence.
            _require(runtime_provenance(env) == manifest["provenance"], "Source/runtime provenance changed during generation")
            validate_manifest(manifest)
            _publish_json(path, manifest, replace=False)
        except BaseException as error:
            evidence = {**manifest, "status": "incomplete", "completed_candidates": completed,
                        "reset_evaluations": reset_evaluations,
                        "error": {"type": type(error).__name__, "candidate": current}}
            _publish_json(partial, evidence, replace=True)
            print(json.dumps({**_summary(manifest, mode="incomplete", reset_evaluations=reset_evaluations),
                              "completed_candidates": completed, "partial_artifact": str(partial),
                              "error_type": type(error).__name__}), file=sys.stderr, flush=True)
            raise
    partial.unlink()
    return {**_summary(manifest, mode="generated", reset_evaluations=reset_evaluations),
            "manifest_sha256": _file_sha256(path), "manifest": str(path)}


def revalidate_partial(source_path: Path, path: Path, max_candidates: int, project: Path | None) -> dict[str, Any]:
    """Replay complete old evidence on a frozen runtime, never replacing seeds."""
    _require(path.resolve() != source_path.resolve(), "Output must not replace original partial evidence")
    _require(not path.exists(), f"Manifest already exists: {path}")
    partial = path.with_suffix(".revalidation.partial.json")
    _require(partial.resolve() != source_path.resolve(), "Replay evidence must not replace the original partial")
    _require(not partial.exists(), f"Revalidation evidence already exists: {partial}; preserve it before another run")
    original_sha256 = _file_sha256(source_path)
    source = _load_revalidation_source(source_path)
    _require(_file_sha256(source_path) == original_sha256, "Original partial changed while loading")
    _require(source["candidate_count"] <= max_candidates, "Recorded scan exceeds --max-candidates revalidation budget")
    _require(project is not None, "--revalidate-partial requires --path to a frozen runtime snapshot")
    entries = [entry for split in SPLIT_COUNTS for entry in source["splits"][split]] + source["rejections"]
    entries.sort(key=lambda entry: entry["candidate_index"])
    membership = {entry["candidate_index"]: split for split in SPLIT_COUNTS for entry in source["splits"][split]}
    audit = {"original_partial_sha256": original_sha256,
             "original_provenance_fingerprint_sha256": source["provenance"]["fingerprint_sha256"],
             "candidate_evaluations": 0, "reset_evaluations": 0,
             "changed_record_count": 0, "changed_candidate_indices": []}
    manifest = {"schema_version": 2, "generator": source["generator"], "provenance": {},
                "runtime_project": "", "revalidation": audit, "candidate_count": source["candidate_count"],
                "splits": {split: [] for split in SPLIT_COUNTS}, "rejections": []}
    completed = 0
    accepted = 0
    rejected = 0
    current = None
    actual = None
    with OrebitEnv(path=project) as env:
        try:
            manifest["runtime_project"] = _runtime_project_name(env.path)
            # A migration is explicitly about a content-frozen project, never an
            # unchecked new provenance fingerprint over the still-active game.
            validate_snapshot(env.path)
            manifest["provenance"] = runtime_provenance(env)
            _require(_hash(manifest["provenance"]["runtime_snapshot_sha256"]), "Snapshot provenance is missing")
            for entry in entries:
                current = {"candidate_index": entry["candidate_index"], "seed": entry["seed"]}
                actual = None
                if entry.get("reason") == "duplicate_seed":
                    passed, actual = False, dict(entry)
                else:
                    audit["reset_evaluations"] += 1
                    passed, actual = evaluate_candidate(env, entry["seed"], entry["candidate_index"])
                completed += 1
                audit["candidate_evaluations"] = completed
                if actual != entry:
                    audit["changed_candidate_indices"].append(entry["candidate_index"])
                    audit["changed_record_count"] += 1
                expected_split = membership.get(entry["candidate_index"])
                _require(passed == (expected_split is not None),
                         f"Revalidation changed acceptance for candidate {entry['candidate_index']}; membership cannot change")
                if passed:
                    manifest["splits"][expected_split].append(actual)
                    accepted += 1
                else:
                    manifest["rejections"].append(actual)
                    rejected += 1
                _publish_json(partial, {**manifest, "status": "incomplete", "completed_candidates": completed,
                                       "reset_evaluations": audit["reset_evaluations"]}, replace=True)
                _progress(completed, accepted, rejected, audit["reset_evaluations"])
            env.close()
            _require(runtime_provenance(env) == manifest["provenance"], "Source/snapshot provenance changed during revalidation")
            _require(_file_sha256(source_path) == original_sha256, "Original partial changed during revalidation")
            validate_manifest(manifest)
            _publish_json(path, manifest, replace=False)
        except BaseException as error:
            evidence = {**manifest, "status": "incomplete", "completed_candidates": completed,
                        "reset_evaluations": audit["reset_evaluations"],
                        "error": {"type": type(error).__name__, "message": str(error),
                                  "candidate": current, "observed_entry": actual}}
            _publish_json(partial, evidence, replace=True)
            print(json.dumps({**_summary(manifest, mode="revalidation_failed", reset_evaluations=audit["reset_evaluations"]),
                              "completed_candidates": completed, "partial_artifact": str(partial),
                              "error_type": type(error).__name__}), file=sys.stderr, flush=True)
            raise
    partial.unlink()
    return {**_summary(manifest, mode="revalidated", reset_evaluations=audit["reset_evaluations"]),
            "revalidation": audit, "runtime_project": manifest["runtime_project"],
            "manifest_sha256": _file_sha256(path), "manifest": str(path)}


def verify_manifest(path: Path, max_candidates: int, project: Path | None = None) -> dict[str, Any]:
    manifest = _load_json(path)
    validate_manifest(manifest)
    _require(manifest["candidate_count"] <= max_candidates, "Recorded scan exceeds --max-candidates verification budget")
    project = manifest_runtime_project(manifest, project)
    failure = path.with_suffix(".verification-failed.json")
    _require(not failure.exists(), f"Verification failure evidence already exists: {failure}; preserve it before another run")
    entries = [entry for split in SPLIT_COUNTS for entry in manifest["splits"][split]] + manifest["rejections"]
    entries.sort(key=lambda entry: entry["candidate_index"])
    reset_evaluations = 0
    accepted = 0
    rejected = 0
    completed = 0
    current = None
    actual = None
    with OrebitEnv(path=project) as env:
        try:
            _require(runtime_provenance(env) == manifest["provenance"], "Manifest source/runtime provenance is stale; refusing replay")
            for entry in entries:
                current = {"candidate_index": entry["candidate_index"], "seed": entry["seed"]}
                actual = None
                if entry.get("reason") == "duplicate_seed":
                    actual = entry  # The pure validator reproduced this deterministic rejection.
                    passed = False
                else:
                    reset_evaluations += 1
                    passed, actual = evaluate_candidate(env, entry["seed"], entry["candidate_index"])
                _require(actual == entry, f"Replay diverged for candidate {entry['candidate_index']} seed {entry['seed']}")
                _require(passed == ("reason" not in entry), "Replay acceptance status diverged")
                accepted += int(passed)
                rejected += int(not passed)
                completed += 1
                _progress(completed, accepted, rejected, reset_evaluations)
            env.close()
            _require(runtime_provenance(env) == manifest["provenance"], "Source/runtime provenance changed during verification")
        except BaseException as error:
            evidence = {"mode": "verification_failed", "manifest_sha256": _file_sha256(path),
                        "reset_evaluations": reset_evaluations, "completed_candidates": completed,
                        "verified_accepted": accepted, "verified_rejections": rejected,
                        "error": {"type": type(error).__name__, "message": str(error),
                                  "candidate": current, "observed_entry": actual}}
            _publish_json(failure, evidence, replace=False)
            print(json.dumps({key: value for key, value in evidence.items() if key != "error"}),
                  file=sys.stderr, flush=True)
            raise
    return {**_summary(manifest, mode="verified", reset_evaluations=reset_evaluations),
            "verified_rejections": rejected, "manifest_sha256": _file_sha256(path), "manifest": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="Replay every accepted start and natural/scripted rejection")
    mode.add_argument("--revalidate-partial", type=Path, help="Fully replay a complete schema-1 partial against a frozen snapshot")
    parser.add_argument("--path", type=Path, help="Godot project (must match the pinned project for --verify)")
    parser.add_argument("--max-candidates", type=int,
                        help="Bound scan/replay candidates (default 350 for partial revalidation, otherwise 498; maximum 1000)")
    args = parser.parse_args()
    cap = args.max_candidates if args.max_candidates is not None else (350 if args.revalidate_partial is not None else DEFAULT_CANDIDATES)
    if not 1 <= cap <= MAX_CANDIDATES:
        parser.error("--max-candidates must be between 1 and 1000")
    try:
        if args.revalidate_partial is not None:
            result = revalidate_partial(args.revalidate_partial, args.manifest, cap, args.path)
        elif args.verify:
            result = verify_manifest(args.manifest, cap, args.path)
        else:
            result = generate_manifest(args.manifest, cap, args.path)
    except (Exception, KeyboardInterrupt) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from error
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
