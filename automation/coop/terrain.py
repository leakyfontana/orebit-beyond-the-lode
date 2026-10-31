"""Authoritative port of Godot WorldData.generate and legacy System.Random.

Keep random draws in the same order as godot/scripts/world_data.gd; rotations
consume draws even though the service only needs tile types.
"""

WIDTH, HEIGHT = 36, 600
MINERALS = (
    "Ironium", "Bronzium", "Silverium", "Goldium", "Platinium", "Einsteinium",
    "Emerald", "Ruby", "Diamond", "Amazonite", "Dinosaur Bones", "Treasure",
    "Martian Skeleton", "Religious Artifact", "Mr. Natas' Kevlar Suit",
    "Mr. Natas' Staff of Hell", "Mr. Natas' Laser Monacle", "Satan's Hooves",
    "Satan's Horns", "Satan's Evil Eye (right)", "Satan's Evil Eye (left)",
    "Satan's Boiler of Eternal Infernos", "Martian Reward for Restoring Peace",
    "250,000 Shares of Natas HI Inc.",
)
WEIGHTS = dict(zip(MINERALS[:10], (1, 1, 1, 2, 3, 4, 6, 8, 10, 12)))
TREASURE_VALUES = dict(zip(MINERALS[10:], (
    5000, 12500, 20000, 50000, 50000, 100000, 200000, 300000, 400000,
    500000, 500000, 600000, 1000000, 25000000,
)))
CARGO_CAPACITY = {
    "Micro Bay": 7, "Medium Bay": 15, "Huge Bay": 25,
    "Gigantic Bay": 40, "Titanic Bay": 70, "Leviathan Bay": 120,
}


def signed32(value: int) -> int:
    return ((value + 2147483648) & 0xFFFFFFFF) - 2147483648


class DotNetRandom:
    BIG = 2147483647

    def __init__(self, seed: int):
        seed = signed32(seed)
        subtraction = self.BIG if seed == -2147483648 else abs(seed)
        mj = 161803398 - subtraction
        self.values = [0] * 56
        self.values[55] = mj
        mk = 1
        for i in range(1, 55):
            ii = (21 * i) % 55
            self.values[ii] = mk
            mk = signed32(mj - mk)
            if mk < 0:
                mk += self.BIG
            mj = self.values[ii]
        for _ in range(4):
            for i in range(1, 56):
                self.values[i] = signed32(self.values[i] - self.values[1 + ((i + 30) % 55)])
                if self.values[i] < 0:
                    self.values[i] += self.BIG
        self.index, self.other = 0, 21

    def next(self, maximum: int) -> int:
        self.index = self.index + 1 if self.index < 55 else 1
        self.other = self.other + 1 if self.other < 55 else 1
        value = self.values[self.index] - self.values[self.other]
        if value == self.BIG:
            value -= 1
        if value < 0:
            value += self.BIG
        self.values[self.index] = value
        return int((float(value) * (1.0 / float(self.BIG))) * maximum)


def generate(seed: int) -> list[list[int]]:
    random = DotNetRandom(seed)
    cells = [[0] * HEIGHT for _ in range(WIDTH)]
    for x in range(WIDTH):
        for y in range(HEIGHT):
            random.next(4)  # Rotation, including overwritten surface cells.
            if y < 5:
                tile = 0
            elif y == 5:
                tile = random.next(2) - 2
            elif y == HEIGHT - 12:
                tile = random.next(2) - 7
            elif HEIGHT - 11 <= y < HEIGHT - 5:
                tile = -999
            elif y == HEIGHT - 5:
                tile = -(9 + random.next(4))
            elif y > HEIGHT - 5:
                tile = -8
            else:
                mineral_range = int(float(y) / 65.0) + 2
                if random.next(5) == 0:
                    if random.next(5) == 0:
                        if random.next(5) == 0:
                            if random.next(4) == 0 and y > 80:
                                tile = random.next(4) + 16
                            else:
                                tile = min(random.next(mineral_range) + 8, 15)
                        else:
                            tile = min(random.next(mineral_range) + 7, 15)
                    else:
                        tile = min(random.next(mineral_range) + 6, 15)
                else:
                    tile = random.next(5) + 1
                    if float(y) * 1.5 > int(float(HEIGHT) / 3.0):
                        hazard_range = int((float(HEIGHT - y) / float(HEIGHT)) * 15.0)
                        if random.next(hazard_range) == 0:
                            if float(y) / 2.0 * 1.5 > float(HEIGHT) / 3.0 and random.next(2) == 0:
                                if float(y) / 3.0 * 1.5 > float(HEIGHT) / 3.0 and random.next(2) == 0:
                                    tile = 31
                                else:
                                    tile = 28 + random.next(3)
                            else:
                                tile = 25 + random.next(3)
                if random.next(4) == 0:
                    tile = 0
            cells[x][y] = tile
    cells[WIDTH - 3][HEIGHT - 12] = 0
    cells[WIDTH - 4][HEIGHT - 12] = 0
    # Buildings are traversable, pavement invincible; none can be excavated.
    for x in (2, 3, 4, 5, 9, 10, 11, 12, 13, 14, 21, 22, 23, 24, 25, 26, 30, 31, 32, 33):
        cells[x][5] = -3
    return cells


def tile_name(tile: int) -> str:
    if 1 <= tile <= 5:
        return "Dirt"
    if tile in (-1, -2):
        return "Grass"
    if 6 <= tile <= 29 and tile - 6 < len(MINERALS) and tile < 25:
        return MINERALS[tile - 6]
    if 25 <= tile <= 27:
        return "Rock"
    if 28 <= tile <= 30:
        return "Lava"
    if tile == 31:
        return "Gas"
    return ""


def award(state: dict, ore: str) -> dict:
    # Caller supplies a detached state, committed with the excavation transaction.
    if ore in WEIGHTS:
        cargo = state.setdefault("player_cargo", {name: 0 for name in WEIGHTS})
        weight = sum(cargo.get(name, 0) * amount for name, amount in WEIGHTS.items())
        capacity = CARGO_CAPACITY.get(state.get("current_upgrades", {}).get("Cargo", "Micro Bay"), 7)
        if weight + WEIGHTS[ore] <= capacity:
            cargo[ore] = cargo.get(ore, 0) + 1
    elif ore in TREASURE_VALUES:
        state["player_money"] = state.get("player_money", 20) + TREASURE_VALUES[ore]
    return state
