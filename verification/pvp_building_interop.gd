extends SceneTree

# Offline authority packets exercise the actual native scene/UI/body. The parent
# WS integration separately verifies door validation, damage and safe exit search.
const STEP := 1.0 / 60.0
const DOORS := {
	"FuelShopManager": Vector2(3.2404, -3.637),
	"MineralBuyerManager": Vector2(10.92, -3.6023),
	"UpgradeShopUI": Vector2(24.4346, -3.6228),
	"ItemShopManager": Vector2(30.9, -3.6228),
}
var failures := 0
var host: Node
var network: CoopClient
var player: PortPlayer
var pvp: PvpView

func _initialize() -> void:
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func receive(event: Dictionary) -> void:
	network._receive(JSON.parse_string(JSON.stringify(event)))

func snapshot() -> Dictionary:
	return host.coop.state().duplicate(true)

func acknowledge_flush() -> void:
	receive({"type": "state_ack", "state_revision": network.state_revision, "state": snapshot()})

func authority(script: String, enter: bool, accepted: bool, position: Vector2, message: String = "") -> Dictionary:
	var request := pvp.building_request_id
	check(not request.is_empty(), "Building lifecycle did not submit a request")
	acknowledge_flush()
	var state := snapshot()
	if accepted:
		state.building = script if enter else ""
	state.x = position.x
	state.y = position.y
	state.vx = 0.0
	state.vy = 0.0
	state.drill_x = 0.0
	state.drill_y = 0.0
	var revision := network.state_revision + 1
	receive({"type": "state_sync", "state_revision": revision, "state": state})
	return {"type": "building_result", "accepted": accepted, "building": script, "enter": enter, "request_id": request, "message": message, "state_revision": revision, "state": state}

func check_absent(label: String) -> void:
	check(player.pvp_building_hidden and not player.visual.visible, label + " left the local vehicle visible")
	check(host.body.freeze and host.body.linear_velocity == Vector2.ZERO and host.body.angular_velocity == 0.0, label + " left the native body moving")
	check(host.body.collision_layer == 0 and host.body.collision_mask == 0, label + " left local collisions enabled")
	check(not player.isOnGround and player.pvp_drill_direction() == Vector2.ZERO, label + " retained ground/drill intent")
	for emitter in ["dirt_particle_emitter", "smoke_particle_emitter"]:
		var node: Node = host.bridge.node(player.properties.get(emitter, {}))
		if node is CanvasItem:
			check(not node.is_visible_in_tree(), label + " left particles visible: " + emitter)
	var fuel: float = host.data.player_fuel
	player.tick(STEP)
	player.physics_tick(STEP)
	player.updateFuel()
	check(host.data.player_fuel == fuel, label + " burned fuel")
	var sequence := network.pvp_sequence
	player.loseHP(5)
	check(network.pvp_sequence == sequence, label + " emitted a crash damage request")

func check_outside(label: String) -> void:
	check(pvp.building.is_empty() and not pvp.building_pending and not player.pvp_building_hidden, label + " retained interior state")
	check(player.visual.visible and not host.body.freeze and host.body.collision_layer != 0 and host.body.collision_mask != 0, label + " did not restore a working native vehicle")
	check(host.player_alive and player._alive and not player._pvp_fuel_death_pending, label + " fabricated a death/respawn")

func native_door(script: String) -> Vector2:
	for trigger in host.scene_triggers:
		if str(trigger.script) != "ShopDoorCollision":
			continue
		var owner: String = host.bridge.component_owner(trigger.properties.get("linked_shop_object", {}))
		if not host.bridge.properties(owner, script).is_empty():
			return trigger.area.global_position / PortPlayer.UNITS
	return Vector2(INF, INF)

func trade(script: String) -> void:
	var money: int = host.data.player_money
	match script:
		"FuelShopManager":
			host.fuel_pricing.price_per_gallon = 4.0
			host.fuel_pricing.valid_until = Time.get_unix_time_from_system() + 3600.0
			host.ui.fillFuel()
			check(host.data.player_fuel == host.data.player_max_fuel and host.data.player_money == money - 4, "Protected native fuel purchase did not use normal paid pricing")
		"MineralBuyerManager":
			var value := int(host.data.minerals.Ironium.ore_value) * int(host.data.player_cargo.Ironium)
			host.ui.sellAllMinerals()
			check(int(host.data.player_cargo.Ironium) == 0 and host.data.player_money == money + value, "Protected native mineral sale failed")
		"UpgradeShopUI":
			host.ui.displayCategory("Drill")
			host.ui.displayPotentialUpgrade(1)
			var selection: String = host.ui.current_potential_upgrade
			var price := int(host.data.upgrades.Drill[selection].price)
			host.ui.buyUpgrade()
			check(host.data.current_upgrades.Drill == selection and host.data.player_money == money - price, "Protected native upgrade purchase failed")
		"ItemShopManager":
			var count: int = host.data.player_items.Dynamite
			var price := int(host.data.items.Dynamite.price)
			host.ui.updateItemInformationScreen("Dynamite")
			host.ui.buyItem()
			check(host.data.player_items.Dynamite == count + 1 and host.data.player_money == money - price, "Protected native item purchase failed")

