extends SceneTree

# Production lifecycle only. The frozen policy owns all controls and decisions;
# the real host owns the native clock, physics, world, mining and economy.
var _config: Dictionary = {}
var _classes: Dictionary = {}
var _host: Node
var _network: CoopClient
var _brain: RefCounted
var _round_id := ""
var _closing := false
var _exit_code := 0
var _close_at := 0
var _check_after := 0.0
var _reason := "starting"

func _initialize() -> void:
	Engine.max_fps = 50
	Engine.time_scale = 1.0
	auto_accept_quit = false
	var path := ""
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--worker-config="):
			path = argument.trim_prefix("--worker-config=")
	if not path.is_absolute_path() or not FileAccess.file_exists(path):
		_fail("missing_configuration")
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		_fail("invalid_configuration")
		return
	_config = parsed
	for field in ["state_dir", "token_file", "stop_file", "lease_file", "status_file"]:
		var value := str(_config.get(field, ""))
		if not value.is_absolute_path() or value.contains("://"):
			_fail("invalid_private_path")
			return
	_create_host.call_deferred()

func _create_host() -> void:
	if _closing:
		return
	var token_data: Variant = JSON.parse_string(FileAccess.get_file_as_string(str(_config.token_file)))
	if not token_data is Dictionary or str(token_data.get("token", "")).is_empty():
		_fail("missing_account_token")
		return
	var policy := load(get_script().resource_path.get_base_dir().path_join("policy.gd")) as Script
	if policy == null:
		_fail("policy_load_failed")
		return
	_classes = policy.get_script_constant_map()
	if not _classes.has("BotHost") or not _classes.has("BotBrain"):
		_fail("policy_interface_missing")
		return
	_host = _classes.BotHost.new()
	_set_private_data_paths()
	# agent_axes must remain null through _ready: this installs Box2DClock,
	# CoopSession and FuelPricing. Their children remain normally processed.
	root.add_child(_host)
	_host.set_process(false)
	_host.set_physics_process(false)
	if _host.coop == null or _host._physics_clock == null or _host.fuel_pricing == null:
		_fail("native_runtime_unavailable")
		return
	_network = _host.coop.network
	if _network.base_url != str(_config.endpoint) or _network.startup_mode != "private" or not _network.token.is_empty():
		_fail("startup_isolation_failed")
		return
	_network.token = str(token_data.token)
	_network.expires_at = int(token_data.expires_at)
	_network.username = str(_config.username)
	_network.mode = "pvp"
	_network.world_id = "public"
	_host.agent_axes = Vector2.ZERO
	_network.joined_world.connect(_joined)
	_network.connection_lost.connect(_connection_lost)
	_network.recovery_started.connect(_recovery_started)
	_network.auth_state_changed.connect(_auth_changed)
	_network.join_world()
	if not _network.connecting:
		_fail("join_not_started")

func _set_private_data_paths() -> void:
	_host.data.savefile = str(_config.state_dir).path_join("save.data")
	_host.data.settings_file = str(_config.state_dir).path_join("settings.json")

func _joined(snapshot: Dictionary) -> void:
	if _closing:
		return
	var next_round := str(snapshot.get("round_id", ""))
	if next_round.is_empty() or (not _round_id.is_empty() and (str(snapshot.get("type", "")) != "round_started" or next_round == _round_id)):
		_fail("invalid_round_identity")
		return
	# CoopSession's earlier joined handler has installed fresh native data/world.
	# Drop the entire old RefCounted brain, including weak event subscriptions,
	# routes, retaliation, bags and expedition memory. No policy reset shortcut.
	_brain = null
	_host.bot_control = Callable()
	_host.agent_axes = Vector2.ZERO
	_host.bot_attack_enabled = false
	_host.bot_attack_target = ""
	_host.set_process(false)
	_host.set_physics_process(false)
	_set_private_data_paths()
	_host.pending_scene = ""
	_host._load_scene("Game")
	_host.pending_scene = ""
	if not _network.connected or not _host.is_coop or not _host.data.pvp_mode or _host.player == null or _host.body == null:
		_fail("native_game_missing")
		return
	_round_id = next_round
	_brain = _classes.BotBrain.new(_host, int(_config.slot))
	_reason = "connected"
	_host.set_process(true)
	_host.set_physics_process(true)
	_status()
	print("PVP_BOT_CONNECTED slot=", int(_config.slot), " round=", _round_id)

func _connection_lost(_message: String) -> void:
	if not _closing:
		_fail("connection_lost")

func _recovery_started() -> void:
	# The authoritative pool, not the native human-client recovery loop, decides
	# whether a bot may reconnect after eviction or a broken transport.
	if not _closing:
		_close(1, "transport_lost")

func _auth_changed() -> void:
	if not _closing and _network.token.is_empty():
		_fail("auth_expired")

func _process(delta: float) -> bool:
	if _closing:
		if Time.get_ticks_msec() >= _close_at:
			quit(_exit_code)
		return false
	_check_after -= delta
	if _check_after <= 0.0 and not _config.is_empty():
		_check_after = 0.25
		if FileAccess.file_exists(str(_config.stop_file)):
			_close(0, "requested_stop")
			return false
		var lease_age := int(Time.get_unix_time_from_system()) - FileAccess.get_modified_time(str(_config.lease_file))
		if lease_age > 15 or lease_age < -15:
			_close(1, "supervisor_lease_expired")
			return false
		_status()
	# This is real elapsed SceneTree time, at a maximum of 50 FPS. No fixed-fps,
	# shared trial epoch, manual policy stepping or altered physics is involved.
	if _brain != null:
		_brain.tick(delta)
	return false

func _status() -> void:
	if not _config.has("status_file"):
		return
	var path := str(_config.status_file)
	var file := FileAccess.open(path + ".tmp", FileAccess.WRITE)
	if file == null:
		return
	file.store_string(JSON.stringify({"reason": _reason, "connected": not _closing and _network != null and _network.connected,
		"player_id": _network.player_id if _network != null else "", "round_id": _round_id,
		"updated_at": Time.get_unix_time_from_system()}))
	file.close()
	DirAccess.rename_absolute(path + ".tmp", path)

func _close(code: int, reason: String) -> void:
	if _closing:
		return
	_closing = true
	_exit_code = code
	_reason = reason
	_brain = null
	if _host != null:
		_host.agent_axes = Vector2.ZERO
		_host.bot_attack_enabled = false
		_host.set_process(false)
		_host.set_physics_process(false)
	if _network != null:
		_network.leave_world()
	_close_at = Time.get_ticks_msec() + 250
	_status()

func _fail(reason: String) -> void:
	if not _closing:
		printerr("PVP_BOT_ERROR ", reason)
		_close(1, reason)

func _notification(what: int) -> void:
	if what == Node.NOTIFICATION_WM_CLOSE_REQUEST:
		_close(0, "window_close")
