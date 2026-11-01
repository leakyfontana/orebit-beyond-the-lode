"""Gymnasium interface to Orebit's real, isolated Godot RL worker."""

from gymnasium.envs.registration import register

from .environment import Action, OrebitEnv, OrebitError

__all__ = ["Action", "OrebitEnv", "OrebitError"]

register(id="OrebitCollect-v0", entry_point="orebit_rl:OrebitEnv")
