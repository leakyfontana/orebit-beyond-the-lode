extends Node2D

const UNIT := Vector2(50, -50)
var manifest: Dictionary
var data := GameData.new()
var world: WorldData
var bridge: SceneBridge
var audio := GameAudio.new()
var ui: GameUI
var player: PortPlayer
var boss: PortBoss
var body: RigidBody2D
var player_trigger: Area2D
var terrain: TerrainView
var camera: Camera2D
var _camera_orthographic_size := 5.0
var world_root: Node2D
var ui_root: Control
var player_position := Vector2.ZERO
var player_alive := false:
	set(value):
		player_alive = value
		_sync_touch_controls()
var paused := false:
	set(value):
		paused = value
		if is_inside_tree():
			Engine.time_scale = 0.0 if value else 1.0
			get_tree().paused = value
		_sync_touch_controls()
var scene_name := ""
var player_go := ""
var animators: Array = []
var scene_triggers: Array = []
var background_goal: Dictionary = {}
var seed_value := 1
var _seed_is_explicit := false
var unity_random := UnityRandom.new()
var replay: Dictionary = {}
var frame_number := 0
var capture_directory := ""
var pending_scene := ""
var _last_ui_usec := 0
var replay_runner: ReplayRunner
var touch_controls: TouchControls

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	var catalog := load("res://data/game_assets.res") as GameAssetCatalog
	if catalog == null or catalog.schema_version != 1:
		push_error("Native game assets unavailable; run verification/bake_game_assets.gd")
		get_tree().quit(1)
		return
	manifest = catalog.data
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--seed="):
			seed_value = int(argument.trim_prefix("--seed="))
			_seed_is_explicit = true
		elif argument.begins_with("--replay="):
			replay = JSON.parse_string(FileAccess.get_file_as_string(argument.trim_prefix("--replay=")))
		elif argument.begins_with("--capture="):
			capture_directory = argument.trim_prefix("--capture=")
	if not replay.is_empty():
		seed_value = int(replay.get("seed", seed_value))
		_seed_is_explicit = true
		if capture_directory.is_empty():
			push_error("--capture directory required with --replay")
			get_tree().quit(1)
			return
		replay_runner = ReplayRunner.new()
		replay_runner.configure(self, replay, capture_directory)
	unity_random.reseed(seed_value if _seed_is_explicit else Time.get_ticks_usec())
	data.setVolumeLevels()
	world = WorldData.new(data)
	add_child(audio)
	audio.configure(manifest.get("audio", {}), data, unity_random)
	add_child(GameInput.new())
	var touch_layer := CanvasLayer.new()
	touch_layer.name = "TouchControlsLayer"
	touch_layer.layer = 100
	add_child(touch_layer)
	touch_controls = preload("res://scenes/touch_controls.tscn").instantiate()
	touch_layer.add_child(touch_controls)
	touch_controls.configure(self)
	change_scene("MainMenu")
	print("MOTHERLOAD_READY scene=MainMenu godot=" + Engine.get_version_info().string)

func change_scene(which: String) -> void:
	pending_scene = which
	_sync_touch_controls()

func _sync_touch_controls() -> void:
	if is_instance_valid(touch_controls):
		touch_controls.sync_state()

