"""Deterministic PvP mechanics plus real WebSocket isolation/lifecycle regressions."""
import asyncio
import copy
import json
import os
import tempfile
from pathlib import Path
import sqlite3
import time
import types
import unittest
from unittest.mock import patch

import test_server
from pvp import BAG_HALF_SIZE, BLAST_HALF_SIZE, BUILDING_DOORS, BodyMotionPhase, DAMAGE, POD_HALF_HEIGHT, POD_HALF_WIDTH, PvpWorld, STOCK_UPGRADES, overlaps, stock_state
from server import APIError, Player, Service, Store
from terrain import HEIGHT, WIDTH


class Socket:
    closed = False


class PvpMechanicsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orebit-pvp-unit-")
        self.store = Store(os.path.join(self.directory.name, "state.sqlite3"))
        self.messages = []
        async def send(player, message):
            self.messages.append((player.player_id, copy.deepcopy(message)))
        self.service = types.SimpleNamespace(store=self.store, world_id="public", send=send)
        self.service.validate_state = types.MethodType(Service.validate_state, self.service)
        self.world = PvpWorld(self.service, APIError)
        await self.world.startup()
        self.world.task.cancel()
        try:
            await self.world.task
        except asyncio.CancelledError:
            pass
        self.world.task = None
        self.world.terrain = {x: [0] * HEIGHT for x in range(WIDTH)}
        self.world.excavated.clear()
        self.world.overrides.clear()
        self.world.bags.clear()
        self.world.falling.clear()
        self.world.impacts.clear()
        for x in range(WIDTH):
            self.world.terrain[x][10] = 1

    async def asyncTearDown(self):
        await self.world.stop()
        await self.store.close()
        self.directory.cleanup()

    def player(self, name, x=5.5, y=-3.5):
        player = Player(Socket(), name, name, None, None, 0, stock_state(x), 0)
        player.state["y"] = y
        player.movement_credit = 3
        self.world.members[name] = player
        return player

    async def restart_world(self, now):
        await self.world.stop()
        terrain = copy.deepcopy(self.world.terrain)
        self.world = PvpWorld(self.service, APIError)
        with patch("pvp.generate", return_value=terrain), patch("pvp.time.time", return_value=now):
            await self.world.startup()
        self.world.task.cancel()
        try:
            await self.world.task
        except asyncio.CancelledError:
            pass
        self.world.task = None

    async def snapshot(self, player, state, revision=None, motion_seq=None):
        if motion_seq is None:
            motion_seq = getattr(player, "motion_seq", 0) + 1
        await self.world.update_state(player, {"type": "state", "round_id": self.world.round_id, "state": state, "motion_seq": motion_seq,
                                             "state_revision": player.revision if revision is None else revision})

    async def building(self, player, script, enter=True, request_id=None):
        self.messages.clear()
        await self.world.building(player, {"type": "building", "round_id": self.world.round_id, "building": script, "enter": enter,
                                          "request_id": request_id or f"building-{len(player.requests)}"})
        owner = [message for player_id, message in self.messages if player_id == player.player_id]
        self.assertEqual([message["type"] for message in owner], ["state_sync", "building_result", "pvp_tick"])
        self.assertEqual(owner[0]["state"], owner[1]["state"])
        self.assertEqual(owner[0]["state_revision"], owner[1]["state_revision"])
        return owner[1]

    async def test_four_shop_doors_validate_entry_and_idempotent_safe_exit(self):
        player = self.player("shopper")
        for script, (x, y) in BUILDING_DOORS.items():
            with self.subTest(script=script):
                player.state.update(x=x, y=y, drill_x=1, vx=8, vy=-4)
                before = copy.deepcopy(player.state)
                result = await self.building(player, script)
                self.assertTrue(result["accepted"])
                self.assertEqual(result["building"], script)
                self.assertTrue(result["enter"])
                self.assertEqual(player.state["building"], script)
                self.assertEqual((player.state["drill_x"], player.state["vx"], player.state["vy"]), (0, 0, 0))
                revision = player.revision
                self.assertTrue((await self.building(player, script))["accepted"])
                self.assertEqual(player.revision, revision)
                result = await self.building(player, script, False)
                self.assertTrue(result["accepted"])
                self.assertEqual(player.state["building"], "")
                self.assertEqual((player.state["x"], player.state["y"]), (x, -3.5))
                self.assertFalse(self.world.position_blocked(player, player.state["x"], player.state["y"]))
                for key in ("alive", "player_hp", "player_money", "player_cargo", "player_items", "current_upgrades"):
                    self.assertEqual(player.state[key], before[key])
                # A delayed duplicate close must not teleport a pod that already left.
                player.state["x"] += 0.2
                position, revision = player.state["x"], player.revision
                self.assertTrue((await self.building(player, script, False))["accepted"])
                self.assertEqual((player.state["x"], player.revision), (position, revision))

    async def test_remote_forged_help_and_dead_entries_never_protect(self):
        player = self.player("forger", 18, -3.5)
        for script in (*BUILDING_DOORS, "HelpUI", "OptionsUI", "InventoryUI", "TransmissionManager"):
            result = await self.building(player, script)
            self.assertFalse(result["accepted"])
            self.assertTrue(result["message"])
            self.assertEqual(player.state["building"], "")
        for forged_flag in ("FuelShopManager", {"building": "FuelShopManager"}, True):
            forged = copy.deepcopy(player.state)
            forged["building"] = forged_flag
            await self.snapshot(player, forged)
            self.assertEqual(player.state["building"], "")
        self.world.damage(player, 1, 100)
        self.assertEqual(player.state["player_hp"], 9)
        # Entry uses the accepted swept pose, never request-supplied coordinates.
        forged = copy.deepcopy(player.state)
        forged.update(x=3.2404, y=-3.637)
        player.movement_credit = 0
        with patch("pvp.time.monotonic", return_value=player.moved_at):
            await self.snapshot(player, forged)
        self.assertFalse((await self.building(player, "FuelShopManager"))["accepted"])
        player.state.update(x=3.2404, y=-3.637)
        self.world.damage(player, 100, 101)
        self.assertFalse((await self.building(player, "FuelShopManager"))["accepted"])
        self.assertEqual(player.state["building"], "")

    async def test_entry_requires_euclidean_door_distance_and_replay_cannot_reenter(self):
        player = self.player("shopper")
        x, y = BUILDING_DOORS["FuelShopManager"]
        player.state.update(x=x + 1.1, y=y + 1.1)
        self.assertFalse((await self.building(player, "FuelShopManager"))["accepted"])
        player.state.update(x=x + 1.49, y=y)
        self.assertTrue((await self.building(player, "FuelShopManager", request_id="entry"))["accepted"])
        self.assertFalse((await self.building(player, "ItemShopManager", False))["accepted"])
        self.assertTrue((await self.building(player, "FuelShopManager", False))["accepted"])
        self.assertFalse((await self.building(player, "FuelShopManager", request_id="entry"))["accepted"])
        self.assertEqual(player.state["building"], "")

    async def test_inside_pins_pose_preserves_fuel_and_accepts_all_shop_finances(self):
        player = self.player("shopper")
        player.state.update(player_money=10000, player_hp=4, player_fuel=2)
        player.state["player_cargo"]["Ironium"] = 2
        for script, (x, y) in BUILDING_DOORS.items():
            player.state.update(x=x, y=y)
            self.assertTrue((await self.building(player, script))["accepted"])
            requested = copy.deepcopy(player.state)
            requested.update(x=19, y=-200, vx=30, vy=-30, facing=True, drill_x=1,
                             player_fuel=0, player_hp=0, alive=False, building="")
            if script == "FuelShopManager":
                requested.update(player_fuel=10, player_money=player.state["player_money"] - 5)
            elif script == "MineralBuyerManager":
                requested["player_cargo"]["Ironium"] = 0
                requested["player_money"] += 60
            elif script == "UpgradeShopUI":
                requested["current_upgrades"]["Hull"] = "Ironium Hull"
                requested["player_money"] -= 750
                requested["player_hp"] = 17
            else:
                requested["player_items"]["Dynamite"] += 1
                requested["player_money"] -= 2000
            fuel_before = player.state["player_fuel"]
            await self.snapshot(player, requested)
            self.assertEqual((player.state["x"], player.state["y"]), (x, y))
            self.assertEqual(player.state["building"], script)
            self.assertTrue(player.state["alive"])
            self.assertGreaterEqual(player.state["player_fuel"], fuel_before)
            self.assertEqual(player.state["player_money"], requested["player_money"])
            self.assertEqual((player.state["vx"], player.state["vy"], player.state["drill_x"]), (0, 0, 0))
            self.assertEqual(player.state["player_hp"], 17 if script in ("UpgradeShopUI", "ItemShopManager") else 4)
            self.assertTrue((await self.building(player, script, False))["accepted"])
        self.assertEqual(player.state["player_cargo"]["Ironium"], 0)
        self.assertEqual(player.state["player_items"]["Dynamite"], 1)
        self.assertEqual(player.state["current_upgrades"]["Hull"], "Ironium Hull")
        self.assertEqual(player.state["player_money"], 7305)

    async def test_inside_cannot_damage_mine_pickup_collide_or_receive_any_damage(self):
        x, y = BUILDING_DOORS["FuelShopManager"]
        shopper = self.player("shopper", x, y)
        shopper.state["player_items"]["Dynamite"] = 2
        shopper.state["player_money"] = 1234
        self.assertTrue((await self.building(shopper, "FuelShopManager"))["accepted"])
        attacker = self.player("attacker", x - 0.8, y)
        attacker.state.update(facing=True, drill_x=1)
        attacker.state["player_items"]["Dynamite"] = 1
        attacker.state["player_money"] = 0
        for source in ("crash", "fuel"):
            await self.world.action(shopper, {"type": "damage", "source": source, "amount": 1e15})
        for source in self.world.damage_values:
            self.world.damage(shopper, self.world.damage_values[source] * 100, 100)
        await self.world.action(attacker, {"type": "blast", "item": "Dynamite", "request_id": "outside-blast"})
        self.assertEqual(shopper.state["player_hp"], 10)
        await self.world.action(shopper, {"type": "blast", "item": "Dynamite", "request_id": "inside-blast"})
        self.assertEqual(shopper.state["player_items"]["Dynamite"], 2)
        self.assertEqual(attacker.state["player_hp"], 10)
        self.assertFalse(self.messages[-1][1]["accepted"])
        self.world.terrain[3][5] = 6
        await self.world.mine(shopper, {"request_id": "inside-mine", "x": 3, "y": 5})
        self.assertEqual(self.world.cell(3, 5), 6)
        self.assertFalse(self.messages[-1][1]["accepted"])
        # Put the other pod outside pickup reach, then sweep hazards through the
        # hidden pod while testing both incoming and outgoing stale drill state.
        attacker.state.update(x=x + 0.8, facing=False, drill_x=-1)
        shopper.state.update(facing=True, drill_x=1)
        for tile in (25, 28):
            self.world.falling.append({"id": str(tile), "x": x, "y": y + 0.5, "tile": tile, "vy": -10, "hit": []})
        attacker.state["y"] = y + 2
        self.world.bags = [{"id": "bag", "x": x, "y": y, "amount": 50, "vy": 0}]
        self.assertFalse(self.world.bag_reaches_player(self.world.bags[0], y, shopper))
        self.world.step(0.1, 100, time.monotonic())
        self.assertEqual(shopper.state["player_hp"], 10)
        self.assertEqual(shopper.state["player_money"], 1234)
        self.assertTrue(shopper.state["alive"])
        self.assertEqual(shopper.state["respawn_at"], 0)
        self.assertEqual(len(self.world.bags), 1)
        self.assertTrue(all("shopper" not in hazard["hit"] for hazard in self.world.falling))
        attacker.state.update(x=x + 0.8, y=y)
        self.world.step(0.1, 101, time.monotonic())
        self.assertEqual(attacker.state["player_hp"], 10)
        self.assertFalse(self.world.motion_blocked(attacker, x, y))
        shopper.state.update(x=5.5, y=-3.5)
        self.assertEqual(self.world.spawn_x(exclude=attacker), 5.5)

    async def test_exit_avoids_players_or_stays_protected_when_terrain_blocks_all_pads(self):
        x, y = BUILDING_DOORS["FuelShopManager"]
        shopper = self.player("shopper", x, y)
        self.assertTrue((await self.building(shopper, "FuelShopManager"))["accepted"])
        blocker = self.player("blocker", x, -3.5)
        self.assertTrue((await self.building(shopper, "FuelShopManager", False))["accepted"])
        self.assertFalse(overlaps(shopper.state["x"], shopper.state["y"], blocker.state["x"], blocker.state["y"]))
        shopper.state.update(x=x, y=y)
        self.assertTrue((await self.building(shopper, "FuelShopManager"))["accepted"])
        for column in range(0, 7):
            for row in range(3, 6):
                self.world.terrain[column][row] = 1
        before = copy.deepcopy(shopper.state)
        result = await self.building(shopper, "FuelShopManager", False)
        self.assertFalse(result["accepted"])
        self.assertIn("blocked", result["message"])
        self.assertEqual(shopper.state, before)
        self.world.damage(shopper, 1000, 100)
        self.assertEqual(shopper.state, before)

    async def test_reconnect_persisted_interior_does_not_spawn_overlap_or_restore_cash(self):
        account_id = await self.store.run(lambda db: db.execute(
            "INSERT INTO users(username,display_name,created_at) VALUES('shopper','Shopper',0)").lastrowid)
        x, y = BUILDING_DOORS["ItemShopManager"]
        shopper = self.player("shopper", x, y)
        shopper.user_id = account_id
        shopper.state.update(player_money=789, player_hp=7)
        self.assertTrue((await self.building(shopper, "ItemShopManager"))["accepted"])
        await self.restart_world(100)
        state, revision = await self.store.run(lambda db: tuple(db.execute(
            "SELECT state,revision FROM player_states WHERE world_id=? AND user_id=?",
            (self.world.world_id, account_id)).fetchone()))
        blocker = self.player("blocker", x, y)
        rejoined = Player(Socket(), "rejoined", "Shopper", account_id, None, 0, self.world.decode(state), revision)
        await self.world.prepare_player(rejoined)
        self.world.members[rejoined.player_id] = rejoined
        self.assertEqual(rejoined.state["building"], "ItemShopManager")
        self.assertEqual((rejoined.state["x"], rejoined.state["y"]), (x, y))
        self.world.step(0, 1000, time.monotonic())
        self.assertEqual((rejoined.state["player_money"], rejoined.state["player_hp"]), (789, 7))
        self.assertEqual(rejoined.state["respawn_at"], 0)
        self.assertFalse(self.world.bags)
        self.assertTrue((await self.building(rejoined, "ItemShopManager", False))["accepted"])
        self.assertFalse(overlaps(rejoined.state["x"], rejoined.state["y"], blocker.state["x"], blocker.state["y"]))
        self.world.damage(rejoined, 1000, 1001)
        self.assertEqual(rejoined.state["building"], "")
        self.world.respawn(rejoined)
        self.assertEqual(rejoined.state["building"], "")
        self.assertEqual(rejoined.state["player_money"], 0)

    async def test_fast_falling_body_keeps_accelerating_until_collision(self):
        body = {"x": 5.5, "y": 0, "vy": -25}
        self.assertIs(self.world.gravity(body, 0.1, 0.5), BodyMotionPhase.FALLING)
        self.assertLess(body["vy"], -25)
        self.assertLess(body["y"], -2.5)

    async def test_transmission_rewards_require_earned_depth_and_survive_death_without_replay(self):
        player = self.player("miner")
        claim = {"type": "claim_transmission", "index": 1}
        await self.world.action(player, claim)
        self.assertEqual(player.state["player_money"], 20)
        forged = copy.deepcopy(player.state)
        forged["deepest_y"] = -500
        forged["claimed_transmissions"] = []
        await self.snapshot(player, forged)
        await self.world.action(player, claim)
        self.assertEqual(player.state["player_money"], 20)
        player.state["deepest_y"] = -44
        await self.world.action(player, claim)
        self.assertEqual(player.state["player_money"], 1020)
        await self.world.action(player, claim)
        self.assertEqual(player.state["player_money"], 1020)
        self.world.damage(player, 10, 100)
        self.world.respawn(player)
        await self.world.action(player, claim)
        self.assertEqual(player.state["player_money"], 0)
        await self.world.action(player, {"type": "claim_transmission", "index": 2})
        self.assertEqual(player.state["player_money"], 0)

    async def test_blast_owner_immunity_square_boundary_and_replay(self):
        owner = self.player("owner", 8.5)
        owner.state["player_items"]["Dynamite"] = 2
        # Corners inside the original square hitbox are not incorrectly rejected
        # by a circular distance test; exact non-overlap boundaries remain outside.
        corner = self.player("corner", 10.2, -5.2)
        outside = self.player("outside", 8.5 + BLAST_HALF_SIZE["Dynamite"] + POD_HALF_WIDTH, -3.5)
        self.world.terrain[8][4] = 1
        self.world.terrain[10][4] = 1
        await self.world.action(owner, {"type": "blast", "item": "Dynamite", "request_id": "blast1"})
        self.assertEqual(owner.state["player_hp"], 10)
        self.assertEqual(corner.state["player_hp"], 6)
        self.assertEqual(outside.state["player_hp"], 10)
        self.assertEqual(owner.state["player_items"]["Dynamite"], 1)
        self.assertEqual(self.world.cell(8, 4), 0)
        self.assertEqual(self.world.cell(10, 4), 1)
        await self.world.action(owner, {"type": "blast", "item": "Dynamite", "request_id": "blast1"})
        self.assertEqual(corner.state["player_hp"], 6)
        self.assertEqual(owner.state["player_items"]["Dynamite"], 1)
        # A stale pre-blast snapshot cannot restore its consumed inventory.
        old = copy.deepcopy(owner.state)
        old["player_items"]["Dynamite"] = 2
        await self.snapshot(owner, old, revision=0)
        self.assertEqual(owner.state["player_items"]["Dynamite"], 1)

    async def test_plastic_damage_and_terrain_radius(self):
        owner = self.player("owner", 8.5)
        victim = self.player("victim", 10.5)
        owner.state["player_items"]["Plastic Explosives"] = 1
        self.world.terrain[10][6] = 25
        self.world.terrain[11][6] = 1
        await self.world.action(owner, {"type": "blast", "item": "Plastic Explosives", "request_id": "plastic"})
        self.assertEqual(victim.state["player_hp"], 3)
        self.assertEqual(owner.state["player_hp"], 10)
        self.assertEqual(self.world.cell(10, 6), 0)
        self.assertEqual(self.world.cell(11, 6), 1)

    async def test_aboveground_blast_does_not_reflect_into_underground_terrain(self):
        owner = self.player("owner", 8.5, 3.5)
        victim = self.player("victim", 9.5, 3.5)
        owner.state["player_items"]["Dynamite"] = 1
        self.world.terrain[8][4] = 1
        self.world.terrain[9][5] = 1
        await self.world.action(owner, {"type": "blast", "item": "Dynamite", "request_id": "aboveground"})
        self.assertEqual(owner.state["player_items"]["Dynamite"], 0)
        self.assertEqual(owner.state["player_hp"], 10)
        self.assertEqual(victim.state["player_hp"], 6)
        self.assertEqual(self.world.cell(8, 4), 1)
        self.assertEqual(self.world.cell(9, 5), 1)
        self.assertFalse(self.world.overrides)

    async def test_drill_direction_contact_duration_airborne_and_stale_input(self):
        attacker = self.player("attacker", 5.5, -8.55)
        victim = self.player("victim", 6.3, -8.55)
        state = copy.deepcopy(attacker.state)
        state.update(facing=True, drill_x=1, drill_y=0)
        await self.snapshot(attacker, state)
        self.assertEqual(attacker.state["drill_x"], 1)
        for _ in range(10):
            self.world.step(0.1, 100, attacker.contact_at)
        self.assertAlmostEqual(victim.state["player_hp"], 8)
        self.assertEqual(attacker.state["player_hp"], 10)
        attacker.state["drill_x"] = -1
        self.world.step(0.5, 100, attacker.contact_at)
        self.assertAlmostEqual(victim.state["player_hp"], 8)
        attacker.state["drill_x"] = 1
        self.world.step(0.5, 100, attacker.contact_at + 0.351)
        self.assertAlmostEqual(victim.state["player_hp"], 8)
        state = copy.deepcopy(attacker.state)
        state["y"] = victim.state["y"] = -7
        await self.snapshot(attacker, state)
        self.assertEqual(attacker.state["drill_x"], 1)
        self.world.step(0.5, 100, attacker.contact_at)
        self.assertAlmostEqual(victim.state["player_hp"], 7)
        attacker.state.update(x=6.3, y=-6.1)
        state = copy.deepcopy(attacker.state)
        state.update(drill_x=1, drill_y=-1)
        await self.snapshot(attacker, state)
        self.assertEqual((attacker.state["drill_x"], attacker.state["drill_y"]), (0, -1))
        self.world.step(0.5, 100, attacker.contact_at)
        self.assertAlmostEqual(victim.state["player_hp"], 6)

    async def test_airborne_horizontal_drill_requires_matching_facing(self):
        attacker = self.player("attacker", 5.5, -4)
        victim = self.player("victim", 6.3, -4)
        for facing, direction in ((False, 1), (True, -1), (True, 1), (False, -1)):
            with self.subTest(facing=facing, direction=direction):
                victim.state.update(x=5.5 + direction * 0.8, player_hp=10)
                state = copy.deepcopy(attacker.state)
                state.update(facing=facing, drill_x=direction)
                await self.snapshot(attacker, state)
                expected_direction = direction if (direction > 0) == facing else 0
                self.assertEqual(attacker.state["drill_x"], expected_direction)
                self.world.step(0.5, 100, attacker.contact_at)
                self.assertEqual(victim.state["player_hp"], 9 if expected_direction else 10)

    def test_airborne_drill_preserves_contact_and_alive_bounds(self):
        attacker = self.player("attacker", 5.5, -4)
        victim = self.player("victim", 6.3, -4)
        cases = (
            ("idle", 0, True, 0.8, 0, True, True),
            ("backward_intent", -1, True, -0.8, 0, True, True),
            ("behind", 1, True, -0.8, 0, True, True),
            ("too_close", 1, True, 0.59, 0, True, True),
            ("out_of_range", 1, True, 1.16, 0, True, True),
            ("lateral", 1, True, 0.8, 0.56, True, True),
            ("dead_attacker", 1, True, 0.8, 0, False, True),
            ("dead_victim", 1, True, 0.8, 0, True, False),
        )
        for name, direction, facing, offset_x, offset_y, attacker_alive, victim_alive in cases:
            with self.subTest(name=name):
                attacker.state.update(drill_x=direction, facing=facing, alive=attacker_alive,
                                      respawn_at=200)
                victim.state.update(x=5.5 + offset_x, y=-4 + offset_y, alive=victim_alive,
                                    respawn_at=200, player_hp=10)
                self.world.step(0.5, 100, attacker.contact_at)
                self.assertEqual(victim.state["player_hp"], 10)

    def test_swept_solid_player_collision_no_contact_damage(self):
        first = self.player("first", 5.5)
        second = self.player("second", 6.5)
        first.movement_credit = 3
        x, y = self.world.move(first, 8.5, -3.5, first.moved_at)
        self.assertLessEqual(x, second.state["x"] - 2 * POD_HALF_WIDTH + 1e-6)
        self.assertEqual(y, -3.5)
        self.world.step(1, 100, first.contact_at)
        self.assertEqual(first.state["player_hp"], 10)
        self.assertEqual(second.state["player_hp"], 10)
        second.state["alive"] = False
        first.movement_credit = 3
        x, _ = self.world.move(first, 8.5, -3.5, first.moved_at)
        self.assertAlmostEqual(x, 8.5)

    async def test_owner_flight_has_no_artificial_ceiling(self):
        player = self.player("pilot", 5.5, 29.5)
        state = copy.deepcopy(player.state)
        state.update(y=32)
        await self.snapshot(player, state)
        self.assertEqual(player.state["y"], 32)
        ack = self.messages[-1][1]
        self.assertEqual(ack["type"], "state_ack")
        self.assertEqual(ack["motion_seq"], 1)
        self.assertEqual(ack["requested_position"], [5.5, 32])
        self.assertEqual(ack["state"]["y"], 32)

    async def test_owner_drilling_can_enter_pending_solid_target(self):
        player = self.player("driller", 5.5, -7.5)
        self.world.terrain[5][9] = 1
        state = copy.deepcopy(player.state)
        state.update(y=-8.25, drill_y=-1)
        self.assertTrue(self.world.position_blocked(player, state["x"], state["y"]))
        await self.snapshot(player, state)
        self.assertEqual(player.state["y"], -8.25)
        self.assertEqual(self.world.cell(5, 9), 1)
        self.assertEqual(player.state["drill_y"], -1)

    async def test_motion_ack_reports_peer_correction_and_rejects_replay(self):
        player = self.player("pilot", 5.5)
        peer = self.player("peer", 6.5)
        requested = copy.deepcopy(player.state)
        requested["x"] = 8.5
        await self.snapshot(player, requested, motion_seq=2)
        ack = next(message for name, message in self.messages if name == "pilot" and message["type"] == "state_ack")
        self.assertEqual(ack["motion_seq"], 2)
        self.assertEqual(ack["requested_position"], [8.5, -3.5])
        self.assertLessEqual(ack["state"]["x"], peer.state["x"] - 2 * POD_HALF_WIDTH + 1e-6)
        accepted = copy.deepcopy(player.state)
        updates = player.state_updates
        for sequence in (1, 2):
            replay = copy.deepcopy(requested)
            replay["x"] = 4.5
            await self.snapshot(player, replay, motion_seq=sequence)
            self.assertEqual(player.state, accepted)
            self.assertEqual(player.state_updates, updates)
            self.assertEqual(self.messages[-1][1]["type"], "state_sync")

    async def test_motion_sequence_is_required_and_independent_of_economy_revision(self):
        player = self.player("pilot")
        for sequence in (None, True, 0, -1, 1.5):
            with self.assertRaises(APIError):
                await self.world.update_state(player, {"state": copy.deepcopy(player.state),
                                                      "state_revision": player.revision, "motion_seq": sequence})
        requested = copy.deepcopy(player.state)
        requested["x"] = 6
        await self.snapshot(player, requested, revision=-1, motion_seq=5)
        self.assertEqual(player.state["x"], 5.5)
        await self.snapshot(player, requested, motion_seq=5)
        self.assertEqual(player.state["x"], 5.5)
        await self.snapshot(player, requested, motion_seq=6)
        self.assertEqual(player.state["x"], 6)

    def test_owner_motion_retains_world_edges_floor_and_credit(self):
        player = self.player("pilot", POD_HALF_WIDTH, -3.5)
        x, y = self.world.move(player, -2, -3.5, player.moved_at)
        self.assertEqual(x, POD_HALF_WIDTH)
        self.assertEqual(y, -3.5)
        player.state.update(x=WIDTH - POD_HALF_WIDTH, y=-3.5)
        player.movement_credit = 3
        x, _ = self.world.move(player, WIDTH + 2, -3.5, player.moved_at)
        self.assertEqual(x, WIDTH - POD_HALF_WIDTH)
        player.state.update(x=5.5, y=-HEIGHT + POD_HALF_HEIGHT)
        player.movement_credit = 3
        _, y = self.world.move(player, 5.5, -HEIGHT - 2, player.moved_at)
        self.assertEqual(y, -HEIGHT + POD_HALF_HEIGHT)
        player.state.update(x=5.5, y=20)
        player.movement_credit = 0.5
        x, y = self.world.move(player, 15.5, 20, player.moved_at)
        self.assertAlmostEqual(x, 6)
        self.assertEqual(y, 20)

    async def test_owner_motion_rejects_nonfinite_coordinates(self):
        player = self.player("pilot")
        for key in ("x", "y"):
            for value in (float("nan"), float("inf"), -float("inf")):
                requested = copy.deepcopy(player.state)
                requested[key] = value
                with self.assertRaises(APIError):
                    await self.snapshot(player, requested)
        self.assertEqual(player.state["x"], 5.5)
        self.assertEqual(player.state["y"], -3.5)

    def test_authored_surface_collision_and_unity_cell_coordinates(self):
        player = self.player("player", 5.5, -3.5)
        for tile in (-101, -136, -999, 0):
            self.world.terrain[5][4] = tile
            self.assertFalse(self.world.position_blocked(player, 5.5, -3.5))
        for tile in (-3, -4, -5, 1, 25, 28):
            self.world.terrain[5][4] = tile
            self.assertTrue(self.world.position_blocked(player, 5.5, -3.5))
        self.world.terrain[5][4] = 0
        bag = {"x": 5.5, "y": -3.5, "vy": 0}
        self.assertIs(self.world.gravity(bag, 2, BAG_HALF_SIZE), BodyMotionPhase.SUPPORTED)
        self.assertAlmostEqual(bag["y"], 1 - 10 + BAG_HALF_SIZE)

    def test_bag_render_sized_gravity_lands_stably_in_its_column(self):
        # MoneyBag is 50px at 1/50 scale: its visible half-height is .5,
        # not the old .18 that left .32 of the sprite buried in the floor.
        for tile in (1, 6, 25, 28):
            with self.subTest(tile=tile):
                self.world.terrain[5][10] = tile
                self.world.terrain[4][6] = self.world.terrain[6][6] = 1
                bag = {"id": "cash", "x": 5.9, "y": -3.5, "vy": 0, "amount": 1234}
                self.world.bags = [bag]
                self.world.step(0.1, 100, 0)
                self.assertAlmostEqual(bag["vy"], -9.8100004196167 * 0.1)
                self.assertAlmostEqual(bag["y"], -3.5 - 9.8100004196167 * 0.01)
                self.world.step(2, 102, 0)
                self.assertEqual(bag["x"], 5.9)
                self.assertEqual(bag["y"], -8.5)
                self.assertEqual(bag["vy"], 0)
                for tick in range(30):
                    self.world.step(0.1, 102 + tick * 0.1, 0)
                    self.assertEqual(bag["y"], -8.5)
                    self.assertEqual(bag["x"], 5.9)

    def test_bag_resumes_falling_after_support_is_mined(self):
        self.world.terrain[5][20] = 6
        bag = {"id": "cash", "x": 5.5, "y": -8.5, "vy": 0, "amount": 1234}
        self.world.bags = [bag]
        self.world.step(0.1, 100, 0)
        self.assertEqual(bag["y"], -8.5)
        self.world.set_cell(5, 10, 0)
        self.world.step(0.1, 101, 0)
        self.assertLess(bag["y"], -8.5)
        self.assertLess(bag["vy"], 0)
        self.world.step(2, 103, 0)
        self.assertEqual((bag["x"], bag["y"], bag["vy"]), (5.5, -18.5, 0))

    def test_death_bag_embedded_while_drilling_rests_on_intersected_tile(self):
        victim = self.player("victim", 5.5, -4.4)
        victim.state["player_money"] = 1234.5
        self.world.terrain[5][5] = 6
        self.world.damage(victim, 10, 100)
        bag, = self.world.bags
        # The old row >= old_bottom test skipped row 5 when spawned inside it.
        self.world.step(0.1, 100.1, victim.contact_at)
        self.assertEqual((bag["x"], bag["y"], bag["vy"]), (5.5, -3.5, 0))
        self.assertEqual(bag["amount"], 1234.5)
        self.assertEqual(victim.state["player_money"], 0)
        self.world.step(0.1, 100.2, victim.contact_at)
        self.assertEqual(bag["y"], -3.5)

    async def test_hovering_hull_collects_exact_bag_once_and_persists_both(self):
        account_id = await self.store.run(lambda db: db.execute(
            "INSERT INTO users(username,display_name,created_at) VALUES('picker','Picker',0)").lastrowid)
        picker = self.player("picker", 5.5, -7.5)
        picker.user_id = account_id
        bag = {"id": "cash", "x": 5.5, "y": -8.5, "vy": 0, "amount": 1234.5}
        self.world.bags = [bag]
        self.world.stage_runtime()
        await self.world.persist()
        # 1.0 center separation leaves a .05 hovering gap above the .45 hull
        # plus .5 bag, outside the old .75 center-radius pickup.
        self.world.step(0.1, 100, picker.contact_at)
        self.assertEqual(picker.state["player_money"], 1254.5)
        self.assertFalse(self.world.bags)
        self.assertIn(picker, self.world.dirty_players)
        revision = picker.revision
        self.world.step(0.1, 100.1, picker.contact_at)
        self.assertEqual(picker.state["player_money"], 1254.5)
        self.assertEqual(picker.revision, revision)
        await self.world.persist()
        state, runtime = await self.store.run(lambda db: (
            self.world.decode(db.execute(
                "SELECT state FROM player_states WHERE world_id=? AND user_id=?",
                (self.world.world_id, account_id)).fetchone()[0]),
            self.world.decode(db.execute(
                "SELECT state FROM pvp_runtime WHERE world_id=?",
                (self.world.world_id,)).fetchone()[0])))
        self.assertEqual(state["player_money"], 1254.5)
        self.assertEqual(runtime["bags"], [])
        await self.restart_world(101)
        self.assertFalse(self.world.bags)

    def test_falling_bag_collects_swept_hull_not_just_center_radius(self):
        picker = self.player("picker", 6.35, -6)
        bag = {"id": "cash", "x": 5.5, "y": -3.5, "vy": -10, "amount": 1234}
        self.world.bags = [bag]
        self.world.step(0.5, 100, picker.contact_at)
        self.assertEqual(picker.state["player_money"], 1254)
        self.assertFalse(self.world.bags)

    def test_bag_collection_excludes_dead_far_and_solid_obstructed_players(self):
        dead = self.player("dead", 5.5, -7.6)
        dead.state.update(alive=False, player_money=0, respawn_at=200)
        far = self.player("far", 6.501, -8.5)
        above = self.player("above", 5.5, -7.449)
        below = self.player("below", 5.5, -9.4)
        bag = {"id": "cash", "x": 5.5, "y": -8.5, "vy": 0, "amount": 1234}
        self.world.bags = [bag]
        # Below's center is in the supporting earth, as can happen while
        # mining: expanded hull reach must not collect through that tile.
        self.world.step(0.1, 100, 0)
        self.assertEqual(self.world.bags, [bag])
        self.assertEqual(dead.state["player_money"], 0)
        for player in (far, above, below):
            self.assertEqual(player.state["player_money"], 20)

    def test_competing_bag_collectors_are_deterministic_and_money_conserved(self):
        second = self.player("z-second", 5.5, -7.6)
        first = self.player("a-first", 5.5, -7.6)
        full = self.player("0-full", 5.5, -7.6)
        full.state["player_money"] = 1e15
        bag = {"id": "cash", "x": 5.5, "y": -8.5, "vy": 0, "amount": 1234.5}
        self.world.bags = [bag]
        before = sum(p.state["player_money"] for p in (first, second, full)) + bag["amount"]
        self.world.step(0.1, 100, 0)
        self.assertEqual(first.state["player_money"], 1254.5)
        self.assertEqual(second.state["player_money"], 20)
        self.assertEqual(full.state["player_money"], 1e15)
        self.assertFalse(self.world.bags)
        self.assertEqual(sum(p.state["player_money"] for p in (first, second, full)), before)

    async def test_consumed_teleporter_allows_one_surface_jump(self):
        player = self.player("player", 5.5, -7)
        player.state["player_items"]["Matter Transmitter"] = 1
        used = copy.deepcopy(player.state)
        used["player_items"]["Matter Transmitter"] = 0
        await self.snapshot(player, used)
        destination = copy.deepcopy(player.state)
        destination.update(x=20.5, y=-3.5)
        await self.snapshot(player, destination)
        self.assertEqual(player.state["x"], 20.5)
        self.assertEqual(player.state["y"], -3.5)
        self.assertEqual(player.state["player_items"]["Matter Transmitter"], 0)
        destination.update(x=30.5, y=-3.5)
        await self.snapshot(player, destination)
        self.assertLess(player.state["x"], 24)

    async def test_death_cash_bag_pickup_stale_money_and_exact_respawn(self):
        victim = self.player("victim", 5.5)
        victim.state["player_money"] = 1234
        victim.state["current_upgrades"]["Hull"] = "Ironium Hull"
        victim.state["player_items"]["Dynamite"] = 7
        victim.state["player_cargo"]["Ironium"] = 3
        stale = copy.deepcopy(victim.state)
        self.world.damage(victim, 10, 100)
        self.assertFalse(victim.state["alive"])
        self.assertEqual(victim.state["respawn_at"], 110)
        self.assertEqual(victim.state["player_money"], 0)
        self.assertEqual(sum(b["amount"] for b in self.world.bags), 1234)
        picker = self.player("picker", 5.5, -4)
        self.world.step(0.1, 109.999, picker.contact_at)
        self.assertFalse(victim.state["alive"])
        self.assertEqual(picker.state["player_money"], 1254)
        self.assertFalse(self.world.bags)
        await self.world.persist()
        await self.snapshot(victim, stale, revision=0)
        self.assertEqual(victim.state["player_money"], 0)
        self.world.step(0, 110, picker.contact_at)
        self.assertTrue(victim.state["alive"])
        self.assertEqual(victim.state["player_hp"], 10)
        self.assertEqual(victim.state["player_fuel"], 10)
        self.assertEqual(victim.state["current_upgrades"], STOCK_UPGRADES)
        self.assertEqual(victim.state["player_items"]["Dynamite"], 0)
        self.assertEqual(victim.state["player_cargo"]["Ironium"], 0)
        self.assertEqual(picker.state["player_items"]["Dynamite"], 7)
        self.assertEqual(picker.state["player_cargo"]["Ironium"], 3)
        self.assertEqual(victim.state["player_money"] + picker.state["player_money"], 1254)

    def test_falling_hazards_damage_once_then_leave_nonsolid_timed_impacts(self):
        for x, tile, damage in ((5, 25, DAMAGE["Rock"]), (8, 28, DAMAGE["Lava"])):
            with self.subTest(tile=tile):
                victim = self.player(str(tile), x + 0.5, -6)
                self.world.terrain[x][3] = tile
                # Diagonal earth does not support falling lava.
                self.world.terrain[x - 1][2] = 1
                self.world.detach_hazards()
                hazard_id = self.world.falling[0]["id"]
                self.assertEqual(self.world.cell(x, 3), 0)
                for tick in range(30):
                    self.world.step(0.1, 100 + tick * 0.1, victim.contact_at)
                    if not self.world.falling:
                        break
                self.assertFalse(self.world.falling)
                self.assertEqual(victim.state["player_hp"], 10 - damage)
                impact, = self.world.snapshot([])["impacts"]
                self.assertEqual(set(impact), {"id", "x", "y", "tile", "started_at", "expires_at"})
                self.assertEqual(impact["id"], hazard_id)
                self.assertEqual((impact["x"], impact["y"], impact["tile"]), (x + 0.5, -8.5, tile))
                self.assertEqual(impact["expires_at"] - impact["started_at"], 2.5)
                self.assertEqual(self.world.join_details()["impacts"], [impact])
                self.assertEqual(self.world.cell(x, 9), 0)
                self.assertEqual(self.world.overrides[x, 3], 0)
                self.assertNotIn((x, 9), self.world.overrides)
                victim.state.update(x=impact["x"], y=impact["y"])
                self.assertFalse(self.world.position_blocked(victim, impact["x"], impact["y"]))
                newcomer = self.player("new-" + str(tile), impact["x"], impact["y"])
                # Both the original victim and a fresh arrival can occupy residue.
                self.world.step(0.1, impact["expires_at"] - 0.001, victim.contact_at)
                self.assertEqual(self.world.snapshot([])["impacts"], [impact])
                self.assertEqual(victim.state["player_hp"], 10 - damage)
                self.assertEqual(newcomer.state["player_hp"], 10)
                self.world.step(0, impact["expires_at"], victim.contact_at)
                self.assertEqual(self.world.snapshot([])["impacts"], [])
                self.assertEqual(self.world.join_details()["impacts"], [])
                self.assertEqual(self.world.cell(x, 9), 0)
                self.assertEqual(victim.state["player_hp"], 10 - damage)
                self.assertEqual(newcomer.state["player_hp"], 10)

    async def test_impact_restart_preserves_epoch_lifetime_without_ghost_terrain(self):
        self.world.terrain[5][3] = 25
        self.world.detach_hazards()
        self.world.step(2, 100, time.monotonic())
        impact, = self.world.snapshot([])["impacts"]
        await self.restart_world(101)
        self.assertEqual(self.world.join_details()["impacts"], [impact])
        self.assertFalse(self.world.falling)
        self.assertEqual(self.world.cell(5, 3), 0)
        self.assertEqual(self.world.cell(5, 9), 0)
        await self.restart_world(102.5)
        self.assertEqual(self.world.join_details()["impacts"], [])
        self.assertFalse(self.world.falling)
        self.assertEqual(self.world.cell(5, 9), 0)
        runtime = await self.store.run(lambda db: self.world.decode(db.execute(
            "SELECT state FROM pvp_runtime WHERE world_id=?", (self.world.world_id,)).fetchone()[0]))
        self.assertEqual(runtime["impacts"], [])
        self.assertFalse(any(tile in (25, 28) for tile in self.world.overrides.values()))

    async def test_legacy_runtime_without_impacts_loads_empty(self):
        await self.store.run(lambda db: db.execute(
            "INSERT INTO pvp_runtime(world_id,state) VALUES(?,?) ON CONFLICT(world_id) DO UPDATE SET state=excluded.state",
            (self.world.world_id, self.world.encode({"bags": [], "falling": []}))))
        await self.restart_world(100)
        self.assertEqual(self.world.snapshot([])["impacts"], [])

    async def test_upgraded_hull_crash_damage_over_ten_and_numeric_limits(self):
        victim = self.player("victim")
        victim.state["current_upgrades"]["Hull"] = "Ironium Hull"
        victim.state["player_hp"] = 17
        with patch("pvp.time.time", return_value=100):
            await self.world.action(victim, {"type": "damage", "source": "crash", "amount": 12})
        self.assertTrue(victim.state["alive"])
        self.assertEqual(victim.state["player_hp"], 5)
        for amount in (True, 0, -1, float("inf"), float("nan"), 1e15 + 1):
            with self.subTest(amount=amount):
                with self.assertRaises(APIError):
                    await self.world.action(victim, {"type": "damage", "source": "crash", "amount": amount})
        self.assertEqual(victim.state["player_hp"], 5)
        with patch("pvp.time.time", return_value=101):
            await self.world.action(victim, {"type": "damage", "source": "crash", "amount": 1e15})
        self.assertFalse(victim.state["alive"])
        self.assertEqual(victim.state["player_hp"], 0)

    async def test_upgraded_hull_fuel_exhaustion_is_authoritatively_lethal(self):
        for amount in (10, 17, 1):
            with self.subTest(amount=amount):
                victim = self.player("fuel-" + str(amount), 5.5)
                victim.state["current_upgrades"]["Hull"] = "Ironium Hull"
                victim.state.update(player_hp=17, player_fuel=0)
                with patch("pvp.time.time", return_value=100):
                    await self.world.action(victim, {"type": "damage", "source": "fuel", "amount": amount})
                self.assertFalse(victim.state["alive"])
                self.assertEqual(victim.state["player_hp"], 0)
                self.assertEqual(victim.state["respawn_at"], 110)
                self.world.step(0, 110, victim.contact_at)
                self.assertTrue(victim.state["alive"])
                self.assertEqual(victim.state["player_hp"], 10)
                self.assertEqual(victim.state["player_fuel"], 10)
                self.assertEqual(victim.state["current_upgrades"], STOCK_UPGRADES)
                self.world.members.pop(victim.player_id)

    async def test_cannot_forge_hull_money_items_or_cargo_and_paid_repair_works(self):
        player = self.player("player")
        player.state["player_hp"] = 4
        forged = copy.deepcopy(player.state)
        forged.update(player_hp=10, alive=False)
        await self.snapshot(player, forged)
        self.assertEqual(player.state["player_hp"], 4)
        self.assertTrue(player.state["alive"])
        for key, value in (("player_money", 100000), ("player_items", {"Dynamite": 1}), ("player_cargo", {"Ironium": 1})):
            forged = copy.deepcopy(player.state)
            forged[key] = value
            await self.snapshot(player, forged)
            self.assertNotEqual(player.state[key], value)
        repaired = copy.deepcopy(player.state)
        repaired.update(player_money=5, player_hp=5)
        await self.snapshot(player, repaired)
        self.assertEqual(player.state["player_hp"], 5)
        self.assertEqual(player.state["player_money"], 5)
        player.state["player_money"] = 755
        upgraded = copy.deepcopy(player.state)
        upgraded["current_upgrades"]["Hull"] = "Ironium Hull"
        upgraded.update(player_money=5, player_hp=17)
        await self.snapshot(player, upgraded)
        self.assertEqual(player.state["player_hp"], 17)
        self.assertEqual(player.state["current_upgrades"]["Hull"], "Ironium Hull")

    async def test_mining_reach_rock_and_lava_boundaries(self):
        player = self.player("player", 5.5, -4.5)
        self.world.terrain[5][5] = 28
        self.world.terrain[6][5] = 25
        self.world.terrain[30][5] = 6
        await self.world.mine(player, {"request_id": "far", "x": 30, "y": 5})
        self.assertEqual(self.world.cell(30, 5), 6)
        await self.world.mine(player, {"request_id": "rock", "x": 6, "y": 5})
        self.assertEqual(self.world.cell(6, 5), 25)
        await self.world.mine(player, {"request_id": "lava", "x": 5, "y": 5})
        self.assertEqual(self.world.cell(5, 5), 0)
        self.assertEqual(player.state["player_hp"], 5)
        await self.world.mine(player, {"request_id": "lava", "x": 5, "y": 5})
        self.assertEqual(player.state["player_hp"], 5)

    async def test_world_runtime_and_deadline_survive_restart(self):
        account_id = await self.store.run(lambda db: db.execute("INSERT INTO users(username,display_name,created_at) VALUES('saved','Saved',0)").lastrowid)
        player = self.player("saved")
        player.user_id = account_id
        self.world.set_cell(5, 3, 0)
        self.world.set_cell(5, 9, 25)
        self.world.set_cell(5, 10, 1)
        self.world.damage(player, 10, 100)
        self.world.falling.append({"id": "fall", "x": 12.5, "y": -12.5, "tile": 28, "vy": -4, "hit": []})
        self.world.stage_runtime()
        await self.world.persist()
        reloaded = PvpWorld(self.service, APIError)
        await reloaded.startup()
        await reloaded.stop()
        self.assertEqual(reloaded.cell(5, 9), 25)
        self.assertEqual(reloaded.cell(5, 3), 0)
        self.assertEqual(reloaded.bags[0]["amount"], 20)
        self.assertTrue(any(b["id"] == "fall" and b["vy"] == -4 for b in reloaded.falling))
        row = await self.store.run(lambda db: db.execute("SELECT state FROM player_states WHERE world_id=? AND user_id=?", (reloaded.world_id, account_id)).fetchone())
        state = reloaded.decode(row["state"])
        self.assertFalse(state["alive"])
        self.assertEqual(state["respawn_at"], 110)
        self.assertEqual(state["player_money"], 0)

    async def test_each_authoritative_credit_path_wins_and_resets_once(self):
        for credit in ("sale", "transmission", "treasure", "transfer"):
            with self.subTest(credit=credit):
                self.world.members.clear()
                player = self.player("winner")
                player.state["player_money"] = 999_990
                old_round, old_seed = self.world.round_id, self.world.seed
                self.messages.clear()
                if credit == "sale":
                    player.state["player_cargo"]["Ironium"] = 1
                    requested = copy.deepcopy(player.state)
                    requested["player_cargo"]["Ironium"] = 0
                    requested["player_money"] += 30
                    await self.snapshot(player, requested)
                elif credit == "transmission":
                    player.state["deepest_y"] = -44
                    await self.world.action(player, {"type": "claim_transmission", "index": 1,
                                                     "round_id": old_round})
                elif credit == "treasure":
                    player.state.update(x=5.5, y=-3.5)
                    self.world.terrain[5][4] = 16  # Dinosaur Bones pay cash directly.
                    await self.world.mine(player, {"type": "mine", "x": 5, "y": 4,
                                                   "request_id": "treasure", "round_id": old_round})
                else:
                    sender = self.player("sender", x=10.5)
                    await self.world.transfer(sender, {"type": "transfer", "recipient_id": player.player_id,
                                                       "amount": 10, "round_id": old_round})
                self.assertNotEqual(self.world.round_id, old_round)
                self.assertNotEqual(self.world.seed, old_seed)
                self.assertEqual(self.world.winner["player_id"], player.player_id)
                self.assertEqual(self.world.winner["round_id"], old_round)
                self.assertGreaterEqual(self.world.winner["amount"], 1_000_000)
                self.assertEqual(player.state, stock_state())
                events = [m for identity, m in self.messages if identity == player.player_id]
                self.assertEqual([m["type"] for m in events], ["round_started"])
                self.assertEqual(events[0]["round_id"], self.world.round_id)
                self.assertFalse(await self.world.finish_round())
                # The next subtest starts with a simple traversable unit world.
                self.world.terrain = {x: [0] * HEIGHT for x in range(WIDTH)}

    async def test_tick_first_winner_freezes_before_later_larger_pickup(self):
        first = self.player("a-first", 5.5, -7.6)
        later = self.player("z-later", 15.5, -7.6)
        first.state["player_money"] = later.state["player_money"] = 999_990
        self.world.bags = [
            {"id": "first", "x": 5.5, "y": -8.5, "vy": 0, "amount": 10},
            {"id": "later", "x": 15.5, "y": -8.5, "vy": 0, "amount": 500_000},
        ]
        self.world.step(0.1, 100, 0)
        self.assertEqual(self.world.pending_winner["player_id"], first.player_id)
        self.assertEqual(later.state["player_money"], 999_990)
        self.world.step(0.1, 101, 0)
        self.assertEqual(later.state["player_money"], 999_990)
        await self.world.finish_round()
        self.assertEqual(self.world.winner["amount"], 1_000_000)
        self.assertFalse(self.world.bags)
        self.assertEqual(len([m for _, m in self.messages if m["type"] == "round_started"]), 2)

    async def test_death_loot_partial_weighted_full_bay_and_reloaded_remainder(self):
        victim = self.player("victim", 5.5, -7.6)
        victim.state["player_money"] = 0
        victim.state["player_items"]["Dynamite"] = 7
        victim.state["player_cargo"].update(Ironium=4, Goldium=3, Diamond=2)
        self.world.damage(victim, 100, 100)
        self.world.damage(victim, 100, 100)
        bag, = self.world.bags
        self.assertEqual(bag["items"]["Dynamite"], 7)
        self.assertFalse(any(victim.state["player_cargo"].values()))
        self.assertFalse(any(victim.state["player_items"].values()))
        picker = self.player("picker", 5.5, -7.6)
        picker.state["player_cargo"]["Ironium"] = 7
        self.world.step(0.1, 100, 0)
        self.assertEqual(picker.state["player_items"]["Dynamite"], 7)
        self.assertEqual(bag["cargo"]["Diamond"], 2)
        self.assertEqual(len(self.world.bags), 1)
        # With five free weight units, four Ironium fit but the last free unit
        # cannot hold Goldium or Diamond; neither mineral may be destroyed.
        picker.state["player_cargo"]["Ironium"] = 2
        with patch("pvp.secrets.randbelow", return_value=0):
            self.world.step(0.1, 100.1, 0)
        self.assertEqual(picker.state["player_cargo"]["Ironium"], 6)
        self.assertEqual(picker.state["player_cargo"]["Goldium"], 0)
        self.assertEqual(bag["cargo"]["Goldium"], 3)
        self.assertEqual(bag["cargo"]["Diamond"], 2)
        # One free unit cannot fit either remaining mineral; another collector
        # may still take the remainder later, including after restart.
        await self.world.persist()
        await self.restart_world(101)
        bag, = self.world.bags
        self.assertEqual(bag["cargo"]["Goldium"], 3)
        self.assertEqual(bag["cargo"]["Diamond"], 2)
        self.assertEqual(bag["items"]["Dynamite"], 0)
        self.world.members.clear()
        collector = self.player("collector", 5.5, -7.6)
        collector.state["current_upgrades"]["Cargo"] = "Leviathan Bay"
        self.world.step(0.1, 101, 0)
        self.assertFalse(self.world.bags)
        self.assertEqual(collector.state["player_cargo"]["Goldium"], 3)
        self.assertEqual(collector.state["player_cargo"]["Diamond"], 2)

    def test_random_unit_draw_respects_weight_and_counter_limits(self):
        picker = self.player("picker")
        bag = {"id": "loot", "x": 5.5, "y": -3.5, "vy": 0, "amount": 12,
               "cargo": {"Ironium": 2, "Goldium": 3, "Diamond": 1},
               "items": {"Dynamite": 1_000_000_000, "Plastic Explosives": float("inf"),
                         "Quantum Teleporter": 1.5, "Matter Transmitter": True}}
        picker.state["player_items"]["Dynamite"] = 999_999_999
        self.world.bags = [bag]
        with patch("pvp.secrets.randbelow", side_effect=lambda total: total - 1):
            self.assertTrue(self.world.collect_bag(picker, bag))
        self.assertEqual(picker.state["player_money"], 32)
        self.assertEqual(picker.state["player_items"]["Dynamite"], 1_000_000_000)
        self.assertEqual(bag["items"]["Dynamite"], 999_999_999)
        self.assertEqual(picker.state["player_cargo"]["Goldium"], 3)
        self.assertEqual(picker.state["player_cargo"]["Ironium"], 1)
        self.assertEqual(bag["cargo"]["Ironium"], 1)
        self.assertEqual(bag["cargo"]["Diamond"], 1)
        self.assertFalse(self.world.collect_bag(picker, bag))

    async def test_failed_round_transaction_rolls_back_and_cannot_save_dirty_winner(self):
        player = self.player("winner")
        player.user_id = await self.store.run(lambda db: db.execute(
            "INSERT INTO users(username,display_name,created_at) VALUES('winner','Winner',0)").lastrowid)
        player.state["player_money"] = 999_990
        player.state["player_cargo"]["Ironium"] = 1
        self.world.dirty_players.add(player)
        self.world.set_cell(2, 4, 0)
        await self.world.persist()
        old_round, old_seed = self.world.round_id, self.world.seed
        old_cells = await self.store.run(lambda db: db.execute(
            "SELECT count(*) FROM pvp_cells WHERE world_id=?", (self.world.world_id,)).fetchone()[0])
        await self.store.run(lambda db: db.execute(
            "CREATE TEMP TRIGGER reject_round BEFORE UPDATE ON pvp_rounds "
            "BEGIN SELECT RAISE(ABORT,'simulated disk save failure'); END"))
        requested = copy.deepcopy(player.state)
        requested["player_cargo"]["Ironium"] = 0
        requested["player_money"] += 30
        with self.assertRaises(sqlite3.Error):
            await self.snapshot(player, requested)
        self.assertFalse(any(m["type"] == "round_started" for _, m in self.messages))
        with self.assertRaises(APIError):
            await self.world.persist()
        await self.world.stop()
        def load(db):
            return (db.execute("SELECT seed FROM worlds WHERE id=?", (self.world.world_id,)).fetchone()[0],
                    db.execute("SELECT round_id,winner FROM pvp_rounds WHERE world_id=?", (self.world.world_id,)).fetchone(),
                    db.execute("SELECT state FROM player_states WHERE world_id=? AND user_id=?",
                               (self.world.world_id, player.user_id)).fetchone()[0],
                    db.execute("SELECT count(*) FROM pvp_cells WHERE world_id=?", (self.world.world_id,)).fetchone()[0])
        seed, round_row, saved, cells = await self.store.run(load)
        self.assertEqual(seed, old_seed)
        self.assertEqual(round_row["round_id"], old_round)
        self.assertIsNone(round_row["winner"])
        self.assertEqual(json.loads(saved)["player_money"], 999_990)
        self.assertEqual(json.loads(saved)["player_cargo"]["Ironium"], 1)
        self.assertEqual(cells, old_cells)

    def test_damage_tunables_reject_nonfinite_and_negative(self):
        for value in ("nan", "inf", "-1"):
            with patch.dict(os.environ, {"OREBIT_PVP_DRILL_DPS": value}):
                with self.assertRaises(ValueError):
                    PvpWorld(self.service, APIError)
        with patch.dict(os.environ, {"OREBIT_PVP_DRILL_DPS": "3.5"}):
            self.assertEqual(PvpWorld(self.service, APIError).damage_values["drill"], 3.5)


