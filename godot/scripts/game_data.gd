class_name GameData
extends RefCounted

# Persist exactly the original SaveDataType fields using its data-only NRBF codec.
# Health, fuel, position, and derived upgrade/cargo values are not saved.
const BinarySaveCodec = preload("res://scripts/binary_save.gd")
var settings_file: String = "user://motherloadrecodedsettings.json"
const DEFAULT_UPGRADES: Dictionary = {"Drill": "Stock Drill", "Hull": "Stock Hull", "Engine": "Stock Engine", "Fuel": "Micro Tank", "Radiator": "Stock Fan", "Cargo": "Micro Bay"}
const UPGRADE_TABLE: Dictionary = {
	"Drill": {
		"Stock Drill": {
			"price": 2,
			"effect": 2.0
		},
		"Silvide Drill": {
			"price": 750,
			"effect": 2.8
		},
		"Goldium Drill": {
			"price": 2000,
			"effect": 4.0
		},
		"Emerald Drill": {
			"price": 5000,
			"effect": 5.0
		},
		"Ruby Drill": {
			"price": 20000,
			"effect": 7.0
		},
		"Diamond Drill": {
			"price": 100000,
			"effect": 9.5
		},
		"Amazonite Drill": {
			"price": 500000,
			"effect": 12.0
		}
	},
	"Hull": {
		"Stock Hull": {
			"price": 0,
			"effect": 10.0
		},
		"Ironium Hull": {
			"price": 750,
			"effect": 17.0
		},
		"Bronzium Hull": {
			"price": 2000,
			"effect": 30.0
		},
		"Steel Hull": {
			"price": 5000,
			"effect": 50.0
		},
		"Platinium Hull": {
			"price": 20000,
			"effect": 80.0
		},
		"Einsteinium Hull": {
			"price": 100000,
			"effect": 120.0
		},
		"Energy-Shielded Hull": {
			"price": 500000,
			"effect": 180.0
		}
	},
	"Engine": {
		"Stock Engine": {
			"price": 0,
			"effect": 6.0
		},
		"V4 1600 cc": {
			"price": 750,
			"effect": 6.4
		},
		"V4 2.0 Ltr Turbo": {
			"price": 2000,
			"effect": 6.8
		},
		"V6 3.8 Ltr": {
			"price": 5000,
			"effect": 7.2
		},
		"V8 Supercharged 5.0 Ltr": {
			"price": 20000,
			"effect": 7.6
		},
		"V12 6.0 Ltr": {
			"price": 100000,
			"effect": 8.0
		},
		"V16 Jag Engine": {
			"price": 500000,
			"effect": 8.4
		}
	},
	"Fuel": {
		"Micro Tank": {
			"price": 0,
			"effect": 10.0
		},
		"Medium Tank": {
			"price": 750,
			"effect": 15.0
		},
		"Huge Tank": {
			"price": 2000,
			"effect": 25.0
		},
		"Gigantic Tank": {
			"price": 5000,
			"effect": 40.0
		},
		"Titanic Tank": {
			"price": 20000,
			"effect": 60.0
		},
		"Leviathan Tank": {
			"price": 100000,
			"effect": 100.0
		},
		"Liquid Compression Tank": {
			"price": 500000,
			"effect": 150.0
		}
	},
	"Radiator": {
		"Stock Fan": {
			"price": 0,
			"effect": 0.0
		},
		"Dual Fans": {
			"price": 2000,
			"effect": 0.1
		},
		"Single Turbine": {
			"price": 5000,
			"effect": 0.25
		},
		"Dual Turbines": {
			"price": 20000,
			"effect": 0.4
		},
		"Puron Cooling": {
			"price": 100000,
			"effect": 0.6
		},
		"Tri-Turbine Freon Array": {
			"price": 500000,
			"effect": 0.8
		}
	},
	"Cargo": {
		"Micro Bay": {
			"price": 0,
			"effect": 7.0
		},
		"Medium Bay": {
			"price": 750,
			"effect": 15.0
		},
		"Huge Bay": {
			"price": 2000,
			"effect": 25.0
		},
		"Gigantic Bay": {
			"price": 5000,
			"effect": 40.0
		},
		"Titanic Bay": {
			"price": 20000,
			"effect": 70.0
		},
		"Leviathan Bay": {
			"price": 100000,
			"effect": 120.0
		}
	}
}
const ITEM_TABLE: Dictionary = {
	"Reserve Fuel Tank": {
		"price": 2000,
		"description": "Portable backup - refills up to 25 Liters instantaneously.",
		"button_to_press": "1"
	},
	"Hull Repair Nanobots": {
		"price": 7500,
		"description": "Repairs a maximum of 30 Damage anytime, anywhere.",
		"button_to_press": "2"
	},
	"Dynamite": {
		"price": 2000,
		"description": "Blasts clear a small area around your pod.",
		"button_to_press": "3"
	},
	"Plastic Explosives": {
		"price": 5000,
		"description": "Creates an enormous explosion, clearing a large area around your pod.",
		"button_to_press": "4"
	},
	"Quantum Teleporter": {
		"price": 2000,
		"description": "Teleports you somewhere above surface level.  (results may vary)",
		"button_to_press": "5"
	},
	"Matter Transmitter": {
		"price": 10000,
		"description": "Safely and accurately returns you above ground.",
		"button_to_press": "6"
	},
	"Core Teleporter": {
		"price": 1,
		"description": "Teleports you directly to the planet's core",
		"button_to_press": "0"
	}
}
const MINERAL_TABLE: Dictionary = {
	"Ironium": {
		"ore_value": 30,
		"weight": 1
	},
	"Bronzium": {
		"ore_value": 60,
		"weight": 1
	},
	"Silverium": {
		"ore_value": 100,
		"weight": 1
	},
	"Goldium": {
		"ore_value": 250,
		"weight": 2
	},
	"Platinium": {
		"ore_value": 750,
		"weight": 3
	},
	"Einsteinium": {
		"ore_value": 2000,
		"weight": 4
	},
	"Emerald": {
		"ore_value": 5000,
		"weight": 6
	},
	"Ruby": {
		"ore_value": 20000,
		"weight": 8
	},
	"Diamond": {
		"ore_value": 100000,
		"weight": 10
	},
	"Amazonite": {
		"ore_value": 500000,
		"weight": 12
	},
	"Dinosaur Bones": {
		"ore_value": 5000,
		"weight": 1
	},
	"Treasure": {
		"ore_value": 12500,
		"weight": 1
	},
	"Martian Skeleton": {
		"ore_value": 20000,
		"weight": 1
	},
	"Religious Artifact": {
		"ore_value": 50000,
		"weight": 1
	},
	"Mr. Natas' Kevlar Suit": {
		"ore_value": 50000,
		"weight": 1
	},
	"Mr. Natas' Staff of Hell": {
		"ore_value": 100000,
		"weight": 1
	},
	"Mr. Natas' Laser Monacle": {
		"ore_value": 200000,
		"weight": 1
	},
	"Satan's Hooves": {
		"ore_value": 300000,
		"weight": 1
	},
	"Satan's Horns": {
		"ore_value": 400000,
		"weight": 1
	},
	"Satan's Evil Eye (right)": {
		"ore_value": 500000,
		"weight": 1
	},
	"Satan's Evil Eye (left)": {
		"ore_value": 500000,
		"weight": 1
	},
	"Satan's Boiler of Eternal Infernos": {
		"ore_value": 600000,
		"weight": 1
	},
	"Martian Reward for Restoring Peace": {
		"ore_value": 1000000,
		"weight": 1
	},
	"250,000 Shares of Natas HI Inc.": {
		"ore_value": 25000000,
		"weight": 1
	}
}
const TRANSMISSION_TABLE: Array = [
	{
		"text": "We forgot to refuel you on the way over!  Drive over to the fuel station (Left) and fill 'er up!\n\nIt's been almost impossible to hire decent miners on Mars since all the strange activity started happening around here.  That's why we're willing to pay you at a premium for your services!\n\nI've given you a basic mining machine to get started with.  Unfortunately, you'll be on your own from this point onward, as the settlers who were lucky enough to escape with their lives have fled to safety.  However, all of the shops here have been computerized, so you'll still be able to sell your minerals, fuel up, upgrade your pod, and buy special items.\n\nRemember - your job is to collect minerals and bring them back to the surface for processing.  The deeper you dig, the more valuable the minerals you'll encounter.\n\nDon't forget to refuel - Good Luck!",
		"signature": "Mr. Natas",
		"picture_name": "natas",
		"displayed": false
	},
	{
		"text": "Good!  I see you're adapting well to the Martian soil!\n\nHere's a little something to help you on your way.",
		"signature": "Mr. Natas",
		"picture_name": "natas",
		"displayed": false
	},
	{
		"text": "Congratulations on reaching a depth of 1000 ft!  I've wired you a bonus for your excellent work.\n\nWe're picking up some heavy vibrations from the planet core - They seem to be causing some earthquakes.  They also seem to be causing some garbled and misdirected transmissions - just ignore them.\n\nKeep up the good work!",
		"signature": "Mr. Natas",
		"picture_name": "natas",
		"displayed": false
	},
	{
		"text": "\n\nThe eyes... oh my god, THE EYES!!!",
		"signature": "Unidentified Source",
		"picture_name": "static",
		"displayed": false
	},
	{
		"text": "I'm suprised to find another signal around here... I'm the only miner who hasn't disappeared in the past three years.  Next week, I finally get to retire, wealthy, to the moons of jupiter with my wife and three daughters.",
		"signature": "Martian Digging Pod #3422-2",
		"picture_name": "miner",
		"displayed": false
	},
	{
		"text": "Is anyone there?!  I need help badly!!  I can't feel my legs - Oh god, he's coming back..\n\nOH NO!! PLEASE HELP ME!!! AAAHHHHGGGK!.",
		"signature": "Unidentified Source",
		"picture_name": "static",
		"displayed": false
	},
	{
		"text": "How are you making out, kid? I know you're new here, so I though I'd give you a tip; make sure you don't neglect your radiator.  I ran into a Lava pocket a few moments ago, but my twin turbines dissipated the heat amazingly and my hull was barely damaged - Probably saved my life.",
		"signature": "Martian Digging Pod #3422-2",
		"picture_name": "miner",
		"displayed": false
	},
	{
		"text": "Once again, congratulations!  You've made it farther than even I anticipated...\n\nAnyways, I've sent you another bonus. One more thing - Your altimeter is only rated for a depth of around 6000 ft.  After that, you'll need to turn back. Really - it's just too dangerous.",
		"signature": "Mr. Natas",
		"picture_name": "natas",
		"displayed": false
	},
	{
		"text": "Trapped... in a crevasse.\n\nEarthquake damaged my drill and I'm out fuel.\n\nThis will probably be my last transmission.\n\nTell my kids.. I love them.. I-\n\nwhat? YOU!?? what are you doing dow-AAARGH!",
		"signature": "Martian Digging Pod #3422-2",
		"picture_name": "miner",
		"displayed": false
	},
	{
		"text": "Oh BABY!!! THIS IS IT!!! I HIT THE MOTHERLOAD!!!!! I'm rich, I'm FILTHY rich!!\n\nHey, what the!??  NO!   IT CAN'T BE!!!!  OH GOD!!",
		"signature": "Martian Digging Pod #10043",
		"picture_name": "static",
		"displayed": false
	},
	{
		"text": "You are violating the terms of your employment!  Turn back immediately!",
		"signature": "Mr. Natas",
		"picture_name": "natas",
		"displayed": false
	},
	{
		"text": "Return to the surface immediately or you'll be terminated... er... as in fired!",
		"signature": "Mr. Natas",
		"picture_name": "natas",
		"displayed": false
	},
	{
		"text": "HAHAHA!! YOU FOOL!!!\n\nI told you to turn back... now I have no choice but to kill you.  You've served my factories well, but I think I'll take my machine, my money, and your pathetic life now.\n\nSEE YOU IN HELL!!!",
		"signature": "Mr. Natas",
		"picture_name": "natas",
		"displayed": false
	},
	{
		"text": "MWAHAHAHA!  Imbecile!!\n\nYou really think you can defeat me?\n\nI am the master of all EVIL!\n\nBEHOLD MY TRUE FORM!!!",
		"signature": "Mr. Natas",
		"picture_name": "natas",
		"displayed": false
	}
]

