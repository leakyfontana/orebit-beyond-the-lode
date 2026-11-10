class_name PortBoss
extends Node

const UNITS := Vector2(1, -1)
const UNITY_FIXED_DELTA := 0.02
const HURTBOX_LAYER := 8

enum EncounterState { DORMANT, STARTING, RUNNING, ENDING }
enum PhaseState { UNSELECTED = -1, ONE = 0, TWO = 1 }
enum AnimationPassState { START_FRAME, RUNNING }
enum BehaviorOpportunity { BLOCKED, UPDATE }
enum Facing { RIGHT, LEFT }
enum MoveState { IDLE, PENDING }
enum CollisionState { DISABLED, ENABLED }
enum ImmunityState { VULNERABLE, BLINK_VISIBLE, BLINK_HIDDEN }
enum P1MotionState { IDLE, INTRO, INTRO_FINISHED, DEATH }
enum JumpTimerState { UNINITIALIZED, COUNTING, ELAPSED }
enum LandingState { INACTIVE, DELAYED, SEEKING_GROUND, LANDED }
enum AttackMonitorState { DISABLED, DAMAGE, DAMAGE_AND_HURTBOX }
enum LaserSweepState { STILL, NEGATIVE, POSITIVE }
enum LaserActivationState { INACTIVE, SWEEPING }
enum FireballState { FLYING, EXPIRED }
enum ContactState { ARMED, TOUCHING }
var host: Node
var bridge: SceneBridge
var phases: Array[Dictionary] = []
var encounter_state := EncounterState.DORMANT
var phase_state := PhaseState.UNSELECTED
var active: bool:
	get:
		return encounter_state == EncounterState.STARTING or encounter_state == EncounterState.RUNNING
	set(value):
		if value:
			encounter_state = EncounterState.STARTING if phase_state == PhaseState.UNSELECTED else EncounterState.RUNNING
		else:
			encounter_state = EncounterState.DORMANT
var phase: int:
	get: return phase_state
	set(value): phase_state = value as PhaseState
var projectiles: Array[Dictionary] = []
var attacks: Array[Dictionary] = []
var player_shapes: Array[Dictionary] = []
var ceiling: StaticBody2D
var trigger: Dictionary = {}
var laser_animator: NativeAnimator
var laser_sweep := LaserSweepState.STILL
var laser_direction: float:
	get:
		match laser_sweep:
			LaserSweepState.NEGATIVE: return -1.0
			LaserSweepState.POSITIVE: return 1.0
		return 0.0
var owned_root_ids: Array[String] = []
var frozen_particle_roots: Array[Dictionary] = []
var _float32_buffer := PackedFloat32Array([0.0])

func configure(main: Node) -> void:
	host = main
	bridge = host.bridge
	for id in bridge.scene.game_objects:
		var p := bridge.properties(id, "StartBossfightTrigger")
		if not p.is_empty():
			trigger = p
		if not bridge.properties(id, "freezeParticulatorYAxis").is_empty():
			var particle_root: Node2D = bridge.node(id)
			frozen_particle_roots.append({"node": particle_root, "y": particle_root.global_position.y})
		for script in ["P1BossMethods", "P2BossMethods"]:
			p = bridge.properties(id, script)
			if p.is_empty():
				continue
			var root: Node2D = bridge.node(id)
			owned_root_ids.append(str(id))
			phases.append({"id": id, "node": root, "properties": p, "animator": null,
				"hp": float(p.max_hp), "immunity": ImmunityState.VULNERABLE, "invincible": 0.0, "frames": 0,
				"facing": Facing.LEFT if bool(p.is_facing_left) else Facing.RIGHT,
				"collision_state": CollisionState.ENABLED, "behaviors": [], "behavior_generation": 0,
				"animation_pass": AnimationPassState.START_FRAME, "animation_start_frame": 0,
				"p1_motion": P1MotionState.IDLE, "jump_timer": JumpTimerState.UNINITIALIZED,
				"landing": LandingState.INACTIVE, "jump_time_left": 0.0,
				"time_left": 0.0, "duration": 0.0, "height": 0.0,
				"ground": 0.0, "body": null, "solid_shapes": [], "move_target": null})
	phases.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return bridge.scene.game_objects[a.id].tag < bridge.scene.game_objects[b.id].tag)
	for i in range(phases.size()):
		var d := phases[i]
		_create_phase_body(d)
		_set_collisions(d, false)
	for id in bridge.scene.game_objects:
		var p := bridge.properties(id, "BossAttackBehavior")
		if not p.is_empty():
			var attack := {"node": bridge.node(id), "damage": int(p.damage), "owner": id, "area": null}
			var area := Area2D.new()
			area.collision_layer = 0
			area.collision_mask = 0
			var tag: String = bridge.scene.game_objects[id].tag
			area.monitorable = tag in ["BossP1", "BossP2"]
			attack.node.add_child(area)
			for s in _colliders(bridge.components(id), true):
				var collision := CollisionShape2D.new()
				collision.shape = s.shape
				collision.transform = s.transform
				area.add_child(collision)
			attack.area = area
			area.body_entered.connect(_attack_entered.bind(attack))
			attacks.append(attack)
	var player_id: String = bridge.component_owner(phases[0].properties.player) if not phases.is_empty() else ""
	player_shapes = _colliders(bridge.components(player_id), false)
	if not trigger.is_empty():
		var ceiling_id := bridge.component_owner(trigger.ceiling_collider)
		for c in bridge.components(ceiling_id):
			if c.get("type", "") == "BoxCollider2D":
				ceiling = _static_body(bridge.node(ceiling_id), c)
				ceiling.collision_layer = 0

