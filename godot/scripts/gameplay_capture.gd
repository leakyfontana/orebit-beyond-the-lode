class_name GameplayCapture
extends Node

# Captures human/replay runtime behavior, never the separate RL worker protocol.
# No account state or raw packets enter archives; capabilities stay in memory.
const STATE_FIELDS := ["x", "y", "vx", "vy", "fuel", "hp", "max_fuel", "max_hp", "money", "cargo_capacity", "alive", "paused", "facing", "in_shop", "digging", "grounded", "item_0", "item_1", "item_2", "item_3", "item_4", "item_5", "cargo_0", "cargo_1", "cargo_2", "cargo_3", "cargo_4", "cargo_5", "cargo_6", "cargo_7", "cargo_8", "cargo_9", "upgrade_0", "upgrade_1", "upgrade_2", "upgrade_3", "upgrade_4", "upgrade_5", "cargo_weight", "peer_0_present", "peer_0_x", "peer_0_y", "peer_0_facing", "peer_0_alive", "peer_1_present", "peer_1_x", "peer_1_y", "peer_1_facing", "peer_1_alive", "peer_2_present", "peer_2_x", "peer_2_y", "peer_2_facing", "peer_2_alive", "peer_3_present", "peer_3_x", "peer_3_y", "peer_3_facing", "peer_3_alive", "ui_panel_mask", "selected_shop_item", "selected_upgrade_category", "selected_upgrade_tier"]
const CATEGORIES := ["Drill", "Hull", "Engine", "Fuel", "Radiator", "Cargo"]
const COMMANDS := ["use_item", "buy_item", "buy_upgrade", "buy_fuel", "buy_hull", "sell_all", "drop_mineral", "shop_enter", "shop_exit"]
const MAX_QUEUE_BYTES := 8 * 1024 * 1024
const MAX_CHUNK_BYTES := 128 * 1024
const MAX_CHUNK_TRANSITIONS := 100
const SOURCE_PATHS := ["main.gd", "port_player.gd", "game_ui.gd", "coop_client.gd", "coop_session.gd", "world_data.gd", "game_data.gd", "gameplay_capture.gd"]

var host: Node
var session_id := ""
var capture_token := ""
var episode_id := ""
var uploaded_chunks := 0
var dropped_transitions := 0
var last_http_code := 0
var _session_chunks := 0
var _http: HTTPRequest
var _request_kind := ""
var _upload_body := PackedByteArray()
var _upload_session := ""
var _endpoint := ""
var _retry_at := 0
var _backoff := 1.0
var _build := ""
var _started_at_ms := 0
var _mode := "private"
var _actor := "human"
var _seed := 0
var _sequence := 0
var _chunk_index := 0
var _observation: Dictionary = {}
var _tick := 0
var _sample_usec := 0
var _last_flush_usec := 0
var _axes := [0.0, 0.0]
var _commands: Array = []
var _events: Array = []
var _last_server_event: Dictionary = {}
var _peer_slots: Array[WeakRef] = [null, null, null, null]
var _lines: Array[String] = []
var _line_bytes := 0
var _checkpoint: Dictionary = {}
var _queue: Array[Dictionary] = []
var _queue_bytes := 0
var _gap_first := -1
var _gap_last := -1
var _gap_episode := ""
var _closing := false

func configure(main_host: Node) -> void:
	host = main_host
	process_mode = Node.PROCESS_MODE_ALWAYS
	_http = HTTPRequest.new()
	_http.timeout = 10.0
	_http.body_size_limit = 4096
	_http.accept_gzip = not OS.has_feature("web")
	add_child(_http)
	_http.request_completed.connect(_completed)
	_build = GameplayCaptureBuild.SOURCE_SHA256
	var has_sources := true
	for path in SOURCE_PATHS:
		if not FileAccess.file_exists("res://scripts/" + path):
			has_sources = false
			break
	if has_sources:
		var source := HashingContext.new()
		source.start(HashingContext.HASH_SHA256)
		for path in SOURCE_PATHS:
			source.update(path.to_utf8_buffer())
			source.update(FileAccess.get_file_as_bytes("res://scripts/" + path))
		_build = source.finish().hex_encode()
	get_tree().auto_accept_quit = false

