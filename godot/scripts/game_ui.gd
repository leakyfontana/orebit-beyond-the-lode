class_name GameUI
extends Node

# UnityEvent targets remain component IDs; all scene references pass through
# SceneBridge.component_owner so both GameObject and component references work.
# Input ownership: ESC closes the active original panel, otherwise opens options;
# I opens inventory. Neither key is a toggle for inventory. Slider callbacks use
# serialized m_OnValueChanged; buttons arrive through SceneBridge.invoked.
signal mouse_control_changed(enabled: bool)

const SHOP_SCRIPTS: Array[String] = ["FuelShopManager", "MineralBuyerManager", "ItemShopManager", "UpgradeShopUI"]
const PANEL_SCRIPTS: Array[String] = ["FuelShopManager", "MineralBuyerManager", "ItemShopManager", "UpgradeShopUI", "HelpUUIManager", "OptionsUIManager", "InventoryUIManager", "TransmissionManager"]
const UPGRADE_NAMES: Dictionary = {
	"Drill": ["Stock Drill", "Silvide Drill", "Goldium Drill", "Emerald Drill", "Ruby Drill", "Diamond Drill", "Amazonite Drill"],
	"Hull": ["Stock Hull", "Ironium Hull", "Bronzium Hull", "Steel Hull", "Platinium Hull", "Einsteinium Hull", "Energy-Shielded Hull"],
	"Engine": ["Stock Engine", "V4 1600 cc", "V4 2.0 Ltr Turbo", "V6 3.8 Ltr", "V8 Supercharged 5.0 Ltr", "V12 6.0 Ltr", "V16 Jag Engine"],
	"Fuel": ["Micro Tank", "Medium Tank", "Huge Tank", "Gigantic Tank", "Titanic Tank", "Leviathan Tank", "Liquid Compression Tank"],
	"Radiator": ["Stock Fan", "Dual Fans", "Single Turbine", "Dual Turbines", "Puron Cooling", "Tri-Turbine Freon Array"],
	"Cargo": ["Micro Bay", "Medium Bay", "Huge Bay", "Gigantic Bay", "Titanic Bay", "Leviathan Bay"]
}
const EFFECT_UNITS: Dictionary = {"Drill": " Ft/s", "Hull": " Health", "Engine": " HorsePower", "Fuel": " Liters", "Radiator": "% Effective", "Cargo": " Cu ft."}
const EFFECT_MULTIPLIERS: Dictionary = {"Drill": 10, "Hull": 1, "Engine": 25, "Fuel": 1, "Radiator": 100, "Cargo": 1}

var host: Node
var bridge: SceneBridge
var data: GameData
var audio: GameAudio
var script_components: Dictionary = {}
var panel_active: Dictionary = {}
var slow_text: Dictionary = {}
var displayed_money: int = 0
var previous_fuel_percent: int = 0
var previous_hull_percent: int = 0
var is_low_fuel_playing: bool = false
var is_very_low_fuel_playing: bool = false
var current_category: String = ""
var current_potential_upgrade: String = ""
var currently_selected_item: String = ""
var current_transmission_index: int = 0
var _boss_health: Control
var _boss_health_offsets := Vector4.ZERO
var controller_ui: ControllerUI

func configure(game_host: Node, scene_bridge: SceneBridge, game_data: GameData, game_audio: GameAudio) -> void:
	host = game_host
	bridge = scene_bridge
	data = game_data
	audio = game_audio
	process_mode = Node.PROCESS_MODE_ALWAYS
	bridge.invoked.connect(_dispatch)
	for id in bridge.scene.objects:
		var component: Dictionary = bridge.object(str(id))
		var script: String = _script_name(str(component.get("script", "")))
		if script.is_empty():
			continue
		if not script_components.has(script):
			script_components[script] = []
		script_components[script].append(str(id))
		if script == "SlowTextDisplayer":
			var p: Dictionary = component.properties
			slow_text[bridge.component_owner(id)] = {
				"text": "", "complete": false, "count": 0,
				"interval": float(p.get("max_time_until_next_char", 0)),
				"remaining": float(p.get("max_time_until_next_char", 0)),
				"underscore": bool(p.get("show_underscore_at_end", false))
			}
	for id in bridge.scene.game_objects:
		_install_slider_callbacks(str(id))
	for id in script_components.get("CancelMouseMovementOnMouseHover", []):
		var control: Node = bridge.node(id)
		if control is Control:
			control.mouse_filter = Control.MOUSE_FILTER_PASS
			control.mouse_entered.connect(_mouse_entered)
			control.mouse_exited.connect(_mouse_exited)
	var hud: Dictionary = _properties("UIManager")
	if not hud.is_empty():
		displayed_money = int(hud.get("displayed_money", 0))
		previous_fuel_percent = int(hud.get("previous_fuel_percent", 0))
		previous_hull_percent = int(hud.get("previous_hull_percent", 0))
		updateAllUI()
		_install_boss_health_layout()
	for script in PANEL_SCRIPTS:
		if script_components.has(script):
			panel_active[script] = false
	_sync_panels()
	controller_ui = ControllerUI.new()
	add_child(controller_ui)
	controller_ui.configure(self)

