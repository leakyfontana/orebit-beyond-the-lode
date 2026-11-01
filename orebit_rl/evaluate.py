"""Reload the saved CPU PPO and compare it with uniform random validation actions.

Only the manifest's 50 validation worlds are evaluated; this module never learns
or starts a train/test episode. Existing evidence is never overwritten.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, TextIO

import numpy as np
from stable_baselines3 import PPO
import torch

from .environment import MINERAL_NAMES, OrebitEnv
from .experiment import (
    DEFAULT_MANIFEST, DEFAULT_RUN, code_hashes, file_sha256, load_manifest,
    publish_json, read_json, software_versions, validate_start, verify_runtime,
)


DECISION_CAP = 300
RANDOM_SEED = 20261031
TRAINING_SEED = 20261030
POLICIES = ("learned", "random")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _number(value: Any, label: str) -> float:
    _require(type(value) in (int, float) and math.isfinite(value), f"Invalid {label}")
    return float(value)


def _event(stream: TextIO, value: dict[str, Any]) -> None:
    stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def _verify_training(report: dict[str, Any], manifest_sha: str,
                     provenance: dict[str, Any], software: dict[str, str],
                     sources: dict[str, str]) -> None:
    _require(type(report.get("schema_version")) is int and report["schema_version"] == 1,
             "Unsupported training report schema")
    for key, expected in {"status": "completed", "algorithm": "PPO",
                          "policy": "MlpPolicy", "device": "cpu",
                          "manifest_sha256": manifest_sha,
                          "runtime_provenance": provenance, "software": software,
                          "code_sha256": {name: sources[name] for name in ("experiment.py", "train.py")}}.items():
        _require(report.get(key) == expected, f"Training report mismatch: {key}")
    model = report.get("model")
    _require(isinstance(model, dict) and model.get("file") == "model.zip",
             "Training report must identify model.zip")
    _require(type(model.get("num_timesteps")) is int and model["num_timesteps"] == 20480,
             "Training must have completed exactly 20480 decisions")
    digest = model.get("sha256")
    _require(isinstance(digest, str) and len(digest) == 64
             and all(char in "0123456789abcdef" for char in digest), "Invalid model SHA256")
    config = report.get("config")
    _require(isinstance(config, dict), "Missing training config")
    for key, expected in {"decision_cap": 20480, "wall_seconds_cap": 5400,
                          "seed": TRAINING_SEED}.items():
        _require(type(config.get(key)) is int and config[key] == expected,
                 f"Unexpected training config: {key}")
    observed = report.get("observed")
    _require(isinstance(observed, dict) and type(observed.get("decisions")) is int
             and observed["decisions"] == 20480, "Training decision accounting is incomplete")


def _state(env: OrebitEnv, observation: np.ndarray, info: dict[str, Any],
           seed: int, decisions: int, terminated: bool, truncated: bool) -> dict[str, Any]:
    _require(env.observation_space.contains(observation) and bool(np.isfinite(observation).all()),
             "Invalid normalized runtime observation")
    _require(type(info.get("seed")) is int and info["seed"] == seed,
             "Runtime changed the requested world seed")
    _require(type(info.get("steps")) is int and info["steps"] == decisions,
             "Runtime decision counter mismatch")
    _require(info.get("backend") == "Box2D" and info.get("physics_hz") == 50,
             "Runtime is not Box2D at 50 Hz")
    ticks = info.get("physics_ticks")
    _require(type(ticks) is int and (5 * (decisions - 1) < ticks <= 5 * decisions
                                   if decisions else ticks == 0), "Invalid runtime tick count")
    seconds = _number(info.get("simulated_seconds"), "simulated_seconds")
    _require(math.isclose(seconds, ticks / 50, rel_tol=1e-9, abs_tol=1e-9),
             "Runtime simulation clock mismatch")
    _require(type(terminated) is bool and type(truncated) is bool and not (terminated and truncated),
             "Invalid episode terminal flags")
    reason = info.get("reason")
    if terminated or truncated:
        _require(reason in {"success", "fuel", "death", "scene", "timeout"},
                 "Unknown terminal reason")
        _require(truncated == (reason == "timeout"), "Terminal reason/flags mismatch")
        if truncated:
            _require(decisions == DECISION_CAP, "Episode timed out before decision cap")
    else:
        _require(reason == "running" and ticks == 5 * decisions,
                 "Nonterminal reason or tick count mismatch")
    raw = info.get("raw_observation")
    _require(isinstance(raw, dict), "Missing authoritative raw observation")
    hp = _number(raw.get("hp"), "hp")
    fuel = _number(raw.get("fuel"), "fuel")
    cargo = raw.get("cargo")
    _require(isinstance(cargo, dict) and set(cargo) == set(MINERAL_NAMES)
             and all(type(value) is int and value >= 0 for value in cargo.values()),
             "Invalid authoritative mineral cargo")
    success = reason == "success"
    if success:
        _require(terminated and not truncated and sum(cargo.values()) >= 1 and hp > 0 and fuel > 0,
                 "Success is not backed by actual surviving mineral collection")
    return {"reason": reason, "success": success, "decisions": decisions,
            "physics_ticks": ticks, "simulated_seconds": seconds,
            "hp": hp, "fuel": fuel, "cargo": dict(cargo),
            "terminated": terminated, "truncated": truncated}


def _episode(env: OrebitEnv, model: PPO, entry: dict[str, Any], policy: str,
             active: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    seed = entry["seed"]
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([RANDOM_SEED, seed])))
    actions: list[int] = []
    total_reward = 0.0
    active.update({"policy": policy, "seed": seed, "candidate_index": entry["candidate_index"],
                   "status": "incomplete", "decisions": 0, "return": 0.0,
                   "reset_attempted": True, "reset_verified": False})
    try:
        observation, info = env.reset(seed=seed, options={"max_steps": DECISION_CAP})
        validate_start(env, observation, info, entry)
        active.update(_state(env, observation, info, seed, 0, False, False))
        active["reset_verified"] = True
        active["initial_observation_sha256"] = entry["observation_sha256"]
        for decision in range(1, DECISION_CAP + 1):
            if policy == "learned":
                action, _ = model.predict(observation, deterministic=True)
                candidate = np.asarray(action)
                _require(candidate.shape == () and candidate.dtype.kind in "iu",
                         "PPO predicted a non-scalar integer action")
                action = int(candidate.item())
            else:
                action = int(rng.integers(0, 5))
            _require(env.action_space.contains(action), "Policy predicted an invalid action")
            active["attempted_decision"] = decision
            active["attempted_action"] = action
            observation, reward, terminated, truncated, info = env.step(action)
            actions.append(action)
            total_reward += _number(reward, "reward")
            _require(math.isfinite(total_reward), "Non-finite accumulated episode return")
            active.update(_state(env, observation, info, seed, decision, terminated, truncated))
            active["return"] = total_reward
            active["actions"] = actions.copy()
            if terminated or truncated:
                break
        else:
            raise ValueError("Runtime failed to end the episode within 300 decisions")
    finally:
        env.close()
        active["wall_seconds"] = time.monotonic() - started
    active.pop("attempted_decision", None)
    active.pop("attempted_action", None)
    active["status"] = "completed"
    active["action_sha256"] = hashlib.sha256(bytes(actions)).hexdigest()
    return dict(active)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [row for row in rows if row["success"]]
    return {"episodes": len(rows), "success_count": len(successes),
            "success_rate": len(successes) / len(rows),
            "terminal_reason_counts": dict(sorted(Counter(row["reason"] for row in rows).items())),
            "mean_return": statistics.mean(row["return"] for row in rows),
            "median_decisions_all": statistics.median(row["decisions"] for row in rows),
            "median_simulated_seconds_success": (statistics.median(row["simulated_seconds"] for row in successes)
                                                  if successes else None),
            "decisions": sum(row["decisions"] for row in rows),
            "physics_ticks": sum(row["physics_ticks"] for row in rows)}


def _comparison(episodes: dict[str, list[dict[str, Any]]],
                summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pairs = list(zip(episodes["learned"], episodes["random"], strict=True))
    both = [(learned, random) for learned, random in pairs if learned["success"] and random["success"]]
    gap = 100 * (summaries["learned"]["success_count"] - summaries["random"]["success_count"]) / 50
    return {"paired_worlds": len(pairs), "success_percentage_point_gap_learned_minus_random": gap,
            "learned_only_success": sum(learned["success"] and not random["success"] for learned, random in pairs),
            "random_only_success": sum(random["success"] and not learned["success"] for learned, random in pairs),
            "both_success": len(both),
            "neither_success": sum(not learned["success"] and not random["success"] for learned, random in pairs),
            "higher_observed_success_rate": ("learned" if gap > 0 else "random" if gap < 0 else "neither"),
            "time_to_success": {
                "units": "simulated_seconds",
                "learned_median_conditional_on_success": summaries["learned"]["median_simulated_seconds_success"],
                "random_median_conditional_on_success": summaries["random"]["median_simulated_seconds_success"],
                "both_success_worlds": len(both),
                "paired_median_learned_minus_random": (statistics.median(
                    learned["simulated_seconds"] - random["simulated_seconds"] for learned, random in both)
                    if both else None),
                "interpretation": "Conditional medians may use different successful worlds; paired differences use only worlds where both succeed."
            },
            "interpretation": "Observed fixed-validation comparison only; training does not imply improvement or statistical significance."}


def evaluate(run_dir: Path, manifest_path: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest_path = manifest_path.resolve()
    _require(run_dir.is_dir(), f"Training run directory does not exist: {run_dir}")
    output = run_dir / "validation.json"
    failure = run_dir / "validation.failed.json"
    progress = run_dir / "validation.episodes.jsonl"
    for path in (output, failure, progress):
        _require(not path.exists(), f"Evaluation evidence already exists; refusing overwrite/resume: {path}")
    started = time.monotonic()
    active: dict[str, Any] = {}
    record: dict[str, Any] = {
        "schema_version": 1, "status": "failed", "split": "validation", "device": "cpu",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "training_run": str(run_dir), "manifest": str(manifest_path),
        "test_episode_count": 0, "training_episode_count": 0, "learning_calls": 0,
        "decision_cap_per_episode": DECISION_CAP,
        "episode_order": "manifest order; learned then random on each world",
        "decision_mode": {"learned": "PPO.predict(deterministic=True)",
                          "random": "uniform integers in [0, 5), independent RNG per world"},
        "random_policy": {"seed": RANDOM_SEED, "bit_generator": "PCG64",
                          "seed_algorithm": "numpy.random.SeedSequence([random_seed, world_seed])",
                          "sampling": "Generator.integers(0, 5)"},
        "episodes": {policy: [] for policy in POLICIES},
        "progress_file": progress.name,
    }
    manifest: dict[str, Any] | None = None
    project: Path | None = None
    with progress.open("x", encoding="utf-8") as stream:
        try:
            _event(stream, {"event": "evaluation_started", "split": "validation",
                            "started_at": record["started_at"]})
            manifest, manifest_sha, project = load_manifest(manifest_path)
            provenance = verify_runtime(manifest, project)
            sources = code_hashes("experiment.py", "train.py", "evaluate.py")
            software = software_versions()
            training_path = run_dir / "training.json"
            training_sha = file_sha256(training_path)
            training = read_json(training_path)
            _require(file_sha256(training_path) == training_sha, "Training report changed while loading")
            _verify_training(training, manifest_sha, provenance, software, sources)
            model_path = run_dir / "model.zip"
            _require(file_sha256(model_path) == training["model"]["sha256"], "Saved model SHA256 mismatch")
            record.update({"manifest_sha256": manifest_sha, "runtime_provenance": provenance,
                           "software": software, "code_sha256": sources,
                           "training_report_sha256": training_sha,
                           "model": dict(training["model"]),
                           "validation_seeds": [entry["seed"] for entry in manifest["splits"]["validation"]]})
            torch.set_num_threads(1)
            torch.manual_seed(TRAINING_SEED)
            torch.use_deterministic_algorithms(True)
            model = PPO.load(model_path, device="cpu")
            _require(model.device.type == "cpu" and model.policy.device.type == "cpu",
                     "Reloaded PPO is not on CPU")
            _require(type(model.num_timesteps) is int
                     and model.num_timesteps == training["model"]["num_timesteps"],
                     "Reloaded PPO timestep count mismatch")
            _require(all(bool(torch.isfinite(value).all()) for value in model.policy.state_dict().values()),
                     "Reloaded PPO policy has non-finite parameters/buffers")
            model.policy.set_training_mode(False)
            record["reload_verified"] = True
            record["torch_cpu_threads"] = torch.get_num_threads()
            record["deterministic_algorithms"] = torch.are_deterministic_algorithms_enabled()
            with OrebitEnv(path=project) as env:
                _require(model.observation_space == env.observation_space,
                         "Saved observation space differs from the frozen environment")
                _require(model.action_space == env.action_space and env.action_space.n == 5,
                         "Saved action space differs from Discrete(5)")
                for entry in manifest["splits"]["validation"]:
                    for policy in POLICIES:
                        active = {}
                        _event(stream, {"event": "episode_started", "policy": policy, "seed": entry["seed"]})
                        row = _episode(env, model, entry, policy, active)
                        record["episodes"][policy].append(row)
                        _event(stream, {"event": "episode_completed", **row})
                        active = {}
            for policy in POLICIES:
                rows = record["episodes"][policy]
                _require(len(rows) == 50 and [row["seed"] for row in rows] == record["validation_seeds"],
                         "Evaluation did not complete every validation seed in manifest order")
            _require(verify_runtime(manifest, project) == provenance, "Runtime provenance changed during evaluation")
            _require(file_sha256(manifest_path) == manifest_sha, "Manifest changed during evaluation")
            _require(file_sha256(training_path) == training_sha, "Training report changed during evaluation")
            _require(file_sha256(model_path) == training["model"]["sha256"], "Model changed during evaluation")
            _require(code_hashes("experiment.py", "train.py", "evaluate.py") == sources,
                     "Experiment sources changed during evaluation")
            record["summary"] = {policy: _summary(record["episodes"][policy]) for policy in POLICIES}
            record["comparison"] = _comparison(record["episodes"], record["summary"])
            record["status"] = "completed"
            record["completed_episode_count"] = 100
            record["wall_seconds"] = time.monotonic() - started
            record["completed_at"] = datetime.now(timezone.utc).isoformat()
            publish_json(output, record)
        except BaseException as error:
            record["status"] = "failed"
            record["error"] = {"type": type(error).__name__, "message": str(error)}
            record["active_episode"] = active or None
            record["completed_episode_count"] = sum(len(rows) for rows in record["episodes"].values())
            record["wall_seconds"] = time.monotonic() - started
            if manifest is not None and project is not None:
                try:
                    record["runtime_provenance_at_failure"] = verify_runtime(manifest, project)
                except Exception as guard_error:
                    record["provenance_guard_error"] = {"type": type(guard_error).__name__,
                                                        "message": str(guard_error)}
            publish_json(failure, record)
            _event(stream, {"event": "evaluation_failed", "error": record["error"],
                            "active_episode": record["active_episode"],
                            "completed_episode_count": record["completed_episode_count"]})
            raise
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("validation",), default="validation",
                        help="Only validation is allowed; no train/test evaluation")
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    try:
        result = evaluate(args.run_dir, args.manifest)
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__,
                          "message": str(error)}, allow_nan=False), file=sys.stderr, flush=True)
        return 1
    print(json.dumps({"status": result["status"], "split": result["split"],
                      "summary": result["summary"], "comparison": result["comparison"],
                      "report": str(args.run_dir.resolve() / "validation.json")},
                     sort_keys=True, allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
