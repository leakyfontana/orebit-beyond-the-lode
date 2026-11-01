extends SceneTree

# The last process callback is the protocol barrier. Blocking here freezes both
# game clocks, after the native physics step and the host's render-side digging.
class EpisodeBoundary extends Node:
	var worker: SceneTree

	func _physics_process(delta: float) -> void:
		worker.call("_after_physics", delta)

	func _process(_delta: float) -> void:
		worker.call("_after_frame")

const PHYSICS_HZ := 50
const ACTION_TICKS := 5
const SETTLE_LIMIT := 150
const MODAL_RULE := "dismiss_transmissions_only"

var _socket := StreamPeerTCP.new()
var _incoming := PackedByteArray()
var _host: Node
var _config: Dictionary = {}
var _seed := 0
var _max_steps := 300
var _steps := 0
var _physics_ticks := 0
var _settle_ticks := 0
var _settle_frames := 0
var _stable_ticks := 0
var _decision_ticks := 0
var _awaiting_arrival := true
var _arrival_frames := 0
var _arrival_ship: CanvasItem
var _settling := true
var _terminal := false
var _closing := false
var _target := Vector2i(-1, -1)
var _start := Vector2.ZERO
var _backend_class := ""
var _reason := "running"

func _initialize() -> void:
	call_deferred("_boot")

func _boot() -> void:
	var arguments: Dictionary = {}
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--") and argument.contains("="):
			var separator: int = argument.find("=")
			arguments[argument.substr(2, separator - 2)] = argument.substr(separator + 1)
	var port: int = str(arguments.get("rl-port", "0")).to_int()
	var token: String = str(arguments.get("rl-token", ""))
	var config_path: String = str(arguments.get("rl-config", ""))
	if port <= 0 or port > 65535 or token.is_empty() or not config_path.is_absolute_path():
		_fail("Required worker arguments: --rl-config=<absolute JSON> --rl-port=<port> --rl-token=<token>")
		return
	if _socket.connect_to_host("127.0.0.1", port) != OK:
		_fail("Cannot connect to Python's loopback listener")
		return
	var deadline: int = Time.get_ticks_msec() + 10000
	while _socket.get_status() == StreamPeerTCP.STATUS_CONNECTING:
		_socket.poll()
		if Time.get_ticks_msec() >= deadline:
			_fail("Loopback connection timed out")
			return
		OS.delay_usec(1000)
	if _socket.get_status() != StreamPeerTCP.STATUS_CONNECTED or not _send({"token": token}):
		_shutdown(1)
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(config_path))
	if not parsed is Dictionary:
		_fail("RL config must be a JSON object")
		return
	_config = parsed
	if not _integer(_config.get("seed")) or not _integer(_config.get("max_steps", 300)) or int(_config.get("max_steps", 300)) <= 0:
		_fail("RL config requires integer seed and positive integer max_steps")
		return
	_seed = int(_config.seed)
	_max_steps = int(_config.get("max_steps", 300))
	if not arguments.has("seed") or str(arguments.seed).to_int() != _seed:
		_fail("--seed must match the RL config seed")
		return
	var directory: String = str(_config.get("directory", ""))
	if not directory.is_absolute_path() or not DirAccess.dir_exists_absolute(directory):
		_fail("RL config directory must be an existing absolute runtime directory")
		return
	var initial_fuel: Variant = _config.get("initial_fuel")
	if initial_fuel != null and (not _number(initial_fuel) or not is_finite(float(initial_fuel))):
		_fail("initial_fuel must be a finite number or null")
		return
	Engine.physics_ticks_per_second = PHYSICS_HZ
	Engine.max_physics_steps_per_frame = 1
	Engine.physics_jitter_fix = 0.0
	Engine.time_scale = 1.0
	_host = load("res://scripts/main.gd").new()
	# Set isolation before _ready can read settings, create UI, or configure co-op.
	_host.agent_axes = Vector2.ZERO
	_host.seed_value = _seed
	_host.data.savefile = directory.path_join("save.data")
	_host.data.settings_file = directory.path_join("settings.json")
	root.add_child(_host)
	_host.pending_scene = ""
	_host.data.setNewGameData()
	_host._load_scene("Game")
	if _host.player == null or _host.body == null:
		_fail("Game did not create the real player body")
		return
	_backend_class = _host.body.get_world_2d().direct_space_state.get_class()
	if _backend_class != "Box2DDirectSpaceState2D":
		_fail("RL requires the real Box2D backend; found " + _backend_class)
		return
	_host.data.resetCargo()
	_host.data.player_hp = _host.data.player_max_hp
	_host.data.player_fuel = _host.data.player_max_fuel
	_host.player.can_use_mouse_control = false
	_host.player.mouse_is_last_used_input = false
	for id in _host.bridge.scene.game_objects:
		if not _host.bridge.properties(str(id), "MotherShipManager").is_empty():
			_arrival_ship = _host.bridge.nodes[id]
			break
	var boundary := EpisodeBoundary.new()
	boundary.worker = self
	boundary.process_mode = Node.PROCESS_MODE_ALWAYS
	boundary.process_priority = 2147483647
	boundary.process_physics_priority = 2147483647
	root.add_child(boundary)
	print("OREBIT_RL backend=Box2D physics_hz=50 modal_rule=" + MODAL_RULE)