func _install_boss_health_layout() -> void:
	_boss_health = bridge.node(_child(_panel("UIManager"), "BossHealth")) as Control
	if _boss_health == null:
		return
	_boss_health_offsets = Vector4(_boss_health.offset_left, _boss_health.offset_top, _boss_health.offset_right, _boss_health.offset_bottom)
	var touch := host.touch_controls as TouchControls
	touch.hud_layout_changed.connect(_layout_boss_health)
	(_boss_health.get_parent() as Control).resized.connect(_layout_boss_health)
	_layout_boss_health()

func _layout_boss_health() -> void:
	var touch := host.touch_controls as TouchControls
	var safe := touch.get_hud_safe_rect()
	if not safe.has_area():
		return
	# BossHealth is the complete source hierarchy (bar, frame and HP text).
	# Preserve its desktop anchors/geometry; only touch layouts reserve the
	# existing safe-area dock. Both CanvasLayers must use the same coordinates.
	var parent := _boss_health.get_parent() as Control
	safe = (parent.get_global_transform_with_canvas().affine_inverse() * touch.get_global_transform_with_canvas()) * safe
	_boss_health.offset_left = _boss_health_offsets.x
	_boss_health.offset_top = _boss_health_offsets.y
	_boss_health.offset_right = _boss_health_offsets.z
	_boss_health.offset_bottom = _boss_health_offsets.w
	_boss_health.scale = Vector2.ONE
	var source_rect := _boss_health.get_rect()
	var fit := minf(1.0, minf(safe.size.x / source_rect.size.x, safe.size.y / source_rect.size.y))
	var fitted_size := source_rect.size * fit
	var origin := Vector2(
		clampf(source_rect.position.x, safe.position.x, safe.end.x - fitted_size.x),
		clampf(source_rect.position.y, safe.position.y, safe.end.y - fitted_size.y))
	_boss_health.scale = Vector2.ONE * fit
	_boss_health.position = origin - _boss_health.pivot_offset * (1.0 - fit)

func _script_name(value: String) -> String:
	return "HelpUUIManager" if value == "HelpUIManager" else value

func _component(script: String) -> String:
	var ids: Array = script_components.get(script, [])
	return str(ids[0]) if not ids.is_empty() else "0"

func _properties(script: String) -> Dictionary:
	return bridge.object(_component(script)).get("properties", {})

func _panel(script: String) -> String:
	return bridge.component_owner(_component(script))

func _active(reference: Variant) -> bool:
	var target: Node = bridge.node(reference)
	return target is CanvasItem and target.visible

func _visible(reference: Variant) -> bool:
	var target: Node = bridge.node(reference)
	return target is CanvasItem and target.is_visible_in_tree()

func _child(reference: Variant, path: String) -> String:
	var id: String = bridge.component_owner(reference)
	for part in path.split("/"):
		var found: String = ""
		for candidate in bridge.scene.game_objects.get(id, {}).get("children", []):
			if str(bridge.scene.game_objects[str(candidate)].name) == part:
				found = str(candidate)
				break
		if found.is_empty():
			push_error("Missing original UI child '" + path + "' under " + id)
			return "0"
		id = found
	return id

func _children(reference: Variant) -> Array:
	return bridge.scene.game_objects.get(bridge.component_owner(reference), {}).get("children", [])

func _object_name(reference: Variant) -> String:
	return str(bridge.scene.game_objects.get(bridge.component_owner(reference), {}).get("name", ""))

func _text(reference: Variant, value: String) -> void:
	bridge.set_text(reference, value)

func _slow(reference: Variant, value: String) -> void:
	var id: String = bridge.component_owner(reference)
	if not slow_text.has(id):
		push_error("Missing original SlowTextDisplayer on " + id)
		return
	var state: Dictionary = slow_text[id]
	state.text = value
	state.count = 0
	state.complete = false
	# The original does not reset its remaining character timer here.
	_text(id, "" if value.is_empty() else "_")

