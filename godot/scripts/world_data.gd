class_name WorldData
extends RefCounted

# Map coordinates are [x][y], with y increasing downwards. A Unity tile center
# is (x + .5, -y + .5). Rotation indices map to Unity degrees 90 * (rotation - 2).
# The renderer must negate those degrees when converting to Godot y-down.
var data: GameData
var blockChangedTexture: bool = false
var generation_seed: int = 0
# A halfway-dug node stays solid and retains its original ore/name until digBlock,
# even though my_map already reads empty. Keep that visual/collision state apart.
var halfway_blocks: Dictionary = {}
const NEIGHBOURS: Array[Vector2i] = [Vector2i(0, 1), Vector2i(1, 0), Vector2i(0, -1), Vector2i(-1, 0), Vector2i(1, 1), Vector2i(-1, 1), Vector2i(1, -1), Vector2i(-1, -1)]
const TunnelTiles: Dictionary = {
	"00000000": "0",
	"00000001": "1",
	"00000010": "16",
	"00000011": "16",
	"00000100": "2",
	"00000101": "5",
	"00000110": "16",
	"00000111": "16",
	"00001000": "17",
	"00001001": "17",
	"00001010": "28",
	"00001011": "28",
	"00001100": "20",
	"00001101": "20",
	"00001110": "28",
	"00001111": "28",
	"00010000": "19",
	"00010001": "27",
	"00010010": "29",
	"00010011": "29",
	"00010100": "19",
	"00010101": "27",
	"00010110": "29",
	"00010111": "29",
	"00011000": "40",
	"00011001": "40",
	"00011010": "42",
	"00011011": "42",
	"00011100": "40",
	"00011101": "40",
	"00011110": "42",
	"00011111": "42",
	"00100000": "4",
	"00100001": "6",
	"00100010": "26",
	"00100011": "26",
	"00100100": "9",
	"00100101": "13",
	"00100110": "26",
	"00100111": "26",
	"00101000": "17",
	"00101001": "17",
	"00101010": "28",
	"00101011": "28",
	"00101100": "20",
	"00101101": "20",
	"00101110": "28",
	"00101111": "28",
	"00110000": "22",
	"00110001": "35",
	"00110010": "37",
	"00110011": "37",
	"00110100": "22",
	"00110101": "35",
	"00110110": "37",
	"00110111": "37",
	"00111000": "40",
	"00111001": "40",
	"00111010": "42",
	"00111011": "42",
	"00111100": "40",
	"00111101": "40",
	"00111110": "42",
	"00111111": "42",
	"01000000": "18",
	"01000001": "23",
	"01000010": "41",
	"01000011": "41",
	"01000100": "24",
	"01000101": "34",
	"01000110": "41",
	"01000111": "41",
	"01001000": "31",
	"01001001": "31",
	"01001010": "43",
	"01001011": "43",
	"01001100": "38",
	"01001101": "38",
	"01001110": "43",
	"01001111": "43",
	"01010000": "30",
	"01010001": "39",
	"01010010": "44",
	"01010011": "44",
	"01010100": "30",
	"01010101": "39",
	"01010110": "44",
	"01010111": "44",
	"01011000": "45",
	"01011001": "45",
	"01011010": "46",
	"01011011": "46",
	"01011100": "45",
	"01011101": "45",
	"01011110": "46",
	"01011111": "46",
	"01100000": "18",
	"01100001": "23",
	"01100010": "41",
	"01100011": "41",
	"01100100": "24",
	"01100101": "34",
	"01100110": "41",
	"01100111": "41",
	"01101000": "31",
	"01101001": "31",
	"01101010": "43",
	"01101011": "43",
	"01101100": "38",
	"01101101": "38",
	"01101110": "43",
	"01101111": "43",
	"01110000": "30",
	"01110001": "39",
	"01110010": "44",
	"01110011": "44",
	"01110100": "30",
	"01110101": "39",
	"01110110": "44",
	"01110111": "44",
	"01111000": "45",
	"01111001": "45",
	"01111010": "46",
	"01111011": "46",
	"01111100": "45",
	"01111101": "45",
	"01111110": "46",
	"01111111": "46",
	"10000000": "3",
	"10000001": "10",
	"10000010": "21",
	"10000011": "21",
	"10000100": "8",
	"10000101": "12",
	"10000110": "21",
	"10000111": "21",
	"10001000": "25",
	"10001001": "25",
	"10001010": "36",
	"10001011": "36",
	"10001100": "33",
	"10001101": "33",
	"10001110": "36",
	"10001111": "36",
	"10010000": "19",
	"10010001": "27",
	"10010010": "29",
	"10010011": "29",
	"10010100": "19",
	"10010101": "27",
	"10010110": "29",
	"10010111": "29",
	"10011000": "40",
	"10011001": "40",
	"10011010": "42",
	"10011011": "42",
	"10011100": "40",
	"10011101": "40",
	"10011110": "42",
	"10011111": "42",
	"10100000": "7",
	"10100001": "14",
	"10100010": "32",
	"10100011": "32",
	"10100100": "11",
	"10100101": "15",
	"10100110": "32",
	"10100111": "32",
	"10101000": "25",
	"10101001": "25",
	"10101010": "36",
	"10101011": "36",
	"10101100": "33",
	"10101101": "33",
	"10101110": "36",
	"10101111": "36",
	"10110000": "22",
	"10110001": "35",
	"10110010": "37",
	"10110011": "37",
	"10110100": "22",
	"10110101": "35",
	"10110110": "37",
	"10110111": "37",
	"10111000": "40",
	"10111001": "40",
	"10111010": "42",
	"10111011": "42",
	"10111100": "40",
	"10111101": "40",
	"10111110": "42",
	"10111111": "42",
	"11000000": "18",
	"11000001": "23",
	"11000010": "41",
	"11000011": "41",
	"11000100": "24",
	"11000101": "34",
	"11000110": "41",
	"11000111": "41",
	"11001000": "31",
	"11001001": "31",
	"11001010": "43",
	"11001011": "43",
	"11001100": "38",
	"11001101": "38",
	"11001110": "43",
	"11001111": "43",
	"11010000": "30",
	"11010001": "39",
	"11010010": "44",
	"11010011": "44",
	"11010100": "30",
	"11010101": "39",
	"11010110": "44",
	"11010111": "44",
	"11011000": "45",
	"11011001": "45",
	"11011010": "46",
	"11011011": "46",
	"11011100": "45",
	"11011101": "45",
	"11011110": "46",
	"11011111": "46",
	"11100000": "18",
	"11100001": "23",
	"11100010": "41",
	"11100011": "41",
	"11100100": "24",
	"11100101": "34",
	"11100110": "41",
	"11100111": "41",
	"11101000": "31",
	"11101001": "31",
	"11101010": "43",
	"11101011": "43",
	"11101100": "38",
	"11101101": "38",
	"11101110": "43",
	"11101111": "43",
	"11110000": "30",
	"11110001": "39",
	"11110010": "44",
	"11110011": "44",
	"11110100": "30",
	"11110101": "39",
	"11110110": "44",
	"11110111": "44",
	"11111000": "45",
	"11111001": "45",
	"11111010": "46",
	"11111011": "46",
	"11111100": "45",
	"11111101": "45",
	"11111110": "46",
	"11111111": "46"
}
# TilesLoader values deliberately differ from LevelData for the first three treasures.
const minerals_list: Array = [
	{
		"name": "Ironium",
		"ore_value": 30,
		"weight": 1
	},
	{
		"name": "Bronzium",
		"ore_value": 60,
		"weight": 1
	},
	{
		"name": "Silverium",
		"ore_value": 100,
		"weight": 1
	},
	{
		"name": "Goldium",
		"ore_value": 250,
		"weight": 2
	},
	{
		"name": "Platinium",
		"ore_value": 750,
		"weight": 3
	},
	{
		"name": "Einsteinium",
		"ore_value": 2000,
		"weight": 4
	},
	{
		"name": "Emerald",
		"ore_value": 5000,
		"weight": 6
	},
	{
		"name": "Ruby",
		"ore_value": 20000,
		"weight": 8
	},
	{
		"name": "Diamond",
		"ore_value": 100000,
		"weight": 10
	},
	{
		"name": "Amazonite",
		"ore_value": 500000,
		"weight": 12
	},
	{
		"name": "Dinosaur Bones",
		"ore_value": 1000,
		"weight": 1
	},
	{
		"name": "Treasure",
		"ore_value": 5000,
		"weight": 1
	},
	{
		"name": "Martian Skeleton",
		"ore_value": 10000,
		"weight": 1
	},
	{
		"name": "Religious Artifact",
		"ore_value": 50000,
		"weight": 1
	},
	{
		"name": "Mr. Natas' Kevlar Suit",
		"ore_value": 50000,
		"weight": 1
	},
	{
		"name": "Mr. Natas' Staff of Hell",
		"ore_value": 100000,
		"weight": 1
	},
	{
		"name": "Mr. Natas' Laser Monacle",
		"ore_value": 200000,
		"weight": 1
	},
	{
		"name": "Satan's Hooves",
		"ore_value": 300000,
		"weight": 1
	},
	{
		"name": "Satan's Horns",
		"ore_value": 400000,
		"weight": 1
	},
	{
		"name": "Satan's Evil Eye (right)",
		"ore_value": 500000,
		"weight": 1
	},
	{
		"name": "Satan's Evil Eye (left)",
		"ore_value": 500000,
		"weight": 1
	},
	{
		"name": "Satan's Boiler of Eternal Infernos",
		"ore_value": 600000,
		"weight": 1
	},
	{
		"name": "Martian Reward for Restoring Peace",
		"ore_value": 1000000,
		"weight": 1
	},
	{
		"name": "250,000 Shares of Natas HI Inc.",
		"ore_value": 25000000,
		"weight": 1
	}
]