func _load_scene(which: String) -> void:
	paused = false
	player_alive = false
	animators.clear()
	scene_triggers.clear()
	background_goal.clear()
	for instance in [ui, player, boss, bridge, world_root, ui_root, camera, body]:
		if is_instance_valid(instance):
			instance.free()
	ui = null
	player = null
	boss = null
	body = null
	player_trigger = null
	terrain = null
	player_go = ""
	scene_name = which
	world_root = Node2D.new()
	world_root.name = "World"
	world_root.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(world_root)
	var layer := CanvasLayer.new()
	ui_root = Control.new()
	ui_root.name = "UI"
	ui_root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	ui_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(layer)
	layer.add_child(ui_root)
	bridge = SceneBridge.new(manifest)
	add_child(bridge)
	bridge.build(which, world_root, ui_root)
	camera = Camera2D.new()
	add_child(camera)
	_camera_orthographic_size = 5.0
	camera.position = Vector2(8.886563, 0) * UNIT
	camera.make_current()
	for id in bridge.scene.game_objects:
		for component in bridge.components(id):
			if component.get("type", "") == "Camera":
				var p: Dictionary = component.properties
				var color: Dictionary = p.get("m_BackGroundColor", {})
				RenderingServer.set_default_clear_color(Color(float(color.get("r", 0)), float(color.get("g", 0)), float(color.get("b", 0))))
				var camera_visual: Node2D = bridge.nodes[id]
				camera.global_position = camera_visual.global_position
				_camera_orthographic_size = float(p.get("orthographic size", 5))
	if not get_viewport().size_changed.is_connected(_resize_camera):
		get_viewport().size_changed.connect(_resize_camera)
	_resize_camera()
	if which == "Game":
		if not data.level_is_already_generated:
			world.generate(seed_value if _seed_is_explicit else null)
		data.initPlayer()
	ui = GameUI.new()
	add_child(ui)
	ui.configure(self, bridge, data, audio)
	if which == "Game":
		terrain = TerrainView.new()
		world_root.add_child(terrain)
		terrain.configure(world, data, bridge)
		_setup_player()
		_setup_static_collisions()
		boss = PortBoss.new()
		add_child(boss)
		boss.configure(self)
		audio.PlayMusic("MainLevelMusic")
	for id in bridge.scene.game_objects:
		var visual := bridge.nodes.get(id) as CanvasItem
		if visual == null or id == player_go:
			continue
		if boss != null and (boss.owned_root_ids.has(str(id)) or not bridge.properties(id, "P1LaserAttackBehavior").is_empty()):
			continue
		for component in bridge.components(id):
			if component.get("type", "") == "Animator":
				var controller: String = component.properties.get("m_Controller", {}).get("guid", "")
				if not controller.is_empty():
					var animator := make_animator(visual, controller)
					animators.append({"root": visual, "animator": animator})
					animator.animation_event.connect(_scene_event.bind(id))
	ui.updateAllUI()

func _setup_player() -> void:
	for id in bridge.scene.game_objects:
		if not bridge.properties(id, "PlayerMovement").is_empty():
			player_go = id
			break
	if player_go.is_empty():
		push_error("Original scene contains no PlayerMovement component")
		return
	var visual: Node2D = bridge.nodes[player_go]
	var rigid := bridge.properties(player_go, "Rigidbody2D")
	body = RigidBody2D.new()
	body.name = "PlayerPhysics"
	body.collision_layer = 2
	body.collision_mask = 1
	body.lock_rotation = true
	body.contact_monitor = true
	body.max_contacts_reported = 16
	body.continuous_cd = RigidBody2D.CCD_MODE_DISABLED if int(rigid.get("m_CollisionDetection", 0)) == 0 else RigidBody2D.CCD_MODE_CAST_SHAPE
	body.gravity_scale = float(rigid.get("m_GravityScale", 1.0))
	body.linear_damp_mode = RigidBody2D.DAMP_MODE_REPLACE
	body.linear_damp = 0.0
	body.angular_damp = 0.0
	add_child(body)
	body.global_position = visual.global_position
	body.mass = float(rigid.get("m_Mass", 1))
	var material := PhysicsMaterial.new()
	var original_material: Dictionary = rigid.get("published_physics_material", {})
	material.friction = float(original_material.get("friction", 0))
	material.bounce = float(original_material.get("bounciness", 0))
	body.physics_material_override = material
	for component in bridge.components(player_go):
		if component.get("type", "").ends_with("Collider2D") and not bool(component.properties.get("m_IsTrigger", false)):
			_add_shape(body, component, visual.global_scale)
	body.set_meta("unity_tag", "Player")
	body.add_to_group("Player")
	# Tag-filtered triggers observe the original child sensor, not the solid body.
	for id in bridge.scene.game_objects:
		if bridge.scene.game_objects[id].get("tag", "") != "PlayerTrigger":
			continue
		var sensor_visual := bridge.nodes[id] as Node2D
		player_trigger = Area2D.new()
		player_trigger.name = "PlayerTrigger"
		player_trigger.collision_layer = 2
		player_trigger.collision_mask = 0
		player_trigger.monitoring = false
		body.add_child(player_trigger)
		player_trigger.global_transform = Transform2D(sensor_visual.global_rotation, sensor_visual.global_position)
		for component in bridge.components(id):
			if component.get("type", "").ends_with("Collider2D") and bool(component.properties.get("m_IsTrigger", false)) and bool(component.properties.get("m_Enabled", true)):
				_add_shape(player_trigger, component, sensor_visual.global_scale)
	player_position = body.global_position / UNIT
	player_alive = visual.visible
	body.freeze = not player_alive
	player = PortPlayer.new()
	add_child(player)
	player.configure(self, body, visual, bridge.properties(player_go, "PlayerMovement"))
	ui.mouse_control_changed.connect(func(enabled: bool): player.can_use_mouse_control = enabled)
	terrain.follow(player_position)