func _image_alpha(reference: Variant, alpha: float) -> void:
	var id: String = bridge.component_owner(reference)
	if bridge.graphics.has(id):
		bridge.graphics[id].modulate.a = alpha

func _resource_image(reference: Variant, resource: String) -> void:
	var guids: Array = bridge.manifest.get("resources", {}).get(resource, [])
	if guids.is_empty():
		push_error("Missing original Resources texture: " + resource)
		return
	var asset: Dictionary = bridge.manifest.assets[str(guids[0])]
	bridge.set_image(reference, str(asset.path))

func _grouped(value: int) -> String:
	var digits: String = str(absi(value))
	var result: String = ""
	for index in range(digits.length()):
		if index > 0 and (digits.length() - index) % 3 == 0:
			result += " "
		result += digits[index]
	return ("-" if value < 0 else "") + result

func _round_even(value: float) -> int:
	var lower: int = floori(value)
	if value - lower == 0.5:
		return lower if lower % 2 == 0 else lower + 1
	return roundi(value)

func _number(value: float) -> String:
	return str(int(value)) if value == floorf(value) else str(value)

func _input(event: InputEvent) -> void:
	if host.coop != null and host.coop.lobby.modal:
		return
	if not event.is_pressed() or (event is InputEventKey and event.echo):
		return
	if event.is_action_pressed(&"pause"):
		var open_scripts: Array[String] = []
		for script in PANEL_SCRIPTS:
			if script_components.has(script) and _visible(_panel(script)):
				open_scripts.append(script)
		if open_scripts.is_empty():
			open_options()
		else:
			# Every enabled original manager receives the same Escape key down.
			for script in open_scripts:
				_close_panel(script)
		get_viewport().set_input_as_handled()
	elif event.is_action_pressed(&"inventory"):
		open_inventory()
		get_viewport().set_input_as_handled()

func tick(delta: float) -> void:
	_sync_panels()
	controller_ui.sync_state(delta)
	_update_slow_text(delta)
	if script_components.has("UIManager"):
		updateDepthUI()
		if displayed_money != data.player_money and not isFreezingMoneyUIOpen():
			var step: int = maxi(1, absi(int(float(data.player_money - displayed_money) / 20.0)))
			displayed_money = int(move_toward(float(displayed_money), float(data.player_money), float(step)))
			updateMoneyUI()

func _update_slow_text(delta: float) -> void:
	for id in slow_text:
		if not _visible(id):
			continue
		var state: Dictionary = slow_text[id]
		if state.interval == 0.0:
			_text(id, str(state.text))
			state.complete = true
		if state.complete:
			continue
		state.remaining -= delta
		if state.remaining < 0.0:
			state.remaining = state.interval
			if state.count >= str(state.text).length():
				if not state.underscore:
					_text(id, str(state.text))
					if int(state.count) % 3 == 0:
						audio.PlaySoundOneShot("ComputerTypeLetter2")
				state.complete = true
			else:
				state.count += 1
				_text(id, str(state.text).substr(0, int(state.count)) + "_")
				if int(state.count) % 3 == 0:
					audio.PlaySoundOneShot("ComputerTypeLetter2")

func _install_slider_callbacks(id: String) -> void:
	if not bridge.sliders.has(id):
		return
	for component in bridge.components(id):
		var p: Dictionary = component.get("properties", {})
		if p.has("m_OnValueChanged"):
			var calls: Array = p.m_OnValueChanged.get("m_PersistentCalls", {}).get("m_Calls", [])
			bridge.sliders[id].value_changed.connect(_slider_changed.bind(calls))

func _slider_changed(value: float, calls: Array) -> void:
	for event in calls:
		if int(event.get("m_CallState", 0)) == 0:
			continue
		var argument: Variant = value
		var arguments: Dictionary = event.get("m_Arguments", {})
		match int(event.get("m_Mode", 0)):
			1: argument = null
			2: argument = arguments.get("m_ObjectArgument", {})
			3: argument = int(arguments.get("m_IntArgument", 0))
			4: argument = float(arguments.get("m_FloatArgument", 0))
			5: argument = str(arguments.get("m_StringArgument", ""))
			6: argument = bool(arguments.get("m_BoolArgument", false))
		_dispatch(bridge.reference_id(event.get("m_Target", {})), str(event.get("m_MethodName", "")), argument)

func _mouse_entered() -> void:
	mouse_control_changed.emit(false)

func _mouse_exited() -> void:
	mouse_control_changed.emit(true)

