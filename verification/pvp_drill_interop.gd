extends SceneTree

# Uses the shipped scene, authored native AnimationTree, serialized block
# detectors, terrain and manual Box2D clock. Only incoming server snapshots are
# supplied by this fixture: no server, saved account, bot or live world is used.
# Run from the repository root:
# verification/tools/Godot.app/Contents/MacOS/Godot --headless --path godot --script ../verification/pvp_drill_interop.gd -- --mode=private --coop-url=http://127.0.0.1:1 --coop-token=
# Deliberately slow horizontal approach permits the complete authored closing
# animation before contact. Zero gravity isolates it from landing; the actual
# flight force, native body integration and player control path remain enabled.

const STEP := 0.02
var failures := 0
var host: Node
var network: CoopClient
var player: PortPlayer
var _held: Array[Key] = []
var _states: Array[String] = []

func _initialize() -> void:
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func key(code: Key, pressed: bool) -> void:
	var event := InputEventKey.new()
	event.physical_keycode = code
	event.pressed = pressed
	Input.parse_input_event(event)
	Input.flush_buffered_events()
	if pressed and not _held.has(code):
		_held.append(code)
	elif not pressed:
		_held.erase(code)

func release_keys() -> void:
	for code in _held.duplicate():
		key(code, false)

func step(count: int = 1) -> void:
	for frame in count:
		host._process(STEP)
		if player != null and not _states.has(player.animator.current_state):
			_states.append(player.animator.current_state)

func condition(name: String) -> bool:
	return bool(player.animator.native_parameters.get(name, false))

func drill_direction() -> Vector2:
	var state: Dictionary = host.coop.state()
	return Vector2(float(state.get("drill_x", 0)), float(state.get("drill_y", 0)))

func game(pvp: bool, cooperative: bool) -> void:
	release_keys()
	host.coop.active = false
	network.peers.clear()
	host.coop._remote_visuals.clear()
	host.data = GameData.new()
	host.data.pvp_mode = pvp
	host.data.coop_mode = cooperative
	host.world = WorldData.new(host.data)
	# Story UI is unrelated to this fixture; mark it acknowledged rather than
	# letting a real depth trigger pause private/co-op mining midway through.
	for transmission in host.data.transmissions:
		transmission.displayed = true
	host.audio.state = host.data
	network.mode = "pvp" if pvp else "coop"
	host.change_scene("Game")
	host._process(STEP)
	player = host.player
	player.apply_pvp_life(true, Vector2(30.75, 12.5))
	player.position_unity = Vector2(30.75, 12.5)
	player.velocity_unity = Vector2.ZERO
	player.can_use_mouse_control = false
	host.body.gravity_scale = 0.0
	host.coop.active = cooperative
	_states.clear()

func peer(position: Vector2, alive: bool = true, velocity: Vector2 = Vector2.ZERO) -> void:
	# Traverse the production snapshot/event path, including its real remote
	# collision body. Snap the fixture's authoritative pose, not a lerped trail.
	network._receive({"type": "pvp_tick", "players": [{
		"player_id": "fixture-peer", "name": "Drill fixture", "state": {
			"x": position.x, "y": position.y, "alive": alive, "facing": true,
			"vx": velocity.x, "vy": velocity.y,
		},
	}]})
	if host.coop._remote_visuals.has("fixture-peer"):
		var remote: Node2D = host.coop._remote_visuals["fixture-peer"]
		if remote is RigidBody2D:
			# Snapshot jumps are not simulated player motion. Static freeze keeps
			# solid contact without sweeping a teleported hull across our craft.
			remote.freeze_mode = RigidBody2D.FREEZE_MODE_STATIC
		remote.position = position * PortPlayer.UNITS
		if remote is RigidBody2D:
			PhysicsServer2D.body_set_state(remote.get_rid(), PhysicsServer2D.BODY_STATE_TRANSFORM, remote.global_transform)

func no_side_engagement(label: String, offset: Vector2, alive: bool = true) -> void:
	peer(player.position_unity + offset, alive)
	step()
	var direction := drill_direction()
	var detail := " direction=%s pose=%s peer=%s facing=%s ground=%s terrain=%s" % [direction, player.position_unity, network.peers["fixture-peer"].state, player.isFacingRight, player.isOnGround, player.is_digging_side]
	check(direction == Vector2.ZERO, label + " advertised horizontal drill intent" + detail)
	check(not condition("IsDiggingSide"), label + " deployed the side drill" + detail)
	for frame in 35:
		# Hold the boundary in world space relative to this still-flying craft;
		# otherwise its ascent can legitimately bring an off-axis peer in range.
		peer(player.position_unity + offset, alive)
		step()
	check(not condition("IsDiggingSide"), label + " retained side deployment")

