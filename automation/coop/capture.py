"""Private capability-scoped gameplay archives; no account or chat data is accepted."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum, auto
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import time
import zlib

MAX_COMPRESSED = 256 * 1024
MAX_RAW = 2 * 1024 * 1024
MAX_TRANSITIONS = 1000
MAX_SESSIONS = 512
SESSION_LIFETIME = 24 * 3600
MAX_CHUNKS = 4096
MAX_SESSION_BYTES = 256 * 1024 * 1024
DISK_RESERVE = 16 * 1024 * 1024
STATE_FIELDS = ["x", "y", "vx", "vy", "fuel", "hp", "max_fuel", "max_hp", "money", "cargo_capacity", "alive", "paused", "facing", "in_shop", "digging", "grounded"] + [f"item_{i}" for i in range(6)] + [f"cargo_{i}" for i in range(10)] + [f"upgrade_{i}" for i in range(6)] + ["cargo_weight"] + [f"peer_{i}_{name}" for i in range(4) for name in ("present", "x", "y", "facing", "alive")] + ["ui_panel_mask", "selected_shop_item", "selected_upgrade_category", "selected_upgrade_tier"]
COMMAND_KINDS = {"use_item", "buy_item", "buy_upgrade", "buy_fuel", "buy_hull", "sell_all", "drop_mineral", "shop_enter", "shop_exit"}
EVENT_KINDS = {"server", "server_gap", "life", "gap", "timing"}
REASONS = {"running", "death", "round_end", "scene_change", "disconnect", "shutdown"}
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PACKETS = {"joined", "round_started", "round_rejected", "state_ack", "state_sync", "state", "mined", "transfer_result", "building_result", "blast_result", "pvp_tick", "vulcan_tick", "worm_death", "worm_respawn", "player_joined", "player_left", "pong", "capture_linked"}


class CaptureError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def invalid():
    raise CaptureError("invalid_capture", "Capture does not match the gameplay schema.")


def number(value, low=-1e15, high=1e15, integer=False):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value) or (integer and value != int(value)):
        invalid()
    return value


def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        invalid()


def observation(value):
    keys(value, ("state", "tiles"))
    if not isinstance(value["state"], list) or len(value["state"]) != len(STATE_FIELDS):
        invalid()
    for item in value["state"]:
        number(item)
    if not isinstance(value["tiles"], list) or len(value["tiles"]) != 81:
        invalid()
    for tile in value["tiles"]:
        number(tile, -1, 19, True)
        if tile not in (-1, 0, 1, 2, 3, 4, *range(10, 20)):
            invalid()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            invalid()
        result[key] = value
    return result


class TransitionOutcome(Enum):
    RUNNING = auto()
    TERMINATED = auto()
    TRUNCATED = auto()

    @classmethod
    def validate(cls, record, mode):
        terminated, truncated, reason = record["terminated"], record["truncated"], record["reason"]
        if type(terminated) is not bool or type(truncated) is not bool or not isinstance(reason, str) or reason not in REASONS or (terminated and truncated):
            invalid()
        outcome = cls.TERMINATED if terminated else cls.TRUNCATED if truncated else cls.RUNNING
        terminal = (mode == "private" and reason == "death") or (mode == "pvp" and reason == "round_end")
        if (outcome is cls.TERMINATED and not terminal) or (reason == "round_end" and outcome is not cls.TERMINATED):
            invalid()
        if (outcome is cls.RUNNING) != (reason == "running"):
            invalid()
        return outcome


class ChainState(Enum):
    CHECKPOINT = auto()
    CONTINUING = auto()
    TERMINAL = auto()


@dataclass
class TransitionChain:
    checkpoint: dict
    state: ChainState = ChainState.CHECKPOINT
    previous: dict | None = None

    def validate_link(self, record):
        if self.state is ChainState.CHECKPOINT:
            if any(record[key] != self.checkpoint[key] for key in ("sequence", "tick", "observation")):
                invalid()
        elif self.state is ChainState.TERMINAL:
            invalid()
        elif record["sequence"] != self.previous["sequence"] + 1 or record["tick"] != self.previous["next_tick"] or record["observation"] != self.previous["next_observation"]:
            invalid()

    def advance(self, record, outcome):
        self.previous = record
        self.state = ChainState.CONTINUING if outcome is TransitionOutcome.RUNNING else ChainState.TERMINAL


def _records(raw, session_id, chunk_index):
    if not isinstance(session_id, str) or not HEX32.fullmatch(session_id):
        invalid()
    if not isinstance(raw, bytes) or len(raw) > MAX_RAW or not raw.endswith(b"\n"):
        invalid()
    lines = raw.splitlines()
    if not 2 <= len(lines) <= MAX_TRANSITIONS + 1:
        invalid()
    try:
        records = [json.loads(line, object_pairs_hook=unique_object) for line in lines]
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        invalid()
    manifest = records[0]
    keys(manifest, ("type", "schema_version", "session_id", "episode_id", "chunk_index", "mode", "seed", "physics_hz", "build", "engine", "state_fields", "checkpoint", "started_at_ms", "source", "terrain", "actor"))
    if manifest["type"] != "manifest" or manifest["schema_version"] != 1 or manifest["session_id"] != session_id or manifest["chunk_index"] != chunk_index or not isinstance(manifest["episode_id"], str) or not HEX32.fullmatch(manifest["episode_id"]):
        invalid()
    if manifest["mode"] not in ("private", "coop", "pvp", "vulcan") or manifest["physics_hz"] != 50 or manifest["state_fields"] != STATE_FIELDS or manifest["source"] != "runtime_scripts_sha256" or manifest["terrain"] != "visible_local_9x9_v1":
        invalid()
    if manifest["actor"] not in ("human", "replay"):
        invalid()
    number(manifest["schema_version"], 1, 1, True)
    number(manifest["chunk_index"], 0, 99999999, True)
    number(manifest["seed"], -2**63, 2**63 - 1, True)
    number(manifest["physics_hz"], 50, 50, True)
    number(manifest["started_at_ms"], 0, 1e15, True)
    if not isinstance(manifest["build"], str) or not HEX64.fullmatch(manifest["build"]) or not isinstance(manifest["engine"], str) or not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}", manifest["engine"]):
        invalid()
    checkpoint = manifest["checkpoint"]
    keys(checkpoint, ("sequence", "tick", "observation"))
    number(checkpoint["sequence"], 0, 1e15, True)
    number(checkpoint["tick"], 0, 1e15, True)
    observation(checkpoint["observation"])
    chain = TransitionChain(checkpoint)
    for record in records[1:]:
        keys(record, ("type", "sequence", "tick", "next_tick", "observation", "action", "next_observation", "reward_components", "terminated", "truncated", "reason", "events"))
        if record["type"] != "transition":
            invalid()
        for name in ("sequence", "tick", "next_tick"):
            number(record[name], 0, 1e15, True)
        if record["next_tick"] < record["tick"]:
            invalid()
        observation(record["observation"])
        observation(record["next_observation"])
        chain.validate_link(record)
        action = record["action"]
        keys(action, ("movement", "commands"))
        if not isinstance(action["movement"], list) or len(action["movement"]) != 2 or not isinstance(action["commands"], list) or len(action["commands"]) > 64:
            invalid()
        for axis in action["movement"]:
            number(axis, -1, 1)
        for command in action["commands"]:
            keys(command, ("kind", "item", "amount", "category"))
            if not isinstance(command["kind"], str) or command["kind"] not in COMMAND_KINDS:
                invalid()
            number(command["item"], -1, 9, True)
            number(command["category"], -1, 5, True)
            number(command["amount"], 0, 1e15)
        keys(record["reward_components"], ("money", "hp", "fuel"))
        for component in record["reward_components"].values():
            number(component)
        outcome = TransitionOutcome.validate(record, manifest["mode"])
        if not isinstance(record["events"], list) or len(record["events"]) > 128:
            invalid()
        for event in record["events"]:
            if not isinstance(event, dict) or not isinstance(event.get("kind"), str):
                invalid()
            kind = event["kind"]
            fields = {"server": ("server_sequence", "session_id"), "server_gap": ("first_sequence", "last_sequence", "session_id"), "life": ("alive",), "gap": ("first_sequence", "last_sequence"), "timing": ("elapsed_ms",)}.get(kind)
            if fields is None:
                invalid()
            keys(event, ("kind", *fields))
            for name in fields:
                if name == "alive":
                    if type(event[name]) is not bool:
                        invalid()
                elif name == "session_id":
                    if not isinstance(event[name], str) or not HEX32.fullmatch(event[name]):
                        invalid()
                else:
                    number(event[name], 0, 1e15, True)
            if kind in ("gap", "server_gap") and event["first_sequence"] > event["last_sequence"]:
                invalid()
        chain.advance(record, outcome)
    return records


def canonical(records):
    return ("\n".join(json.dumps(record, separators=(",", ":"), sort_keys=True, ensure_ascii=True, allow_nan=False) for record in records) + "\n").encode()


def validate_chunk(raw, session_id, chunk_index):
    return canonical(_records(raw, session_id, chunk_index))


def decompress_chunk(body):
    if not body or len(body) > MAX_COMPRESSED:
        raise CaptureError("capture_too_large", "Compressed capture exceeds the request limit.", 413)
    try:
        stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = stream.decompress(body, MAX_RAW + 1)
        if len(raw) > MAX_RAW or stream.unconsumed_tail:
            raise CaptureError("capture_too_large", "Decompressed capture exceeds the request limit.", 413)
        if not stream.eof or stream.unused_data:
            invalid()
        return raw
    except zlib.error:
        invalid()


def decode_chunk(body, session_id, chunk_index):
    return _records(decompress_chunk(body), session_id, chunk_index)


class CapabilityState(Enum):
    ACTIVE = auto()
    EXPIRED = auto()
    MISSING = auto()

    @classmethod
    def at(cls, capability, now):
        # Registry insertion/removal are issuance/pruning; expiry is clock-derived.
        if capability is None:
            return cls.MISSING
        return cls.EXPIRED if capability.expires <= now else cls.ACTIVE


class QuotaWindowState(Enum):
    ELAPSED = auto()
    ACCEPTING = auto()
    EXCEEDED = auto()


class AuthorityPreparationState(Enum):
    RESERVABLE = auto()
    GAP = auto()


@dataclass
class Capability:
    token_hash: bytes
    expires: float
    chunks: dict = field(default_factory=dict)
    stored_bytes: int = 0
    server_sequence: int = 0
    window: float = 0
    requests: int = 0

    def quota_state_at(self, now):
        if now - self.window >= 60:
            return QuotaWindowState.ELAPSED
        return QuotaWindowState.EXCEEDED if self.requests > 120 else QuotaWindowState.ACCEPTING

    def charge(self, now):
        if self.quota_state_at(now) is QuotaWindowState.ELAPSED:
            self.window, self.requests = now, 0
        self.requests += 1
        if self.quota_state_at(now) is QuotaWindowState.EXCEEDED:
            raise CaptureError("capture_rate_limited", "Capture request quota exceeded.", 429)

    def authority_state(self, size):
        return AuthorityPreparationState.GAP if self.stored_bytes + size > MAX_SESSION_BYTES else AuthorityPreparationState.RESERVABLE

    def reserve_authority(self, encoded):
        # A rejected byte reservation still consumes its authority sequence.
        self.server_sequence += 1
        if self.authority_state(len(encoded)) is AuthorityPreparationState.GAP:
            return self.server_sequence, None
        self.stored_bytes += len(encoded)
        return self.server_sequence, encoded


class ChunkWriteState(Enum):
    CANDIDATE = auto()
    ACCEPTED = auto()
    DUPLICATE = auto()
    CONFLICT = auto()
    CHUNK_LIMIT = auto()
    RESERVED = auto()
    WRITING = auto()
    COMMITTED = auto()
    REFUNDED = auto()


@dataclass
class ChunkWrite:
    capability: Capability
    index: int
    incoming_hash: bytes
    state: ChunkWriteState = ChunkWriteState.CANDIDATE
    size: int = 0

    def admit(self):
        assert self.state is ChunkWriteState.CANDIDATE
        if self.index in self.capability.chunks:
            self.state = ChunkWriteState.DUPLICATE if secrets.compare_digest(self.capability.chunks[self.index], self.incoming_hash) else ChunkWriteState.CONFLICT
        elif len(self.capability.chunks) >= MAX_CHUNKS:
            self.state = ChunkWriteState.CHUNK_LIMIT
        else:
            self.state = ChunkWriteState.ACCEPTED
        if self.state is ChunkWriteState.CONFLICT:
            raise CaptureError("capture_conflict", "This chunk index already contains different bytes.", 409)
        if self.state is ChunkWriteState.CHUNK_LIMIT:
            raise CaptureError("capture_quota", "Capture session chunk quota exceeded.", 429)

    def reserve(self, size):
        assert self.state is ChunkWriteState.ACCEPTED
        if self.capability.stored_bytes + size > MAX_SESSION_BYTES:
            raise CaptureError("capture_quota", "Capture session byte quota exceeded.", 429)
        self.size = size
        self.capability.stored_bytes += size
        self.state = ChunkWriteState.RESERVED

    def begin_write(self):
        assert self.state is ChunkWriteState.RESERVED
        self.state = ChunkWriteState.WRITING

    def refund(self):
        assert self.state is ChunkWriteState.WRITING
        self.capability.stored_bytes -= self.size
        self.state = ChunkWriteState.REFUNDED

    def commit(self):
        assert self.state is ChunkWriteState.WRITING
        self.capability.chunks[self.index] = self.incoming_hash
        self.state = ChunkWriteState.COMMITTED


class PublishState(Enum):
    PENDING = auto()
    FILE_SYNCED = auto()
    RENAMED = auto()
    DURABLE = auto()


class DescriptorState(Enum):
    CLOSED = auto()
    OWNED = auto()
    STREAM = auto()


@dataclass
class AtomicPublish:
    directory: Path
    filename: str
    temporary: Path = field(init=False)
    state: PublishState = PublishState.PENDING
    descriptor_state: DescriptorState = DescriptorState.CLOSED
    fd: int = -1

    def __post_init__(self):
        self.temporary = self.directory / (".pending-" + secrets.token_hex(16))

    def write(self, body):
        assert self.state is PublishState.PENDING and self.descriptor_state is DescriptorState.CLOSED
        self.fd = os.open(self.temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        self.descriptor_state = DescriptorState.OWNED
        try:
            with os.fdopen(self.fd, "wb") as output:
                self.descriptor_state = DescriptorState.STREAM
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
        finally:
            if self.descriptor_state is DescriptorState.STREAM:
                self.descriptor_state = DescriptorState.CLOSED
        self.state = PublishState.FILE_SYNCED

    def publish(self):
        assert self.state is PublishState.FILE_SYNCED
        os.replace(self.temporary, self.directory / self.filename)
        self.state = PublishState.RENAMED

    def sync_directory(self):
        assert self.state is PublishState.RENAMED
        directory_fd = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        self.state = PublishState.DURABLE

    def cleanup(self):
        if self.descriptor_state is DescriptorState.OWNED:
            os.close(self.fd)
            self.descriptor_state = DescriptorState.CLOSED
        self.temporary.unlink(missing_ok=True)


class CaptureStore:
    def __init__(self, root):
        self.root = Path(root).expanduser().absolute()
        self.sessions = OrderedDict()
        self.lock = threading.RLock()
        self.disk_lock = threading.Lock()
        self.upload_lock = threading.Lock()
        self.slots = asyncio.Semaphore(4)

    def _directory(self, path):
        created = not path.exists()
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise OSError("Unsafe capture directory")
        os.chmod(path, 0o700)
        if created:
            parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)

    def _prune(self):
        now = time.monotonic()
        for key in list(self.sessions):
            if CapabilityState.at(self.sessions[key], now) is CapabilityState.EXPIRED:
                del self.sessions[key]

    def disk_guard(self, incoming):
        usage = os.statvfs(self.root)
        total = usage.f_blocks * usage.f_frsize
        available = usage.f_bavail * usage.f_frsize
        if total <= 0 or total - available + incoming + DISK_RESERVE >= total * 0.8:
            raise CaptureError("capture_storage_full", "Capture storage is paused at its filesystem safety limit.", 507)

    def issue(self):
        try:
            with self.disk_lock:
                self._directory(self.root)
                self.disk_guard(MAX_COMPRESSED)
        except OSError:
            raise CaptureError("capture_unavailable", "Capture storage is temporarily unavailable.", 503) from None
        with self.lock:
            self._prune()
            if len(self.sessions) >= MAX_SESSIONS:
                raise CaptureError("capture_busy", "Capture session capacity is temporarily full.", 429)
            session, token = secrets.token_hex(16), secrets.token_urlsafe(32)
            self.sessions[session] = Capability(hashlib.sha256(token.encode()).digest(), time.monotonic() + SESSION_LIFETIME)
            return {"session_id": session, "token": token}

    def authenticate(self, session, token):
        with self.lock:
            if not isinstance(session, str) or not HEX32.fullmatch(session) or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", token):
                raise CaptureError("capture_unauthorized", "A valid capture capability is required.", 401)
            capability = self.sessions.get(session)
            if CapabilityState.at(capability, time.monotonic()) is not CapabilityState.ACTIVE or not secrets.compare_digest(capability.token_hash, hashlib.sha256(token.encode()).digest()):
                raise CaptureError("capture_unauthorized", "A valid capture capability is required.", 401)
            return capability

    def charge(self, session, token):
        with self.lock:
            capability = self.authenticate(session, token)
            capability.charge(time.monotonic())

    def _persist(self, directory, filename, body):
        self._directory(self.root)
        self._directory(self.root / directory.relative_to(self.root).parts[0])
        self._directory(directory)
        self.disk_guard(len(body) + 4096)
        publication = AtomicPublish(directory, filename)
        try:
            publication.write(body)
            publication.publish()
            publication.sync_directory()
        finally:
            publication.cleanup()

    def ingest(self, session, token, index, body):
        # Serialize uploads, not game packets: validation and fsync never hold
        # the small capability lock used by the gameplay send path.
        with self.upload_lock:
            with self.lock:
                capability = self.authenticate(session, token)
                if type(index) is not int or not 0 <= index <= 99999999:
                    invalid()
                transaction = ChunkWrite(capability, index, hashlib.sha256(body).digest())
                transaction.admit()
                if transaction.state is ChunkWriteState.DUPLICATE:
                    return {"status": "stored", "chunk_index": index, "duplicate": True}
            encoded = gzip.compress(canonical(decode_chunk(body, session, index)), compresslevel=6, mtime=0)
            with self.lock:
                transaction.reserve(len(encoded))
            try:
                with self.disk_lock:
                    transaction.begin_write()
                    self._persist(self.root / session, f"{index:08d}.jsonl.gz", encoded)
            except (OSError, CaptureError) as error:
                with self.lock:
                    transaction.refund()
                if isinstance(error, CaptureError):
                    raise
                raise CaptureError("capture_unavailable", "Capture storage is temporarily unavailable.", 503) from None
            with self.lock:
                transaction.commit()
            return {"status": "stored", "chunk_index": index, "duplicate": False}

    def prepare_authority(self, session, message, request_context=None):
        """Only explicit numeric/enum fields survive this trust boundary."""
        with self.lock:
            capability = self.sessions.get(session)
            packet = message.get("type")
            if CapabilityState.at(capability, time.monotonic()) is not CapabilityState.ACTIVE or packet not in PACKETS:
                return None
            data = {}
            for key in ("x", "y", "state_revision", "motion_seq", "seed", "round", "tick"):
                value = message.get(key)
                if type(value) in (int, float) and abs(value) <= 1e15 and math.isfinite(value):
                    data[key] = value
            if type(message.get("ore_code")) is int and 0 <= message["ore_code"] <= 23:
                data["ore_code"] = message["ore_code"]
            for key in ("accepted", "enter"):
                if type(message.get(key)) is bool:
                    data[key] = message[key]
            for key, allowed in {"method": {"drill", "blast"}, "ore": {"", "Ironium", "Bronzium", "Silverium", "Goldium", "Platinium", "Einsteinium", "Emerald", "Ruby", "Diamond", "Amazonite", "Rock"}, "item": {"Dynamite", "Plastic Explosives"}, "building": {"FuelShopManager", "MineralBuyerManager", "UpgradeShopUI", "ItemShopManager"}}.items():
                value = message.get(key)
                if isinstance(value, str) and value in allowed:
                    data[key] = value
            state = message.get("state")
            if isinstance(state, dict):
                safe_state = {}
                for key in ("x", "y", "vx", "vy", "drill_x", "drill_y", "respawn_at", "deepest_y", "player_money", "player_hp", "player_fuel", "alive", "facing"):
                    value = state.get(key)
                    if type(value) is bool or (type(value) in (int, float) and abs(value) <= 1e15 and math.isfinite(value)):
                        safe_state[key] = value
                for key, names in {"player_items": ("Reserve Fuel Tank", "Hull Repair Nanobots", "Dynamite", "Plastic Explosives", "Quantum Teleporter", "Matter Transmitter"), "player_cargo": ("Ironium", "Bronzium", "Silverium", "Goldium", "Platinium", "Einsteinium", "Emerald", "Ruby", "Diamond", "Amazonite")}.items():
                    values = state.get(key)
                    if isinstance(values, dict):
                        safe_state[key] = {name: value for name, value in values.items() if name in names and type(value) in (int, float) and 0 <= value <= 1e9 and math.isfinite(value)}
                data["state"] = safe_state
            levels = message.get("upgrade_levels")
            if isinstance(levels, dict):
                data["upgrade_levels"] = {name: value for name, value in levels.items() if name in ("Drill", "Hull", "Engine", "Fuel", "Radiator", "Cargo") and type(value) is int and 0 <= value <= 6}
            context = request_context or {}
            record = {"type": "authority", "schema_version": 1, "session_id": session, "server_sequence": capability.server_sequence + 1, "packet": packet, "timestamp_ms": time.time_ns() // 1000000, "data": data}
            request_id = message.get("request_id", context.get("request_id"))
            if isinstance(request_id, str) and len(request_id) <= 64:
                record["request_id_hash"] = hashlib.sha256(request_id.encode("utf-8", errors="surrogatepass")).hexdigest()
            motion_seq = message.get("motion_seq", context.get("motion_seq"))
            if type(motion_seq) is int and 0 <= motion_seq <= 1e15:
                record["motion_seq"] = motion_seq
            encoded = canonical([record])
            return capability.reserve_authority(encoded)

    def persist_authority(self, session, first_sequence, last_sequence, raw):
        with self.disk_lock:
            try:
                encoded = gzip.compress(raw, compresslevel=6, mtime=0)
                self._persist(self.root / session / "authority", f"{first_sequence:012d}-{last_sequence:012d}.jsonl.gz", encoded)
            except (CaptureError, OSError):
                return False
            return True
