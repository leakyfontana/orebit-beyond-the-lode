"""Gymnasium control of Orebit's real, isolated Godot worker.

Model observations are normalized float32 vectors; authoritative game state is
retained unmodified in ``info["raw_observation"]``. No game simulation runs here.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import IntEnum
import json
import math
import os
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any, BinaryIO

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from numpy.typing import NDArray


# Row-major tiles, with eight categorical channels per tile, precede scalars.
TILE_WINDOW_SIZE = 9
TILE_CATEGORY_COUNT = 8
TILE_FEATURE_COUNT = TILE_WINDOW_SIZE * TILE_WINDOW_SIZE * TILE_CATEGORY_COUNT
MINERAL_NAMES = (
    "Ironium", "Bronzium", "Silverium", "Goldium", "Platinium",
    "Einsteinium", "Emerald", "Ruby", "Diamond", "Amazonite",
)
SCALAR_NAMES = (
    "world_x", "world_y", "fractional_x", "fractional_y",
    "velocity_x", "velocity_y", "facing_right", "grounded", "flying",
    "digging", "paused", "fuel_ratio", "hp_ratio", "cargo_ratio",
    "max_fuel", "max_hp", "cargo_capacity", *MINERAL_NAMES,
    "in_game", "elapsed_ticks",
)
OBSERVATION_SIZE = TILE_FEATURE_COUNT + len(SCALAR_NAMES)


def _finite_number(value: Any, name: str) -> float:
    """Reject malformed worker values rather than masking corrupt game state."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"Worker {name} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"Worker {name} must be a finite number") from error
    if not math.isfinite(number):
        raise ValueError(f"Worker {name} must be finite")
    return number


def _encode_observation(
    raw: Mapping[str, Any], info: Mapping[str, Any], max_steps: int
) -> NDArray[np.float32]:
    """Encode raw state without mutation; see constants for the feature layout.

    Tile IDs are categorical one-hot features, never ordinal quantities. World
    and velocity scales are 36x600 tiles and 10 tiles/s. Resource ratios preserve
    negative depletion, capacity scales are 10/10/7, and elapsed time is measured
    against five physics ticks per decision.
    """
    encoded = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
    tiles = raw.get("tiles")
    if not isinstance(tiles, (list, tuple)) or len(tiles) != TILE_WINDOW_SIZE:
        raise ValueError("Worker tiles must be a 9x9 array")
    for row_index, row in enumerate(tiles):
        if not isinstance(row, (list, tuple)) or len(row) != TILE_WINDOW_SIZE:
            raise ValueError("Worker tiles must be a 9x9 array")
        for column_index, category in enumerate(row):
            if (
                isinstance(category, (bool, np.bool_))
                or not isinstance(category, (int, np.integer))
                or not 0 <= category < TILE_CATEGORY_COUNT
            ):
                raise ValueError("Worker tile categories must be integers in [0, 7]")
            offset = (row_index * TILE_WINDOW_SIZE + column_index) * TILE_CATEGORY_COUNT
            encoded[offset + int(category)] = 1.0

    vectors: dict[str, tuple[float, float]] = {}
    for name in ("position", "velocity", "tile_center"):
        vector = raw.get(name)
        if not isinstance(vector, (list, tuple)) or len(vector) != 2:
            raise ValueError(f"Worker {name} must contain two finite numbers")
        vectors[name] = (
            _finite_number(vector[0], f"{name}[0]"),
            _finite_number(vector[1], f"{name}[1]"),
        )
    x, y = vectors["position"]
    vx, vy = vectors["velocity"]
    flags = []
    for name in ("facing_right", "grounded", "flying", "digging", "paused"):
        flag = raw.get(name)
        if type(flag) is not bool:
            raise ValueError(f"Worker {name} must be a JSON boolean")
        flags.append(float(flag))

    resources = {}
    for name in ("fuel", "max_fuel", "hp", "max_hp", "cargo_weight", "cargo_capacity"):
        resources[name] = _finite_number(raw.get(name), name)
    for name in ("max_fuel", "max_hp", "cargo_capacity"):
        if resources[name] <= 0:
            raise ValueError(f"Worker {name} must be positive")
    cargo = raw.get("cargo")
    if not isinstance(cargo, Mapping):
        raise ValueError("Worker cargo must be a mineral-count object")
    minerals = [math.tanh(_finite_number(cargo.get(name), f"cargo.{name}")) for name in MINERAL_NAMES]
    scene = raw.get("scene")
    if not isinstance(scene, str):
        raise ValueError("Worker scene must be a string")
    ticks = _finite_number(info.get("physics_ticks"), "physics_ticks")
    if ticks < 0 or not ticks.is_integer():
        raise ValueError("Worker physics_ticks must be a nonnegative integer")
    if isinstance(max_steps, (bool, np.bool_)) or not isinstance(max_steps, (int, np.integer)) or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")

    encoded[TILE_FEATURE_COUNT:] = (
        math.tanh(x / 36.0), math.tanh(y / 600.0),
        2.0 * (x - math.floor(x)) - 1.0, 2.0 * (y - math.floor(y)) - 1.0,
        math.tanh(vx / 10.0), math.tanh(vy / 10.0),
        *flags,
        max(-1.0, min(1.0, resources["fuel"] / resources["max_fuel"])),
        max(-1.0, min(1.0, resources["hp"] / resources["max_hp"])),
        max(0.0, min(1.0, resources["cargo_weight"] / resources["cargo_capacity"])),
        math.tanh(resources["max_fuel"] / 10.0),
        math.tanh(resources["max_hp"] / 10.0),
        math.tanh(resources["cargo_capacity"] / 7.0),
        *minerals, float(scene == "Game"), min(1.0, ticks / (5 * max_steps)),
    )
    return encoded


