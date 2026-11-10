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

enum EpisodeState { IDLE, ACTIVE, TERMINAL, TRUNCATED }
enum CloseState { OPEN, DRAINING, CLOSED }
enum InputState { EMPTY, COMMANDS, EVENTS, COMMANDS_AND_EVENTS }
enum PeerSlotState { VACANT, EXPIRED, RESERVED }
enum ChunkState { EMPTY, ASSEMBLING }
enum QueueState { EMPTY, RETAINED, UPLOADING_HEAD }
enum QueueAdmission { APPEND, DROP_NEWEST }
enum GapState { NONE, PENDING }
enum CapabilityState { UNALLOCATED, ACTIVE, RENEWAL_REQUIRED, ROTATION_REQUIRED }
enum HttpState { IDLE, ALLOCATING_SESSION, UPLOADING_CHUNK, BACKOFF }
enum UploadHeadState { EMPTY, CACHED_CURRENT_CAPABILITY, CACHED_PREVIOUS_CAPABILITY }

var host: Node
var session_id := ""
var capture_token := ""
var episode_id := ""
var uploaded_chunks := 0
var dropped_transitions := 0
var last_http_code := 0
var _session_chunks := 0
var _http: HTTPRequest
var _http_state: HttpState = HttpState.IDLE
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
var _gap_state: GapState = GapState.NONE
var _gap_first := 0
var _gap_last := -1
var _gap_episode := ""
var _episode_state: EpisodeState = EpisodeState.IDLE
var _close_state: CloseState = CloseState.OPEN
var _capability_state: CapabilityState = CapabilityState.UNALLOCATED

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
	if _capability_state != CapabilityState.ACTIVE:
		return {}
	return {"capture_session": session_id, "capture_token": capture_token}

func begin_episode() -> void:
	if _close_state != CloseState.OPEN or host.agent_axes != null or host.scene_name != "Game" or host.player == null:
		return
	finish("scene_change")
	episode_id = Crypto.new().generate_random_bytes(16).hex_encode()
	_episode_state = EpisodeState.ACTIVE
	_sequence = 0
	_started_at_ms = int(Time.get_unix_time_from_system() * 1000.0)
	_mode = "vulcan" if host.data.vulcan_mode else ("pvp" if host.data.pvp_mode else ("coop" if host.is_coop else "private"))
	_actor = "replay" if host.replay_runner != null else "human"
	_reset_peer_slots()
	_seed = host.world.generation_seed
	_observation = _observe()
	_tick = host.physics_step
	_sample_usec = Time.get_ticks_usec()
	_last_flush_usec = _sample_usec
	_axes = [0.0, 0.0]
	if _mode != "private" and not _last_server_event.is_empty():
		_append_event(_last_server_event.duplicate())

func resolved_axes() -> void:
	if _episode_state != EpisodeState.ACTIVE:
		return
	var player: PortPlayer = host.player
	if host.paused or not host.player_alive or player.pvp_building_hidden:
		_axes = [0.0, 0.0]
	else:
		_axes = [clampf(player.moveX / maxf(host.data.player_horizontal_speed, 0.000001), -1.0, 1.0), clampf(player.moveY / maxf(host.data.player_vertical_speed, 0.000001), -1.0, 1.0)]

func _input_state() -> InputState:
	if _commands.is_empty():
		return InputState.EMPTY if _events.is_empty() else InputState.EVENTS
	return InputState.COMMANDS if _events.is_empty() else InputState.COMMANDS_AND_EVENTS

func command(kind: String, item: int = -1, amount: float = 0.0, category: int = -1) -> void:
	if _episode_state != EpisodeState.ACTIVE or kind not in COMMANDS:
		return
	if _commands.size() >= 64:
		sample()
	_commands.append({"kind": kind, "item": item, "amount": amount, "category": category})

func _append_event(event: Dictionary) -> void:
	_events.append(event)

func _consume_transition_inputs() -> void:
	# Serialized transitions own these arrays; movement remains held until resolved.
	_commands = []
	_events = []

func server_event(sequence: int, source_session: String) -> void:
	if sequence <= 0 or source_session.length() != 32:
		return
	_last_server_event = {"kind": "server", "server_sequence": sequence, "session_id": source_session}
	if _episode_state == EpisodeState.ACTIVE:
		if _events.size() >= 60:
			sample()
		_append_event(_last_server_event.duplicate())

