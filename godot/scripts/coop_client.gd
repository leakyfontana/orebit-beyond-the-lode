class_name CoopClient
extends Node

signal status_changed(message: String)
signal identity_changed
signal joined_world(snapshot: Dictionary)
signal connection_lost(message: String)
signal world_event(event: Dictionary)

const DEFAULT_URL := "https://play.arcmonkeyswelding.com/coop"
const SESSION_FILE := "user://orebit_coop_session.json"
var base_url := DEFAULT_URL
var world_id := "public"
var token := ""
var username := ""
var player_id := ""
var connected := false
var connecting := false
var peers: Dictionary = {}
var host: Node
var state_revision := 0
var _socket: WebSocketPeer
var _http: HTTPRequest
var _http_kind := ""
var _poll_token := ""
var _poll_after := 0.0
var _state_after := 0.0
var _join_sent := false
var _connect_elapsed := 0.0
var _sequence := 0
var _pending_mines: Dictionary = {}
var _mining_baseline: Dictionary = {}
var startup_mode := ""
var _last_usec := 0
var discord_url := ""

func configure(main_host: Node) -> void:
	host = main_host
	process_mode = Node.PROCESS_MODE_ALWAYS
	_http = HTTPRequest.new()
	_http.timeout = 20.0
	add_child(_http)
	_http.request_completed.connect(_http_completed)
	if FileAccess.file_exists(SESSION_FILE):
		var saved: Variant = JSON.parse_string(FileAccess.get_file_as_string(SESSION_FILE))
		if saved is Dictionary:
			token = str(saved.get("token", ""))
			username = str(saved.get("username", ""))
			base_url = str(saved.get("base_url", DEFAULT_URL))
	var arguments := Array(OS.get_cmdline_user_args())
	if OS.has_feature("web"):
		var query: Variant = JSON.parse_string(str(JavaScriptBridge.eval("JSON.stringify(Object.fromEntries(new URLSearchParams(window.location.search)))")))
		if query is Dictionary:
			for key in ["mode", "coop-url", "coop-world"]:
				if query.has(key):
					arguments.append("--" + key + "=" + str(query[key]))
	var saved_endpoint := base_url
	var explicit_token := false
	for argument in arguments:
		if str(argument).begins_with("--coop-url="):
			base_url = str(argument).trim_prefix("--coop-url=").trim_suffix("/")
		elif str(argument).begins_with("--coop-world="):
			world_id = str(argument).trim_prefix("--coop-world=")
		elif str(argument).begins_with("--coop-token="):
			token = str(argument).trim_prefix("--coop-token=")
			explicit_token = true
		elif str(argument).begins_with("--mode="):
			startup_mode = str(argument).trim_prefix("--mode=")
	if saved_endpoint != base_url and not explicit_token:
		token = ""
		username = ""

func endpoint_is_secure() -> bool:
	if base_url.begins_with("https://"):
		return true
	var local_url := RegEx.new()
	local_url.compile("^http://(127\\.0\\.0\\.1|localhost)(:[0-9]+)?(/|$)")
	return local_url.search(base_url) != null

func set_endpoint(endpoint: String) -> void:
	if base_url != endpoint:
		logout()
		base_url = endpoint
		_store_session()

func authenticate(kind: String, user: String, password: String) -> void:
	_request("/api/auth/" + kind, {"username": user, "password": password}, "native")

func discord_login() -> void:
	_request("/api/auth/discord/start", {}, "discord_start")

func logout() -> void:
	if not _http_kind.is_empty():
		_http.cancel_request()
		_http_kind = ""
	if not token.is_empty():
		var revocation := HTTPRequest.new()
		revocation.timeout = 20.0
		add_child(revocation)
		revocation.request_completed.connect(func(result: int, code: int, _headers: PackedStringArray, _body: PackedByteArray):
			if result != HTTPRequest.RESULT_SUCCESS or code != 200:
				status_changed.emit("Signed out locally, but the server could not revoke this session. Reconnect to the account service to revoke it.")
			revocation.queue_free()
		)
		var result := revocation.request(base_url + "/api/auth/logout", ["Content-Type: application/json", "Authorization: Bearer " + token], HTTPClient.METHOD_POST, "{}")
		if result != OK:
			revocation.queue_free()
			status_changed.emit("Signed out locally; server session revocation could not be sent.")
	token = ""
	username = ""
	_poll_token = ""
	discord_url = ""
	_store_session()
	identity_changed.emit()

