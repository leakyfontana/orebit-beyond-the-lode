"""One bounded CPU PPO run using only the frozen manifest's training seeds."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
import sys
import time
from typing import Any, TextIO

import gymnasium as gym
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import DummyVecEnv
import torch

from .environment import OrebitEnv
from .experiment import (
    DEFAULT_MANIFEST, DEFAULT_RUN, code_hashes, file_sha256, load_manifest,
    publish_json, software_versions, validate_start, verify_runtime,
)


DECISION_CAP = 20_480
WALL_SECONDS_CAP = 5_400
TRAINING_SEED = 20_261_030
PPO_CONFIG = {
    "n_steps": 512, "batch_size": 64, "n_epochs": 10,
    "learning_rate": 3e-4, "gamma": 0.99, "gae_lambda": 0.95,
    "clip_range": 0.2, "clip_range_vf": None, "normalize_advantage": True,
    "ent_coef": 0.0, "vf_coef": 0.5, "max_grad_norm": 0.5,
    "use_sde": False, "sde_sample_freq": -1, "target_kl": None,
    "stats_window_size": 100, "tensorboard_log": None, "verbose": 0,
    "policy_kwargs": {"net_arch": [64, 64], "activation_fn": "torch.nn.Tanh"},
}


class WallTimeCap(BaseException):
    """Bypass native transport's Exception handler when the real timer expires."""


def _wall_time_cap(signum: int, frame: Any) -> None:
    raise WallTimeCap(f"Model setup/learning reached {WALL_SECONDS_CAP} seconds")


def policy_sha256(model: PPO) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.policy.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(str(tuple(value.shape)).encode("ascii"))
        digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def finite_policy(model: PPO) -> bool:
    return all(bool(torch.isfinite(value).all()) for value in model.policy.state_dict().values())


