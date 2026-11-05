extends SceneTree

var failures: Array[String] = []

func _initialize() -> void:
	_run.call_deferred()

func _check(value: bool, reason: String) -> void:
	if not value:
		failures.append(reason)

func _pickup_playing(host: Node) -> bool:
	for voice in host.audio.one_shots.get("MineralGet", []):
		if is_instance_valid(voice) and voice.playing:
			return true
	return false

func _feedback_style(host: Node) -> Array:
	var style: Array = []
	for popup in get_nodes_in_group("PlayerPopup"):
		for record in popup.get_meta("native_animators"):
			record.animator.advance(0.1)
		for label in popup.find_children("*", "Label", true, false):
			style.append([label.modulate, label.self_modulate, label.get_theme_color("font_color")])
	return style

func _case(initial: int, returned: int, sold: bool = false) -> Array:
	var host = load("res://scripts/main.gd").new()
	host.agent_axes = Vector2.ZERO
	host.data.settings_file = "user://mineral-feedback-settings-" + str(OS.get_process_id()) + ".json"
	host.data.savefile = "user://mineral-feedback-save-" + str(OS.get_process_id()) + ".data"
	root.add_child(host)
	host.set_process(false)
	host.set_physics_process(false)
	host.pending_scene = ""
	host.data.setNewGameData()
	host.world.generate(12345)
	host._load_scene("Game")
	host.body.freeze = true
	host.coop = load("res://scripts/coop_session.gd").new()
	host.add_child(host.coop)
	host.coop.configure(host)
	host.coop.active = true
	host.data.coop_mode = true
	var network = host.coop.network
	network.connected = false
	network.player_id = "mineral-feedback-fixture"
	network.state_revision = 0
	host.data.player_cargo.Ironium = initial
	host.data.player_money = 100
	host.data.updateCargoWeight()
	network._economic_baseline = host.data.coop_snapshot()
	var state: Dictionary = host.data.coop_snapshot()
	state.player_cargo.Ironium = returned
	if sold:
		host.ui.sellAllMinerals()
	var money: int = host.data.player_money
	var before: int = host.data.player_cargo.Ironium
	var event := {"type":"mined", "accepted":true, "player_id":network.player_id, "request_id":"fresh", "method":"drill", "x":11, "y":6, "ore":"Ironium", "state":state, "state_revision":1}
	network._receive(event)
	var credited := returned > initial
	_check(host.data.player_cargo.Ironium == before + returned - initial, "Mining reconciliation lost or duplicated accounted cargo")
	_check(host.data.player_money == money, "Mining reconciliation changed sale proceeds")
	_check(_pickup_playing(host) == credited, "Pickup audio must mean a mineral was actually loaded")
	_check(get_nodes_in_group("PlayerPopup").size() == 1, "A new mining result must display exactly one outcome")
	var style := _feedback_style(host)
	host.audio.StopAllSounds()
	network._receive(event.duplicate(true))
	_check(get_nodes_in_group("PlayerPopup").size() == 1, "Already-applied mining reply repeated feedback")
	_check(not _pickup_playing(host), "Already-applied mining reply repeated pickup audio")
	_check(host.data.player_money == money and host.data.player_cargo.Ironium == before + returned - initial, "Already-applied mining reply changed economy")
	host.free()
	return style

func _run() -> void:
	var fitting_style := _case(6, 7)
	await process_frame
	var full_style := _case(7, 7)
	await process_frame
	var sold_style := _case(7, 7, true)
	await process_frame
	_check(full_style != fitting_style, "Denied cargo must not use the successful pickup visual style")
	_check(sold_style == full_style, "A sale while a no-fit reply is pending must retain denial feedback")
	for failure in failures:
		push_error(failure)
	print("COOP_MINERAL_FEEDBACK_INTEROP failures=%d" % failures.size())
	quit(0 if failures.is_empty() else 1)