func shops() -> void:
	for script in host.ui.SHOP_SCRIPTS:
		var door := native_door(script)
		check(door.distance_to(DOORS[script]) < 0.001, "Native door differs from authority coordinates: " + script)
		player.position_unity = door
		host.data.player_fuel = host.data.player_max_fuel - 1.0
		host.data.player_cargo.Ironium = 2
		host.data.updateCargoWeight()
		network._economic_baseline = snapshot()
		var entry_pose := player.position_unity
		host.ui.open_shop(host.ui._component(script))
		check(pvp.building_pending and pvp.building.is_empty(), "Stock shop did not request authority: " + script)
		check_absent(script + " pending entry")
		var old := snapshot()
		old.x = entry_pose.x - 2.0
		receive({"type": "pvp_tick", "players": [{"player_id": "self", "state": old}]})
		check_absent(script + " old alive tick")
		check(player.position_unity.distance_to(entry_pose) < 0.0001, "Pending entry was rewound by an old living tick")
		var result := authority(script, true, true, door)
		check_absent(script + " canonical entry before result")
		receive(result)
		check(pvp.building == script and not pvp.building_pending, "Entry result did not settle the matching request")
		check_absent(script + " interior")
		trade(script)
		var money: int = host.data.player_money
		var cargo: Dictionary = host.data.player_cargo.duplicate(true)
		host.ui._close_panel(script)
		check(pvp.building_pending and bool(host.ui.panel_active[script]), "Shop close exposed the vehicle before validation")
		check_absent(script + " pending exit")
		var exterior := Vector2(door.x + 0.7, -3.5)
		result = authority(script, false, true, exterior)
		check_absent(script + " exit sync before result")
		check(player.position_unity.distance_to(exterior) < 0.0001, "Living exit did not apply the authoritative exterior position")
		receive(result)
		check_outside(script + " successful close")
		check(not bool(host.ui.panel_active[script]), "Successful exit did not close the stock shop")
		check(host.data.player_money == money and host.data.player_cargo == cargo, "Building result reconciled trade economy a second time")
		player.position_unity += Vector2.RIGHT
		var moving := player.position_unity
		receive({"type": "state_sync", "state_revision": network.state_revision, "state": result.state})
		check(player.position_unity.distance_to(moving) < 0.0001, "Ordinary living health snapshot rewound movement after exit")
		await process_frame
		for shape in player._shapes:
			check(not shape.disabled, "Successful exit left a native collision shape disabled")

func rejections() -> void:
	var script := "FuelShopManager"
	player.position_unity = Vector2(18.0, -3.5)
	host.ui._set_panel(script, true)
	var result := authority(script, true, false, player.position_unity, "Move closer to the door")
	check_absent("Rejected entry awaiting result")
	receive(result)
	check_outside("Rejected entry")
	check(not bool(host.ui.panel_active[script]), "Rejected entry left a shop panel open")
	player.position_unity = DOORS[script]
	host.ui._set_panel(script, true)
	receive(authority(script, true, true, player.position_unity))
	host.ui._close_panel(script)
	result = authority(script, false, false, player.position_unity, "Exterior blocked")
	receive(result)
	check(pvp.building == script and not pvp.building_pending and bool(host.ui.panel_active[script]), "Blocked exit did not restore the protected menu")
	check_absent("Blocked exit")
	# A forced bridge close must request an exit rather than silently exposing us.
	host.bridge.set_active(host.ui._panel(script), false)
	host.ui._sync_panels()
	check(pvp.building_pending and bool(host.ui.panel_active[script]), "Forced panel close bypassed the authority lifecycle")
	result = authority(script, false, true, Vector2(4.0, -3.5))
	# Entry's old in-flight correction must not move the new exterior pose.
	receive(result)
	var exterior := player.position_unity
	receive({"type": "state_ack", "state_revision": network.state_revision, "motion_seq": network._last_motion_ack, "requested_position": [3.0, -3.5], "state": {"x": 2.0, "y": -3.5}})
	check(player.position_unity == exterior, "Stale motion acknowledgement rewound a validated exit")
	check_outside("Retried blocked exit")
	# A close pressed before entry response is not lost or turned into a false exit.
	host.ui._set_panel(script, true)
	host.ui._close_panel(script)
	receive(authority(script, true, true, player.position_unity))
	check(pvp.building_pending and not pvp._requested_enter, "Close during entry did not defer a real exit request")
	receive(authority(script, false, true, Vector2(4.5, -3.5)))
	check_outside("Close during entry")

