extends SceneTree

# Auth-expiry coverage writes SESSION_FILE. Use a staged project with a
# throwaway custom user directory, never the installed game's application data.
var failures := 0

func _initialize() -> void:
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _run() -> void:
	var arguments := OS.get_cmdline_user_args()
	if not arguments.has("--mode=private") or not arguments.has("--coop-url=http://127.0.0.1:1") or not arguments.has("--coop-token="):
		push_error("Co-op state probe requires --mode=private --coop-url=http://127.0.0.1:1 --coop-token=")
		quit(2)
		return
	if OS.get_user_data_dir().replace("\\", "/").trim_suffix("/").get_file() == "Motherload Re-Coded":
		push_error("Co-op state probe requires a staged project with an isolated custom user directory")
		quit(2)
		return
	var host: Node = load("res://main.tscn").instantiate()
	host.data.settings_file = "user://coop-state-interop-settings.json"
	host.data.savefile = "user://coop-state-interop-save.data"
	root.add_child(host)
	for frame in range(3):
		await process_frame
	var network: CoopClient = host.coop.network
	var data: GameData = host.data
	data.player_items["Reserve Fuel Tank"] = 2
	data.player_money = 100
	network._economic_baseline = data.coop_snapshot()
	var authoritative := data.coop_snapshot()
	authoritative.player_cargo.Ironium = 1
	# Consumption and a purchase happen after the excavation request but before reply.
	data.player_items["Reserve Fuel Tank"] -= 1
	data.player_money -= 50
	data.setUpgrade("Hull", "Ironium Hull")
	var reconciled := network._reconcile_economic_state(authoritative)
	check(reconciled.player_items["Reserve Fuel Tank"] == 1, "Mining reply duplicated a consumed fuel tank")
	check(reconciled.player_money == 50, "Mining reply rolled back a purchase")
	check(reconciled.current_upgrades.Hull == "Ironium Hull", "Mining reply lost an upgrade")
	check(reconciled.player_cargo.Ironium == 1, "Reconciliation lost the server mining reward")
	data.restore_coop_state(reconciled, true)
	# A second blast confirmation contains cumulative server rewards, not our local edits.
	authoritative.player_cargo.Ironium = 2
	reconciled = network._reconcile_economic_state(authoritative)
	check(reconciled.player_items["Reserve Fuel Tank"] == 1, "Batched mining replayed local consumption twice")
	check(reconciled.player_money == 50 and reconciled.player_cargo.Ironium == 2, "Batched mining lost local spending or duplicated ore")
	network.state_revision = 2
	var sync_events := [0]
	network.world_event.connect(func(_event: Dictionary): sync_events[0] += 1)
	network._receive({"type": "state_sync", "state_revision": 2, "state": authoritative})
	check(sync_events[0] == 0, "Already acknowledged state revision overwrote newer local changes")
	# Incoming transfers must preserve an unacknowledged purchase, but not replay an
	# already accepted one against the recipient's authoritative credit.
	data.player_money = 100
	var acknowledged := data.coop_snapshot()
	network._receive({"type": "state_ack", "state_revision": 2, "state": acknowledged})
	data.player_money = 70
	var credited := acknowledged.duplicate(true)
	credited.player_money = 125
	reconciled = network._reconcile_economic_state(credited)
	check(reconciled.player_money == 95, "Incoming transfer lost unacknowledged local spending")
	acknowledged.player_money = 70
	network._receive({"type": "state_ack", "state_revision": 2, "state": acknowledged})
	credited.player_money = 95
	reconciled = network._reconcile_economic_state(credited)
	check(reconciled.player_money == 95, "Incoming transfer applied acknowledged spending twice")
	for url in ["http://localhost.attacker.test", "http://127.0.0.1.attacker.test", "http://localhost@attacker.test"]:
		network.base_url = url
		check(not network.endpoint_is_secure(), "Credential endpoint accepted insecure host: " + url)
	network.base_url = "http://127.0.0.1:8765"
	check(network.endpoint_is_secure(), "Local development endpoint rejected")
	var lobby: CoopLobby = host.coop.lobby
	lobby.hide_lobby(true)
	host.paused = true
	lobby.show_lobby()
	lobby.hide_lobby()
	check(host.paused, "Account overlay resumed an already paused game")
	host.paused = false
	lobby.show_lobby()
	lobby.hide_lobby()
	check(not host.paused, "Account overlay left active gameplay paused")
	host.change_scene("Game")
	for frame in range(3):
		await process_frame
	var player: PortPlayer = host.player
	data.setUpgrade("Hull", "Energy-Shielded Hull")
	data.player_hp = 180
	player._block_target = Vector2i(35, 6)
	player._block_target_data = {"name": "Lava"}
	player.coop_mining_resolved(35, 6, true, false)
	check(data.player_hp == 180, "Blast confirmation inflicted drilling-only lava damage")
	player._block_target = Vector2i(35, 6)
	player._block_target_data = {"name": "Lava"}
	player.coop_mining_resolved(35, 6, true, true)
	check(data.player_hp == 135, "Accepted lava drilling lost its normal damage")
	await _recovery_cases(host)
	host.free()
	data = null
	network = null
	player = null
	lobby = null
	await process_frame
	print("COOP_STATE_INTEROP failures=" + str(failures))
	quit(0 if failures == 0 else 1)