class TrainingSeeds(gym.Wrapper):
    """Cycle independently shuffled train-only permutations and record native evidence."""

    def __init__(self, env: OrebitEnv, entries: list[dict[str, Any]], trace: TextIO):
        super().__init__(env)
        self.entries = entries
        self.trace = trace
        self.rng = np.random.default_rng(TRAINING_SEED)
        self.scheduler_seed = TRAINING_SEED
        self.order: list[int] = []
        self.position = 0
        self.permutations: list[list[int]] = []
        self.reset_attempts = 0
        self.resets = 0
        self.decisions = 0
        self.decision_attempts = 0
        self.physics_ticks = 0
        self.completed = 0
        self.completed_return = 0.0
        self.reasons: Counter[str] = Counter()
        self.seed_counts: Counter[int] = Counter()
        self.active: dict[str, Any] | None = None
        self.pending_seed: int | None = None
        self.step_in_flight = False
        self.unfinished: dict[str, Any] | None = None

    def _append(self, row: dict[str, Any]) -> None:
        self.trace.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        self.trace.flush()

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        if options:
            raise ValueError("Training reset options are fixed at max_steps=300")
        if self.active is not None:
            raise RuntimeError("Training cannot discard an unfinished episode")
        if seed is not None:
            if self.reset_attempts:
                raise RuntimeError("The training scheduler may only be seeded before its first reset")
            self.scheduler_seed = int(seed)
            self.rng = np.random.default_rng(self.scheduler_seed)
        if self.position == len(self.order):
            self.order = self.rng.permutation(len(self.entries)).tolist()
            self.position = 0
            self.permutations.append([self.entries[index]["seed"] for index in self.order])
        entry = self.entries[self.order[self.position]]
        self.position += 1
        self.reset_attempts += 1
        self.pending_seed = entry["seed"]
        observation, info = self.env.reset(seed=entry["seed"], options={"max_steps": 300})
        validate_start(self.env, observation, info, entry)
        self.resets += 1
        self.seed_counts[entry["seed"]] += 1
        self.active = {
            "episode": self.resets, "seed": entry["seed"], "split": "train",
            "return": 0.0, "decisions": 0, "physics_ticks": 0,
            "simulated_seconds": 0.0, "reason": info["reason"],
            "terminated": False, "truncated": False,
        }
        self.pending_seed = None
        return observation, info

    def step(self, action):
        if self.active is None:
            raise RuntimeError("Training step requires a verified train-seed reset")
        if self.decision_attempts >= DECISION_CAP:
            raise RuntimeError("Refusing a native decision beyond the training cap")
        self.decision_attempts += 1
        self.step_in_flight = True
        observation, reward, terminated, truncated, info = self.env.step(action)
        self.step_in_flight = False
        previous_ticks = self.active["physics_ticks"]
        self.decisions += 1
        self.active["return"] += float(reward)
        self.active["decisions"] += 1
        self.active.update({
            "physics_ticks": info["physics_ticks"],
            "simulated_seconds": info["simulated_seconds"], "reason": info["reason"],
            "terminated": bool(terminated), "truncated": bool(truncated),
        })
        self.physics_ticks += info["physics_ticks"] - previous_ticks
        if terminated or truncated:
            row = {**self.active, "status": "completed", "success": info["reason"] == "success"}
            self._append(row)
            self.completed += 1
            self.completed_return += row["return"]
            self.reasons[row["reason"]] += 1
            self.active = None
        return observation, reward, terminated, truncated, info

    def finish_trace(self) -> None:
        if self.active is not None:
            self.unfinished = {
                **self.active, "status": "unfinished", "success": False,
                "step_in_flight": self.step_in_flight,
            }
            self._append(self.unfinished)
            self.active = None
        if self.pending_seed is not None:
            self._append({"seed": self.pending_seed, "split": "train", "status": "reset_failed"})

    def evidence(self) -> dict[str, Any]:
        return {
            "decisions": self.decisions, "native_decision_attempts": self.decision_attempts,
            "native_step_in_flight_at_stop": self.step_in_flight,
            "physics_ticks": self.physics_ticks, "simulated_seconds": self.physics_ticks / 50.0,
            "reset_attempts": self.reset_attempts, "verified_resets": self.resets,
            "failed_resets": self.reset_attempts - self.resets,
            "completed_episodes": self.completed, "unfinished_episodes": int(self.unfinished is not None),
            "unfinished_episode": self.unfinished,
            "completed_episode_return_sum": self.completed_return,
            "terminal_reason_counts": dict(sorted(self.reasons.items())),
            "train_seeds_used": sorted(self.seed_counts),
            "train_seed_reset_counts": {str(seed): count for seed, count in sorted(self.seed_counts.items())},
            "train_seed_coverage": len(self.seed_counts), "validation_episodes": 0, "test_episodes": 0,
            "scheduler": {"seed": self.scheduler_seed, "algorithm": "numpy.default_rng.PCG64.permutation",
                          "permutations": self.permutations},
        }


class Progress(BaseCallback):
    def __init__(self, env: TrainingSeeds):
        super().__init__(verbose=0)
        self.training_env_evidence = env

    def _on_step(self) -> bool:
        if self.num_timesteps > DECISION_CAP:
            raise RuntimeError("PPO exceeded its decision cap")
        if self.num_timesteps != self.training_env_evidence.decisions:
            raise RuntimeError("PPO and native decision accounting disagree")
        if self.num_timesteps % PPO_CONFIG["n_steps"] == 0:
            print(f"PPO decisions={self.num_timesteps}/{DECISION_CAP} "
                  f"completed_episodes={self.training_env_evidence.completed}", flush=True)
        return True


