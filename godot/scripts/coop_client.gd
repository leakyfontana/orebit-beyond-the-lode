class_name CoopClient
extends Node

signal status_changed(message: String)
signal identity_changed
signal auth_state_changed
signal joined_world(snapshot: Dictionary)
signal connection_lost(message: String)
signal recovery_started
signal world_event(event: Dictionary)

const DEFAULT_URL := "https://play.arcmonkeyswelding.com/coop"
const SESSION_FILE := "user://orebit_coop_session.json"
const RECOVERY_WINDOW_USEC := 35000000
const RECOVERY_ATTEMPT_USEC := 8000000
const RECOVERY_BACKOFF_USEC := [250000, 750000, 1500000, 2500000]
var base_url := DEFAULT_URL
var world_id := "public"
var token := ""
var username := ""
var expires_at := 0
var session_checking := false
var auth_busy: bool:
	get:
		return session_checking or not _http_kind.is_empty() or not _poll_token.is_empty()
var player_id := ""
var connected := false
var connecting := false
var recovering := false
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
var _connect_started_usec := 0
var _join_context: Dictionary = {}
var _recovery_deadline_usec := 0
var _recovery_after_usec := 0
var _recovery_attempt := 0
var _sequence := 0
var _pending_mines: Dictionary = {}
var _economic_baseline: Dictionary = {}
var transfer_pending := false
var _transfer_elapsed := 0.0
var startup_mode := ""
var mode := "coop"
var _last_usec := 0
var _auth_expires_at := 0
var _auth_navigating := false
var _session_expiry_after := 0.0
var _join_after_session_check := false
const ANDROID_AUTH_RETURN := "org.motherloadrecoded.game://auth/discord"
var pvp_sequence := 0
var _pvp_blasts: Dictionary = {}
var _motion_sequence := 0
var _last_motion_ack := 0
var _motion_offset := Vector2.ZERO
var _sent_motion_offsets: Dictionary = {}
var round_id := ""
var _round_loading := false
var _round_events: Array[Dictionary] = []