var savefile: String = "user://motherloadrecodedsavedata.data"
var string_format: Dictionary = {"NumberGroupSeparator": " "}
var player_money: int = 20
var level_is_already_generated: bool = false
var player_horizontal_speed: float = 0.0
var player_vertical_speed: float = 0.0
var player_dig_speed: float = 0.0
var player_hp: int = 0
var player_max_hp: int = 0
var player_fuel: float = 0.0
var player_max_fuel: float = 0.0
var player_radiator: float = 0.0
var player_current_cargo_weight: int = 0
var player_total_weight: int = 1980
var player_max_cargo_weight: int = 0
var music_volume: float = 1.0
var sound_volume: float = 1.0
var upgrades: Dictionary = UPGRADE_TABLE.duplicate(true)
var current_upgrades: Dictionary = DEFAULT_UPGRADES.duplicate()
var items: Dictionary = ITEM_TABLE.duplicate(true)
var player_items: Dictionary = {"Reserve Fuel Tank": 0, "Hull Repair Nanobots": 0, "Dynamite": 0, "Plastic Explosives": 0, "Quantum Teleporter": 0, "Matter Transmitter": 0}
# Core Teleporter exists in the shop table but not in inventory, just as in Unity.
var my_map: Array = []
var earthWidth: int = 36
var earthHeight: int = 600
var minerals: Dictionary = MINERAL_TABLE.duplicate(true)
var minerals_name_list: Array = ["Ironium", "Bronzium", "Silverium", "Goldium", "Platinium", "Einsteinium", "Emerald", "Ruby", "Diamond", "Amazonite"]
var treasure_name_list: Array = [
	"Dinosaur Bones",
	"Treasure",
	"Martian Skeleton",
	"Religious Artifact",
	"Mr. Natas' Kevlar Suit",
	"Mr. Natas' Staff of Hell",
	"Mr. Natas' Laser Monacle",
	"Satan's Hooves",
	"Satan's Horns",
	"Satan's Evil Eye (right)",
	"Satan's Evil Eye (left)",
	"Satan's Boiler of Eternal Infernos",
	"Martian Reward for Restoring Peace",
	"250,000 Shares of Natas HI Inc."
]
var player_cargo: Dictionary = {"Ironium": 0, "Bronzium": 0, "Silverium": 0, "Goldium": 0, "Platinium": 0, "Einsteinium": 0, "Emerald": 0, "Ruby": 0, "Diamond": 0, "Amazonite": 0}
var transmissions: Array = TRANSMISSION_TABLE.duplicate(true)
var blockHalfwayDugFilename: Dictionary = {
	Vector2i(0, 0): "Up", Vector2i(0, 1): "Left", Vector2i(0, 2): "Down", Vector2i(0, 3): "Right",
	Vector2i(1, 0): "Right", Vector2i(1, 1): "Up", Vector2i(1, 2): "Left", Vector2i(1, 3): "Down",
	Vector2i(2, 0): "Down", Vector2i(2, 1): "Right", Vector2i(2, 2): "Up", Vector2i(2, 3): "Left",
	Vector2i(3, 0): "Left", Vector2i(3, 1): "Down", Vector2i(3, 2): "Right", Vector2i(3, 3): "Up"
}

