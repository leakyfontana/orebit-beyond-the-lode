"""Exercise the real normalized Orebit environment; no training.

Run from the repository root: python3 -m orebit_rl.smoke
GODOT_BIN may name an alternative compatible Godot executable.
"""

import json
import time

import numpy as np

from . import Action, OrebitEnv
from .environment import SCALAR_NAMES, TILE_FEATURE_COUNT


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check_observation(env, observation):
    require(isinstance(observation, np.ndarray), "Observation must be a NumPy array")
    require(observation.dtype == np.float32, "Observation must use float32")
    require(observation.shape == (677,), "Observation must have 677 flat features")
    require(np.isfinite(observation).all(), "Observation must contain only finite values")
    require(env.observation_space.contains(observation),
            "Observation must belong to the normalized observation space")


def mineral_count(observation):
    return sum(observation["cargo"].values())


def check_clock(previous, current, *, terminal=False):
    ticks = current["physics_ticks"] - previous["physics_ticks"]
    require(1 <= ticks <= 5 if terminal else ticks == 5,
            f"Unexpected physics advancement: {ticks} ticks")
    require(abs(current["simulated_seconds"] - current["physics_ticks"] / 50) < 1e-8,
            "Simulated duration disagrees with the 50 Hz physics clock")


def run():
    results = []
    with OrebitEnv() as env:
        initial, initial_info = env.reset(seed=12345)
        check_observation(env, initial)
        raw_initial = initial_info["raw_observation"]
        require(mineral_count(raw_initial) == 0, "Reset must have empty cargo")
        require(raw_initial["hp"] > 0 and raw_initial["fuel"] > 0
                and not raw_initial["paused"],
                "Reset must expose a living, playable state")
        require(initial_info["physics_hz"] == 50, "Expected configured 50 Hz physics")
        require(initial_info["physics_ticks"] == 0, "Reset must precede episode ticks")
        prefix = []
        info = initial_info
        for decision in range(300):
            previous = info
            observation, reward, terminated, truncated, info = env.step(Action.DOWN)
            check_observation(env, observation)
            raw = info["raw_observation"]
            check_clock(previous, info, terminal=terminated or truncated)
            if len(prefix) < 3:
                prefix.append((observation, reward, terminated, truncated))
            if terminated or truncated:
                require(terminated and not truncated and info["reason"] == "success",
                        f"Scripted mining did not succeed: {info}")
                require(mineral_count(raw) >= 1 and raw["hp"] > 0
                        and raw["fuel"] > 0,
                        "Success must reflect actual cargo and surviving resources")
                require(reward > 0, "Collection must earn the terminal success reward")
                results.append({"case": "scripted_collection", "seed": 12345,
                                "target_cell": info["target_cell"], "decisions": decision + 1,
                                "physics_ticks": info["physics_ticks"],
                                "simulated_seconds": info["simulated_seconds"],
                                "cargo": raw["cargo"], "backend": info["backend"]})
                try:
                    env.step(Action.DOWN)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Terminal episodes must require reset")
                break
        else:
            raise AssertionError("Scripted mining exceeded its decision limit")

        repeated, repeated_info = env.reset(seed=12345)
        check_observation(env, repeated)
        require(np.array_equal(repeated, initial),
                "Same seed must reproduce the full normalized initial observation")
        require(repeated_info["target_cell"] == initial_info["target_cell"],
                "Same seed must select the same natural ore target")
        # Client wall time must not leak into simulation while awaiting an action.
        time.sleep(0.1)
        info = repeated_info
        for expected in prefix:
            previous = info
            observation, reward, terminated, truncated, info = env.step(Action.DOWN)
            check_observation(env, observation)
            check_clock(previous, info, terminal=terminated or truncated)
            (expected_observation, expected_reward,
             expected_terminated, expected_truncated) = expected
            require(np.array_equal(observation, expected_observation)
                    and (reward, terminated, truncated)
                    == (expected_reward, expected_terminated, expected_truncated),
                    "Repeated action prefix diverged after a client-side delay")
        results.append({"case": "same_seed_reset_and_action_prefix",
                        "matching_decisions": len(prefix), "client_delay_seconds": 0.1})

        observation, info = env.reset(seed=12345, options={"initial_fuel": 0.001})
        check_observation(env, observation)
        require(info["raw_observation"]["fuel"] > 0, "Low-fuel setup must begin alive")
        observation, reward, terminated, truncated, info = env.step(Action.IDLE)
        check_observation(env, observation)
        raw = info["raw_observation"]
        require(terminated and not truncated and info["reason"] == "fuel",
                f"Fuel exhaustion must be a natural terminal failure: {info}")
        require(raw["fuel"] <= 0 and reward < 0 and mineral_count(raw) == 0,
                "Fuel failure must come from consumed fuel, not awarded cargo")
        fuel_index = TILE_FEATURE_COUNT + SCALAR_NAMES.index("fuel_ratio")
        require(observation[fuel_index] < 0,
                "Normalization must preserve signed fuel depletion")
        results.append({"case": "fuel_failure", "reason": info["reason"],
                        "fuel": raw["fuel"], "physics_ticks": info["physics_ticks"]})

        observation, previous = env.reset(seed=12345, options={"max_steps": 1})
        check_observation(env, observation)
        observation, reward, terminated, truncated, info = env.step(Action.IDLE)
        check_observation(env, observation)
        raw = info["raw_observation"]
        check_clock(previous, info)
        require(not terminated and truncated and info["reason"] == "timeout",
                f"Time limit must truncate, not naturally terminate: {info}")
        require(info["steps"] == 1 and raw["hp"] > 0 and raw["fuel"] > 0,
                "Timeout must preserve the living game state")
        require(abs(reward + 0.001) < 1e-8, "Timeout should incur only the decision cost")
        results.append({"case": "time_limit", "reason": info["reason"],
                        "steps": info["steps"], "physics_ticks": info["physics_ticks"]})

        observation, previous = env.reset(seed=12345, options={"max_steps": 1})
        check_observation(env, observation)
        env.action_space.seed(0)
        action = env.action_space.sample()
        require(env.action_space.contains(action), "Sampled action must belong to its space")
        observation, reward, terminated, truncated, info = env.step(action)
        check_observation(env, observation)
        check_clock(previous, info)
        require(not terminated and truncated and info["reason"] == "timeout",
                "A sampled action must advance the actual one-decision episode")
        results.append({"case": "sampled_action", "action": int(action),
                        "action_type": type(action).__name__,
                        "physics_ticks": info["physics_ticks"]})

    print(json.dumps({"passed": True, "cases": results}, indent=2))


if __name__ == "__main__":
    run()