func _dispatch(target_id: String, method: String, argument: Variant) -> void:
	var target: Dictionary = bridge.object(target_id)
	var script: String = _script_name(str(target.get("script", "")))
	if script.is_empty() and bridge.scene.game_objects.has(target_id):
		for component in bridge.components(target_id):
			var candidate: String = _script_name(str(component.get("script", "")))
			if candidate in PANEL_SCRIPTS or candidate in ["MainMenuManager", "UIManager", "EndingScreen", "PopupManager", "PercentTextBehavior", "SlowTextDisplayer", "PlayerPopupManager"]:
				script = candidate
				break
	match script:
		"MainMenuManager":
			match method:
				"startNewGame": startNewGame()
				"continueGame": continueGame()
				"openInstructions": openInstructions()
				"closeInstructions": closeInstructions()
		"UIManager", "EndingScreen":
			match method:
				"returnToMainMenu": returnToMainMenu()
				"updateAllUI": updateAllUI()
				"updateMoneyUI": updateMoneyUI()
				"updateFuelUI": updateFuelUI()
				"updateHullUI": updateHullUI()
				"updateDepthUI": updateDepthUI()
		"InventoryUIManager":
			match method:
				"openUI": open_inventory()
				"closeUI": _close_panel(script)
				"dropMineral": dropMineral(str(argument))
		"OptionsUIManager", "HelpUUIManager":
			match method:
				"openUI": _open_guarded(script)
				"closeUI": _close_panel(script)
		"FuelShopManager":
			match method:
				"closeUI": _close_panel(script)
				"addFuel": addFuel(int(argument))
				"fillFuel": fillFuel()
		"ItemShopManager":
			match method:
				"closeUI": _close_panel(script)
				"openDisplay": _item_open_display()
				"updateHullBarDisplay": updateHullBarDisplay()
				"updateItemInformationScreen": updateItemInformationScreen(str(argument))
				"buyItem": buyItem()
				"addHull": addHull(int(argument))
				"fillHull": fillHull()
		"UpgradeShopUI":
			match method:
				"closeUI": _close_panel(script)
				"openDisplay": _upgrade_open_display()
				"displayCategory": displayCategory(str(argument))
				"updateCategory": updateCategory()
				"displayPotentialUpgrade": displayPotentialUpgrade(int(argument))
				"buyUpgrade": buyUpgrade()
		"MineralBuyerManager":
			match method:
				"closeUI": _close_panel(script)
				"sellAllMinerals": sellAllMinerals()
		"PopupManager":
			match method:
				"openPopup": _open_popup(target_id, str(argument), true)
				"openPopupWithoutSlowTextDisplayer": _open_popup(target_id, str(argument), false)
				"closePopup": bridge.set_active(target_id, false)
		"TransmissionManager":
			match method:
				"openUI":
					host.enterShop()
					_set_panel(script, true)
				"closeUI": _close_panel(script)
				"displayTransmission": displayTransmission(int(argument))
				"updatePortrait": updatePortrait(str(argument))
		"PercentTextBehavior":
			if method == "setTextPercent0to1":
				_text(target_id, str(_round_even(float(argument) * 100.0)) + "%")
		"SlowTextDisplayer":
			if method == "setText":
				_slow(target_id, str(argument))
		"PlayerPopupManager":
			if method == "finishAnimation":
				var popup: Node = bridge.node(target_id)
				if popup != null:
					popup.queue_free()

func isUIOpen() -> bool:
	for reference in _properties("UIManager").get("allUI", []):
		if _active(reference):
			return true
	return false

func isFreezingMoneyUIOpen() -> bool:
	for reference in _properties("UIManager").get("freezingMoneyUI", []):
		if _active(reference):
			return true
	return false

func _sync_panels() -> void:
	for script in panel_active:
		var enabled: bool = _visible(_panel(script))
		if enabled != bool(panel_active[script]):
			panel_active[script] = enabled
			_panel_lifecycle(script, enabled)

func _set_panel(script: String, enabled: bool) -> void:
	bridge.set_active(_panel(script), enabled)
	_sync_panels()

func _panel_lifecycle(script: String, enabled: bool) -> void:
	if not SHOP_SCRIPTS.has(script):
		return
	if enabled:
		host.enterShop()
		match script:
			"UpgradeShopUI": _upgrade_open_display()
			"FuelShopManager": _update_fuel_bar()
			"ItemShopManager": _item_open_display()
			"MineralBuyerManager": _update_mineral_buyer()
	else:
		host.exitShop()
		updateAllUI()