func server_gap(source_session: String, first: int, last: int) -> void:
	if _episode_state != EpisodeState.ACTIVE or source_session.length() != 32 or first < 0 or last < first:
		return
	if _events.size() >= 60:
		sample()
	_append_event({"kind": "server_gap", "session_id": source_session, "first_sequence": first, "last_sequence": last})

func life(alive: bool) -> void:
	if _episode_state == EpisodeState.ACTIVE:
		_append_event({"kind": "life", "alive": alive})

func sample(only_changes: bool = false) -> void:
	if _episode_state != EpisodeState.ACTIVE or not is_instance_valid(host.player):
		return
	var next_observation := _observe()
	var dead: bool = not host.player._alive and not host.data.pvp_mode and not host.data.vulcan_mode
	if only_changes and not dead and next_observation == _observation and _input_state() == InputState.EMPTY:
		return
	var outcome := EpisodeState.TERMINAL if dead else EpisodeState.ACTIVE
	_record(next_observation, outcome, "death" if dead else "running")
	if outcome == EpisodeState.TERMINAL:
		_end_episode(outcome)

func finish(reason: String = "scene_change") -> void:
	if _episode_state != EpisodeState.ACTIVE:
		return
	var outcome := EpisodeState.TRUNCATED
	if is_instance_valid(host.player):
		var dead: bool = not host.player._alive and not host.data.pvp_mode and not host.data.vulcan_mode
		outcome = EpisodeState.TERMINAL if dead or (reason == "round_end" and host.data.pvp_mode) else EpisodeState.TRUNCATED
		_record(_observe(), outcome, "death" if dead else reason)
	_end_episode(outcome)

func _end_episode(outcome: EpisodeState) -> void:
	_seal_chunk()
	_episode_state = outcome
	episode_id = ""

func _chunk_state() -> ChunkState:
	return ChunkState.EMPTY if _lines.is_empty() else ChunkState.ASSEMBLING

func _start_chunk() -> void:
	_checkpoint = {"sequence": _sequence, "tick": _tick, "observation": _observation}
	if _gap_state == GapState.PENDING and _gap_episode == episode_id:
		_append_event({"kind": "gap", "first_sequence": _gap_first, "last_sequence": _gap_last})

func _record(next_observation: Dictionary, outcome: EpisodeState, reason: String) -> void:
	var now := Time.get_ticks_usec()
	if _chunk_state() == ChunkState.EMPTY:
		_start_chunk()
	_append_event({"kind": "timing", "elapsed_ms": maxi(0, int((now - _sample_usec) / 1000))})
	var before: Array = _observation.state
	var after: Array = next_observation.state
	var record := {"type": "transition", "sequence": _sequence, "tick": _tick, "next_tick": host.physics_step, "observation": _observation, "action": {"movement": _axes, "commands": _commands}, "next_observation": next_observation, "reward_components": {"money": after[8] - before[8], "hp": after[5] - before[5], "fuel": after[4] - before[4]}, "terminated": outcome == EpisodeState.TERMINAL, "truncated": outcome == EpisodeState.TRUNCATED, "reason": reason, "events": _events}
	var line := JSON.stringify(record) + "\n"
	_lines.append(line)
	_line_bytes += line.length()
	_sequence += 1
	_observation = next_observation
	_tick = host.physics_step
	_sample_usec = now
	_consume_transition_inputs()
	if _lines.size() >= MAX_CHUNK_TRANSITIONS or _line_bytes >= MAX_CHUNK_BYTES or now - _last_flush_usec >= 2000000:
		_seal_chunk()

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
			if host.ui.script_components.has(panel) and host.ui.is_panel_visible(panel):
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

func _reset_peer_slots() -> void:
	_peer_slots.fill(null)

func _peer_slot_state(index: int) -> PeerSlotState:
	var reference: WeakRef = _peer_slots[index]
	if reference == null:
		return PeerSlotState.VACANT
	return PeerSlotState.EXPIRED if reference.get_ref() == null else PeerSlotState.RESERVED