func credentials() -> Dictionary:
	if session_id.is_empty():
		return {}
	return {"capture_session": session_id, "capture_token": capture_token}

func begin_episode() -> void:
	if _closing or host.agent_axes != null or host.scene_name != "Game" or host.player == null:
		return
	finish("scene_change")
	episode_id = Crypto.new().generate_random_bytes(16).hex_encode()
	_sequence = 0
	_started_at_ms = int(Time.get_unix_time_from_system() * 1000.0)
	_mode = "vulcan" if host.data.vulcan_mode else ("pvp" if host.data.pvp_mode else ("coop" if host.is_coop else "private"))
	_actor = "replay" if host.replay_runner != null else "human"
	_peer_slots = [null, null, null, null]
	_seed = host.world.generation_seed
	_observation = _observe()
	_tick = host.physics_step
	_sample_usec = Time.get_ticks_usec()
	_last_flush_usec = _sample_usec
	_axes = [0.0, 0.0]
	if _mode != "private" and not _last_server_event.is_empty():
		_events.append(_last_server_event.duplicate())

func resolved_axes() -> void:
	if episode_id.is_empty():
		return
	var player: PortPlayer = host.player
	if host.paused or not host.player_alive or player.pvp_building_hidden:
		_axes = [0.0, 0.0]
	else:
		_axes = [clampf(player.moveX / maxf(host.data.player_horizontal_speed, 0.000001), -1.0, 1.0), clampf(player.moveY / maxf(host.data.player_vertical_speed, 0.000001), -1.0, 1.0)]

func command(kind: String, item: int = -1, amount: float = 0.0, category: int = -1) -> void:
	if episode_id.is_empty() or kind not in COMMANDS:
		return
	if _commands.size() >= 64:
		sample()
	_commands.append({"kind": kind, "item": item, "amount": amount, "category": category})

func server_event(sequence: int, source_session: String) -> void:
	if sequence <= 0 or source_session.length() != 32:
		return
	_last_server_event = {"kind": "server", "server_sequence": sequence, "session_id": source_session}
	if not episode_id.is_empty():
		if _events.size() >= 60:
			sample()
		_events.append(_last_server_event.duplicate())

func server_gap(source_session: String, first: int, last: int) -> void:
	if episode_id.is_empty() or source_session.length() != 32 or first < 0 or last < first:
		return
	if _events.size() >= 60:
		sample()
	_events.append({"kind": "server_gap", "session_id": source_session, "first_sequence": first, "last_sequence": last})

func life(alive: bool) -> void:
	if not episode_id.is_empty():
		_events.append({"kind": "life", "alive": alive})

func sample(only_changes: bool = false) -> void:
	if episode_id.is_empty() or not is_instance_valid(host.player):
		return
	var next_observation := _observe()
	var dead: bool = not host.player._alive and not host.data.pvp_mode and not host.data.vulcan_mode
	if only_changes and not dead and next_observation == _observation and _commands.is_empty() and _events.is_empty():
		return
	_record(next_observation, dead, false, "death" if dead else "running")
	if dead:
		_flush()
		episode_id = ""

func finish(reason: String = "scene_change") -> void:
	if episode_id.is_empty():
		return
	if is_instance_valid(host.player):
		var dead: bool = not host.player._alive and not host.data.pvp_mode and not host.data.vulcan_mode
		var terminal: bool = dead or (reason == "round_end" and host.data.pvp_mode)
		_record(_observe(), terminal, not terminal, "death" if dead else reason)
	_flush()
	episode_id = ""