func open_shop(reference: Variant) -> void:
	if isUIOpen():
		return
	var owner: String = bridge.component_owner(reference)
	for script in SHOP_SCRIPTS:
		if owner == _panel(script):
			audio.PlayMusic("ShopMusic")
			_set_panel(script, true)
			return
	push_error("Shop trigger references no original shop: " + owner)

func _open_guarded(script: String) -> void:
	if not script_components.has(script) or not host.player_alive or isUIOpen():
		return
	host.enterShop()
	if script == "InventoryUIManager":
		_update_inventory()
	_set_panel(script, true)
	if script == "OptionsUIManager":
		var p: Dictionary = _properties(script)
		bridge.set_value(p.music_slider, data.music_volume)
		bridge.set_value(p.sound_slider, data.sound_volume)

func open_inventory() -> void:
	_open_guarded("InventoryUIManager")

func open_options() -> void:
	_open_guarded("OptionsUIManager")

func _close_panel(script: String) -> void:
	if SHOP_SCRIPTS.has(script):
		if script == "UpgradeShopUI":
			current_category = ""
			current_potential_upgrade = ""
		_set_panel(script, false)
		audio.PlayMusic("MainLevelMusic")
		data.saveData()
		return
	if script == "TransmissionManager":
		var bonus: int = 0
		match current_transmission_index:
			1: bonus = 1000
			2: bonus = 3000
			7: bonus = 25000
		if bonus != 0:
			host.createPopup("Bonus\n+$" + str(bonus), "IsMineral")
			data.player_money += bonus
			audio.PlaySoundOneShot("Purchase")
		current_transmission_index = 0
	# Main-menu instructions have the same broken HelpUUIManager with null player;
	# its dedicated close button targets MainMenuManager instead. Keep that error
	# explicit rather than treating it as a valid gameplay pause target.
	if not _properties(script).has("player") or bridge.reference_id(_properties(script).get("player", {})) == "0":
		push_error("Original " + script + ".closeUI has no player reference")
		return
	host.exitShop()
	_set_panel(script, false)
	if script == "OptionsUIManager":
		var p: Dictionary = _properties(script)
		data.saveVolumeLevels(bridge.get_value(p.music_slider), bridge.get_value(p.sound_slider))
		data.setVolumeLevels()
		audio.setNewVolumeLevels()

func startNewGame() -> void:
	if host.is_coop:
		host.coop.network.join_world()
		return
	var p: Dictionary = _properties("MainMenuManager")
	if not _active(p.helpUI):
		audio.PlaySoundOneShot("SelectUpgradeCategory")
		data.setNewGameData()
		host.change_scene("Game")

func continueGame() -> void:
	if host.is_coop:
		return
	var p: Dictionary = _properties("MainMenuManager")
	if _active(p.helpUI):
		return
	if data.doesSaveFileExist():
		audio.PlaySoundOneShot("SelectUpgradeCategory")
		if data.loadData():
			host.change_scene("Game")
		else:
			_open_popup(p.popup, "Unable to load save game.", false)
	else:
		_open_popup(p.popup, "No save game present on disk!", false)

func openInstructions() -> void:
	audio.PlaySoundOneShot("SelectUpgradeCategory")
	bridge.set_active(_properties("MainMenuManager").helpUI, true)

func closeInstructions() -> void:
	audio.PlaySoundOneShot("SelectUpgradeCategory")
	bridge.set_active(_properties("MainMenuManager").helpUI, false)

func returnToMainMenu() -> void:
	if host.is_coop:
		if not host.leave_coop():
			return
		host.coop.lobby.show_lobby()
	host.paused = false
	audio.StopAllMusic()
	audio.StopAllSounds()
	host.change_scene("MainMenu")

func updateAllUI() -> void:
	if not script_components.has("UIManager"):
		return
	updateMoneyUI()
	updateFuelUI()
	updateHullUI()
	updateDepthUI()

func updateMoneyUI() -> void:
	_text(_properties("UIManager").MoneyUI, "$" + _grouped(displayed_money))

