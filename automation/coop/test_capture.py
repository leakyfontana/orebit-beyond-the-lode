"""Capture security/storage boundaries; only newly created temporary archives are used."""
import asyncio
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import capture
from capture import CaptureError, CaptureStore, STATE_FIELDS, canonical, decode_chunk
from server import Player, create_app


def records(session, index=0):
    observation = {"state": [0] * len(STATE_FIELDS), "tiles": [0] * 81}
    manifest = {
        "type": "manifest", "schema_version": 1, "session_id": session,
        "episode_id": "e" * 32, "chunk_index": index, "mode": "private", "seed": 123,
        "physics_hz": 50, "build": "a" * 64, "engine": "4.6.1", "state_fields": STATE_FIELDS,
        "checkpoint": {"sequence": 0, "tick": 0, "observation": observation},
        "started_at_ms": 1000, "source": "runtime_scripts_sha256", "terrain": "visible_local_9x9_v1", "actor": "human",
    }
    transition = {
        "type": "transition", "sequence": 0, "tick": 0, "next_tick": 1,
        "observation": observation, "next_observation": copy.deepcopy(observation),
        "action": {"movement": [0, 0], "commands": []},
        "reward_components": {"money": 0, "hp": 0, "fuel": 0},
        "terminated": False, "truncated": False, "reason": "running", "events": [],
    }
    return [manifest, transition]


def chunk(session, index=0):
    return gzip.compress(canonical(records(session, index)), mtime=0)


