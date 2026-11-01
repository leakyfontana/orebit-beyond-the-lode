"""Run Gymnasium and Stable-Baselines3 checks against the real headless game.

Run from the repository root: python -m orebit_rl.check
GODOT_BIN may name an alternative compatible Godot executable. No training runs.
"""

import json

import gymnasium
from gymnasium.utils.env_checker import check_env as check_gymnasium_env
import numpy as np
import stable_baselines3
from stable_baselines3.common.env_checker import check_env as check_sb3_env


def run():
    results = []
    for name, checker in (
        ("gymnasium", check_gymnasium_env),
        ("stable_baselines3", check_sb3_env),
    ):
        with gymnasium.make("OrebitCollect-v0") as wrapped:
            env = wrapped.unwrapped
            # Keep each checker's defaults; do not suppress compatibility warnings.
            checker(env)
            results.append({
                "checker": name,
                "passed": True,
                "observation_shape": list(env.observation_space.shape),
                "observation_dtype": str(env.observation_space.dtype),
                "actions": int(env.action_space.n),
            })

    print(json.dumps({
        "passed": True,
        "versions": {
            "gymnasium": gymnasium.__version__,
            "stable_baselines3": stable_baselines3.__version__,
            "numpy": np.__version__,
        },
        "checks": results,
    }, indent=2))


if __name__ == "__main__":
    run()