func _init(state: GameData) -> void:
	data = state

func generate(seed_value: Variant = null) -> void:
	var random: DotNetRandom = DotNetRandom.new(seed_value)
	generation_seed = random.seed_value
	data.my_map = []
	halfway_blocks.clear()
	blockChangedTexture = false
	for x in range(data.earthWidth):
		var column: Array = []
		for y in range(data.earthHeight):
			column.append([-100, -100])
		data.my_map.append(column)
	for x in range(data.earthWidth):
		for y in range(data.earthHeight):
			var tile: Array = data.my_map[x][y]
			tile[1] = random.Next(4)
			if y < 5:
				tile[0] = 0
			elif y == 5:
				tile[0] = random.Next(2) - 2
			elif y == data.earthHeight - 12:
				tile[0] = random.Next(2) - 7
			elif y >= data.earthHeight - 11 and y < data.earthHeight - 5:
				tile[0] = -999
			elif y == data.earthHeight - 5:
				tile[0] = -(9 + random.Next(4))
			elif y > data.earthHeight - 5:
				tile[0] = -8
			else:
				var mineral_range: int = int(float(y) / 65.0) + 2
				if random.Next(5) == 0:
					if random.Next(5) == 0:
						if random.Next(5) == 0:
							if random.Next(4) == 0 and y > 80:
								tile[0] = random.Next(4) + 16
								if tile[0] == 17:
									tile[1] = 0
							else:
								tile[0] = mini(random.Next(mineral_range) + 8, 15)
						else:
							tile[0] = mini(random.Next(mineral_range) + 7, 15)
					else:
						tile[0] = mini(random.Next(mineral_range) + 6, 15)
				else:
					tile[0] = random.Next(5) + 1
					if float(y) * 1.5 > int(float(data.earthHeight) / 3.0):
						var hazard_range: int = int((float(data.earthHeight - y) / float(data.earthHeight)) * 15.0)
						if random.Next(hazard_range) == 0:
							if float(y) / 2.0 * 1.5 > float(data.earthHeight) / 3.0 and random.Next(2) == 0:
								if float(y) / 3.0 * 1.5 > float(data.earthHeight) / 3.0 and random.Next(2) == 0:
									tile[0] = 31
								else:
									tile[0] = 28 + random.Next(3)
							else:
								tile[0] = 25 + random.Next(3)
				if random.Next(4) == 0:
					tile[0] = 0
	data.my_map[data.earthWidth - 3][data.earthHeight - 12][0] = 0
	data.my_map[data.earthWidth - 4][data.earthHeight - 12][0] = 0
	# Fixed surface buildings and pavement overwrite generated types, not rotations.
	data.my_map[3][3][0] = -125
	data.my_map[4][3][0] = -126
	data.my_map[5][3][0] = -127
	data.my_map[3][4][0] = -128
	data.my_map[4][4][0] = -129
	data.my_map[5][4][0] = -130
	data.my_map[2][5][0] = -3
	data.my_map[3][5][0] = -4
	data.my_map[4][5][0] = -4
	data.my_map[5][5][0] = -5
	data.my_map[10][2][0] = -110
	data.my_map[11][2][0] = -111
	data.my_map[12][2][0] = -112
	data.my_map[13][2][0] = -113
	data.my_map[10][3][0] = -114
	data.my_map[11][3][0] = -115
	data.my_map[12][3][0] = -116
	data.my_map[13][3][0] = -117
	data.my_map[10][4][0] = -118
	data.my_map[11][4][0] = -119
	data.my_map[12][4][0] = -120
	data.my_map[13][4][0] = -121
	data.my_map[9][5][0] = -3
	data.my_map[10][5][0] = -4
	data.my_map[11][5][0] = -4
	data.my_map[12][5][0] = -4
	data.my_map[13][5][0] = -4
	data.my_map[14][5][0] = -5
	data.my_map[25][2][0] = -101
	data.my_map[22][3][0] = -102
	data.my_map[23][3][0] = -103
	data.my_map[24][3][0] = -104
	data.my_map[25][3][0] = -105
	data.my_map[22][4][0] = -106
	data.my_map[23][4][0] = -107
	data.my_map[24][4][0] = -108
	data.my_map[25][4][0] = -109
	data.my_map[21][5][0] = -3
	data.my_map[22][5][0] = -4
	data.my_map[23][5][0] = -4
	data.my_map[24][5][0] = -4
	data.my_map[25][5][0] = -4
	data.my_map[26][5][0] = -5
	data.my_map[30][3][0] = -131
	data.my_map[31][3][0] = -132
	data.my_map[32][3][0] = -133
	data.my_map[30][4][0] = -134
	data.my_map[31][4][0] = -135
	data.my_map[32][4][0] = -136
	data.my_map[30][5][0] = -3
	data.my_map[31][5][0] = -4
	data.my_map[32][5][0] = -4
	data.my_map[33][5][0] = -5
	# Generation itself did not set level_is_already_generated in Unity.