func _bind_peer_slot(index: int, remote: Node2D) -> void:
	_peer_slots[index] = weakref(remote)

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
					var slot_state := _peer_slot_state(index)
					if slot_state == PeerSlotState.VACANT or slot_state == PeerSlotState.EXPIRED:
						_bind_peer_slot(index, remote)
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

func _queue_state() -> QueueState:
	if _queue.is_empty():
		return QueueState.EMPTY
	return QueueState.UPLOADING_HEAD if _http_state == HttpState.UPLOADING_CHUNK else QueueState.RETAINED

func _queue_admission(bytes: int) -> QueueAdmission:
	return QueueAdmission.APPEND if _queue.size() < 64 and _queue_bytes + bytes <= MAX_QUEUE_BYTES else QueueAdmission.DROP_NEWEST

func _append_chunk(chunk: Dictionary) -> void:
	_queue.append(chunk)
	_queue_bytes += int(chunk.bytes)
	if _gap_state == GapState.PENDING and _gap_episode == episode_id:
		_gap_state = GapState.NONE

func _drop_newest_chunk() -> void:
	dropped_transitions += _lines.size()
	if _gap_state == GapState.NONE or _gap_episode != episode_id:
		_gap_first = int(_checkpoint.sequence)
		_gap_episode = episode_id
	_gap_last = _sequence - 1
	_gap_state = GapState.PENDING

func _seal_chunk() -> void:
	if _chunk_state() == ChunkState.EMPTY:
		return
	var manifest := {"type": "manifest", "schema_version": 1, "session_id": "", "episode_id": episode_id, "chunk_index": _chunk_index, "mode": _mode, "actor": _actor, "seed": _seed, "physics_hz": 50, "build": _build, "engine": "%d.%d.%d" % [Engine.get_version_info().major, Engine.get_version_info().minor, Engine.get_version_info().patch], "state_fields": STATE_FIELDS, "checkpoint": _checkpoint, "started_at_ms": _started_at_ms, "source": "runtime_scripts_sha256", "terrain": "visible_local_9x9_v1"}
	var chunk := {"manifest": manifest, "lines": "".join(_lines), "bytes": _line_bytes, "first": int(_checkpoint.sequence), "last": _sequence - 1}
	# Retain the oldest unsent data (including an in-flight request). New loss is
	# explicit in the next surviving transition, never an invented terminal.
	match _queue_admission(_line_bytes):
		QueueAdmission.APPEND:
			_append_chunk(chunk)
		QueueAdmission.DROP_NEWEST:
			_drop_newest_chunk()
	_chunk_index += 1
	_lines.clear()
	_line_bytes = 0
	_checkpoint = {}
	_last_flush_usec = Time.get_ticks_usec()

func _discard_compressed_head() -> void:
	_upload_body = PackedByteArray()
	_upload_session = ""

func _upload_head_state() -> UploadHeadState:
	if _upload_body.is_empty():
		return UploadHeadState.EMPTY
	return UploadHeadState.CACHED_CURRENT_CAPABILITY if _upload_session == session_id else UploadHeadState.CACHED_PREVIOUS_CAPABILITY

func _invalidate_capability(next_state: CapabilityState) -> void:
	_capability_state = next_state
	session_id = ""
	capture_token = ""

func _change_endpoint(endpoint: String) -> void:
	_http.cancel_request()
	_http_state = HttpState.IDLE
	_invalidate_capability(CapabilityState.UNALLOCATED)
	_discard_compressed_head()
	_session_chunks = 0
	_endpoint = endpoint
	_retry_at = 0

func _process(_delta: float) -> void:
	if _chunk_state() == ChunkState.ASSEMBLING and Time.get_ticks_usec() - _last_flush_usec >= 2000000:
		_seal_chunk()
	if host == null or host.coop == null:
		return
	var endpoint: String = host.coop.network.base_url.trim_suffix("/")
	if endpoint != _endpoint:
		_change_endpoint(endpoint)
	if _http_state == HttpState.BACKOFF and Time.get_ticks_msec() >= _retry_at:
		_http_state = HttpState.IDLE
	if _http_state != HttpState.IDLE or not host.coop.network.endpoint_is_secure():
		return
	# Menus contain no gameplay episode and must not allocate capture sessions.
	if _capability_state != CapabilityState.ACTIVE:
		if _episode_state != EpisodeState.ACTIVE and _queue_state() == QueueState.EMPTY:
			return
		_request_session()
	elif _queue_state() != QueueState.EMPTY:
		_upload_head()