func _add_shape(owner_body: CollisionObject2D, component: Dictionary, scaling: Vector2 = Vector2.ONE) -> void:
	var p: Dictionary = component.properties
	if not bool(p.get("m_Enabled", true)):
		return
	var shape: Shape2D
	match str(component.get("type", "")):
		"CircleCollider2D":
			var circle := CircleShape2D.new()
			circle.radius = float(p.get("m_Radius", 0.5)) * 50.0 * maxf(absf(scaling.x), absf(scaling.y))
			shape = circle
		"BoxCollider2D":
			var rectangle := RectangleShape2D.new()
			rectangle.size = _vec(p.get("m_Size", {}), Vector2.ONE) * 50.0 * scaling.abs()
			shape = rectangle
		"CapsuleCollider2D":
			var capsule := CapsuleShape2D.new()
			var size := _vec(p.get("m_Size", {}), Vector2.ONE) * 50.0 * scaling.abs()
			capsule.radius = minf(size.x, size.y) / 2.0
			capsule.height = maxf(size.x, size.y)
			shape = capsule
		"EdgeCollider2D":
			var vertices: Array = p.get("m_Points", [])
			for index in range(vertices.size() - 1):
				var start := _vec(vertices[index]) * UNIT * scaling
				var end := _vec(vertices[index + 1]) * UNIT * scaling
				var segment := SegmentShape2D.new()
				segment.a = start
				segment.b = end
				var edge := CollisionShape2D.new()
				edge.shape = segment
				edge.position = _vec(p.get("m_Offset", {})) * UNIT * scaling
				owner_body.add_child(edge)
			return
		"PolygonCollider2D":
			var paths: Array = p.get("m_Points", {}).get("m_Paths", [])
			for path in paths:
				var polygon := ConvexPolygonShape2D.new()
				var points := PackedVector2Array()
				for point in path:
					points.append(_vec(point) * UNIT * scaling)
				polygon.points = points
				var polygon_node := CollisionShape2D.new()
				polygon_node.shape = polygon
				owner_body.add_child(polygon_node)
			return
		_:
			push_error("Unsupported original collider: " + str(component.get("type", "")))
			return
	var collision := CollisionShape2D.new()
	collision.shape = shape
	collision.position = _vec(p.get("m_Offset", {})) * UNIT * scaling
	owner_body.add_child(collision)

