#!/usr/bin/env python3
"""Run five real WebSocket clients against disposable, deterministic PvP fixtures.

The real service owns combat, gravity, persistence and respawn. Fixture placement
under its world lock replaces random terrain/starting inventory, not game logic.
Run with the co-op Python environment from the repository root.
"""
import argparse
import asyncio
import copy
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "automation/coop"))
from aiohttp import ClientSession, WSMsgType, web
from server import Service, create_app
from pvp import STOCK_UPGRADES, stock_state


class Client:
    def __init__(self, socket):
        self.socket = socket
        self.events = asyncio.Queue()
        self.reader = asyncio.create_task(self.read())
        self.motion_sequence = 0
        self.round_id = ""

    async def read(self):
        async for message in self.socket:
            if message.type == WSMsgType.TEXT:
                import json
                event = json.loads(message.data)
                self.round_id = event.get("round_id", self.round_id)
                self.events.put_nowait(event)

    async def event(self, kind, predicate=lambda event: True, timeout=5):
        async with asyncio.timeout(timeout):
            while True:
                event = await self.events.get()
                if event.get("type") == kind and predicate(event):
                    return event

    async def send(self, kind, **fields):
        if kind == "join" and fields.get("mode") == "pvp":
            fields["pvp_rounds"] = 1
        if kind in ("state", "mine", "transfer", "blast", "damage", "claim_transmission", "building"):
            fields["round_id"] = self.round_id
        if kind == "state":
            self.motion_sequence += 1
            fields["motion_seq"] = self.motion_sequence
        await self.socket.send_json({"type": kind, **fields})

    async def close(self):
        await self.socket.close()
        await self.reader


