"""Private provisioning and real HTTP/WebSocket bot admission regressions."""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer
from argon2 import PasswordHasher

from bot_pool import ProvisionError, provision
from pvp import SimulationPhase, stock_state
import server


class BotProvisionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orebit-provision-")
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "state.sqlite3"
        self.accounts = Path(self.directory.name) / "accounts.json"

    def cli(self, *extra):
        return subprocess.run([sys.executable, str(Path(__file__).with_name("bot_pool.py")),
                               "provision", "--db", str(self.database), "--accounts", str(self.accounts),
                               *extra], capture_output=True, text=True, timeout=30)

    def test_cli_private_normal_argon_accounts_idempotent_and_no_game_resources(self):
        first = self.cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        original = self.accounts.read_bytes()
        document = json.loads(original)
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(stat.S_IMODE(self.accounts.stat().st_mode), 0o600)
        self.assertEqual([a["slot"] for a in document["accounts"]], [1, 2, 3, 4, 5])
        with sqlite3.connect(self.database) as db:
            rows = db.execute("SELECT u.id,u.username,u.display_name,u.password_hash,b.slot FROM users u "
                              "JOIN pvp_bot_accounts b ON b.user_id=u.id ORDER BY b.slot").fetchall()
            self.assertEqual(len(rows), 5)
            for row, account in zip(rows, document["accounts"]):
                self.assertEqual(row[:3], (account["user_id"], account["username"].lower(), account["username"]))
                self.assertEqual(row[4], account["slot"])
                self.assertTrue(PasswordHasher().verify(row[3], account["password"]))
                self.assertNotIn(account["password"], first.stdout + first.stderr)
            hashes = [row[3] for row in rows]
            for table in ("tokens", "worlds", "player_states", "excavations"):
                self.assertEqual(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)
        second = self.cli()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.accounts.read_bytes(), original)
        with sqlite3.connect(self.database) as db:
            self.assertEqual([r[0] for r in db.execute("SELECT password_hash FROM users ORDER BY id")], hashes)

    def test_refuses_existing_human_name_without_adopting_or_creating_partial_pool(self):
        store = server.Store(str(self.database))
        with store.connection as db:
            db.execute("INSERT INTO users(username,display_name,password_hash,created_at) VALUES(?,?,?,0)",
                       ("orebit_bot_3", "Orebit_Bot_3", "existing-human-hash"))
        store.connection.close()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.accounts.exists())
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM pvp_bot_accounts").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT password_hash FROM users").fetchone()[0], "existing-human-hash")

    def test_refuses_missing_changed_public_or_symlinked_private_credentials(self):
        provision(self.database, self.accounts)
        original = self.accounts.read_bytes()
        self.accounts.chmod(0o644)
        with self.assertRaises(ProvisionError):
            provision(self.database, self.accounts)
        self.accounts.chmod(0o600)
        document = json.loads(original)
        document["accounts"][0]["password"] = "incorrect-private-password"
        self.accounts.write_text(json.dumps(document))
        with self.assertRaises(ProvisionError):
            provision(self.database, self.accounts)
        self.accounts.unlink()
        with self.assertRaises(ProvisionError):
            provision(self.database, self.accounts)
        target = self.accounts.with_name("private.json")
        target.write_bytes(original)
        target.chmod(0o600)
        self.accounts.symlink_to(target)
        with self.assertRaises(OSError):
            provision(self.database, self.accounts)
        self.assertEqual(target.read_bytes(), original)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0], 5)


class BotPoolNetworkTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orebit-pool-network-")
        self.database = Path(self.directory.name) / "state.sqlite3"
        self.credentials = Path(self.directory.name) / "accounts.json"
        await asyncio.to_thread(provision, self.database, self.credentials)
        self.accounts = json.loads(self.credentials.read_text())["accounts"]
        self.environment = patch.dict(os.environ, {
            "OREBIT_PUBLIC_URL": "http://127.0.0.1:8765", "OREBIT_WORLD_ID": "public",
            "OREBIT_PVP_BOT_CONTROL_KEY": "private-test-control-key",
            "OREBIT_DISCORD_CLIENT_ID": "", "OREBIT_DISCORD_CLIENT_SECRET": "",
            "OREBIT_CAPTURE_DIR": str(Path(self.directory.name) / "captures"),
        })
        self.environment.start()
        self.http = ClientSession()
        self.sockets = []
        self.tokens = {}
        await self.start()

    async def start(self):
        app = server.create_app(argparse.Namespace(db=str(self.database)))
        self.backend = next(route.handler.__self__ for route in app.router.routes()
                            if route.resource.canonical == "/api/ws")
        self.service = TestServer(app)
        await self.service.start_server()
        self.base = str(self.service.make_url("/")).rstrip("/")

    async def stop(self):
        for connection in self.sockets:
            await connection.close()
        self.sockets.clear()
        await self.service.close()

    async def asyncTearDown(self):
        await self.stop()
        await self.http.close()
        self.environment.stop()
        self.directory.cleanup()

    async def event(self, connection, kind):
        async with asyncio.timeout(5):
            while True:
                message = await connection.receive_json()
                if message.get("type") == kind:
                    return message

    async def login(self, slot):
        if slot not in self.tokens:
            account = self.accounts[slot - 1]
            async with self.http.post(self.base + "/api/auth/login", json={
                    "mode": "pvp", "username": account["username"], "password": account["password"]}) as response:
                self.assertEqual(response.status, 200)
                self.tokens[slot] = (await response.json())["token"]
        return self.tokens[slot]

    async def join(self, slot=None, **fields):
        token = await self.login(slot) if slot else ""
        connection = await self.http.ws_connect(self.base + "/api/ws")
        self.sockets.append(connection)
        await connection.send_json({"type": "join", "mode": "pvp", "pvp_rounds": 1,
                                    "token": token, **fields})
        return connection, await connection.receive_json(timeout=5)

    async def pool(self):
        async with self.http.get(self.base + "/api/pvp/bot-pool", headers={
                "Authorization": "Bearer private-test-control-key"}) as response:
            self.assertEqual(response.status, 200)
            return await response.json()

    async def wait_population(self, humans, bots):
        async with asyncio.timeout(5):
            while True:
                pool = await self.pool()
                if pool["humans"] == humans and len(pool["connected_bots"]) == bots:
                    return pool
                await asyncio.sleep(0.01)

    async def fill(self):
        return [await self.join(slot) for slot in range(1, 6)]

    async def profile(self, slot, state, revision=7):
        user_id = self.accounts[slot - 1]["user_id"]
        await self.backend.store.run(lambda db: db.execute(
            "INSERT INTO player_states(world_id,user_id,state,revision,updated_at) VALUES('public:pvp',?,?,?,0) "
            "ON CONFLICT(world_id,user_id) DO UPDATE SET state=excluded.state,revision=excluded.revision",
            (user_id, json.dumps(state), revision)))

    async def spend(self, connection, joined, amount):
        state = copy.deepcopy(joined["state"])
        state["player_money"] = amount
        await connection.send_json({"type": "state", "round_id": joined["round_id"], "state": state,
                                    "state_revision": joined["state_revision"], "motion_seq": 1})
        acknowledged = await self.event(connection, "state_ack")
        self.assertEqual(acknowledged["state"]["player_money"], amount)
        return acknowledged

    async def test_control_requires_separate_key_and_reports_actual_registry_membership(self):
        token = await self.login(1)
        for authorization in (None, "Bearer wrong", "Bearer " + token):
            headers = {} if authorization is None else {"Authorization": authorization}
            async with self.http.get(self.base + "/api/pvp/bot-pool", headers=headers) as response:
                self.assertEqual(response.status, 401)
        initial = await self.pool()
        self.assertEqual(initial["world_id"], "public:pvp")
        self.assertEqual(initial["round_id"], self.backend.pvp.round_id)
        self.assertEqual((initial["humans"], initial["target_bots"], initial["connected_bots"]), (0, 5, []))
        self.assertEqual(initial["bots"], [{"slot": a["slot"], "user_id": a["user_id"], "name": a["username"]}
                                           for a in self.accounts])
        _, bot = await self.join(1)
        _, human = await self.join()
        current = await self.pool()
        self.assertEqual((current["humans"], current["target_bots"]), (1, 4))
        self.assertEqual(current["connected_bots"], [{"user_id": self.accounts[0]["user_id"],
                                                     "player_id": bot["player_id"], "cash": 20}])
        self.assertNotIn(human["player_id"], {b["player_id"] for b in current["connected_bots"]})
        self.assertNotIn("password", json.dumps(current))
        self.backend.bot_control_key = ""
        async with self.http.get(self.base + "/api/pvp/bot-pool") as response:
            self.assertEqual(response.status, 404)

    async def test_lowest_integer_cash_then_highest_player_id_yields_to_anonymous_human(self):
        bots = await self.fill()
        amounts = (12.9, 2.9, 2.1, 9, 20)
        for (connection, joined), amount in zip(bots, amounts):
            await self.spend(connection, joined, amount)
        worst = max((bots[1][1]["player_id"], bots[2][1]["player_id"]))
        observer = next(connection for connection, joined in bots if joined["player_id"] != worst)
        _, human = await self.join(is_bot=True, name="Orebit_Bot_1", user_id=self.accounts[0]["user_id"])
        self.assertEqual(human["type"], "joined")
        self.assertEqual(len(human["players"]), 5)
        self.assertNotIn(worst, {p["player_id"] for p in human["players"]})
        self.assertEqual((await self.event(observer, "player_left"))["player_id"], worst)
        pool = await self.pool()
        self.assertEqual((pool["humans"], len(pool["connected_bots"]), pool["target_bots"]), (1, 4, 4))
        self.assertNotIn(worst, {b["player_id"] for b in pool["connected_bots"]})
        _, rejected = await self.join(next(i for i, (_, joined) in enumerate(bots, 1) if joined["player_id"] == worst))
        self.assertEqual(rejected["code"], "server_full")

    async def test_names_and_client_flags_cannot_spoof_bot_or_human_role(self):
        async with self.http.post(self.base + "/api/auth/signup", json={
                "username": "Orebit_Bot_99", "password": "ordinary-human-password", "is_bot": True}) as response:
            self.assertEqual(response.status, 200)
            human_token = (await response.json())["token"]
        _, named = await self.join(token=human_token, is_bot=True, bot_slot=1)
        _, anonymous = await self.join(is_bot=True, role="bot", name="Orebit_Bot_2")
        _, bot = await self.join(1, is_bot=False, role="human")
        pool = await self.pool()
        self.assertEqual(pool["humans"], 2)
        self.assertEqual([p["player_id"] for p in pool["connected_bots"]], [bot["player_id"]])
        self.assertNotEqual(anonymous["player_id"], named["player_id"])
        async with self.http.get(self.base + "/healthz") as response:
            pvp = (await response.json())["modes"]["pvp"]
        self.assertEqual((pvp["players"], pvp["humans"], pvp["bots"]), (3, 2, 1))

    async def test_simultaneous_humans_replace_only_bots_never_oversubscribe_and_refill(self):
        await self.fill()
        arrivals = await asyncio.gather(*(self.join() for _ in range(6)))
        admitted = [(connection, message) for connection, message in arrivals if message["type"] == "joined"]
        rejected = [message for _, message in arrivals if message["type"] == "error"]
        self.assertEqual(len(admitted), 5)
        self.assertEqual([m["code"] for m in rejected], ["server_full"])
        self.assertTrue(all(len(message["players"]) == 5 for _, message in admitted))
        pool = await self.pool()
        self.assertEqual((pool["humans"], pool["target_bots"], pool["connected_bots"]), (5, 0, []))
        _, rejected_bot = await self.join(1)
        self.assertEqual(rejected_bot["code"], "server_full")
        await admitted[0][0].close()
        pool = await self.wait_population(4, 0)
        self.assertEqual(pool["target_bots"], 1)
        _, refill = await self.join(1)
        self.assertEqual(refill["type"], "joined")
        pool = await self.pool()
        self.assertEqual((pool["humans"], len(pool["connected_bots"])), (4, 1))

    async def test_invalid_duplicate_failed_and_bot_admissions_do_not_evict(self):
        await self.fill()
        before = {b["player_id"] for b in (await self.pool())["connected_bots"]}
        for fields, code in (({"pvp_rounds": 0}, "client_update_required"),
                             ({"world_id": "missing"}, "world_not_found"),
                             ({"mode": "invalid"}, "invalid_mode"),
                             ({"token": "not-a-valid-account-token"}, "invalid_token"),
                             ({"token": False}, "invalid_token")):
            _, rejected = await self.join(**fields)
            self.assertEqual(rejected["code"], code)
            self.assertEqual({b["player_id"] for b in (await self.pool())["connected_bots"]}, before)
        _, duplicate = await self.join(1)
        self.assertEqual(duplicate["code"], "already_connected")
        await self.backend.pvp.stop()
        async with self.backend.pvp.world_lock:
            self.backend.pvp.phase = SimulationPhase.FAILED
        try:
            _, unavailable = await self.join()
            self.assertEqual(unavailable["code"], "pvp_unavailable")
            snapshot = await self.pool()
            self.assertFalse(snapshot["enabled"])
            self.assertEqual(snapshot["target_bots"], 0)
            self.assertEqual({b["player_id"] for b in snapshot["connected_bots"]}, before)
        finally:
            self.backend.pvp.phase = SimulationPhase.RUNNING

    async def test_duplicate_human_at_capacity_does_not_displace_another_bot(self):
        async with self.http.post(self.base + "/api/auth/signup", json={
                "username": "connected_human", "password": "ordinary-human-password"}) as response:
            token = (await response.json())["token"]
        await self.fill()
        _, human = await self.join(token=token)
        before = await self.pool()
        _, rejected = await self.join(token=token)
        self.assertEqual(rejected["code"], "already_connected")
        self.assertEqual((await self.pool())["connected_bots"], before["connected_bots"])
        self.assertIn(human["player_id"], self.backend.pvp.members)

    async def test_evicted_buffered_mutations_and_old_cleanup_cannot_touch_replacement(self):
        bots = await self.fill()
        await self.spend(*bots[0], 1)
        old_socket, old_joined = bots[0]
        # Real clients continuously consume ticks. Keep the unrelated peers
        # reading so this retirement test does not manufacture outbound
        # backpressure and stall the simulation behind unread WebSockets.
        async def drain(connection):
            async for _ in connection:
                pass

        readers = [asyncio.create_task(drain(connection)) for connection, _ in bots[1:]]

        async def stop_readers():
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)

        self.addAsyncCleanup(stop_readers)
        victim_socket = self.backend.pvp.members[old_joined["player_id"]].socket
        release = asyncio.Event()
        retiring = asyncio.Event()
        original = self.backend.retire_socket

        async def held_retirement(socket):
            if socket is victim_socket:
                retiring.set()
                await release.wait()
            await original(socket)

        with patch.object(self.backend, "retire_socket", held_retirement):
            try:
                human_socket, human = await asyncio.wait_for(self.join(), 1)
                self.assertEqual(human["type"], "joined")
                await asyncio.wait_for(retiring.wait(), 1)
                # Refill the same account while its evicted socket is still open.
                await bots[1][0].close()
                await self.wait_population(1, 3)
                replacement_socket, replacement = await self.join(1)
                self.assertNotEqual(replacement["player_id"], old_joined["player_id"])
                # A stale transfer must neither overwrite the reconnected
                # account's saved wallet nor credit the new human.
                await old_socket.send_json({"type": "transfer", "round_id": old_joined["round_id"],
                                            "recipient_id": human["player_id"], "amount": 1})
                async with asyncio.timeout(3):
                    while (await old_socket.receive()).type not in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                        pass
                await replacement_socket.send_json({"type": "state", "round_id": replacement["round_id"],
                                                    "state": {}, "state_revision": -1, "motion_seq": 1})
                synchronized = await self.event(replacement_socket, "state_sync")
                self.assertTrue(synchronized["state"]["alive"])
                self.assertEqual(synchronized["state"]["player_money"], 1)
                await human_socket.send_json({"type": "state", "round_id": human["round_id"],
                                              "state": {}, "state_revision": -1, "motion_seq": 1})
                self.assertEqual((await self.event(human_socket, "state_sync"))["state"]["player_money"], 20)
                self.assertEqual(len(self.backend.pvp.members), 5)
                self.assertIn(replacement["player_id"], self.backend.pvp.members)
                self.assertFalse(self.backend.pvp.bags)
                saved = await self.backend.store.run(lambda db: db.execute(
                    "SELECT state FROM player_states WHERE world_id='public:pvp' AND user_id=?",
                    (self.accounts[0]["user_id"],)).fetchone())
                self.assertTrue(json.loads(saved["state"])["alive"])
                self.assertEqual(json.loads(saved["state"])["player_money"], 1)
            finally:
                release.set()
        await asyncio.gather(*list(self.backend.retiring_sockets))
        self.assertIn(replacement["player_id"], self.backend.pvp.members)

    async def test_eviction_retains_full_bot_profile_and_round_resets_offline_bots_only_in_pvp(self):
        saved = stock_state()
        saved.update(player_money=3, player_hp=13, player_fuel=47)
        saved["current_upgrades"]["Hull"] = "Ironium Hull"
        saved["current_upgrades"]["Fuel"] = "Medium Tank"
        saved["player_items"]["Dynamite"] = 4
        saved["player_cargo"]["Ironium"] = 2
        await self.profile(1, saved)
        coop_state = {"player_money": 4321, "player_items": {"Dynamite": 9}}
        await self.backend.store.run(lambda db: db.execute(
            "INSERT INTO player_states(world_id,user_id,state,revision,updated_at) VALUES('public',?,?,3,0)",
            (self.accounts[0]["user_id"], json.dumps(coop_state))))
        bots = await self.fill()
        _, human = await self.join()
        self.assertNotIn(bots[0][1]["player_id"], {p["player_id"] for p in human["players"]})
        row = await self.backend.store.run(lambda db: db.execute(
            "SELECT state,revision FROM player_states WHERE world_id='public:pvp' AND user_id=?",
            (self.accounts[0]["user_id"],)).fetchone())
        retained = json.loads(row["state"])
        for key in ("alive", "player_hp", "player_money", "player_fuel", "current_upgrades", "player_cargo", "player_items"):
            self.assertEqual(retained[key], saved[key])
        self.assertFalse(self.backend.pvp.bags)
        await bots[1][0].close()
        await self.wait_population(1, 3)
        restored_socket, restored = await self.join(1)
        for key in ("alive", "player_hp", "player_money", "player_fuel", "current_upgrades", "player_cargo", "player_items"):
            self.assertEqual(restored["state"][key], saved[key])
        await restored_socket.close()
        await self.wait_population(1, 3)
        # A genuine sale crosses one million through the normal state protocol.
        winner = stock_state()
        winner["player_money"] = 999_990
        winner["player_cargo"]["Ironium"] = 1
        await bots[2][0].close()
        await self.wait_population(1, 2)
        await self.profile(3, winner)
        winner_socket, winning_join = await self.join(3)
        sold = copy.deepcopy(winning_join["state"])
        sold["player_money"] += 30
        sold["player_cargo"]["Ironium"] = 0
        await winner_socket.send_json({"type": "state", "round_id": winning_join["round_id"], "state": sold,
                                       "state_revision": winning_join["state_revision"], "motion_seq": 1})
        reset = await self.event(winner_socket, "round_started")
        self.assertEqual(reset["winner"]["player_id"], winning_join["player_id"])
        self.assertNotEqual(reset["round_id"], winning_join["round_id"])
        self.assertEqual((await self.pool())["round_id"], reset["round_id"])
        untouched = await self.backend.store.run(lambda db: db.execute(
            "SELECT state,revision FROM player_states WHERE world_id='public' AND user_id=?",
            (self.accounts[0]["user_id"],)).fetchone())
        self.assertEqual(json.loads(untouched["state"]), coop_state)
        self.assertEqual(untouched["revision"], 3)
        _, offline_restored = await self.join(1)
        self.assertEqual(offline_restored["state"]["player_money"], 20)
        self.assertEqual(offline_restored["state"]["current_upgrades"], stock_state()["current_upgrades"])
        self.assertFalse(any(offline_restored["state"]["player_items"].values()))
        self.assertFalse(any(offline_restored["state"]["player_cargo"].values()))
        await self.stop()
        await self.start()
        _, restarted = await self.join(1)
        self.assertEqual(restarted["round_id"], reset["round_id"])
        self.assertEqual(restarted["state"]["player_money"], 20)

    async def test_bot_accounts_cannot_join_coop_and_vulcan_id_collisions_remain_human(self):
        _, denied = await self.join(1, mode="coop")
        self.assertEqual(denied["code"], "bot_mode_forbidden")
        _, invalid_vulcan = await self.join(1, mode="vulcan")
        self.assertEqual(invalid_vulcan["code"], "invalid_token")
        async with self.http.post(self.base + "/api/auth/signup", json={
                "mode": "vulcan", "username": "Orebit_Bot_1", "password": "ordinary-vulcan-human"}) as response:
            self.assertEqual(response.status, 200)
            vulcan_account = await response.json()
        self.assertEqual(vulcan_account["user"]["id"], self.accounts[0]["user_id"])
        vulcan_socket, vulcan = await self.join(mode="vulcan", token=vulcan_account["token"], is_bot=True)
        self.assertEqual(vulcan["type"], "joined")
        self.assertFalse(self.backend.vulcan.members[vulcan["player_id"]].is_bot)
        coop_socket, coop = await self.join(mode="coop", is_bot=True)
        self.assertEqual(coop["type"], "joined")
        await self.fill()
        await self.join()
        self.assertEqual((await self.pool())["humans"], 1)
        for connection in (vulcan_socket, coop_socket):
            await connection.send_json({"type": "ping"})
            await self.event(connection, "pong")
        self.assertEqual(len(self.backend.members), 1)
        self.assertEqual(len(self.backend.vulcan.members), 1)


if __name__ == "__main__":
    unittest.main()
