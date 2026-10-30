class_name PortPlayer
extends Node

const PIXELS := Vector2(50.0, -50.0)
const ITEM_NAMES := ["Reserve Fuel Tank", "Hull Repair Nanobots", "Dynamite", "Plastic Explosives", "Quantum Teleporter", "Matter Transmitter"]

var host: Node
var body: RigidBody2D
var visual: Node2D
var properties: Dictionary
var data: GameData
var world: WorldData
var bridge: SceneBridge
var animator: NativeAnimator
var my_rigidbody: RigidBody2D
var _float32_buffer := PackedFloat32Array([0.0])
var moveX: float = 0.0
var moveY: float = 0.0
var isFacingRight: bool = false
var isOnGround: bool = false
var isFlying: bool = false
var isDigging: bool = false
var is_digging_side: bool = false
var is_digging_bottom: bool = false
var is_in_shop: bool = false
var can_use_mouse_control: bool = true
var mouse_is_last_used_input: bool = false
var has_bossfight_started: bool = false
var is_invincible: bool = false
var is_permanently_invincible: bool = false
var invincibility_time: float = 2.0
var invincibility_time_left: float = 0.0
var frames_of_invisibility: int = 10
var frames_of_invisibility_left: int = 0
var max_cooldown_between_item_use: float = 2.0
var accelerationMovementSmoothing: float = 0.3
var slowdownMovementSmoothing: float = 1.0
var velocity_unity: Vector2:
	get:
		var velocity: Vector2 = PhysicsServer2D.body_get_state(body.get_rid(), PhysicsServer2D.BODY_STATE_LINEAR_VELOCITY)
		return velocity / PIXELS
	set(value):
		body.linear_velocity = value * PIXELS
var position_unity: Vector2:
	get:
		var pose: Transform2D = PhysicsServer2D.body_get_state(body.get_rid(), PhysicsServer2D.BODY_STATE_TRANSFORM)
		return pose.origin / PIXELS
	set(value):
		body.global_position = value * PIXELS
		visual.global_position = body.global_position
		host.player_position = value

var _alive: bool = true
var _smooth_velocity: float = 0.0
var _previous_y_velocity: float = 0.0
var _drill_clink_audio_cooldown: float = 0.0
var _time_until_can_use_item: float = 0.0
var _is_teleporting: bool = false
var _is_creating_explosions: bool = false
var _explosion_location := Vector2i.ZERO
var _explosion_min := Vector2.ZERO
var _explosion_max := Vector2.ZERO
var _total_explosion_time: float = 0.0
var _time_until_next_explosion_creation: float = 0.0
var _number_of_explosions_per_batch: int = 0
var _range_to_destroy_around_player: int = 0
var _active_attacks: Array[Dictionary] = []
var _block_target := Vector2i(-1, -1)
var _block_target_data: Dictionary = {}
var _block_target_position := Vector2.ZERO
var _collision_properties: Dictionary = {}
var _bottom_target: Node2D
var _side_target: Node2D
var _ground_node: Node2D
var _ground_offset := Vector2.ZERO
var _ground_query: PhysicsShapeQueryParameters2D
var _last_ground_render_step: int = -1
var _shapes: Array[Node2D] = []
var _shape_transforms: Array[Transform2D] = []
var _collision_layer: int
var _collision_mask: int
var _item_keys_down: Array[bool] = [false, false, false, false, false, false]
var _pressed_item: int = -1
var _frame_delta: float = 0.0
var _physics_delta: float = 0.02
var _sprite: CanvasItem

