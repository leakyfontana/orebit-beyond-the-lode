extends SceneTree

# Runs unchanged against the pre-fix player in an isolated project copy.
# Uses the actual native physics body, transmission UI, bonus close path and HP.
const DELTA := 5368709.0 / 268435456.0
var failures := 0
var clock: Object

func _initialize() -> void:
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _host():
	var host = load("res://scripts/main.gd").new()
	# Avoid network and real user saves while retaining the real game scene/UI.
	host.agent_axes = Vector2.ZERO
	host.seed_value = 12345
	host.data.settings_file = "user://spawn-impact-test-settings.json"
	host.data.savefile = "user://spawn-impact-test-save.data"
	root.add_child(host)
	host.set_process(false)
	host.set_physics_process(false)
	host.pending_scene = ""
	host.data.setNewGameData()
	host.data.coop_mode = true
	host.world.generate(12345)
	# Model the shared server's already-excavated earth below the spawn.
	# Keep the floor below the open shaft for positive impact controls.
	for x in range(host.data.earthWidth):
		for y in range(5, 120):
			host.data.my_map[x][y] = [0, 0]
	host.data.level_is_already_generated = true
	host._load_scene("Game")
	# Publish the same player activation as the ship's dropPlayer event.
	host.bridge.set_active(host.player_go, true)
	host.player_alive = true
	host.player.startMovement()
	# Position within the open shaft, away from surface building colliders.
	host.player.position_unity = Vector2(17.5, -8.0)
	host.terrain.follow(host.player.position_unity)
	return host

func _contacts(host) -> int:
	var state := PhysicsServer2D.body_get_direct_state(host.body.get_rid())
	return state.get_contact_count() if state != null else -1

func _step(host) -> void:
	host.player.physics_tick(DELTA)
	check(clock.step_manual(DELTA), "Native physics step failed")
	host.physics_step = clock.get_completed_steps()
	host.player.refresh_ground_after_step()
	host.terrain.follow(host.player.position_unity)

func _fall(host, speed: float) -> void:
	for step in range(500):
		_step(host)
		if absf(host.player.velocity_unity.y) >= speed:
			return
	check(false, "Excavated spawn never reached the required free-fall speed")

func _modal_case(index: int) -> void:
	var host = _host()
	_fall(host, 22.0)
	check(_contacts(host) == 0, "Modal reproduction must begin without solid contact")
	var hp_before: int = host.data.player_hp
	var money_before: int = host.data.player_money
	var speed_before: float = host.player.velocity_unity.y
	host.ui.displayTransmission(index)
	check(host.paused and host.player.is_in_shop, "Transmission did not enter the real modal pause path")
	host.ui._close_panel("TransmissionManager")
	check(not host.paused and not host.player.is_in_shop, "Transmission did not resume gameplay")
	check(host.data.player_money == money_before + (1000 if index == 1 else 3000), "Mr. Natas bonus was not awarded")
	# This is the first fixed update after closing the popup, where the old
	# velocity-only crash detector mistakes cancelVelocity for a lethal impact.
	_step(host)
	print("SPAWN_IMPACT_CASE modal=", index, " falling_velocity=", speed_before, " contacts=", _contacts(host), " hp_before=", hp_before, " hp_after=", host.data.player_hp, " alive=", host.player_alive)
	check(host.data.player_hp == hp_before and host.player_alive, "Closing a bonus popup damaged a falling player without an impact")
	for step in range(5):
		_step(host)
	check(host.data.player_hp == hp_before, "Resumed free fall caused delayed phantom damage")
	host.free()

func _airborne_deceleration_case() -> void:
	var host = _host()
	_fall(host, 22.0)
	var hp_before: int = host.data.player_hp
	# Exercise contact gating independently of modal baseline resets.
	host.player.velocity_unity = Vector2.ZERO
	check(_contacts(host) == 0, "Airborne deceleration control unexpectedly touched terrain")
	host.player.manageCrashVerification()
	print("SPAWN_IMPACT_CASE airborne_deceleration hp_before=", hp_before, " hp_after=", host.data.player_hp)
	check(host.data.player_hp == hp_before, "A velocity change without contact caused crash damage")
	host.free()

func _landing_case(speed: float, should_damage: bool) -> void:
	var host = _host()
	# A real solid floor in an otherwise empty shaft isolates actual impacts.
	var floor_body := StaticBody2D.new()
	floor_body.collision_layer = 1
	floor_body.collision_mask = 2
	floor_body.position = Vector2(17.5, 12.0)
	var floor_shape := CollisionShape2D.new()
	var rectangle := RectangleShape2D.new()
	rectangle.size = Vector2(8.0, 1.0)
	floor_shape.shape = rectangle
	floor_body.add_child(floor_shape)
	host.world_root.add_child(floor_body)
	host.body.gravity_scale = 0.0
	host.body.linear_damp = 0.0
	host.player.position_unity = Vector2(17.5, -9.0)
	host.player.velocity_unity = Vector2(0.0, -speed)
	var hp_before: int = host.data.player_hp
	var contacted := false
	for step in range(150):
		_step(host)
		if _contacts(host) > 0:
			contacted = true
			host.player.manageCrashVerification()
			break
	check(contacted, "Landing control never reached its native solid floor")
	print("SPAWN_IMPACT_CASE landing speed=", speed, " contacted=", contacted, " hp_before=", hp_before, " hp_after=", host.data.player_hp)
	check((host.data.player_hp < hp_before) == should_damage, "Actual landing damage did not match the existing crash speed threshold")
	host.free()

func _run() -> void:
	if not Engine.has_singleton("Box2DClock"):
		push_error("The native Box2DClock extension is required")
		quit(1)
		return
	clock = Engine.get_singleton("Box2DClock")
	if not clock.set_manual_clock(true):
		push_error("Native main-thread manual physics is required")
		quit(1)
		return
	_modal_case(1)
	_modal_case(2)
	_airborne_deceleration_case()
	_landing_case(22.0, true)
	_landing_case(3.0, false)
	clock.set_manual_clock(false)
	print("SPAWN_IMPACT_INTEROP failures=", failures)
	quit(1 if failures else 0)