func configure(main_host: Node) -> void:
	host = main_host
	process_mode = Node.PROCESS_MODE_ALWAYS
	_http = HTTPRequest.new()
	# Fetch already decompresses web responses; Safari retains Content-Encoding.
	_http.accept_gzip = not OS.has_feature("web")
	_http.timeout = 20.0
	add_child(_http)
	_http.request_completed.connect(_http_completed)
	var pending: Variant = {}
	var auth_returned := false
	if FileAccess.file_exists(SESSION_FILE):
		var saved: Variant = JSON.parse_string(FileAccess.get_file_as_string(SESSION_FILE))
		if saved is Dictionary:
			token = str(saved.get("token", ""))
			username = str(saved.get("username", ""))
			base_url = str(saved.get("base_url", DEFAULT_URL))
			expires_at = int(saved.get("expires_at", 0))
			pending = saved.get("pending_auth", {})
	var arguments := Array(OS.get_cmdline_user_args())
	if OS.has_feature("web"):
		var query: Variant = JSON.parse_string(str(JavaScriptBridge.eval("JSON.stringify(Object.fromEntries(new URLSearchParams(window.location.search)))")))
		if query is Dictionary:
			auth_returned = query.has("orebit_auth")
			for key in ["mode", "coop-url", "coop-world"]:
				if query.has(key):
					arguments.append("--" + key + "=" + str(query[key]))
		JavaScriptBridge.eval("(() => { const url = new URL(location.href); if (url.searchParams.has('orebit_auth')) { url.searchParams.delete('orebit_auth'); history.replaceState(null, '', url.href); } })()")
		pending = JSON.parse_string(str(JavaScriptBridge.eval("(() => { try { return sessionStorage.getItem('orebit.pending_discord') || '{}'; } catch (_) { return '{}'; } })()")))
	var saved_endpoint := base_url
	var explicit_token := false
	for argument in arguments:
		if str(argument).begins_with("--coop-url="):
			base_url = str(argument).trim_prefix("--coop-url=").trim_suffix("/")
		elif str(argument).begins_with("--coop-world="):
			world_id = str(argument).trim_prefix("--coop-world=")
		elif str(argument).begins_with("--coop-token="):
			token = str(argument).trim_prefix("--coop-token=")
			expires_at = 0
			explicit_token = true
		elif str(argument).begins_with("--mode="):
			startup_mode = str(argument).trim_prefix("--mode=")
	if startup_mode == "pvp":
		mode = "pvp"
	if saved_endpoint != base_url and not explicit_token:
		token = ""
		username = ""
		expires_at = 0
	if pending is Dictionary and str(pending.get("base_url", "")) == base_url:
		_auth_expires_at = int(pending.get("expires_at", 0))
		if _auth_expires_at > int(Time.get_unix_time_from_system()):
			_poll_token = str(pending.get("poll_token", ""))
			mode = "pvp" if str(pending.get("mode", mode)) == "pvp" else "coop"
			auth_returned = auth_returned or not _poll_token.is_empty()
	if auth_returned:
		startup_mode = "auth_return"
	if not _poll_token.is_empty():
		_poll_after = 0.0
	elif not token.is_empty():
		session_checking = true
		_validate_session.call_deferred()

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
	if auth_busy:
		status_changed.emit("A sign-in request is already in progress.")
		return
	if not token.is_empty():
		_validate_session()
		return
	var payload: Dictionary = {}
	if OS.has_feature("web"):
		payload.return_url = str(JavaScriptBridge.eval("(() => { const url = new URL(location.href); url.searchParams.delete('orebit_auth'); url.searchParams.set('mode', " + JSON.stringify(mode) + "); url.hash = ''; return url.href; })()"))
	elif OS.get_name() == "Android":
		payload.return_url = ANDROID_AUTH_RETURN
	_request("/api/auth/discord/start", payload, "discord_start")

func logout() -> void:
	if connected or connecting or recovering:
		_fail("Signed out. Sign in again or continue anonymously.")
	cancel_auth(false)
	if not token.is_empty():
		var revocation := HTTPRequest.new()
		revocation.accept_gzip = not OS.has_feature("web")
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
	expires_at = 0
	_store_session()
	identity_changed.emit()
	auth_state_changed.emit()
	status_changed.emit("Signed out. You can sign in again or play anonymously.")

func cancel_auth(show_message: bool = true) -> void:
	if not _http_kind.is_empty():
		_http.cancel_request()
		_http_kind = ""
	session_checking = false
	_join_after_session_check = false
	_clear_pending_auth()
	_store_session()
	auth_state_changed.emit()
	if show_message:
		status_changed.emit("Sign-in cancelled.")

func _clear_pending_auth() -> void:
	_poll_token = ""
	_auth_expires_at = 0
	_auth_navigating = false
	if OS.has_feature("web"):
		JavaScriptBridge.eval("(() => { try { sessionStorage.removeItem('orebit.pending_discord'); } catch (_) {} })()")

func _validate_session() -> void:
	if expires_at > 0 and expires_at <= int(Time.get_unix_time_from_system()):
		_expire_session()
		return
	if token.is_empty():
		session_checking = false
		auth_state_changed.emit()
		return
	session_checking = true
	_request("/api/auth/session", {}, "session", HTTPClient.METHOD_GET, true)

func _expire_session() -> void:
	token = ""
	username = ""
	expires_at = 0
	session_checking = false
	_join_after_session_check = false
	_store_session()
	identity_changed.emit()
	auth_state_changed.emit()
	if connected or connecting or recovering:
		_fail("Your sign-in expired. Sign in again to restore your account progress.")
	else:
		status_changed.emit("Your sign-in expired. Sign in again or continue anonymously.")