func configure(main_host: Node, player_body: RigidBody2D, player_visual: Node2D, serialized_properties: Dictionary) -> void:
	host = main_host
	body = player_body
	my_rigidbody = body
	visual = player_visual
	properties = serialized_properties
	data = host.data
	world = host.world
	bridge = host.bridge
	for field in ["can_use_mouse_control", "mouse_is_last_used_input", "isOnGround", "isFlying", "isDigging", "has_bossfight_started", "is_invincible", "is_permanently_invincible", "invincibility_time", "invincibility_time_left", "frames_of_invisibility", "frames_of_invisibility_left", "max_cooldown_between_item_use", "accelerationMovementSmoothing", "slowdownMovementSmoothing"]:
		if properties.has(field):
			set(field, properties[field])
	var owner_id: String = bridge.component_owner(properties.get("m_GameObject", {}))
	_collision_properties = bridge.properties(owner_id, "PlayerCollisions")
	_bottom_target = bridge.node(_collision_properties.get("block_detector_bottom", {})) as Node2D
	_side_target = bridge.node(_collision_properties.get("block_detector_side", {})) as Node2D
	_sprite = bridge.graphics.get(owner_id) as CanvasItem
	_collision_layer = body.collision_layer
	_collision_mask = body.collision_mask
	for child in body.get_children():
		if child is CollisionShape2D or child is CollisionPolygon2D:
			_shapes.append(child)
			_shape_transforms.append(child.transform)
	body.contact_monitor = true
	body.max_contacts_reported = maxi(body.max_contacts_reported, 16)
	_configure_ground_detector()
	var animator_id: String = bridge.reference_id(properties.get("animator", {}))
	var animator_properties: Dictionary = bridge.object(animator_id).get("properties", {})
	var controller: Dictionary = animator_properties.get("m_Controller", {})
	if controller.is_empty():
		animator_properties = bridge.properties(owner_id, "Animator")
		controller = animator_properties.get("m_Controller", {})
	animator = host.make_animator(visual, str(controller.get("guid", "")))
	animator.animation_event.connect(_animation_event)
	animator.state_entered.connect(_state_entered)
	animator.state_exited.connect(_state_exited)
	host.ui.updateAllUI()

func sync_physics_pose() -> void:
	# Node state synchronizes before the step; source Update sees the completed step.
	var pose: Transform2D = PhysicsServer2D.body_get_state(body.get_rid(), PhysicsServer2D.BODY_STATE_TRANSFORM)
	visual.global_position = pose.origin
	visual.global_rotation = pose.get_rotation()
	host.player_position = pose.origin / PIXELS

func tick(delta: float) -> void:
	_poll_item_keys()
	if not _alive or host.paused:
		return
	_frame_delta = delta
	sync_physics_pose()
	_tick_explosions(delta)
	_tick_invincibility(delta)
	if _time_until_can_use_item <= 0.0 and _can_move():
		checkIfObjectIsPressed()
	else:
		_time_until_can_use_item = _f32(_time_until_can_use_item - _f32(delta))
	if _drill_clink_audio_cooldown >= 0.0:
		_drill_clink_audio_cooldown = _f32(_drill_clink_audio_cooldown - _f32(delta))
	if _can_move():
		_read_axes()
		if not isFlying and moveY > 0.0:
			isFlying = true
			host.audio.PlaySound("RotorPlayer")
		if isOnGround == isFlying:
			isFlying = false
			host.audio.StopSound("RotorPlayer")
		animator.condition("IsFlying", isFlying)
		animator.condition("IsStillPressingDown", moveY < 0.0)
		if moveY < 0.0 and not _is_creating_explosions:
			_try_start_dig(getBlockPositionBottomPlayer(), true)
		elif moveX != 0.0 and isOnGround and not _is_creating_explosions:
			_try_start_dig(getBlockPositionSidePlayer(), false)
		animator.parameter("HorizontalSpeed", absf(velocity_unity.x))
		animator.parameter("VerticalSpeed", absf(moveY))
		animator.condition("IsOnGround", isOnGround and velocity_unity.y <= 0.01)
		animator.condition("IsDiggingBottom", is_digging_bottom)
		animator.condition("IsDiggingSide", is_digging_side)
	elif is_digging_bottom or is_digging_side:
		animator.condition("IsDiggingBottom", is_digging_bottom)
		animator.condition("IsDiggingSide", is_digging_side)
		dig()
	elif is_in_shop or _is_teleporting:
		animator.parameter("HorizontalSpeed", absf(velocity_unity.x))
		animator.parameter("VerticalSpeed", velocity_unity.x)
	if not _alive:
		return
	host.audio.ChangeSoundPitch("IdlePlayer", absf(velocity_unity.x) / 25.0)
	if velocity_unity.y > 0.0:
		host.audio.ChangeSoundPitch("RotorPlayer", velocity_unity.y / 10.0)
	if not _block_target_data.is_empty() and position_unity.distance_to(_block_target_position) > 1.5:
		cancelDig()
	animator.advance(delta)