func _number(value: Variant) -> bool:
	return typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT

func _integer(value: Variant) -> bool:
	return _number(value) and is_finite(float(value)) and float(value) == floorf(float(value))

func _body_bounds() -> Rect2:
	var bounds := Rect2()
	var first := true
	for child in _host.body.get_children():
		if not child is CollisionShape2D or child.disabled or child.shape == null:
			continue
		var rectangle: Rect2 = child.shape.get_rect()
		for corner in [rectangle.position, Vector2(rectangle.end.x, rectangle.position.y), rectangle.end, Vector2(rectangle.position.x, rectangle.end.y)]:
			var point: Vector2 = child.transform * corner
			if first:
				bounds = Rect2(point, Vector2.ZERO)
				first = false
			else:
				bounds = bounds.expand(point)
	return bounds

func _select_spawn() -> bool:
	var bounds: Rect2 = _body_bounds()
	if bounds.size.x <= 0.0 or bounds.size.y <= 0.0:
		return false
	var detector: Node2D = _host.player.get("_bottom_target")
	if detector == null:
		return false
	var detector_offset: Vector2 = detector.global_position - _host.body.global_position
	# Row-major shallow scan, never rewriting terrain or granting cargo. The
	# actual collider bounds, not just the center tile, must fit a natural cavity.
	for y in range(6, 41):
		for x in range(1, int(_host.data.earthWidth) - 1):
			var tile: Dictionary = _host.world.getBlockData(x, y)
			if not _host.data.minerals_name_list.has(str(tile.name)):
				continue
			var position := Vector2(float(x) + 0.5 - detector_offset.x, float(y) - 1.0 - bounds.end.y - 0.04)
			if not _map_clear(Rect2(position + bounds.position, bounds.size).grow(0.01)):
				continue
			_host.terrain.follow(position * Vector2(1.0, -1.0))
			var pose := Transform2D(0.0, position)
			if not _physics_clear(pose):
				continue
			_target = Vector2i(x, y)
			_host.player.position_unity = position * Vector2(1.0, -1.0)
			_host.player.velocity_unity = Vector2.ZERO
			_host.body.sleeping = false
			_host.player.sync_physics_pose()
			_host.terrain.follow(_host.player.position_unity)
			return true
	return false

func _map_clear(rectangle: Rect2) -> bool:
	for y in range(ceili(rectangle.position.y), ceili(rectangle.end.y) + 1):
		for x in range(floori(rectangle.position.x), floori(rectangle.end.x) + 1):
			if not _host.world.inBounds(x, y):
				return false
			var tile: Dictionary = _host.world.getBlockData(x, y)
			if str(tile.layer) != "Traversable":
				return false
	return true

func _physics_clear(pose: Transform2D) -> bool:
	for child in _host.body.get_children():
		if not child is CollisionShape2D or child.disabled or child.shape == null:
			continue
		var query := PhysicsShapeQueryParameters2D.new()
		query.shape = child.shape
		query.transform = pose * child.transform
		query.collision_mask = 1
		query.collide_with_areas = false
		query.exclude = [_host.body.get_rid()]
		if not _host.body.get_world_2d().direct_space_state.intersect_shape(query, 1).is_empty():
			return false
	return true

