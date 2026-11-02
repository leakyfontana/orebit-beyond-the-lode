extends SceneTree

# The real PortPlayer crash consumer runs once per native physics step against
# real RigidBody2D contacts. Only the outgoing damage boundary is observed here;
# no contact, velocity, ground result, or fall-history decision is mocked.
class DamageProbe extends PortPlayer:
	var damage: Array[int] = []
	func loseHP(amount: int) -> void:
		damage.append(amount)

class CrashFixture extends Node2D:
	var player_position := Vector2.ZERO
	var physics_step := 0
	var frame_number := 0
	var physics_render_delta := 0.0
	var ui: Node
	var audio: Node
	var ui_updates := 0
	var stopped_sounds: Array[String] = []
	var player: DamageProbe
	var body: RigidBody2D
	var support: StaticBody2D
	var terrain_contact_steps := 0
	var peer_contact_steps := 0
	var grounded_steps := 0

	func updateAllUI() -> void:
		ui_updates += 1

	func StopSound(sound: String) -> void:
		stopped_sounds.append(sound)

	func _physics_process(_delta: float) -> void:
		physics_step += 1
		frame_number += 1
		player.sync_physics_pose(false)
		player._update_ground_contact()
		if player.isOnGround:
			grounded_steps += 1
		for collider in body.get_colliding_bodies():
			if collider.is_in_group("PvpMiner"):
				peer_contact_steps += 1
			elif collider.is_in_group("Ground"):
				terrain_contact_steps += 1
		player.manageCrashVerification()

var failures := 0

func _initialize() -> void:
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func fixture(support_group: String = "") -> CrashFixture:
	var viewport := SubViewport.new()
	viewport.world_2d = World2D.new()
	root.add_child(viewport)
	PhysicsServer2D.space_set_active(viewport.world_2d.space, true)
	PhysicsServer2D.area_set_param(viewport.world_2d.space, PhysicsServer2D.AREA_PARAM_GRAVITY, 0.0)
	var world := CrashFixture.new()
	world.ui = world
	world.audio = world
	viewport.add_child(world)
	world.set_physics_process(false)
	var body := RigidBody2D.new()
	body.position = Vector2(0.0, -2.0)
	body.gravity_scale = 0.0
	body.linear_damp_mode = RigidBody2D.DAMP_MODE_REPLACE
	body.linear_damp = 0.0
	body.lock_rotation = true
	body.can_sleep = false
	body.collision_layer = 2
	body.collision_mask = 3
	body.contact_monitor = true
	body.max_contacts_reported = 16
	body.continuous_cd = RigidBody2D.CCD_MODE_CAST_SHAPE
	world.add_child(body)
	world.body = body
	var collision := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 0.25
	collision.shape = circle
	body.add_child(collision)
	# A lower segment mirrors the vehicle's non-rectangular support footprint.
	var bottom := CollisionShape2D.new()
	var segment := SegmentShape2D.new()
	segment.a = Vector2(-0.2, 0.24)
	segment.b = Vector2(0.2, 0.24)
	bottom.shape = segment
	body.add_child(bottom)
	var visual := Node2D.new()
	world.add_child(visual)
	var bridge := SceneBridge.new({})
	bridge.scene = {"objects": {}, "game_objects": {}}
	world.add_child(bridge)
	var player := DamageProbe.new()
	player.host = world
	player.body = body
	player.visual = visual
	player.bridge = bridge
	player.data = GameData.new()
	player.data.pvp_mode = true
	player._collision_layer = 2
	player._collision_mask = 3
	player._shapes.append(collision)
	player._shapes.append(bottom)
	world.add_child(player)
	world.player = player
	var ground_node := Node2D.new()
	ground_node.position = Vector2(0.0, 0.27)
	body.add_child(ground_node)
	player._ground_node = ground_node
	player._ground_query = PhysicsShapeQueryParameters2D.new()
	var detector := RectangleShape2D.new()
	detector.size = Vector2(0.5, 0.2)
	player._ground_query.shape = detector
	player._ground_query.exclude = [body.get_rid()]
	player._ground_query.collision_mask = 3
	if not support_group.is_empty():
		var support := StaticBody2D.new()
		support.add_to_group(support_group)
		support.collision_layer = 2 if support_group == "PvpMiner" else 1
		support.collision_mask = 2
		var material := PhysicsMaterial.new()
		material.bounce = 0.0
		support.physics_material_override = material
		world.add_child(support)
		var floor_shape := CollisionShape2D.new()
		var rectangle := RectangleShape2D.new()
		rectangle.size = Vector2(20.0, 1.0)
		floor_shape.shape = rectangle
		floor_shape.position.y = 0.5
		support.add_child(floor_shape)
		world.support = support
	world.set_physics_process(true)
	return world

func steps(count: int) -> void:
	for step in count:
		await physics_frame
		await process_frame

func dispose(world: CrashFixture) -> void:
	world.get_parent().queue_free()
	await process_frame