func _accept_socket(server: TCPServer) -> Dictionary:
	var deadline := Time.get_ticks_msec() + 5000
	while not server.is_connection_available() and Time.get_ticks_msec() < deadline:
		await process_frame
	if not server.is_connection_available():
		check(false, "Recovery fixture did not receive a native TCP connection")
		return {}
	var stream := server.take_connection()
	var peer := WebSocketPeer.new()
	check(peer.accept_stream(stream) == OK, "Recovery fixture could not accept a native WebSocket")
	while peer.get_ready_state() == WebSocketPeer.STATE_CONNECTING and Time.get_ticks_msec() < deadline:
		peer.poll()
		await process_frame
	check(peer.get_ready_state() == WebSocketPeer.STATE_OPEN, "Recovery fixture WebSocket handshake failed")
	return {"stream": stream, "peer": peer}

func _read_message(peer: WebSocketPeer, kind: String) -> Dictionary:
	var deadline := Time.get_ticks_msec() + 5000
	while Time.get_ticks_msec() < deadline:
		peer.poll()
		while peer.get_available_packet_count() > 0:
			var parsed: Variant = JSON.parse_string(peer.get_packet().get_string_from_utf8())
			if parsed is Dictionary and str(parsed.get("type", "")) == kind:
				return parsed
		await process_frame
	check(false, "Recovery fixture did not receive " + kind)
	return {}

func _transport_ended(network: CoopClient) -> void:
	var deadline := Time.get_ticks_msec() + 5000
	while (network.connected or network.connecting) and not network.recovering and Time.get_ticks_msec() < deadline:
		await process_frame
	check(network.recovering or (not network.connected and not network.connecting), "Native socket loss was not observed")

func _fixture_snapshot(network: CoopClient, state: Dictionary, revision: int) -> Dictionary:
	return {"type": "joined", "player_id": "recovery-" + network.mode, "world_id": network.world_id,
		"seed": 12345, "excavated": [[8, 6]], "state": state, "state_revision": revision,
		"players": [{"player_id": "recovery-" + network.mode, "name": "Fixture", "state": state, "state_revision": revision}],
		"round_id": "recovery-round" if network.mode == "pvp" else "", "server_time": 1000.0}

func _load_joined(host: Node, peer: WebSocketPeer) -> void:
	var deadline := Time.get_ticks_msec() + 5000
	while host.pending_scene != "Game" and Time.get_ticks_msec() < deadline:
		peer.poll()
		await process_frame
	check(host.pending_scene == "Game", "Authoritative joined did not reconstruct the game")
	if host.pending_scene != "Game":
		return
	host.pending_scene = ""
	host._load_scene("Game")
	host.body.freeze = true
	if not host.data.pvp_mode:
		host.player_alive = host.player._alive
	await process_frame
	await process_frame