func begin() -> void:
	if active or phases.is_empty():
		return
	encounter_state = EncounterState.STARTING
	host.audio.PlayMusic("BossMusic")
	if not trigger.is_empty():
		bridge.set_active(trigger.ceiling_collider, true)
		bridge.set_active(trigger.m_GameObject, false)
	if ceiling != null:
		ceiling.collision_layer = 1
	_enable_phase(0)

func _enable_phase(index: int) -> void:
	phase_state = index as PhaseState
	encounter_state = EncounterState.RUNNING
	var d := phases[index]
	d.node.visible = true
	d.hp = float(d.properties.max_hp)
	_set_collisions(d, true)
	d.body.freeze = int(bridge.properties(d.id, "Rigidbody2D").get("m_BodyType", 1)) != 0
	if index == 0:
		bridge.set_active(d.properties.boss_health_object, true)
	else:
		_turn(d)
	_update_ui(d)
	var controller: Dictionary = bridge.properties(d.id, "Animator").get("m_Controller", {})
	var animator: NativeAnimator = host.make_animator(d.node, str(controller.get("guid", "")))
	d.animator = animator
	animator.animation_event.connect(_event.bind(index))
	animator.state_entered.connect(_state_enter.bind(index))
	animator.state_exited.connect(_state_exit.bind(index))
	# Public stock-engine ordering: initialize synchronously, then skip this
	# process frame's delta and behavior update.
	d.animation_pass = AnimationPassState.START_FRAME
	d.animation_start_frame = Engine.get_process_frames()
	animator.advance(0.0)

func tick(delta: float) -> void:
	if host.paused:
		return
	var projectile_index := 0
	while projectile_index < projectiles.size():
		var projectile := projectiles[projectile_index]
		projectile.life -= delta
		if projectile.life <= 0 or not is_instance_valid(projectile.node):
			projectile.state = FireballState.EXPIRED
		if projectile.state == FireballState.EXPIRED:
			if is_instance_valid(projectile.body):
				projectile.body.queue_free()
			projectiles.remove_at(projectile_index)
		else:
			projectile_index += 1
	if not active or phase < 0:
		return
	var d := phases[phase]
	_sync_phase_pose(d)
	_tick_immunity(d, delta)
	var behavior_generation: int = d.behavior_generation
	_advance_phase_animation(d, delta)
	# Unity calls OnStateEnter/OnStateExit instead of OnStateUpdate on those
	# evaluation frames. Never charge the newly entered behavior a full delta.
	if _behavior_opportunity(d, behavior_generation) == BehaviorOpportunity.UPDATE:
		for behavior in d.behaviors:
			_behavior_tick(d, behavior, delta)
			if phases[phase] != d:
				break
	if phase == 0:
		var laser: Node2D = bridge.node(d.properties.laser_attack_gameobject)
		if _laser_activation(laser) == LaserActivationState.SWEEPING:
			laser.rotation += deg_to_rad(-100.0 * laser_direction * delta)
			if laser_animator != null:
				laser_animator.advance(delta)
	for frozen in frozen_particle_roots:
		frozen.node.global_position.y = frozen.y
	_refresh_attack_monitors()