func _store_session() -> void:
	var file := FileAccess.open(SESSION_FILE, FileAccess.WRITE)
	if file != null:
		var pending := {"base_url": base_url, "poll_token": _poll_token, "expires_at": _auth_expires_at, "mode": mode} if not _poll_token.is_empty() else {}
		file.store_string(JSON.stringify({"token": token, "username": username, "expires_at": expires_at, "base_url": base_url, "pending_auth": pending}))
		file.close()
		if OS.has_feature("web"):
			JavaScriptBridge.force_fs_sync()

func _request(path: String, payload: Dictionary, kind: String, method: HTTPClient.Method = HTTPClient.METHOD_POST, authorized: bool = false) -> void:
	if not _http_kind.is_empty():
		status_changed.emit("An account request is already in progress.")
		return
	_http_kind = kind
	var headers := PackedStringArray(["Content-Type: application/json"])
	if authorized:
		headers.append("Authorization: Bearer " + token)
	var result := _http.request(base_url.trim_suffix("/") + path, headers, method, "" if method == HTTPClient.METHOD_GET else JSON.stringify(payload))
	if result != OK:
		_http_kind = ""
		session_checking = false
		status_changed.emit("Unable to contact account service: " + error_string(result))
	else:
		status_changed.emit("Checking saved sign-in…" if kind == "session" else ("Waiting for Discord…" if kind == "discord_poll" else "Contacting account service…"))
	auth_state_changed.emit()

func _http_completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var kind := _http_kind
	_http_kind = ""
	session_checking = false
	if kind == "session" and code == 401:
		_expire_session()
		return
	if result != HTTPRequest.RESULT_SUCCESS:
		if kind != "session":
			_clear_pending_auth()
		auth_state_changed.emit()
		status_changed.emit("Account service unavailable. Your saved sign-in has not been removed." if kind == "session" else "Account service unavailable. Anonymous play is still available.")
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not parsed is Dictionary:
		if kind != "session":
			_clear_pending_auth()
		auth_state_changed.emit()
		status_changed.emit("The account service returned an unreadable response.")
		return
	var response: Dictionary = parsed
	if code < 200 or code >= 300:
		if kind != "session":
			_clear_pending_auth()
		auth_state_changed.emit()
		status_changed.emit(str(response.get("message", response.get("error", "Account request failed (%d)." % code))))
		return
	if kind == "session":
		expires_at = int(response.get("expires_at", 0))
		var user: Dictionary = response.get("user", {})
		username = str(user.get("name", username))
		_store_session()
		if _join_after_session_check:
			_join_after_session_check = false
			join_world.call_deferred()
		identity_changed.emit()
		auth_state_changed.emit()
		status_changed.emit("Saved session restored.")
		return
	if kind == "discord_start":
		_poll_token = str(response.get("poll_token", ""))
		_auth_expires_at = int(response.get("expires_at", 0))
		_poll_after = 2.0
		var authorization_url := str(response.get("authorization_url", ""))
		if _poll_token.is_empty() or not authorization_url.begins_with("https://discord.com/oauth2/authorize?"):
			_clear_pending_auth()
			auth_state_changed.emit()
			status_changed.emit("Discord authorization is unavailable on this server.")
			return
		if OS.has_feature("web"):
			var pending := JSON.stringify({"base_url": base_url, "poll_token": _poll_token, "expires_at": _auth_expires_at, "mode": mode})
			var stored: Variant = JavaScriptBridge.eval("(() => { try { sessionStorage.setItem('orebit.pending_discord', " + JSON.stringify(pending) + "); return true; } catch (_) { return false; } })()")
			if not stored:
				_clear_pending_auth()
				auth_state_changed.emit()
				status_changed.emit("Allow site storage in this browser to complete Discord sign-in.")
				return
			_auth_navigating = true
			JavaScriptBridge.eval("window.location.assign(" + JSON.stringify(authorization_url) + ")")
		else:
			_store_session()
			if OS.shell_open(authorization_url) != OK:
				_clear_pending_auth()
				_store_session()
				auth_state_changed.emit()
				status_changed.emit("Your browser could not open Discord. Try signing in again.")
				return
		auth_state_changed.emit()
		status_changed.emit("Complete sign-in in Discord. You will return to Orebit automatically.")
		return
	if kind == "discord_poll" and response.get("status", "") == "pending":
		_poll_after = 2.0
		auth_state_changed.emit()
		return
	if str(response.get("token", "")).is_empty():
		_clear_pending_auth()
		_store_session()
		auth_state_changed.emit()
		status_changed.emit(str(response.get("message", "The account service did not complete sign-in.")))
		return
	token = str(response.token)
	expires_at = int(response.get("expires_at", 0))
	var user: Variant = response.get("user", {})
	username = str(user.get("username", user.get("name", "Account"))) if user is Dictionary else str(user)
	_clear_pending_auth()
	_store_session()
	identity_changed.emit()
	auth_state_changed.emit()
	status_changed.emit("Join to restore your server progress.")
	if kind == "discord_poll" and not OS.has_feature("web") and OS.get_name() != "Android":
		DisplayServer.window_move_to_foreground()

