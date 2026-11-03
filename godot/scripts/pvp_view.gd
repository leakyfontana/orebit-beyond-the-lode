class_name PvpView
extends Node

var host: Node
var network: CoopClient
var objects: Dictionary = {}
var respawn_at := 0.0
var server_time := 0.0
var last_hull := -1.0
var _respawn_root: Control
var _respawn_shade: ColorRect
var _respawn_panel: PanelContainer
var _respawn_margin: MarginContainer
var _respawn_body: VBoxContainer
var _respawn_title: Label
var _respawn_time: Label
var _respawn_detail: Label
var _respawn_footer: Label
var _respawn_progress: ProgressBar
var _last_respawn_seconds := -1
var building := ""
var building_pending := false
var building_request_id := ""
var _requested_building := ""
var _requested_enter := false
var _close_requested := false

func configure(main_host: Node, client: CoopClient) -> void:
	host = main_host
	network = client
	_build_respawn_overlay()

func scene_loaded(snapshot: Dictionary) -> void:
	objects.clear()
	building = ""
	_clear_building_request()
	apply_state(snapshot.get("state", {}))
	apply_event(snapshot)

func apply_state(state: Dictionary, full: bool = true) -> void:
	if host.player == null or host.scene_name != "Game":
		return
	var was_alive: bool = host.player_alive
	var alive := bool(state.get("alive", true))
	if full or alive != was_alive:
		host.data.restore_coop_state(state)
		host.data.player_hp = ceili(maxf(0.0, float(state.get("player_hp", host.data.player_hp))))
	elif float(state.get("player_hp", last_hull)) != last_hull:
		host.data.player_hp = ceili(maxf(0.0, float(state.get("player_hp", host.data.player_hp))))
	last_hull = float(state.get("player_hp", host.data.player_hp))
	respawn_at = float(state.get("respawn_at", 0.0))
	var position := Vector2(float(state.get("x", 5.5)), float(state.get("y", -3.5)))
	var next_building := str(state.get("building", "")) if alive else ""
	if not host.ui.SHOP_SCRIPTS.has(next_building):
		next_building = ""
	if alive and not next_building.is_empty():
		# Entry may win a race with a local exhaustion report. Interior
		# authority suspends fuel death, not life or the fuel balance: outside,
		# an unrefueled tank is exhausted normally by the next fixed update.
		host.player._pvp_fuel_death_pending = false
		host.player._pvp_fuel_death_sent = false
	if building != next_building:
		network._reset_motion_history()
		# Ordinary hull ticks must never rewind a moving living player. Only
		# leaving an authoritative interior corrects an existing life's pose.
		if alive and was_alive and not building.is_empty() and next_building.is_empty():
			host.player.position_unity = position
		building = next_building
	if not alive:
		host.coop.lobby.leaderboard.close()
		_clear_building_request()
		if was_alive:
			host.ui.sync_building_panel("")
			for panel in host.ui.PANEL_SCRIPTS:
				if bool(host.ui.panel_active.get(panel, false)):
					host.ui._set_panel(panel, false)
			host.player.exitShop()
	host.player.apply_pvp_life(alive, position)
	_refresh_building()
	if not alive:
		host.paused = false
	host.ui.updateAllUI()
	_update_respawn_overlay()

func _clear_building_request() -> void:
	building_pending = false
	building_request_id = ""
	_requested_building = ""
	_requested_enter = false
	_close_requested = false

func request_building(script: String, enter: bool) -> void:
	if not host.ui.SHOP_SCRIPTS.has(script):
		return
	if not network.connected or not host.player_alive or host.player._pvp_fuel_death_pending:
		host.ui.sync_building_panel(building)
		return
	if building_pending:
		if not enter and _requested_enter and script == _requested_building:
			_close_requested = true
		_refresh_building()
		return
	if (enter and building == script) or (not enter and building.is_empty()):
		_refresh_building()
		return
	building_pending = true
	_requested_building = script
	_requested_enter = enter
	_submit_building()
	_refresh_building()

func _submit_building() -> void:
	if not building_pending or not building_request_id.is_empty() or network.has_pending_actions():
		return
	# Flush the current position/purchases before either authority transition.
	network.send_state()
	building_request_id = network.pvp_action("building", {"building": _requested_building, "enter": _requested_enter})

func building_result(event: Dictionary) -> void:
	if not building_pending or building_request_id.is_empty() or str(event.get("request_id", "")) != building_request_id:
		return
	if str(event.get("building", "")) != _requested_building or bool(event.get("enter", false)) != _requested_enter:
		return
	var close_after_entry := _close_requested and _requested_enter and bool(event.get("accepted", false))
	var script := _requested_building
	_clear_building_request()
	# The preceding state_sync owns life, position and economy. Never apply
	# the duplicate result snapshot (it would spend/credit local deltas twice).
	_refresh_building()
	if not bool(event.get("accepted", false)):
		network.status_changed.emit(str(event.get("message", "Unable to use this building.")))
	if close_after_entry and building == script:
		request_building(script, false)

