"""Exercise traceability, durable rotation and privacy at real service boundaries."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from aiohttp import ClientSession

ROOT = Path(__file__).resolve().parent
CANARY = "private-canary-password-token-code"


class LoggingServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="orebit-logging-test-")
        self.directory = Path(self.temporary.name)
        self.logs = self.directory / "logs"
        self.process = None
        self.http = ClientSession()
        await self.start()

    async def start(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        environment = {**os.environ, "OREBIT_PUBLIC_URL": self.base, "OREBIT_LOG_DIR": str(self.logs), "OREBIT_LOG_MAX_BYTES": "10485760", "OREBIT_LOG_BACKUP_COUNT": "9"}
        self.process = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--port", str(port), "--db", str(self.directory / "state.sqlite3")], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            if self.process.poll() is not None:
                self.fail(self.process.stderr.read().decode())
            try:
                async with self.http.get(self.base + "/healthz") as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            await asyncio.sleep(.05)
        self.fail("Service did not become ready")

    async def stop(self):
        if self.process:
            self.process.terminate()
            await asyncio.to_thread(self.process.wait, 15)
            self.process.stderr.close()
            self.process = None

    async def asyncTearDown(self):
        await self.stop()
        await self.http.close()
        self.temporary.cleanup()

    async def test_http_and_websocket_failures_survive_restart_without_secrets(self):
        async with self.http.get(self.base + "/missing?code=" + CANARY, headers={"Authorization": "Bearer " + CANARY, "X-Request-ID": "a" * 32}) as response:
            rejected_status = response.status
            self.assertGreaterEqual(rejected_status, 400)
            request_id = response.headers["X-Request-ID"]
            self.assertRegex(request_id, r"^[0-9a-f]{32}$")
            self.assertNotEqual(request_id, "a" * 32)
            self.assertEqual((await response.json())["request_id"], request_id)
        async with self.http.post(self.base + "/api/auth/login", json={"username": "missing_account", "password": CANARY}) as response:
            self.assertEqual(response.status, 401)
            login_id = response.headers["X-Request-ID"]
            self.assertEqual((await response.json())["request_id"], login_id)
        ws = await self.http.ws_connect(self.base + "/api/ws?token=" + CANARY)
        session_id = ws._response.headers["X-Request-ID"]
        await ws.send_json({"type": "join"})
        joined = await ws.receive_json(timeout=5)
        self.assertEqual(joined["type"], "joined")
        await ws.send_json({"type": "state", "state_revision": 0, "state": {"x": 5.5, "y": -3.5, "transmissions": [{"text": CANARY}]}})
        await ws.send_json({"type": "ping"})
        self.assertEqual((await ws.receive_json(timeout=5))["type"], "pong")
        # A real write lock causes SQLite's actual timeout/error path, not a mock.
        lock = sqlite3.connect(self.directory / "state.sqlite3")
        lock.execute("BEGIN IMMEDIATE")
        try:
            await ws.send_json({"type": "mine", "request_id": CANARY, "x": 0, "y": 5})
            failure = await ws.receive_json(timeout=20)
            self.assertEqual(failure["code"], "server_error")
            self.assertEqual(failure["request_id"], session_id)
        finally:
            lock.rollback()
            lock.close()
            await ws.close()
        await self.stop()
        original = (self.logs / "events.jsonl").read_text()
        self.assertNotIn(CANARY, original)
        self.assertNotIn("database is locked", original)
        records = [json.loads(line) for line in original.splitlines()]
        trace = [record for record in records if record.get("request_id") == request_id]
        self.assertEqual([(record["event"], record["status"], record["route"]) for record in trace], [("http_request", rejected_status, "<unmatched>")])
        login = [record for record in records if record.get("request_id") == login_id]
        self.assertTrue({"auth_failure", "http_request"}.issubset({record["event"] for record in login}))
        session = [record for record in records if record.get("session_id") == session_id]
        self.assertTrue({"session_upgrade", "session_join", "session_error", "session_leave"}.issubset({record["event"] for record in session}))
        self.assertTrue(any(record.get("error_type") == "OperationalError" and record.get("stack") for record in session))
        summary = next(record for record in session if record["event"] == "session_leave")
        self.assertEqual(summary["state_updates"], 1)
        first_boot = next(record["boot_id"] for record in records if record["event"] == "startup")
        await self.start()
        await self.stop()
        retained = [json.loads(line) for line in (self.logs / "events.jsonl").read_text().splitlines()]
        self.assertEqual(len({record["boot_id"] for record in retained if record["event"] == "startup"}), 2)
        self.assertTrue(any(record.get("request_id") == request_id and record["boot_id"] == first_boot for record in retained))
        queried = subprocess.run([sys.executable, str(ROOT / "logs.py"), "--directory", str(self.logs), "--session-id", session_id], capture_output=True, text=True, check=True)
        self.assertEqual({json.loads(line)["event"] for line in queried.stdout.splitlines()}, {record["event"] for record in session})
        with (self.logs / "events.jsonl").open("a") as output:
            output.write('{"token":"' + CANARY)
        incomplete = subprocess.run([sys.executable, str(ROOT / "logs.py"), "--directory", str(self.logs)], capture_output=True, text=True)
        self.assertEqual(incomplete.returncode, 1)
        self.assertNotIn(CANARY, incomplete.stdout + incomplete.stderr)

    async def test_concurrent_sessions_keep_trace_ownership(self):
        async def join():
            connection = await self.http.ws_connect(self.base + "/api/ws")
            trace = connection._response.headers["X-Request-ID"]
            await connection.send_json({"type": "join"})
            participant = await connection.receive_json(timeout=5)
            self.assertEqual(participant["type"], "joined")
            return connection, trace, participant["player_id"]

        participants = await asyncio.gather(*(join() for _ in range(3)))
        self.assertEqual(len({trace for _, trace, _ in participants}), 3)

        async def fail_session(connection, trace, _player):
            await connection.send_json({"type": CANARY})
            async with asyncio.timeout(5):
                while True:
                    response = await connection.receive_json()
                    if response.get("type") == "error":
                        self.assertEqual(response["request_id"], trace)
                        break
            await connection.close()

        await asyncio.gather(*(fail_session(*participant) for participant in participants))
        await self.stop()
        records = [json.loads(line) for line in (self.logs / "events.jsonl").read_text().splitlines()]
        for _, trace, player in participants:
            session = [record for record in records if record.get("session_id") == trace]
            self.assertTrue({"session_join", "session_error", "session_leave"}.issubset({record["event"] for record in session}))
            self.assertEqual({record["player_id"] for record in session if "player_id" in record}, {player})
            self.assertEqual({record["request_id"] for record in session}, {trace})


class LoggingRetentionTest(unittest.TestCase):
    def test_rotation_privacy_and_safe_sink_failure(self):
        with tempfile.TemporaryDirectory(prefix="orebit-log-retention-") as temporary:
            directory = Path(temporary) / "logs"
            environment = {**os.environ, "PYTHONPATH": str(ROOT), "OREBIT_LOG_DIR": str(directory), "OREBIT_LOG_MAX_BYTES": "2048", "OREBIT_LOG_BACKUP_COUNT": "2"}
            program = '''
import logging, os
from telemetry import configure_logging, event
os.umask(0o022)
configure_logging()
for number in range(80):
    event("http_request", method="GET", route="/healthz", status=200, state_updates=number, password="private-canary-password-token-code")
try:
    raise RuntimeError("private-canary-password-token-code")
except RuntimeError:
    logging.getLogger("foreign").exception("Authorization: private-canary-password-token-code")
'''
            result = subprocess.run([sys.executable, "-c", program], env=environment, capture_output=True, text=True, check=True)
            files = list(directory.glob("events.jsonl*"))
            self.assertLessEqual(len(files), 3)
            records = []
            for path in files:
                self.assertLessEqual(path.stat().st_size, 2048)
                self.assertEqual(path.stat().st_mode & 0o007, 0)
                content = path.read_text()
                self.assertNotIn(CANARY, content)
                records.extend(json.loads(line) for line in content.splitlines())
            self.assertNotIn(CANARY, result.stdout + result.stderr)
            counts = [record["state_updates"] for record in records if "state_updates" in record]
            self.assertEqual(max(counts), 79)
            self.assertNotIn(0, counts)
            foreign = next(record for record in records if record["event"] == "external_log")
            self.assertEqual(foreign["error_type"], "RuntimeError")
            query = subprocess.run([sys.executable, str(ROOT / "logs.py"), "--directory", str(directory), "--event", "http_request", "--limit", "2"], capture_output=True, text=True, check=True)
            self.assertEqual([json.loads(line)["state_updates"] for line in query.stdout.splitlines()], [78, 79])
            failure_program = '''
import os
from pathlib import Path
from telemetry import configure_logging, event
configure_logging()
source=Path(os.environ["OREBIT_LOG_DIR"])
source.rename(source.with_name("private-canary-password-token-code"))
for number in range(20):
    event("http_request", method="GET", route="/healthz", status=200)
'''
            result = subprocess.run([sys.executable, "-c", failure_program], env=environment, capture_output=True, text=True, check=True)
            self.assertNotIn(CANARY, result.stdout + result.stderr)
            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(sum(record["event"] == "log_sink_error" for record in events), 1)


if __name__ == "__main__":
    unittest.main()