class CaptureStorageTest(unittest.TestCase):
    def setUp(self):
        usage = patch("capture.os.statvfs", return_value=SimpleNamespace(f_blocks=1000000, f_frsize=4096, f_bavail=900000))
        usage.start()
        self.addCleanup(usage.stop)
        self.directory = tempfile.TemporaryDirectory(prefix="orebit-capture-test-")
        self.addCleanup(self.directory.cleanup)
        self.store = CaptureStore(Path(self.directory.name) / "captures")
        self.capability = self.store.issue()
        self.session, self.token = self.capability["session_id"], self.capability["token"]

    def assert_status(self, status, function, *args):
        with self.assertRaises(CaptureError) as raised:
            function(*args)
        self.assertEqual(raised.exception.status, status)

    def test_authentication_and_path_injection(self):
        body = chunk(self.session)
        for session, token in ((self.session, ""), (self.session, "wrong" * 8), (self.session, "\ud800" * 30), ("../outside", self.token), ("f" * 32, self.token)):
            self.assert_status(401, self.store.ingest, session, token, 0, body)
        for index in (-1, True, 100000000, "../../secret"):
            self.assert_status(400, self.store.ingest, self.session, self.token, index, body)
        self.assertEqual(list(self.store.root.iterdir()), [])

    def test_atomic_canonical_idempotence_and_permissions(self):
        body = chunk(self.session)
        self.assertFalse(self.store.ingest(self.session, self.token, 0, body)["duplicate"])
        self.assertTrue(self.store.ingest(self.session, self.token, 0, body)["duplicate"])
        alternative = gzip.compress(canonical(records(self.session)), mtime=1)
        self.assert_status(409, self.store.ingest, self.session, self.token, 0, alternative)
        destination = self.store.root / self.session / "00000000.jsonl.gz"
        self.assertEqual(gzip.decompress(destination.read_bytes()), canonical(records(self.session)))
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(destination.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store.root.stat().st_mode), 0o700)
        self.assertEqual([path.name for path in destination.parent.iterdir()], [destination.name])
        self.assertNotIn(self.token.encode(), destination.read_bytes())

    def test_schema_privacy_and_nonfinite_rejection(self):
        bad_values = []
        value = records(self.session)
        value[0]["account_id"] = "not-a-dataset-field"
        bad_values.append(value)
        value = records(self.session)
        value[1]["events"] = [{"kind": "chat", "message": "never retained"}]
        bad_values.append(value)
        value = records(self.session)
        value[1]["action"]["commands"] = [{"kind": "use_item", "item": 0, "amount": 1, "category": 0, "token": "credential"}]
        bad_values.append(value)
        value = records(self.session)
        value[1]["next_observation"]["tiles"][0] = 5
        bad_values.append(value)
        value = records(self.session)
        value[1]["next_observation"]["state"][0] = float("nan")
        bad_values.append(value)
        value = records(self.session)
        value[0]["checkpoint"]["sequence"] = 1
        bad_values.append(value)
        value = records(self.session)
        value[1]["terminated"] = True
        value[1]["reason"] = "death"
        value[0]["mode"] = "pvp"
        bad_values.append(value)
        value = records(self.session)
        value[1]["next_observation"]["state"][0] = 10**400
        bad_values.append(value)
        for value in bad_values:
            raw = ("\n".join(json.dumps(record) for record in value) + "\n").encode()
            self.assert_status(400, self.store.ingest, self.session, self.token, 0, gzip.compress(raw))
        self.assertEqual(list(self.store.root.iterdir()), [])

    def test_vulcan_death_and_respawn_are_nonterminal_life_events(self):
        value = records(self.session)
        value[0]["mode"] = "vulcan"
        value[1]["events"] = [{"kind": "life", "alive": False}]
        value[1]["next_observation"]["state"][STATE_FIELDS.index("alive")] = 0
        revived = copy.deepcopy(value[1])
        revived.update(sequence=1, tick=1, next_tick=2)
        revived["observation"] = copy.deepcopy(value[1]["next_observation"])
        revived["next_observation"]["state"][STATE_FIELDS.index("alive")] = 1
        revived["events"] = [{"kind": "life", "alive": True}]
        value.append(revived)
        body = gzip.compress(canonical(value))
        self.store.ingest(self.session, self.token, 0, body)
        stored = decode_chunk(body, self.session, 0)
        self.assertEqual([row["events"][0]["alive"] for row in stored[1:]], [False, True])
        value[1].update(terminated=True, reason="death")
        self.assert_status(400, decode_chunk, gzip.compress(canonical(value)), self.session, 0)

    def test_round_end_requires_terminal_pvp_boundary(self):
        for mode, terminated, truncated in (("private", True, False), ("coop", True, False),
                                             ("pvp", False, True), ("pvp", False, False)):
            with self.subTest(mode=mode, terminated=terminated, truncated=truncated):
                value = records(self.session)
                value[0]["mode"] = mode
                value[1].update(reason="round_end", terminated=terminated, truncated=truncated)
                self.assert_status(400, decode_chunk, gzip.compress(canonical(value)), self.session, 0)

    def test_gzip_bombs_truncation_members_and_duplicate_keys(self):
        self.assert_status(413, decode_chunk, gzip.compress(b"x" * (capture.MAX_RAW + 1)), self.session, 0)
        self.assert_status(413, decode_chunk, b"x" * (capture.MAX_COMPRESSED + 1), self.session, 0)
        body = chunk(self.session)
        for malformed in (body[:-1], body + body, body + b"garbage", b"not gzip"):
            self.assert_status(400, decode_chunk, malformed, self.session, 0)
        raw = canonical(records(self.session)).replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        self.assert_status(400, decode_chunk, gzip.compress(raw), self.session, 0)

    def test_threshold_includes_reserve_and_incoming_without_deletion(self):
        body = chunk(self.session)
        self.store.ingest(self.session, self.token, 0, body)
        destination = self.store.root / self.session / "00000000.jsonl.gz"
        archived = destination.read_bytes()
        usage = SimpleNamespace(f_blocks=1000000, f_frsize=4096, f_bavail=200000)
        with patch("capture.os.statvfs", return_value=usage):
            self.assert_status(507, self.store.ingest, self.session, self.token, 1, chunk(self.session, 1))
            self.assert_status(507, self.store.issue)
            self.assertTrue(self.store.ingest(self.session, self.token, 0, body)["duplicate"])
        # Even below 80%, the reserve and incoming bytes must fit below the boundary.
        usage.f_bavail = 200001
        with patch("capture.os.statvfs", return_value=usage):
            self.assert_status(507, self.store.disk_guard, 1)
        self.assertEqual(destination.read_bytes(), archived)
        self.assertFalse((destination.parent / "00000001.jsonl.gz").exists())

    def test_expiry_capacity_and_per_session_quota(self):
        capability = self.store.sessions[self.session]
        capability.expires = time.monotonic() - 1
        self.assert_status(401, self.store.authenticate, self.session, self.token)
        renewed = self.store.issue()
        self.assertNotIn(self.session, self.store.sessions)
        with patch("capture.MAX_SESSIONS", 1):
            self.assert_status(429, self.store.issue)
        session, token = renewed["session_id"], renewed["token"]
        for _ in range(120):
            self.store.charge(session, token)
        self.assert_status(429, self.store.charge, session, token)
        with patch("capture.MAX_CHUNKS", 1):
            self.store.ingest(session, token, 100, chunk(session, 100))
            self.assert_status(429, self.store.ingest, session, token, 101, chunk(session, 101))

    def test_authority_excludes_names_credentials_and_raw_request_id(self):
        message = {
            "type": "mined", "accepted": True, "x": 2, "y": 3, "method": "drill", "ore": "Ironium",
            "player_id": "direct-player-id", "name": "SecretName", "user_id": 1234567,
            "token": self.token, "message": "private chat text", "request_id": "private-request-id",
            "state": {"player_money": 42, "transmissions": [{"chat": "private"}], "player_items": {"Dynamite": 1, "private": 99}},
        }
        sequence, raw = self.store.prepare_authority(self.session, message, {"motion_seq": 7})
        record = json.loads(raw)
        self.assertEqual(record["server_sequence"], 1)
        self.assertEqual(record["request_id_hash"], hashlib.sha256(b"private-request-id").hexdigest())
        self.assertEqual(record["motion_seq"], 7)
        for secret in ("SecretName", "direct-player-id", self.token, "private-request-id", "private chat text", "transmissions", "user_id"):
            self.assertNotIn(secret, raw.decode())
        self.assertEqual(record["data"]["state"]["player_items"], {"Dynamite": 1})
        self.assertTrue(self.store.persist_authority(self.session, sequence, sequence, raw))
        destination = self.store.root / self.session / "authority" / "000000000001-000000000001.jsonl.gz"
        self.assertEqual(gzip.decompress(destination.read_bytes()), raw)
        self.assertEqual(stat.S_IMODE(destination.parent.parent.stat().st_mode), 0o700)
        usage = SimpleNamespace(f_blocks=1000000, f_frsize=4096, f_bavail=100000)
        with patch("capture.os.statvfs", return_value=usage):
            self.assertFalse(self.store.persist_authority(self.session, 2, 2, raw))
        self.assertTrue(destination.exists())


class CaptureHTTPTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        usage = patch("capture.os.statvfs", return_value=SimpleNamespace(f_blocks=1000000, f_frsize=4096, f_bavail=900000))
        usage.start()
        self.addCleanup(usage.stop)
        self.directory = tempfile.TemporaryDirectory(prefix="orebit-capture-http-")
        environment = {"OREBIT_PUBLIC_URL": "http://127.0.0.1:8765", "OREBIT_WORLD_ID": "public", "OREBIT_CAPTURE_DIR": str(Path(self.directory.name) / "captures")}
        with patch.dict(os.environ, environment):
            self.app = create_app(SimpleNamespace(db=str(Path(self.directory.name) / "state.sqlite3")))
        self.service = next(route.handler.__self__ for route in self.app.router.routes() if route.resource.canonical == "/api/captures/session")
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

    async def test_http_storage_auth_download_and_authority_correlation(self):
        issued = await self.client.post("/api/captures/session")
        self.assertEqual(issued.status, 200)
        capability = await issued.json()
        session, token = capability["session_id"], capability["token"]
        path = f"/api/captures/{session}/chunks/0"
        for headers in ({}, {"Authorization": "Bearer wrong-token-not-a-real-capability"}):
            response = await self.client.post(path, data=chunk(session), headers=headers)
            self.assertEqual(response.status, 401)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/gzip"}
        uploaded = await self.client.post(path, data=chunk(session), headers=headers)
        self.assertEqual(uploaded.status, 200)
        self.assertTrue((self.service.capture.root / session / "00000000.jsonl.gz").exists())
        for target in (path, f"/api/captures/{session}/00000000.jsonl.gz"):
            response = await self.client.get(target, headers=headers)
            self.assertGreaterEqual(response.status, 400)
        usage = SimpleNamespace(f_blocks=1000000, f_frsize=4096, f_bavail=100000)
        with patch("capture.os.statvfs", return_value=usage):
            response = await self.client.post(f"/api/captures/{session}/chunks/1", data=chunk(session, 1), headers=headers)
            self.assertEqual(response.status, 507)
        connection = await self.client.ws_connect("/api/ws")
        await connection.send_json({"type": "join", "capture_session": session, "capture_token": token})
        joined = await connection.receive_json(timeout=5)
        self.assertEqual(joined["type"], "joined")
        self.assertGreater(joined["capture_server_sequence"], 0)
        await self.service.capture_queue.join()
        authority = self.service.capture.root / session / "authority" / f"{joined['capture_server_sequence']:012d}-{joined['capture_server_sequence']:012d}.jsonl.gz"
        raw = gzip.decompress(authority.read_bytes())
        self.assertNotIn(token.encode(), raw)
        self.assertNotIn(joined["player_id"].encode(), raw)
        self.assertEqual(json.loads(raw)["packet"], "joined")
        await connection.close()

    async def test_bad_link_does_not_break_gameplay_and_late_link_works(self):
        connection = await self.client.ws_connect("/api/ws")
        await connection.send_json({"type": "join", "capture_session": "a" * 32, "capture_token": "wrong" * 8})
        joined = await connection.receive_json(timeout=5)
        self.assertEqual(joined["type"], "joined")
        self.assertNotIn("capture_server_sequence", joined)
        issued = await self.client.post("/api/captures/session")
        capability = await issued.json()
        await connection.send_json({"type": "capture_link", "capture_session": capability["session_id"], "capture_token": capability["token"]})
        linked = await connection.receive_json(timeout=5)
        self.assertEqual(linked["type"], "capture_linked")
        self.assertTrue(linked["accepted"])
        await connection.send_json({"type": "ping"})
        self.assertEqual((await connection.receive_json(timeout=5))["type"], "pong")
        await connection.close()

    async def test_tick_uses_own_authority_state_and_reports_capture_only_loss(self):
        class Socket:
            def __init__(self):
                self.packets = []

            async def send_str(self, raw):
                self.packets.append(json.loads(raw))

        capability = self.service.capture.issue()
        session = capability["session_id"]
        socket = Socket()
        player = Player(socket, "ephemeral-id", "NeverArchiveThisName", None, None, 0, {"player_hp": 0, "player_money": 0, "alive": False, "current_upgrades": {"Drill": "Stock Drill"}}, 3)
        player.capture_session = session
        await self.service.send(player, {"type": "pvp_tick", "players": [{"name": "OtherSecretName", "state": {"player_money": 999}}]})
        await self.service.capture_queue.join()
        path = self.service.capture.root / session / "authority" / "000000000001-000000000001.jsonl.gz"
        raw = gzip.decompress(path.read_bytes())
        record = json.loads(raw)
        self.assertEqual(record["data"]["state"], {"player_hp": 0, "player_money": 0, "alive": False})
        self.assertEqual(record["data"]["state_revision"], 3)
        self.assertEqual(record["data"]["upgrade_levels"], {"Drill": 0})
        for forbidden in ("NeverArchiveThisName", "OtherSecretName", "ephemeral-id", capability["token"]):
            self.assertNotIn(forbidden.encode(), raw)
        with patch.object(self.service.capture, "persist_authority", return_value=False):
            await self.service.send(player, {"type": "pong"})
            await self.service.capture_queue.join()
        await self.service.send(player, {"type": "pong"})
        self.assertEqual(socket.packets[-1]["capture_session_id"], session)
        self.assertEqual(socket.packets[-1]["capture_gap_first"], 2)
        self.assertEqual(socket.packets[-1]["capture_gap_last"], 2)
        with patch("capture.MAX_SESSION_BYTES", 0):
            await self.service.send(player, {"type": "pong"})
        self.assertEqual(socket.packets[-1]["type"], "pong")
        self.assertEqual(socket.packets[-1]["capture_gap_first"], 4)
        self.assertEqual(player.state["player_hp"], 0)


if __name__ == "__main__":
    unittest.main()