func join_world() -> void:
	if session_checking:
		_join_after_session_check = true
		return
	if has_pending_actions():
		status_changed.emit("Waiting for the current server transaction before rejoining.")
		return
	if auth_busy:
		status_changed.emit("Finish signing in, or cancel sign-in to join anonymously.")
		return
	leave_world()
	_join_context = {"base_url": base_url, "world_id": world_id, "mode": mode, "token": token}
	var result := _open_socket()
	if result != OK:
		status_changed.emit("Unable to connect: " + error_string(result))
		return
	status_changed.emit("Joining " + ("PvP sandbox" if mode == "pvp" else "Co-op") + " · " + world_id + "…")

func _open_socket() -> Error:
	_socket = WebSocketPeer.new()
	_socket.inbound_buffer_size = 4 * 1024 * 1024
	_socket.max_queued_packets = 4096
	var websocket_url := str(_join_context.base_url).trim_suffix("/").replace("https://", "wss://").replace("http://", "ws://") + "/api/ws"
	var result := _socket.connect_to_url(websocket_url)
	if result != OK:
		_socket = null
		connecting = false
		return result
	connecting = true
	_connect_started_usec = Time.get_ticks_usec()
	_join_sent = false
	return OK

func _recovery_context_matches() -> bool:
	return not token.is_empty() and not player_id.is_empty() and not _join_context.is_empty() and token == _join_context.token and base_url == _join_context.base_url and world_id == _join_context.world_id and mode == _join_context.mode

func _begin_recovery(now: int) -> void:
	recovering = true
	_recovery_deadline_usec = now + RECOVERY_WINDOW_USEC
	_recovery_attempt = 0
	# An action may have reached the server even when its reply did not. Discard
	# local pending work and rebuild from joined; never resubmit it on a retry.
	_pending_mines.clear()
	_pvp_blasts.clear()
	_economic_baseline.clear()
	transfer_pending = false
	_transfer_elapsed = 0.0
	_round_loading = false
	_round_events.clear()
	_reset_motion_history()
	_schedule_recovery(now)
	recovery_started.emit()
	status_changed.emit("Reconnecting… Local controls are disabled until the server restores your session.")

func _schedule_recovery(now: int) -> void:
	if _socket != null:
		_socket.close()
	# Release this peer now: a dead transport's close handshake must not hold
	# the replacement connection or the overall recovery deadline open.
	_socket = null
	connected = false
	connecting = false
	_join_sent = false
	_recovery_after_usec = now + int(RECOVERY_BACKOFF_USEC[mini(_recovery_attempt, RECOVERY_BACKOFF_USEC.size() - 1)])
	_recovery_attempt += 1