func _after_physics(delta: float) -> void:
	if _closing or _host.paused or delta <= 0.0:
		return
	if absf(delta - 1.0 / float(PHYSICS_HZ)) > 0.000001:
		_fail("Worker received a non-fixed physics delta")
		return
	if _settling:
		_settle_ticks += 1
	else:
		_physics_ticks += 1

func _dismiss_transmission() -> void:
	if _host.ui != null and bool(_host.ui.panel_active.get("TransmissionManager", false)):
		_host.ui._close_panel("TransmissionManager")

func _after_frame() -> void:
	if _closing:
		return
	_dismiss_transmission()
	if _awaiting_arrival:
		_arrival_frames += 1
		if _host.scene_name != "Game":
			_fail("Game left its scene during arrival")
			return
		if _host.player_alive and not _host.paused and (_arrival_ship == null or not _arrival_ship.is_visible_in_tree()):
			if not _select_spawn():
				_fail("No collision-clear shallow natural mineral with room above it for the authored player body")
				return
			_awaiting_arrival = false
			_settle_ticks = 0
			_settle_frames = 0
			return
		if _arrival_frames >= 1000:
			_fail("Arrival did not produce a playable player within 20 simulated seconds")
		return
	if _settling:
		_settle_frames += 1
		if _host.scene_name != "Game" or not _host.player_alive:
			_fail("Player died or left Game while settling the natural spawn")
			return
		var velocity: Vector2 = _host.player.velocity_unity
		var detector_cell: Vector2i = _host.player.getBlockPositionBottomPlayer()
		if _settle_ticks >= 10 and _host.player.isOnGround and velocity.length() < 0.05 and detector_cell == _target and not _host.paused:
			_stable_ticks += 1
		else:
			_stable_ticks = 0
		if _stable_ticks >= 5:
			_finish_reset()
		elif _settle_frames >= SETTLE_LIMIT:
			_fail("Natural spawn did not settle grounded directly above target ore")
		return
	_decision_ticks += 1
	_reason = _terminal_reason()
	if _reason != "running" or _decision_ticks >= ACTION_TICKS:
		if _reason == "running" and _steps >= _max_steps:
			_reason = "timeout"
		_terminal = _reason != "running"
		var reward := -0.001
		if _reason == "success":
			reward += 1.0
		elif _reason in ["fuel", "death", "scene"]:
			reward -= 1.0
		if not _send({"observation": _observation(), "reward": reward, "terminated": _terminal and _reason != "timeout", "truncated": _reason == "timeout", "info": _info()}):
			_shutdown(1)
			return
		_read_command()

func _finish_reset() -> void:
	_settling = false
	_start = _host.player.position_unity
	_host.data.player_hp = _host.data.player_max_hp
	_host.data.player_fuel = float(_config.initial_fuel) if _config.get("initial_fuel") != null else float(_host.data.player_max_fuel)
	_host.ui.updateAllUI()
	if not _send({"observation": _observation(), "info": _info()}):
		_shutdown(1)
		return
	_read_command()

func _terminal_reason() -> String:
	if _host.scene_name != "Game" or (not str(_host.pending_scene).is_empty() and _host.pending_scene != "Game"):
		return "scene"
	if float(_host.data.player_fuel) <= 0.0:
		return "fuel"
	if not _host.player_alive or int(_host.data.player_hp) <= 0:
		return "death"
	for count in _host.data.player_cargo.values():
		if int(count) >= 1:
			return "success"
	return "running"

func _tile_category(x: int, y: int) -> int:
	if not _host.world.inBounds(x, y):
		return 0
	var tile: Dictionary = _host.world.getBlockData(x, y)
	var tile_name: String = str(tile.name)
	if str(tile.layer) == "Traversable":
		return 1
	if str(tile.layer) == "Invincible":
		return 7
	if _host.data.minerals_name_list.has(tile_name):
		return 3
	if tile_name == "Rock":
		return 4
	if tile_name == "Lava":
		return 5
	if tile_name == "Gas":
		return 6
	return 2

