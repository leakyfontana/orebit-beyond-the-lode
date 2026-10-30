class_name ReplayRunner
extends RefCounted

var host: Node
var scenario: Dictionary
var output_directory: String
var frame := -1
var axes: Dictionary = {}
var keys: Dictionary = {}
var states: FileAccess
var random_states: FileAccess
var capture_pending := false
var finished := false
var render_delta := 1.0 / 60.0
var live_input := false
const KEY_CODES := {"Escape": KEY_ESCAPE, "I": KEY_I, "LeftArrow": KEY_LEFT, "RightArrow": KEY_RIGHT, "UpArrow": KEY_UP, "DownArrow": KEY_DOWN, "Alpha1": KEY_1, "Alpha2": KEY_2, "Alpha3": KEY_3, "Alpha4": KEY_4, "Alpha5": KEY_5, "Alpha6": KEY_6}
const UI_METHODS := {
	"MainMenuManager": ["startNewGame", "continueGame", "openInstructions", "closeInstructions"],
	"UIManager": ["returnToMainMenu", "updateAllUI", "updateMoneyUI", "updateFuelUI", "updateHullUI", "updateDepthUI"],
	"EndingScreen": ["returnToMainMenu"],
	"InventoryUIManager": ["openUI", "closeUI", "dropMineral"],
	"OptionsUIManager": ["openUI", "closeUI"],
	"HelpUUIManager": ["openUI", "closeUI"],
	"FuelShopManager": ["closeUI", "addFuel", "fillFuel"],
	"ItemShopManager": ["closeUI", "openDisplay", "updateHullBarDisplay", "updateItemInformationScreen", "buyItem", "addHull", "fillHull"],
	"UpgradeShopUI": ["closeUI", "openDisplay", "displayCategory", "updateCategory", "displayPotentialUpgrade", "buyUpgrade"],
	"MineralBuyerManager": ["closeUI", "sellAllMinerals"],
	"PopupManager": ["openPopup", "openPopupWithoutSlowTextDisplayer", "closePopup"],
	"TransmissionManager": ["openUI", "closeUI", "displayTransmission", "updatePortrait"],
	"PercentTextBehavior": ["setTextPercent0to1"],
	"SlowTextDisplayer": ["setText"],
	"PlayerPopupManager": ["finishAnimation"],
}

func configure(game: Node, specification: Dictionary, directory: String) -> void:
	host = game
	scenario = specification
	live_input = bool(specification.get("live_input", false))
	render_delta = PackedFloat32Array([1.0 / float(specification.get("fps", 60))])[0]
	output_directory = directory
	DirAccess.make_dir_recursive_absolute(directory)
	host.data.savefile = directory.path_join("motherloadrecodedsavedata.data")
	host.data.settings_file = directory.path_join("settings.json")
	states = FileAccess.open(directory.path_join("states.jsonl"), FileAccess.WRITE)
	if states == null:
		push_error("Cannot open replay state output: " + directory)
		host.get_tree().quit(1)
	if bool(scenario.get("capture_random", false)):
		random_states = FileAccess.open(directory.path_join("random-states.jsonl"), FileAccess.WRITE)
		if random_states == null:
			push_error("Cannot open replay random-state output: " + directory)
			host.get_tree().quit(1)
	Engine.max_fps = int(scenario.get("fps", 60))

func pre_tick() -> void:
	if finished:
		return
	frame += 1
	for action in scenario.get("actions", []):
		if int(action.frame) != frame:
			continue
		match str(action.kind):
			"axis": axes[str(action.key)] = float(action.value)
			"key":
				keys[str(action.key)] = bool(action.pressed)
				var event := InputEventKey.new()
				event.keycode = KEY_CODES.get(str(action.key), 0)
				event.physical_keycode = event.keycode
				event.pressed = bool(action.pressed)
				if host.ui != null:
					host.ui._input(event)
			"invoke": _invoke(action)
			"checkpoint": _checkpoint(str(action.get("argument", "")))
			_: _fail("Unsupported recorded input: " + str(action.kind))
		if finished:
			return

func _invoke(action: Dictionary) -> void:
	var target := str(action.target)
	var method := str(action.method)
	var supported: Array = UI_METHODS.get(target, [])
	if not method in supported and not (target == "Slider" and method == "set_value"):
		_fail("Unhandled replay method: " + target + "." + method)
		return
	for id in host.bridge.scene.objects:
		var component: Dictionary = host.bridge.object(id)
		if target == "Slider":
			var properties: Dictionary = component.get("properties", {})
			if not properties.has("m_MinValue") or not properties.has("m_MaxValue"):
				continue
		elif str(component.get("script", "")) != target:
			continue
		var owner: String = host.bridge.component_owner(str(id))
		if action.has("target_object") and str(host.bridge.scene.game_objects.get(owner, {}).get("name", "")) != str(action.target_object):
			continue
		var argument: Variant = action.get("argument", null)
		if target == "Slider":
			if not host.bridge.sliders.has(owner):
				_fail("Replay slider missing: " + str(action.get("target_object", owner)))
				return
			host.bridge.sliders[owner].value = float(argument)
		else:
			host.ui._dispatch(str(id), method, argument)
		return
	_fail("Replay target missing: " + target + " " + str(action.get("target_object", "")))