func _advance_phase_animation(d: Dictionary, delta: float) -> void:
	if d.animation_pass == AnimationPassState.START_FRAME:
		if d.animation_start_frame == Engine.get_process_frames():
			return
		d.animation_pass = AnimationPassState.RUNNING
	if d.animator != null:
		d.animator.advance(delta)

func _behavior_opportunity(d: Dictionary, generation: int) -> BehaviorOpportunity:
	if d.behavior_generation != generation or d.animation_start_frame == Engine.get_process_frames():
		return BehaviorOpportunity.BLOCKED
	return BehaviorOpportunity.UPDATE

func _begin_immunity(d: Dictionary) -> void:
	d.invincible = float(d.properties.invincibility_time)
	if d.invincible > 0.0:
		var visual: CanvasItem = bridge.graphics.get(d.id)
		d.immunity = ImmunityState.BLINK_HIDDEN if visual != null and visual.modulate.a == 0.0 else ImmunityState.BLINK_VISIBLE
	else:
		d.immunity = ImmunityState.VULNERABLE

func _tick_immunity(d: Dictionary, delta: float) -> void:
	if d.immunity == ImmunityState.VULNERABLE:
		return
	d.invincible = _f32(d.invincible - _f32(delta))
	d.frames -= 1
	var visual: CanvasItem = bridge.graphics.get(d.id)
	if d.frames <= 0:
		d.frames = int(d.properties.frames_of_invisibility)
		if visual != null:
			d.immunity = ImmunityState.BLINK_VISIBLE if visual.modulate.a == 0.0 else ImmunityState.BLINK_HIDDEN
			visual.modulate.a = 0.0 if d.immunity == ImmunityState.BLINK_HIDDEN else 1.0
	if d.invincible <= 0:
		d.immunity = ImmunityState.VULNERABLE
		if visual != null:
			visual.modulate.a = 1.0
			d.frames = 0

func _laser_activation(laser: Node2D) -> LaserActivationState:
	return LaserActivationState.SWEEPING if laser != null and laser.is_visible_in_tree() else LaserActivationState.INACTIVE

func _move_request_state(d: Dictionary) -> MoveState:
	# Keep the public nullable MovePosition mailbox, including fixture writes.
	return MoveState.IDLE if d.move_target == null else MoveState.PENDING

func physics_tick(_delta: float) -> void:
	for projectile in projectiles:
		projectile.body.freeze = host.paused
	if host.paused or not host.player_alive:
		return
	if active and phase >= 0:
		var d := phases[phase]
		if _move_request_state(d) == MoveState.PENDING:
			# MovePosition is consumed by the next native fixed step, not a
			# render-frame teleport of a StaticBody2D's parent.
			d.body.global_position = d.move_target
			d.move_target = null
	_refresh_attack_monitors()
	for p in projectiles:
		var touching := _hits_player(p.node, p.shapes)
		if touching and p.contact == ContactState.ARMED:
			host.damage_player(p.damage)
		p.contact = ContactState.TOUCHING if touching else ContactState.ARMED

func damage_from_attack(collider: Node2D, damage: int) -> bool:
	if not active or phase < 0:
		return false
	var d := phases[phase]
	if d.collision_state == CollisionState.DISABLED or d.immunity != ImmunityState.VULNERABLE or d.hp <= 0:
		return false
	var hit: bool = collider == d.body
	var tag := "BossP1" if phase == 0 else "BossP2"
	for attack in attacks:
		if collider == attack.area and bridge.scene.game_objects[attack.owner].tag == tag:
			hit = true
			break
	if not hit:
		return false
	d.hp = maxf(0.0, d.hp - damage)
	if d.hp <= 0:
		d.animator.pulse("DeathTrigger")
	else:
		_begin_immunity(d)
	host.audio.PlaySoundOneShot("P1Damage1" if host.unity_random.range_float(0.0, 1.0) < 0.5 else "P1Damage2")
	_update_ui(d)
	return true

