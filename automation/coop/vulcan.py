"""Co-op terrain/economy with an isolated, durable, server-owned ten-tile worm.

Wire: join mode=vulcan; co-op state plus drilling:bool (actual drill animation).
joined/vulcan_tick contain worm and Unity-world-coordinate segments, head first.
worm_death/worm_respawn carry player_id, state, state_revision, respawn_at and
server_time. State revisions fence pre-death snapshots. Terrain changes use
[x, depth, 0], matching ordinary co-op excavations; the worm never awards ore.

Conservative spawn: head (18.5,-19.5), nine tiles behind it downwards. Idle until
first drilling; no offline catch-up, and no movement without connected miners.
The worm stays below the surface (center y <= -5.5), preserving shops/pavement
and the fixed co-op respawn pad (5.5,-3.5). Immutable core scenery is not eaten.
Death loses all cargo and consumable items, never money or purchased upgrades.
"""
from __future__ import annotations

import asyncio
import copy
import json
import math
import secrets
import time

from pvp import HULL_HP, ITEM_NAMES, STOCK_UPGRADES
from terrain import HEIGHT, MIN_X, WEIGHTS, WIDTH, generate, tile_name

# game_data.gd Stock Engine effect=6.0; port_player.gd uses it on both axes.
BASE_FLYING_SPEED = 6.0
WORM_SPEED = BASE_FLYING_SPEED * 0.9
WORM_LENGTH = 10
TICK_SECONDS = 0.1
RESPAWN_SECONDS = 3.0
DRILL_TIMEOUT = 0.75
FUEL_CAPACITY = dict(zip(("Micro Tank", "Medium Tank", "Huge Tank", "Gigantic Tank", "Titanic Tank", "Leviathan Tank", "Liquid Compression Tank"), (10, 15, 25, 40, 60, 100, 150)))
DIRECTIONS = ((0, 1), (1, 0), (0, -1), (-1, 0))


def stock_state():
    return {"x": 5.5, "y": -3.5, "facing": False, "alive": True,
            "player_hp": 10, "player_fuel": 10, "player_money": 20,
            "current_upgrades": dict(STOCK_UPGRADES),
            "player_cargo": dict.fromkeys(WEIGHTS, 0),
            "player_items": dict.fromkeys(ITEM_NAMES, 0), "transmissions": [],
            "drilling": False, "respawn_at": 0}