func leave_world() -> void:
	if host.gameplay_capture != null and host.is_coop:
		host.gameplay_capture.finish("disconnect")
	if connected:
		send_state()
	if _socket != null:
		_socket.close(1000, "Leaving world")
	_socket = null
	connected = false
	connecting = false
	recovering = false
	_join_context.clear()
	_recovery_deadline_usec = 0
	_recovery_after_usec = 0
	_recovery_attempt = 0
	_connect_started_usec = 0
	player_id = ""
	peers.clear()
	_pvp_blasts.clear()
	_pending_mines.clear()
	_economic_baseline.clear()
	transfer_pending = false
	_transfer_elapsed = 0.0
	_motion_sequence = 0
	_reset_motion_history()
	round_id = ""
	_round_loading = false
	_round_events.clear()

func send_state() -> void:
	if not _round_loading and not has_pending_actions() and connected and host.is_coop and host.scene_name == "Game" and host.player != null and host.player.data == host.data:
		if mode == "pvp" and not host.player_alive:
			return
		var message := {"type": "state", "state": host.coop_state(), "state_revision": state_revision}
		if mode == "pvp":
			_motion_sequence += 1
			message.motion_seq = _motion_sequence
			_sent_motion_offsets[_motion_sequence] = _motion_offset
			# Only outstanding acknowledgements need history; old replies are ignored.
			if _sent_motion_offsets.size() > 128:
				_sent_motion_offsets.erase(_sent_motion_offsets.keys()[0])
		_send(message)

func _reset_motion_history() -> void:
	_sent_motion_offsets.clear()
	_motion_offset = Vector2.ZERO
	_last_motion_ack = _motion_sequence

func _acknowledge_motion(event: Dictionary) -> void:
	var sequence := int(event.get("motion_seq", 0))
	if sequence <= _last_motion_ack or not _sent_motion_offsets.has(sequence):
		return
	_last_motion_ack = sequence
	var sent_offset: Vector2 = _sent_motion_offsets[sequence]
	for pending in _sent_motion_offsets.keys():
		if int(pending) <= sequence:
			_sent_motion_offsets.erase(pending)
	var requested: Array = event.get("requested_position", [])
	if requested.size() != 2 or not host.player_alive or host.player == null or host.player.pvp_building_hidden:
		return
	var state: Dictionary = event.get("state", {})
	var accepted := Vector2(float(state.x), float(state.y))
	var requested_position := Vector2(float(requested[0]), float(requested[1]))
	var correction := accepted - requested_position - (_motion_offset - sent_offset)
	if correction.length_squared() > 0.000001:
		host.player.apply_motion_correction(correction)
		_motion_offset += correction

func pvp_action(kind: String, fields: Dictionary = {}) -> String:
	if connected and mode == "pvp" and not _round_loading:
		pvp_sequence += 1
		var message := fields.duplicate()
		message.type = kind
		message.request_id = "pvp-" + str(pvp_sequence)
		if kind == "blast":
			_pvp_blasts[message.request_id] = str(fields.get("item", ""))
		_send(message)
		return str(message.request_id)
	return ""

func has_pending_actions() -> bool:
	return not _pending_mines.is_empty() or transfer_pending

func transfer_money(recipient_id: String, amount: int) -> bool:
	if _round_loading or not connected or has_pending_actions() or recipient_id == player_id or not peers.has(recipient_id) or amount <= 0 or amount > host.data.player_money:
		return false
	send_state()
	transfer_pending = true
	_transfer_elapsed = 0.0
	_send({"type": "transfer", "recipient_id": recipient_id, "amount": amount})
	return true

func mine(x: int, y: int, method: String = "drill") -> bool:
	if _round_loading or not connected or transfer_pending:
		return false
	var cell := Vector2i(x, y)
	if _pending_mines.has(cell):
		return true
	if _pending_mines.is_empty():
		send_state()
	_sequence += 1
	_pending_mines[cell] = 0.0
	_send({"type": "mine", "request_id": str(_sequence), "x": x, "y": y, "method": method})
	return true