func peer_contact_at(position: Vector2) -> Node2D:
	var query := PhysicsPointQueryParameters2D.new()
	query.position = position * PortPlayer.UNITS
	query.collision_mask = 2
	query.exclude = [host.body.get_rid()]
	query.collide_with_areas = false
	for hit in host.body.get_world_2d().direct_space_state.intersect_point(query):
		if hit.collider is Node2D and hit.collider.is_in_group("PvpMiner"):
			return hit.collider
	return null

func menus_and_remote() -> void:
	for script in ["InventoryUIManager", "OptionsUIManager", "HelpUUIManager", "TransmissionManager"]:
		var sequence := network.pvp_sequence
		host.enterShop()
		host.ui._set_panel(script, true)
		check(player.visual.visible and host.body.collision_layer != 0 and not player.pvp_building_hidden, "Generic menu hid/protected the PvP vehicle: " + script)
		check(network.pvp_sequence == sequence and pvp.building.is_empty(), "Generic menu issued a building request: " + script)
		host.ui._set_panel(script, false)
		host.exitShop()
	var state := {"alive": true, "building": "", "x": 4.0, "y": -3.5}
	receive({"type": "pvp_tick", "players": [{"player_id": "remote", "name": "Remote", "state": state}]})
	var remote: Node2D = host.coop._remote_visuals.remote
	var contact := peer_contact_at(Vector2(4.0, -3.5))
	check(remote.visible and contact != null, "Remote fixture did not create a visible solid native peer")
	state.building = "ItemShopManager"
	receive({"type": "pvp_tick", "players": [{"player_id": "remote", "state": state}]})
	check(not remote.visible and peer_contact_at(Vector2(4.0, -3.5)) == null, "Remote interior vehicle remained visible/collidable")
	check(contact == null or not player._is_ground(contact), "Remote interior vehicle remained ground support")
	player.position_unity = Vector2(2.0, -3.5)
	player.moveX = 5.0
	player.isFacingRight = true
	check(player.pvp_drill_direction() == Vector2.ZERO, "Remote interior vehicle remained a drill target")
	state.building = ""
	receive({"type": "pvp_tick", "players": [{"player_id": "remote", "state": state}]})
	check(remote.visible and peer_contact_at(Vector2(4.0, -3.5)) != null, "Remote exit did not restore its native peer")
	receive({"type": "player_left", "player_id": "remote"})

func persistence_and_death() -> void:
	var state := snapshot()
	state.building = "UpgradeShopUI"
	state.x = DOORS.UpgradeShopUI.x
	state.y = DOORS.UpgradeShopUI.y
	pvp.scene_loaded({"state": state, "players": []})
	check(pvp.building == "UpgradeShopUI" and bool(host.ui.panel_active.UpgradeShopUI), "Persisted interior join did not restore the actual shop panel")
	check_absent("Persisted interior join")
	host.ui._close_panel("UpgradeShopUI")
	receive(authority("UpgradeShopUI", false, true, Vector2(25.0, -3.5)))
	# Mining must settle before the entry flush, without exposing the pending pod.
	network._pending_mines[Vector2i(1, 1)] = 0.0
	host.ui._set_panel("ItemShopManager", true)
	check(pvp.building_pending and pvp.building_request_id.is_empty(), "Building entry overtook pending mining economy")
	check_absent("Entry queued behind mining")
	network._pending_mines.clear()
	pvp.tick(STEP)
	check(not pvp.building_request_id.is_empty(), "Queued building entry never submitted after mining settled")
	var stale_request := pvp.building_request_id
	state = snapshot()
	state.alive = false
	state.building = ""
	state.player_hp = 0
	state.player_money = 0
	state.respawn_at = 10.0
	receive({"type": "state_sync", "state_revision": network.state_revision + 1, "state": state})
	var sequence := network.pvp_sequence
	check(not host.player_alive and not pvp.building_pending and pvp.building.is_empty(), "Death retained a pending building lifecycle")
	check(not bool(host.ui.panel_active.ItemShopManager), "Death did not force-close the shop")
	receive({"type": "building_result", "building": "ItemShopManager", "enter": true, "accepted": true, "request_id": stale_request, "state": state})
	check(not host.player_alive and not player.visual.visible and network.pvp_sequence == sequence, "Late building result resurrected the pod or requested a death exit")
	state.alive = true
	state.player_hp = 10
	state.respawn_at = 0.0
	state.x = 5.5
	state.y = -3.5
	receive({"type": "state_sync", "state_revision": network.state_revision + 1, "state": state})
	check_outside("Respawn after pending entry")
	player._pvp_fuel_death_pending = true
	host.ui._set_panel("FuelShopManager", true)
	check(not pvp.building_pending and not bool(host.ui.panel_active.FuelShopManager), "Fuel-death-pending vehicle entered a building")
	check(player._pvp_fuel_death_pending, "Rejected building entry cleared the pending fuel death")
	player._pvp_fuel_death_pending = false