func generateLevel(seed_value: Variant = null) -> void:
	generate(seed_value)

func inBounds(x: int, y: int) -> bool:
	return x >= 0 and x < data.earthWidth and y >= 0 and y < data.earthHeight

func _tile(filename: String, tile_name: String, rotation: int, layer: String, ore_value: int = 0, weight: int = 0) -> Dictionary:
	return {"filename": filename, "name": tile_name, "rotation": rotation, "layer": layer, "ore_value": ore_value, "weight": weight}

func getTileDataFromLevelData(x: int, y: int) -> Dictionary:
	var n: int = int(data.my_map[x][y][0])
	var rotation: int = int(data.my_map[x][y][1])
	if n != 0:
		if n < 6 and n > -1:
			return _tile("Dirt" + str(n), "Dirt", rotation, "Diggable")
		if n == -100:
			return _tile("Half", "Half", rotation, "Diggable")
		if n == -999:
			return _tile("Blank", "Blank", 0, "Traversable")
		if n < -100:
			return _tile("Shop" + str(-n), "Shop", 2, "Traversable")
		if n < 0 and n > -3:
			return _tile("Grass" + str(-n), "Grass", 2, "Diggable")
		if n > -6 and n < -2:
			return _tile("Pavement" + str(-n - 3), "Pavement", 2, "Invincible")
		if n > 24 and n < 28:
			return _tile("Rock" + str(n - 24), "Rock", rotation, "Diggable")
		if n > 27 and n < 31:
			return _tile("Lava" + str(n - 27), "Lava", rotation, "Diggable")
		if n == 31:
			return _tile("Gas", "Gas", rotation, "Diggable")
		if n < -5 and n > -8:
			return _tile("Stalactite" + str(-n - 5), "Stalactite", 2, "Invincible")
		if n == -8:
			return _tile("Darkness", "Darkness", 0, "Invincible")
		if n <= -9 and n >= -12:
			return _tile("Souls" + str(-n - 8), "Souls", 2, "Invincible")
		var mineral: Dictionary = minerals_list[n - 6]
		return _tile(mineral.name, mineral.name, rotation, "Diggable", mineral.ore_value, mineral.weight)
	if y < 5 or y > data.earthHeight - 13:
		return _tile("Empty", "Empty", 0, "Traversable")
	return getTunnelTileGraphicName(x, y)