func _setup_static_collisions() -> void:
	for id in bridge.scene.game_objects:
		if id == player_go:
			continue
		var visual := bridge.nodes[id] as Node2D
		if visual == null:
			continue
		var area: Area2D
		for component in bridge.components(id):
			var script: String = component.get("script", "")
			if script in ["ShopDoorCollision", "ExitShopDoorCollision", "TransmissionTrigger", "StartBossfightTrigger", "BackgroundChangeColorTrigger"]:
				if area == null:
					area = Area2D.new()
					area.collision_layer = 1
					area.collision_mask = 2
					area.monitorable = false
					world_root.add_child(area)
					area.global_transform = Transform2D(visual.global_rotation, visual.global_position)
					for shape_component in bridge.components(id):
						if shape_component.get("type", "").ends_with("Collider2D") and bool(shape_component.properties.get("m_IsTrigger", false)):
							_add_shape(area, shape_component, visual.global_scale)
				var trigger := {"id": id, "script": script, "properties": component.properties, "area": area}
				scene_triggers.append(trigger)
				if script in ["TransmissionTrigger", "StartBossfightTrigger", "BackgroundChangeColorTrigger"]:
					area.area_entered.connect(_trigger_entered.bind(trigger), CONNECT_DEFERRED)
				else:
					area.body_entered.connect(_trigger_entered.bind(trigger), CONNECT_DEFERRED)
					area.body_exited.connect(_trigger_exited.bind(trigger), CONNECT_DEFERRED)
		if not bridge.properties(id, "Rigidbody2D").is_empty() or not bridge.properties(id, "StartBossfightTrigger").is_empty():
			continue
		if not bridge.properties(id, "P1BossMethods").is_empty() or not bridge.properties(id, "P2BossMethods").is_empty():
			continue
		if str(bridge.scene.game_objects[id].get("name", "")).to_lower().contains("ceiling"):
			continue
		var collidable := false
		for component in bridge.components(id):
			if component.get("type", "").ends_with("Collider2D") and not bool(component.properties.get("m_IsTrigger", false)):
				collidable = true
		if not collidable or not visual.is_visible_in_tree():
			continue
		var solid := StaticBody2D.new()
		solid.collision_layer = 1
		solid.collision_mask = 2
		world_root.add_child(solid)
		solid.global_transform = Transform2D(visual.global_rotation, visual.global_position)
		var tag: String = bridge.scene.game_objects[id].get("tag", "Untagged")
		solid.set_meta("unity_tag", tag)
		if tag == "Ground":
			solid.add_to_group("Ground")
		for component in bridge.components(id):
			if component.get("type", "").ends_with("Collider2D") and not bool(component.properties.get("m_IsTrigger", false)):
				_add_shape(solid, component, visual.global_scale)

func _process(delta: float) -> void:
	var now_usec := Time.get_ticks_usec()
	var ui_delta := float(now_usec - _last_ui_usec) / 1000000.0 if _last_ui_usec > 0 else delta
	_last_ui_usec = now_usec
	if replay_runner != null:
		ui_delta = replay_runner.render_delta
		delta = ui_delta * Engine.time_scale
	if player != null and player_alive and not paused:
		player.refresh_ground_after_step()
	var next := pending_scene
	pending_scene = ""
	if replay_runner != null and bridge != null:
		replay_runner.pre_tick()
	if not next.is_empty():
		_load_scene(next)
	if player != null and player_alive:
		player.sync_physics_pose()
	if ui != null:
		ui.tick(ui_delta)
	if not paused:
		# Spawns append for the next frame; queued tree exits retire after this pass.
		var animator_count := animators.size()
		for index in animator_count:
			var record: Dictionary = animators[index]
			if is_instance_valid(record.root) and record.root.is_visible_in_tree():
				if record.get("start_explosion", false):
					record.animator.parameter("ExplosionNumber", unity_random.range_int(1, 4))
					record.erase("start_explosion")
				record.animator.advance(delta)
		if player != null and player_alive:
			player.tick(delta)
		if boss != null:
			boss.tick(delta)
		_tick_background()
	if body != null and player_alive:
		player.sync_physics_pose()
		_update_camera(0.0 if paused else delta)
		terrain.follow(player_position)
	_tick_triggers()
	frame_number += 1
	if replay_runner != null:
		if replay_runner.frame < 0:
			replay_runner.pre_tick()
		replay_runner.post_tick()