func fuel_entry_race() -> void:
	for paid_refuel in [true, false]:
		player.position_unity = DOORS.FuelShopManager
		host.data.player_fuel = 0.001
		network._economic_baseline = snapshot()
		host.ui._set_panel("FuelShopManager", true)
		# The request was issued while alive, then local exhaustion raced its
		# response. Authority accepts the interior, not a predicted new life.
		host.data.player_fuel = 0.0
		player._pvp_fuel_death_pending = true
		player._pvp_fuel_death_sent = true
		receive(authority("FuelShopManager", true, true, player.position_unity))
		check(not player._pvp_fuel_death_pending and not player._pvp_fuel_death_sent, "Authoritative interior retained a stale fuel death latch")
		check_absent("Fuel exhaustion raced accepted entry")
		if paid_refuel:
			var money: int = host.data.player_money
			host.ui.fillFuel()
			check(host.data.player_fuel == host.data.player_max_fuel and host.data.player_money < money, "Raced fuel exhaustion prevented ordinary paid interior refueling")
		host.ui._close_panel("FuelShopManager")
		receive(authority("FuelShopManager", false, true, Vector2(4.0, -3.5)))
		check_outside("Fuel-race validated exit")
		player.physics_tick(0.02)
		if paid_refuel:
			check(not player._pvp_fuel_death_pending and host.data.player_fuel > 0.0, "Paid fuel-race exit retained an exhaustion latch")
		else:
			check(player._pvp_fuel_death_pending and player._pvp_fuel_death_sent, "Unrefueled exit gained outside fuel immunity")
	var state := snapshot()
	state.alive = false
	state.player_hp = 0
	receive({"type": "state_sync", "state_revision": network.state_revision + 1, "state": state})
	state.alive = true
	state.player_hp = 10
	state.player_fuel = host.data.player_max_fuel
	receive({"type": "state_sync", "state_revision": network.state_revision + 1, "state": state})

func _run() -> void:
	if not OS.get_cmdline_user_args().has("--mode=private"):
		push_error("Building regression requires --mode=private; never connect this fixture to a live world")
		quit(2)
		return
	host = load("res://main.tscn").instantiate()
	root.add_child(host)
	for frame in 3:
		await process_frame
	host.set_process(false)
	network = host.coop.network
	network.mode = "pvp"
	network.player_id = "self"
	host.data.pvp_mode = true
	host.data.coop_mode = true
	for transmission in host.data.transmissions:
		transmission.displayed = true
	host.change_scene("Game")
	host._process(STEP)
	player = host.player
	pvp = host.coop.pvp
	for id in host.bridge.scene.game_objects:
		if not host.bridge.properties(str(id), "MotherShipManager").is_empty():
			host.bridge.set_active(str(id), false)
	player.apply_pvp_life(true, Vector2(5.5, -3.5))
	host.body.gravity_scale = 0.0
	player.can_use_mouse_control = false
	host.coop.active = true
	host.coop.lobby.hide_lobby()
	network.connected = true
	host.data.player_money = 1000000
	host.data.player_hp = host.data.player_max_hp
	host.fuel_pricing._http.cancel_request()
	network._economic_baseline = snapshot()
	await shops()
	rejections()
	menus_and_remote()
	fuel_entry_race()
	persistence_and_death()
	host.coop.active = false
	network.connected = false
	host.free()
	await process_frame
	print("PVP_BUILDING_INTEROP failures=", failures)
	quit(0 if failures == 0 else 1)