func physics_tick(delta: float) -> void:
	if not _alive or host.paused:
		return
	_physics_delta = delta
	sync_physics_pose()
	_update_ground_contact()
	manageCrashVerification()
	if not _alive:
		return
	if _can_move():
		var velocity: Vector2 = velocity_unity
		velocity.x = _smooth_damp(velocity.x, moveX, slowdownMovementSmoothing if moveX == 0.0 else accelerationMovementSmoothing, delta)
		velocity_unity = velocity
		if moveY > 0.0 and velocity.y < data.player_vertical_speed:
			body.apply_central_force(Vector2(0.0, moveY * delta * 200.0) * PIXELS)
		if (moveX > 0.0 and not isFacingRight) or (moveX < 0.0 and isFacingRight):
			animator.condition("NeedsFlipping", true)
			_set_particles("smoke_particle_emitter", false)
		var rotation_unity: float = -body.rotation_degrees
		var target_angle: float = 0.0
		var angular_step: float = 0.4
		if isFlying and moveX != 0.0:
			target_angle = 10.0 if moveX < 0.0 else -10.0
			angular_step = (-0.5 if moveX < 0.0 else 0.5) * velocity.x
		var difference: float = wrapf(target_angle - rotation_unity, -180.0, 180.0)
		body.rotation_degrees = -(rotation_unity + clampf(difference, -angular_step, angular_step))
		visual.global_rotation = body.global_rotation
	updateFuel()
	host.player_position = position_unity
	_check_boss_attacks()

func _can_move() -> bool:
	return not is_digging_bottom and not is_digging_side and not is_in_shop and not _is_teleporting

func _read_axes() -> void:
	var horizontal: int = int(GameInput.axis_raw("Horizontal"))
	var vertical: int = int(GameInput.axis_raw("Vertical"))
	if host.replay_runner != null and not host.replay_runner.live_input:
		horizontal = int(host.replay_runner.axes.get("Horizontal", 0))
		vertical = int(host.replay_runner.axes.get("Vertical", 0))
	moveX = horizontal * data.player_horizontal_speed
	moveY = vertical * data.player_vertical_speed
	var arrow: CanvasItem = bridge.node(properties.get("mouse_pointer_arrow", {})) as CanvasItem
	if not GameInput.mouse_steering_allowed():
		mouse_is_last_used_input = false
		if arrow != null:
			arrow.hide()
		return
	if (moveX != 0.0 or moveY != 0.0) and arrow != null and arrow.visible:
		arrow.hide()
		mouse_is_last_used_input = false
	if moveX != 0.0 or moveY != 0.0 or not can_use_mouse_control:
		return
	updateMousePointerRotation()
	if visual.get_viewport().gui_get_hovered_control() != null:
		return
	var offset: Vector2 = _mouse_position_unity() - position_unity
	var distance: float = offset.length()
	var angle: float = rad_to_deg(offset.angle())
	if Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT) and distance >= 1.0:
		mouse_is_last_used_input = true
		if arrow != null:
			arrow.show()
		moveX = clampf(offset.x, -1.0, 1.0) * data.player_horizontal_speed
		moveY = clampf(offset.y, -1.0, 1.0) * data.player_vertical_speed
		if (angle < 0.0 and (angle <= -105.0 or angle >= -75.0)) or angle > 160.0 or angle < -160.0 or (angle < 20.0 and angle > -20.0):
			moveY = 0.0
	if arrow != null:
		if distance < 1.0 and arrow.visible:
			arrow.hide()
		if distance >= 1.0 and not arrow.visible and mouse_is_last_used_input:
			arrow.show()

func _mouse_position_unity() -> Vector2:
	return visual.get_global_mouse_position() / PIXELS

func updateMousePointerRotation() -> void:
	var arrow: Node2D = bridge.node(properties.get("mouse_pointer_arrow", {})) as Node2D
	if arrow != null:
		arrow.global_rotation = -((_mouse_position_unity() - position_unity).angle() - PI / 2.0)