func _refresh_building() -> void:
	var protected: bool = host.player_alive and (building_pending or not building.is_empty())
	var panel := building
	if protected and panel.is_empty() and building_pending:
		panel = _requested_building
	var panels_match := true
	for script in host.ui.SHOP_SCRIPTS:
		if bool(host.ui.panel_active.get(script, false)) != (script == panel):
			panels_match = false
	if not panels_match:
		host.ui.sync_building_panel(panel)
	var was_hidden: bool = host.player.pvp_building_hidden
	host.player.set_pvp_building_hidden(protected)
	if protected:
		host.player.enterShop()
	elif was_hidden:
		host.player.exitShop()

func apply_event(event: Dictionary) -> void:
	if host.scene_name != "Game" or host.player == null:
		return
	server_time = maxf(server_time, float(event.get("server_time", server_time)))
	for peer in event.get("players", []):
		if str(peer.player_id) == network.player_id:
			apply_state(peer.get("state", {}), false)
	var changed: Array[Vector2i] = []
	for cell in event.get("terrain_changes", []):
		var x := int(cell[0])
		var y := int(cell[1])
		var raw: Array = host.world.getRawTile(x, y)
		if not raw.is_empty() and int(raw[0]) != int(cell[2]):
			raw[0] = int(cell[2])
			# Empty tunnel sprites include borders from all eight neighbors.
			# Detaching a hazard must redraw those borders just like excavation.
			changed.append_array(host.world.digBlock(x, y))
	if not changed.is_empty():
		host.refresh_tiles(changed)
	var present: Dictionary = {}
	for kind in ["bags", "falling", "impacts"]:
		for record in event.get(kind, []):
			# Local presentation can reach expiry before the next server tick.
			# Do not resurrect that residue on the sheet's intact first frame.
			if kind == "impacts" and float(record.expires_at) <= server_time:
				continue
			var key: String = kind + str(record.id)
			present[key] = true
			if not objects.has(key):
				var sprite := Sprite2D.new()
				sprite.name = "MoneyBag" if kind == "bags" else ("HazardImpact" if kind == "impacts" else "FallingHazard")
				sprite.z_index = 15
				sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
				sprite.scale = Vector2.ONE / 50.0
				if kind == "bags":
					sprite.texture = load("res://assets/money_bag.png")
				elif kind == "impacts":
					sprite.texture = load("res://assets/rock_breaking.png" if int(record.tile) <= 27 else "res://assets/lava_splash.png")
					sprite.hframes = 8
					sprite.set_meta("started_at", float(record.started_at))
					sprite.set_meta("expires_at", float(record.expires_at))
				else:
					var tile_number := int(record.tile)
					var filename := ("Rock" + str(tile_number - 24)) if tile_number <= 27 else ("Lava" + str(tile_number - 27))
					var source := host.terrain.tile_layer.tile_set.get_source(0) as TileSetAtlasSource
					var texture := AtlasTexture.new()
					texture.atlas = source.texture
					texture.region = Rect2(source.get_tile_texture_region(host.terrain.tile_coordinates[filename]))
					sprite.texture = texture
				host.world_root.add_child(sprite)
				objects[key] = sprite
			objects[key].position = Vector2(float(record.x), -float(record.y))
			if kind == "impacts":
				_update_impact_pose(objects[key])
	for key in objects.keys():
		if not present.has(key):
			if is_instance_valid(objects[key]):
				objects[key].hide()
				objects[key].queue_free()
			objects.erase(key)

func tick(delta: float) -> void:
	server_time += delta
	_submit_building()
	for key in objects.keys():
		var sprite: Sprite2D = objects[key]
		if not is_instance_valid(sprite) or not sprite.has_meta("started_at"):
			continue
		if server_time >= float(sprite.get_meta("expires_at")):
			sprite.hide()
			sprite.queue_free()
			objects.erase(key)
			continue
		_update_impact_pose(sprite)
	_update_respawn_overlay()

func _update_impact_pose(sprite: Sprite2D) -> void:
	var age := maxf(0.0, server_time - float(sprite.get_meta("started_at")))
	sprite.frame = mini(7, floori(age / 0.4 * 8.0))
	# Only visibility changes once the animation has reached its broken pose.
	var blink_age := maxf(0.0, age - 0.4)
	var blink_phase := 2.0 * blink_age + 2.5 * blink_age * blink_age
	sprite.visible = age < 0.4 or fmod(blink_phase, 1.0) < 0.55

func hide_respawn() -> void:
	_respawn_root.hide()
	_last_respawn_seconds = -1