func _reconcile_economic_state(authoritative: Dictionary) -> Dictionary:
	# Merge only local changes since the last server-acknowledged snapshot.
	# A sent snapshot is not a baseline: stale revisions may reject that write.
	var current: Dictionary = host.data.coop_snapshot()
	var merged := authoritative.duplicate(true)
	merged.player_money = int(authoritative.get("player_money", 20)) + int(current.player_money) - int(_economic_baseline.get("player_money", 20))
	for field in ["player_items", "player_cargo"]:
		var values: Dictionary = authoritative.get(field, {}).duplicate()
		var before: Dictionary = _economic_baseline.get(field, {})
		for key in current[field]:
			values[key] = maxi(0, int(values.get(key, 0)) + int(current[field][key]) - int(before.get(key, 0)))
		merged[field] = values
	for field in ["current_upgrades", "transmissions"]:
		if current[field] != _economic_baseline.get(field, current[field]):
			merged[field] = current[field]
	_economic_baseline = authoritative.duplicate(true)
	return merged

func finish_round_load() -> void:
	if not _round_loading:
		return
	_round_loading = false
	var pending := _round_events
	_round_events = []
	for event in pending:
		_receive(event)
	send_state()

func _send(message: Dictionary) -> void:
	if mode == "pvp" and message.get("type") == "join":
		message.pvp_rounds = 1
	if mode == "pvp" and str(message.get("type", "")) in ["state", "mine", "transfer", "blast", "damage", "claim_transmission", "building"]:
		message.round_id = round_id
	if str(message.get("type", "")) == "join" and host.gameplay_capture != null:
		message.merge(host.gameplay_capture.credentials())
	if _socket != null and _socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		var result := _socket.send_text(JSON.stringify(message))
		if result != OK:
			_socket.close(1011, "Unable to send progress")
			status_changed.emit("The server connection could not send your progress.")

func link_capture() -> void:
	if connected and host.gameplay_capture != null:
		var fields: Dictionary = host.gameplay_capture.credentials()
		if not fields.is_empty():
			fields.type = "capture_link"
			_send(fields)

