"""Consumer-visible co-op boundaries, exercised through real HTTP and WebSockets."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from aiohttp import ClientSession

from terrain import HEIGHT, MIN_X, WIDTH, generate, tile_name


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
        environment = {**os.environ, "OREBIT_PUBLIC_URL": self.base, "OREBIT_WORLD_ID": "public"}
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

    async def signup(self, username):
        async with self.http.post(self.base + "/api/auth/signup", json={"username": username, "password": "distinct-long-test-password"}) as response:
            self.assertEqual(response.status, 200)
            return await response.json()

    async def set_state(self, connection, state, revision=0):
        await connection.send_json({"type": "state", "state": state, "state_revision": revision})
        acknowledged = await self.event(connection, "state_ack")
        self.assertEqual(acknowledged["state"], state)
        self.assertEqual(acknowledged["state_revision"], revision)

    async def synchronized(self, connection):
        await connection.send_json({"type": "state", "state": {}, "state_revision": -1})
        return await self.event(connection, "state_sync")

    async def test_transfer_exact_balances_stale_snapshots_and_restart(self):
        sender_account = await self.signup("transfer_sender")
        recipient_account = await self.signup("transfer_recipient")
        sender, _ = await self.join(sender_account["token"])
        recipient, joined = await self.join(recipient_account["token"])
        sender_state = {"player_money": 125, "player_cargo": {"Ironium": 3}, "x": -5.5, "y": -3.5}
        recipient_state = {"player_money": 40, "player_items": {"Dynamite": 2}, "x": 2, "y": -8}
        await self.set_state(sender, sender_state)
        await self.set_state(recipient, recipient_state)

        await sender.send_json({"type": "transfer", "recipient_id": joined["player_id"], "amount": 65})
        result = await self.event(sender, "transfer_result")
        received = await self.event(recipient, "state_sync")
        self.assertTrue(result["accepted"])
        self.assertIsInstance(result["message"], str)
        self.assertTrue(result["message"])
        self.assertEqual(result["state"], {**sender_state, "player_money": 60})
        self.assertEqual(received["state"], {**recipient_state, "player_money": 105})
        self.assertEqual(result["state_revision"], 1)
        self.assertEqual(received["state_revision"], 1)

        # Neither side may restore a pre-transfer balance with a queued snapshot.
        for connection, old_state, money in ((sender, sender_state, 60), (recipient, recipient_state, 105)):
            await connection.send_json({"type": "state", "state": old_state, "state_revision": 0})
            synchronized = await self.event(connection, "state_sync")
            self.assertEqual(synchronized["state"]["player_money"], money)
            self.assertEqual(synchronized["state_revision"], 1)

        # Sending the entire remaining balance is valid and never leaves debt.
        await sender.send_json({"type": "transfer", "recipient_id": joined["player_id"], "amount": 60})
        result = await self.event(sender, "transfer_result")
        received = await self.event(recipient, "state_sync")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["state"]["player_money"], 0)
        self.assertEqual(received["state"]["player_money"], 165)
        self.assertEqual(result["state_revision"], 2)
        self.assertEqual(received["state_revision"], 2)

        await self.stop()
        await self.start()
        for account, state, money in ((sender_account, sender_state, 0), (recipient_account, recipient_state, 165)):
            _, restored = await self.join(account["token"])
            self.assertEqual(restored["state"], {**state, "player_money": money})
            self.assertEqual(restored["state_revision"], 2)

    async def test_transfer_rejects_invalid_offline_and_foreign_recipients(self):
        sender, sender_joined = await self.join()
        recipient, recipient_joined = await self.join()
        recipient_id = recipient_joined["player_id"]
        # A brand-new player has no funds even before the first state snapshot.
        await sender.send_json({"type": "transfer", "recipient_id": recipient_id, "amount": 1})
        self.assertFalse((await self.event(sender, "transfer_result"))["accepted"])
        await self.set_state(sender, {"player_money": 100})
        await self.set_state(recipient, {"player_money": 12})

        invalid = [
            (None, 1), ({}, 1), ([], 1), ("", 1), ("foreign-world-player", 1),
            (sender_joined["player_id"], 1),
            (recipient_id, 0), (recipient_id, -1),
            (recipient_id, True), (recipient_id, False),
            (recipient_id, 1.0), (recipient_id, 1.5),
            (recipient_id, "1"), (recipient_id, None),
            (recipient_id, 101), (recipient_id, 10 ** 100),
        ]
        for target, amount in invalid:
            with self.subTest(recipient=target, amount=amount):
                await sender.send_json({"type": "transfer", "recipient_id": target, "amount": amount})
                rejected = await self.event(sender, "transfer_result")
                self.assertFalse(rejected["accepted"])
                self.assertIsInstance(rejected["message"], str)
                self.assertTrue(rejected["message"])
                self.assertNotIn("state", rejected)

        for connection, money in ((sender, 100), (recipient, 12)):
            synchronized = await self.synchronized(connection)
            self.assertEqual(synchronized["state"]["player_money"], money)
            self.assertEqual(synchronized["state_revision"], 0)

        await self.set_state(recipient, {"player_money": 1e15})
        await sender.send_json({"type": "transfer", "recipient_id": recipient_id, "amount": 1})
        self.assertFalse((await self.event(sender, "transfer_result"))["accepted"])
        self.assertEqual((await self.synchronized(recipient))["state"]["player_money"], 1e15)

        # World membership is isolated at join, before any player ID is issued.
        foreign = await self.http.ws_connect(self.base + "/api/ws")
        self.sockets.append(foreign)
        await foreign.send_json({"type": "join", "world_id": "other-world"})
        self.assertEqual((await foreign.receive_json(timeout=5))["code"], "world_not_found")
        await recipient.close()
        await self.event(sender, "player_left")
        await sender.send_json({"type": "transfer", "recipient_id": recipient_id, "amount": 1})
        self.assertFalse((await self.event(sender, "transfer_result"))["accepted"])
        synchronized = await self.synchronized(sender)
        self.assertEqual(synchronized["state"]["player_money"], 100)
        self.assertEqual(synchronized["state_revision"], 0)

    async def test_simultaneous_transfers_serialize_shared_account(self):
        first, _ = await self.join()
        middle, middle_joined = await self.join()
        last, last_joined = await self.join()
        for connection, money in ((first, 100), (middle, 20), (last, 0)):
            await self.set_state(connection, {"player_money": money})
        await asyncio.gather(
            first.send_json({"type": "transfer", "recipient_id": middle_joined["player_id"], "amount": 80}),
            middle.send_json({"type": "transfer", "recipient_id": last_joined["player_id"], "amount": 20}),
        )
        first_result, middle_result = await asyncio.gather(
            self.event(first, "transfer_result"), self.event(middle, "transfer_result"),
        )
        self.assertTrue(first_result["accepted"])
        self.assertTrue(middle_result["accepted"])
        self.assertEqual((await self.event(last, "state_sync"))["state"]["player_money"], 20)
        for connection, money, revision in ((first, 20, 1), (middle, 80, 2), (last, 20, 1)):
            synchronized = await self.synchronized(connection)
            self.assertEqual(synchronized["state"]["player_money"], money)
            self.assertEqual(synchronized["state_revision"], revision)

    async def test_transfer_rolls_back_both_accounts_on_persistence_failure(self):
        sender_account = await self.signup("rollback_sender")
        recipient_account = await self.signup("rollback_recipient")
        sender, _ = await self.join(sender_account["token"])
        recipient, joined = await self.join(recipient_account["token"])
        await self.set_state(sender, {"player_money": 100})
        await self.set_state(recipient, {"player_money": 20})
        database = sqlite3.connect(Path(self.directory.name) / "state.sqlite3")
        self.addCleanup(database.close)
        recipient_user_id = recipient_account["user"]["id"]
        database.execute(f"CREATE TRIGGER reject_recipient BEFORE UPDATE ON player_states WHEN NEW.user_id={recipient_user_id} BEGIN SELECT RAISE(ABORT, 'test recipient write failure'); END")
        database.commit()

        await sender.send_json({"type": "transfer", "recipient_id": joined["player_id"], "amount": 30})
        rejected = await self.event(sender, "transfer_result")
        self.assertFalse(rejected["accepted"])
        self.assertTrue(rejected["message"])
        for connection, account, money in ((sender, sender_account, 100), (recipient, recipient_account, 20)):
            synchronized = await self.synchronized(connection)
            self.assertEqual(synchronized["state"]["player_money"], money)
            self.assertEqual(synchronized["state_revision"], 0)
            state, revision = database.execute("SELECT state,revision FROM player_states WHERE world_id='public' AND user_id=?", (account["user"]["id"],)).fetchone()
            self.assertEqual(json.loads(state)["player_money"], money)
            self.assertEqual(revision, 0)

        database.execute("DROP TRIGGER reject_recipient")
        database.commit()
        await sender.send_json({"type": "transfer", "recipient_id": joined["player_id"], "amount": 30})
        accepted = await self.event(sender, "transfer_result")
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["state"]["player_money"], 70)
        self.assertEqual(accepted["state_revision"], 1)
        received = await self.event(recipient, "state_sync")
        self.assertEqual(received["state"]["player_money"], 50)
        self.assertEqual(received["state_revision"], 1)

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

    async def test_western_contested_rewards_dig_blast_slab_and_restart(self):
        accounts = [await self.signup("west_owner"), await self.signup("west_peer")]
        joined = [await self.join(account["token"]) for account in accounts]
        connections = [connection for connection, _ in joined]
        terrain = generate(joined[0][1]["seed"])
        ore_x, ore_y = next(
            (x, y) for x in range(MIN_X, 0) for y in range(HEIGHT)
            if tile_name(terrain[x][y]) == "Ironium"
        )
        state = {
            "player_money": 20, "player_cargo": {"Ironium": 0},
            "current_upgrades": {"Cargo": "Micro Bay"}, "x": -9.5, "y": -10,
        }
        for connection in connections:
            await self.set_state(connection, state)
        await asyncio.gather(*(
            connection.send_json({
                "type": "mine", "request_id": f"west-contest-{index}",
                "x": ore_x, "y": ore_y, "method": "drill",
            }) for index, connection in enumerate(connections)
        ))
        events = [await self.event(connection, "mined") for connection in connections]
        self.assertEqual(events[0], events[1])
        self.assertTrue(events[0]["accepted"])
        self.assertEqual(events[0]["ore"], "Ironium")
        winner = next(index for index, (_, initial) in enumerate(joined) if initial["player_id"] == events[0]["player_id"])
        loser = 1 - winner
        rejected = await self.event(connections[loser], "mined")
        self.assertFalse(rejected["accepted"])
        self.assertEqual(rejected["ore"], "")
        for index, connection in enumerate(connections):
            synchronized = await self.synchronized(connection)
            self.assertEqual(synchronized["state"]["player_cargo"], {"Ironium": int(index == winner)})
            self.assertEqual(synchronized["state_revision"], int(index == winner))
            self.assertEqual(synchronized["state"]["player_money"], 20)
        await connections[winner].send_json({
            "type": "mine", "request_id": f"west-contest-{winner}", "x": ore_x, "y": ore_y,
        })
        retry = await self.event(connections[winner], "state_sync")
        self.assertEqual(retry["state"]["player_cargo"], {"Ironium": 1})
        self.assertEqual(retry["state_revision"], 1)

        owner = connections[0]
        # Both drill and explosives leave every segment of Ria's concrete intact.
        for x in range(-8, -2):
            for method in ("drill", "blast"):
                await owner.send_json({
                    "type": "mine", "request_id": f"slab-{x}-{method}",
                    "x": x, "y": 5, "method": method,
                })
                slab = await self.event(owner, "mined")
                self.assertFalse(slab["accepted"])
                self.assertEqual(slab["ore"], "")

        mutations = {(ore_x, ore_y)}
        for name, method in (("Dirt", "drill"), ("Rock", "blast")):
            x, y = next(
                (x, y) for x in range(MIN_X, 0) for y in range(HEIGHT)
                if tile_name(terrain[x][y]) == name
            )
            await owner.send_json({
                "type": "mine", "request_id": f"west-{method}", "x": x, "y": y, "method": method,
            })
            mined = await self.event(owner, "mined")
            self.assertTrue(mined["accepted"])
            self.assertEqual(mined["ore"], name if method == "drill" else "")
            self.assertEqual(mined["state"]["player_money"], 20)
            self.assertEqual(mined["state"]["player_cargo"], {"Ironium": int(winner == 0)})
            mutations.add((x, y))

        # Signed edge columns are legal at the deepest row, which is invincible.
        for x in (MIN_X, -1, WIDTH - 1):
            await owner.send_json({
                "type": "mine", "request_id": f"edge-{x}", "x": x, "y": HEIGHT - 1,
            })
            self.assertFalse((await self.event(owner, "mined"))["accepted"])
        expected = [await self.synchronized(connection) for connection in connections]
        with sqlite3.connect(Path(self.directory.name) / "state.sqlite3") as database:
            rows = database.execute("SELECT x,y FROM excavations WHERE world_id='public'").fetchall()
            self.assertEqual(set(rows), mutations)
            self.assertEqual(len(rows), 3)
        _, replayed = await self.join()
        self.assertTrue(mutations.issubset({tuple(cell) for cell in replayed["excavated"]}))

        await self.stop()
        await self.start()
        for index, account in enumerate(accounts):
            connection, restored = await self.join(account["token"])
            self.assertEqual(restored["seed"], joined[index][1]["seed"])
            self.assertEqual(restored["state"], expected[index]["state"])
            self.assertEqual(restored["state_revision"], expected[index]["state_revision"])
            self.assertTrue(mutations.issubset({tuple(cell) for cell in restored["excavated"]}))
            self.assertFalse(any([x, 5] in restored["excavated"] for x in range(-8, -2)))
            await connection.send_json({
                "type": "mine", "request_id": f"restored-{index}", "x": ore_x, "y": ore_y,
            })
            self.assertFalse((await self.event(connection, "mined"))["accepted"])
            synchronized = await self.synchronized(connection)
            self.assertEqual(synchronized["state"], expected[index]["state"])

    async def test_mining_rejects_coordinates_outside_signed_world_bounds(self):
        for index, (x, y) in enumerate((
            (MIN_X - 1, 6), (WIDTH, 6), (MIN_X, -1), (MIN_X, HEIGHT),
            (-1.5, 6), (MIN_X, 6.5), (True, 6), (MIN_X, False),
        )):
            with self.subTest(x=x, y=y):
                connection, initial = await self.join()
                self.assertEqual(initial["type"], "joined")
                await connection.send_json({
                    "type": "mine", "request_id": f"invalid-{index}", "x": x, "y": y,
                })
                self.assertEqual((await self.event(connection, "error"))["code"], "invalid_mine")
                await connection.close()


if __name__ == "__main__":
    unittest.main()