func _configure_ground_detector() -> void:
	var reference: Variant = _collision_properties.get("bottom_detector", {})
	var collider: Dictionary = bridge.object(bridge.reference_id(reference)).get("properties", {})
	_ground_node = bridge.node(reference) as Node2D
	if _ground_node == null or collider.is_empty():
		return
	var shape := RectangleShape2D.new()
	var size: Dictionary = collider.get("m_Size", {})
	shape.size = Vector2(float(size.get("x", 0.0)), float(size.get("y", 0.0))) * 50.0 * _ground_node.global_scale.abs()
	var offset: Dictionary = collider.get("m_Offset", {})
	_ground_offset = Vector2(float(offset.get("x", 0.0)), float(offset.get("y", 0.0))) * PIXELS
	_ground_query = PhysicsShapeQueryParameters2D.new()
	_ground_query.shape = shape
	_ground_query.exclude = [body.get_rid()]
	_ground_query.collide_with_areas = true
	_ground_query.collision_mask = _collision_mask

func refresh_ground_after_step() -> void:
	var step := Engine.get_physics_frames()
	if step == _last_ground_render_step:
		return
	_last_ground_render_step = step
	sync_physics_pose()
	_update_ground_contact()

func _update_ground_contact() -> void:
	isOnGround = false
	if _ground_query == null:
		return
	# Box2D query transforms carry rotation/translation, not shape scaling.
	var transform := _ground_node.global_transform
	_ground_query.transform = Transform2D(transform.get_rotation(), transform * _ground_offset)
	for hit in body.get_world_2d().direct_space_state.intersect_shape(_ground_query, 32):
		if _is_ground(hit.collider):
			isOnGround = true
			break

func _is_ground(collider: Object) -> bool:
	return collider is Node and (collider.is_in_group("Ground") or str(collider.get_meta("unity_tag", "")) == "Ground" or str(collider.get_meta("tag", "")) == "Ground")

func getBlockPositionBottomPlayer() -> Vector2i:
	return _detector_cell(_bottom_target)

func getBlockPositionSidePlayer() -> Vector2i:
	return _detector_cell(_side_target)

func _detector_cell(detector: Node2D) -> Vector2i:
	if detector == null:
		push_error("PlayerCollisions is missing a serialized block detector")
		return Vector2i(-1, -1)
	var point: Vector2 = detector.global_position / PIXELS
	return Vector2i(floori(point.x), absi(floori(point.y)))

func _try_start_dig(cell: Vector2i, bottom: bool) -> void:
	if world.doesBlockExistAndIsDiggable(cell.x, cell.y):
		is_digging_bottom = bottom
		is_digging_side = not bottom
		_block_target = cell
		_block_target_data = world.getBlockData(cell.x, cell.y).duplicate()
		var tile_position := Vector2(cell.x + 0.5, -cell.y + 0.5)
		if bottom:
			_block_target_position = tile_position + Vector2(0.25 if isFacingRight else -0.25, 0.0)
		elif isFacingRight and moveX > 0.0:
			_block_target_position = tile_position + Vector2(0.25, 0.0)
		elif not isFacingRight and moveX < 0.0:
			_block_target_position = Vector2(tile_position.x - 0.25, position_unity.y)
		else:
			cancelDig()
			return
		stopPlayerCollisions()
		stopMovement()
		host.audio.PlaySound("Drill")
		body.rotation = 0.0
		visual.global_rotation = 0.0
	elif world.doesBlockExistAndIsNotDiggable(cell.x, cell.y) and _drill_clink_audio_cooldown <= 0.0:
		host.audio.PlaySoundOneShot("DrillClink")
		_drill_clink_audio_cooldown = 0.25 if bottom else 0.5

