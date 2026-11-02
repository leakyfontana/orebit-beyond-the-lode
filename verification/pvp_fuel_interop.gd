extends SceneTree

# Isolated actual-Game consumer regression. The shipped fixed-update callback
# drains positive fuel through zero; the shipped main loop advances the original
# DeadPlayer native AnimationTree and sprite tracks. Only incoming authority
# snapshots are supplied, as in pvp_state_interop.gd. There is no mock server,
# socket, account, save, live world, fabricated animation or direct kill call.
# verification/tools/Godot.app/Contents/MacOS/Godot --headless --path godot --script ../verification/pvp_fuel_interop.gd -- --mode=private --coop-url=http://127.0.0.1:1 --coop-token= --seed=1

const STEP := 0.02
const CORPSE_CONTROLLER := "eec0bcb77c401d14caf4788cc312c99c"
const DEATH_SOUNDS := ["LowFuelWarning", "VeryLowFuelWarning", "Drill", "IdlePlayer", "RotorPlayer"]
var failures := 0
var host: Node
var network: CoopClient
var player: PortPlayer

func _initialize() -> void:
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func receive(event: Dictionary) -> void:
	# Wire snapshots do not alias the mutable dictionaries used by this fixture.
	network._receive(JSON.parse_string(JSON.stringify(event)))

func game(pvp: bool, cooperative: bool) -> void:
	host.coop.active = false
	network.connected = false
	network.peers.clear()
	host.coop._remote_visuals.clear()
	host.audio.StopAllSounds()
	host.data = GameData.new()
	host.data.pvp_mode = pvp
	host.data.coop_mode = cooperative
	for transmission in host.data.transmissions:
		transmission.displayed = true
	host.world = WorldData.new(host.data)
	host.audio.state = host.data
	network.mode = "pvp" if pvp else "coop"
	network.state_revision = 0
	host.change_scene("Game")
	host._process(STEP)
	player = host.player
	# Bypass only the unrelated arrival cinematic; use the real craft, body,
	# serialized collision shapes, UI, native animator and fixed-update method.
	for id in host.bridge.scene.game_objects:
		if not host.bridge.properties(str(id), "MotherShipManager").is_empty():
			host.bridge.set_active(str(id), false)
	player.apply_pvp_life(true, Vector2(18.5, 6.5))
	player.position_unity = Vector2(18.5, 6.5)
	player.velocity_unity = Vector2.ZERO
	player.can_use_mouse_control = false
	host.body.gravity_scale = 0.0
	host.coop.active = cooperative
	host.coop.lobby.hide_lobby()
	host.data.setUpgrade("Hull", "Ironium Hull")
	host.data.player_hp = 17
	host.data.player_money = 3055
	host.data.player_items.Dynamite = 2
	host.data.player_cargo.Ironium = 3
	host.data.updateCargoWeight()
	host.data.player_fuel = 0.0033
	player.moveX = 0.0
	player.moveY = 0.0
	network._economic_baseline = host.coop.state().duplicate(true)
	network.connected = pvp
	check(corpses().is_empty(), "Fresh scene retained a previous-life native corpse")
	check(not death_screen().visible, "Fresh scene started with the private game-over screen")
	check(not host.body.freeze and host.body.collision_mask != 0, "Fuel fixture did not activate the native vehicle")
	# Exercise actual consumers rather than asserting calls to stop helpers.
	player._activate_attack("dynamite_hitbox")
	player._activate_attack("C4_hitbox")
	check(player._attack_areas.size() == 2, "Serialized native explosive attack areas were not created")
	for attack in player._attack_areas.values():
		attack.hit = true
		check(attack.area.collision_mask != 0, "Attack fixture started disabled")
	for sound in DEATH_SOUNDS:
		host.audio.PlaySound(sound)
		host.audio.PlaySoundOneShot(sound)
		check(host.audio._sound_is_playing(sound), "Native sound fixture did not start " + sound)

func death_screen() -> CanvasItem:
	return host.bridge.node(player.properties.death_screen) as CanvasItem

func corpses() -> Array[Node2D]:
	var result: Array[Node2D] = []
	for child in host.world_root.get_children():
		if not child.has_meta("native_animators") or child.is_queued_for_deletion():
			continue
		for record in child.get_meta("native_animators"):
			var animator: NativeAnimator = record.animator
			if animator._set.controller_id == CORPSE_CONTROLLER:
				result.append(child)
				break
	return result