func _state_enter(_name: String, behaviors: Array, index: int) -> void:
	var d := phases[index]
	d.behaviors = behaviors
	d.behavior_generation += 1
	for b in behaviors:
		var p: Dictionary = b.get("properties", {})
		match str(b.get("script", "")):
			"P1BossIntro":
				d.p1_motion = P1MotionState.INTRO
				d.duration = _f32(float(p.intro_time))
				d.time_left = d.duration
				d.height = _height(d) * 1.5
				d.node.position.y += d.height
				_teleport_phase(d)
				host.audio.PlaySoundOneShot("P1Laugh")
				_particles(d, "sustained_particles", true)
			"P1BossDeathBehavior":
				d.p1_motion = P1MotionState.DEATH
				d.duration = _f32(float(p.death_time))
				d.time_left = d.duration
				d.height = _height(d) * 1.5
				_set_collisions(d, false)
				host.audio.PlaySoundOneShot("P1Death")
				_particles(d, "sustained_particles", true)
			"P2IntroBehavior":
				_set_collisions(d, false)
				d.ground = -d.node.global_position.y + _height(d) * 0.5 + 0.05
				# The source mutates this field without resetting it on re-entry.
				if d.jump_timer == JumpTimerState.UNINITIALIZED:
					d.jump_time_left = _f32(float(p.time_until_collision_reactivation))
					d.jump_timer = JumpTimerState.COUNTING
				d.landing = LandingState.DELAYED if d.jump_timer == JumpTimerState.COUNTING else LandingState.SEEKING_GROUND
				d.body.apply_central_force(Vector2(float(p.jump_force_x) * (-1 if d.facing == Facing.LEFT else 1), float(p.jump_force_y)) * UNITS)
				host.audio.PlaySoundOneShot("P2Breakout")
				host.ui.displayTransmission(13)
				_particles(d, "burst_particles", true)

func _state_exit(_name: String, behaviors: Array, index: int) -> void:
	var d := phases[index]
	for b in behaviors:
		match str(b.get("script", "")):
			"P1BossIntro", "P1BossDeathBehavior":
				d.p1_motion = P1MotionState.IDLE
				_particles(d, "sustained_particles", false)
				if b.get("script", "") == "P1BossDeathBehavior":
					_set_collisions(d, true)
			"P2IntroBehavior":
				d.landing = LandingState.INACTIVE
				_set_collisions(d, true)

func _behavior_tick(d: Dictionary, b: Dictionary, delta: float) -> void:
	var p: Dictionary = b.get("properties", {})
	match str(b.get("script", "")):
		"BossMovement", "P2BossMovementBehavior":
			var target := 0.5 if d.facing == Facing.LEFT else 35.5
			var x: float = d.node.global_position.x
			if absf(target - x) <= 0.1:
				_flip(d)
			d.move_target = Vector2(move_toward(x, target, float(p.speed) * delta), d.node.global_position.y)
		"P1BossIntro":
			if d.p1_motion != P1MotionState.INTRO and d.p1_motion != P1MotionState.INTRO_FINISHED:
				return
			d.time_left = _f32(d.time_left - _f32(delta))
			d.node.position.y -= d.height * delta / d.duration
			_teleport_phase(d)
			if d.time_left <= 0.0:
				d.p1_motion = P1MotionState.INTRO_FINISHED
			if d.p1_motion == P1MotionState.INTRO_FINISHED:
				d.animator.pulse("IntroIsFinished")
				host.ui.displayTransmission(12)
		"P1BossDeathBehavior":
			if d.p1_motion != P1MotionState.DEATH:
				return
			d.time_left = _f32(d.time_left - _f32(delta))
			d.node.position.y += d.height * delta / d.duration
			_teleport_phase(d)
			if d.time_left <= 0.0:
				_finish_death(0)
		"P2IntroBehavior":
			match d.landing:
				LandingState.INACTIVE:
					return
				LandingState.DELAYED:
					if d.jump_time_left > 0.0:
						d.jump_time_left = _f32(d.jump_time_left - _f32(delta))
						return
					d.jump_timer = JumpTimerState.ELAPSED
					d.landing = LandingState.SEEKING_GROUND
			# Landing remains repeatable until the Animator exits; the source's
			# sticky timer is not reset on re-entry.
			if d.landing == LandingState.SEEKING_GROUND or d.landing == LandingState.LANDED:
				if -d.node.global_position.y - _height(d) * 0.5 <= d.ground:
					d.landing = LandingState.LANDED
					d.animator.pulse("FinishedJumping")
					d.body.linear_velocity = Vector2.ZERO
					d.body.angular_velocity = 0.0
					d.body.freeze_mode = RigidBody2D.FREEZE_MODE_KINEMATIC
					d.body.freeze = true
					_turn(d)
					_particles(d, "burst_particles", true)