func _process(delta: float) -> void:
	var now := Time.get_ticks_usec()
	delta = float(now - _last_usec) / 1000000.0 if _last_usec > 0 else 0.0
	_last_usec = now
	if not token.is_empty() and expires_at > 0:
		_session_expiry_after -= delta
		if _session_expiry_after <= 0.0:
			_session_expiry_after = 1.0
			if expires_at <= int(Time.get_unix_time_from_system()):
				_expire_session()
	if not _poll_token.is_empty() and _auth_expires_at <= int(Time.get_unix_time_from_system()):
		_clear_pending_auth()
		_store_session()
		auth_state_changed.emit()
		status_changed.emit("Discord sign-in expired. Try again.")
	if not _auth_navigating and not _poll_token.is_empty() and _http_kind.is_empty():
		_poll_after -= delta
		if _poll_after <= 0.0:
			_request("/api/auth/discord/poll", {"poll_token": _poll_token}, "discord_poll")
	if recovering:
		if not _recovery_context_matches():
			_fail("Reconnection cancelled because the account, server, world or mode changed.")
			return
		if now >= _recovery_deadline_usec:
			_fail("Could not reconnect to the server. Progress already confirmed by the server is retained; unconfirmed actions were not retried. Your private save is unchanged.")
			return
		if _socket == null and now >= _recovery_after_usec:
			if _open_socket() != OK:
				_schedule_recovery(now)
	if _socket == null:
		return
	_socket.poll()
	var ready := _socket.get_ready_state()
	if ready == WebSocketPeer.STATE_OPEN and not _join_sent:
		_join_sent = true
		var join := {"type": "join", "token": _join_context.token, "world_id": _join_context.world_id, "mode": _join_context.mode}
		if recovering:
			join.resume_player_id = player_id
		_send(join)
	# A policy/auth error and its close frame may arrive in the same poll.
	# Consume the error before deciding whether this was a transport loss.
	while _socket != null and _socket.get_available_packet_count() > 0:
		var parsed: Variant = JSON.parse_string(_socket.get_packet().get_string_from_utf8())
		if not parsed is Dictionary:
			_fail("The server returned an unreadable game message.")
			return
		_receive(parsed)
	if _socket == null:
		return
	ready = _socket.get_ready_state()
	if ready in [WebSocketPeer.STATE_CLOSING, WebSocketPeer.STATE_CLOSED]:
		var close_code := _socket.get_close_code()
		# Native close processing can discard the final JSON error packet.
		# Explicit server failure must remain terminal, not become a retry.
		if close_code in [1002, 1003, 1007, 1008, 1009, 1011]:
			var reason := _socket.get_close_reason()
			if close_code == 1008 and reason in ["invalid_token", "Signed out"]:
				_expire_session()
			else:
				_fail("The server ended this session." if reason.is_empty() else "The server ended this session: " + reason)
		elif recovering:
			_schedule_recovery(now)
		elif connected and _recovery_context_matches():
			_begin_recovery(now)
		else:
			_fail("Disconnected from the server. Account progress already received by the server is retained; anonymous progress is not.")
		return
	if connecting and now - _connect_started_usec > (RECOVERY_ATTEMPT_USEC if recovering else 25000000):
		if recovering:
			_schedule_recovery(now)
		else:
			_fail("The " + ("PvP" if mode == "pvp" else "co-op") + " server did not respond. Your private save is unchanged.")
		return
	if ready != WebSocketPeer.STATE_OPEN:
		return
	if not connected:
		return
	if transfer_pending:
		_transfer_elapsed += delta
		if _transfer_elapsed > 20.0:
			_fail("The server stopped confirming the transfer. Rejoin to see the saved balance; do not resend an unconfirmed transfer.")
			return
	for cell in _pending_mines.keys():
		_pending_mines[cell] += delta
		if _pending_mines[cell] > 20.0:
			if _recovery_context_matches():
				_begin_recovery(now)
			else:
				_fail("The server stopped confirming excavation. Rejoin before continuing.")
			return
	_state_after -= delta
	if _state_after <= 0.0:
		_state_after = 0.05 if mode == "pvp" else 0.5
		send_state()