func _store_session() -> void:
	var file := FileAccess.open(SESSION_FILE, FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify({"token": token, "username": username, "base_url": base_url}))

func _request(path: String, payload: Dictionary, kind: String) -> void:
	if not _http_kind.is_empty():
		status_changed.emit("An account request is already in progress.")
		return
	_http_kind = kind
	var result := _http.request(base_url.trim_suffix("/") + path, ["Content-Type: application/json"], HTTPClient.METHOD_POST, JSON.stringify(payload))
	if result != OK:
		_http_kind = ""
		status_changed.emit("Unable to contact account service: " + error_string(result))
	else:
		status_changed.emit("Contacting account service…")

func _http_completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var kind := _http_kind
	_http_kind = ""
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or not parsed is Dictionary:
		_poll_token = ""
		status_changed.emit("Account service unavailable. Anonymous play is still available.")
		return
	var response: Dictionary = parsed
	if code < 200 or code >= 300:
		_poll_token = ""
		status_changed.emit(str(response.get("message", response.get("error", "Account request failed (%d)." % code))))
		return
	if kind == "discord_start":
		_poll_token = str(response.get("poll_token", ""))
		_poll_after = 2.0
		var authorization_url := str(response.get("authorization_url", ""))
		if _poll_token.is_empty() or not authorization_url.begins_with("https://"):
			_poll_token = ""
			status_changed.emit("Discord authorization is unavailable on this server.")
			return
		discord_url = authorization_url
		if not OS.has_feature("web"):
			OS.shell_open(authorization_url)
		status_changed.emit("Open Discord sign-in below, finish authorization in your browser, then return here.")
		return
	if kind == "discord_poll" and response.get("status", "") == "pending":
		_poll_after = 2.0
		return
	_poll_token = ""
	discord_url = ""
	if str(response.get("token", "")).is_empty():
		status_changed.emit("The account service did not complete sign-in.")
		return
	token = str(response.token)
	var user: Variant = response.get("user", {})
	username = str(user.get("username", user.get("name", "Account"))) if user is Dictionary else str(user)
	_store_session()
	identity_changed.emit()
	status_changed.emit("Signed in as " + username + ". Join to restore your server progress.")

func join_world() -> void:
	if not _pending_mines.is_empty():
		status_changed.emit("Waiting for excavation confirmation before rejoining.")
		return
	if not _http_kind.is_empty() or not _poll_token.is_empty():
		status_changed.emit("Finish signing in, or use Sign out / cancel sign-in to join anonymously.")
		return
	leave_world()
	_socket = WebSocketPeer.new()
	_socket.inbound_buffer_size = 4 * 1024 * 1024
	_socket.max_queued_packets = 4096
	var websocket_url := base_url.trim_suffix("/").replace("https://", "wss://").replace("http://", "ws://") + "/api/ws"
	var result := _socket.connect_to_url(websocket_url)
	if result != OK:
		_socket = null
		status_changed.emit("Unable to connect: " + error_string(result))
		return
	connecting = true
	_connect_elapsed = 0.0
	_join_sent = false
	status_changed.emit("Joining " + world_id + "…")

func leave_world() -> void:
	if connected:
		send_state()
	if _socket != null:
		_socket.close(1000, "Leaving world")
	_socket = null
	connected = false
	connecting = false
	player_id = ""
	peers.clear()
	_pending_mines.clear()
	_mining_baseline.clear()

func send_state() -> void:
	if _pending_mines.is_empty() and connected and host.is_coop and host.scene_name == "Game" and host.player != null and host.player.data == host.data:
		_send({"type": "state", "state": host.coop_state(), "state_revision": state_revision})

func mine(x: int, y: int, method: String = "drill") -> bool:
	if not connected:
		return false
	var cell := Vector2i(x, y)
	if _pending_mines.has(cell):
		return true
	if _pending_mines.is_empty():
		send_state()
		_mining_baseline = host.data.coop_snapshot()
	_sequence += 1
	_pending_mines[cell] = 0.0
	_send({"type": "mine", "request_id": str(_sequence), "x": x, "y": y, "method": method})
	return true

