"""Measure real Godot IDLE throughput on manifest training starts, without training.

Run with ``python -m orebit_rl.benchmark`` after generating or revalidating the
seed manifest. Its pinned runtime is selected automatically and checked before
and after measurement. Timing reproducibility means a fixed procedure, not
identical wall-clock results.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile
import time
from typing import Any

import numpy as np

from .environment import Action, OrebitEnv
from .seeds import manifest_runtime_project, observation_sha256, runtime_provenance, validate_manifest


DEFAULT_MANIFEST = Path(__file__).with_name("seed_manifest.json")
DEFAULT_OUTPUT = Path(__file__).with_name("benchmark_results.json")


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _seconds(start: int) -> float:
    return (time.perf_counter_ns() - start) / 1_000_000_000


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _latencies(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "median_seconds": None, "p95_seconds": None}
    ordered = sorted(values)
    rank = (len(ordered) - 1) * 0.95
    lower = math.floor(rank)
    upper = math.ceil(rank)
    p95 = ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)
    return {"count": len(values), "median_seconds": statistics.median(values),
            "p95_seconds": p95}


def _clock(info: dict[str, Any]) -> tuple[int, float]:
    ticks = info.get("physics_ticks")
    seconds = info.get("simulated_seconds")
    if type(ticks) is not int or ticks < 0:
        raise ValueError("Runtime physics_ticks must be a nonnegative integer")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds < 0):
        raise ValueError("Runtime simulated_seconds must be finite and nonnegative")
    if not math.isclose(seconds, ticks / 50, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("Runtime simulation clock does not match actual 50 Hz ticks")
    return ticks, float(seconds)


def _run_episode(entry: dict[str, Any], steps: int, env_options: dict[str, Any],
                 *, warmup: bool = False) -> dict[str, Any]:
    started = time.perf_counter_ns()
    record: dict[str, Any] = {
        "seed": entry["seed"], "candidate_index": entry["candidate_index"],
        "excluded_warmup": warmup, "requested_decisions": steps,
        "status": "failed", "decisions": 0, "physics_ticks": 0,
        "simulated_seconds": 0.0, "step_measurements": [],
        "reset_wall_seconds": None, "close_wall_seconds": None, "reset_attempted": False,
    }
    env: OrebitEnv | None = None
    try:
        env = OrebitEnv(**env_options)
        reset_started = time.perf_counter_ns()
        record["reset_attempted"] = True
        try:
            observation, info = env.reset(seed=entry["seed"], options={"max_steps": steps})
        finally:
            record["reset_wall_seconds"] = _seconds(reset_started)
        record["reset_info"] = info
        record["final_info"] = info
        if not env.observation_space.contains(observation) or not np.isfinite(observation).all():
            raise ValueError("Reset observation is not finite and within observation_space")
        observed_hash = observation_sha256(observation)
        record["observation_sha256"] = observed_hash
        if observed_hash != entry["observation_sha256"]:
            raise ValueError("Reset observation fingerprint differs from verified manifest")
        if info.get("target_cell") != entry["target_cell"] or info.get("start_position") != entry["start_position"]:
            raise ValueError("Reset target/start position differs from verified manifest")
        if info.get("backend") != "Box2D" or info.get("physics_hz") != 50:
            raise ValueError("Benchmark requires the actual Box2D 50 Hz runtime")
        previous_ticks, previous_seconds = _clock(info)
        if previous_ticks != 0 or previous_seconds != 0 or info.get("reason") != "running":
            raise ValueError("Reset did not begin at the running simulation origin")
        for decision in range(1, steps + 1):
            step_started = time.perf_counter_ns()
            try:
                observation, reward, terminated, truncated, info = env.step(Action.IDLE)
            except Exception:
                record["failed_step_wall_seconds"] = _seconds(step_started)
                raise
            elapsed = _seconds(step_started)
            measurement = {"decision": decision, "wall_seconds": elapsed,
                           "reward": reward, "terminated": terminated,
                           "truncated": truncated, "reason": info.get("reason"),
                           "physics_ticks_total": info.get("physics_ticks"),
                           "simulated_seconds_total": info.get("simulated_seconds")}
            record["step_measurements"].append(measurement)
            record["decisions"] += 1
            record["final_info"] = info
            ticks, simulated = _clock(info)
            if ticks < previous_ticks or simulated < previous_seconds:
                raise ValueError("Runtime counters moved backwards")
            measurement["physics_ticks"] = ticks - previous_ticks
            measurement["simulated_seconds"] = simulated - previous_seconds
            record["physics_ticks"] += ticks - previous_ticks
            record["simulated_seconds"] += simulated - previous_seconds
            previous_ticks, previous_seconds = ticks, simulated
            if not env.observation_space.contains(observation) or not np.isfinite(observation).all():
                raise ValueError("Step observation is not finite and within observation_space")
            if terminated or truncated:
                if decision != steps or terminated or not truncated or info.get("reason") != "timeout":
                    record["status"] = "unexpected_terminal"
                else:
                    record["status"] = "completed"
                break
            if info.get("reason") != "running":
                raise ValueError("Nonterminal step has a non-running reason")
        else:
            raise ValueError("Runtime did not truncate at the requested max_steps")
    except Exception as error:
        record["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if env is not None:
            close_started = time.perf_counter_ns()
            try:
                env.close()
            except Exception as error:
                record["close_error"] = {"type": type(error).__name__, "message": str(error)}
                record["status"] = "failed"
            finally:
                record["close_wall_seconds"] = _seconds(close_started)
        record["episode_wall_seconds"] = _seconds(started)
    durations = [step["wall_seconds"] for step in record["step_measurements"]]
    record["step_wall_seconds"] = sum(durations)
    record["decision_latency"] = _latencies(durations)
    record["decisions_per_step_second"] = _ratio(record["decisions"], sum(durations))
    record["physics_ticks_per_step_second"] = _ratio(record["physics_ticks"], sum(durations))
    record["simulated_seconds_per_step_second"] = _ratio(record["simulated_seconds"], sum(durations))
    return record


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = sum(item["decisions"] for item in episodes)
    ticks = sum(item["physics_ticks"] for item in episodes)
    simulated = sum(item["simulated_seconds"] for item in episodes)
    step_seconds = sum(item["step_wall_seconds"] for item in episodes)
    reset_times = [item["reset_wall_seconds"] for item in episodes if item["reset_wall_seconds"] is not None]
    reset_seconds = sum(reset_times)
    whole_seconds = sum(item["episode_wall_seconds"] for item in episodes)
    latencies = [step["wall_seconds"] for item in episodes for step in item["step_measurements"]]
    return {
        "episodes_attempted": len(episodes),
        "episodes_completed": sum(item["status"] == "completed" for item in episodes),
        "decisions": decisions, "physics_ticks": ticks, "simulated_seconds": simulated,
        "step_wall_seconds": step_seconds, "reset_wall_seconds": reset_seconds,
        "close_wall_seconds": sum(item["close_wall_seconds"] or 0 for item in episodes),
        "episode_wall_seconds": whole_seconds,
        "decisions_per_step_second": _ratio(decisions, step_seconds),
        "physics_ticks_per_step_second": _ratio(ticks, step_seconds),
        "simulated_seconds_per_step_second": _ratio(simulated, step_seconds),
        "reset_inclusive_decisions_per_second": _ratio(decisions, reset_seconds + step_seconds),
        "end_to_end_decisions_per_second": _ratio(decisions, whole_seconds),
        "startup_mean_seconds": statistics.mean(reset_times) if reset_times else None,
        "startup_median_seconds": statistics.median(reset_times) if reset_times else None,
        "decision_latency": _latencies(latencies),
    }


def _save(path: Path, result: dict[str, Any], overwrite: bool) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            # An atomic no-clobber publication also protects against concurrent runs.
            os.link(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace the output artifact")
    parser.add_argument("--episodes", type=int, default=3, help="First N train starts only (1–200)")
    parser.add_argument("--steps", type=int, default=200, help="IDLE decisions/max_steps per episode (1–200)")
    parser.add_argument("--warmup-steps", type=int, default=0, help="One excluded first-train-seed warmup (0 disables; 1–5)")
    parser.add_argument("--godot-bin")
    parser.add_argument("--path", type=Path, help="Optional project override; must match the manifest's pinned runtime")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request runtime timeout in seconds")
    args = parser.parse_args(argv)
    if not 1 <= args.episodes <= 200 or not 1 <= args.steps <= 200 or not 0 <= args.warmup_steps <= 5:
        parser.error("episodes and steps must be in 1–200; warmup-steps must be in 0–5")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    if args.output.exists() and not args.overwrite:
        parser.error(f"Output already exists: {args.output}; use --overwrite explicitly")
    if not args.output.parent.is_dir():
        parser.error(f"Output directory does not exist: {args.output.parent}")
    if args.output.resolve() == args.manifest.resolve():
        parser.error("Output must not replace the seed manifest")
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    validate_manifest(manifest)
    entries = manifest["splits"]["train"][:args.episodes]
    project = manifest_runtime_project(manifest, args.path)
    env_options = {"godot_bin": args.godot_bin, "path": project, "timeout": args.timeout}
    with OrebitEnv(**env_options) as env:
        provenance = runtime_provenance(env)
    if provenance != manifest["provenance"]:
        raise ValueError("Pinned runtime/source provenance differs from manifest; refusing benchmark resets")
    result: dict[str, Any] = {
        "schema_version": 1, "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "provenance": provenance, "status": "running", "episodes": [], "warmup": None,
        "runtime_project": manifest["runtime_project"],
        "settings": {
            "split": "train", "selection": "first N entries in manifest order",
            "seeds": [entry["seed"] for entry in entries], "episodes": args.episodes,
            "decisions_per_episode": args.steps, "max_steps": args.steps,
            "action": "IDLE", "action_value": int(Action.IDLE),
            "warmup_steps": args.warmup_steps, "timeout_seconds": args.timeout,
            "fresh_worker_per_reset": True, "learned_model": False,
        },
        "method": {
            "clock": "time.perf_counter_ns (monotonic wall time)",
            "baseline": "Neutral IDLE game-runtime throughput, not learned-model throughput",
            "step_wall_seconds": "Sum of individual synchronous env.step call durations, including transport and observation encoding",
            "startup": "One env.reset call per episode; launches a fresh isolated worker and generates/settles its world",
            "episode_wall_seconds": "Environment construction through close, including Python recording/validation overhead",
            "weighted_rates": "Sum of executed counters / sum of measured durations; never mean of per-episode rates",
            "reset_inclusive_rate": "Executed decisions / (reset wall seconds + successful step-call wall seconds)",
            "end_to_end_rate": "Executed decisions / episode wall seconds including shutdown and failed calls",
            "latency_p95": "Linear interpolation at rank 0.95 * (N - 1) of sorted successful step-call durations",
            "warmup": "Optional separate first-train-seed episode, excluded from every aggregate",
            "counter_source": "Differences of returned cumulative physics_ticks and simulated_seconds; no assumed ticks per decision",
            "failure_policy": "Record early terminals/errors and stop; no dropped episodes or replacement seeds",
        },
    }
    run_started = time.perf_counter_ns()
    if args.warmup_steps:
        result["warmup"] = _run_episode(entries[0], args.warmup_steps, env_options, warmup=True)
    if result["warmup"] is None or result["warmup"]["status"] == "completed":
        for entry in entries:
            episode = _run_episode(entry, args.steps, env_options)
            result["episodes"].append(episode)
            if episode["status"] != "completed":
                break
    result["measurement_wall_seconds"] = _seconds(run_started)
    result["reset_evaluations"] = (
        sum(episode["reset_attempted"] for episode in result["episodes"])
        + int(result["warmup"] is not None and result["warmup"]["reset_attempted"])
    )
    result["aggregate"] = _aggregate(result["episodes"])
    result["status"] = "completed" if (
        len(result["episodes"]) == args.episodes
        and all(episode["status"] == "completed" for episode in result["episodes"])
    ) else "failed"
    try:
        with OrebitEnv(**env_options) as env:
            result["final_provenance"] = runtime_provenance(env)
        if result["final_provenance"] != provenance:
            raise ValueError("Source/snapshot provenance changed during benchmark")
    except Exception as error:
        result["status"] = "failed"
        result["provenance_error"] = {"type": type(error).__name__, "message": str(error)}
    result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    _save(args.output, result, args.overwrite)
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "manifest_sha256": result["manifest_sha256"],
                      "reset_evaluations": result["reset_evaluations"],
                      "aggregate": result["aggregate"]}, sort_keys=True, allow_nan=False), flush=True)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