func applyShopUpgrades() -> void:
	player_dig_speed = upgrades["Drill"][current_upgrades["Drill"]].effect
	player_max_hp = int(upgrades["Hull"][current_upgrades["Hull"]].effect)
	player_horizontal_speed = upgrades["Engine"][current_upgrades["Engine"]].effect
	player_vertical_speed = upgrades["Engine"][current_upgrades["Engine"]].effect
	player_max_fuel = upgrades["Fuel"][current_upgrades["Fuel"]].effect
	player_radiator = upgrades["Radiator"][current_upgrades["Radiator"]].effect
	player_max_cargo_weight = int(upgrades["Cargo"][current_upgrades["Cargo"]].effect)

func resetCargo() -> void:
	for mineral in player_cargo:
		player_cargo[mineral] = 0
	updateCargoWeight()

func sellCargo() -> int:
	var total: int = 0
	for mineral in player_cargo:
		var value: int = minerals[mineral].ore_value * player_cargo[mineral]
		player_money += value
		total += value
	resetCargo()
	return total

func addMineralInCargo(mineral_name: String) -> bool:
	if player_current_cargo_weight + minerals[mineral_name].weight > player_max_cargo_weight:
		return false
	player_cargo[mineral_name] += 1
	updateCargoWeight()
	return true