func _record(next_observation: Dictionary, terminated: bool, truncated: bool, reason: String) -> void:
	var now := Time.get_ticks_usec()
	if _lines.is_empty():
		_checkpoint = {"sequence": _sequence, "tick": _tick, "observation": _observation}
	if _lines.is_empty() and _gap_first >= 0 and _gap_episode == episode_id:
		_events.append({"kind": "gap", "first_sequence": _gap_first, "last_sequence": _gap_last})
	_events.append({"kind": "timing", "elapsed_ms": maxi(0, int((now - _sample_usec) / 1000))})
	var before: Array = _observation.state
	var after: Array = next_observation.state
	var record := {"type": "transition", "sequence": _sequence, "tick": _tick, "next_tick": host.physics_step, "observation": _observation, "action": {"movement": _axes, "commands": _commands}, "next_observation": next_observation, "reward_components": {"money": after[8] - before[8], "hp": after[5] - before[5], "fuel": after[4] - before[4]}, "terminated": terminated, "truncated": truncated, "reason": reason, "events": _events}
	var line := JSON.stringify(record) + "\n"
	_lines.append(line)
	_line_bytes += line.length()
	_sequence += 1
	_observation = next_observation
	_tick = host.physics_step
	_sample_usec = now
	_commands = []
	_events = []
	if _lines.size() >= MAX_CHUNK_TRANSITIONS or _line_bytes >= MAX_CHUNK_BYTES or now - _last_flush_usec >= 2000000:
		_flush()

func _observe() -> Dictionary:
	var player: PortPlayer = host.player
	var data: GameData = host.data
	var position: Vector2 = player.position_unity
	var velocity: Vector2 = player.velocity_unity
	var state: Array = [position.x, position.y, velocity.x, velocity.y, data.player_fuel, data.player_hp, data.player_max_fuel, data.player_max_hp, data.player_money, data.player_max_cargo_weight, int(host.player_alive), int(host.paused), int(player.isFacingRight), int(player.is_in_shop), int(player.is_digging_bottom or player.is_digging_side), int(player.isOnGround)]
	for item in PortPlayer.ITEM_NAMES:
		state.append(int(data.player_items.get(item, 0)))
	for mineral in data.minerals_name_list:
		state.append(int(data.player_cargo.get(mineral, 0)))
	for category in CATEGORIES:
		state.append(data.upgrades[category].keys().find(data.current_upgrades[category]))
	state.append(data.player_current_cargo_weight)
	var tiles: Array[int] = []
	var center := Vector2i(floori(position.x), ceili(-position.y))
	var viewport := host.get_viewport()
	var screen: Transform2D = viewport.get_canvas_transform()
	var visible_rect: Rect2 = viewport.get_visible_rect()
	for y in range(center.y - 4, center.y + 5):
		for x in range(center.x - 4, center.x + 5):
			var visible := visible_rect.has_point(screen * Vector2(x + 0.5, y - 0.5))
			if not visible or not host.world.inBounds(x, y) or player.pvp_building_hidden:
				tiles.append(-1)
				continue
			var tile: Dictionary = host.world.getBlockData(x, y)
			var mineral: int = data.minerals_name_list.find(str(tile.name))
			var code := 2
			if tile.layer == "Traversable":
				code = 0
			elif mineral >= 0:
				code = 10 + mineral
			elif tile.name in ["Dirt", "Grass", "Half"]:
				code = 1
			elif tile.name == "Lava":
				code = 3
			elif tile.name == "Gas":
				code = 4
			tiles.append(code)
	state.append_array(_visible_peer_state(screen, visible_rect))
	var panel_mask := 0
	if host.ui != null:
		for index in GameUI.PANEL_SCRIPTS.size():
			var panel: String = GameUI.PANEL_SCRIPTS[index]
			if host.ui.script_components.has(panel) and host.ui._visible(host.ui._panel(panel)):
				panel_mask |= 1 << index
	state.append(panel_mask)
	var item_selected := -1
	var upgrade_category := -1
	var upgrade_tier := -1
	if (panel_mask & (1 << 2)) != 0:
		item_selected = data.items.keys().find(host.ui.currently_selected_item)
	if (panel_mask & (1 << 3)) != 0:
		upgrade_category = CATEGORIES.find(host.ui.current_category)
		if upgrade_category >= 0:
			upgrade_tier = data.upgrades[CATEGORIES[upgrade_category]].keys().find(host.ui.current_potential_upgrade)
	state.append_array([item_selected, upgrade_category, upgrade_tier])
	return {"state": state, "tiles": tiles}

