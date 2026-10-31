extends SceneTree

var failures := 0

func _initialize() -> void:
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _run() -> void:
	var host: Node = load("res://main.tscn").instantiate()
	root.add_child(host)
	for frame in range(3):
		await process_frame
	var network: CoopClient = host.coop.network
	var data: GameData = host.data
	data.player_items["Reserve Fuel Tank"] = 2
	data.player_money = 100
	network._mining_baseline = data.coop_snapshot()
	var authoritative := data.coop_snapshot()
	authoritative.player_cargo.Ironium = 1
	# Consumption and a purchase happen after the excavation request but before reply.
	data.player_items["Reserve Fuel Tank"] -= 1
	data.player_money -= 50
	data.setUpgrade("Hull", "Ironium Hull")
	var reconciled := network._reconcile_mining_state(authoritative)
	check(reconciled.player_items["Reserve Fuel Tank"] == 1, "Mining reply duplicated a consumed fuel tank")
	check(reconciled.player_money == 50, "Mining reply rolled back a purchase")
	check(reconciled.current_upgrades.Hull == "Ironium Hull", "Mining reply lost an upgrade")
	check(reconciled.player_cargo.Ironium == 1, "Reconciliation lost the server mining reward")
	data.restore_coop_state(reconciled, true)
	# A second blast confirmation contains cumulative server rewards, not our local edits.
	authoritative.player_cargo.Ironium = 2
	reconciled = network._reconcile_mining_state(authoritative)
	check(reconciled.player_items["Reserve Fuel Tank"] == 1, "Batched mining replayed local consumption twice")
	check(reconciled.player_money == 50 and reconciled.player_cargo.Ironium == 2, "Batched mining lost local spending or duplicated ore")
	network.state_revision = 2
	var sync_events := [0]
	network.world_event.connect(func(_event: Dictionary): sync_events[0] += 1)
	network._receive({"type": "state_sync", "state_revision": 2, "state": authoritative})
	check(sync_events[0] == 0, "Already acknowledged state revision overwrote newer local changes")
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
	host.free()
	data = null
	network = null
	player = null
	lobby = null
	await process_frame
	print("COOP_STATE_INTEROP failures=" + str(failures))
	quit(0 if failures == 0 else 1)