func _checkpoint(argument: String) -> void:
	var parsed: Variant = JSON.parse_string(argument)
	if not parsed is Dictionary:
		_fail("Checkpoint argument must be a JSON object")
		return
	var setup: Dictionary = parsed
	if not host.player_alive or host.player == null or host.body == null or host.ui == null:
		_fail("Checkpoint requires live Game player and HUD")
		return
	if setup.has("position"):
		var position: Variant = setup.position
		if not position is Array or position.size() != 2:
			_fail("Checkpoint position must be two finite Unity world coordinates")
			return
		for coordinate in position:
			if not (coordinate is float or coordinate is int) or not is_finite(float(coordinate)):
				_fail("Checkpoint position must be two finite Unity world coordinates")
				return
	for resource in ["money", "fuel", "hp"]:
		if bool(setup.get("apply_" + resource, false)) and (not setup.has(resource) or not (setup[resource] is float or setup[resource] is int) or not is_finite(float(setup[resource])) or float(setup[resource]) < 0):
			_fail("Checkpoint resources must be nonnegative and finite: " + resource)
			return
	for item in setup.get("items", []):
		if not item is Dictionary or not host.data.player_items.has(item.get("name", "")) or not item.has("count") or float(item.count) < 0 or float(item.count) != int(item.count):
			_fail("Invalid checkpoint item: " + str(item))
			return
	for upgrade in setup.get("upgrades", []):
		if not upgrade is Dictionary or not host.data.current_upgrades.has(upgrade.get("name", "")) or not host.data.upgrades[upgrade.name].has(upgrade.get("value", "")):
			_fail("Invalid checkpoint upgrade: " + str(upgrade))
			return
	if bool(setup.get("apply_boss_hp", false)):
		if host.boss == null or not host.boss.active or host.boss.phase < 0 or int(setup.get("boss_hp", 0)) < 1:
			_fail("Checkpoint boss HP requires an active real boss and positive HP")
			return
	if setup.has("upgrades"):
		for upgrade in setup.upgrades:
			host.data.current_upgrades[upgrade.name] = upgrade.value
		host.data.applyShopUpgrades()
		host.data.updateCargoWeight()
	if bool(setup.get("apply_money", false)):
		host.data.player_money = int(setup.money)
	if bool(setup.get("apply_fuel", false)):
		host.data.player_fuel = float(setup.fuel)
	if bool(setup.get("apply_hp", false)):
		host.data.player_hp = int(setup.hp)
	for item in setup.get("items", []):
		host.data.player_items[item.name] = int(item.count)
	if setup.has("position"):
		host.player.position_unity = Vector2(float(setup.position[0]), float(setup.position[1]))
		host.body.linear_velocity = Vector2.ZERO
		host.body.angular_velocity = 0.0
	if bool(setup.get("apply_boss_hp", false)):
		var phase: Dictionary = host.boss.phases[host.boss.phase]
		phase.hp = float(setup.boss_hp)
		host.boss._update_ui(phase)
	host.ui.displayed_money = host.data.player_money
	host.ui.updateAllUI()

func _fail(message: String) -> void:
	push_error(message)
	finished = true
	states.close()
	if random_states != null:
		random_states.close()
	host.audio.finish_capture()
	host.get_tree().quit(1)

func post_tick() -> void:
	if finished:
		return
	var data: GameData = host.data
	var state := {"frame": frame, "scene": host.scene_name, "time_scale": Engine.time_scale, "fixed_delta": 1.0 / Engine.physics_ticks_per_second}
	state.music_volume = data.music_volume
	state.sound_volume = data.sound_volume
	state.boss_phase = host.boss.phase + 1 if host.boss != null and host.boss.active else 0
	state.boss_hp = host.boss.phases[host.boss.phase].hp if state.boss_phase > 0 else null
	for key in ["player_money", "player_hp", "player_max_hp", "player_fuel", "player_max_fuel", "player_current_cargo_weight", "player_total_weight", "player_max_cargo_weight", "current_upgrades", "player_items", "player_cargo", "my_map"]:
		if key != "my_map" or not live_input:
			state[key] = data.get(key)
	var transmissions: Array = []
	for transmission in data.transmissions:
		transmissions.append({"Item1": transmission.text, "Item2": transmission.signature, "Item3": transmission.picture_name, "Item4": transmission.displayed})
	state.transmissions = transmissions
	state.player_position = [host.player_position.x, host.player_position.y] if host.player_alive else null
	var velocity: Vector2 = host.player.velocity_unity if host.player_alive else Vector2.ZERO
	state.player_velocity = [velocity.x, velocity.y] if host.player_alive else null
	states.store_line(JSON.stringify(state, "", true, true))
	states.flush()
	if random_states != null:
		random_states.store_line(JSON.stringify({"frame": frame, "state": host.unity_random.get_state()}))
		random_states.flush()
	for requested_frame in scenario.get("captures", []):
		if int(requested_frame) == frame:
			capture_pending = true
			_capture(frame)
	if frame + 1 >= int(scenario.frames):
		finished = true
		states.close()
		if random_states != null:
			random_states.close()
		_finish()

func _capture(number: int) -> void:
	await RenderingServer.frame_post_draw
	var image := host.get_viewport().get_texture().get_image()
	var error := image.save_png(output_directory.path_join("frame-%06d.png" % number))
	if error != OK:
		push_error("Screenshot capture failed: " + str(error))
	capture_pending = false

func _finish() -> void:
	if capture_pending:
		await RenderingServer.frame_post_draw
	host.get_tree().quit(0 if host.audio.finish_capture() else 1)