func _visible_peer_state(screen: Transform2D, visible_rect: Rect2) -> Array:
	# Object references establish local slots only; network IDs/names never enter
	# observations. Offscreen/hidden actors contribute zeros, not remembered poses.
	if host.is_coop:
		for peer_id in host.coop._remote_visuals:
			var remote: Node2D = host.coop._remote_visuals[peer_id]
			if not _peer_visible(remote, screen, visible_rect):
				continue
			var assigned := false
			for reference in _peer_slots:
				if reference != null and reference.get_ref() == remote:
					assigned = true
					break
			if not assigned:
				for index in _peer_slots.size():
					if _peer_slots[index] == null or _peer_slots[index].get_ref() == null:
						_peer_slots[index] = weakref(remote)
						break
	var values: Array = []
	for reference in _peer_slots:
		var remote: Node2D
		if reference != null:
			remote = reference.get_ref() as Node2D
		if host.is_coop and _peer_visible(remote, screen, visible_rect):
			var pod := remote.get_node("Pod") as Node2D
			values.append_array([1, remote.global_position.x, -remote.global_position.y, int(pod.scale.x < 0.0), 1])
		else:
			values.append_array([0, 0, 0, 0, 0])
	return values

func _peer_visible(remote: Node2D, screen: Transform2D, visible_rect: Rect2) -> bool:
	if not is_instance_valid(remote) or not remote.is_visible_in_tree() or not visible_rect.has_point(screen * remote.global_position):
		return false
	var pod := remote.get_node_or_null("Pod") as Node2D
	return pod != null and pod.is_visible_in_tree()

func _flush() -> void:
	if _lines.is_empty():
		return
	var manifest := {"type": "manifest", "schema_version": 1, "session_id": "", "episode_id": episode_id, "chunk_index": _chunk_index, "mode": _mode, "actor": _actor, "seed": _seed, "physics_hz": 50, "build": _build, "engine": "%d.%d.%d" % [Engine.get_version_info().major, Engine.get_version_info().minor, Engine.get_version_info().patch], "state_fields": STATE_FIELDS, "checkpoint": _checkpoint, "started_at_ms": _started_at_ms, "source": "runtime_scripts_sha256", "terrain": "visible_local_9x9_v1"}
	var chunk := {"manifest": manifest, "lines": "".join(_lines), "bytes": _line_bytes, "first": int(_checkpoint.sequence), "last": _sequence - 1}
	# Retain the oldest unsent data (including an in-flight request). New loss is
	# explicit in the next surviving transition, never an invented terminal.
	if _queue.size() < 64 and _queue_bytes + _line_bytes <= MAX_QUEUE_BYTES:
		_queue.append(chunk)
		_queue_bytes += _line_bytes
		if _gap_episode == episode_id:
			_gap_first = -1
			_gap_last = -1
	else:
		dropped_transitions += _lines.size()
		if _gap_first < 0 or _gap_episode != episode_id:
			_gap_first = int(_checkpoint.sequence)
			_gap_episode = episode_id
		_gap_last = _sequence - 1
	_chunk_index += 1
	_lines.clear()
	_line_bytes = 0
	_checkpoint = {}
	_last_flush_usec = Time.get_ticks_usec()