class VulcanWorld:
    def __init__(self, service, error_type):
        self.service, self.error = service, error_type
        self.store = service.vulcan_store
        self.world_id = service.world_id + ":vulcan"
        self.world_lock = asyncio.Lock()
        self.members = {}
        self.seed, self.terrain, self.excavated = 0, {}, set()
        self.nodes = [[18.5, -19.5 - index] for index in range(WORM_LENGTH)]
        self.direction, self.progress = [0, 1], 0.0
        self.last_drill = None
        self.target_id = ""
        self.dirty_players, self.dirty_cells = set(), set()
        self.events = []
        self.runtime_dirty = False
        self.task, self.failed = None, False
        self.send = service.send

    @staticmethod
    def encode(value):
        return json.dumps(value, separators=(",", ":"), allow_nan=False)

    async def startup(self):
        def load(db):
            db.execute("CREATE TABLE IF NOT EXISTS vulcan_runtime (world_id TEXT PRIMARY KEY REFERENCES worlds(id), state TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO worlds(id,seed,created_at) VALUES(?,?,?)", (self.world_id, secrets.randbelow(2147483646) + 1, int(time.time())))
            seed = db.execute("SELECT seed FROM worlds WHERE id=?", (self.world_id,)).fetchone()[0]
            cells = {tuple(row) for row in db.execute("SELECT x,y FROM excavations WHERE world_id=?", (self.world_id,))}
            row = db.execute("SELECT state FROM vulcan_runtime WHERE world_id=?", (self.world_id,)).fetchone()
            return seed, cells, json.loads(row[0]) if row else None
        self.seed, self.excavated, runtime = await self.store.run(load)
        self.terrain = await asyncio.to_thread(generate, self.seed)
        if runtime:
            self.nodes, self.direction, self.progress = runtime["nodes"], runtime["direction"], runtime["progress"]
            self.last_drill = runtime["last_drill"]
        # The complete initial body excavates too, not merely a later head step.
        self.consume_body()
        self.runtime_dirty = True
        await self.persist()
        self.task = asyncio.create_task(self.run(), name="orebit-vulcan-simulation")

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        async with self.world_lock:
            await self.persist()

    async def run(self):
        previous = time.monotonic()
        try:
            while True:
                await asyncio.sleep(TICK_SECONDS)
                current = time.monotonic()
                elapsed, previous = min(current - previous, 0.5), current
                async with self.world_lock:
                    self.step(elapsed, time.time(), current)
                    if self.members:
                        await self.publish()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failed = True
            asyncio.get_running_loop().call_exception_handler({"message": "Vulcan simulation failed", "exception": error})
            await asyncio.gather(*(p.socket.close(code=1011, message=b"Vulcan simulation stopped; reconnect to resume") for p in list(self.members.values())), return_exceptions=True)

    async def broadcast(self, message, exclude=None):
        await asyncio.gather(*(self.send(p, message) for p in list(self.members.values()) if p is not exclude))

    def public(self, player):
        return {**player.public(), "state_revision": player.revision}

    def segments(self):
        result = [[self.nodes[0][axis] + self.direction[axis] * self.progress for axis in (0, 1)]]
        for index in range(1, WORM_LENGTH):
            result.append([self.nodes[index][axis] + (self.nodes[index - 1][axis] - self.nodes[index][axis]) * self.progress for axis in (0, 1)])
        return result

    def worm(self):
        return {"segments": self.segments(), "direction": list(self.direction),
                "speed": WORM_SPEED, "step_interval": 1 / WORM_SPEED,
                "target_player_id": self.target_id, "last_drill": self.last_drill,
                "server_time": time.time()}

    def join_details(self):
        return {"mode": "vulcan", "worm": self.worm(), "server_time": time.time()}

    def save_state(self, db, player, state, revision):
        if player.user_id is not None:
            db.execute("INSERT INTO player_states(world_id,user_id,state,revision,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(world_id,user_id) DO UPDATE SET state=excluded.state,revision=excluded.revision,updated_at=excluded.updated_at", (self.world_id, player.user_id, self.encode(state), revision, int(time.time())))

    async def persist(self):
        if not self.dirty_players and not self.dirty_cells and not self.runtime_dirty:
            return
        runtime = {"nodes": self.nodes, "direction": self.direction, "progress": self.progress, "last_drill": self.last_drill}
        def commit(db):
            for player in self.dirty_players:
                self.save_state(db, player, player.state, player.revision)
            db.executemany("INSERT OR IGNORE INTO excavations(world_id,x,y,user_id,created_at) VALUES(?,?,?,NULL,?)", [(self.world_id, x, y, int(time.time())) for x, y in self.dirty_cells])
            if self.runtime_dirty:
                db.execute("INSERT INTO vulcan_runtime(world_id,state) VALUES(?,?) ON CONFLICT(world_id) DO UPDATE SET state=excluded.state", (self.world_id, self.encode(runtime)))
        await self.store.run(commit)
        self.dirty_players.clear()
        self.dirty_cells.clear()
        self.runtime_dirty = False

    async def publish(self):
        changes = [[x, y, 0] for x, y in sorted(self.dirty_cells)]
        changed, events = list(self.dirty_players), list(self.events)
        await self.persist()
        self.events.clear()
        for event in events:
            await self.broadcast(event)
        for player in changed:
            await self.sync(player)
        await self.broadcast({"type": "vulcan_tick", "worm": self.worm(), "terrain_changes": changes,
                              "players": [self.public(p) for p in self.members.values()], "server_time": time.time()})

    async def sync(self, player):
        await self.send(player, {"type": "state_sync", "state": player.state, "state_revision": player.revision})

    async def prepare_player(self, player):
        if self.failed:
            raise self.error("vulcan_unavailable", "Vulcan simulation is unavailable. Other modes remain available.", 503)
        player.state = {**stock_state(), **player.state}
        player.state["drilling"] = False
        if not player.state["alive"] and player.state["respawn_at"] <= time.time():
            self.respawn(player, time.time())
        elif player.state["alive"] and self.touches_body(player.state["x"], player.state["y"]):
            self.kill(player, time.time())
        self.dirty_players.add(player)
        # This player is not a world member until joined has been sent.
        await self.persist()
        self.events = [event for event in self.events if event["player_id"] != player.player_id]

    def target(self, monotonic):
        head = self.segments()[0]
        active = [p for p in self.members.values() if p.state["alive"] and p.state.get("drilling", False) and monotonic - p.contact_at <= DRILL_TIMEOUT]
        if active:
            nearest = min(active, key=lambda p: ((p.state["x"] - head[0]) ** 2 + (p.state["y"] - head[1]) ** 2, p.player_id))
            self.target_id = nearest.player_id
            self.last_drill = [nearest.state["x"], nearest.state["y"]]
            self.runtime_dirty = True
        else:
            self.target_id = ""
        return self.last_drill

    def choose_direction(self, target):
        x, y = self.nodes[0]
        tx = max(MIN_X + 0.5, min(WIDTH - 0.5, math.floor(target[0]) + 0.5))
        ty = max(-HEIGHT + 1.5, min(-5.5, math.floor(target[1]) + 0.5))
        if abs(tx - x) < 1e-8 and abs(ty - y) < 1e-8:
            return False
        candidates = []
        for dx, dy in DIRECTIONS:
            # A snake cannot reverse into its neck; it can turn at grid nodes.
            if [dx, dy] == [-self.direction[0], -self.direction[1]]:
                continue
            nx, ny = x + dx, y + dy
            if not MIN_X + 0.5 <= nx <= WIDTH - 0.5 or not -HEIGHT + 1.5 <= ny <= -5.5:
                continue
            tile = self.terrain[math.floor(nx)][math.floor(0.5 - ny)]
            if tile != 0 and not tile_name(tile):
                continue
            candidates.append((abs(tx - nx) + abs(ty - ny), (dx, dy) != tuple(self.direction), dx, dy))
        if not candidates:
            return False
        _, _, dx, dy = min(candidates)
        self.direction = [dx, dy]
        return True

    def consume_body(self):
        for x, y in self.segments():
            for cx in range(math.floor(x - 0.5 + 1e-8), math.floor(x + 0.5 - 1e-8) + 1):
                for cy in range(math.floor(1 - y - 0.5 + 1e-8), math.floor(1 - y + 0.5 - 1e-8) + 1):
                    if MIN_X <= cx < WIDTH and 0 <= cy < HEIGHT and (cx, cy) not in self.excavated and tile_name(self.terrain[cx][cy]):
                        self.excavated.add((cx, cy))
                        self.dirty_cells.add((cx, cy))

    def touches_body(self, x, y):
        return any(abs(x - bx) <= 0.9 and abs(y - by) <= 0.95 for bx, by in self.segments())

    def kill(self, player, now):
        if not player.state["alive"]:
            return
        player.state = copy.deepcopy(player.state)
        player.state.update(alive=False, player_hp=0, drilling=False, respawn_at=now + RESPAWN_SECONDS,
                            player_cargo=dict.fromkeys(WEIGHTS, 0), player_items=dict.fromkeys(ITEM_NAMES, 0))
        player.revision += 1
        self.dirty_players.add(player)
        self.events.append(self.life_event("worm_death", player, now))

    def respawn(self, player, now):
        upgrades = player.state["current_upgrades"]
        player.state = copy.deepcopy(player.state)
        player.state.update(x=5.5, y=-3.5, alive=True, drilling=False, respawn_at=0,
                            player_hp=HULL_HP.get(upgrades.get("Hull"), 10),
                            player_fuel=FUEL_CAPACITY.get(upgrades.get("Fuel"), 10))
        player.revision += 1
        self.dirty_players.add(player)
        self.events.append(self.life_event("worm_respawn", player, now))

    @staticmethod
    def life_event(kind, player, now):
        return {"type": kind, "player_id": player.player_id, "state": copy.deepcopy(player.state),
                "state_revision": player.revision, "respawn_at": player.state["respawn_at"], "server_time": now}

    def step(self, elapsed, now, monotonic):
        if not self.members:
            return
        for player in self.members.values():
            if not player.state["alive"] and player.state["respawn_at"] <= now:
                self.respawn(player, now)
        target = self.target(monotonic)
        distance = max(0, elapsed) * WORM_SPEED if target else 0
        # Substeps sweep every body segment, including stationary contact.
        while True:
            self.consume_body()
            for player in self.members.values():
                if player.state["alive"] and self.touches_body(player.state["x"], player.state["y"]):
                    self.kill(player, now)
            if distance <= 1e-9:
                break
            if self.progress <= 1e-9 and not self.choose_direction(target):
                break
            movement = min(distance, 0.08, 1 - self.progress)
            self.progress += movement
            distance -= movement
            self.runtime_dirty = True
            if self.progress >= 1 - 1e-9:
                self.nodes.insert(0, [self.nodes[0][axis] + self.direction[axis] for axis in (0, 1)])
                self.nodes.pop()
                self.progress = 0.0

    async def update_state(self, player, message):
        incoming = message.get("state")
        if not isinstance(incoming, dict):
            raise self.error("invalid_state", "Invalid player state.")
        drilling = incoming.get("drilling", False)
        if type(drilling) is not bool:
            raise self.error("invalid_state", "drilling must be a boolean.")
        base = {key: value for key, value in incoming.items() if key not in ("drilling", "respawn_at")}
        self.service.validate_state(base)
        if message.get("state_revision") != player.revision or not player.state["alive"]:
            await self.sync(player)
            return
        old = player.state
        state = {**copy.deepcopy(old), **base, "drilling": drilling, "respawn_at": 0}
        # Only the server can revive a pod. Client damage/death otherwise follows co-op.
        if not state.get("alive", True) or state.get("player_hp", 1) <= 0:
            state["alive"] = True
            player.state = state
            self.kill(player, time.time())
        else:
            ox, oy, nx, ny = old["x"], old["y"], state["x"], state["y"]
            steps = max(1, math.ceil(max(abs(nx - ox), abs(ny - oy)) / 0.1))
            # Do not adopt a carried-money/inventory snapshot before a swept kill.
            collision = any(self.touches_body(ox + (nx - ox) * index / steps, oy + (ny - oy) * index / steps) for index in range(steps + 1))
            if collision:
                self.kill(player, time.time())
            else:
                player.state = state
                player.contact_at = time.monotonic()
                self.dirty_players.add(player)
                # Record even a drill burst ending before the next 100ms tick.
                if drilling:
                    self.target(player.contact_at)
        player.state_updates += 1
        if self.events:
            await self.publish()
        else:
            await self.persist()
            await self.send(player, {"type": "state_ack", "state": player.state, "state_revision": player.revision})
            await self.broadcast({"type": "state", "player_id": player.player_id, "state": player.state}, exclude=player)

    async def mine(self, player, message):
        if not player.state["alive"]:
            await self.sync(player)
            return
        # Reuse the unchanged co-op validation, awards and atomic excavation path.
        await type(self.service).mine(self, player, message)

    async def transfer(self, player, message):
        await type(self.service).transfer(self, player, message)