func _build_respawn_overlay() -> void:
	var layer := CanvasLayer.new()
	layer.name = "RespawnOverlay"
	layer.layer = 100
	layer.process_mode = Node.PROCESS_MODE_ALWAYS
	add_child(layer)
	_respawn_root = Control.new()
	_respawn_root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_respawn_root.mouse_filter = Control.MOUSE_FILTER_STOP
	layer.add_child(_respawn_root)
	_respawn_shade = ColorRect.new()
	_respawn_shade.color = Color(0.0, 0.0, 0.0, 0.48)
	_respawn_shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_respawn_shade.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_respawn_root.add_child(_respawn_shade)
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_respawn_root.add_child(center)
	_respawn_panel = PanelContainer.new()
	# Reuse the original options menu's metal bezel and green CRT glass.
	var frame := StyleBoxTexture.new()
	frame.texture = preload("res://assets/Resources/UI/OptionsUI/269.png")
	for side in [SIDE_LEFT, SIDE_TOP, SIDE_RIGHT, SIDE_BOTTOM]:
		frame.set_texture_margin(side, 24.0)
		frame.set_content_margin(side, 12.0)
	_respawn_panel.add_theme_stylebox_override("panel", frame)
	center.add_child(_respawn_panel)
	_respawn_margin = MarginContainer.new()
	var screen := PanelContainer.new()
	var glass := StyleBoxTexture.new()
	glass.texture = preload("res://assets/Resources/UI/OptionsUI/280.png")
	for side in [SIDE_LEFT, SIDE_TOP, SIDE_RIGHT, SIDE_BOTTOM]:
		glass.set_texture_margin(side, 32.0)
	screen.add_theme_stylebox_override("panel", glass)
	screen.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_respawn_panel.add_child(screen)
	screen.add_child(_respawn_margin)
	_respawn_body = VBoxContainer.new()
	_respawn_margin.add_child(_respawn_body)
	_respawn_label("VEHICLE RECOVERY", 16, Color("c4c3ad"))
	_respawn_title = _respawn_label("Rebuilding your craft", 26, Color("24c51c"))
	_respawn_time = _respawn_label("", 68, Color("fff000"))
	_respawn_progress = ProgressBar.new()
	_respawn_progress.max_value = 10.0
	_respawn_progress.show_percentage = false
	_respawn_progress.custom_minimum_size.y = 14
	_respawn_progress.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var track := StyleBoxFlat.new()
	track.bg_color = Color("11190e")
	track.border_color = Color("77786a")
	track.set_border_width_all(2)
	_respawn_progress.add_theme_stylebox_override("background", track)
	var fill := StyleBoxFlat.new()
	fill.bg_color = Color("24b817")
	_respawn_progress.add_theme_stylebox_override("fill", fill)
	_respawn_body.add_child(_respawn_progress)
	_respawn_detail = _respawn_label("Full hull · Stock upgrades\nDropped cash, cargo and items stay in the mine.", 18, Color("dedac6"))
	_respawn_footer = _respawn_label("The world keeps moving while you rebuild.", 14, Color("b8b8a3"))
	get_viewport().size_changed.connect(_resize_respawn_overlay)
	_resize_respawn_overlay()
	hide_respawn()

func _respawn_label(text: String, size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_font_override("font", preload("res://assets/MyFonts/214_Arial Black.ttf"))
	label.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.9))
	label.add_theme_constant_override("shadow_offset_x", 1)
	label.add_theme_constant_override("shadow_offset_y", 2)
	label.add_theme_color_override("font_color", color)
	_respawn_body.add_child(label)
	return label

func _resize_respawn_overlay() -> void:
	var size := get_viewport().get_visible_rect().size
	var compact := size.y < 480 or size.x < 480
	_respawn_panel.custom_minimum_size.x = maxf(0, minf(620, size.x - 32))
	for side in ["left", "right"]:
		_respawn_margin.add_theme_constant_override("margin_" + side, 18 if compact else 28)
	for side in ["top", "bottom"]:
		_respawn_margin.add_theme_constant_override("margin_" + side, 12 if compact else 24)
	_respawn_body.add_theme_constant_override("separation", 6 if compact else 12)
	_respawn_title.add_theme_font_size_override("font_size", 20 if compact else 26)
	_respawn_time.add_theme_font_size_override("font_size", 48 if compact else 68)
	_respawn_detail.add_theme_font_size_override("font_size", 14 if compact else 18)
	_respawn_footer.add_theme_font_size_override("font_size", 12 if compact else 14)

func _update_respawn_overlay() -> void:
	var show_overlay: bool = host.is_coop and host.data.pvp_mode and host.scene_name == "Game" and not host.player_alive and not host.coop.lobby.modal
	_respawn_root.visible = show_overlay
	if not show_overlay:
		_last_respawn_seconds = -1
		return
	# Keep input blocked, but do not cover the original opening death sequence.
	# Its authored transition, not another timer, reveals the remaining countdown.
	var show_countdown: bool = not host.player.pvp_death_animation_active()
	_respawn_panel.visible = show_countdown
	_respawn_shade.visible = show_countdown
	var remaining := maxf(0, respawn_at - server_time)
	var seconds := ceili(remaining)
	_respawn_progress.value = clampf(10.0 - remaining, 0, 10)
	if seconds == _last_respawn_seconds:
		return
	_last_respawn_seconds = seconds
	_respawn_time.text = "%ds" % seconds if seconds > 0 else "..."
	_respawn_title.text = "Rebuilding your craft" if seconds > 0 else "Almost ready"
	_respawn_footer.text = "The world keeps moving while you rebuild." if seconds > 0 else "Waiting for the server to confirm your respawn."