func _process(_delta: float) -> void:
	if not _lines.is_empty() and Time.get_ticks_usec() - _last_flush_usec >= 2000000:
		_flush()
	if host == null or host.coop == null:
		return
	var endpoint: String = host.coop.network.base_url.trim_suffix("/")
	if endpoint != _endpoint:
		_http.cancel_request()
		_request_kind = ""
		session_id = ""
		capture_token = ""
		_upload_body = PackedByteArray()
		_upload_session = ""
		_session_chunks = 0
		_endpoint = endpoint
		_retry_at = 0
	if not _request_kind.is_empty() or Time.get_ticks_msec() < _retry_at or not host.coop.network.endpoint_is_secure():
		return
	# Menus contain no gameplay episode and must not allocate capture sessions.
	if session_id.is_empty() and episode_id.is_empty() and _queue.is_empty():
		return
	if session_id.is_empty():
		_request_kind = "session"
		var error := _http.request(_endpoint + "/api/captures/session", [], HTTPClient.METHOD_POST, "")
		if error != OK:
			_failed()
	elif not _queue.is_empty():
		_request_kind = "chunk"
		var chunk: Dictionary = _queue[0]
		chunk.manifest.session_id = session_id
		if _upload_body.is_empty() or _upload_session != session_id:
			_upload_body = (JSON.stringify(chunk.manifest) + "\n" + str(chunk.lines)).to_utf8_buffer().compress(FileAccess.COMPRESSION_GZIP)
			_upload_session = session_id
		var error := _http.request_raw(_endpoint + "/api/captures/" + session_id + "/chunks/" + str(chunk.manifest.chunk_index), ["Content-Type: application/gzip", "Authorization: Bearer " + capture_token], HTTPClient.METHOD_POST, _upload_body)
		if error != OK:
			_failed()

func _completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	last_http_code = code
	var kind := _request_kind
	_request_kind = ""
	if result != HTTPRequest.RESULT_SUCCESS or code < 200 or code >= 300:
		var quota_exhausted := false
		if code == 429 and kind == "chunk":
			var error_response: Variant = JSON.parse_string(body.get_string_from_utf8())
			quota_exhausted = error_response is Dictionary and error_response.get("error", "") == "capture_quota"
		if code in [401, 403] or quota_exhausted:
			session_id = ""
			capture_token = ""
		_failed()
		return
	if kind == "session":
		var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
		if not parsed is Dictionary or str(parsed.get("session_id", "")).length() != 32 or str(parsed.get("token", "")).is_empty():
			_failed()
			return
		session_id = str(parsed.session_id)
		capture_token = str(parsed.token)
		_session_chunks = 0
		host.coop.network.link_capture()
	elif kind == "chunk" and not _queue.is_empty():
		_queue_bytes -= int(_queue[0].bytes)
		_queue.pop_front()
		_upload_body = PackedByteArray()
		_upload_session = ""
		uploaded_chunks += 1
		_session_chunks += 1
		if _session_chunks >= 4000:
			session_id = ""
			capture_token = ""
			_session_chunks = 0
	_backoff = 1.0
	_retry_at = 0

func _failed() -> void:
	_request_kind = ""
	_retry_at = Time.get_ticks_msec() + int(_backoff * 1000.0)
	_backoff = minf(_backoff * 2.0, 60.0)

func _notification(what: int) -> void:
	if what in [NOTIFICATION_APPLICATION_PAUSED, NOTIFICATION_WM_WINDOW_FOCUS_OUT] and is_instance_valid(host):
		sample(true)
		_flush()
	if what == NOTIFICATION_WM_CLOSE_REQUEST and not _closing:
		_closing = true
		finish("shutdown")
		# Bounded grace only on deliberate window close; recording never waits
		# inside a gameplay update or blocks the render/physics thread.
		get_tree().create_timer(2.0, true, false, true).timeout.connect(func(): get_tree().quit())