func _physics_process(delta: float) -> void:
	if not pending_scene.is_empty():
		var next := pending_scene
		pending_scene = ""
		_load_scene(next)
	if paused or body == null or not player_alive:
		return
	player.physics_tick(delta)
	if boss != null:
		boss.physics_tick(delta)

func enterShop() -> void:
	if player != null:
		player.enterShop()

func exitShop() -> void:
	if player != null:
		player.exitShop()

func damage_player(amount: int) -> void:
	if player != null:
		player.loseHP(amount)

func begin_boss() -> void:
	if boss != null:
		boss.begin()

func refresh_tiles(cells: Array) -> void:
	if terrain != null:
		terrain.refresh(cells)

func make_animator(visual: CanvasItem, controller_guid: String) -> NativeAnimator:
	var animator := NativeAnimator.new()
	animator.bind_controller(controller_guid, visual, bridge)
	return animator

func spawn_prefab(prefab_name: String, position_unity: Vector2, parent: Node2D) -> Node2D:
	if not manifest.prefabs.has(prefab_name):
		push_error("Missing original prefab: " + prefab_name)
		return null
	var prefab_bridge := SceneBridge.new(manifest)
	add_child(prefab_bridge)
	prefab_bridge.scene_name = prefab_name
	prefab_bridge.scene = manifest.prefabs[prefab_name]
	prefab_bridge.world_root = world_root
	prefab_bridge.ui_root = ui_root
	var container := Node2D.new()
	parent.add_child(container)
	var owned_animators: Array = []
	prefab_bridge.instantiate_native(container, ui_root)
	container.global_transform = Transform2D(0.0, position_unity * UNIT)
	for root_id in prefab_bridge.scene.roots:
		var root: Node2D = prefab_bridge.nodes[str(root_id)]
		root.position = Vector2.ZERO
		root.visible = true
		var random_explosion := not prefab_bridge.properties(str(root_id), "ExplosionBehavior").is_empty() or not prefab_bridge.properties(str(root_id), "ExplosionWithoutParticlesBehavior").is_empty()
		for component in prefab_bridge.components(str(root_id)):
			if component.get("type", "") == "Animator" and prefab_name != "Fireball":
				var animator := NativeAnimator.new()
				animator.bind_controller(component.properties.get("m_Controller", {}).get("guid", ""), root, prefab_bridge)
				var record := {"root": root, "animator": animator, "start_explosion": random_explosion}
				animators.append(record)
				owned_animators.append(record)
				animator.animation_event.connect(_prefab_event.bind(container))
	container.set_meta("native_animators", owned_animators)
	container.tree_exited.connect(func():
		for record in owned_animators:
			animators.erase(record)
	)
	container.tree_exited.connect(prefab_bridge.queue_free)
	return container

func createPopup(text: String, kind: String) -> void:
	var popup := spawn_prefab("PlayerPopup", player_position, bridge.nodes[player_go])
	if popup == null:
		return
	popup.add_to_group("PlayerPopup")
	for record in popup.get_meta("native_animators"):
		record.animator.pulse(kind)
	for descendant in popup.find_children("*", "Label", true, false):
		descendant.text = text

func _prefab_event(method: String, argument: Variant, container: Node2D) -> void:
	if method in ["destroyObject", "DestroyObject", "destroy", "finishAnimation"]:
		container.queue_free()
	elif method == "playSound":
		audio.PlaySoundOneShot(str(argument))
	else:
		push_error("Unhandled prefab event: " + method)

func _scene_event(method: String, argument: Variant, id: String) -> void:
	var ship := bridge.properties(id, "MotherShipManager")
	if not ship.is_empty():
		match method:
			"arrivalSound": audio.PlaySoundOneShot("MothershipArrive")
			"departSound": audio.PlaySoundOneShot("MothershipLeave")
			"dropPlayer":
				bridge.set_active(ship.player, true)
				player_alive = true
				body.freeze = false
				audio.PlaySound("IdlePlayer")
			"finishAnimation":
				bridge.set_active(id, false)
				ui.displayTransmission(0)
		return
	if method == "playSound":
		audio.PlaySoundOneShot(str(argument))
	else:
		push_error("Unhandled original scene animation event: " + method)