async def run():
    with tempfile.TemporaryDirectory(prefix="orebit-pvp-scenario-") as directory:
        app = create_app(argparse.Namespace(db=str(Path(directory) / "state.sqlite3")))
        service = next(callback.__self__ for callback in app.on_startup if isinstance(getattr(callback, "__self__", None), Service))
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        clients = []
        try:
            async with ClientSession() as http:
                async def join(mode="pvp"):
                    client = Client(await http.ws_connect(f"http://127.0.0.1:{port}/api/ws"))
                    clients.append(client)
                    await client.send("join", mode=mode)
                    return client

                joined = []
                for _ in range(5):
                    client = await join()
                    joined.append(await client.event("joined"))
                sixth = await join()
                assert (await sixth.event("error"))["code"] == "server_full"
                coop = await join("coop")
                await coop.event("joined")
                world = service.pvp
                players = [world.members[event["player_id"]] for event in joined]
                a, b, c, d, e = players
                sequence = 0

                async def fixture(positions):
                    async with world.world_lock:
                        world.terrain = {x: [0] * 600 for x in range(36)}
                        for x in range(36):
                            world.terrain[x][5] = 1
                        world.bags.clear()
                        world.falling.clear()
                        world.impacts.clear()
                        world.excavated.clear()
                        world.overrides.clear()
                        for index, player in enumerate(players):
                            player.state = stock_state()
                            player.state.update(x=positions[index][0], y=positions[index][1])
                            player.revision += 1
                            player.contact_at = 0
                            player.moved_at = time.monotonic() - 1
                            player.movement_credit = 3
                            player.damage_times.clear()
                        world.dirty_players.update(players)
                        world.runtime_dirty = True
                        await world.persist()

                async def state(index, **values):
                    player = players[index]
                    snapshot = copy.deepcopy(player.state)
                    snapshot.update(values)
                    motion_seq = clients[index].motion_sequence + 1
                    await clients[index].send("state", state=snapshot, state_revision=player.revision)
                    return await clients[index].event("state_ack", lambda event: event.get("motion_seq") == motion_seq)

                async def blast(item):
                    nonlocal sequence
                    sequence += 1
                    await clients[0].send("blast", item=item, request_id=f"smoke-{sequence}")
                    result = await clients[0].event("blast_result")
                    assert result["accepted"]
                    await clients[0].event("pvp_tick")

                positions = [(8, -3.55), (8.8, -3.55), (16, -3.55), (22, -3.55), (30, -3.55)]
                await fixture(positions)
                await state(0, x=10)
                assert a.state["x"] <= b.state["x"] - 0.8 + 1e-6
                assert all(player.state["player_hp"] == 10 for player in players)
                await state(0, drill_x=-1)
                await clients[0].event("pvp_tick")
                assert b.state["player_hp"] == 10
                # Keep contact engaged across authoritative simulation ticks.
                before = time.monotonic()
                while time.monotonic() - before < 1.1:
                    await state(0, drill_x=1, facing=True)
                    await clients[0].event("pvp_tick")
                await state(0, drill_x=0)
                assert 7.0 < b.state["player_hp"] < 8.5
                print("PASS five-client capacity, mode isolation, solid collision, directional/time-based drill")

                sky_positions = [(x, 12.5) for x, _ in positions]
                await fixture(sky_positions)
                await state(0, drill_x=0, facing=True)
                await clients[0].event("pvp_tick")
                assert b.state["player_hp"] == 10
                before = time.monotonic()
                while time.monotonic() - before < 0.6:
                    await state(0, drill_x=1, facing=True)
                    await clients[0].event("pvp_tick")
                await state(0, drill_x=0)
                airborne_hp = b.state["player_hp"]
                assert 8.0 < airborne_hp < 9.5
                before = time.monotonic()
                while time.monotonic() - before < 0.5:
                    await clients[0].event("pvp_tick")
                assert b.state["player_hp"] == airborne_hp
                print("PASS airborne forward drill contact, immediate input release, passive contact immunity")

                await fixture(positions)
                a.state["player_items"]["Dynamite"] = 1
                await blast("Dynamite")
                assert a.state["player_hp"] == 10 and b.state["player_hp"] == 6
                assert c.state["player_hp"] == 10
                await fixture(positions)
                a.state["player_items"]["Plastic Explosives"] = 1
                await blast("Plastic Explosives")
                assert a.state["player_hp"] == 10 and b.state["player_hp"] == 3
                print("PASS real item-consuming dynamite/plastic blasts, owner immunity, range exclusion")

                for tile, damage in [(25, 3), (28, 5)]:
                    await fixture(positions)
                    async with world.world_lock:
                        world.set_cell(8, 1, tile)
                        world.set_cell(7, 1, 1)
                        world.detach_hazards()
                        assert not world.falling
                        world.set_cell(7, 1, 0)
                        world.detach_hazards()
                        assert len(world.falling) == 1
                    await clients[0].event("pvp_tick", lambda event: any(p["player_id"] == a.player_id and p["state"]["player_hp"] == 10 - damage for p in event["players"]))
                    impact_event = await clients[0].event("pvp_tick", lambda event: not event["falling"] and bool(event["impacts"]))
                    impact = impact_event["impacts"][0]
                    assert abs(impact["expires_at"] - impact["started_at"] - 2.5) < 1e-6
                    assert a.state["player_hp"] == 10 - damage
                    assert world.terrain[8][4] == 0
                    await clients[0].event("pvp_tick", lambda event: not event["impacts"])
                    assert a.state["player_hp"] == 10 - damage
                print("PASS support removal, real-gravity rock/lava impact, harmless residue and 2.5s expiry")

                await fixture([(8, -3.55), (12, -1), (14, -3.55), (22, -3.55), (30, -3.55)])
                async with world.world_lock:
                    b.state["player_money"] = 55
                    b.state["current_upgrades"]["Hull"] = "Ironium Hull"
                    b.state["player_hp"] = 17
                    b.state["player_items"]["Dynamite"] = 2
                    b.state["player_cargo"]["Ironium"] = 1
                death_started = time.monotonic()
                await clients[1].send("damage", source="fuel", amount=10)
                dead = await clients[1].event("state_sync", lambda event: not event["state"]["alive"])
                assert dead["state"]["player_money"] == 0
                bag = copy.deepcopy(world.bags[0])
                assert bag["cargo"]["Ironium"] == 1 and bag["items"]["Dynamite"] == 2
                await clients[0].event("pvp_tick", lambda event: bool(event["bags"]) and event["bags"][0]["y"] < bag["y"] - 0.1)
                landed = await clients[0].event("pvp_tick", lambda event: bool(event["bags"]) and abs(event["bags"][0]["y"] + 3.5) < 1e-6)
                assert landed["bags"][0]["x"] == bag["x"]
                # A one-tile bag rests on row5's top (-4), and a real hull can
                # hover .05 above its visible top without making physical contact.
                await state(2, x=12, y=-2.5)
                pickup = await clients[2].event("state_sync", lambda event: event["state"]["player_money"] == 75)
                assert pickup["state"]["player_cargo"]["Ironium"] == 1
                assert pickup["state"]["player_items"]["Dynamite"] == 2
                assert not world.bags
                respawn = await clients[1].event("state_sync", lambda event: event["state"]["alive"], timeout=12)
                assert 10 <= time.monotonic() - death_started < 12
                assert respawn["state"]["player_hp"] == 10
                assert respawn["state"]["current_upgrades"] == STOCK_UPGRADES
                assert respawn["state"]["player_money"] == 0
                assert respawn["state"]["player_items"]["Dynamite"] == 0
                assert respawn["state"]["player_cargo"]["Ironium"] == 0
                print("PASS cash/cargo/item death loot, bag gravity/pickup conservation, actual 10s stock respawn")

                await fixture([(8, -3.55), (12, -1), (14, -2.5), (10, -3.55), (14, -3.55)])
                b.state["player_money"] = 55
                b.state["player_items"]["Dynamite"] = 2
                b.state["player_cargo"].update(Ironium=1, Goldium=2)
                c.state["player_cargo"]["Ironium"] = 7
                d.state["player_cargo"]["Ironium"] = 6
                await clients[1].send("damage", source="fuel", amount=10)
                await clients[0].event("pvp_tick", lambda event: bool(event["bags"]) and abs(event["bags"][0]["y"] + 3.5) < 1e-6)
                await state(2, x=12, y=-2.5)
                full = await clients[2].event("state_sync", lambda event: event["state"]["player_money"] == 75)
                assert full["state"]["player_cargo"]["Ironium"] == 7
                assert full["state"]["player_items"]["Dynamite"] == 2
                assert len(world.bags) == 1 and world.bags[0]["cargo"]["Goldium"] == 2
                await state(3, x=11, y=-3.55)
                partial = await clients[3].event("state_sync", lambda event: event["state"]["player_cargo"]["Ironium"] == 7)
                assert partial["state"]["player_cargo"]["Goldium"] == 0
                assert world.bags[0]["cargo"]["Ironium"] == 0 and world.bags[0]["cargo"]["Goldium"] == 2
                await state(4, x=13, y=-3.55)
                await clients[4].event("state_sync", lambda event: event["state"]["player_cargo"]["Goldium"] == 2)
                assert not world.bags
                assert sum(p.state["player_cargo"]["Ironium"] for p in players) == 14
                assert sum(p.state["player_items"]["Dynamite"] for p in players) == 2
                print("PASS full bay still collects cash/items, weighted partial pickup leaves heavy ore, later pickup conserves loot")

                await fixture([(10, -2.5), (12, -1), (14, -2.5), (22, -3.55), (30, -3.55)])
                b.state["player_money"] = 55
                b.state["player_items"]["Dynamite"] = 2
                b.state["player_cargo"].update(Ironium=2, Goldium=1)
                await clients[1].send("damage", source="fuel", amount=10)
                await clients[0].event("pvp_tick", lambda event: bool(event["bags"]) and abs(event["bags"][0]["y"] + 3.5) < 1e-6)
                await asyncio.gather(state(0, x=11.1, y=-2.5), state(2, x=12.9, y=-2.5))
                await clients[0].event("pvp_tick", lambda event: not event["bags"])
                assert sum(p.state["player_money"] for p in players) == 135
                assert sum(p.state["player_cargo"]["Ironium"] for p in players) == 2
                assert sum(p.state["player_cargo"]["Goldium"] for p in players) == 1
                assert sum(p.state["player_items"]["Dynamite"] for p in players) == 2
                assert sum(p.state["player_money"] == 75 for p in players) == 1
                print("PASS concurrent real-client pickups cannot duplicate cash, minerals or consumables")
                assert len(service.members) == 1 and len(world.members) == 5
                print("OREBIT_PVP_FIVE_CLIENT_SCENARIO PASS")
        finally:
            for client in clients:
                await client.close()
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(run())