def run(run_dir: Path) -> int:
    # mkdir is exclusive: neither success nor a failed prior attempt can be overwritten.
    run_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report: dict[str, Any] = {
        "schema_version": 1, "status": "failed", "algorithm": "PPO", "policy": "MlpPolicy",
        "device": "cpu", "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": {"decision_cap": DECISION_CAP, "wall_seconds_cap": WALL_SECONDS_CAP,
                   "seed": TRAINING_SEED, "ppo": PPO_CONFIG, "num_envs": 1,
                   "torch_cpu_threads": 1, "max_episode_decisions": 300,
                   "manifest_file": str(DEFAULT_MANIFEST), "training_split": "train"},
        "errors": [], "model": None,
    }
    model: PPO | None = None
    env: TrainingSeeds | None = None
    vector: DummyVecEnv | None = None
    manifest = None
    project = None
    trace = None
    timer_installed = False
    previous_handler = None
    learning_started: float | None = None
    learning_finished: float | None = None
    optimizer_hook = None
    optimizer_steps = 0
    initial_policy_hash: str | None = None

    def record_error(phase: str, error: BaseException) -> None:
        report["errors"].append({"phase": phase, "type": type(error).__name__, "message": str(error)})

    def optimizer_step_completed(optimizer, args, kwargs):
        nonlocal optimizer_steps
        optimizer_steps += 1

    try:
        report["software"] = software_versions()
        report["code_sha256"] = code_hashes("experiment.py", "train.py")
        manifest, manifest_hash, project = load_manifest()
        report["manifest_sha256"] = manifest_hash
        entries = manifest["splits"]["train"]
        if len(entries) != 200 or len({entry["seed"] for entry in entries}) != 200:
            raise ValueError("Training requires exactly 200 distinct manifest training seeds")
        if DECISION_CAP % PPO_CONFIG["n_steps"] or DECISION_CAP != 40 * 512:
            raise ValueError("Decision cap must contain exactly 40 complete PPO rollouts")
        report["runtime_provenance"] = verify_runtime(manifest, project)
        if file_sha256(DEFAULT_MANIFEST) != manifest_hash:
            raise ValueError("Manifest changed during training preflight")
        if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
            raise RuntimeError("Refusing to replace an existing process wall timer")
        trace = (run_dir / "episodes.jsonl").open("x", encoding="utf-8")
        env = TrainingSeeds(OrebitEnv(path=project), entries, trace)
        if env.observation_space.shape != (677,) or env.action_space != gym.spaces.Discrete(5):
            raise ValueError("Training requires normalized 677-float observations and five actions")
        vector = DummyVecEnv([lambda: env])
        previous_handler = signal.signal(signal.SIGALRM, _wall_time_cap)
        timer_installed = True
        learning_started = time.monotonic()
        signal.setitimer(signal.ITIMER_REAL, WALL_SECONDS_CAP)
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        report["config"]["torch_deterministic_algorithms"] = torch.are_deterministic_algorithms_enabled()
        report["config"]["torch_cpu_interop_threads"] = torch.get_num_interop_threads()
        kwargs = {**PPO_CONFIG, "policy_kwargs": {"net_arch": [64, 64], "activation_fn": torch.nn.Tanh}}
        model = PPO("MlpPolicy", vector, device="cpu", seed=TRAINING_SEED, **kwargs)
        report["config"]["optimizer"] = {
            "class": f"{type(model.policy.optimizer).__module__}.{type(model.policy.optimizer).__name__}",
            "param_groups": [{key: value for key, value in group.items() if key != "params"}
                             for group in model.policy.optimizer.param_groups],
        }
        if str(model.device) != "cpu" or torch.get_num_threads() != 1 or not finite_policy(model):
            raise RuntimeError("PPO did not initialize finite parameters on one-thread CPU")
        initial_policy_hash = policy_sha256(model)
        optimizer_hook = model.policy.optimizer.register_step_post_hook(optimizer_step_completed)
        model.learn(total_timesteps=DECISION_CAP, callback=Progress(env), log_interval=None, progress_bar=False)
        learning_finished = time.monotonic()
        signal.setitimer(signal.ITIMER_REAL, 0)
        if learning_finished - learning_started >= WALL_SECONDS_CAP:
            raise WallTimeCap("Model setup/learning reached the wall cap")
        if model.num_timesteps != DECISION_CAP or env.decisions != DECISION_CAP:
            raise RuntimeError("Training ended without exactly 20480 native/PPO decisions")
        if model._n_updates != 400 or optimizer_steps != 3200:
            raise RuntimeError("Training did not execute 40 complete rollouts and their optimizer updates")
        if not finite_policy(model) or policy_sha256(model) == initial_policy_hash:
            raise RuntimeError("Training did not produce changed, finite policy parameters")
        report["status"] = "completed"
    except WallTimeCap as error:
        report["status"] = "wall_time_cap"
        record_error("training", error)
    except (Exception, KeyboardInterrupt) as error:
        record_error("training", error)
    finally:
        if timer_installed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
        if learning_started is not None:
            report["model_setup_and_learning_seconds"] = (learning_finished or time.monotonic()) - learning_started
        if optimizer_hook is not None:
            optimizer_hook.remove()
        if env is not None:
            try:
                env.finish_trace()
            except Exception as error:
                record_error("episode_trace", error)
            try:
                env.close()
            except Exception as error:
                record_error("environment_close", error)
        if trace is not None:
            trace.close()
        if manifest is not None and project is not None:
            try:
                report["final_runtime_provenance"] = verify_runtime(manifest, project)
                if file_sha256(DEFAULT_MANIFEST) != report["manifest_sha256"]:
                    raise ValueError("Manifest changed during training")
                if code_hashes("experiment.py", "train.py") != report["code_sha256"]:
                    raise ValueError("Training implementation changed during training")
            except Exception as error:
                record_error("final_provenance", error)
        if report["errors"] and report["status"] == "completed":
            report["status"] = "failed"

    observed = env.evidence() if env is not None else {"decisions": 0, "validation_episodes": 0, "test_episodes": 0}
    observed.update({"optimizer_steps": optimizer_steps, "initial_policy_sha256": initial_policy_hash})
    report["observed"] = observed
    if model is not None:
        try:
            observed["ppo_num_timesteps"] = int(model.num_timesteps)
            observed["ppo_epoch_updates"] = int(model._n_updates)
            observed["parameters_finite"] = finite_policy(model)
            observed["final_policy_sha256"] = policy_sha256(model)
            state_steps = [int(state["step"].item()) for state in model.policy.optimizer.state.values() if "step" in state]
            observed["optimizer_state_step_min"] = min(state_steps) if state_steps else 0
            observed["optimizer_state_step_max"] = max(state_steps) if state_steps else 0
            if not observed["parameters_finite"]:
                raise ValueError("Refusing to save a model with non-finite parameters")
            filename = "model.zip" if report["status"] == "completed" else "model.partial.zip"
            path = run_dir / filename
            with path.open("xb") as stream:
                model.save(stream)
            report["model"] = {"file": filename, "sha256": file_sha256(path),
                               "num_timesteps": int(model.num_timesteps)}
            reloaded = PPO.load(path, device="cpu")
            if (reloaded.num_timesteps != model.num_timesteps or not finite_policy(reloaded)
                    or str(reloaded.device) != "cpu" or policy_sha256(reloaded) != observed["final_policy_sha256"]
                    or reloaded.observation_space != model.observation_space
                    or reloaded.action_space != model.action_space):
                raise ValueError("Saved model did not reload with identical finite policy and spaces on CPU")
            observed["checkpoint_reload_verified"] = True
        except Exception as error:
            record_error("checkpoint", error)
            if report["status"] == "completed":
                report["status"] = "failed"
    if trace is not None:
        report["episode_trace"] = {"file": "episodes.jsonl", "sha256": file_sha256(run_dir / "episodes.jsonl")}
    report["total_wall_seconds"] = time.monotonic() - started
    publish_json(run_dir / "training.json", report)
    print(json.dumps({"status": report["status"], "report": str(run_dir / "training.json"),
                      "decisions": observed["decisions"]}), flush=True)
    return 0 if report["status"] == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN,
                        help="New exclusive artifact directory; existing directories are refused")
    args = parser.parse_args()
    try:
        return run(args.run_dir.expanduser().resolve())
    except Exception as error:
        print(f"Training could not publish evidence: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