func corpse_record(corpse: Node2D) -> Dictionary:
	for record in corpse.get_meta("native_animators"):
		var animator: NativeAnimator = record.animator
		if animator._set.controller_id == CORPSE_CONTROLLER:
			return record
	return {}

func deplete(label: String) -> void:
	# These are the exact production fixed updates that call updateFuel(), not
	# killPlayer() or a replacement drain. Two ticks stay positive; the third
	# crosses zero at the authored idle consumption rate of .08 gallons/second.
	for tick in 2:
		var previous: float = host.data.player_fuel
		player.physics_tick(STEP)
		check(host.data.player_fuel < previous and host.data.player_fuel > 0.0, label + " did not naturally drain positive fuel")
		check(host.player_alive and corpses().is_empty(), label + " died before fuel crossed zero")
	player.physics_tick(STEP)
	check(host.data.player_fuel <= 0.0, label + " fixed update did not cross zero fuel")

func check_dead(label: String) -> void:
	check(not host.player_alive, label + " left the native vehicle alive")
	check(host.body.freeze and host.body.linear_velocity == Vector2.ZERO and host.body.angular_velocity == 0.0, label + " did not freeze and stop the native body")
	check(host.body.collision_layer == 0 and host.body.collision_mask == 0, label + " left dead-body collisions enabled")
	check(not player.visual.visible, label + " left the living vehicle visible")
	for attack in player._attack_areas.values():
		check(attack.area.collision_mask == 0 and not attack.hit, label + " retained an active native attack area")
	for sound in DEATH_SOUNDS:
		check(not host.audio._sound_is_playing(sound), label + " retained native death sound " + sound)
		check(host.audio.one_shots[sound].is_empty(), label + " retained one-shot voices for " + sound)
	check(host.audio.one_shots.KillPlayer.size() == 1, label + " did not play exactly one original KillPlayer voice")
	check(corpses().size() == 1, label + " did not spawn exactly one original DeadPlayer prefab")
	check(not host.paused, label + " paused the authored death animation")

func animation_trace(label: String) -> Array:
	var trace: Array = []
	var found := corpses()
	if found.size() != 1:
		return trace
	var corpse: Node2D = found[0]
	var record := corpse_record(corpse)
	var animator: NativeAnimator = record.animator
	check(record.root.is_visible_in_tree(), label + " native corpse root is hidden")
	check(corpse.global_position.distance_to(player.position_unity * PortPlayer.UNITS) < 0.0001, label + " corpse did not spawn at the fuel-depleted craft")
	var sprites := corpse.find_children("*", "Sprite2D", true, false)
	check(not sprites.is_empty(), label + " corpse has no native sprite renderer")
	var textures: Dictionary = {}
	var states: Array[String] = []
	var unobscured_frames := 0
	var respawn_card_frames := 0
	for frame in 180:
		var state_before: String = animator.current_state
		host._process(STEP)
		check(corpses().size() == 1, label + " lost or duplicated its death presentation while dead")
		if label == "pvp":
			var overlay: PvpView = host.coop.pvp
			check(overlay._respawn_root.is_visible_in_tree() and overlay._respawn_root.mouse_filter == Control.MOUSE_FILTER_STOP, "PvP death lost its input shield while the native sequence played")
			# Main updates the overlay before advancing native animators, so
			# presentation on this frame corresponds to the pre-advance state.
			var initial_clip := state_before.is_empty() or state_before == "DeadPlayer_Anim"
			check(overlay._respawn_panel.is_visible_in_tree() != initial_clip, "PvP respawn card obscured the original death clip or stayed hidden during the aftermath")
			for shade: ColorRect in overlay._respawn_root.find_children("*", "ColorRect", true, false):
				check(shade.is_visible_in_tree() != initial_clip, "PvP overlay shade obscured the original death clip or stayed hidden during the aftermath")
			check(overlay.respawn_at == 110.0, "Native death presentation restarted the authoritative respawn deadline")
			if initial_clip:
				unobscured_frames += 1
			else:
				respawn_card_frames += 1
		var poses: Array = []
		for sprite: Sprite2D in sprites:
			var texture_path := sprite.texture.resource_path if sprite.texture != null else ""
			textures[texture_path] = true
			poses.append([texture_path, sprite.transform, sprite.modulate, sprite.visible])
		trace.append([animator.current_state, animator.state_time, poses])
		if not states.has(animator.current_state):
			states.append(animator.current_state)
	check(textures.size() >= 4 and not textures.has(""), label + " original corpse sprite frames never advanced")
	check(states.has("DeadPlayer_Anim") and states.has("DeadPlayerPart2_Anim"), label + " did not traverse the authored initial death clip and looping aftermath")
	if label == "pvp":
		check(unobscured_frames >= 100 and respawn_card_frames >= 20, "PvP did not retain both an unobscured native death phase and the normal aftermath respawn card")
	print("PVP_FUEL_NATIVE mode=", label, " states=", states, " textures=", textures.size(), " samples=", trace.size())
	return trace

