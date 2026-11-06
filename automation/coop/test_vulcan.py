"""Authoritative mechanics and consumer-visible HTTP/WebSocket Vulcan regressions."""
import argparse
import asyncio
import copy
import math
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from server import APIError, Player, Service, create_app
from terrain import HEIGHT, MIN_X, WIDTH, generate, tile_name
from vulcan import BASE_FLYING_SPEED, DRILL_TIMEOUT, RESPAWN_SECONDS, WORM_LENGTH, WORM_SPEED, VulcanWorld, stock_state


class VulcanMechanicsTest(unittest.TestCase):
    def setUp(self):
        self.world = VulcanWorld(SimpleNamespace(vulcan_store=None, world_id="public", send=None), APIError)
        self.world.terrain = {x: [0] * HEIGHT for x in range(MIN_X, WIDTH)}

    def player(self, name, x, y, drilling=False):
        state = stock_state()
        state.update(x=x, y=y, drilling=drilling)
        player = Player(None, name, name, None, None, 0, state, 0)
        player.contact_at = 100
        self.world.members[name] = player
        return player

    def test_nearest_active_drill_last_location_timeout_and_disconnect(self):
        far = self.player("far", 30.5, -19.5, True)
        near = self.player("near", 21.5, -19.5, True)
        self.player("silent", 19.5, -19.5)
        self.assertEqual(self.world.target(100), [21.5, -19.5])
        self.assertEqual(self.world.target_id, "near")
        near.state["drilling"] = False
        self.assertEqual(self.world.target(100), [30.5, -19.5])
        self.assertEqual(self.world.target_id, "far")
        far.contact_at = 100 - DRILL_TIMEOUT - 0.01
        self.assertEqual(self.world.target(100), [30.5, -19.5])
        self.assertEqual(self.world.target_id, "")
        self.world.members.pop("far")
        self.assertEqual(self.world.target(100), [30.5, -19.5])
        # A dead miner cannot attract the worm even with a stale drill flag.
        near.state.update(alive=False, drilling=True)
        self.assertEqual(self.world.target(100), [30.5, -19.5])
        self.assertEqual(self.world.target_id, "")

    def test_fixed_speed_cardinal_path_ten_segments_and_idle_spawn(self):
        self.assertAlmostEqual(BASE_FLYING_SPEED, 6.0)
        self.assertAlmostEqual(WORM_SPEED, 5.4)
        initial = self.world.segments()
        self.player("silent", 0.5, -3.5)
        self.world.step(10, 1000, 100)
        self.assertEqual(self.world.segments(), initial)
        hunter = self.player("target", 30.5, -10.5, True)
        before = self.world.segments()[0]
        self.world.step(0.1, 1000, 100)
        after = self.world.segments()[0]
        self.assertAlmostEqual(math.dist(before, after), WORM_SPEED * 0.1)
        self.assertTrue(before[0] == after[0] or before[1] == after[1])
        self.assertEqual(len(self.world.segments()), WORM_LENGTH)
        self.assertIn(tuple(self.world.direction), ((0, 1), (1, 0), (0, -1), (-1, 0)))
        hunter.state["drilling"] = False
        before = self.world.segments()[0]
        self.world.step(0.1, 1000, 100)
        self.assertNotEqual(self.world.segments()[0], before)
        self.world.members.clear()
        before = self.world.segments()
        self.world.step(10, 2000, 200)
        self.assertEqual(self.world.segments(), before)

    def test_entire_body_consumes_earth_ore_and_hazards_without_awards(self):
        player = self.player("observer", 0.5, -3.5)
        original = copy.deepcopy(player.state)
        tiles = (1, 2, 6, 7, 25, 26, 28, 29, 30, 31)
        expected = set()
        for index, (x, y) in enumerate(self.world.segments()):
            cx, cy = math.floor(x), round(0.5 - y)
            self.world.terrain[cx][cy] = tiles[index]
            expected.add((cx, cy))
        self.world.terrain[19][20] = -3
        self.world.consume_body()
        self.assertEqual(self.world.excavated, expected)
        self.assertEqual(self.world.dirty_cells, expected)
        self.assertNotIn((19, 20), self.world.excavated)
        self.assertEqual(player.state, original)

    def test_every_segment_contact_kills_once_and_respawns_retaining_money(self):
        for index in range(WORM_LENGTH):
            with self.subTest(segment=index):
                x, y = self.world.segments()[index]
                player = self.player("victim", x, y)
                player.state["player_money"] = 12345
                player.state["player_cargo"]["Ironium"] = 7
                player.state["player_items"]["Dynamite"] = 3
                player.state["current_upgrades"].update(Hull="Ironium Hull", Fuel="Medium Tank")
                self.world.step(0, 1000, 100)
                self.assertFalse(player.state["alive"])
                self.assertEqual(player.state["player_hp"], 0)
                self.assertEqual(player.state["player_money"], 12345)
                self.assertFalse(any(player.state["player_cargo"].values()))
                self.assertFalse(any(player.state["player_items"].values()))
                revision = player.revision
                self.world.step(0, 1000 + RESPAWN_SECONDS - 0.01, 100)
                self.assertEqual(player.revision, revision)
                self.world.step(0, 1000 + RESPAWN_SECONDS, 100)
                self.assertTrue(player.state["alive"])
                self.assertEqual((player.state["x"], player.state["y"]), (5.5, -3.5))
                self.assertEqual(player.state["player_hp"], 17)
                self.assertEqual(player.state["player_fuel"], 15)
                self.assertEqual(player.state["player_money"], 12345)
                self.assertEqual(player.revision, revision + 1)
                self.world.members.clear()

    def test_swept_worm_collision_catches_victim_between_tick_endpoints(self):
        victim = self.player("victim", 20.5, -19.5)
        self.player("target", 34.5, -19.5, True)
        self.world.step(3, 1000, 100)
        self.assertFalse(victim.state["alive"])
        self.assertFalse(self.world.touches_body(victim.state["x"], victim.state["y"]))
        self.assertTrue(any(event["type"] == "worm_death" and event["player_id"] == "victim" for event in self.world.events))

    def test_surface_bounds_and_immutable_tiles_are_preserved(self):
        self.world.nodes = [[18.5, -5.5 - index] for index in range(WORM_LENGTH)]
        self.world.direction = [0, 1]
        self.world.terrain[18][5] = -3
        self.player("surface-driller", 18.5, -3.5, True)
        self.world.step(1, 1000, 100)
        self.assertEqual(self.world.segments()[0], [18.5, -5.5])
        self.assertEqual(self.world.terrain[18][5], -3)
        self.assertNotIn((18, 5), self.world.excavated)
        self.world.nodes = [[MIN_X + 0.5, -19.5 - index] for index in range(WORM_LENGTH)]
        self.world.last_drill = [-100, -19.5]
        self.world.members["surface-driller"].state["drilling"] = False
        self.world.step(1, 1000, 100)
        self.assertTrue(all(MIN_X + 0.5 <= x <= WIDTH - 0.5 for x, _ in self.world.segments()))


class VulcanServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orebit-vulcan-http-")
        self.db = Path(self.directory.name) / "state.sqlite3"
        self.environment = patch.dict(os.environ, {"OREBIT_PUBLIC_URL": "http://127.0.0.1", "OREBIT_WORLD_ID": "vulcan-test", "OREBIT_DISCORD_CLIENT_ID": "", "OREBIT_DISCORD_CLIENT_SECRET": ""})
        self.environment.start()
        self.http = ClientSession()
        self.sockets = []
        await self.start()

    async def start(self):
        app = create_app(argparse.Namespace(db=str(self.db)))
        self.backend = next(route.handler.__self__ for route in app.router.routes() if route.resource.canonical == "/api/ws")
        self.server = TestServer(app)
        await self.server.start_server()
        self.base = str(self.server.make_url("/")).rstrip("/")
        # Drive the actual authoritative simulation deterministically; transport,
        # SQLite and all consumer requests remain real.
        self.backend.vulcan.task.cancel()
        try:
            await self.backend.vulcan.task
        except asyncio.CancelledError:
            pass
        self.backend.vulcan.task = None

    async def stop(self):
        for socket in self.sockets:
            await socket.close()
        self.sockets.clear()
        await self.server.close()

    async def asyncTearDown(self):
        await self.stop()
        await self.http.close()
        self.environment.stop()
        self.directory.cleanup()

    async def account(self, mode="vulcan", name="vulcan_miner", password="distinct-vulcan-password"):
        async with self.http.post(self.base + "/api/auth/signup", json={"mode": mode, "username": name, "password": password}) as response:
            self.assertEqual(response.status, 200)
            return await response.json()

    async def join(self, mode="vulcan", token="", **fields):
        socket = await self.http.ws_connect(self.base + "/api/ws")
        self.sockets.append(socket)
        await socket.send_json({"type": "join", "mode": mode, "token": token, "pvp_rounds": 1, **fields})
        return socket, await socket.receive_json(timeout=5)

    async def event(self, socket, kind):
        async with asyncio.timeout(5):
            while True:
                event = await socket.receive_json()
                self.assertNotEqual(event.get("type"), "error", event)
                if event.get("type") == kind:
                    return event

    async def state(self, socket, state, revision=0):
        await socket.send_json({"type": "state", "state": state, "state_revision": revision})
        return await self.event(socket, "state_ack")

    async def advance(self, elapsed=0, now=None):
        world = self.backend.vulcan
        async with world.world_lock:
            world.step(elapsed, time.time() if now is None else now, time.monotonic())
            await world.publish()

    async def test_accounts_tokens_sessions_logout_and_worlds_are_isolated(self):
        coop = await self.account("coop", password="original-coop-password")
        vulcan = await self.account()
        self.assertNotEqual(coop["token"], vulcan["token"])
        for token, mode, expected in ((coop["token"], "coop", 200), (vulcan["token"], "vulcan", 200), (coop["token"], "vulcan", 401), (vulcan["token"], "coop", 401)):
            async with self.http.get(self.base + "/api/auth/session?mode=" + mode, headers={"Authorization": "Bearer " + token}) as response:
                self.assertEqual(response.status, expected)
        for mode, password, expected in (("vulcan", "original-coop-password", 401), ("coop", "distinct-vulcan-password", 401), ("vulcan", "distinct-vulcan-password", 200)):
            async with self.http.post(self.base + "/api/auth/login?mode=" + mode, json={"username": "vulcan_miner", "password": password}) as response:
                self.assertEqual(response.status, expected)
        coop_socket, coop_join = await self.join("coop", coop["token"])
        vulcan_socket, joined = await self.join(token=vulcan["token"])
        pvp_socket, pvp_join = await self.join("pvp", coop["token"])
        self.assertEqual(joined["mode"], "vulcan")
        self.assertEqual(len(joined["worm"]["segments"]), 10)
        self.assertNotIn("worm", coop_join)
        self.assertNotIn("worm", pvp_join)
        self.assertEqual([p["player_id"] for p in joined["players"]], [joined["player_id"]])
        for mode, token in (("vulcan", coop["token"]), ("coop", vulcan["token"]), ("pvp", vulcan["token"])):
            _, rejected = await self.join(mode, token)
            self.assertEqual(rejected["code"], "invalid_token")
        await self.state(coop_socket, {"player_money": 300})
        await self.state(vulcan_socket, {"player_money": 900})
        await vulcan_socket.send_json({"type": "transfer", "recipient_id": coop_join["player_id"], "amount": 1})
        self.assertFalse((await self.event(vulcan_socket, "transfer_result"))["accepted"])
        await self.stop()
        await self.start()
        coop_socket, coop_restored = await self.join("coop", coop["token"])
        vulcan_socket, vulcan_restored = await self.join(token=vulcan["token"])
        pvp_socket, _ = await self.join("pvp", coop["token"])
        self.assertEqual(coop_restored["state"]["player_money"], 300)
        self.assertEqual(vulcan_restored["state"]["player_money"], 900)
        self.assertEqual(coop_restored["seed"], coop_join["seed"])
        self.assertEqual(vulcan_restored["seed"], joined["seed"])
        response, _ = await asyncio.gather(
            self.http.post(self.base + "/api/auth/logout?mode=vulcan", headers={"Authorization": "Bearer " + vulcan["token"]}),
            vulcan_socket.receive(timeout=5),
        )
        self.assertEqual(response.status, 200)
        response.release()
        async with self.http.get(self.base + "/api/auth/session", headers={"Authorization": "Bearer " + coop["token"]}) as response:
            self.assertEqual(response.status, 200)
        self.assertFalse(coop_socket.closed)
        self.assertFalse(pvp_socket.closed)

    async def test_real_drill_packets_nearest_last_location_and_short_burst(self):
        near, near_join = await self.join()
        far, far_join = await self.join()
        silent, _ = await self.join()
        await self.state(near, {"x": 21.5, "y": -19.5, "drilling": True})
        await self.state(far, {"x": 30.5, "y": -19.5, "drilling": True})
        await self.state(silent, {"x": 18.5, "y": -17.5, "drilling": False})
        await self.advance()
        tick = await self.event(near, "vulcan_tick")
        self.assertEqual(tick["worm"]["target_player_id"], near_join["player_id"])
        await self.state(near, {"drilling": False})
        await self.advance()
        tick = await self.event(near, "vulcan_tick")
        self.assertEqual(tick["worm"]["target_player_id"], far_join["player_id"])
        await self.state(far, {"drilling": False})
        await self.advance(0.1)
        tick = await self.event(near, "vulcan_tick")
        self.assertEqual(tick["worm"]["target_player_id"], "")
        self.assertEqual(tick["worm"]["last_drill"], [30.5, -19.5])
        self.assertGreater(tick["worm"]["segments"][0][0], 18.5)
        # No simulation tick occurs between these two state packets.
        await self.state(near, {"x": 23.5, "drilling": True})
        await self.state(near, {"drilling": False})
        self.assertEqual(self.backend.vulcan.last_drill, [23.5, -19.5])

    async def test_body_death_resource_loss_stale_rejection_respawn_and_restart(self):
        account = await self.account()
        socket, joined = await self.join(token=account["token"])
        upgrades = {**joined["state"]["current_upgrades"], "Hull": "Ironium Hull", "Fuel": "Medium Tank"}
        await self.state(socket, {"player_money": 4321, "player_items": {"Dynamite": 4}, "player_cargo": {"Ironium": 5}, "current_upgrades": upgrades})
        old_state = copy.deepcopy(self.backend.vulcan.members[joined["player_id"]].state)
        # Contact the tail, proving head-only checks cannot pass.
        x, y = joined["worm"]["segments"][-1]
        await socket.send_json({"type": "state", "state": {"x": x, "y": y}, "state_revision": 0})
        death = await self.event(socket, "worm_death")
        self.assertEqual(death["player_id"], joined["player_id"])
        self.assertFalse(death["state"]["alive"])
        self.assertEqual(death["state"]["player_money"], 4321)
        self.assertEqual(death["state"]["current_upgrades"], upgrades)
        self.assertFalse(any(death["state"]["player_cargo"].values()))
        self.assertFalse(any(death["state"]["player_items"].values()))
        self.assertAlmostEqual(death["respawn_at"] - death["server_time"], RESPAWN_SECONDS)
        await self.event(socket, "state_sync")
        await socket.send_json({"type": "state", "state": old_state, "state_revision": 0})
        rejected = await self.event(socket, "state_sync")
        self.assertFalse(rejected["state"]["alive"])
        self.assertEqual(rejected["state_revision"], death["state_revision"])
        await self.stop()
        await self.start()
        socket, restored = await self.join(token=account["token"])
        # Durable death is restored, not an older inventory-bearing snapshot.
        self.assertEqual(restored["state"]["player_money"], 4321)
        self.assertFalse(any(restored["state"]["player_cargo"].values()))
        if not restored["state"]["alive"]:
            await self.advance(now=death["respawn_at"] + 0.01)
            respawn = await self.event(socket, "worm_respawn")
            self.assertTrue(respawn["state"]["alive"])
            self.assertEqual(respawn["state"]["player_hp"], 17)
            self.assertEqual(respawn["state"]["player_fuel"], 15)
            self.assertEqual((respawn["state"]["x"], respawn["state"]["y"]), (5.5, -3.5))
            self.assertEqual(respawn["state"]["player_money"], 4321)
            self.assertGreater(respawn["state_revision"], death["state_revision"])

    async def test_generation_excavations_worm_state_and_resume_survive_restart(self):
        account = await self.account()
        socket, joined = await self.join(token=account["token"])
        self.assertEqual(self.backend.vulcan.terrain, generate(joined["seed"]))
        world = self.backend.vulcan
        x, depth = next((x, y) for x in range(MIN_X, WIDTH) for y in range(6, 18) if tile_name(world.terrain[x][y]) and tile_name(world.terrain[x][y]) != "Rock" and (x, y) not in world.excavated)
        await socket.send_json({"type": "mine", "request_id": "isolated-mine", "x": x, "y": depth})
        mined = await self.event(socket, "mined")
        self.assertTrue(mined["accepted"])
        await self.state(socket, {"x": 30.5, "y": -19.5, "drilling": True}, mined["state_revision"])
        await self.advance(0.4)
        tick = await self.event(socket, "vulcan_tick")
        worm = tick["worm"]["segments"]
        self.assertIsInstance(tick["terrain_changes"], list)
        self.assertTrue(all(cell[2] == 0 for cell in tick["terrain_changes"]))
        resumed, handoff = await self.join(token=account["token"], resume_player_id=joined["player_id"])
        self.assertEqual(handoff["player_id"], joined["player_id"])
        self.assertEqual(handoff["worm"]["segments"], worm)
        self.assertEqual(len(self.backend.vulcan.members), 1)
        coop, original = await self.join("coop")
        self.assertNotIn([x, depth], original["excavated"])
        await self.stop()
        await self.start()
        _, restored = await self.join(token=account["token"])
        self.assertEqual(restored["seed"], joined["seed"])
        self.assertIn([x, depth], restored["excavated"])
        self.assertEqual(restored["worm"]["segments"], worm)
        self.assertEqual(restored["worm"]["last_drill"], [30.5, -19.5])
        self.assertFalse(restored["state"]["drilling"])
        self.assertTrue(Path(str(self.db) + ".vulcan").is_file())

    async def test_player_motion_crossing_body_is_swept_even_without_endpoint_contact(self):
        socket, joined = await self.join()
        await self.state(socket, {"x": 16.5, "y": -19.5})
        await socket.send_json({"type": "state", "state": {"x": 20.5, "y": -19.5}, "state_revision": 0})
        death = await self.event(socket, "worm_death")
        self.assertFalse(death["state"]["alive"])
        self.assertEqual(death["player_id"], joined["player_id"])


if __name__ == "__main__":
    unittest.main()