func removeMineralInCargo(mineral_name: String) -> bool:
	if player_cargo[mineral_name] <= 0:
		return false
	player_cargo[mineral_name] -= 1
	updateCargoWeight()
	return true

func updateCargoWeight() -> void:
	player_current_cargo_weight = 0
	for mineral in player_cargo:
		player_current_cargo_weight += player_cargo[mineral] * minerals[mineral].weight
	player_total_weight = player_current_cargo_weight * 10 + 1980

func addTreasureInCargo(treasure_name: String) -> void:
	player_money += minerals[treasure_name].ore_value

func returnCargoString() -> String:
	var result: String = "Cargo: "
	for mineral in minerals_name_list:
		if player_cargo.has(mineral):
			result += mineral + " " + str(player_cargo[mineral]) + ", "
	return result

func returnItemString() -> String:
	var result: String = "Items: "
	for item_name in player_items:
		result += item_name + " " + str(player_items[item_name]) + ", "
	return result

func returnUpgradeString() -> String:
	var result: String = "Upgrades: "
	for category in ["Drill", "Hull", "Engine", "Fuel", "Radiator", "Cargo"]:
		result += current_upgrades[category] + ", "
	return result

func tryToBuy(price: int) -> bool:
	if player_money >= price:
		player_money -= price
		return true
	return false

func addFuel(dollar_amount: int) -> void:
	player_fuel = minf(player_fuel + dollar_amount, player_max_fuel)