func _wallValue(x: int, y: int) -> String:
	if not inBounds(x, y) or data.my_map[x][y][0] != 0:
		return "1"
	return "0"

func getTunnelTileGraphicName(x: int, y: int) -> Dictionary:
	var tilename: String = ""
	tilename += _wallValue(x - 1, y - 1)
	tilename += _wallValue(x, y - 1)
	tilename += _wallValue(x + 1, y - 1)
	tilename += _wallValue(x - 1, y)
	tilename += _wallValue(x + 1, y)
	tilename += _wallValue(x - 1, y + 1)
	tilename += _wallValue(x, y + 1)
	tilename += _wallValue(x + 1, y + 1)
	return _tile("DirtConnectors/" + TunnelTiles[tilename], "DirtConnector", 2, "Traversable")

func getBlockData(x: int, y: int) -> Dictionary:
	var key: Vector2i = Vector2i(x, y)
	if halfway_blocks.has(key):
		return halfway_blocks[key]
	return getTileDataFromLevelData(x, y)

func getBlockNameFromAllTiles(x: int, y: int) -> String:
	return getBlockData(x, y).name

func doesBlockExistAndIsDiggable(x: int, y: int) -> bool:
	y = absi(y)
	if not inBounds(x, y):
		return false
	var tile: Dictionary = getBlockData(x, y)
	return tile.layer == "Diggable" and tile.name != "Rock"

