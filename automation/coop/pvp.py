"""Isolated, persistent PvP simulation; authentication and transport stay in server.py."""
from __future__ import annotations

import asyncio
import copy
import math
import os
import secrets
import time

from terrain import CARGO_CAPACITY, HEIGHT, WIDTH, WEIGHTS, award, generate, tile_name, unsupported_hazards

STOCK_UPGRADES = {"Drill": "Stock Drill", "Hull": "Stock Hull", "Engine": "Stock Engine", "Fuel": "Micro Tank", "Radiator": "Stock Fan", "Cargo": "Micro Bay"}
HULL_HP = dict(zip(("Stock Hull", "Ironium Hull", "Bronzium Hull", "Steel Hull", "Platinium Hull", "Einsteinium Hull", "Energy-Shielded Hull"), (10, 17, 30, 50, 80, 120, 180)))
ITEM_NAMES = ("Reserve Fuel Tank", "Hull Repair Nanobots", "Dynamite", "Plastic Explosives", "Quantum Teleporter", "Matter Transmitter")
DAMAGE = {"Dynamite": 4.0, "Plastic Explosives": 7.0, "Rock": 3.0, "Lava": 5.0, "drill": 2.0}
BLAST_RADIUS = {"Dynamite": 1, "Plastic Explosives": 2}
BLAST_HALF_SIZE = {"Dynamite": 1.5, "Plastic Explosives": 2.25}
ITEM_PRICES = dict(zip(ITEM_NAMES, (2000, 7500, 2000, 5000, 2000, 10000)))
ORE_VALUES = dict(zip(WEIGHTS, (30, 60, 100, 250, 750, 2000, 5000, 20000, 100000, 500000)))
UPGRADE_NAMES = {
    "Drill": ("Stock Drill", "Silvide Drill", "Goldium Drill", "Emerald Drill", "Ruby Drill", "Diamond Drill", "Amazonite Drill"),
    "Hull": tuple(HULL_HP),
    "Engine": ("Stock Engine", "V4 1600 cc", "V4 2.0 Ltr Turbo", "V6 3.8 Ltr", "V8 Supercharged 5.0 Ltr", "V12 6.0 Ltr", "V16 Jag Engine"),
    "Fuel": ("Micro Tank", "Medium Tank", "Huge Tank", "Gigantic Tank", "Titanic Tank", "Leviathan Tank", "Liquid Compression Tank"),
    "Radiator": ("Stock Fan", "Dual Fans", "Single Turbine", "Dual Turbines", "Puron Cooling", "Tri-Turbine Freon Array"),
    "Cargo": ("Micro Bay", "Medium Bay", "Huge Bay", "Gigantic Bay", "Titanic Bay", "Leviathan Bay"),
}
UPGRADE_PRICES = {category: dict(zip(names, (2 if category == "Drill" else 0, 750, 2000, 5000, 20000, 100000, 500000))) for category, names in UPGRADE_NAMES.items()}
UPGRADE_PRICES["Radiator"] = dict(zip(UPGRADE_NAMES["Radiator"], (0, 2000, 5000, 20000, 100000, 500000)))
RESPAWN_SECONDS = 10.0
TICK_SECONDS = 0.1
IMPACT_SECONDS = 2.5
GRAVITY = 9.8100004196167  # Match Godot's world gravity; swept collision needs no speed cap.
POD_HALF_WIDTH = 0.4
POD_HALF_HEIGHT = 0.45
# MoneyBag's 50px sprite is rendered at 1/50 world units per pixel.
BAG_HALF_SIZE = 0.5
BAG_PICKUP_MARGIN = 0.1
EXTRA_STATE_KEYS = {"drill_x", "drill_y", "vx", "vy", "respawn_at"}
SERVER_STATE_KEYS = {"deepest_y", "claimed_transmissions", "building"}
# Authored bonus trigger bands centered at depths 45.5, 85.5 and 285.5.
TRANSMISSION_BONUSES = {1: (-44.0, 1000), 2: (-84.0, 3000), 7: (-284.0, 25000)}
# Native authored door centers, in the same tile units as accepted player poses.
BUILDING_DOORS = {"FuelShopManager": (3.2404, -3.637), "MineralBuyerManager": (10.92, -3.6023),
                  "UpgradeShopUI": (24.4346, -3.6228), "ItemShopManager": (30.9, -3.6228)}
BUILDING_ENTRY_RADIUS = 1.5
VICTORY_CASH = 1_000_000
MAX_COUNTER = 1_000_000_000
MAX_CASH = 1e15
MUTATIONS = frozenset(("state", "mine", "transfer", "blast", "damage", "claim_transmission", "building"))


def inventory(value, names):
    """Normalize historical bags without accepting unbounded/noninteger counters."""
    value = value if isinstance(value, dict) else {}
    return {name: int(count) if type(count) in (int, float) and 0 <= count <= MAX_COUNTER
            and math.isfinite(count) and count == int(count) else 0
            for name in names for count in (value.get(name, 0),)}


def stock_state(x=5.5):
    return {"x": x, "y": -3.5, "facing": False, "alive": True, "player_hp": 10,
            "player_fuel": 10, "player_money": 20, "current_upgrades": dict(STOCK_UPGRADES),
            "player_items": dict.fromkeys(ITEM_NAMES, 0), "player_cargo": dict.fromkeys(WEIGHTS, 0),
            "transmissions": [], "drill_x": 0, "drill_y": 0, "vx": 0, "vy": 0, "respawn_at": 0, "building": ""}


def overlaps(ax, ay, bx, by, half_width=POD_HALF_WIDTH * 2, half_height=POD_HALF_HEIGHT * 2):
    return abs(ax - bx) < half_width - 1e-8 and abs(ay - by) < half_height - 1e-8


def segment_near(ax, ay, bx, by, px, py, radius):
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    fraction = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length)) if length else 0.0
    return math.hypot(px - ax - fraction * dx, py - ay - fraction * dy) <= radius