func _run() -> void:
	var world := fixture()
	world.player.velocity_unity = Vector2(0.0, 18.0)
	await steps(3)
	# Native damping brakes an ascent sharply without any collision.
	world.body.linear_damp = 100.0
	await steps(4)
	check(absf(world.player.velocity_unity.y) < 1.0, "Rotor braking fixture did not slow the rising body")
	check(world.player.damage.is_empty(), "Braking an ascent reported crash damage")
	world.body.linear_damp = 0.0
	world.player.velocity_unity = Vector2(0.0, -18.0)
	await steps(3)
	world.body.apply_central_impulse(Vector2(0.0, -18.0))
	await steps(3)
	check(world.player.damage.is_empty(), "Rotor arrest of an airborne fall reported crash damage")
	await dispose(world)

	world = fixture("Ground")
	world.player.velocity_unity = Vector2(0.0, -18.0)
	await steps(40)
	check(world.terrain_contact_steps > 0 and world.grounded_steps > 0, "Terrain landing did not exercise native support contacts")
	check(not world.player.damage.is_empty() and world.player.damage[0] >= 7, "Fast downward terrain landing did not report crash damage")
	await dispose(world)

	world = fixture("PvpMiner")
	world.player.velocity_unity = Vector2(0.0, -18.0)
	await steps(40)
	check(world.peer_contact_steps > 0 and world.grounded_steps > 0, "Peer landing did not exercise native miner support")
	check(world.player.damage.is_empty(), "Landing on another miner reported terrain crash damage")
	await dispose(world)

	world = fixture("Ground")
	# Establish a fall, then invoke the actual drill freeze/cancel lifecycle.
	world.player.velocity_unity = Vector2(0.0, -18.0)
	await steps(2)
	world.player.is_digging_bottom = true
	world.player._block_target = Vector2i(0, 1)
	world.player._block_target_data = {"name": "Dirt"}
	world.player._block_target_position = Vector2(0.0, -0.5)
	world.player.stopMovement()
	check(world.player._previous_y_velocity == 0.0, "Drill freeze retained pre-freeze fall history")
	world.player.position_unity = Vector2(0.0, 0.25)
	await steps(4)
	world.player.cancelDig()
	await steps(5)
	check(not world.body.freeze and not world.player.is_digging_bottom, "Drill cancel did not restore movement")
	check(world.player.damage.is_empty(), "Drill freeze/reposition/cancel injected crash damage")
	world.player.velocity_unity = Vector2(0.0, -18.0)
	world.player.manageCrashVerification()
	world.player.cancelVelocity()
	check(world.player._previous_y_velocity == 0.0, "Deliberate velocity cancellation retained fall history")
	await steps(3)
	check(world.player.damage.is_empty(), "Deliberate stop on terrain injected crash damage")
	await dispose(world)

	world = fixture()
	world.player.velocity_unity = Vector2(6.0, -18.0)
	await steps(3)
	var before := world.player.position_unity
	world.player._pose_history_start_step = -100
	world.player._pose_render_frame = world.frame_number
	world.player.apply_motion_correction(Vector2(-0.5, 0.25))
	check(world.player.position_unity.is_equal_approx(before + Vector2(-0.5, 0.25)), "Correction rewound newer native motion instead of rebasing it")
	check(world.player.velocity_unity.is_zero_approx(), "Correction retained velocity driving into the corrected boundary")
	check(world.player._previous_y_velocity == 0.0 and world.player._pose_history_start_step == world.physics_step and world.player._pose_render_frame == -1, "Correction retained fall or extrapolation history")
	world.player.sync_physics_pose()
	check(world.player_position.is_equal_approx(world.player.position_unity), "Correction immediately extrapolated back into the obstacle")
	world.player.velocity_unity = Vector2(-3.0, 4.0)
	world.player.apply_motion_correction(Vector2(-0.1, 0.2))
	check(world.player.velocity_unity.is_equal_approx(Vector2(-3.0, 4.0)), "Correction discarded velocity moving away from the obstacle")
	world.player.is_digging_side = true
	world.player._block_target = Vector2i(1, 1)
	world.player._block_target_data = {"name": "Dirt"}
	world.player._block_target_position = world.player.position_unity + Vector2.RIGHT
	world.player.stopMovement()
	before = world.player.position_unity
	world.player.apply_motion_correction(Vector2(-0.2, 0.0))
	check(world.player._block_target_data.is_empty() and not world.player.is_digging_side and not world.body.freeze, "Blocking correction did not cancel the terrain drill")
	check(world.player.position_unity.is_equal_approx(before + Vector2(-0.2, 0.0)), "Drill cancellation lost the correction delta")
	await steps(3)
	check(world.player.damage.is_empty(), "Motion correction injected crash damage")
	await dispose(world)
	print("PVP_CRASH_INTEROP failures=", failures)
	quit(0 if failures == 0 else 1)