func updateFuelUI() -> void:
	var percent: int = maxi(ceili(host.unity_random.single(host.unity_random.single(data.player_fuel / data.player_max_fuel) * 100.0)), 0)
	if percent == previous_fuel_percent:
		return
	previous_fuel_percent = percent
	var p: Dictionary = _properties("UIManager")
	# The original constructs its sprite list in descending resource-name order.
	if percent > 100:
		push_error("Original fuel sprite index out of range: " + str(percent))
		return
	_resource_image(p.FuelUI, "UI/HUD/FuelSprite/" + str(100 - percent))
	if percent > 20:
		if is_low_fuel_playing:
			audio.StopSound("LowFuelWarning")
			bridge.set_active(p.low_fuel_text, false)
			is_low_fuel_playing = false
		if is_very_low_fuel_playing:
			audio.StopSound("VeryLowFuelWarning")
			bridge.set_active(p.very_low_fuel_text, false)
			is_very_low_fuel_playing = false
	elif percent > 7:
		if not is_low_fuel_playing:
			audio.PlaySound("LowFuelWarning")
			bridge.set_active(p.low_fuel_text, true)
			is_low_fuel_playing = true
		if is_very_low_fuel_playing:
			audio.StopSound("VeryLowFuelWarning")
			bridge.set_active(p.very_low_fuel_text, false)
			is_very_low_fuel_playing = false
	else:
		if is_low_fuel_playing:
			audio.StopSound("LowFuelWarning")
			bridge.set_active(p.low_fuel_text, false)
			is_low_fuel_playing = false
		if not is_very_low_fuel_playing:
			audio.PlaySound("VeryLowFuelWarning")
			bridge.set_active(p.very_low_fuel_text, true)
			is_very_low_fuel_playing = true

func updateHullUI() -> void:
	var percent: int = maxi(ceili(float(data.player_hp) / float(data.player_max_hp) * 20.0), 0)
	if percent != previous_hull_percent:
		previous_hull_percent = percent
		if percent > 20:
			push_error("Original hull sprite index out of range: " + str(percent))
			return
		_resource_image(_properties("UIManager").HullUI, "UI/HUD/HullSprite/" + str(20 - percent))

func updateDepthUI() -> void:
	var p: Dictionary = _properties("UIManager")
	if bridge.node(p.get("player", {})) == null:
		return
	var depth: int = floori((host.player_position.y + 3.5) * 12.5)
	if depth > -5800:
		_text(p.DepthUI, str(depth) + " ft.")
	elif depth > -7300:
		_text(p.DepthUI, "?" + str(host.unity_random.range_int(10000, 99999)) + " ft.")
	else:
		_text(p.DepthUI, "-66666 ft.")

func _update_inventory() -> void:
	var p: Dictionary = _properties("InventoryUIManager")
	var percent: int = _round_even(float(data.player_current_cargo_weight) / float(data.player_max_cargo_weight) * 100.0)
	_text(p.cargo_text, "Cargo " + str(percent) + "% full\n" + str(data.player_total_weight) + " Kg")
	for category in data.current_upgrades:
		_text(_child(p.equipment, category), str(data.current_upgrades[category]))
	for item in data.player_items:
		var picture: String = _child(p.equipment, item)
		var quantity: int = int(data.player_items[item])
		_image_alpha(picture, 0.25 if quantity <= 0 else 1.0)
		_text(_child(picture, "Quantity"), "" if quantity <= 0 else "x" + str(quantity))
	for mineral in data.player_cargo:
		var line: String = _child(p.minerals_list, mineral)
		var quantity: int = int(data.player_cargo[mineral])
		_image_alpha(_child(line, "Image"), 0.25 if quantity <= 0 else 1.0)
		_text(_child(line, "Quantity"), "" if quantity <= 0 else "x" + str(quantity))
		_text(_child(line, "Name"), "" if quantity <= 0 else str(mineral))
		bridge.set_active(_child(line, "Image/DropButton"), quantity > 0)

func dropMineral(mineral_name: String) -> void:
	data.removeMineralInCargo(mineral_name)
	audio.PlaySoundOneShot("JettisonMineral")
	_update_inventory()

func _upgrade_open_display() -> void:
	var p: Dictionary = _properties("UpgradeShopUI")
	bridge.set_active(p.welcome_ui, true)
	bridge.set_active(p.upgrade_display, false)
	bridge.set_active(p.upgrade_grid_area, false)
	current_category = ""
	current_potential_upgrade = ""
	_text(p.current_category_display, current_category)
	_slow(p.potential_upgrade_name, current_potential_upgrade)

func displayCategory(category: String) -> void:
	if category != current_category:
		current_category = category
		updateCategory()
		audio.PlaySoundOneShot("SelectUpgradeCategory")