func _event(method: String, argument: Variant, index: int) -> void:
	var d := phases[index]
	match method:
		"finishOneWalkCycle":
			_turn(d)
			var random: float = host.unity_random.range_float(0.0, 1.0)
			if random < 0.33:
				d.animator.pulse("StickAttack" if index == 0 else "FireballAttack")
			elif random < 0.66:
				d.animator.pulse("LaserAttack" if index == 0 else "ArmAttack")
		"activateLaserAttack":
			bridge.set_active(d.properties.laser_attack_gameobject, true)
			var laser: Node2D = bridge.node(d.properties.laser_attack_gameobject)
			var offset: float = host.unity_random.range_float(-1.0, 1.0)
			var difference: Vector2 = host.player_position - laser.global_position / UNITS
			laser.global_rotation = -(difference.angle() - PI * 0.5 + offset * PI * 0.5)
			laser_sweep = LaserSweepState.NEGATIVE if offset <= 0 else LaserSweepState.POSITIVE
			if laser_animator == null:
				var id := bridge.component_owner(d.properties.laser_attack_gameobject)
				laser_animator = host.make_animator(laser, str(bridge.properties(id, "Animator").m_Controller.guid))
		"deactivateLaserAttack": bridge.set_active(d.properties.laser_attack_gameobject, false)
		"launchFireball": _fireball(d)
		"playSound": host.audio.PlaySoundOneShot(str(argument))
		"startSustainedParticles": _particles(d, "sustained_particles", true)
		"stopSustainedParticles": _particles(d, "sustained_particles", false)
		"startBurstParticles": _particles(d, "burst_particles", true)
		"startSmallBurstParticles": _particles(d, "small_burst_particles", true)
		"deactivateCollisions": _set_collisions(d, false)
		"reactivateCollisions": _set_collisions(d, true)
		"finishDeath": _finish_death(index)
		"playTransmission": host.ui.displayTransmission(12 + index)

func _finish_death(index: int) -> void:
	if index == 0 and phase_state == PhaseState.ONE:
		var d := phases[0]
		# SetActive invokes P2.OnEnable (including its turn) before the source
		# copies P1's X position; do not turn against the already-moved phase.
		_enable_phase(1)
		phases[1].node.global_position.x = d.node.global_position.x
		_teleport_phase(phases[1])
		bridge.set_active(d.properties.p1_boss_head, false)
		bridge.set_active(d.properties.p2_boss_head, true)
		d.node.visible = false
		_set_collisions(d, false)
		_particles(d, "sustained_particles", false)
	elif index == 1:
		encounter_state = EncounterState.ENDING
		host.audio.PlayMusic("MainLevelMusic")
		host.audio.StopAllSounds()
		host.change_scene("Ending")

func _flip(d: Dictionary) -> void:
	d.node.scale.x *= -1
	d.facing = Facing.RIGHT if d.facing == Facing.LEFT else Facing.LEFT
	_sync_phase_shapes(d)

func _turn(d: Dictionary) -> void:
	var x: float = d.node.global_position.x
	if (host.player_position.x < x and d.facing == Facing.RIGHT) or (host.player_position.x > x and d.facing == Facing.LEFT):
		_flip(d)

func _height(d: Dictionary) -> float:
	var sprite: Sprite2D = bridge.graphics.get(d.id)
	if sprite == null or sprite.texture == null:
		return 0.0
	return sprite.get_rect().size.y * absf(sprite.global_scale.y)

func _update_ui(d: Dictionary) -> void:
	bridge.set_value(d.properties.boss_health_bar, d.hp / float(d.properties.max_hp))
	bridge.set_text(d.properties.boss_health_text, "%d/%d" % [int(d.hp), int(d.properties.max_hp)])

func _particles(d: Dictionary, key: String, emitting: bool) -> void:
	var root: Node = bridge.node(d.properties.get(key, {}))
	if root != null:
		_emit_particles(root, emitting)

func _emit_particles(root: Node, emitting: bool) -> void:
	if root is GPUParticles2D:
		root.emitting = emitting
		if emitting:
			root.restart()
	for child in root.get_children():
		_emit_particles(child, emitting)