class PvpWorld:
    def __init__(self, service, error_type):
        self.service = service
        self.error = error_type
        self.store = service.store
        # A colon cannot occur in the externally configured co-op world ID.
        self.world_id = service.world_id + ":pvp"
        self.members = {}
        self.world_lock = asyncio.Lock()
        self.seed = 0
        self.round_id = ""
        self.winner = None
        self.pending_winner = None
        self.terrain = {}
        self.excavated = set()
        self.overrides = {}
        self.bags = []
        self.falling = []
        self.impacts = []
        self.dirty_players = set()
        self.dirty_cells = {}
        self.runtime_dirty = False
        self.task = None
        self.failed = False
        # Tag even direct state/results messages, not only snapshots.
        self.send = self.send_round
        self.damage_values = {}
        for source, suffix in (("Dynamite", "DYNAMITE_DAMAGE"), ("Plastic Explosives", "PLASTIC_DAMAGE"), ("Rock", "ROCK_DAMAGE"), ("Lava", "LAVA_DAMAGE"), ("drill", "DRILL_DPS")):
            value = float(os.environ.get("OREBIT_PVP_" + suffix, DAMAGE[source]))
            if not math.isfinite(value) or value < 0:
                raise ValueError("PvP damage tunables must be finite and nonnegative")
            self.damage_values[source] = value

    async def startup(self):
        def load(db):
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pvp_cells (
                    world_id TEXT NOT NULL REFERENCES worlds(id), x INTEGER NOT NULL,
                    y INTEGER NOT NULL, tile INTEGER NOT NULL, PRIMARY KEY(world_id,x,y)
                );
                CREATE TABLE IF NOT EXISTS pvp_runtime (
                    world_id TEXT PRIMARY KEY REFERENCES worlds(id), state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pvp_rounds (
                    world_id TEXT PRIMARY KEY REFERENCES worlds(id),
                    round_id TEXT NOT NULL, winner TEXT
                );
            """)
            db.execute("INSERT OR IGNORE INTO worlds(id,seed,created_at) VALUES(?,?,?)", (self.world_id, secrets.randbelow(2147483646) + 1, int(time.time())))
            seed = db.execute("SELECT seed FROM worlds WHERE id=?", (self.world_id,)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO pvp_rounds(world_id,round_id) VALUES(?,?)", (self.world_id, secrets.token_hex(16)))
            round_row = db.execute("SELECT round_id,winner FROM pvp_rounds WHERE world_id=?", (self.world_id,)).fetchone()
            cells = [tuple(row) for row in db.execute("SELECT x,y,tile FROM pvp_cells WHERE world_id=?", (self.world_id,))]
            row = db.execute("SELECT state FROM pvp_runtime WHERE world_id=?", (self.world_id,)).fetchone()
            return seed, cells, self.decode(row[0]) if row else {"bags": [], "falling": [], "impacts": []}, round_row["round_id"], self.decode(round_row["winner"]) if round_row["winner"] else None
        self.seed, cells, runtime, self.round_id, self.winner = await self.store.run(load)
        self.terrain = await asyncio.to_thread(generate, self.seed, pvp=True)
        for x, y, tile in cells:
            self.terrain[x][y] = tile
            self.overrides[x, y] = tile
            if tile == 0:
                self.excavated.add((x, y))
        self.bags, self.falling = runtime["bags"], runtime["falling"]
        for bag in self.bags:
            bag["cargo"] = inventory(bag.get("cargo"), WEIGHTS)
            bag["items"] = inventory(bag.get("items"), ITEM_NAMES)
        now = time.time()
        self.impacts = [impact for impact in runtime.get("impacts", []) if impact["expires_at"] > now]
        self.runtime_dirty = len(self.impacts) != len(runtime.get("impacts", []))
        self.detach_hazards()
        await self.persist()
        self.task = asyncio.create_task(self.run(), name="orebit-pvp-simulation")

    @staticmethod
    def decode(value):
        import json
        return json.loads(value)

    @staticmethod
    def encode(value):
        import json
        return json.dumps(value, separators=(",", ":"), allow_nan=False)

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        async with self.world_lock:
            if not self.failed:
                await self.persist()

    async def run(self):
        previous = time.monotonic()
        try:
            while True:
                await asyncio.sleep(TICK_SECONDS)
                current = time.monotonic()
                elapsed = min(current - previous, 0.5)
                previous = current
                async with self.world_lock:
                    if self.failed:
                        raise RuntimeError("PvP authority requires restart after a failed round reset")
                    # Substeps keep gravity collision and drill integration independent
                    # of a moderately delayed network/database tick.
                    while elapsed > 1e-8:
                        step = min(elapsed, TICK_SECONDS)
                        self.step(step, time.time(), current)
                        if self.pending_winner:
                            await self.finish_round()
                            break
                        elapsed -= step
                    changes = [[x, y, tile] for (x, y), tile in sorted(self.dirty_cells.items())]
                    changed_players = list(self.dirty_players)
                    await self.persist()
                    for player in changed_players:
                        await self.sync(player)
                    if self.members:
                        await self.broadcast({"type": "pvp_tick", **self.snapshot(changes)})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failed = True
            # A failed authoritative save must never keep running an unsaved world.
            asyncio.get_running_loop().call_exception_handler({"message": "PvP simulation failed", "exception": error})
            await asyncio.gather(*(p.socket.close(code=1011, message=b"PvP simulation stopped; reconnect to resume") for p in list(self.members.values())), return_exceptions=True)

    async def broadcast(self, message, exclude=None):
        await asyncio.gather(*(self.send(p, message) for p in list(self.members.values()) if p is not exclude))

    async def send_round(self, player, message):
        await self.service.send(player, {**message, "round_id": self.round_id})

    def accepts_round(self, message):
        return message.get("round_id") == self.round_id

    def recognize_winner(self, player):
        if self.pending_winner is None and player.state.get("player_money", 0) >= VICTORY_CASH:
            self.pending_winner = {"player_id": player.player_id, "name": player.name,
                                   "amount": player.state["player_money"], "round_id": self.round_id}
        return self.pending_winner is not None

    async def finish_round(self):
        """Commit winner, new world and every PvP save together before publication.

        The caller holds world_lock through generation, commit and notifications.
        Never save a winning balance separately: a restart sees either the old
        transaction or the completely reset round, not an unannounced winner.
        """
        if self.pending_winner is None:
            return False
        winner = self.pending_winner
        self.failed = True
        seed = secrets.randbelow(2147483645) + 1
        if seed >= self.seed:
            seed += 1
        terrain = await asyncio.to_thread(generate, seed, pvp=True)
        round_id = secrets.token_hex(16)
        states = [(p, stock_state(x), p.revision + 1)
                  for p, x in zip(self.members.values(), (5.5, 10.5, 14.5, 22.5, 30.5))]
        completed_states = {p.player_id: p.state for p, _, _ in states}

        def commit(db):
            db.execute("UPDATE worlds SET seed=?,created_at=? WHERE id=?", (seed, int(time.time()), self.world_id))
            db.execute("UPDATE pvp_rounds SET round_id=?,winner=? WHERE world_id=?", (round_id, self.encode(winner), self.world_id))
            db.execute("DELETE FROM pvp_cells WHERE world_id=?", (self.world_id,))
            db.execute("DELETE FROM excavations WHERE world_id=?", (self.world_id,))
            # Include offline users; retaining only connected states revives old
            # balances and equipment on the next account reconnect.
            db.execute("UPDATE player_states SET state=?,revision=revision+1,updated_at=? WHERE world_id=?",
                       (self.encode(stock_state()), int(time.time()), self.world_id))
            for player, state, revision in states:
                self.save_state(db, player, state, revision)
            db.execute("INSERT INTO pvp_runtime(world_id,state) VALUES(?,?) ON CONFLICT(world_id) DO UPDATE SET state=excluded.state",
                       (self.world_id, self.encode({"bags": [], "falling": [], "impacts": []})))
        try:
            await self.store.run(commit)
        except BaseException:
            # No further mutations may publish the uncommitted in-memory winner.
            self.failed = True
            raise
        self.seed, self.terrain, self.round_id, self.winner = seed, terrain, round_id, winner
        self.excavated.clear()
        self.overrides.clear()
        self.bags.clear()
        self.falling.clear()
        self.impacts.clear()
        self.dirty_players.clear()
        self.dirty_cells.clear()
        self.runtime_dirty = False
        self.pending_winner = None
        self.failed = False
        now = time.monotonic()
        for player, state, revision in states:
            player.state, player.revision = state, revision
            player.requests.clear()
            player.damage_times.clear()
            player.capture_context.clear()
            player.motion_seq = 0
            player.teleport_until = 0
            player.moved_at = player.contact_at = now
            player.movement_credit = 0.5
        # A single event is both the announcement and replacement snapshot.
        for player, _, _ in states:
            await self.send(player, {"type": "round_started", "player_id": player.player_id,
                                    "world_id": self.service.world_id, "seed": self.seed,
                                    "excavated": [], "state": player.state,
                                    "state_revision": player.revision, "winner": winner,
                                    "completed_state": completed_states[player.player_id],
                                    **self.join_details()})
        return True

    async def finish_if_winner(self, player):
        if self.recognize_winner(player):
            return await self.finish_round()
        return False


    def public(self, player):
        return {**player.public(), "state_revision": player.revision}

    def snapshot(self, changes=None):
        return {"round_id": self.round_id, "players": [self.public(p) for p in self.members.values()],
                "bags": [{**{k: b[k] for k in ("id", "x", "y", "amount")},
                          "cargo": b.get("cargo", {}), "items": b.get("items", {})} for b in self.bags],
                "falling": [{k: b[k] for k in ("id", "x", "y", "tile")} for b in self.falling],
                "impacts": [{k: impact[k] for k in ("id", "x", "y", "tile", "started_at", "expires_at")} for impact in self.impacts],
                "terrain_changes": changes if changes is not None else [[x, y, tile] for (x, y), tile in sorted(self.overrides.items())],
                "server_time": time.time()}

    def join_details(self):
        return {"mode": "pvp", **self.snapshot()}

    @staticmethod
    def in_world(player):
        return player.state.get("alive", True) and not player.state.get("building", "")

    def spawn_x(self, exclude=None):
        # Distinct surface pads make every respawn solid immediately, not after
        # a grace period that would allow players to tunnel through each other.
        for x in (5.5, 10.5, 14.5, 22.5, 30.5, 3.5, 25.5):
            if all(p is exclude or not self.in_world(p) or not overlaps(x, -3.5, p.state["x"], p.state["y"]) for p in self.members.values()):
                return x
        # At most five members exist; seven non-overlapping pads guarantee one.
        raise RuntimeError("No free PvP spawn pad")

    async def prepare_player(self, player):
        if self.failed:
            raise self.error("pvp_unavailable", "PvP simulation is unavailable. Co-op remains available.", 503)
        if not player.state:
            player.state = stock_state(self.spawn_x())
        elif not player.state.get("alive", True):
            player.state["building"] = ""
            if player.state.get("respawn_at", 0) <= time.time():
                self.respawn(player)
        else:
            player.state = {**stock_state(), **player.state}
            if player.state["building"] not in BUILDING_DOORS:
                player.state["building"] = ""
            if player.state["building"]:
                player.state.update(drill_x=0, drill_y=0, vx=0, vy=0, respawn_at=0)
            elif self.position_blocked(player, player.state["x"], player.state["y"]):
                player.state["x"], player.state["y"] = self.spawn_x(), -3.5
        player.contact_at = time.monotonic()
        player.moved_at = time.monotonic()
        player.movement_credit = 0.5
        self.dirty_players.add(player)
        await self.persist()

    def save_state(self, db, player, state, revision):
        if player.user_id is not None:
            db.execute("INSERT INTO player_states(world_id,user_id,state,revision,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(world_id,user_id) DO UPDATE SET state=excluded.state,revision=excluded.revision,updated_at=excluded.updated_at", (self.world_id, player.user_id, self.encode(state), revision, int(time.time())))

    async def persist(self):
        if self.failed:
            raise self.error("pvp_unavailable", "PvP simulation is unavailable. Co-op remains available.", 503)
        if not self.dirty_players and not self.dirty_cells and not self.runtime_dirty:
            return
        def commit(db):
            for player in self.dirty_players:
                self.save_state(db, player, player.state, player.revision)
            db.executemany("INSERT INTO pvp_cells(world_id,x,y,tile) VALUES(?,?,?,?) ON CONFLICT(world_id,x,y) DO UPDATE SET tile=excluded.tile", [(self.world_id, x, y, tile) for (x, y), tile in self.dirty_cells.items()])
            if self.runtime_dirty:
                db.execute("INSERT INTO pvp_runtime(world_id,state) VALUES(?,?) ON CONFLICT(world_id) DO UPDATE SET state=excluded.state", (self.world_id, self.encode({"bags": self.bags, "falling": self.falling, "impacts": self.impacts})))
        await self.store.run(commit)
        self.dirty_players.clear()
        self.dirty_cells.clear()
        self.runtime_dirty = False

    async def sync(self, player):
        await self.send(player, {"type": "state_sync", "state": player.state, "state_revision": player.revision})

    def changed(self, player):
        if player not in self.dirty_players:
            player.revision += 1
        self.dirty_players.add(player)

    def cell(self, x, y):
        if not 0 <= x < WIDTH or y >= HEIGHT:
            return -8
        if y < 0:
            return 0
        return self.terrain[x][y]

    @staticmethod
    def solid(tile):
        # Authored shops and blank core cells are traversable; every pavement
        # variant (-3/-4/-5) and all remaining non-air tiles are solid.
        return tile != 0 and tile >= -100

    def set_cell(self, x, y, tile):
        self.terrain[x][y] = tile
        self.overrides[x, y] = tile
        self.dirty_cells[x, y] = tile
        if tile == 0:
            self.excavated.add((x, y))
        else:
            self.excavated.discard((x, y))

    def motion_blocked(self, player, x, y):
        # The owner Godot body resolves terrain; only world edges and other
        # miners are authoritative movement obstacles here.
        if not POD_HALF_WIDTH <= x <= WIDTH - POD_HALF_WIDTH or y < -HEIGHT + POD_HALF_HEIGHT:
            return True
        for other in self.members.values():
            if other is not player and self.in_world(other) and overlaps(x, y, other.state["x"], other.state["y"]):
                return True
        return False

    def position_blocked(self, player, x, y):
        # Spawn and teleporter destinations still require clear terrain.
        if self.motion_blocked(player, x, y):
            return True
        for cx in range(math.floor(x - POD_HALF_WIDTH + 1e-6), math.floor(x + POD_HALF_WIDTH - 1e-6) + 1):
            for cy in range(math.floor(-y + 1 - POD_HALF_HEIGHT + 1e-6), math.floor(-y + 1 + POD_HALF_HEIGHT - 1e-6) + 1):
                if self.solid(self.cell(cx, cy)):
                    return True
        return False

    def move(self, player, x, y, now):
        ox, oy = player.state["x"], player.state["y"]
        elapsed = max(0.0, now - player.moved_at)
        player.moved_at = now
        player.movement_credit = min(3.0, getattr(player, "movement_credit", 0.5) + elapsed * 16)
        distance = math.hypot(x - ox, y - oy)
        if distance > 3 and now <= getattr(player, "teleport_until", 0) and y >= -4 and not self.position_blocked(player, x, y):
            player.teleport_until = 0
            return x, y
        if distance > player.movement_credit and distance:
            fraction = player.movement_credit / distance
            x, y = ox + (x - ox) * fraction, oy + (y - oy) * fraction
            distance = player.movement_credit
        player.movement_credit -= distance
        steps = max(1, math.ceil(max(abs(x - ox), abs(y - oy)) / 0.15))
        px, py = ox, oy
        blocked_x = blocked_y = False
        for index in range(1, steps + 1):
            nx, ny = ox + (x - ox) * index / steps, oy + (y - oy) * index / steps
            # Axis-separated swept resolution prevents tunnelling and permits sliding.
            if not blocked_x:
                blocked_x = self.motion_blocked(player, nx, py)
                if not blocked_x:
                    px = nx
            if not blocked_y:
                blocked_y = self.motion_blocked(player, px, ny)
                if not blocked_y:
                    py = ny
        return px, py

    def economy(self, old, state):
        """Validate existing client shop/sale snapshots without a second shop API."""
        at_surface = bool(old.get("building")) or state["y"] >= -5
        expense = 0
        for category, names in UPGRADE_PRICES.items():
            selected = state["current_upgrades"].get(category)
            if selected not in names:
                return False, 0
            if selected != old["current_upgrades"].get(category):
                if not at_surface:
                    return False, 0
                expense += names[selected]
        for item, price in ITEM_PRICES.items():
            bought = state["player_items"].get(item, 0) - old["player_items"].get(item, 0)
            if bought > 0:
                if not at_surface:
                    return False, 0
                expense += bought * price
        proceeds = 0
        for mineral, value in ORE_VALUES.items():
            sold = old["player_cargo"].get(mineral, 0) - state["player_cargo"].get(mineral, 0)
            if sold < 0 or (sold and not at_surface):
                return False, 0
            proceeds += sold * value
        available = old["player_money"] + proceeds - expense
        return 0 <= state["player_money"] <= available, max(0, available - state["player_money"])

    async def update_state(self, player, message):
        incoming = message.get("state")
        if not isinstance(incoming, dict):
            raise self.error("invalid_state", "Invalid player state.")
        base = {key: value for key, value in incoming.items() if key not in EXTRA_STATE_KEYS | SERVER_STATE_KEYS}
        self.service.validate_state(base, open_sky=True)
        for key in EXTRA_STATE_KEYS & incoming.keys():
            value = incoming[key]
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e15:
                raise self.error("invalid_state", "Invalid PvP motion state.")
        motion_seq = message.get("motion_seq")
        if type(motion_seq) is not int or motion_seq <= 0:
            raise self.error("invalid_state", "A positive integer motion_seq is required.")
        if motion_seq <= getattr(player, "motion_seq", 0):
            await self.sync(player)
            return
        player.motion_seq = motion_seq
        if message.get("state_revision") != player.revision:
            await self.sync(player)
            return
        old = player.state
        if not old["alive"]:
            await self.sync(player)
            return
        state = {**copy.deepcopy(old), **base}
        requested_position = [state["x"], state["y"]]
        if old.get("building"):
            state["x"], state["y"], state["facing"] = old["x"], old["y"], old["facing"]
            # The local pod is frozen inside. Stale fuel-burn snapshots cannot
            # consume fuel, but ordinary paid refueling/upgrades still reconcile.
            state["player_fuel"] = max(old["player_fuel"], state["player_fuel"])
        valid_economy, repair_payment = self.economy(old, state)
        if not valid_economy:
            await self.sync(player)
            return
        for item in ("Quantum Teleporter", "Matter Transmitter"):
            if not old.get("building") and old["player_items"].get(item, 0) - state["player_items"].get(item, 0) == 1:
                player.teleport_until = time.monotonic() + 5
        if not old.get("building"):
            state["x"], state["y"] = self.move(player, state["x"], state["y"], time.monotonic())
        state["deepest_y"] = min(old.get("deepest_y", old["y"]), state["y"])
        state["alive"], state["respawn_at"] = True, 0
        state["player_hp"] = old["player_hp"]
        # Repairs must pay $15/HP on the surface; nanobots consume a real item.
        # Buying a validated new hull includes its normal full-health refill.
        requested_hp = base.get("player_hp", old["player_hp"])
        healing = max(0, requested_hp - old["player_hp"])
        new_hull = state["current_upgrades"]["Hull"] != old["current_upgrades"]["Hull"]
        bots_used = old["player_items"].get("Hull Repair Nanobots", 0) - state["player_items"].get("Hull Repair Nanobots", 0)
        allowed_healing = (30 if bots_used == 1 else 0) + (math.ceil(repair_payment / 15) if old.get("building") or state["y"] >= -5 else 0)
        if new_hull or (healing and healing <= allowed_healing + 1e-8):
            maximum = HULL_HP[state["current_upgrades"]["Hull"]]
            state["player_hp"] = maximum if new_hull else min(maximum, requested_hp)
        dx, dy = incoming.get("drill_x", 0), incoming.get("drill_y", 0)
        if dy < -0.5:
            state["drill_x"], state["drill_y"] = 0, -1
        elif abs(dx) > 0.5 and (dx > 0) == state["facing"]:
            state["drill_x"], state["drill_y"] = (1 if dx > 0 else -1), 0
        else:
            state["drill_x"], state["drill_y"] = 0, 0
        for key in ("vx", "vy"):
            state[key] = max(-30.0, min(30.0, incoming.get(key, 0)))
        if old.get("building"):
            state.update(drill_x=0, drill_y=0, vx=0, vy=0)
        player.state = state
        player.contact_at = time.monotonic()
        player.state_updates += 1
        self.dirty_players.add(player)
        if await self.finish_if_winner(player):
            return
        await self.persist()
        await self.send(player, {"type": "state_ack", "state": state, "state_revision": player.revision,
                                 "motion_seq": motion_seq, "requested_position": requested_position})
        await self.broadcast({"type": "state", "player_id": player.player_id, "state": state, "state_revision": player.revision}, exclude=player)

    async def transfer(self, player, message):
        if not player.state.get("alive", True):
            await self.send(player, {"type": "transfer_result", "accepted": False, "message": "Respawn before transferring money."})
            return
        recipient = self.members.get(message.get("recipient_id")) if isinstance(message.get("recipient_id"), str) else None
        if recipient and not recipient.state.get("alive", True):
            await self.send(player, {"type": "transfer_result", "accepted": False, "message": "That player is waiting to respawn."})
            return
        recipient_id, amount = message.get("recipient_id"), message.get("amount")
        reason = ""
        if type(amount) is not int or amount <= 0:
            reason = "Enter a positive whole-dollar amount."
        elif recipient is player:
            reason = "Choose another player to receive the money."
        elif recipient is None or recipient.socket.closed:
            reason = "That player is no longer connected to this world."
        elif amount > player.state["player_money"]:
            reason = "You do not have enough money for this transfer."
        elif recipient.state["player_money"] + amount > MAX_CASH:
            reason = "That transfer would exceed the recipient's balance limit."
        if reason:
            await self.send(player, {"type": "transfer_result", "accepted": False, "message": reason})
            return
        player.state["player_money"] -= amount
        recipient.state["player_money"] += amount
        self.changed(player)
        self.changed(recipient)
        if await self.finish_if_winner(recipient):
            return
        await self.persist()
        await self.send(player, {"type": "transfer_result", "accepted": True,
                                "message": f"Sent ${amount:,} to {recipient.name}.",
                                "state": player.state, "state_revision": player.revision})
        await self.sync(recipient)
        await self.broadcast({"type": "pvp_tick", **self.snapshot([])})

    def damage(self, player, amount, now):
        if not self.in_world(player) or amount <= 0:
            return
        player.state["player_hp"] = max(0.0, player.state["player_hp"] - amount)
        self.changed(player)
        if player.state["player_hp"] <= 1e-8:
            player.state.update(player_hp=0, alive=False, respawn_at=now + RESPAWN_SECONDS, drill_x=0, drill_y=0, vx=0, vy=0, building="")
            cash = player.state.get("player_money", 0)
            cargo = inventory(player.state.get("player_cargo"), WEIGHTS)
            items = inventory(player.state.get("player_items"), ITEM_NAMES)
            if cash > 0 or any(cargo.values()) or any(items.values()):
                self.bags.append({"id": secrets.token_hex(8), "x": player.state["x"], "y": player.state["y"],
                                  "amount": cash, "cargo": cargo, "items": items, "vy": 0.0})
                self.runtime_dirty = True
            player.state["player_money"] = 0
            player.state["player_cargo"] = dict.fromkeys(WEIGHTS, 0)
            player.state["player_items"] = dict.fromkeys(ITEM_NAMES, 0)

    def respawn(self, player):
        previous = player.state
        player.state = stock_state(self.spawn_x(exclude=player))
        for key in ("player_items", "player_cargo", "transmissions"):
            player.state[key] = copy.deepcopy(previous[key])
        player.state["deepest_y"] = previous.get("deepest_y", previous["y"])
        player.state["claimed_transmissions"] = list(previous.get("claimed_transmissions", []))
        # Death forfeits the complete cash balance, not just the amount above the
        # initial $20. Respawn does not manufacture a new cash grant every ten seconds.
        player.state["player_money"] = 0
        player.moved_at = time.monotonic()
        player.contact_at = time.monotonic()
        player.movement_credit = 0.5
        player.teleport_until = 0
        self.changed(player)

    def remember(self, player, request_id):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 64:
            raise self.error("invalid_request", "A unique request_id of 1-64 characters is required.")
        if request_id in player.requests:
            return False
        player.requests[request_id] = None
        if len(player.requests) > 512:
            player.requests.popitem(last=False)
        return True

    def building_exit(self, player, building):
        door_x, _ = BUILDING_DOORS[building]
        # Prefer the authored ground-standing height and the nearest clear pad.
        # A bounded search never ejects a shopper across the map or into terrain.
        for y in (-3.5, -3.25, -3.0):
            for offset in (0, 0.85, -0.85, 1.7, -1.7, 2.55, -2.55):
                x = door_x + offset
                if not self.position_blocked(player, x, y):
                    return x, y
        return None

    async def building(self, player, message):
        requested, enter = message.get("building"), message.get("enter")
        if not isinstance(requested, str) or type(enter) is not bool:
            raise self.error("invalid_building", "A building script name and boolean enter are required.")
        fresh = self.remember(player, message.get("request_id"))
        current = player.state.get("building", "")
        accepted, reason = False, ""
        if requested not in BUILDING_DOORS:
            reason = "That panel is not a shop building."
        elif not player.state.get("alive", True):
            reason = "Respawn before entering a shop."
        elif (enter and current == requested) or (not enter and not current):
            accepted = True
        elif not fresh:
            reason = "That building request has already been handled."
        elif enter:
            door_x, door_y = BUILDING_DOORS[requested]
            if current:
                reason = "Exit the current building first."
            elif math.hypot(player.state["x"] - door_x, player.state["y"] - door_y) > BUILDING_ENTRY_RADIUS:
                reason = "Move closer to this shop's entrance."
            else:
                player.state.update(building=requested, drill_x=0, drill_y=0, vx=0, vy=0)
                player.teleport_until = 0
                self.changed(player)
                accepted = True
        elif current != requested:
            reason = "This is not the building you entered."
        else:
            destination = self.building_exit(player, requested)
            if destination is None:
                reason = "The shop exit is blocked. Wait for a clear space."
            else:
                player.state.update(building="", x=destination[0], y=destination[1], drill_x=0, drill_y=0, vx=0, vy=0)
                player.moved_at = player.contact_at = time.monotonic()
                player.movement_credit = 0.5
                player.teleport_until = 0
                self.changed(player)
                accepted = True
        # The websocket dispatcher holds world_lock across the save and all
        # replies, so reconnects and purchases observe the same canonical state.
        await self.persist()
        await self.sync(player)
        await self.send(player, {"type": "building_result", "accepted": accepted, "building": requested,
                                 "enter": enter, "request_id": message["request_id"], "message": reason,
                                 "state": player.state, "state_revision": player.revision})
        await self.broadcast({"type": "pvp_tick", **self.snapshot([])})

    async def action(self, player, message):
        if not self.in_world(player):
            await self.sync(player)
            if message["type"] == "blast":
                await self.send(player, {"type": "blast_result", "accepted": False, "request_id": message.get("request_id")})
            return
        now = time.time()
        if message["type"] == "damage":
            source, amount = message.get("source"), message.get("amount")
            if source not in ("crash", "fuel") or (source == "crash" and (type(amount) not in (int, float) or not math.isfinite(amount) or not 0 < amount <= 1e15)):
                raise self.error("invalid_damage", "Invalid environmental damage.")
            if source == "fuel":
                amount = player.state["player_hp"]
            if now - player.damage_times.get(source, 0) >= 1:
                player.damage_times[source] = now
                self.damage(player, amount, now)
        elif message["type"] == "claim_transmission":
            index = message.get("index")
            if type(index) is not int or index not in TRANSMISSION_BONUSES:
                raise self.error("invalid_transmission", "Invalid transmission reward.")
            depth, bonus = TRANSMISSION_BONUSES[index]
            claimed = player.state.get("claimed_transmissions", [])
            if player.state.get("deepest_y", player.state["y"]) <= depth and index not in claimed and player.state["player_money"] + bonus <= 1e15:
                player.state["player_money"] += bonus
                player.state["claimed_transmissions"] = [*claimed, index]
                self.changed(player)
                if await self.finish_if_winner(player):
                    return
        else:
            item = message.get("item")
            if item not in BLAST_RADIUS:
                raise self.error("invalid_blast", "Choose Dynamite or Plastic Explosives.")
            if not self.remember(player, message.get("request_id")):
                await self.sync(player)
                return
            if player.state["player_items"].get(item, 0) <= 0 or now - player.damage_times.get("blast", 0) < 0.5:
                await self.send(player, {"type": "blast_result", "accepted": False, "request_id": message["request_id"]})
                await self.sync(player)
                return
            player.damage_times["blast"] = now
            player.state["player_items"][item] -= 1
            self.changed(player)
            radius = BLAST_RADIUS[item]
            px, py = player.state["x"], player.state["y"]
            for victim in self.members.values():
                if victim is not player and self.in_world(victim) and overlaps(px, py, victim.state["x"], victim.state["y"], BLAST_HALF_SIZE[item] + POD_HALF_WIDTH, BLAST_HALF_SIZE[item] + POD_HALF_HEIGHT):
                    self.damage(victim, self.damage_values[item], now)
            cx, cy = math.floor(px), math.floor(1 - py)
            for x in range(max(0, cx - radius), min(WIDTH, cx + radius + 1)):
                for y in range(max(0, cy - radius), min(HEIGHT, cy + radius + 1)):
                    if tile_name(self.cell(x, y)):
                        self.set_cell(x, y, 0)
            self.detach_hazards()
            await self.send(player, {"type": "blast_result", "accepted": True, "request_id": message["request_id"], "item": item, "x": px, "y": py})
        changes = [[x, y, tile] for (x, y), tile in sorted(self.dirty_cells.items())]
        changed_players = list(self.dirty_players)
        await self.persist()
        for changed in changed_players:
            await self.sync(changed)
        await self.broadcast({"type": "pvp_tick", **self.snapshot(changes)})

    async def mine(self, player, message):
        request_id = message.get("request_id")
        if not self.remember(player, request_id):
            player.mine_duplicates += 1
            await self.sync(player)
            return
        x, y = message.get("x"), message.get("y")
        if type(x) not in (int, float) or type(y) not in (int, float) or not math.isfinite(x) or not math.isfinite(y) or x != int(x) or y != int(y) or not 0 <= x < WIDTH or not 0 <= y < HEIGHT:
            raise self.error("invalid_mine", "Mining coordinates are invalid.")
        x, y = int(x), int(y)
        name = tile_name(self.cell(x, y))
        # Blast cells are never accepted separately: a blast must consume its item
        # and resolve victims/terrain in one authoritative action.
        accepted = self.in_world(player) and message.get("method", "drill") == "drill" and bool(name) and name != "Rock" and math.hypot(x + 0.5 - player.state["x"], -y + 0.5 - player.state["y"]) <= 1.8
        event = {"type": "mined", "request_id": request_id, "player_id": player.player_id, "x": x, "y": y, "method": "drill", "accepted": bool(accepted), "ore": name if accepted else ""}
        if accepted:
            self.set_cell(x, y, 0)
            player.state = award(copy.deepcopy(player.state), name)
            self.changed(player)
            if name == "Lava":
                self.damage(player, self.damage_values["Lava"], time.time())
            self.detach_hazards()
            event.update(state=player.state, state_revision=player.revision)
            if await self.finish_if_winner(player):
                return
            changes = [[cx, cy, tile] for (cx, cy), tile in sorted(self.dirty_cells.items())]
            await self.persist()
            player.mine_accepted += 1
            await self.broadcast(event)
            await self.broadcast({"type": "pvp_tick", **self.snapshot(changes)})
        else:
            player.mine_rejected += 1
            await self.send(player, event)

    def detach_hazards(self):
        # Resolve unsupported columns bottom-up, leaving supported hazards static.
        for x, y in sorted(unsupported_hazards(self.terrain), key=lambda cell: (cell[0], -cell[1])):
            if self.solid(self.cell(x, y + 1)):
                continue
            self.falling.append({"id": secrets.token_hex(8), "x": x + 0.5, "y": -y + 0.5, "tile": self.cell(x, y), "vy": 0.0, "hit": []})
            self.set_cell(x, y, 0)
            self.runtime_dirty = True

    def gravity(self, body, dt, half_height, resolve_embedded=False):
        old_y = body["y"]
        velocity = body["vy"] - GRAVITY * dt
        new_y = old_y + velocity * dt
        x = min(WIDTH - 1, max(0, math.floor(body["x"])))
        old_bottom, new_bottom = -old_y + 1 + half_height, -new_y + 1 + half_height
        # A death during drilling can spawn a bag inside an intact tile. Resolve
        # its intersected tile first, rather than skipping that support forever.
        first_row = -old_y + 1 - half_height + 1e-7 if resolve_embedded else old_bottom - 1e-7
        for row in range(max(0, math.floor(first_row)), min(HEIGHT, math.floor(new_bottom) + 1)):
            if self.solid(self.cell(x, row)) and (resolve_embedded or row >= old_bottom - 1e-6):
                body["y"], body["vy"] = 1 - row + half_height, 0.0
                return True
        if new_bottom >= HEIGHT:
            body["y"], body["vy"] = 1 - HEIGHT + half_height, 0.0
            return True
        body["y"], body["vy"] = new_y, velocity
        return False

    def bag_reaches_player(self, bag, old_y, player):
        if not self.in_world(player):
            return False
        px, py = player.state["x"], player.state["y"]
        # Vertical swept AABB: collect against the whole hull, not a circle
        # around its center. A small gap permits hovering above the visible bag.
        by = max(bag["y"], min(max(old_y, bag["y"]), py))
        if (abs(bag["x"] - px) > BAG_HALF_SIZE + POD_HALF_WIDTH + BAG_PICKUP_MARGIN + 1e-8
                or abs(by - py) > BAG_HALF_SIZE + POD_HALF_HEIGHT + BAG_PICKUP_MARGIN + 1e-8):
            return False
        # Reject a pickup across solid terrain, including an owner still
        # intersecting its mining target. Clip the short center-to-center segment
        # against each crossed tile's interior; touching a tile edge is harmless.
        ax, ay = bag["x"], 1 - by
        dx, dy = px - ax, by - py
        for x in range(math.floor(min(ax, px)), math.floor(max(ax, px)) + 1):
            for row in range(math.floor(min(ay, 1 - py)), math.floor(max(ay, 1 - py)) + 1):
                if not self.solid(self.cell(x, row)):
                    continue
                enter, leave = 0.0, 1.0
                for start, delta, low, high in ((ax, dx, x, x + 1), (ay, dy, row, row + 1)):
                    low, high = low + 1e-8, high - 1e-8
                    if abs(delta) < 1e-8:
                        if not low <= start <= high:
                            break
                    else:
                        first, last = sorted(((low - start) / delta, (high - start) / delta))
                        enter, leave = max(enter, first), min(leave, last)
                        if enter > leave:
                            break
                else:
                    return False
        return True

    def collect_bag(self, player, bag):
        """Cash/items ignore the bay; each randomly drawn mineral unit must fit."""
        changed = False
        cash = bag["amount"]
        if cash and player.state["player_money"] + cash <= MAX_CASH:
            player.state["player_money"] += cash
            bag["amount"] = 0
            changed = True
        bag["items"] = inventory(bag.get("items"), ITEM_NAMES)
        bag["cargo"] = inventory(bag.get("cargo"), WEIGHTS)
        for name, count in bag["items"].items():
            held = int(player.state["player_items"].get(name, 0))
            taken = min(count, MAX_COUNTER - held)
            if taken > 0:
                player.state["player_items"][name] = held + taken
                bag["items"][name] -= taken
                changed = True
        cargo = player.state["player_cargo"]
        free = CARGO_CAPACITY.get(player.state["current_upgrades"].get("Cargo"), 7) - sum(
            cargo.get(name, 0) * weight for name, weight in WEIGHTS.items())
        # Capacity is at most 120; even billion-unit historical stacks cannot
        # turn a pickup into unbounded work. Choose uniformly among fitting units.
        while free > 0:
            fitting = [(name, count) for name, count in bag["cargo"].items()
                       if count and WEIGHTS[name] <= free and cargo.get(name, 0) < MAX_COUNTER]
            total = sum(count for _, count in fitting)
            if not total:
                break
            draw = secrets.randbelow(total)
            for name, count in fitting:
                if draw < count:
                    cargo[name] = int(cargo.get(name, 0)) + 1
                    bag["cargo"][name] -= 1
                    free -= WEIGHTS[name]
                    changed = True
                    break
                draw -= count
        if changed:
            self.changed(player)
            self.runtime_dirty = True
        empty = not bag["amount"] and not any(bag["items"].values()) and not any(bag["cargo"].values())
        if empty:
            self.bags.remove(bag)
            self.runtime_dirty = True
        return changed

    def step(self, dt, now, monotonic_now):
        if self.pending_winner:
            return
        active_impacts = [impact for impact in self.impacts if impact["expires_at"] > now]
        if len(active_impacts) != len(self.impacts):
            self.impacts = active_impacts
            self.runtime_dirty = True
        for player in list(self.members.values()):
            if not player.state.get("alive", True) and now >= player.state.get("respawn_at", math.inf):
                self.respawn(player)
        hits = []
        for attacker in self.members.values():
            state = attacker.state
            if not self.in_world(attacker) or monotonic_now - attacker.contact_at > 0.35:
                continue
            dx, dy = state.get("drill_x", 0), state.get("drill_y", 0)
            if not dx and not dy:
                continue
            if dx and (dx > 0) != state["facing"]:
                continue
            for victim in self.members.values():
                if victim is attacker or not self.in_world(victim):
                    continue
                vx, vy = victim.state["x"] - state["x"], victim.state["y"] - state["y"]
                forward, lateral = vx * dx + vy * dy, abs(vx * dy - vy * dx)
                if 0.6 <= forward <= 1.15 and lateral <= 0.55:
                    hits.append((victim, self.damage_values["drill"] * dt))
        # Collect first, apply second: simultaneous lethal drills do not depend on
        # dictionary insertion order or let a dead attacker act an extra tick.
        for victim, amount in hits:
            self.damage(victim, amount, now)
        for body in list(self.falling):
            old_y = body["y"]
            collided = self.gravity(body, dt, 0.5)
            if abs(body["y"] - old_y) > 1e-8:
                for player in self.members.values():
                    if player.player_id not in body["hit"] and self.in_world(player) and segment_near(body["x"], old_y, body["x"], body["y"], player.state["x"], player.state["y"], 0.85):
                        body["hit"].append(player.player_id)
                        self.damage(player, self.damage_values[tile_name(body["tile"])], now)
            self.runtime_dirty = True
            if collided:
                self.impacts.append({**{key: body[key] for key in ("id", "x", "y", "tile")}, "started_at": now, "expires_at": now + IMPACT_SECONDS})
                self.falling.remove(body)
        for bag in list(self.bags):
            old_y, old_vy = bag["y"], bag["vy"]
            self.gravity(bag, dt, BAG_HALF_SIZE, resolve_embedded=True)
            for player in sorted(self.members.values(), key=lambda p: p.player_id):
                if self.bag_reaches_player(bag, old_y, player):
                    collected = self.collect_bag(player, bag)
                    if collected and self.recognize_winner(player):
                        # Stop before another bag or recipient can win/overtake.
                        return
                    if bag not in self.bags:
                        break
            if bag not in self.bags or abs(old_y - bag["y"]) > 1e-8 or old_vy != bag["vy"]:
                self.runtime_dirty = True
