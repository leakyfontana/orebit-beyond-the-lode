"""Validate runtime capture archives and export them to real Minari datasets.

Run directly (``python orebit_rl/capture_export.py --help``) to avoid importing
orebit_rl's unrelated environment registration. Validation needs only stdlib.
No environment, game process, policy, or training loop is created here.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import importlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


MAX_COMPRESSED = 256 * 1024
CHUNK_NAME = re.compile(r"[0-9]{8}\.jsonl\.gz\Z")
SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")
PROVENANCE = ("schema_version", "mode", "physics_hz", "build", "engine",
              "state_fields", "source", "terrain", "actor")
INSTALL = "python -m pip install -r orebit_rl/capture-requirements.txt"


class ExportError(ValueError):
    """A capture cannot be exported without losing or inventing semantics."""


@dataclass
class Chunk:
    path: Path
    manifest: dict[str, Any]
    transitions: list[dict[str, Any]]
    sha256: str


@dataclass
class Segment:
    manifest: dict[str, Any]
    transitions: list[dict[str, Any]] = field(default_factory=list)
    sources: list[tuple[int, str, str]] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)


def _schema():
    # This shares the server's strict allowlists, not its HTTP/database runtime.
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module("automation.coop.capture")


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False)


def discover(inputs: list[str]) -> list[Path]:
    """Select only canonical chunk names; authority archives are not chunks."""
    paths: set[Path] = set()
    for name in inputs:
        path = Path(name)
        if path.is_dir():
            found = [p for p in path.rglob("*.jsonl.gz")
                     if CHUNK_NAME.fullmatch(p.name)
                     and "authority" not in p.relative_to(path).parts]
            if not found:
                raise ExportError(f"No capture chunks found in {path}")
            paths.update(p.resolve() for p in found)
        elif path.is_file():
            paths.add(path.resolve())
        else:
            raise ExportError(f"Capture input does not exist: {path}")
    return sorted(paths)


def read_chunk(path: Path, schema: Any) -> Chunk:
    if path.stat().st_size > MAX_COMPRESSED:
        raise ExportError(f"Compressed chunk exceeds 256 KiB: {path}")
    body = path.read_bytes()
    try:
        raw = schema.decompress_chunk(body)
        header = json.loads(raw.split(b"\n", 1)[0])
        session = header["session_id"]
        index = header["chunk_index"]
        if not isinstance(session, str) or not SESSION_ID.fullmatch(session) or type(index) is not int:
            raise ExportError("Invalid capture session/chunk identity")
        # Share the exact strict server schema, including duplicate-key rejection.
        canonical = schema.validate_chunk(raw, session, index)
        records = [json.loads(line) for line in canonical.splitlines()]
    except (ValueError, KeyError, TypeError, OSError, EOFError) as exc:
        raise ExportError(f"Invalid capture chunk: {path} ({type(exc).__name__})") from exc
    manifest = records[0]
    if SESSION_ID.fullmatch(path.parent.name):
        if manifest["session_id"] != path.parent.name:
            raise ExportError(f"Session directory disagrees with manifest: {path}")
        if CHUNK_NAME.fullmatch(path.name) and int(path.name[:8]) != index:
            raise ExportError(f"Chunk filename disagrees with manifest: {path}")
    return Chunk(path, manifest, records[1:], hashlib.sha256(body).hexdigest())


def assemble(chunks: list[Chunk], allow_incomplete: bool) -> list[Segment]:
    """Join only proven adjacent intervals; never fabricate a missing transition."""
    if not chunks:
        raise ExportError("No capture chunks supplied")
    reference = {key: chunks[0].manifest[key] for key in PROVENANCE}
    groups: dict[str, list[Chunk]] = {}
    identities: set[tuple[str, int]] = set()
    for chunk in chunks:
        manifest = chunk.manifest
        if {key: manifest[key] for key in PROVENANCE} != reference:
            raise ExportError("Mixed schema/build/engine/mode provenance; export separately")
        identity = (manifest["session_id"], manifest["chunk_index"])
        if identity in identities:
            raise ExportError(f"Duplicate session/chunk identity: {identity}")
        identities.add(identity)
        # Episode IDs survive transport capability renewal; sessions do not.
        groups.setdefault(manifest["episode_id"], []).append(chunk)
    segments: list[Segment] = []
    for identity, group in sorted(groups.items()):
        group.sort(key=lambda chunk: chunk.manifest["chunk_index"])
        first = group[0].manifest
        episode_provenance = {key: value for key, value in first.items()
                              if key not in ("checkpoint", "chunk_index", "session_id")}
        segment = Segment(first)
        previous_chunk: int | None = None
        previous: dict[str, Any] | None = None
        for chunk in group:
            manifest = chunk.manifest
            if {key: value for key, value in manifest.items()
                    if key not in ("checkpoint", "chunk_index", "session_id")} != episode_provenance:
                raise ExportError(f"Episode provenance changed: {identity}")
            if not chunk.transitions:
                raise ExportError(f"Chunk has no transitions: {chunk.path}")
            current = chunk.transitions[0]
            checkpoint = manifest["checkpoint"]
            if checkpoint != {"sequence": current["sequence"], "tick": current["tick"],
                              "observation": current["observation"]}:
                raise ExportError(f"Chunk checkpoint disagrees with transition: {chunk.path}")
            gap = None
            if previous is not None:
                if previous["terminated"] or previous["truncated"]:
                    raise ExportError(f"Episode continues after a boundary: {identity}")
                if current["sequence"] <= previous["sequence"]:
                    raise ExportError(f"Overlapping/reversed transition sequence: {identity}")
                if previous_chunk is not None and manifest["chunk_index"] <= previous_chunk:
                    raise ExportError(f"Overlapping/reversed chunk index: {identity}")
                if current["sequence"] != previous["sequence"] + 1:
                    gap = "missing_transitions"
                if previous_chunk is not None and manifest["chunk_index"] != previous_chunk + 1:
                    gap = "missing_chunks"
                if gap is None and (current["tick"] != previous["next_tick"]
                                    or current["observation"] != previous["next_observation"]):
                    raise ExportError(f"Contiguous transition state/tick mismatch: {identity}")
                if gap is not None:
                    if current["tick"] < previous["next_tick"]:
                        raise ExportError(f"Reversed time across a capture gap: {identity}")
                    segment.incomplete.append(gap)
                    segments.append(segment)
                    segment = Segment(manifest, incomplete=[gap])
            if not segment.transitions and current["sequence"] != 0:
                segment.incomplete.append("missing_episode_start")
            for transition in chunk.transitions:
                if any(event["kind"] == "gap" for event in transition["events"]):
                    segment.incomplete.append("reported_capture_loss")
                segment.transitions.append(transition)
                segment.sources.append((manifest["chunk_index"], chunk.sha256, manifest["session_id"]))
            previous = chunk.transitions[-1]
            previous_chunk = manifest["chunk_index"]
        if previous is not None and not (previous["terminated"] or previous["truncated"]):
            segment.incomplete.append("missing_episode_end")
        segments.append(segment)
    for segment in segments:
        segment.incomplete = sorted(set(segment.incomplete))
    incomplete = sum(bool(segment.incomplete) for segment in segments)
    if incomplete and not allow_incomplete:
        reasons = sorted({reason for segment in segments for reason in segment.incomplete})
        raise ExportError(f"{incomplete} incomplete segment(s): {', '.join(reasons)}; "
                          "supply missing chunks or explicitly use --allow-incomplete")
    return segments


def summary(chunks: list[Chunk], segments: list[Segment]) -> dict[str, Any]:
    return {"chunks": len(chunks), "sessions": len({c.manifest["session_id"] for c in chunks}),
            "episodes": len({c.manifest["episode_id"] for c in chunks}),
            "segments": len(segments), "transitions": sum(len(s.transitions) for s in segments),
            "incomplete_segments": sum(bool(s.incomplete) for s in segments),
            "terminated": sum(t["terminated"] for s in segments for t in s.transitions),
            "truncated": sum(t["truncated"] for s in segments for t in s.transitions),
            "build": chunks[0].manifest["build"]}


def export_dataset(segments: list[Segment], dataset_id: str, weights: dict[str, float],
                   schema: Any):
    try:
        import gymnasium as gym
        import minari
        import numpy as np
        import h5py  # noqa: F401 -- require the selected real storage backend up front
        from PIL import Image  # noqa: F401 -- imported by Minari's HDF5 backend
        from minari.data_collector import EpisodeBuffer
    except ImportError as exc:
        raise ExportError(f"Minari export dependencies missing. Install with: {INSTALL}") from exc
    version = importlib.metadata.version("minari")
    if version != "0.5.4":
        raise ExportError(f"Supported Minari version is 0.5.4 (installed {version}). Run: {INSTALL}")
    state_fields = segments[0].manifest["state_fields"]
    kinds = sorted(schema.COMMAND_KINDS)
    kind_codes = {kind: index + 1 for index, kind in enumerate(kinds)}
    slots = max(1, max(len(t["action"]["commands"]) for s in segments for t in s.transitions))
    # Numeric flattening avoids ragged Sequence backend limitations, without
    # discarding any command. The count disambiguates padding from real commands.
    action_size = 3 + 4 * slots
    low = np.zeros(action_size, dtype=np.float64)
    high = np.zeros(action_size, dtype=np.float64)
    low[:3], high[:3] = [-1, -1, 0], [1, 1, slots]
    for slot in range(slots):
        low[3 + 4 * slot:7 + 4 * slot] = [0, -1, 0, -1]
        high[3 + 4 * slot:7 + 4 * slot] = [len(kinds), 9, 1e15, 5]
    action_space = gym.spaces.Box(low=low, high=high, dtype=np.float64)
    observation_space = gym.spaces.Dict({
        "state": gym.spaces.Box(-1e15, 1e15, (len(state_fields),), np.float64),
        "tiles": gym.spaces.Box(-1, 19, (81,), np.int64),
    })
    buffers = []
    for segment in segments:
        transitions = segment.transitions
        observations = [transitions[0]["observation"]] + [t["next_observation"] for t in transitions]
        actions = np.zeros((len(transitions), action_size), dtype=np.float64)
        rewards = []
        for row, transition in enumerate(transitions):
            action = transition["action"]
            actions[row, :3] = [*action["movement"], len(action["commands"])]
            for slot, command in enumerate(action["commands"]):
                actions[row, 3 + slot * 4:7 + slot * 4] = [
                    kind_codes[command["kind"]], command["item"], command["amount"], command["category"]]
            reward = math.fsum(weights[key] * transition["reward_components"][key] for key in weights)
            if not math.isfinite(reward):
                raise ExportError("Reward weights overflowed a finite capture component")
            rewards.append(reward)
        # Infos are observation-aligned (T+1): slot 0 describes reset/checkpoint;
        # slot i+1 describes transition i ending at observation i+1.
        infos = {
            "has_transition": np.asarray([False] + [True] * len(transitions)),
            "sequence": np.asarray([-1] + [t["sequence"] for t in transitions], dtype=np.int64),
            "tick": np.asarray([transitions[0]["tick"]] + [t["next_tick"] for t in transitions], dtype=np.int64),
            "start_tick": np.asarray([transitions[0]["tick"]] + [t["tick"] for t in transitions], dtype=np.int64),
            "chunk_index": np.asarray([segment.sources[0][0]] + [s[0] for s in segment.sources], dtype=np.int64),
            "chunk_sha256": [segment.sources[0][1]] + [s[1] for s in segment.sources],
            "capture_session_id": [segment.sources[0][2]] + [s[2] for s in segment.sources],
            "commands_json": ["[]"] + [_json(t["action"]["commands"]) for t in transitions],
            "events_json": ["[]"] + [_json(t["events"]) for t in transitions],
            "reason": ["checkpoint"] + [t["reason"] for t in transitions],
            "reward_components": {key: np.asarray([0.0] + [t["reward_components"][key] for t in transitions],
                                                  dtype=np.float64) for key in weights},
        }
        buffers.append(EpisodeBuffer(
            seed=segment.manifest["seed"],
            options={"capture_manifest_json": _json(segment.manifest),
                     "capture_incomplete_json": _json(segment.incomplete),
                     "capture_complete": not segment.incomplete,
                     "capture_first_sequence": transitions[0]["sequence"],
                     "capture_last_sequence": transitions[-1]["sequence"]},
            observations={"state": np.asarray([o["state"] for o in observations], dtype=np.float64),
                          "tiles": np.asarray([o["tiles"] for o in observations], dtype=np.int64)},
            actions=actions, rewards=rewards,
            terminations=[t["terminated"] for t in transitions],
            truncations=[t["truncated"] for t in transitions], infos=infos))
    metadata = {"capture_schema_version": 1, "state_fields": state_fields,
                "actor": segments[0].manifest["actor"],
                "action_encoding": {"movement": [0, 1], "command_count": 2,
                                    "command_slots": slots, "slot_start": 3, "slot_width": 4,
                                    "slot_fields": ["kind", "item", "amount", "category"],
                                    "kind_codes": kind_codes, "padding": 0},
                "reward_weights": weights, "infos_alignment": "T+1; transition i at infos[i+1]",
                "incomplete_policy": "split without bridging or synthesizing terminal/truncated flags",
                "authority": "client server_sequence pointers retained; authoritative archives remain separate"}
    dataset = minari.create_dataset_from_buffers(
        dataset_id=dataset_id, buffer=buffers, observation_space=observation_space,
        action_space=action_space, env=None, eval_env=None, data_format="hdf5", jpeg_encoding=False,
        algorithm_name=f'{segments[0].manifest["actor"]}-runtime-capture',
        description="Orebit runtime capture. " + _json(metadata),
        requirements=["minari[hdf5]==0.5.4", "gymnasium==1.4.0"])
    dataset.storage.update_metadata({"orebit_capture": metadata})
    return dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "export"):
        sub = subparsers.add_parser(command)
        sub.add_argument("inputs", nargs="+", help="Canonical archive root, session directory, or chunk files")
        sub.add_argument("--allow-incomplete", action="store_true",
                         help="Export explicit incomplete segments, never bridge gaps or invent boundary flags")
        if command == "export":
            sub.add_argument("--dataset-id", required=True, help="New local Minari dataset ID, e.g. orebit/capture-v0")
            for component in ("money", "hp", "fuel"):
                sub.add_argument(f"--{component}-weight", type=float, default=0.0,
                                 help="Reward coefficient (default 0: no imposed objective)")
    args = parser.parse_args(argv)
    try:
        schema = _schema()
        chunks = [read_chunk(path, schema) for path in discover(args.inputs)]
        segments = assemble(chunks, args.allow_incomplete)
        result = summary(chunks, segments)
        if args.command == "export":
            weights = {key: getattr(args, f"{key}_weight") for key in ("money", "hp", "fuel")}
            if not all(math.isfinite(weight) for weight in weights.values()):
                raise ExportError("Reward weights must be finite")
            dataset = export_dataset(segments, args.dataset_id, weights, schema)
            result.update(dataset_id=dataset.spec.dataset_id,
                          minari_version=importlib.metadata.version("minari"), reward_weights=weights)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ExportError, OSError, ImportError, ValueError, OverflowError, RecursionError) as exc:
        print(f"capture export: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