func doesBlockExistAndIsNotDiggable(x: int, y: int) -> bool:
	y = absi(y)
	if not inBounds(x, y):
		return false
	var tile: Dictionary = getBlockData(x, y)
	return tile.layer == "Invincible" or tile.name == "Rock"

func halfwayDigBlock(x: int, y: int, previous_x: int, previous_y: int, desired_orientation: int) -> Dictionary:
	var original: Dictionary = getBlockData(x, y).duplicate()
	original.filename = "BlockHalfwayDug" + data.blockHalfwayDugFilename[Vector2i(original.rotation, desired_orientation)]
	halfway_blocks[Vector2i(x, y)] = original
	blockChangedTexture = true
	data.my_map[x][y][0] = 0
	data.my_map[x][y][1] = 0
	# Original TilesManager intentionally swaps previous_y and previous_x.
	var refresh: Array[Vector2i] = []
	if inBounds(previous_y, previous_x) and getBlockData(previous_y, previous_x).layer == "Traversable":
		refresh.append(Vector2i(previous_y, previous_x))
	return {"tile": original, "position": Vector2i(x, y), "refresh_cells": refresh}

func digBlock(x: int, y: int) -> Array[Vector2i]:
	# Does not clear the map: halfwayDigBlock normally did that already.
	blockChangedTexture = false
	halfway_blocks.erase(Vector2i(x, y))
	var changed: Array[Vector2i] = [Vector2i(x, y)]
	for offset in NEIGHBOURS:
		var neighbour: Vector2i = Vector2i(x, y) + offset
		if inBounds(neighbour.x, neighbour.y) and getBlockData(neighbour.x, neighbour.y).layer == "Traversable":
			changed.append(neighbour)
	return changed

func instantDigBlock(x: int, y: int) -> Array[Vector2i]:
	# The coordinate overload clears ANY tile. The original GameObject overload
	# checked isDiggable first (including Rock); callers using that path check layer.
	data.my_map[x][y][0] = 0
	data.my_map[x][y][1] = 0
	return digBlock(x, y)