func _request_session() -> void:
	_http_state = HttpState.ALLOCATING_SESSION
	var error := _http.request(_endpoint + "/api/captures/session", [], HTTPClient.METHOD_POST, "")
	if error != OK:
		_enter_backoff()

func _upload_head() -> void:
	_http_state = HttpState.UPLOADING_CHUNK
	var chunk: Dictionary = _queue[0]
	chunk.manifest.session_id = session_id
	if _upload_head_state() != UploadHeadState.CACHED_CURRENT_CAPABILITY:
		_upload_body = (JSON.stringify(chunk.manifest) + "\n" + str(chunk.lines)).to_utf8_buffer().compress(FileAccess.COMPRESSION_GZIP)
		_upload_session = session_id
	var error := _http.request_raw(_endpoint + "/api/captures/" + session_id + "/chunks/" + str(chunk.manifest.chunk_index), ["Content-Type: application/gzip", "Authorization: Bearer " + capture_token], HTTPClient.METHOD_POST, _upload_body)
	if error != OK:
		_enter_backoff()

func _activate_capability(new_session: String, token: String) -> void:
	session_id = new_session
	capture_token = token
	_capability_state = CapabilityState.ACTIVE
	_session_chunks = 0
	host.coop.network.link_capture()

func _acknowledge_head() -> void:
	_queue_bytes -= int(_queue[0].bytes)
	_queue.pop_front()
	_discard_compressed_head()
	uploaded_chunks += 1
	_session_chunks += 1
	if _session_chunks >= 4000:
		_invalidate_capability(CapabilityState.ROTATION_REQUIRED)
		_session_chunks = 0

func _completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	last_http_code = code
	var completed_state := _http_state
	_http_state = HttpState.IDLE
	if result != HTTPRequest.RESULT_SUCCESS or code < 200 or code >= 300:
		var quota_exhausted := false
		if code == 429 and completed_state == HttpState.UPLOADING_CHUNK:
			var error_response: Variant = JSON.parse_string(body.get_string_from_utf8())
			quota_exhausted = error_response is Dictionary and error_response.get("error", "") == "capture_quota"
		if code in [401, 403] or quota_exhausted:
			_invalidate_capability(CapabilityState.RENEWAL_REQUIRED)
		_enter_backoff()
		return
	if completed_state == HttpState.ALLOCATING_SESSION:
		var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
		if not parsed is Dictionary or str(parsed.get("session_id", "")).length() != 32 or str(parsed.get("token", "")).is_empty():
			_enter_backoff()
			return
		_activate_capability(str(parsed.session_id), str(parsed.token))
	elif completed_state == HttpState.UPLOADING_CHUNK and _queue_state() != QueueState.EMPTY:
		_acknowledge_head()
	_backoff = 1.0
	_retry_at = 0

func _enter_backoff() -> void:
	_http_state = HttpState.BACKOFF
	_retry_at = Time.get_ticks_msec() + int(_backoff * 1000.0)
	_backoff = minf(_backoff * 2.0, 60.0)

func _flush_focus_sample() -> void:
	sample(true)
	_seal_chunk()

func _begin_close_drain() -> void:
	_close_state = CloseState.DRAINING
	finish("shutdown")
	# Bounded grace only on deliberate window close; recording never waits
	# inside a gameplay update or blocks the render/physics thread.
	get_tree().create_timer(2.0, true, false, true).timeout.connect(_complete_close_drain)

func _complete_close_drain() -> void:
	_close_state = CloseState.CLOSED
	get_tree().quit()

func _notification(what: int) -> void:
	if what in [NOTIFICATION_APPLICATION_PAUSED, NOTIFICATION_WM_WINDOW_FOCUS_OUT] and is_instance_valid(host):
		_flush_focus_sample()
	if what == NOTIFICATION_WM_CLOSE_REQUEST and _close_state == CloseState.OPEN:
		_begin_close_drain()