class PvpNetworkTest(unittest.IsolatedAsyncioTestCase):
    # Reuse the existing real-service fixture, not its inherited co-op test cases.
    asyncSetUp = test_server.CoopServiceTest.asyncSetUp
    asyncTearDown = test_server.CoopServiceTest.asyncTearDown
    start = test_server.CoopServiceTest.start
    stop = test_server.CoopServiceTest.stop
    event = test_server.CoopServiceTest.event
    signup = test_server.CoopServiceTest.signup

    async def join(self, mode="pvp", token=""):
        connection = await self.http.ws_connect(self.base + "/api/ws")
        self.sockets.append(connection)
        await connection.send_json({"type": "join", "mode": mode, "token": token, "pvp_rounds": 1})
        return connection, await connection.receive_json(timeout=5)

    async def test_old_pvp_clients_require_update_without_using_a_slot(self):
        connection = await self.http.ws_connect(self.base + "/api/ws")
        self.sockets.append(connection)
        await connection.send_json({"type": "join", "mode": "pvp"})
        rejection = await connection.receive_json(timeout=5)
        self.assertEqual(rejection["code"], "client_update_required")
        coop, joined = await self.join(mode="coop")
        self.assertEqual(joined["type"], "joined")
        players = [await self.join() for _ in range(5)]
        self.assertTrue(all(event["type"] == "joined" for _, event in players))

    async def test_real_building_protocol_four_shops_finances_and_persistent_reconnect(self):
        account = await self.signup("building_shopper")
        connection, joined = await self.join(token=account["token"])
        state, revision, motion_seq = joined["state"], joined["state_revision"], 0
        request_number = 0

        async def building(script, enter=True):
            nonlocal state, revision, request_number
            request_number += 1
            request_id = f"building-ws-{request_number}"
            await connection.send_json({"type": "building", "round_id": joined["round_id"], "building": script, "enter": enter, "request_id": request_id})
            # Tick broadcasts may already be buffered, but no building_result may
            # arrive before its authoritative full state_sync.
            async with asyncio.timeout(5):
                while True:
                    message = await connection.receive_json()
                    self.assertNotEqual(message.get("type"), "building_result")
                    if message.get("type") == "state_sync":
                        synchronized = message
                        break
            result = await self.event(connection, "building_result")
            self.assertEqual(result["request_id"], request_id)
            self.assertEqual((result["building"], result["enter"]), (script, enter))
            self.assertEqual(result["state"], synchronized["state"])
            self.assertEqual(result["state_revision"], synchronized["state_revision"])
            state, revision = result["state"], result["state_revision"]
            return result

        async def snapshot(requested):
            nonlocal state, revision, motion_seq
            motion_seq += 1
            await connection.send_json({"type": "state", "round_id": joined["round_id"], "state": requested,
                                       "state_revision": revision, "motion_seq": motion_seq})
            ack = await self.event(connection, "state_ack")
            state, revision = ack["state"], ack["state_revision"]
            return ack

        async def walk_to(x):
            while abs(state["x"] - x) > 0.01:
                await asyncio.sleep(0.1)
                requested = copy.deepcopy(state)
                requested["x"] += max(-1.25, min(1.25, x - state["x"]))
                await snapshot(requested)

        self.assertEqual(state["building"], "")
        self.assertFalse((await building("FuelShopManager"))["accepted"])
        self.assertFalse((await building("HelpUI"))["accepted"])
        forged = copy.deepcopy(state)
        forged["building"] = "FuelShopManager"
        await snapshot(forged)
        self.assertEqual(state["building"], "")
        for script, (x, _) in BUILDING_DOORS.items():
            with self.subTest(script=script):
                await walk_to(x)
                self.assertTrue((await building(script))["accepted"])
                self.assertEqual(state["building"], script)
                before = copy.deepcopy(state)
                requested = copy.deepcopy(state)
                requested.update(x=18, y=-200, vx=30, vy=-30, player_fuel=0, alive=False, building="")
                if script == "FuelShopManager":
                    requested.update(player_fuel=12, player_money=15)
                await snapshot(requested)
                self.assertEqual((state["x"], state["y"]), (before["x"], before["y"]))
                self.assertEqual(state["building"], script)
                self.assertEqual(state["player_fuel"], 12)
                self.assertEqual(state["player_money"], 15)
                await connection.send_json({"type": "damage", "round_id": joined["round_id"], "source": "fuel", "amount": 10})
                immune = await self.event(connection, "state_sync")
                self.assertTrue(immune["state"]["alive"])
                self.assertEqual(immune["state"]["player_hp"], 10)
                if script != "ItemShopManager":
                    self.assertTrue((await building(script, False))["accepted"])
                    self.assertEqual(state["building"], "")
                    self.assertEqual(state["y"], -3.5)
        saved = copy.deepcopy(state)
        await self.stop()
        await self.start()
        connection, restored = await self.join(token=account["token"])
        joined = restored
        state, revision, motion_seq = restored["state"], restored["state_revision"], 0
        self.assertEqual(state, saved)
        self.assertEqual(state["building"], "ItemShopManager")
        self.assertFalse(restored["bags"])
        self.assertTrue((await building("ItemShopManager", False))["accepted"])
        self.assertEqual(state["building"], "")
        self.assertEqual((state["alive"], state["player_hp"], state["player_money"]), (True, 10, 15))
        self.assertEqual(state["respawn_at"], 0)

    async def test_building_action_is_not_available_in_coop(self):
        connection, _ = await self.join("coop")
        await connection.send_json({"type": "building", "building": "FuelShopManager", "enter": True, "request_id": "not-pvp"})
        self.assertEqual((await self.event(connection, "error"))["code"], "invalid_message")

    async def test_five_live_pvp_sixth_rejected_and_coop_simultaneous_isolation(self):
        coop, coop_joined = await self.join("coop")
        pvp = [await self.join() for _ in range(5)]
        _, rejected = await self.join()
        self.assertEqual(rejected["code"], "server_full")
        self.assertEqual(len(pvp[-1][1]["players"]), 5)
        self.assertTrue(all(joined["mode"] == "pvp" for _, joined in pvp))
        self.assertNotIn(coop_joined["player_id"], {p["player_id"] for p in pvp[-1][1]["players"]})
        async with self.http.get(self.base + "/healthz") as response:
            health = await response.json()
        self.assertEqual(health["modes"]["coop"]["players"], 1)
        self.assertEqual(health["modes"]["pvp"]["players"], 5)
        first, joined = pvp[0]
        await first.send_json({"type": "transfer", "round_id": joined["round_id"], "recipient_id": coop_joined["player_id"], "amount": 1})
        self.assertFalse((await self.event(first, "transfer_result"))["accepted"])
        await coop.send_json({"type": "state", "state": {"player_money": 999}, "state_revision": 0})
        self.assertEqual((await self.event(coop, "state_ack"))["state"]["player_money"], 999)
        await first.send_json({"type": "state", "round_id": joined["round_id"], "state": joined["state"], "state_revision": -1, "motion_seq": 1})
        self.assertEqual((await self.event(first, "state_sync"))["state"]["player_money"], 20)
        await first.send_json({"type": "state", "round_id": joined["round_id"], "state": joined["state"],
                               "state_revision": joined["state_revision"], "motion_seq": 2})
        ack = await self.event(first, "state_ack")
        self.assertEqual(ack["motion_seq"], 2)
        self.assertEqual(ack["requested_position"], [joined["state"]["x"], joined["state"]["y"]])
        self.assertEqual(ack["state"]["x"], joined["state"]["x"])
        replay = copy.deepcopy(ack["state"])
        replay["x"] += 0.25
        await first.send_json({"type": "state", "round_id": joined["round_id"], "state": replay,
                               "state_revision": ack["state_revision"], "motion_seq": 2})
        self.assertEqual((await self.event(first, "state_sync"))["state"]["x"], ack["state"]["x"])
        await pvp[-1][0].close()
        await self.event(first, "player_left")
        _, replacement = await self.join()
        self.assertEqual(replacement["type"], "joined")

    async def test_real_ten_second_respawn_and_stale_snapshot_cannot_restore_cash(self):
        connection, joined = await self.join()
        before = time.monotonic()
        await connection.send_json({"type": "damage", "round_id": joined["round_id"], "source": "fuel", "amount": 10})
        dead = await self.event(connection, "state_sync")
        self.assertFalse(dead["state"]["alive"])
        self.assertEqual(dead["state"]["player_money"], 0)
        self.assertAlmostEqual(dead["state"]["respawn_at"] - time.time(), 10, delta=1)
        await connection.send_json({"type": "state", "round_id": joined["round_id"], "state": joined["state"], "state_revision": joined["state_revision"], "motion_seq": 1})
        rejected = await self.event(connection, "state_sync")
        self.assertFalse(rejected["state"]["alive"])
        self.assertEqual(rejected["state"]["player_money"], 0)
        async with asyncio.timeout(13):
            while True:
                message = await connection.receive_json()
                if message.get("type") == "state_sync" and message["state"]["alive"]:
                    respawned = message
                    break
        elapsed = time.monotonic() - before
        self.assertGreaterEqual(elapsed, 10)
        self.assertLess(elapsed, 12)
        self.assertEqual(respawned["state"]["player_hp"], 10)
        self.assertEqual(respawned["state"]["current_upgrades"], STOCK_UPGRADES)
        snapshot = await self.event(connection, "pvp_tick")
        cash = next(p["state"]["player_money"] for p in snapshot["players"] if p["player_id"] == joined["player_id"])
        self.assertEqual(cash + sum(bag["amount"] for bag in snapshot["bags"]), joined["state"]["player_money"])

    async def test_real_competing_sales_durable_round_offline_reset_and_stale_routes(self):
        accounts = [await self.signup(name) for name in ("round_first", "round_second", "round_offline")]
        await self.stop()
        database = Path(self.directory.name) / "state.sqlite3"
        coop_state = {"player_money": 4567, "player_items": {"Dynamite": 9}}
        with sqlite3.connect(database) as db:
            for index, account in enumerate(accounts):
                state = stock_state()
                state["player_money"] = 999_990 if index < 2 else 999_999
                state["player_cargo"]["Ironium"] = 1
                state["player_items"]["Dynamite"] = 4
                db.execute("INSERT INTO player_states(world_id,user_id,state,revision,updated_at) VALUES(?,?,?,?,0)",
                           ("public:pvp", account["user"]["id"], json.dumps(state), 7))
            db.execute("INSERT INTO player_states(world_id,user_id,state,revision,updated_at) VALUES(?,?,?,?,0)",
                       ("public", accounts[2]["user"]["id"], json.dumps(coop_state), 3))
            db.execute("INSERT INTO excavations(world_id,x,y,created_at) VALUES('public',5,5,0)")
            db.execute("INSERT INTO pvp_cells(world_id,x,y,tile) VALUES('public:pvp',0,100,0) "
                       "ON CONFLICT(world_id,x,y) DO UPDATE SET tile=excluded.tile")
            runtime = {"bags": [{"id": "old-round-bag", "x": 35.5, "y": -10,
                                  "amount": 123, "vy": 0, "cargo": {"Ironium": 4},
                                  "items": {"Dynamite": 8}}], "falling": [], "impacts": []}
            db.execute("INSERT INTO pvp_runtime(world_id,state) VALUES('public:pvp',?) "
                       "ON CONFLICT(world_id) DO UPDATE SET state=excluded.state", (json.dumps(runtime),))
        await self.start()
        coop, coop_joined = await self.join("coop", accounts[2]["token"])
        connections = [await self.join(token=account["token"]) for account in accounts[:2]]
        old_round, old_seed = connections[0][1]["round_id"], connections[0][1]["seed"]
        requests = []
        for connection, joined in connections:
            state = copy.deepcopy(joined["state"])
            state["player_cargo"]["Ironium"] = 0
            state["player_money"] += 30
            requests.append(connection.send_json({"type": "state", "round_id": old_round,
                                                  "state": state, "state_revision": joined["state_revision"],
                                                  "motion_seq": 99}))
        await asyncio.gather(*requests)
        started = [await self.event(connection, "round_started") for connection, _ in connections]
        current = started[0]
        self.assertNotEqual(current["round_id"], old_round)
        self.assertNotEqual(current["seed"], old_seed)
        self.assertEqual(current["winner"]["round_id"], old_round)
        self.assertEqual(current["winner"]["amount"], 1_000_020)
        self.assertEqual(current["winner"], started[1]["winner"])
        self.assertEqual(current["round_id"], started[1]["round_id"])
        for (connection, joined), reset in zip(connections, started):
            self.assertEqual(reset["player_id"], joined["player_id"])
            self.assertEqual(reset["state"]["player_money"], 20)
            self.assertEqual(reset["state"]["current_upgrades"], STOCK_UPGRADES)
            self.assertFalse(any(reset["state"]["player_cargo"].values()))
            self.assertFalse(any(reset["state"]["player_items"].values()))
            self.assertEqual(reset["bags"], [])
            self.assertEqual(reset["falling"], [])
            self.assertEqual(reset["impacts"], [])
            await connection.send_json({"type": "ping"})
            async with asyncio.timeout(5):
                while True:
                    message = await connection.receive_json()
                    self.assertNotIn(message["type"], ("round_started", "state_ack"))
                    if message["type"] == "pong":
                        break
        connection = connections[0][0]
        # Every mutation route is rejected before request/motion/cooldown state
        # can change, for both missing IDs and a known prior-round ID.
        stale_mutations = [
            {"type": "state", "state": connections[0][1]["state"], "state_revision": current["state_revision"], "motion_seq": 999},
            {"type": "mine", "x": 5, "y": 4},
            {"type": "transfer", "recipient_id": connections[1][1]["player_id"], "amount": 20},
            {"type": "blast", "item": "Dynamite"},
            {"type": "damage", "source": "fuel"},
            {"type": "claim_transmission", "index": 1},
            {"type": "building", "building": "FuelShopManager", "enter": True},
        ]
        for round_id in (None, old_round):
            for index, mutation in enumerate(stale_mutations):
                request_id = f"stale-{round_id}-{index}"
                message = {**mutation, "request_id": request_id}
                if round_id is not None:
                    message["round_id"] = round_id
                await connection.send_json(message)
                rejected = await self.event(connection, "round_rejected")
                self.assertEqual(rejected["request_id"], request_id)
                self.assertEqual(rejected["round_id"], current["round_id"])
                synchronized = await self.event(connection, "state_sync")
                self.assertEqual(synchronized["state"], current["state"])
        await connection.send_json({"type": "state", "round_id": current["round_id"],
                                    "state": current["state"], "state_revision": current["state_revision"],
                                    "motion_seq": 1})
        self.assertEqual((await self.event(connection, "state_ack"))["motion_seq"], 1)
        # Co-op has neither a new round nor reset balances, including when the
        # same account's offline PvP state was reset.
        await coop.send_json({"type": "state", "state": {}, "state_revision": -1})
        self.assertEqual((await self.event(coop, "state_sync"))["state"], coop_state)
        self.assertNotIn("round_id", coop_joined)
        with sqlite3.connect(database) as db:
            saved = db.execute("SELECT state,revision FROM player_states WHERE world_id='public:pvp' AND user_id=?",
                               (accounts[2]["user"]["id"],)).fetchone()
            self.assertEqual(json.loads(saved[0]), stock_state())
            self.assertEqual(saved[1], 8)
            self.assertEqual(db.execute("SELECT count(*) FROM excavations WHERE world_id='public'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM pvp_cells WHERE world_id='public:pvp'").fetchone()[0], 0)
            durable = db.execute("SELECT round_id,winner FROM pvp_rounds WHERE world_id='public:pvp'").fetchone()
            self.assertEqual(durable[0], current["round_id"])
            self.assertEqual(json.loads(durable[1]), current["winner"])
        await self.stop()
        await self.start()
        _, restored = await self.join(token=accounts[2]["token"])
        self.assertEqual(restored["type"], "joined")  # No winner replay on restart.
        self.assertEqual(restored["seed"], current["seed"])
        self.assertEqual(restored["round_id"], current["round_id"])
        self.assertEqual(restored["state"]["player_money"], 20)
        self.assertEqual(restored["bags"], [])
        _, coop_restored = await self.join("coop", accounts[2]["token"])
        self.assertEqual(coop_restored["state"], coop_state)


if __name__ == "__main__":
    unittest.main()