func addHull(dollar_amount: int) -> void:
	player_hp = int(minf(player_hp + ceilf(float(dollar_amount) / 15.0), player_max_hp))

func addItem(item_name: String) -> void:
	player_items[item_name] += 1

func setUpgrade(category: String, upgrade_name: String) -> void:
	current_upgrades[category] = upgrade_name
	applyShopUpgrades()

func initPlayer() -> void:
	applyShopUpgrades()
	player_hp = player_max_hp
	# The literal five survives new games AND loads when it happens to be current fuel.
	if player_fuel != 5:
		player_fuel = player_max_fuel
	updateCargoWeight()

func setVolumeLevels() -> void:
	var preferences: Dictionary = {}
	if FileAccess.file_exists(settings_file):
		var saved: Variant = JSON.parse_string(FileAccess.get_file_as_string(settings_file))
		if saved is Dictionary:
			preferences = saved
	var changed: bool = false
	for key in ["music_volume", "sound_volume"]:
		if not preferences.has(key):
			preferences[key] = 1.0
			changed = true
	music_volume = float(preferences["music_volume"])
	sound_volume = float(preferences["sound_volume"])
	if changed:
		_writeJson(settings_file, preferences)

func saveVolumeLevels(music: float, sound: float) -> bool:
	# PlayerPrefs.SetFloat does not clamp; neither does this API.
	music_volume = music
	sound_volume = sound
	return _writeJson(settings_file, {"music_volume": music, "sound_volume": sound})

func _writeJson(path: String, contents: Dictionary) -> bool:
	var file: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("Cannot write " + path + ": " + error_string(FileAccess.get_open_error()))
		return false
	# Sorted keys and full floating-point precision make serialization deterministic.
	file.store_string(JSON.stringify(contents, "\t", true, true) + "\n")
	var result: Error = file.get_error()
	file.close()
	if result != OK:
		push_error("Cannot save " + path + ": " + error_string(result))
	return result == OK

func saveData() -> bool:
	var codec = BinarySaveCodec.new()
	var bytes: PackedByteArray = codec.encode({
		"player_money": player_money,
		"current_upgrades": current_upgrades,
		"player_items": player_items,
		"my_map": my_map,
		"player_cargo": player_cargo,
		"transmissions": transmissions
	})
	if not codec.error.is_empty():
		push_error("Cannot save " + savefile + ": " + codec.error)
		return false
	var file: FileAccess = FileAccess.open(savefile, FileAccess.WRITE)
	if file == null:
		push_error("Cannot save " + savefile + ": " + error_string(FileAccess.get_open_error()))
		return false
	file.store_buffer(bytes)
	var result: Error = file.get_error()
	file.close()
	if result != OK:
		push_error("Cannot save " + savefile + ": " + error_string(result))
	return result == OK

func loadData() -> bool:
	var file: FileAccess = FileAccess.open(savefile, FileAccess.READ)
	if file == null:
		push_error("Cannot load " + savefile + ": " + error_string(FileAccess.get_open_error()))
		return false
	if file.get_length() > BinarySaveCodec.MAX_BYTES:
		file.close()
		push_error("Cannot load " + savefile + ": save exceeds NRBF size limit")
		return false
	var codec = BinarySaveCodec.new()
	var saved: Dictionary = codec.decode(file.get_buffer(file.get_length()))
	file.close()
	if not codec.error.is_empty():
		push_error("Cannot load " + savefile + ": " + codec.error)
		return false
	setVolumeLevels()
	player_money = int(saved.player_money)
	current_upgrades = saved.current_upgrades
	player_items = saved.player_items
	my_map = saved.my_map
	player_cargo = saved.player_cargo
	transmissions = saved.transmissions
	level_is_already_generated = true
	return true

func doesSaveFileExist() -> bool:
	return FileAccess.file_exists(savefile)

func setNewGameData() -> void:
	player_money = 20
	current_upgrades = DEFAULT_UPGRADES.duplicate()
	player_items = {"Reserve Fuel Tank": 0, "Hull Repair Nanobots": 0, "Dynamite": 0, "Plastic Explosives": 0, "Quantum Teleporter": 0, "Matter Transmitter": 0}
	player_cargo = {"Ironium": 0, "Bronzium": 0, "Silverium": 0, "Goldium": 0, "Platinium": 0, "Einsteinium": 0, "Emerald": 0, "Ruby": 0, "Diamond": 0, "Amazonite": 0}
	transmissions = TRANSMISSION_TABLE.duplicate(true)
	# Do not reset map, generated flag, HP, derived weights, or settings: original quirk.
	player_fuel = 5