func dig() -> void:
	if _block_target_data.is_empty():
		cancelDig()
		return
	var step: float = 0.4 * data.player_dig_speed * _frame_delta * getDepthModifier(floori(position_unity.y))
	position_unity = position_unity.move_toward(_block_target_position, step)
	updateMousePointerRotation()
	var distance: float = position_unity.distance_to(_block_target_position)
	if distance < 0.5 and not world.blockChangedTexture:
		var previous := _block_target
		var orientation: int = 0
		if is_digging_bottom:
			orientation = 2
			previous.y -= 1
		elif is_digging_side:
			orientation = 3 if isFacingRight else 1
			previous.x += -1 if isFacingRight else 1
		else:
			cancelDig()
			return
		if _block_target_data.name == "Lava":
			host.audio.PlaySoundOneShot("Lava")
		var halfway: Dictionary = world.halfwayDigBlock(_block_target.x, _block_target.y, previous.y, previous.x, orientation)
		var changed: Array = halfway.get("refresh_cells", []).duplicate()
		changed.append(_block_target)
		host.refresh_tiles(changed)
	if distance < 0.05:
		var mineral_name: String = str(_block_target_data.name)
		if data.minerals_name_list.has(mineral_name):
			if data.addMineralInCargo(mineral_name):
				createPopup("+1 " + mineral_name, "IsMineral")
			else:
				createPopup("Cargo is full!\nYou lost " + mineral_name, "IsWarning")
			host.audio.PlaySoundOneShot("MineralGet")
		elif data.treasure_name_list.has(mineral_name):
			createPopup("+1 " + mineral_name + "\n+$" + str(data.minerals[mineral_name].ore_value), "IsMineral")
			data.addTreasureInCargo(mineral_name)
			host.audio.PlaySoundOneShot("MineralGet")
		if mineral_name == "Lava":
			loseHP(int(45.0 * (1.0 - data.player_radiator)))
		host.refresh_tiles(world.digBlock(_block_target.x, _block_target.y))
		_finish_dig()
		cancelVelocity()

func _finish_dig() -> void:
	is_digging_side = false
	is_digging_bottom = false
	_block_target = Vector2i(-1, -1)
	_block_target_data = {}
	_block_target_position = Vector2.ZERO
	startPlayerCollisions()
	host.ui.updateAllUI()
	if _alive:
		startMovement()
	host.audio.StopSound("Drill")

func cancelDig() -> void:
	_finish_dig()

func getDepthModifier(position_y: int) -> float:
	return 0.1 + 0.9 * (1.0 - absf(float(position_y)) / 600.0)

func flipCharacter() -> void:
	visual.scale.x *= -1.0
	isFacingRight = not isFacingRight
	for i in _shapes.size():
		var base: Transform2D = _shape_transforms[i]
		_shapes[i].transform = Transform2D(Vector2(-1.0, 0.0), Vector2(0.0, 1.0), Vector2.ZERO) * base if isFacingRight else base
	_set_particles("smoke_particle_emitter", true)
	updateMousePointerRotation()
	for popup_node in get_tree().get_nodes_in_group("PlayerPopup"):
		if popup_node is Node2D and visual.is_ancestor_of(popup_node):
			popup_node.scale.x *= -1.0

func stopMovement() -> void:
	body.linear_velocity = Vector2.ZERO
	body.angular_velocity = 0.0
	body.freeze_mode = RigidBody2D.FREEZE_MODE_STATIC
	body.freeze = true

func startMovement() -> void:
	body.freeze = false
	body.sleeping = false

func startPlayerCollisions() -> void:
	if _alive:
		body.collision_layer = _collision_layer
		body.collision_mask = _collision_mask
		for shape in _shapes:
			shape.set_deferred("disabled", false)
	_set_particles("dirt_particle_emitter", false)

func stopPlayerCollisions() -> void:
	body.collision_layer = 0
	body.collision_mask = 0
	for shape in _shapes:
		shape.set_deferred("disabled", true)
	_set_particles("dirt_particle_emitter", true)

func _set_particles(property_name: String, emitting: bool) -> void:
	var reference: Variant = properties.get(property_name, {})
	if bridge.has_method("set_particles"):
		bridge.call("set_particles", reference, emitting)
		return
	var emitter: Node = bridge.node(reference)
	if emitter == null:
		return
	var pending: Array[Node] = [emitter]
	while not pending.is_empty():
		var current: Node = pending.pop_back()
		if current is GPUParticles2D or current is CPUParticles2D:
			current.emitting = emitting
		for child in current.get_children():
			pending.append(child)

func manageCrashVerification() -> void:
	var new_velocity: float = absf(velocity_unity.y)
	if new_velocity < _previous_y_velocity - 7.0:
		loseHP(int(0.5 * _previous_y_velocity))
	_previous_y_velocity = new_velocity