func _create_phase_body(d: Dictionary) -> void:
	var rigid := bridge.properties(d.id, "Rigidbody2D")
	var body := RigidBody2D.new()
	body.name = "BossPhysics"
	body.position = d.node.global_position
	body.process_mode = Node.PROCESS_MODE_PAUSABLE
	body.freeze_mode = RigidBody2D.FREEZE_MODE_KINEMATIC
	body.freeze = true
	body.lock_rotation = (int(rigid.get("m_Constraints", 0)) & 4) != 0
	body.mass = float(rigid.get("m_Mass", 1.0))
	body.gravity_scale = float(rigid.get("m_GravityScale", 1.0))
	body.linear_damp_mode = RigidBody2D.DAMP_MODE_REPLACE
	body.linear_damp = float(rigid.get("m_LinearDrag", 0.0))
	body.angular_damp_mode = RigidBody2D.DAMP_MODE_REPLACE
	body.angular_damp = float(rigid.get("m_AngularDrag", 0.05))
	body.collision_layer = 0
	body.collision_mask = 0
	d.body = body
	for s in _colliders(bridge.components(d.id), false):
		var collision := CollisionShape2D.new()
		collision.shape = s.shape
		body.add_child(collision)
		d.solid_shapes.append({"node": collision, "transform": s.transform})
	_sync_phase_shapes(d)
	add_child(body)

func _sync_phase_shapes(d: Dictionary) -> void:
	var basis: Transform2D = d.node.global_transform
	basis.origin = Vector2.ZERO
	for s in d.solid_shapes:
		s.node.transform = basis * s.transform

func _sync_phase_pose(d: Dictionary) -> void:
	var pose: Transform2D = PhysicsServer2D.body_get_state(d.body.get_rid(), PhysicsServer2D.BODY_STATE_TRANSFORM)
	d.node.global_position = pose.origin

func _teleport_phase(d: Dictionary) -> void:
	# Unity Transform writes teleport even a kinematic Rigidbody2D. Reserve
	# native kinematic motion for the source's explicit MovePosition requests.
	var body: RigidBody2D = d.body
	var mode := body.freeze_mode
	if body.freeze:
		body.freeze_mode = RigidBody2D.FREEZE_MODE_STATIC
	body.global_position = d.node.global_position
	if body.freeze:
		body.freeze_mode = mode

func _set_collisions(d: Dictionary, enabled: bool) -> void:
	d.collision_state = CollisionState.ENABLED if enabled else CollisionState.DISABLED
	d.body.collision_layer = 1 if enabled else 0
	d.body.collision_mask = 2 if enabled else 0
	# GetComponents<Collider2D>() includes the root damage trigger too.
	_refresh_attack_monitors()

func _attack_monitor_state(attack: Dictionary) -> AttackMonitorState:
	if not active or attack.node == null or not attack.node.is_visible_in_tree():
		return AttackMonitorState.DISABLED
	for d in phases:
		if attack.owner == d.id and d.collision_state == CollisionState.DISABLED:
			return AttackMonitorState.DISABLED
	return AttackMonitorState.DAMAGE_AND_HURTBOX if attack.area.monitorable else AttackMonitorState.DAMAGE

func _refresh_attack_monitors() -> void:
	for attack in attacks:
		var monitor := _attack_monitor_state(attack)
		var mask := 0 if monitor == AttackMonitorState.DISABLED else 2
		if attack.area.collision_mask != mask:
			attack.area.collision_mask = mask
		var layer: int = HURTBOX_LAYER if monitor == AttackMonitorState.DAMAGE_AND_HURTBOX else 0
		if attack.area.collision_layer != layer:
			attack.area.collision_layer = layer

func _attack_entered(body: Node2D, attack: Dictionary) -> void:
	# The original uses OnTriggerEnter2D, not an overlap poll after the solid
	# contact solver has already separated the player from the boss.
	if body == host.body and host.player_alive and not host.paused and _attack_monitor_state(attack) != AttackMonitorState.DISABLED:
		host.damage_player(attack.damage)

func _vector(p: Dictionary) -> Vector2:
	return Vector2(float(p.get("x", 0)), float(p.get("y", 0)))

