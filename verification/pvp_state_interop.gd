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
	network.mode = "pvp"
	network.player_id = "self"
	host.data.pvp_mode = true
	host.change_scene("Game")
	for frame in range(3):
		await process_frame
	host.coop.active = true
	host.player.apply_pvp_life(true, Vector2(5.5, -3.5))
	check(host.player_alive and host.player.visual.visible, "Server spawn did not activate the initially hidden vehicle")
	var data: GameData = host.data
	data.player_money = 1000
	data.player_hp = 10
	network._economic_baseline = host.coop.state()
	var authoritative: Dictionary = host.coop.state().duplicate(true)
	# A real local purchase races an authoritative damage revision.
	data.player_money -= 750
	data.setUpgrade("Hull", "Ironium Hull")
	data.player_hp = 17
	authoritative.player_hp = 9
	network._receive({"type":"state_sync", "state_revision":1, "state":authoritative})
	check(data.player_money == 250 and data.current_upgrades.Hull == "Ironium Hull", "Damage sync discarded an unacknowledged purchase")
	var accepted: Dictionary = host.coop.state().duplicate(true)
	accepted.player_hp = 17
	network._receive({"type":"state_ack", "state_revision":1, "state":accepted})
	accepted.player_money += 55
	accepted.player_hp = 16
	network._receive({"type":"state_sync", "state_revision":2, "state":accepted})
	check(data.player_money == 305 and data.player_hp == 16, "Bag pickup replayed acknowledged spending or lost authoritative damage")
	# Fractional drill damage is rounded only for display, never pending healing.
	var fractional: Dictionary = accepted.duplicate(true)
	for hp in [15.8, 15.6, 15.4]:
		fractional.player_hp = hp
		network._receive({"type":"state_sync", "state_revision":2, "state":fractional})
		check(data.player_hp == 16 and data.player_hp <= data.player_max_hp, "Fractional damage rounding manufactured healing")
	# Generic health/tick snapshots describe older motion, not a teleport order.
	host.player.position_unity = Vector2(8, -3.5)
	accepted.x = 5.5
	accepted.y = -3.5
	network._receive({"type":"state_sync", "state_revision":2, "state":accepted})
	check(host.player.position_unity.distance_to(Vector2(8, -3.5)) < 0.0001, "Health sync rewound a living craft to an old pose")
	network._receive({"type":"pvp_tick", "players":[{"player_id":"self", "state_revision":2, "state":accepted}]})
	check(host.player.position_unity.distance_to(Vector2(8, -3.5)) < 0.0001, "Periodic tick rewound locally simulated flight")
	# Preserve movement after send; multiple in-flight wall corrections apply once.
	network._motion_sequence = 2
	network._sent_motion_offsets[1] = Vector2.ZERO
	network._sent_motion_offsets[2] = Vector2.ZERO
	var motion_state: Dictionary = accepted.duplicate(true)
	motion_state.x = 6.8
	network._receive({"type":"state_ack", "state_revision":2, "motion_seq":1, "requested_position":[7.0,-3.5], "state":motion_state})
	check(host.player.position_unity.distance_to(Vector2(7.8,-3.5)) < 0.0001, "Collision correction discarded movement after the request")
	motion_state.x = 6.9
	network._receive({"type":"state_ack", "state_revision":2, "motion_seq":2, "requested_position":[7.1,-3.5], "state":motion_state})
	check(host.player.position_unity.distance_to(Vector2(7.8,-3.5)) < 0.0001, "Overlapping in-flight corrections compounded the same displacement")
	motion_state.x = 5.0
	network._receive({"type":"state_ack", "state_revision":2, "motion_seq":1, "requested_position":[7.0,-3.5], "state":motion_state})
	check(host.player.position_unity.distance_to(Vector2(7.8,-3.5)) < 0.0001, "Duplicate motion acknowledgement moved the craft twice")
	network._motion_sequence = 3
	network._sent_motion_offsets[3] = network._motion_offset
	host.player.position_unity = Vector2(8.2,-3.5)
	motion_state.x = 7.8
	network._receive({"type":"state_ack", "state_revision":2, "motion_seq":3, "requested_position":[7.8,-3.5], "state":motion_state})
	check(host.player.position_unity.distance_to(Vector2(8.2,-3.5)) < 0.0001, "Accepted motion acknowledgement rewound newer local movement")
	# Predicted explosive consumption must not be applied twice on confirmation.
	data.player_items.Dynamite = 2
	network._economic_baseline = host.coop.state()
	data.player_items.Dynamite -= 1
	network._pvp_blasts["one"] = "Dynamite"
	network._receive({"type":"blast_result", "request_id":"one", "accepted":true})
	accepted = host.coop.state().duplicate(true)
	accepted.player_items.Dynamite = 1
	network._receive({"type":"state_sync", "state_revision":3, "state":accepted})
	check(data.player_items.Dynamite == 1, "Confirmed blast consumed a second explosive")
	data.player_items.Dynamite -= 1
	network._pvp_blasts["two"] = "Dynamite"
	network._receive({"type":"blast_result", "request_id":"two", "accepted":false})
	network._receive({"type":"state_sync", "state_revision":3, "state":accepted})
	check(data.player_items.Dynamite == 1, "Rejected blast lost an explosive")
	# Death discards pending spending, and respawn cannot resurrect upgrades/cash.
	data.player_money -= 5
	var dead: Dictionary = accepted.duplicate(true)
	dead.alive = false
	dead.player_money = 0
	dead.player_hp = 0
	dead.respawn_at = 10
	network._receive({"type":"state_sync", "state_revision":4, "state":dead})
	check(not host.player_alive and data.player_money == 0, "Death retained predicted cash or left the body alive")
	var respawn: Dictionary = dead.duplicate(true)
	respawn.alive = true
	respawn.player_hp = 10
	respawn.current_upgrades = GameData.DEFAULT_UPGRADES.duplicate()
	respawn.respawn_at = 0
	network._receive({"type":"state_sync", "state_revision":5, "state":respawn})
	check(host.player_alive and data.player_hp == 10 and data.player_money == 0 and data.current_upgrades == GameData.DEFAULT_UPGRADES, "Respawn restored previous-life cash/upgrades")
	_check_bag_credit(host, network)
	host.coop.active = false
	host.free()
	await process_frame
	print("PVP_STATE_INTEROP failures=", failures)
	quit(0 if failures == 0 else 1)