func updateFuel() -> void:
	var rate := 0.08
	if is_digging_bottom or is_digging_side:
		rate = 0.33
	elif moveX != 0.0 or moveY > 0.0:
		rate = 0.16
	data.player_fuel = _f32(data.player_fuel - _f32(_f32(rate) * _f32(_physics_delta)))
	host.ui.updateFuelUI()
	if data.player_fuel <= 0.0:
		killPlayer()

func enterShop() -> void:
	cancelVelocity()
	is_in_shop = true
	host.paused = true
	host.audio.PauseSounds()

func exitShop() -> void:
	is_in_shop = false
	host.paused = false
	host.audio.ResumeSounds()

func cancelVelocity() -> void:
	if not body.freeze:
		velocity_unity = Vector2.ZERO
		body.angular_velocity = 0.0

func _poll_item_keys() -> void:
	_pressed_item = -1
	for index in ITEM_NAMES.size():
		var down: bool = GameInput.key_pressed("Alpha" + str(index + 1))
		if host.replay_runner != null and not host.replay_runner.live_input:
			down = bool(host.replay_runner.keys.get("Alpha" + str(index + 1), false))
		if down and not _item_keys_down[index] and _pressed_item < 0:
			_pressed_item = index
		_item_keys_down[index] = down

func checkIfObjectIsPressed() -> void:
	if _pressed_item >= 0:
		use_item(_pressed_item)
		_pressed_item = -1

func use_item(index: int) -> void:
	if not _alive or host.paused or not _can_move() or _time_until_can_use_item > 0.0 or index < 0 or index >= ITEM_NAMES.size():
		return
	_time_until_can_use_item = max_cooldown_between_item_use
	var item_name: String = ITEM_NAMES[index]
	if index >= 4 and has_bossfight_started:
		createPopup("Cannot teleport", "IsWarning")
		host.audio.PlaySoundOneShot("NoItemAvailable")
		return
	if int(data.player_items[item_name]) <= 0:
		createPopup("No " + item_name, "IsWarning")
		host.audio.PlaySoundOneShot("NoItemAvailable")
		return
	data.player_items[item_name] -= 1
	match index:
		0:
			data.addFuel(25)
			host.audio.PlaySoundOneShot("Refuel")
		1:
			data.addHull(30 * 15)
			host.audio.PlaySoundOneShot("Nanobots")
		2:
			createExplosions(1.0, 0.5, 8)
			host.audio.PlaySoundOneShot("Dynamite")
			_activate_attack("dynamite_hitbox")
		3:
			createExplosions(2.0, 0.7, 15)
			host.audio.PlaySoundOneShot("C4")
			_activate_attack("C4_hitbox")
		4, 5:
			animator.pulse("TeleportDangerous" if index == 4 else "TeleportSafe")
			_is_teleporting = true
			stopMovement()
			host.audio.PlaySoundOneShot("QuantumTeleporter" if index == 4 else "MatterTransmitter")
			host.resetBackgroundColor()
	createPopup("Used " + item_name, "IsObject")
	host.ui.updateAllUI()

func createPopup(text: String, trigger_text: String) -> void:
	host.createPopup(text, trigger_text)

func createExplosions(explosion_range: float, time: float, quantity: int) -> void:
	var player_position: Vector2 = position_unity
	_explosion_location = Vector2i(floori(absf(player_position.x)), floori(absf(player_position.y)) + 1)
	_total_explosion_time = _f32(time)
	_explosion_min = player_position - Vector2.ONE * (explosion_range + 0.5)
	_explosion_max = player_position + Vector2.ONE * (explosion_range + 0.5)
	_time_until_next_explosion_creation = 0.0
	_is_creating_explosions = true
	_number_of_explosions_per_batch = quantity
	_range_to_destroy_around_player = int(explosion_range)