func updateCategory() -> void:
	var p: Dictionary = _properties("UpgradeShopUI")
	bridge.set_active(p.welcome_ui, false)
	bridge.set_active(p.upgrade_display, true)
	bridge.set_active(p.upgrade_grid_area, true)
	_text(p.current_category_display, "FUEL TANK" if current_category == "Fuel" else current_category.to_upper())
	_resource_image(p.current_upgrade_display, "UI/upgradesShop/" + current_category + "/" + str(data.current_upgrades[current_category]))
	_slow(p.current_upgrade_name, str(data.current_upgrades[current_category]))
	var pictures: Array = p.potential_upgrade_pictures
	var names: Array = UPGRADE_NAMES[current_category]
	for index in range(pictures.size()):
		var enabled: bool = index <= names.size() - 2
		bridge.set_active(pictures[index], enabled)
		if enabled:
			_resource_image(pictures[index], "UI/upgradesShop/" + current_category + "/" + str(names[index + 1]))
	_slow(p.potential_upgrade_name, "")
	_slow(p.potential_upgrade_price, "")
	_slow(p.potential_upgrade_effect, "")

func displayPotentialUpgrade(upgrade_index: int) -> void:
	current_potential_upgrade = UPGRADE_NAMES[current_category][upgrade_index]
	var p: Dictionary = _properties("UpgradeShopUI")
	var upgrade: Dictionary = data.upgrades[current_category][current_potential_upgrade]
	_slow(p.potential_upgrade_name, current_potential_upgrade)
	_slow(p.potential_upgrade_price, "$" + _grouped(int(upgrade.price)))
	_slow(p.potential_upgrade_effect, _number(float(upgrade.effect) * float(EFFECT_MULTIPLIERS[current_category])) + str(EFFECT_UNITS[current_category]))
	audio.PlaySoundOneShot("SelectUpgrade")

func buyUpgrade() -> void:
	# Do not invent a default selection: Unity errors if Buy is pressed before one.
	var upgrade: Dictionary = data.upgrades[current_category][current_potential_upgrade]
	if float(upgrade.effect) <= float(data.upgrades[current_category][data.current_upgrades[current_category]].effect):
		_shop_popup("UpgradeShopUI", "The upgrade you are trying to buy is not better than the one you currently have.")
		audio.PlaySoundOneShot("Error2")
	elif data.tryToBuy(int(upgrade.price)):
		data.setUpgrade(current_category, current_potential_upgrade)
		updateCategory()
		updateAllUI()
		audio.PlaySoundOneShot("Purchase")
		if current_category == "Fuel":
			data.player_fuel = data.player_max_fuel
			updateFuelUI()
		elif current_category == "Hull":
			data.player_hp = data.player_max_hp
			updateHullUI()
	else:
		_shop_popup("UpgradeShopUI", "You need $" + str(upgrade.price) + " to purchase")
		audio.PlaySoundOneShot("Error2")
	updateMoneyUI()

func _update_fuel_bar() -> void:
	var p: Dictionary = _properties("FuelShopManager")
	bridge.set_value(p.fuel_display_bar, data.player_fuel / data.player_max_fuel)
	_text(p.fuel_display_text, str(int(data.player_fuel)) + "/" + str(int(data.player_max_fuel)) + " L")

func addFuel(dollar_amount: int) -> void:
	if data.player_fuel == data.player_max_fuel:
		_shop_popup("FuelShopManager", "Tank is full!")
		audio.PlaySoundOneShot("Error2")
	elif data.tryToBuy(dollar_amount):
		data.addFuel(dollar_amount)
		audio.PlaySoundOneShot("Purchase")
	else:
		_shop_popup("FuelShopManager", "You need $" + str(dollar_amount) + " to purchase")
		audio.PlaySoundOneShot("Error2")
	updateMoneyUI()
	updateFuelUI()
	_update_fuel_bar()

func fillFuel() -> void:
	addFuel(ceili(data.player_max_fuel - data.player_fuel))

func _item_open_display() -> void:
	var p: Dictionary = _properties("ItemShopManager")
	_slow(p.item_name_text, "")
	_slow(p.item_price_text, "")
	_slow(p.item_description_text, "")
	_update_item_display()

func _update_item_display() -> void:
	updateHullBarDisplay()
	for reference in _properties("ItemShopManager").item_counter_object_list:
		_text(reference, "x" + str(data.player_items[_object_name(reference)]))

func updateHullBarDisplay() -> void:
	var p: Dictionary = _properties("ItemShopManager")
	bridge.set_value(p.hull_display_bar, float(data.player_hp) / float(data.player_max_hp))
	_text(p.hull_display_text, str(data.player_hp) + "/" + str(data.player_max_hp) + " HP")