func _observation() -> Dictionary:
	var position: Vector2 = _host.player.position_unity if _host.player != null else _host.player_position
	var velocity: Vector2 = _host.player.velocity_unity if _host.player != null else Vector2.ZERO
	var center := Vector2i(floori(position.x), ceili(-position.y))
	var tiles: Array = []
	for y in range(center.y - 4, center.y + 5):
		var row: Array = []
		for x in range(center.x - 4, center.x + 5):
			row.append(_tile_category(x, y))
		tiles.append(row)
	var player: PortPlayer = _host.player
	return {
		"tiles": tiles, "tile_center": [center.x, center.y],
		"position": [position.x, position.y], "velocity": [velocity.x, velocity.y],
		"facing_right": player.isFacingRight if player != null else false,
		"grounded": player.isOnGround if player != null else false,
		"flying": player.isFlying if player != null else false,
		"digging": (player.is_digging_bottom or player.is_digging_side or player.isDigging) if player != null else false,
		"fuel": _host.data.player_fuel, "max_fuel": _host.data.player_max_fuel,
		"hp": _host.data.player_hp, "max_hp": _host.data.player_max_hp,
		"cargo_weight": _host.data.player_current_cargo_weight, "cargo_capacity": _host.data.player_max_cargo_weight,
		"cargo": _host.data.player_cargo.duplicate(), "scene": _host.scene_name, "paused": _host.paused,
	}

func _info() -> Dictionary:
	return {
		"seed": _seed, "steps": _steps, "physics_ticks": _physics_ticks,
		"simulated_seconds": float(_physics_ticks) / float(PHYSICS_HZ), "reason": _reason,
		"target_cell": [_target.x, _target.y], "start_position": [_start.x, _start.y],
		"backend": "Box2D", "backend_class": _backend_class, "physics_hz": PHYSICS_HZ,
		"modal_rule": MODAL_RULE,
	}

func _read_command() -> void:
	# No await/deferred callback here: no simulation is allowed while the client
	# thinks. TCP polling only wakes for complete newline-delimited commands.
	while not _closing:
		_socket.poll()
		if _socket.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			_shutdown(0)
			return
		var newline: int = _incoming.find(10)
		if newline >= 0:
			var line: String = _incoming.slice(0, newline).get_string_from_utf8()
			_incoming = _incoming.slice(newline + 1)
			var command: Variant = JSON.parse_string(line)
			if not command is Dictionary:
				_fail("Request must be a JSON object")
				return
			if command.get("command") == "close":
				_send({"closed": true})
				_shutdown(0)
				return
			if command.get("command") != "step":
				_fail("Unknown worker command")
				return
			if _terminal:
				_fail("Cannot step a terminal episode; reset starts a fresh worker")
				return
			var action: Variant = command.get("action")
			if not _integer(action) or int(action) < 0 or int(action) > 4:
				_fail("Action must be an integer from 0 to 4")
				return
			var axes := Vector2.ZERO
			match int(action):
				1: axes.x = -1.0
				2: axes.x = 1.0
				3: axes.y = 1.0
				4: axes.y = -1.0
			_host.agent_axes = axes
			# Physics precedes render input sampling. Replace movement immediately,
			# including IDLE, so the first fixed tick never reuses the prior action.
			if _host.player != null:
				_host.player._read_axes()
			_steps += 1
			_decision_ticks = 0
			return
		var available: int = _socket.get_available_bytes()
		if available > 0:
			var received: Array = _socket.get_partial_data(available)
			if received[0] != OK:
				_fail("TCP request read failed")
				return
			_incoming.append_array(received[1])
		else:
			OS.delay_usec(1000)

func _send(message: Dictionary) -> bool:
	if _socket.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		return false
	return _socket.put_data((JSON.stringify(message) + "\n").to_utf8_buffer()) == OK

func _fail(message: String) -> void:
	push_error(message)
	_send({"error": message})
	_shutdown(1)

func _shutdown(code: int) -> void:
	_closing = true
	_socket.disconnect_from_host()
	quit(code)