func private_death(cooperative: bool) -> Array:
	var label := "coop" if cooperative else "private"
	game(false, cooperative)
	deplete(label)
	check_dead(label)
	check(death_screen().visible, label + " lost the original private game-over screen")
	check(not host.coop.pvp._respawn_root.visible, label + " displayed the PvP respawn overlay")
	check(host.data.player_money == 3055 and host.data.player_hp == 17, label + " changed the original fuel-death economy or upgraded hull")
	return animation_trace(label)

func pvp_death(reference: Array) -> void:
	game(true, true)
	var alive: Dictionary = host.coop.state().duplicate(true)
	var sequence_before: int = network.pvp_sequence
	var motion_before: int = network._motion_sequence
	deplete("pvp")
	check(host.player_alive and host.data.player_hp == 17 and host.data.player_money == 3055, "Fuel request fabricated authoritative damage, death or cash loss before confirmation")
	check(host.body.freeze and host.body.linear_velocity == Vector2.ZERO, "Pending fuel death did not stop local vehicle motion")
	check(network.pvp_sequence == sequence_before + 1, "Natural zero fuel did not request one fatal PvP action for the upgraded 17HP hull")
	check(network._motion_sequence == motion_before + 1, "Fuel death did not flush the latest craft state before the fatal request")
	for tick in 12:
		player.physics_tick(STEP)
	# An ordinary in-flight living snapshot must not re-arm a zero-fuel request.
	receive({"type":"state_sync", "state_revision":0, "state":alive})
	var pending_position: Vector2 = player.position_unity
	for code in [KEY_D, KEY_W]:
		var event := InputEventKey.new()
		event.physical_keycode = code
		event.pressed = true
		Input.parse_input_event(event)
	Input.flush_buffered_events()
	for frame in 12:
		host._process(STEP)
	for code in [KEY_D, KEY_W]:
		var event := InputEventKey.new()
		event.physical_keycode = code
		event.pressed = false
		Input.parse_input_event(event)
	Input.flush_buffered_events()
	check(host.player_alive and host.body.freeze and host.body.linear_velocity == Vector2.ZERO and player.position_unity.distance_to(pending_position) < 0.0001, "In-flight living snapshot resumed flight controls while fuel death was pending")
	check(network.pvp_sequence == sequence_before + 1, "Repeated depleted updates or a living snapshot duplicated the pending fatal request")
	var dead: Dictionary = alive.duplicate(true)
	dead.alive = false
	dead.player_hp = 0
	dead.player_fuel = 0.0
	dead.player_money = 0
	dead.respawn_at = 110.0
	receive({"type":"state_sync", "state_revision":1, "state":dead})
	var tick := {"type":"pvp_tick", "server_time":100.0, "players":[{"player_id":network.player_id, "state_revision":1, "state":dead}], "bags":[]}
	receive(tick)
	check_dead("pvp")
	check(not death_screen().visible, "PvP exposed the private game-over/restart screen")
	check(host.coop.pvp._respawn_root.is_visible_in_tree() and host.coop.pvp._respawn_root.mouse_filter == Control.MOUSE_FILTER_STOP, "Authoritative death did not immediately block input through the PvP overlay")
	check(not host.coop.pvp._respawn_panel.is_visible_in_tree(), "Initial PvP respawn card obscured the original native fuel-death animation")
	for shade: ColorRect in host.coop.pvp._respawn_root.find_children("*", "ColorRect", true, false):
		check(not shade.is_visible_in_tree(), "Initial PvP overlay shade obscured the original native fuel-death animation")
	check(host.coop.pvp.respawn_at == 110.0 and host.coop.pvp.server_time == 100.0, "PvP native death phase did not retain the normal ten-second authoritative respawn deadline")
	var original_corpses := corpses()
	var corpse: Node2D = original_corpses[0] if original_corpses.size() == 1 else null
	receive({"type":"state_sync", "state_revision":1, "state":dead})
	receive(tick)
	check(corpses().size() == 1 and corpses()[0] == corpse, "Duplicate authoritative death snapshot recreated the corpse")
	check(host.audio.one_shots.KillPlayer.size() == 1, "Duplicate authoritative death snapshot replayed the death sound")
	var trace := animation_trace("pvp")
	check(not reference.is_empty() and trace == reference, "PvP native corpse sprite/transform/state timeline differs from original private fuel death")
	# The overlay's clock is presentation only: expiration cannot locally revive.
	host.coop.pvp.tick(10.5)
	check(not host.player_alive and host.body.freeze and not player.visual.visible, "Respawn countdown expiry locally revived the craft without authority")
	check(host.coop.pvp._respawn_root.visible and host.coop.pvp._respawn_time.text == "...", "Countdown expiry did not wait for server respawn confirmation")
	var stock := GameData.new()
	stock.initPlayer()
	stock.player_money = 0
	var respawn := stock.coop_snapshot()
	respawn.alive = true
	respawn.x = 5.5
	respawn.y = -3.5
	respawn.respawn_at = 0.0
	receive({"type":"state_sync", "state_revision":2, "state":respawn})
	check(host.player_alive and player.visual.visible and not host.body.freeze, "Server respawn did not reactivate the native vehicle")
	check(host.body.collision_layer != 0 and host.body.collision_mask != 0, "Server respawn did not restore native body collisions")
	check(player.position_unity.distance_to(Vector2(5.5, -3.5)) < 0.0001, "Server respawn did not apply its authoritative spawn pose")
	check(host.data.current_upgrades == GameData.DEFAULT_UPGRADES and host.data.player_hp == stock.player_max_hp and host.data.player_fuel == stock.player_max_fuel, "Server respawn did not restore full stock hull/fuel/upgrades")
	check(host.data.player_money == 0 and host.data.player_items == stock.player_items and host.data.player_cargo == stock.player_cargo and host.data.player_current_cargo_weight == 0, "Server respawn restored previous-life cash/items/cargo")
	check(not host.coop.pvp._respawn_root.visible and not death_screen().visible, "Server respawn retained a death overlay")
	check(corpses().is_empty() and (not is_instance_valid(corpse) or corpse.is_queued_for_deletion() or not corpse.is_visible_in_tree()), "Server respawn retained the previous-life native corpse")
	# The next life must be able to naturally request fuel death again.
	host.data.player_fuel = 0.0001
	player.physics_tick(STEP)
	check(network.pvp_sequence == sequence_before + 2, "Authoritative respawn did not re-arm fuel death for the next life")

func _run() -> void:
	if not OS.get_cmdline_user_args().has("--mode=private"):
		push_error("Fuel regression requires --mode=private; never connect this fixture to a live world")
		quit(2)
		return
	host = load("res://main.tscn").instantiate()
	root.add_child(host)
	host.set_process(false)
	host.set_physics_process(false)
	network = host.coop.network
	network.set_process(false)
	network.token = ""
	network.username = ""
	network.base_url = "http://127.0.0.1:1"
	network.player_id = "fuel-fixture-self"
	if host.fuel_pricing != null:
		host.fuel_pricing.set_process(false)
	var reference := private_death(false)
	var cooperative := private_death(true)
	check(not reference.is_empty() and cooperative == reference, "Co-op native fuel-death timeline differs from private mode")
	pvp_death(reference)
	host.coop.active = false
	network.connected = false
	host.free()
	await process_frame
	print("PVP_FUEL_INTEROP failures=", failures)
	quit(0 if failures == 0 else 1)