func _receive(event: Dictionary) -> void:
	var kind := str(event.get("type", ""))
	if kind == "error":
		if str(event.get("code", "")) == "invalid_token":
			_expire_session()
		else:
			_fail(str(event.get("message", "The server rejected the request.")))
		return
	if _round_loading and kind not in ["joined", "round_started"]:
		if _round_events.size() >= 128:
			_fail("World updates exceeded the scene-loading buffer. Reconnect to resume.")
			return
		_round_events.append(event)
		return
	if mode == "pvp" and kind not in ["joined", "round_started"]:
		if event.has("round_id") and str(event.round_id) != round_id:
			return
	if kind == "round_started" and str(event.get("round_id", "")) == round_id:
		return
	if host.gameplay_capture != null and event.has("capture_server_sequence") and event.has("capture_session_id"):
		host.gameplay_capture.server_event(int(event.capture_server_sequence), str(event.capture_session_id))
	if host.gameplay_capture != null and event.has("capture_session_id") and event.has("capture_gap_first") and event.has("capture_gap_last"):
		host.gameplay_capture.server_gap(str(event.capture_session_id), int(event.capture_gap_first), int(event.capture_gap_last))
	match str(event.get("type", "")):
		"round_rejected":
			# Reset already retired these requests. An expected old-round NACK
			# must not open the account/error modal over the new-round announcement.
			return
		"building_result":
			# state_sync already reconciled the financial snapshot. Results only
			# acknowledge the matching lifecycle request and must not merge it again.
			world_event.emit(event)
		"blast_result":
			var request := str(event.get("request_id", ""))
			if _pvp_blasts.has(request):
				var item: String = _pvp_blasts[request]
				_pvp_blasts.erase(request)
				if bool(event.get("accepted", false)):
					var items: Dictionary = _economic_baseline.get("player_items", {})
					items[item] = maxi(0, int(items.get(item, 0)) - 1)
				else:
					host.data.player_items[item] += 1
		"pvp_tick":
			for peer in event.get("players", []):
				peers[str(peer.player_id)] = peer
				if str(peer.player_id) == player_id:
					state_revision = int(peer.get("state_revision", state_revision))
					if bool(peer.get("state", {}).get("alive", true)) != host.player_alive:
						_reset_motion_history()
			world_event.emit(event)
		"joined", "round_started":
			if event.type == "round_started" and host.gameplay_capture != null:
				var completed: Dictionary = event.get("completed_state", {})
				host.data.restore_coop_state(completed)
				host.data.player_hp = ceili(maxf(0.0, float(completed.get("player_hp", host.data.player_hp))))
				host.gameplay_capture.finish("round_end")
			_round_loading = true
			_round_events.clear()
			round_id = str(event.get("round_id", ""))
			_pending_mines.clear()
			_pvp_blasts.clear()
			transfer_pending = false
			_transfer_elapsed = 0.0
			_reset_motion_history()
			peers.clear()
			connected = true
			connecting = false
			recovering = false
			_recovery_deadline_usec = 0
			_recovery_after_usec = 0
			_recovery_attempt = 0
			link_capture()
			player_id = str(event.player_id)
			world_id = str(event.world_id)
			if not _join_context.is_empty():
				_join_context.world_id = world_id
			state_revision = int(event.get("state_revision", 0))
			_economic_baseline = event.get("state", {}).duplicate(true)
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
				if bool(event.get("accepted", false)) and int(event.get("state_revision", 0)) > state_revision:
					state_revision = int(event.state_revision)
					event.state = _reconcile_economic_state(event.get("state", {}))
				elif bool(event.get("accepted", false)):
					event.state = host.data.coop_snapshot()
			world_event.emit(event)
			if own and _pending_mines.is_empty():
				send_state()
		"state_ack":
			if mode == "pvp":
				_acknowledge_motion(event)
			if int(event.get("state_revision", 0)) == state_revision:
				_economic_baseline = event.get("state", {}).duplicate(true)
		"transfer_result":
			transfer_pending = false
			if bool(event.get("accepted", false)) and int(event.get("state_revision", 0)) > state_revision:
				state_revision = int(event.state_revision)
				event.state = _reconcile_economic_state(event.get("state", {}))
			world_event.emit(event)
			send_state()
		"state_sync":
			if mode == "pvp" and (not bool(event.get("state", {}).get("alive", true)) or not host.player_alive):
				_reset_motion_history()
			if mode == "pvp":
				var next_building := str(event.get("state", {}).get("building", ""))
				if host.coop.pvp.building != next_building:
					_reset_motion_history()
				state_revision = int(event.get("state_revision", state_revision))
				var authoritative: Dictionary = event.get("state", {})
				if bool(authoritative.get("alive", true)) and host.player_alive:
					var heal := maxi(0, host.data.player_hp - ceili(float(_economic_baseline.get("player_hp", host.data.player_hp))))
					event.state = _reconcile_economic_state(authoritative)
					if heal > 0:
						event.state.player_hp = float(authoritative.get("player_hp", 0)) + heal
				else:
					_economic_baseline = authoritative.duplicate(true)
					_pvp_blasts.clear()
				world_event.emit(event)
				return
			if int(event.get("state_revision", 0)) > state_revision:
				state_revision = int(event.state_revision)
				event.state = _reconcile_economic_state(event.get("state", {}))
				world_event.emit(event)
				send_state()

func _fail(message: String) -> void:
	var was_active := connected or connecting or recovering
	# A terminal failure must not flush uncertain local changes on its way out.
	connected = false
	leave_world()
	status_changed.emit(message)
	if was_active:
		connection_lost.emit(message)