func _tick_explosions(delta: float) -> void:
	if not _is_creating_explosions:
		return
	_time_until_next_explosion_creation = _f32(_time_until_next_explosion_creation - _f32(delta))
	_total_explosion_time = _f32(_total_explosion_time - _f32(delta))
	if _time_until_next_explosion_creation <= 0.0:
		var property_name: String = "explosion_without_particles_prefab" if has_bossfight_started else "explosion_prefab"
		var prefab_name: String = _prefab_name(property_name)
		for i in _number_of_explosions_per_batch:
			host.spawn_prefab(prefab_name, Vector2(host.unity_random.range_float(_explosion_min.x, _explosion_max.x), host.unity_random.range_float(_explosion_min.y, _explosion_max.y)), host.world_root)
		_time_until_next_explosion_creation = _f32(0.1)
	_check_boss_attacks()
	if _total_explosion_time <= 0.0:
		_is_creating_explosions = false
		destroyBlocksFromExplosion(_range_to_destroy_around_player)
		bridge.set_active(properties.get("dynamite_hitbox", {}), false)
		bridge.set_active(properties.get("C4_hitbox", {}), false)
		_active_attacks.clear()

func _prefab_name(property_name: String) -> String:
	var reference: Dictionary = properties.get(property_name, {})
	var source: String = str(reference.get("source", ""))
	if not source.is_empty():
		return source.get_file().get_basename()
	for prefab_name in bridge.manifest.prefabs:
		if str(bridge.manifest.prefabs[prefab_name].get("guid", "")) == str(reference.get("guid", "")):
			return str(prefab_name)
	push_error("Missing serialized player prefab: " + property_name)
	return ""

func destroyBlocksFromExplosion(explosion_range: int) -> void:
	var changed: Array[Vector2i] = []
	for x in range(maxi(0, _explosion_location.x - explosion_range), mini(data.earthWidth, _explosion_location.x + explosion_range + 1)):
		for y in range(maxi(0, _explosion_location.y - explosion_range), mini(data.earthHeight, _explosion_location.y + explosion_range + 1)):
			# The GameObject overload used here accepts Diggable, including Rock,
			# but does not erase invincible tiles or already-open tunnels.
			if world.getBlockData(x, y).layer == "Diggable":
				changed.append_array(world.instantDigBlock(x, y))
	host.refresh_tiles(changed)

func _activate_attack(property_name: String) -> void:
	var reference: Variant = properties.get(property_name, {})
	bridge.set_active(reference, true)
	var owner_id: String = bridge.component_owner(reference)
	var attack: Dictionary = bridge.properties(owner_id, "PlayerAttackBehavior")
	var collider: Dictionary = bridge.properties(owner_id, "BoxCollider2D")
	var size: Dictionary = collider.get("m_Size", {})
	_active_attacks.append({"node": bridge.node(reference), "damage": int(attack.get("damage", 0)), "size": Vector2(float(size.get("x", 0.0)), float(size.get("y", 0.0))), "hit": false})
	_check_boss_attacks()

func _check_boss_attacks() -> void:
	var boss: Variant = host.get("boss")
	if boss == null or not is_instance_valid(boss):
		return
	for attack in _active_attacks:
		var attack_node: Node2D = attack.node as Node2D
		if not attack.hit and attack_node != null:
			var half_extents: Vector2 = attack.size * attack_node.global_scale.abs() * 0.5
			attack.hit = bool(boss.damage_from_explosion(attack_node.global_position / PIXELS, maxf(half_extents.x, half_extents.y), attack.damage))

func teleportPlayerSafe() -> void:
	position_unity = Vector2(5.5, -3.5)

func endTeleportPlayerSafe() -> void:
	startMovement()
	_is_teleporting = false

func teleportPlayerDangerous() -> void:
	position_unity = Vector2(5.5, -1.5)

func endTeleportPlayerDangerous() -> void:
	startMovement()
	_is_teleporting = false
	velocity_unity = Vector2(host.unity_random.range_float(-6.0, 6.0), -5.0 if host.unity_random.value() < 0.6 else 10.0)

func _tick_invincibility(delta: float) -> void:
	if not is_invincible:
		return
	invincibility_time_left = _f32(invincibility_time_left - _f32(delta))
	frames_of_invisibility_left -= 1
	if frames_of_invisibility_left <= 0:
		frames_of_invisibility_left = frames_of_invisibility
		if _sprite != null:
			_sprite.modulate = Color(1.0, 1.0, 1.0, 1.0 if _sprite.modulate.a == 0.0 else 0.0)
	if invincibility_time_left <= 0.0:
		is_invincible = false
		frames_of_invisibility_left = 0
		if _sprite != null:
			_sprite.modulate = Color.WHITE