func _recovery_cases(host: Node) -> void:
	# Real native peers exercise the boundary between socket loss, the signed-in
	# resume request, and authoritative scene restoration. No account service or
	# persisted world participates; the backend's ownership proof has separate tests.
	host.set_process(false)
	host.set_physics_process(false)
	host.gameplay_capture.set_process(false)
	var network: CoopClient = host.coop.network
	var lobby: CoopLobby = host.coop.lobby
	var private_data: GameData = host.data
	var private_world: WorldData = host.world
	var private_money: int = private_data.player_money
	var server := TCPServer.new()
	if server.listen(0, "127.0.0.1") != OK:
		check(false, "Cannot open the isolated recovery fixture listener")
		return
	var endpoint := "http://127.0.0.1:" + str(server.get_local_port())
	for mode in ["coop", "pvp"]:
		network.base_url = endpoint
		network.world_id = "recovery-fixture"
		network.mode = mode
		network.token = "signed-in-recovery-fixture"
		network.expires_at = 0
		var confirmed := private_data.coop_snapshot()
		confirmed.merge({"player_money": 120, "player_hp": 8, "alive": true, "x": 5.5, "y": -3.5, "facing": false}, true)
		network.join_world()
		var original := await _accept_socket(server)
		if original.is_empty():
			break
		var first := await _read_message(original.peer, "join")
		check(not first.has("resume_player_id"), mode + ": initial join unexpectedly claimed a prior player")
		check(str(first.get("mode", "")) == mode and str(first.get("token", "")) == network.token, mode + ": initial join changed identity or mode")
		original.peer.send_text(JSON.stringify(_fixture_snapshot(network, confirmed, 4)))
		await _load_joined(host, original.peer)
		var game_data: GameData = host.data
		var game_world: WorldData = host.world
		var capture_episode: String = host.gameplay_capture.episode_id
		var capture_session: String = host.gameplay_capture.session_id
		# These writes have uncertain outcomes when the transport dies. They must
		# neither prevent recovery/Leave nor be replayed against the joined state.
		game_data.player_money = 999999
		network._pending_mines[Vector2i(8, 6)] = 0.0
		network.transfer_pending = true
		network._pvp_blasts["uncertain-blast"] = "Dynamite"
		original.stream.disconnect_from_host()
		await _transport_ended(network)
		check(network.recovering and not network.connected, mode + ": signed-in loss did not start recovery")
		check(host.coop.active and host.data == game_data and host.world == game_world, mode + ": interruption discarded game context")
		check(network.token == "signed-in-recovery-fixture" and network.player_id == "recovery-" + mode, mode + ": interruption discarded recovery identity")
		check(host.paused and lobby.modal, mode + ": interruption left local input active")
		var focus := root.gui_get_focus_owner()
		check(focus != null and lobby._root.is_ancestor_of(focus), mode + ": recovery left keyboard focus on an underlying gameplay control")
		check(host.gameplay_capture.episode_id == capture_episode and host.gameplay_capture.session_id == capture_session, mode + ": interruption tore down capture")
		check(not network.has_pending_actions() and network._pvp_blasts.is_empty(), mode + ": uncertain requests survived interruption")
		check(not network.mine(9, 6) and not network.transfer_money("other", 1) and network.pvp_action("damage", {"amount": 1}) == "", mode + ": disconnected gameplay was accepted")
		lobby.hide_lobby()
		check(lobby.modal and host.paused, mode + ": dismissing recovery re-enabled local gameplay")
		var replacement := await _accept_socket(server)
		if replacement.is_empty():
			break
		var resume := await _read_message(replacement.peer, "join")
		check(str(resume.get("resume_player_id", "")) == "recovery-" + mode, mode + ": retry omitted the prior server-issued player id")
		check(str(resume.get("token", "")) == network.token and str(resume.get("world_id", "")) == "recovery-fixture" and str(resume.get("mode", "")) == mode, mode + ": retry changed authenticated world context")
		network.send_state()
		await process_frame
		replacement.peer.poll()
		check(replacement.peer.get_available_packet_count() == 0, mode + ": recovery replayed gameplay before joined")
		# Losing a retry before joined must stay in the same recovery, not turn
		# into a new ordinary join or replay the discarded actions.
		replacement.stream.disconnect_from_host()
		replacement = await _accept_socket(server)
		if replacement.is_empty():
			break
		var retried := await _read_message(replacement.peer, "join")
		check(str(retried.get("resume_player_id", "")) == "recovery-" + mode and str(retried.get("token", "")) == network.token, mode + ": failed retry lost its authenticated resume proof")
		confirmed.player_money = 125
		if mode == "pvp":
			confirmed.merge({"alive": false, "player_hp": 0, "respawn_at": 1007.0}, true)
		replacement.peer.send_text(JSON.stringify(_fixture_snapshot(network, confirmed, 9)))
		await _load_joined(host, replacement.peer)
		check(network.connected and not network.recovering and not lobby.modal and not host.paused, mode + ": successful joined left recovery or the UI paused")
		check(host.data.player_money == 125 and network.state_revision == 9, mode + ": recovery overwrote confirmed progress with uncertain local edits")
		check(host.coop._private_data == private_data and host.coop._private_world == private_world and private_data.player_money == private_money, mode + ": recovery overwrote the private save context")
		check(host.gameplay_capture.session_id == capture_session and not host.gameplay_capture.episode_id.is_empty() and host.gameplay_capture.episode_id != capture_episode, mode + ": scene reconstruction broke capture session/episode lifecycle")
		if mode == "pvp":
			check(not host.player_alive and host.data.player_hp == 0 and host.coop.pvp.respawn_at == 1007.0, "PvP recovery respawned or protected a server-confirmed dead player")
		replacement.stream.disconnect_from_host()
		await _transport_ended(network)
		if mode == "coop":
			lobby._choose_server("pvp")
			check(not network.recovering and not host.coop.active and network.mode == "pvp", "Mode change did not cancel recovery")
		else:
			var rejected := await _accept_socket(server)
			if rejected.is_empty():
				break
			await _read_message(rejected.peer, "join")
			rejected.peer.send_text(JSON.stringify({"type": "error", "code": "invalid_token", "message": "Fixture session expired."}))
			rejected.peer.close(1008, "invalid_token")
			var deadline := Time.get_ticks_msec() + 5000
			while network.recovering and Time.get_ticks_msec() < deadline:
				rejected.peer.poll()
				await process_frame
			check(not network.recovering and network.token.is_empty() and not host.coop.active, "Auth expiry did not cancel recovery and clear credentials")
		check(host.data == private_data and host.world == private_world, mode + ": terminal/cancelled recovery did not restore the private world")
		host.pending_scene = ""
		host._load_scene("MainMenu")

	# Guests and never-joined accounts retain terminal loss behavior. A server
	# action error must stay visible rather than becoming an automatic retry,
	# and an explicit Leave must remain usable during signed-in recovery.
	for scenario in ["guest", "initial", "action_error", "leave"]:
		var guest: bool = scenario == "guest"
		network.token = "" if guest else "signed-in-recovery-fixture"
		network.mode = "coop"
		network.base_url = endpoint
		network.join_world()
		var connection := await _accept_socket(server)
		if connection.is_empty():
			break
		var join := await _read_message(connection.peer, "join")
		check(not join.has("resume_player_id"), "Guest/initial join unexpectedly sent resume proof")
		if scenario != "initial":
			var state := private_data.coop_snapshot()
			state.merge({"alive": true, "x": 5.5, "y": -3.5}, true)
			connection.peer.send_text(JSON.stringify(_fixture_snapshot(network, state, 1)))
			await _load_joined(host, connection.peer)
		if scenario == "action_error":
			connection.peer.send_text(JSON.stringify({"type": "error", "code": "server_error", "message": "Fixture could not save this action."}))
			connection.peer.close(1011, "Server failure")
			connection.peer.poll()
		else:
			connection.stream.disconnect_from_host()
		await _transport_ended(network)
		if scenario == "leave":
			check(network.recovering, "Explicit Leave fixture did not reach signed-in recovery")
			lobby._leave()
		check(not network.recovering and not network.connected and not network.connecting, scenario + ": terminal/cancelled connection incorrectly recovered")
		check(host.data == private_data and not host.coop.active, scenario + ": terminal/cancelled connection lost private isolation")
		host.pending_scene = ""
		host._load_scene("MainMenu")
	network.leave_world()
	network.base_url = "http://127.0.0.1:1"
	network.token = ""
	server.stop()