func _reconcile_mining_state(authoritative: Dictionary) -> Dictionary:
	# Local purchases/consumption can happen while an excavation reply is in flight.
	# Preserve only changes since the last submitted/acknowledged economic snapshot.
	var current: Dictionary = host.data.coop_snapshot()
	var merged := authoritative.duplicate(true)
	merged.player_money = int(authoritative.get("player_money", 20)) + int(current.player_money) - int(_mining_baseline.get("player_money", 20))
	for field in ["player_items", "player_cargo"]:
		var values: Dictionary = authoritative.get(field, {}).duplicate()
		var before: Dictionary = _mining_baseline.get(field, {})
		for key in current[field]:
			values[key] = maxi(0, int(values.get(key, 0)) + int(current[field][key]) - int(before.get(key, 0)))
		merged[field] = values
	for field in ["current_upgrades", "transmissions"]:
		if current[field] != _mining_baseline.get(field, current[field]):
			merged[field] = current[field]
	_mining_baseline = authoritative.duplicate(true)
	return merged

func _send(message: Dictionary) -> void:
	if _socket != null and _socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		var result := _socket.send_text(JSON.stringify(message))
		if result != OK:
			_socket.close(1011, "Unable to send progress")
			status_changed.emit("The server connection could not send your progress.")

func _process(delta: float) -> void:
	var now := Time.get_ticks_usec()
	delta = float(now - _last_usec) / 1000000.0 if _last_usec > 0 else 0.0
	_last_usec = now
	if not _poll_token.is_empty() and _http_kind.is_empty():
		_poll_after -= delta
		if _poll_after <= 0.0:
			_request("/api/auth/discord/poll", {"poll_token": _poll_token}, "discord_poll")
	if _socket == null:
		return
	_socket.poll()
	var ready := _socket.get_ready_state()
	if ready == WebSocketPeer.STATE_CLOSED:
		_fail("Disconnected from the server. Account progress already received by the server is retained; anonymous progress is not.")
		return
	if connecting:
		_connect_elapsed += delta
		if _connect_elapsed > 25.0:
			_fail("The co-op server did not respond. Your private save is unchanged.")
			return
	if ready != WebSocketPeer.STATE_OPEN:
		return
	if not _join_sent:
		_join_sent = true
		_send({"type": "join", "token": token, "world_id": world_id})
	while _socket != null and _socket.get_available_packet_count() > 0:
		var parsed: Variant = JSON.parse_string(_socket.get_packet().get_string_from_utf8())
		if parsed is Dictionary:
			_receive(parsed)
	if not connected:
		return
	for cell in _pending_mines.keys():
		_pending_mines[cell] += delta
		if _pending_mines[cell] > 20.0:
			_fail("The server stopped confirming excavation. Rejoin before continuing.")
			return
	_state_after -= delta
	if _state_after <= 0.0:
		_state_after = 0.5
		send_state()

func _receive(event: Dictionary) -> void:
	match str(event.get("type", "")):
		"joined":
			connected = true
			connecting = false
			player_id = str(event.player_id)
			world_id = str(event.world_id)
			state_revision = int(event.get("state_revision", 0))
			for peer in event.get("players", []):
				peers[str(peer.player_id)] = peer
			joined_world.emit(event)
			print("OREBIT_COOP_JOINED world=" + world_id + " player=" + player_id + " players=" + str(peers.size()))
		"player_joined":
			var peer: Dictionary = event.player
			peers[str(peer.player_id)] = peer
			world_event.emit(event)
		"player_left":
			peers.erase(str(event.player_id))
			world_event.emit(event)
		"state":
			var id := str(event.player_id)
			if peers.has(id):
				peers[id].state = event.get("state", {})
			world_event.emit(event)
		"mined":
			var own := str(event.get("player_id", "")) == player_id
			if own:
				_pending_mines.erase(Vector2i(int(event.x), int(event.y)))
				if bool(event.get("accepted", false)):
					state_revision = int(event.get("state_revision", state_revision))
					event.state = _reconcile_mining_state(event.get("state", {}))
			world_event.emit(event)
			if own and _pending_mines.is_empty():
				_mining_baseline.clear()
				send_state()
		"state_sync":
			# Ordered WebSocket replies already delivered this revision's mining reward.
			if int(event.get("state_revision", 0)) > state_revision:
				state_revision = int(event.state_revision)
				world_event.emit(event)
		"error":
			var message := str(event.get("message", "The server rejected the request."))
			if connecting:
				_fail(message)
			else:
				status_changed.emit(message)

func _fail(message: String) -> void:
	var was_active := connected or connecting
	leave_world()
	status_changed.emit(message)
	if was_active:
		connection_lost.emit(message)