func _colliders(components: Array, triggers: bool) -> Array[Dictionary]:
	var result: Array[Dictionary] = []
	for c in components:
		var p: Dictionary = c.get("properties", {})
		if not bool(p.get("m_Enabled", true)) or bool(p.get("m_IsTrigger", false)) != triggers:
			continue
		var shape: Shape2D
		var rotation := 0.0
		match str(c.get("type", "")):
			"BoxCollider2D":
				var box := RectangleShape2D.new()
				box.size = _vector(p.m_Size)
				shape = box
			"CircleCollider2D":
				var circle := CircleShape2D.new()
				circle.radius = float(p.m_Radius)
				shape = circle
			"CapsuleCollider2D":
				var capsule := CapsuleShape2D.new()
				var size := _vector(p.m_Size)
				var horizontal := int(p.get("m_Direction", 0)) == 1
				capsule.radius = (size.y if horizontal else size.x) * 0.5
				capsule.height = maxf(capsule.radius * 2.0, size.x if horizontal else size.y)
				shape = capsule
				rotation = PI * 0.5 if horizontal else 0.0
			"EdgeCollider2D":
				var points: Array = p.get("m_Points", [])
				for i in range(points.size() - 1):
					var segment := SegmentShape2D.new()
					segment.a = (_vector(points[i]) + _vector(p.get("m_Offset", {}))) * UNITS
					segment.b = (_vector(points[i + 1]) + _vector(p.get("m_Offset", {}))) * UNITS
					result.append({"shape": segment, "transform": Transform2D.IDENTITY})
				continue
			_: continue
		result.append({"shape": shape, "transform": Transform2D(rotation, _vector(p.get("m_Offset", {})) * UNITS)})
	return result

func _static_body(root: Node2D, component: Dictionary) -> StaticBody2D:
	var shapes := _colliders([component], false)
	if shapes.is_empty():
		return null
	var body := StaticBody2D.new()
	body.collision_layer = 1
	body.collision_mask = 0
	root.add_child(body)
	for s in shapes:
		var collision := CollisionShape2D.new()
		collision.shape = s.shape
		collision.transform = s.transform
		body.add_child(collision)
	return body

func _hits_player(root: Node2D, shapes: Array) -> bool:
	var player_root: Node2D = bridge.node(phases[0].properties.player)
	if player_root == null:
		return false
	var player_transform := player_root.global_transform
	player_transform.origin = host.player_position * UNITS
	for s in shapes:
		for p in player_shapes:
			if s.shape.collide(root.global_transform * s.transform, p.shape, player_transform * p.transform):
				return true
	return false

func _fireball(d: Dictionary) -> void:
	var prefab: Dictionary = bridge.manifest.prefabs.Fireball
	var components: Array = prefab.objects.values()
	var body := RigidBody2D.new()
	body.position = d.node.global_position
	for component in components:
		if component.get("type", "") == "Rigidbody2D":
			body.gravity_scale = float(component.properties.m_GravityScale)
			body.mass = float(component.properties.m_Mass)
			break
	body.collision_layer = 0
	body.collision_mask = 1
	body.linear_damp = 0.0
	body.angular_damp = 0.0
	body.linear_damp_mode = RigidBody2D.DAMP_MODE_REPLACE
	body.angular_damp_mode = RigidBody2D.DAMP_MODE_REPLACE
	body.constant_force = Vector2.ZERO
	var material := PhysicsMaterial.new()
	material.bounce = 1.0
	material.friction = 0.0
	body.physics_material_override = material
	host.add_child(body)
	var node: Node2D = host.spawn_prefab("Fireball", d.node.global_position / UNITS, body)
	var solid_shapes := _colliders(components, false)
	for s in solid_shapes:
		var collider := CollisionShape2D.new()
		collider.shape = s.shape
		collider.transform = node.transform * s.transform
		body.add_child(collider)
	body.linear_velocity = Vector2(-150 if d.facing == Facing.LEFT else 150, 400) * UNITY_FIXED_DELTA * UNITS
	# Geometry and inertia now use the source's metre-based units directly.
	body.apply_torque_impulse(-host.unity_random.single(host.unity_random.range_float(-1.0, 1.0) * 360.0) * UNITY_FIXED_DELTA)
	var lifetime := 15.0
	var damage := 25
	for c in components:
		if c.get("script", "") == "P2FireballBehavior":
			lifetime = float(c.properties.lifetime)
		if c.get("script", "") == "BossAttackBehavior":
			damage = int(c.properties.damage)
	projectiles.append({"node": node, "body": body, "life": lifetime, "damage": damage,
		"shapes": _colliders(components, true), "state": FireballState.FLYING, "contact": ContactState.ARMED})

func _f32(value: float) -> float:
	_float32_buffer[0] = value
	return _float32_buffer[0]