func _tick_triggers() -> void:
	for trigger in scene_triggers:
		var visual := bridge.nodes[trigger.id] as Node2D
		if not is_instance_valid(visual):
			continue
		var enabled := visual.is_visible_in_tree()
		if trigger.area.monitoring != enabled:
			trigger.area.set_deferred("monitoring", enabled)

func _trigger_entered(collided: Node2D, trigger: Dictionary) -> void:
	if collided != (player_trigger if trigger.script in ["TransmissionTrigger", "StartBossfightTrigger", "BackgroundChangeColorTrigger"] else body) or not player_alive or not is_instance_valid(trigger.area):
		return
	var visual := bridge.nodes[trigger.id] as Node2D
	if not is_instance_valid(visual) or not visual.is_visible_in_tree():
		return
	var p: Dictionary = trigger.properties
	match trigger.script:
		"ShopDoorCollision":
			if ui.isUIOpen():
				return
			audio.PlayMusic("ShopMusic")
			ui.open_shop(p.linked_shop_object)
			visual.visible = false
		"TransmissionTrigger":
			ui.displayTransmission(int(p.get("transmission_index", 0)))
		"StartBossfightTrigger":
			begin_boss()
			visual.visible = false
		"BackgroundChangeColorTrigger":
			background_goal = {"goal": p.color_goal}

func _trigger_exited(collided: Node2D, trigger: Dictionary) -> void:
	if collided == body and is_instance_valid(trigger.area) and trigger.script == "ExitShopDoorCollision":
		bridge.set_active(trigger.properties.get("linked_door", {}), true)

func resetBackgroundColor() -> void:
	for id in bridge.scene.game_objects:
		var props := bridge.properties(id, "BackgroundScript")
		if not props.is_empty():
			background_goal = {"id": id, "goal": props.get("base_color", {})}

func _tick_background() -> void:
	if background_goal.is_empty():
		return
	for id in bridge.scene.game_objects:
		if bridge.properties(id, "BackgroundScript").is_empty() or not bridge.graphics.has(id):
			continue
		var sprite: CanvasItem = bridge.graphics[id]
		var goal: Dictionary = background_goal.get("goal", {})
		var color := sprite.modulate
		sprite.modulate = Color(move_toward(color.r, float(goal.get("r", color.r)), 0.0005), move_toward(color.g, float(goal.get("g", color.g)), 0.0005), move_toward(color.b, float(goal.get("b", color.b)), 0.0005))

func _resize_camera() -> void:
	if not is_instance_valid(camera):
		return
	# Unity's full-viewport orthographic size is the vertical half-span.
	# Use stretched viewport coordinates, not physical window pixels: 50 px/unit.
	camera.zoom = Vector2.ONE * get_viewport_rect().size.y / (_camera_orthographic_size * 100.0)

func _update_camera(delta: float) -> void:
	var viewport_units := get_viewport_rect().size / camera.zoom / 50.0
	var target: Vector2 = bridge.nodes[player_go].global_position
	var dead := viewport_units * Vector2(0.2, 0.1) * 25.0
	var offset := target - camera.global_position
	var desired := camera.global_position + Vector2(signf(offset.x) * maxf(0, absf(offset.x) - dead.x), signf(offset.y) * maxf(0, absf(offset.y) - dead.y))
	camera.global_position = camera.global_position.lerp(desired, 1.0 - exp(-4.605170186 * delta))
	var half_width := minf(viewport_units.x * 25.0, data.earthWidth * 25.0)
	camera.global_position.x = clampf(camera.global_position.x, half_width, data.earthWidth * 50.0 - half_width)

func _vec(value: Dictionary, fallback: Vector2 = Vector2.ZERO) -> Vector2:
	return Vector2(float(value.get("x", fallback.x)), float(value.get("y", fallback.y)))