class Action(IntEnum):
    IDLE = 0
    LEFT = 1
    RIGHT = 2
    UP = 3
    DOWN = 4


class OrebitError(RuntimeError):
    """A worker launch, transport, or protocol failure, including engine logs."""


class OrebitEnv(gym.Env[NDArray[np.float32], int]):
    """Control one isolated Orebit episode with normalized model observations.

    ``path`` is the Godot project directory (or the repository containing it).
    ``godot_bin`` overrides GODOT_BIN, the bundled engine, and PATH lookup, in
    that order. ``timeout`` bounds startup and each subsequent request in seconds.
    Five discrete actions advance five fixed 50 Hz ticks, unless the episode
    ends sooner. Observations are fresh float32 vectors in ``Box(-1, 1, (677,))``:
    648 one-hot tile features followed by the 29 named ``SCALAR_NAMES``. Raw
    game state is available only through ``info["raw_observation"]``.
    Rendering is unsupported; ``render_mode`` must be ``None``.
    """

    metadata = {"render_modes": []}
    action_count = len(Action)
    action_names = tuple(action.name for action in Action)
    _MAX_MESSAGE_BYTES = 1024 * 1024
    # The world generator uses signed 32-bit seeds; JSON must preserve integers.
    _MAX_INTEGER = (1 << 31) - 1

    def __init__(
        self,
        *,
        godot_bin: str | os.PathLike[str] | None = None,
        path: str | os.PathLike[str] | None = None,
        timeout: float = 30.0,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        if render_mode is not None:
            raise ValueError("OrebitEnv is headless; render_mode must be None")
        self.render_mode = None
        self.action_space = spaces.Discrete(len(Action))
        self.observation_space = spaces.Box(-1.0, 1.0, shape=(OBSERVATION_SIZE,), dtype=np.float32)
        self._max_steps = 300
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a finite positive number")
        try:
            self.timeout = float(timeout)
        except OverflowError as error:
            raise ValueError("timeout must be a finite positive number") from error
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be a finite positive number")

        repository = Path(__file__).resolve().parents[1]
        project = Path(path).expanduser().resolve() if path is not None else repository / "godot"
        if not (project / "project.godot").is_file() and (project / "godot" / "project.godot").is_file():
            project = project / "godot"
        if not (project / "project.godot").is_file():
            raise ValueError(f"No Godot project.godot found in {project}")
        self.path = project
        self._godot_bin = godot_bin
        self._repository = repository
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._directory: Path | None = None
        self._server: socket.socket | None = None
        self._connection: socket.socket | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handles: list[BinaryIO] = []
        self._pending = bytearray()
        self._command: list[str] = []
        self._ready = False
        self._terminal = False

    def __enter__(self) -> OrebitEnv:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if exc_type is None:
            self.close()
        else:
            # Preserve the original exception if shutdown also encounters trouble.
            try:
                self.close()
            except OrebitError:
                pass

    def reset(
        self, *, seed: int | None = None, options: Mapping[str, Any] | None = None
    ) -> tuple[NDArray[np.float32], dict[str, Any]]:
        """Start a fresh worker; options are max_steps and initial_fuel only.

        Explicit seeds are nonnegative signed-32-bit integers. ``None`` draws a
        new worker seed from Gymnasium's persistent RNG, without retrying worlds.
        """
        if seed is not None:
            self._validate_integer("seed", seed, minimum=0)
            seed = int(seed)
        if options is None:
            options = {}
        if not isinstance(options, Mapping):
            raise TypeError("options must be a mapping or None")
        unknown = set(options) - {"max_steps", "initial_fuel"}
        if unknown:
            raise ValueError(f"Unknown reset options: {list(unknown)!r}")
        max_steps = options.get("max_steps", 300)
        self._validate_integer("max_steps", max_steps, minimum=1)
        initial_fuel = options.get("initial_fuel")
        if initial_fuel is not None:
            if isinstance(initial_fuel, bool) or not isinstance(initial_fuel, (int, float)):
                raise TypeError("initial_fuel must be a finite number or None")
            try:
                initial_fuel = float(initial_fuel)
            except OverflowError as error:
                raise ValueError("initial_fuel must be finite") from error
            if not math.isfinite(initial_fuel):
                raise ValueError("initial_fuel must be finite")

        self.close()
        super().reset(seed=seed)
        worker_seed = seed if seed is not None else int(self.np_random.integers(0, self._MAX_INTEGER + 1))
        self._max_steps = int(max_steps)
        try:
            binary = self._find_godot()
            self._temporary = tempfile.TemporaryDirectory(prefix="orebit-rl-")
            self._directory = Path(self._temporary.name).resolve()
            config_path = self._directory / "config.json"
            config_path.write_text(
                json.dumps({"seed": worker_seed, "max_steps": int(max_steps),
                            "initial_fuel": initial_fuel, "directory": str(self._directory)},
                           allow_nan=False),
                encoding="utf-8",
            )
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.bind(("127.0.0.1", 0))
            self._server.listen(1)
            port = self._server.getsockname()[1]
            token = secrets.token_hex(32)
            self._command = [
                binary, "--headless", "--fixed-fps", "50", "--disable-render-loop",
                "--log-file", str(self._directory / "engine.log"),
                "--path", str(self.path), "--script", "res://scripts/rl_worker.gd",
                "--", f"--rl-config={config_path}", f"--rl-port={port}",
                f"--rl-token={token}", f"--seed={worker_seed}", "--mode=private",
            ]
            stdout = (self._directory / "stdout.log").open("wb")
            self._log_handles.append(stdout)
            stderr = (self._directory / "stderr.log").open("wb")
            self._log_handles.append(stderr)
            deadline = time.monotonic() + self.timeout
            self._process = subprocess.Popen(
                self._command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                cwd=self.path,
            )
            self._accept(deadline)
            hello = self._receive(deadline)
            if hello.get("token") != token:
                raise ValueError("Worker authentication token mismatch")
            result = self._receive(deadline)
            observation, info = self._state(result)
            self._ready = True
            self._terminal = False
            return observation, info
        except Exception as error:
            raise self._failure("reset", error) from error

    def step(self, action: int | np.integer | Action) -> tuple[NDArray[np.float32], float, bool, bool, dict[str, Any]]:
        """Advance one decision; never return a fabricated state on worker failure."""
        if isinstance(action, (bool, np.bool_)) or not isinstance(action, (int, np.integer)):
            raise TypeError("action must be an integer or Action, not bool")
        if not 0 <= action < self.action_count:
            raise ValueError(f"action must be in [0, {self.action_count - 1}]")
        if not self._ready:
            raise RuntimeError("Call reset() before step()")
        if self._terminal:
            raise RuntimeError("Episode has ended; call reset() before another step()")
        try:
            deadline = time.monotonic() + self.timeout
            self._send({"command": "step", "action": int(action)}, deadline)
            result = self._receive(deadline)
            observation, info = self._state(result)
            terminated, truncated = result.get("terminated"), result.get("truncated")
            if type(terminated) is not bool or type(truncated) is not bool:
                raise ValueError("Worker step flags must be JSON booleans")
            reward = result.get("reward")
            if isinstance(reward, bool) or not isinstance(reward, (int, float)):
                raise ValueError("Worker reward must be a finite number")
            reward = float(reward)
            if not math.isfinite(reward):
                raise ValueError("Worker reward must be finite")
            self._terminal = terminated or truncated
            return observation, reward, terminated, truncated, info
        except Exception as error:
            raise self._failure("step", error) from error

    def close(self) -> None:
        """Ask the worker to close, then reap it and remove all runtime files."""
        failure: Exception | None = None
        try:
            if self._process is not None:
                if self._process.poll() is not None:
                    raise RuntimeError(f"Worker exited unexpectedly ({self._process.returncode})")
                if self._connection is not None:
                    deadline = time.monotonic() + min(self.timeout, 2.0)
                    self._send({"command": "close"}, deadline)
                    response = self._receive(deadline)
                    if response.get("closed") is not True:
                        raise ValueError("Worker did not acknowledge close")
                    try:
                        self._process.wait(timeout=min(self.timeout, 2.0))
                    except subprocess.TimeoutExpired as error:
                        raise RuntimeError("Worker acknowledged close but did not exit") from error
        except Exception as error:
            failure = error
        if failure is not None:
            raise self._failure("close", failure) from failure
        self._stop()
        self._cleanup()

    @classmethod
    def _validate_integer(cls, name: str, value: Any, *, minimum: int) -> None:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise TypeError(f"{name} must be an integer, not bool")
        if not minimum <= value <= cls._MAX_INTEGER:
            raise ValueError(f"{name} must be between {minimum} and {cls._MAX_INTEGER}")

    def _find_godot(self) -> str:
        configured = self._godot_bin if self._godot_bin is not None else os.environ.get("GODOT_BIN")
        if configured is not None:
            candidate = os.fspath(configured)
            if not candidate:
                raise ValueError("godot_bin/GODOT_BIN must not be empty")
            located = shutil.which(os.path.expanduser(candidate))
            if located is None:
                raise FileNotFoundError(f"Configured Godot executable not found or not executable: {candidate}")
            return str(Path(located).resolve())
        bundled = self._repository / "verification/tools/Godot.app/Contents/MacOS/Godot"
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return str(bundled)
        located = shutil.which("godot")
        if located is None:
            raise FileNotFoundError("Godot not found; set GODOT_BIN or pass godot_bin")
        return str(Path(located).resolve())

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for the Godot worker")
        return remaining

    def _accept(self, deadline: float) -> None:
        assert self._server is not None
        assert self._process is not None
        while True:
            if self._process.poll() is not None:
                raise RuntimeError(f"Worker exited before connecting ({self._process.returncode})")
            self._server.settimeout(min(self._remaining(deadline), 0.1))
            try:
                self._connection, _ = self._server.accept()
                self._server.close()
                self._server = None
                return
            except socket.timeout:
                continue

    def _send(self, message: dict[str, Any], deadline: float) -> None:
        if self._connection is None:
            raise RuntimeError("Worker connection is not available")
        self._connection.settimeout(self._remaining(deadline))
        self._connection.sendall((json.dumps(message, allow_nan=False) + "\n").encode("utf-8"))

    @staticmethod
    def _invalid_constant(value: str) -> Any:
        raise ValueError(f"Non-finite JSON constant from worker: {value}")

    def _receive(self, deadline: float) -> dict[str, Any]:
        if self._connection is None:
            raise RuntimeError("Worker connection is not available")
        while True:
            newline = self._pending.find(b"\n")
            if newline >= 0:
                if newline > self._MAX_MESSAGE_BYTES:
                    raise ValueError("Worker message exceeds protocol size limit")
                line = bytes(self._pending[:newline])
                del self._pending[:newline + 1]
                message = json.loads(line.decode("utf-8"), parse_constant=self._invalid_constant)
                if not isinstance(message, dict):
                    raise ValueError("Worker message must be a JSON object")
                if "error" in message:
                    raise RuntimeError(f"Worker error: {message['error']}")
                return message
            if len(self._pending) > self._MAX_MESSAGE_BYTES:
                raise ValueError("Worker message exceeds protocol size limit")
            self._connection.settimeout(self._remaining(deadline))
            chunk = self._connection.recv(65536)
            if not chunk:
                raise ConnectionError("Worker disconnected before sending a complete reply")
            self._pending.extend(chunk)

    def _state(self, result: dict[str, Any]) -> tuple[NDArray[np.float32], dict[str, Any]]:
        raw, info = result.get("observation"), result.get("info")
        if not isinstance(raw, dict) or not isinstance(info, dict):
            raise ValueError("Worker result must contain observation and info objects")
        observation = _encode_observation(raw, info, self._max_steps)
        info["raw_observation"] = raw
        return observation, info

    def _stop(self) -> None:
        self._ready = False
        self._terminal = False
        for connection in (self._connection, self._server):
            if connection is not None:
                connection.close()
        self._connection = None
        self._server = None
        self._pending.clear()
        if self._process is not None:
            if self._process.poll() is None:
                try:
                    self._process.terminate()
                except ProcessLookupError:
                    # The engine may exit between poll() and terminate().
                    pass
                try:
                    self._process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    try:
                        self._process.kill()
                    except ProcessLookupError:
                        pass
                    self._process.wait()
            else:
                self._process.wait()
        for handle in self._log_handles:
            handle.close()
        self._log_handles.clear()

    def _cleanup(self) -> None:
        self._process = None
        self._command = []
        self._directory = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def _failure(self, operation: str, error: Exception) -> OrebitError:
        # Reap first so redirected stdout/stderr and engine.log are complete.
        self._stop()
        details = [f"Orebit {operation} failed: {type(error).__name__}: {error}"]
        if self._command:
            details.append("Launch: " + shlex.join(self._command))
        if self._process is not None:
            details.append(f"Worker exit code: {self._process.returncode}")
        if self._directory is not None:
            for name in ("stdout.log", "stderr.log", "engine.log"):
                log_path = self._directory / name
                try:
                    contents = log_path.read_text(encoding="utf-8", errors="replace")
                except OSError as log_error:
                    contents = f"[unavailable: {log_error}]"
                details.append(f"--- {name} ---\n{contents}")
        self._cleanup()
        return OrebitError("\n".join(details))