func air_approach() -> void:
	game(true, true)
	host.data.player_horizontal_speed = 0.2
	host.data.player_vertical_speed = 0.5
	# The authored player starts facing left. Do not force an animator state or
	# any flight/drill/ground condition: input and physics must reach it.
	key(KEY_W, true)
	step(35)
	check(not player.isOnGround and player.isFlying, "Air fixture did not establish native flight")
	check(player.animator.current_state == "FlyingBladeRotation_Animation" and condition("FlyingBladesAreOut"), "Air fixture never reached the authored open-rotor state")
	var target_x := player.position_unity.x - 1.4
	peer(Vector2(target_x, player.position_unity.y))
	step()
	check(drill_direction() == Vector2.ZERO and not condition("IsDiggingSide"), "Idle contact with a live peer deployed a drill")
	key(KEY_A, true)
	var before := player.position_unity
	var physics_before: int = host.physics_step
	var engaged_before_contact := false
	var closing_before_contact := false
	var spinning_steps := 0
	var unfrozen := true
	var airborne := true
	for frame in 65:
		peer(Vector2(target_x, player.position_unity.y))
		step()
		var gap := absf(player.position_unity.x - target_x)
		engaged_before_contact = engaged_before_contact or (gap > 0.9 and condition("IsDiggingSide") and drill_direction() == Vector2.LEFT)
		closing_before_contact = closing_before_contact or (gap > 0.9 and player.animator.current_state == "FlyingClosingBlades_Animation")
		if player.animator.current_state == "MovingOnGround_Animation" and condition("IsDiggingSide"):
			spinning_steps += 1
		unfrozen = unfrozen and not host.body.freeze and not player.is_digging_side and not player.is_digging_bottom
		airborne = airborne and not player.isOnGround and not condition("IsOnGround")
	check(engaged_before_contact, "Airborne forward approach failed to deploy drill intent before peer contact")
	check(closing_before_contact, "Airborne engagement never traversed native FlyingClosingBlades before contact")
	check(spinning_steps >= 8 and not condition("FlyingBladesAreOut"), "Airborne approach did not sustain the native spinning side-drill animation")
	check(airborne, "Melee engagement fabricated grounded animation or physics")
	check(unfrozen, "Melee engagement entered terrain-dig freeze or disabled native physics")
	check(host.physics_step > physics_before + 50 and player.position_unity.x < before.x - 0.1, "Side-drill deployment froze horizontal flight")
	check(player.position_unity.y > before.y + 0.1 and player.velocity_unity.y > 0.1 and player.moveY > 0.0, "Side-drill deployment froze upward flight controls/force")
	check(absf(player.position_unity.x - target_x) > 0.9, "Approach fixture reached physical peer contact before deployment assertions")
	# Ballistic drift is insufficient evidence of working flight controls.
	# Clear ascent, then demand new lift from a fresh press while melee stays
	# engaged, with no gravity or contact available to supply that velocity.
	key(KEY_W, false)
	step(2)
	check(player.moveY == 0.0 and condition("IsDiggingSide"), "Active melee ignored release of the flight control")
	player.velocity_unity = Vector2(player.velocity_unity.x, 0.0)
	var lift_start := player.position_unity
	key(KEY_W, true)
	for frame in 8:
		peer(Vector2(target_x, player.position_unity.y))
		step()
	check(player.moveY > 0.0 and player.velocity_unity.y > 0.1 and player.position_unity.y > lift_start.y + 0.005, "Deployed melee drill blocked fresh native flight thrust")
	check(condition("IsDiggingSide") and not host.body.freeze, "Fresh flight input cancelled or froze the deployed side drill")
	# Fresh release must remove intent even with the last target still in reach.
	key(KEY_A, false)
	peer(player.position_unity + Vector2.LEFT * 1.2)
	step()
	check(drill_direction() == Vector2.ZERO and not condition("IsDiggingSide"), "Released movement retained stale airborne drill input")
	step(35)
	check(player.animator.current_state == "FlyingBladeRotation_Animation", "Released melee failed to restore the authored flight animation")
	key(KEY_A, true)
	no_side_engagement("Peer behind facing/movement", Vector2.RIGHT * 1.2)
	no_side_engagement("Dead forward peer", Vector2.LEFT * 1.2, false)
	no_side_engagement("Distant forward peer", Vector2.LEFT * 5.0)
	no_side_engagement("Forward peer outside lateral bounds", Vector2(-1.2, 1.2))
	# Opposite input must not attack through the old facing during a real flip.
	peer(player.position_unity + Vector2.RIGHT * 1.2)
	key(KEY_A, false)
	key(KEY_D, true)
	step()
	if not player.isFacingRight:
		check(drill_direction() == Vector2.ZERO and not condition("IsDiggingSide"), "Unfinished facing flip attacked a peer behind the old facing")
	else:
		check(false, "Facing-boundary fixture skipped the authored flip interval")
	print("PVP_DRILL_AIR states=", _states, " spinning_steps=", spinning_steps)