func _receive_wire(network: CoopClient, event: Dictionary) -> void:
	# Socket packets are independent JSON snapshots, not shared Dictionaries.
	network._receive(JSON.parse_string(JSON.stringify(event)))

func _check_money_hud(host: Node, expected: int, text: String) -> void:
	# Exercise the original animated counter without advancing vehicle physics.
	for frame in range(360):
		host.ui.tick(1.0 / 60.0)
	check(host.ui.displayed_money == expected, "HUD counter did not converge to the authoritative bag balance")
	var money_id: String = host.ui.bridge.component_owner(host.ui._properties("UIManager").MoneyUI)
	var money_label: Label = host.ui.bridge.texts.get(money_id)
	check(money_label != null, "Native scene has no money HUD label")
	if money_label != null:
		check(money_label.text == text, "Native money HUD did not display the collected bag balance")

func _check_bag_credit(host: Node, network: CoopClient) -> void:
	var data: GameData = host.data
	data.player_money = 5000
	data.player_items.Dynamite = 0
	network._economic_baseline = host.coop.state().duplicate(true)
	# Purchases now occur inside authoritative buildings, where bags cannot be
	# collected. Complete the real shop purchase and exit before the cash drop.
	host.player.position_unity = Vector2(30.9, -3.5)
	var interior: Dictionary = host.coop.state().duplicate(true)
	interior.building = "ItemShopManager"
	var purchase_revision := network.state_revision + 1
	_receive_wire(network, {"type":"state_sync", "state_revision":purchase_revision, "state":interior})
	host.ui.currently_selected_item = "Dynamite"
	host.ui.buyItem()
	check(data.player_money == 3000 and data.player_items.Dynamite == 1, "Native building purchase was not applied before bag collection")
	_check_money_hud(host, 3000, "$3 000")
	var purchased: Dictionary = host.coop.state().duplicate(true)
	purchased.building = "ItemShopManager"
	_receive_wire(network, {"type":"state_ack", "state_revision":purchase_revision, "state":purchased})
	var before := purchased.duplicate(true)
	before.building = ""
	var previous_revision := purchase_revision + 1
	_receive_wire(network, {"type":"state_sync", "state_revision":previous_revision, "state":before})
	check(host.coop.pvp.building.is_empty() and host.player.visual.visible, "Purchased vehicle did not return outside before cash pickup")
	var position := Vector2(8.2, -3.5)
	host.player.position_unity = position
	var credit_revision := previous_revision + 1
	var credit := before.duplicate(true)
	credit.player_money += 55
	_receive_wire(network, {"type":"state_sync", "state_revision":credit_revision, "state":credit})
	check(data.player_money == 3055 and data.player_items.Dynamite == 1, "Bag credit erased a completed building purchase")
	var tick := {"type":"pvp_tick", "players":[{"player_id":"self", "state_revision":credit_revision, "state":credit}], "bags":[]}
	_receive_wire(network, tick)
	_check_money_hud(host, 3055, "$3 055")
	# Repeated snapshots and an older acknowledgement cannot erase or double cash.
	_receive_wire(network, {"type":"state_sync", "state_revision":credit_revision, "state":credit})
	_receive_wire(network, tick)
	_receive_wire(network, {"type":"state_ack", "state_revision":previous_revision, "state":before})
	check(data.player_money == 3055 and data.player_items.Dynamite == 1, "Repeated bag snapshots or stale acknowledgement changed purchased inventory/cash")
	check(int(network._economic_baseline.player_money) == 3055, "Stale acknowledgement replaced the post-pickup economic baseline")
	var accepted: Dictionary = host.coop.state().duplicate(true)
	accepted.x = credit.x
	accepted.y = credit.y
	_receive_wire(network, {"type":"state_ack", "state_revision":credit_revision, "state":accepted})
	var acknowledged_tick := {"type":"pvp_tick", "players":[{"player_id":"self", "state_revision":credit_revision, "state":accepted}], "bags":[]}
	_receive_wire(network, acknowledged_tick)
	_receive_wire(network, {"type":"state_ack", "state_revision":credit_revision, "state":accepted})
	_receive_wire(network, {"type":"state_sync", "state_revision":credit_revision, "state":accepted})
	_receive_wire(network, acknowledged_tick)
	check(data.player_money == 3055 and data.player_items.Dynamite == 1, "Next acknowledgement/tick erased bag cash or doubled a completed purchase")
	check(host.player.position_unity.distance_to(position) < 0.0001, "Bag sync/tick/ack rewound the locally simulated vehicle")
	_check_money_hud(host, 3055, "$3 055")