func updateItemInformationScreen(item_name: String) -> void:
	currently_selected_item = item_name
	var item: Dictionary = data.items[item_name]
	var p: Dictionary = _properties("ItemShopManager")
	_slow(p.item_name_text, item_name)
	_slow(p.item_price_text, "$" + _grouped(int(item.price)) + "   (Press '" + str(item.button_to_press) + "' to use)")
	_slow(p.item_description_text, str(item.description))
	audio.PlaySoundOneShot("SelectUpgrade")

func buyItem() -> void:
	var price: int = int(data.items[currently_selected_item].price)
	if data.tryToBuy(price):
		data.addItem(currently_selected_item)
		audio.PlaySoundOneShot("Purchase")
	else:
		_shop_popup("ItemShopManager", "You need $" + str(price) + " to purchase")
		audio.PlaySoundOneShot("Error2")
	updateMoneyUI()
	_update_item_display()

func addHull(dollar_amount: int) -> void:
	if data.player_hp == data.player_max_hp:
		_shop_popup("ItemShopManager", "No damage to repair!")
		audio.PlaySoundOneShot("Error2")
	elif data.tryToBuy(dollar_amount):
		data.addHull(dollar_amount)
		audio.PlaySoundOneShot("Purchase")
	else:
		_shop_popup("ItemShopManager", "You need $" + str(dollar_amount) + " to purchase")
		audio.PlaySoundOneShot("Error2")
	updateMoneyUI()
	updateHullUI()
	_update_item_display()

func fillHull() -> void:
	addHull((data.player_max_hp - data.player_hp) * 15)

func _update_mineral_buyer() -> void:
	var grid: Variant = _properties("MineralBuyerManager").sell_mineral_grid_layout
	var total: int = 0
	for line in _children(grid):
		var mineral: String = _object_name(line)
		if mineral == "SeparatorLine" or mineral == "SellAllButton":
			continue
		var quantity: int = int(data.player_cargo[mineral])
		for child in _children(line):
			bridge.set_active(child, quantity > 0)
		if quantity > 0:
			var ore_value: int = int(data.minerals[mineral].ore_value)
			var ore_total: int = ore_value * quantity
			_text(_child(line, "Quantity"), str(quantity))
			_text(_child(line, "Value"), "$" + _grouped(ore_value))
			_text(_child(line, "TotalValue"), "$" + _grouped(ore_total))
			total += ore_total
	_text(_child(grid, "SellAllButton/TotalValue"), "$" + _grouped(total))

func sellAllMinerals() -> void:
	var total: int = data.sellCargo()
	updateMoneyUI()
	_update_mineral_buyer()
	_shop_popup("MineralBuyerManager", "Sold all minerals for $" + str(total))
	updateMoneyUI()
	audio.PlaySoundOneShot("SellMinerals")

func _shop_popup(script: String, value: String) -> void:
	_open_popup(_properties(script).popup_manager_gameobject, value, true)

func _open_popup(reference: Variant, value: String, use_slow_text: bool) -> void:
	var owner: String = bridge.component_owner(reference)
	var p: Dictionary = bridge.properties(owner, "PopupManager")
	if use_slow_text:
		_slow(p.text_container, value)
	else:
		_text(p.text_container, value)
	bridge.set_active(owner, true)

func openPopup(value: String) -> void:
	_open_popup(_component("PopupManager"), value, true)

func openPopupWithoutSlowTextDisplayer(value: String) -> void:
	_open_popup(_component("PopupManager"), value, false)

func closePopup() -> void:
	bridge.set_active(_component("PopupManager"), false)

func displayTransmission(index: int) -> void:
	var transmission: Dictionary = data.transmissions[index]
	if not bool(transmission.displayed):
		current_transmission_index = index
		updateText(str(transmission.text), str(transmission.signature))
		updatePortrait(str(transmission.picture_name))
		transmission.displayed = true
		host.enterShop()
		_set_panel("TransmissionManager", true)
		audio.PlaySoundOneShot("Transmission")

func updateText(value: String, signature: String) -> void:
	var display_text: String = "** Transmission Received **\n'" + signature + "'\n\n" + value + "\n\n** Transmission Terminated **"
	_slow(_properties("TransmissionManager").text_area, display_text)

func updatePortrait(portrait_name: String) -> void:
	var p: Dictionary = _properties("TransmissionManager")
	if portrait_name in ["miner", "natas", "static"]:
		bridge.set_active(p.portrait_miner, portrait_name == "miner")
		bridge.set_active(p.portrait_natas, portrait_name == "natas")
		bridge.set_active(p.portrait_static, portrait_name == "static")