func fast_approach() -> void:
	game(true, true)
	key(KEY_W, true)
	key(KEY_A, true)
	step(35)
	check(player.animator.current_state == "FlyingBladeRotation_Animation", "Stock-speed approach did not begin with the native flight rotor deployed")
	var before := player.position_unity
	var speed := absf(player.velocity_unity.x)
	check(speed > 1.0, "Stock-speed fixture did not establish normal horizontal flight")
	var target := before + Vector2.LEFT * (1.5 + speed * 0.25)
	# Both craft ascend together, so horizontal closing is not rejected by an
	# unrelated predicted vertical miss at normal engine speed.
	peer(target, true, Vector2(0.0, player.velocity_unity.y))
	step()
	check(absf(player.position_unity.x - target.x) > 1.5 and drill_direction() == Vector2.LEFT and condition("IsDiggingSide"), "Stock-speed approach did not predict drill deployment beyond nearby-contact range")
	var closing := false
	for frame in 80:
		if absf(player.position_unity.x - target.x) <= 0.9 or closing:
			break
		target.y = player.position_unity.y
		peer(target, true, Vector2(0.0, player.velocity_unity.y))
		step()
		closing = closing or player.animator.current_state == "FlyingClosingBlades_Animation"
	check(closing and absf(player.position_unity.x - target.x) > 0.9, "Stock-speed approach did not start native drill deployment before hull contact")
	check(player.position_unity.x < before.x - 0.05 and not host.body.freeze and not player.isOnGround, "Predictive engagement froze stock-speed native flight")

func sky_detector() -> void:
	game(true, true)
	# Populate exactly the underground cells the old absolute-row detector
	# would mirror while this craft is high above the surface.
	var mirrors: Array[Vector2i] = []
	for detector in [player._bottom_target, player._side_target]:
		var point: Vector2 = detector.global_position / PortPlayer.UNITS
		var mirrored := Vector2i(floori(point.x), absi(floori(point.y)))
		var raw: Array = host.world.getRawTile(mirrored.x, mirrored.y)
		raw[0] = 1
		raw[1] = 0
		mirrors.append(mirrored)
	host.refresh_tiles(mirrors)
	key(KEY_S, true)
	for frame in 4:
		step()
		check(not player.is_digging_bottom and not player.is_digging_side and not host.body.freeze, "Sky input mirrored a real underground tile into airborne terrain mining")
	check(not condition("IsDiggingBottom") and drill_direction() == Vector2.ZERO, "Empty sky without a peer deployed the bottom drill")
	for cell in mirrors:
		check(host.world.getBlockData(cell.x, cell.y).name == "Dirt", "Airborne input excavated its mirrored underground tile")