func loseHP(amount: int) -> void:
	if _alive and not is_invincible and not is_permanently_invincible:
		host.audio.PlaySound("PlayerCrash")
		data.player_hp -= amount
		if data.player_hp <= 0:
			killPlayer()
		else:
			is_invincible = true
			invincibility_time_left = invincibility_time
		host.ui.updateAllUI()

func gainHP(amount: int) -> void:
	data.player_hp = mini(data.player_hp + amount, data.player_max_hp)
	if data.player_hp <= 0:
		killPlayer()
	host.ui.updateAllUI()

func killPlayer() -> void:
	if not _alive:
		return
	_alive = false
	host.player_alive = false
	host.audio.PlaySoundOneShot("KillPlayer")
	for sound in ["LowFuelWarning", "VeryLowFuelWarning", "Drill", "IdlePlayer", "RotorPlayer"]:
		host.audio.StopSound(sound)
	bridge.set_active(properties.get("death_screen", {}), true)
	host.spawn_prefab(_prefab_name("dead_player_prefab"), position_unity, host.world_root)
	stopMovement()
	body.collision_layer = 0
	body.collision_mask = 0
	visual.hide()
	_active_attacks.clear()

func _animation_event(method: String, argument: Variant) -> void:
	if not _alive:
		return
	if has_method(method):
		if argument == null:
			call(method)
		else:
			call(method, argument)
	else:
		push_warning("Unknown player animation event: " + method)

func _state_entered(_state_name: String, behaviors: Array) -> void:
	for behavior in behaviors:
		match str(behavior.get("script", "")):
			"FinishFlipping":
				animator.condition("NeedsFlipping", false)
			"FinishOpeningBlades":
				host.audio.PlaySoundOneShot("GetRotorOut")
			"FinishClosinBlades":
				animator.condition("FlyingBladesAreOut", false)
				host.audio.PlaySoundOneShot("GetSideDrillOut")
			"ResetPlayerAnimation":
				for parameter in ["FlyingBladesAreOut", "IsFlying", "IsDiggingBottom", "IsDiggingSide", "IsDownDrillOut"]:
					animator.condition(parameter, false)

func _state_exited(_state_name: String, behaviors: Array) -> void:
	for behavior in behaviors:
		match str(behavior.get("script", "")):
			"FinishFlipping":
				animator.condition("NeedsFlipping", false)
				flipCharacter()
			"FinishOpeningBlades":
				animator.condition("FlyingBladesAreOut", true)
			"FinishGettingDownDrillOut":
				animator.condition("IsDownDrillOut", true)
			"FinishPuttingDownDrillAway":
				animator.condition("IsDownDrillOut", false)

func _smooth_damp(current: float, target: float, smooth_time: float, delta: float) -> float:
	# Preserve float32 operation order from Mathf.SmoothDamp, not double math.
	# The source uses its default infinite maximum speed, so no clamp is needed.
	current = _f32(current)
	target = _f32(target)
	delta = _f32(delta)
	smooth_time = maxf(0.00009999999747378752, _f32(smooth_time))
	var omega: float = _f32(2.0 / smooth_time)
	var x: float = _f32(omega * delta)
	var quadratic: float = _f32(_f32(0.47999998927116394 * x) * x)
	var cubic: float = _f32(_f32(_f32(0.23499999940395355 * x) * x) * x)
	var decay: float = _f32(1.0 / _f32(_f32(_f32(1.0 + x) + quadratic) + cubic))
	var original_target: float = target
	var change: float = _f32(current - target)
	target = _f32(current - change)
	var temporary: float = _f32(_f32(_smooth_velocity + _f32(omega * change)) * delta)
	_smooth_velocity = _f32(_f32(_smooth_velocity - _f32(omega * temporary)) * decay)
	var result: float = _f32(target + _f32(_f32(change + temporary) * decay))
	if (_f32(original_target - current) > 0.0) == (result > original_target):
		result = original_target
		_smooth_velocity = _f32(_f32(result - original_target) / delta)
	return result

func _f32(value: float) -> float:
	_float32_buffer[0] = value
	return _float32_buffer[0]
