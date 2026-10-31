class_name CoopSession
extends Node

var host: Node
var network: CoopClient
var lobby: CoopLobby
var active := false
var _private_data: GameData
var _private_world: WorldData
var _snapshot: Dictionary = {}
var _remote_visuals: Dictionary = {}

func configure(main_host: Node) -> void:
	host = main_host
	process_mode = Node.PROCESS_MODE_ALWAYS
	network = CoopClient.new()
	add_child(network)
	network.configure(host)
	network.joined_world.connect(_joined)
	network.world_event.connect(_event)
	network.connection_lost.connect(_disconnected)
	lobby = CoopLobby.new()
	add_child(lobby)
	lobby.configure(host, network)
	# Existing deterministic replays retain private mode unless explicitly opted in.
	if network.startup_mode == "coop":
		lobby.show_lobby()
		network.join_world()
	elif network.startup_mode == "private" or not host.replay.is_empty():
		lobby.hide_lobby()

func _joined(snapshot: Dictionary) -> void:
	if not active:
		_private_data = host.data
		_private_world = host.world
	active = true
	_snapshot = snapshot
	host.data = GameData.new()
	host.data.coop_mode = true
	host.data.music_volume = _private_data.music_volume
	host.data.sound_volume = _private_data.sound_volume
	host.data.coop_save_requested.connect(network.send_state)
	host.world = WorldData.new(host.data)
	host.world.generate(int(snapshot.seed))
	for cell in snapshot.get("excavated", []):
		var x := int(cell[0])
		var y := int(cell[1])
		if host.world.inBounds(x, y):
			host.world.instantDigBlock(x, y)
	host.data.level_is_already_generated = true
	host.audio.state = host.data
	host.audio.StopAllSounds()
	host.audio.StopAllMusic()
	lobby.hide_lobby(true)
	host.change_scene("Game")

func scene_loaded() -> void:
	_remote_visuals.clear()
	if active and host.scene_name == "Game":
		var state: Dictionary = _snapshot.get("state", {})
		if not state.is_empty():
			host.data.restore_coop_state(state)
			host.player.position_unity = Vector2(float(state.get("x", 5.5)), float(state.get("y", -3.5)))
			if bool(state.get("facing", false)) != host.player.isFacingRight:
				host.player.flipCharacter()
			if not bool(state.get("alive", true)) or host.data.player_hp <= 0:
				# Rejoin is a new life, as in the private load flow; inventory remains.
				host.data.initPlayer()
				host.player.position_unity = Vector2(5.5, -3.5)
		_sync_peers()
		host.ui.updateAllUI()
		network.send_state()
		print("OREBIT_COOP_WORLD seed=" + str(host.world.generation_seed) + " excavated=" + str(_snapshot.get("excavated", []).size()))
	host.paused = lobby.modal
	lobby.refresh_hud()

func leave() -> bool:
	if not network._pending_mines.is_empty():
		network.status_changed.emit("Waiting for the server to save excavation. Leave again after confirmation.")
		return false
	network.leave_world()
	if active:
		active = false
		_private_data.music_volume = host.data.music_volume
		_private_data.sound_volume = host.data.sound_volume
		host.data = _private_data
		host.world = _private_world
		host.audio.state = host.data
		_private_data = null
		_private_world = null
	_snapshot.clear()
	_remote_visuals.clear()
	return true

func state() -> Dictionary:
	var result: Dictionary = host.data.coop_snapshot()
	result.x = host.player_position.x
	result.y = host.player_position.y
	result.facing = host.player.isFacingRight if host.player != null else false
	result.alive = host.player_alive
	return result

func _disconnected(message: String) -> void:
	leave()
	host.audio.StopAllSounds()
	host.audio.StopAllMusic()
	host.change_scene("MainMenu")
	lobby.disconnected(message)

func _event(event: Dictionary) -> void:
	if not active:
		return
	match str(event.get("type", "")):
		"mined":
			var x := int(event.x)
			var y := int(event.y)
			var accepted := bool(event.get("accepted", false))
			var own := str(event.get("player_id", "")) == network.player_id
			if accepted and host.world.inBounds(x, y):
				var changed: Array = host.world.instantDigBlock(x, y)
				if host.player != null and host.player.data == host.data:
					host.refresh_tiles(changed)
			if own and accepted:
				host.data.restore_coop_state(event.get("state", {}), true)
				var ore := str(event.get("ore", ""))
				if host.data.minerals.has(ore):
					host.createPopup("Excavated " + ore, "IsMineral")
					host.audio.PlaySoundOneShot("MineralGet")
			if host.player != null and host.player.data == host.data:
				host.player.coop_mining_resolved(x, y, accepted, own and str(event.get("method", "")) == "drill")
				host.ui.updateAllUI()
			if own:
				network.send_state()
			print("OREBIT_COOP_MINED x=%d y=%d accepted=%s own=%s" % [x, y, accepted, own])
		"state_sync":
			host.data.restore_coop_state(event.get("state", {}), true)
			host.ui.updateAllUI()
		"player_joined", "player_left", "state":
			_sync_peers()
	lobby.refresh_hud()

func _sync_peers() -> void:
	if host.player == null or host.scene_name != "Game" or host.player.data != host.data:
		return
	for id in _remote_visuals.keys():
		if not network.peers.has(id):
			if is_instance_valid(_remote_visuals[id]):
				_remote_visuals[id].queue_free()
			_remote_visuals.erase(id)
	for id in network.peers:
		if id == network.player_id or _remote_visuals.has(id):
			continue
		var remote := Node2D.new()
		remote.name = "RemoteMiner_" + str(id)
		remote.z_index = 20
		host.world_root.add_child(remote)
		# Authored visuals only: no signals, scripts, groups, player physics or input.
		var visual: Node2D = host.player.visual.duplicate(0)
		visual.name = "Pod"
		visual.position = Vector2.ZERO
		visual.rotation = 0.0
		visual.modulate = Color(0.5, 0.9, 1.0)
		visual.show()
		remote.add_child(visual)
		var label := Label.new()
		label.text = str(network.peers[id].get("name", "Miner"))
		label.position = Vector2(-0.8, -1.0)
		label.scale = Vector2.ONE * 0.018
		label.mouse_filter = Control.MOUSE_FILTER_IGNORE
		remote.add_child(label)
		var peer_state: Dictionary = network.peers[id].get("state", {})
		remote.position = Vector2(float(peer_state.get("x", 5.5)), -float(peer_state.get("y", -3.5)))
		_remote_visuals[id] = remote

func tick(delta: float) -> void:
	if not active:
		return
	for id in _remote_visuals:
		var remote: Node2D = _remote_visuals[id]
		if not is_instance_valid(remote) or not network.peers.has(id):
			continue
		var peer_state: Dictionary = network.peers[id].get("state", {})
		var target := Vector2(float(peer_state.get("x", 5.5)), -float(peer_state.get("y", -3.5)))
		remote.position = remote.position.lerp(target, minf(1.0, delta * 12.0))
		remote.visible = bool(peer_state.get("alive", true))
		var visual := remote.get_node("Pod") as Node2D
		visual.scale.x = absf(visual.scale.x) * (-1.0 if bool(peer_state.get("facing", false)) else 1.0)