func terrain_mining(pvp: bool, cooperative: bool, label: String) -> void:
	game(pvp, cooperative)
	if pvp:
		key(KEY_W, true)
		step(35)
		check(player.animator.current_state == "FlyingBladeRotation_Animation", label + " terrain fixture did not begin with the authored flight rotor deployed")
		key(KEY_W, false)
	# An actual isolated dirt tile under the authored bottom detector, plus a
	# second dirt tile that MUST remain untouched when the current tile commits.
	var cleared: Array[Vector2i] = []
	for x in range(27, 35):
		for y in range(7, 18):
			var raw: Array = host.world.getRawTile(x, y)
			raw[0] = 0
			raw[1] = 0
			cleared.append(Vector2i(x, y))
	host.refresh_tiles(cleared)
	player.position_unity = Vector2(30.75, -10.2)
	player.velocity_unity = Vector2.ZERO
	var cell := player.getBlockPositionBottomPlayer()
	check(host.world.inBounds(cell.x, cell.y), label + " bottom detector missed fixture terrain")
	var next_cell := cell + Vector2i.DOWN
	for target in [cell, next_cell]:
		var raw: Array = host.world.getRawTile(target.x, target.y)
		raw[0] = 1
		raw[1] = 0
	host.refresh_tiles([cell, next_cell])
	host.data.player_dig_speed = 0.25
	key(KEY_S, true)
	step()
	check(player.is_digging_bottom and player._block_target == cell and host.body.freeze, label + " input did not begin real terrain mining")
	check(host.world.getBlockData(cell.x, cell.y).name == "Dirt", label + " mining target was not a real dirt tile")
	var deployed := false
	for frame in 80:
		step()
		if player.animator.current_state == "DrillingDown_Animation" and condition("IsDownDrillOut"):
			deployed = true
			break
	check(deployed and player.is_digging_bottom, label + " bottom drill never reached its native deployed mining state")
	var before_release := player.position_unity
	key(KEY_S, false)
	var retained_steps := 0
	var retained_conditions := true
	var retained_animation := true
	for frame in 20:
		step()
		if player.is_digging_bottom:
			retained_steps += 1
			retained_conditions = retained_conditions and condition("IsDiggingBottom") and condition("IsStillPressingDown")
			retained_animation = retained_animation and condition("IsDownDrillOut") and player.animator.current_state == "DrillingDown_Animation"
	check(retained_steps >= 10, label + " release cancelled or bypassed current-tile mining")
	check(retained_conditions and retained_animation, label + " bottom drill retracted while its real terrain tile was still being mined")
	check(player.position_unity.distance_to(before_release) > 0.005, label + " released current tile stopped making mining progress")
	var awaiting_authority := false
	for frame in 900:
		step()
		if cooperative and player._coop_mine_waiting:
			awaiting_authority = true
			break
		if not player.is_digging_bottom:
			break
	if cooperative:
		check(awaiting_authority, label + " never completed movement to the authoritative mining boundary")
		# Exercise the real receive/event/terrain-resolution path. The socket is
		# intentionally disconnected; this is not a server mining-policy test.
		network._receive({"type": "mined", "player_id": network.player_id,
			"x": cell.x, "y": cell.y, "accepted": true, "method": "drill", "ore": "Dirt"})
	check(not player.is_digging_bottom and not host.body.freeze, label + " completion did not release terrain freeze")
	check(host.world.getBlockData(cell.x, cell.y).layer == "Traversable", label + " completed tile was not actually excavated")
	step(45)
	check(not condition("IsDiggingBottom") and not condition("IsDownDrillOut"), label + " completed/released bottom drill did not retract normally")
	check(_states.has("PuttingDownDrillAway_Animation"), label + " skipped native drill retraction animation")
	check(host.world.getBlockData(next_cell.x, next_cell.y).name == "Dirt" and not player.is_digging_bottom, label + " stale released input started the next terrain tile")
	check(not player.isOnGround or not condition("IsDiggingSide"), label + " idle terrain contact deployed side melee")
	print("PVP_DRILL_TERRAIN mode=", label, " states=", _states)

func _run() -> void:
	if not OS.get_cmdline_user_args().has("--mode=private"):
		push_error("Drill regression requires --mode=private; never connect this fixture to a live world")
		quit(2)
		return
	host = load("res://main.tscn").instantiate()
	root.add_child(host)
	# Main's real _process owns its manual physics clock. Advance fixed render
	# intervals explicitly so headless CPU speed cannot shorten animation time.
	host.set_process(false)
	host.set_physics_process(false)
	network = host.coop.network
	network.set_process(false)
	network.token = ""
	network.username = ""
	network.base_url = "http://127.0.0.1:1"
	network.player_id = "drill-fixture-self"
	if host.fuel_pricing != null:
		host.fuel_pricing.set_process(false)
	air_approach()
	fast_approach()
	sky_detector()
	terrain_mining(true, true, "pvp")
	terrain_mining(false, false, "private")
	terrain_mining(false, true, "coop")
	release_keys()
	host.coop.active = false
	host.free()
	await process_frame
	print("PVP_DRILL_INTEROP failures=", failures)
	quit(0 if failures == 0 else 1)
