"""Consumer-visible co-op boundaries, exercised through real HTTP and WebSockets."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from aiohttp import ClientSession

from terrain import generate, tile_name


class CoopServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orebit-coop-test-")
        self.process = None
        self.http = ClientSession()
        self.sockets = []
        await self.start()

    async def start(self):
        import socket
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        environment = {**os.environ, "OREBIT_PUBLIC_URL": self.base}
        environment.pop("OREBIT_DISCORD_CLIENT_ID", None)
        environment.pop("OREBIT_DISCORD_CLIENT_SECRET", None)
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("server.py")), "--port", str(port), "--db", str(Path(self.directory.name) / "state.sqlite3")], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            if self.process.poll() is not None:
                self.fail(self.process.stderr.read().decode())
            try:
                async with self.http.get(self.base + "/healthz") as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            await asyncio.sleep(0.05)
        self.fail("Service did not become ready")

    async def stop(self):
        for connection in self.sockets:
            await connection.close()
        self.sockets.clear()
        if self.process:
            self.process.terminate()
            await asyncio.to_thread(self.process.wait, 10)
            self.process.stderr.close()
            self.process = None

    async def asyncTearDown(self):
        await self.stop()
        await self.http.close()
        self.directory.cleanup()

    async def event(self, connection, kind):
        async with asyncio.timeout(5):
            while True:
                message = await connection.receive_json()
                if message.get("type") == kind:
                    return message

    async def join(self, token=""):
        connection = await self.http.ws_connect(self.base + "/api/ws")
        self.sockets.append(connection)
        await connection.send_json({"type": "join", "token": token})
        return connection, await connection.receive_json(timeout=5)

    async def test_capacity_contested_mining_and_restart_persistence(self):
        credentials = {"username": "test_miner", "password": "distinct-long-test-password"}
        async with self.http.post(self.base + "/api/auth/signup", json=credentials) as response:
            self.assertEqual(response.status, 200)
            account = await response.json()
        owner, initial = await self.join(account["token"])
        self.assertEqual(initial["type"], "joined")
        peers = [await self.join() for _ in range(4)]
        self.assertTrue(all(message["type"] == "joined" for _, message in peers))
        sixth, rejected = await self.join()
        self.assertEqual(rejected["code"], "server_full")
        terrain = generate(initial["seed"])
        x, y = next((x, y) for x in range(36) for y in range(600) if tile_name(terrain[x][y]) == "Ironium")
        state = {"player_money": 20, "player_cargo": {"Ironium": 0}, "current_upgrades": {"Cargo": "Micro Bay"}, "x": x + .5, "y": -y + .5}
        for connection in [owner, peers[0][0]]:
            await connection.send_json({"type": "state", "state": state, "state_revision": 0})
        await asyncio.gather(*(connection.send_json({"type": "mine", "request_id": str(index), "x": x, "y": y}) for index, connection in enumerate([owner, peers[0][0]])))
        first = await self.event(owner, "mined")
        self.assertTrue(first["accepted"])
        self.assertEqual(first["state"]["player_cargo"]["Ironium"], 1)
        peer_event = await self.event(peers[0][0], "mined")
        self.assertTrue(peer_event["accepted"])
        loser = peers[0][0] if first["player_id"] == initial["player_id"] else owner
        rejection = await self.event(loser, "mined")
        self.assertFalse(rejection["accepted"])
        # A stale snapshot must not overwrite an acknowledged mining reward.
        winner_is_owner = first["player_id"] == initial["player_id"]
        if winner_is_owner:
            await owner.send_json({"type": "state", "state": state, "state_revision": 0})
            synchronized = await self.event(owner, "state_sync")
            self.assertEqual(synchronized["state"]["player_cargo"]["Ironium"], 1)
        await self.stop()
        await self.start()
        async with self.http.post(self.base + "/api/auth/login", json=credentials) as response:
            self.assertEqual(response.status, 200)
            login = await response.json()
        _, restored = await self.join(login["token"])
        self.assertEqual(restored["seed"], initial["seed"])
        self.assertIn([x, y], restored["excavated"])
        self.assertEqual(restored["state"]["player_cargo"]["Ironium"], int(winner_is_owner))
        _, anonymous = await self.join()
        self.assertEqual(anonymous["state"], {})
        async with self.http.post(self.base + "/api/auth/discord/start", json={}) as response:
            self.assertEqual(response.status, 503)


if __name__ == "__main__":
    unittest.main()
