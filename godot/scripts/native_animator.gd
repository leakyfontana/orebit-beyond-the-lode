class_name NativeAnimator
extends Node

signal animation_event(method: String, argument: Variant)
signal state_entered(name: String, behaviors: Array)
signal state_exited(name: String, behaviors: Array)

const SetResource = preload("res://scripts/native_animation_set.gd")
const BOUNDARY_EPSILON := 0.000000001

## Texture/pivot/PPU are one discrete sprite pose. Godot blends numeric tracks,
## but textures are not interpolatable. Filter the non-dominant native pose so
## all three native property tracks switch together at the original midpoint.
class BoundTree extends AnimationTree:
	var animator: NativeAnimator
	func _post_process_key_value(animation: Animation, track: int, value: Variant, _object_id: int, _object_sub_idx: int) -> Variant:
		if not animation.has_meta("sprite_tracks") or track not in animation.get_meta("sprite_tracks"):
			return value
		var playback := animator._playback
		if playback == null or playback.get_fading_from_node() == &"":
			return value
		var dominant := playback.get_current_node()
		if playback.get_fading_position() < playback.get_fading_length() * 0.5:
			dominant = playback.get_fading_from_node()
		var definition: Dictionary = animator._set.states[dominant]
		return value if str(animation.get_meta("source_state", "")) == str(definition.get("source_state", "")) else null

var current_state: String:
	get:
		if _playback == null or _playback.get_current_node() == &"":
			return ""
		return str(_set.states[_playback.get_current_node()].name)
var state_time: float:
	get:
		return _elapsed

## Referenced directly by baked native advance_expression strings.
var native_parameters: Dictionary = {}
var native_gates: Dictionary = {}
var native_transition_available: bool = false
var native_playback: AnimationNodeStateMachinePlayback:
	get: return _playback

var _set: NativeAnimationSet
var _root: Node
var _player: AnimationPlayer
var _tree: BoundTree
var _playback: AnimationNodeStateMachinePlayback
var _opened_gates: Array[StringName] = []
var _started: bool = false
var _elapsed: float = 0.0
var _event_methods: Array[String] = []
var _event_arguments: Array = []
var _endpoint_animation: StringName
var _used_gates: Dictionary = {}

func bind_controller(controller_id: String, actor_root: Node, bridge: SceneBridge) -> void:
	assert(actor_root != null and bridge != null, "NativeAnimator requires actor and SceneBridge")
	if get_parent() == null:
		actor_root.add_child(self)
	if is_instance_valid(_tree):
		_tree.active = false
		_tree.free()
	if is_instance_valid(_player):
		_player.free()
	_playback = null
	_started = false
	_elapsed = 0.0
	_root = actor_root
	_set = load("res://animations/controllers/%s.tres" % controller_id) as NativeAnimationSet
	assert(_set != null and _set.schema_version == 1, "Missing/outdated baked native controller: " + controller_id)
	native_parameters.clear()
	native_gates.clear()
	native_transition_available = false
	_opened_gates.clear()
	_event_methods.clear()
	_event_arguments.clear()
	_endpoint_animation = &""
	for key in _set.parameters:
		native_parameters[key] = _set.parameters[key].default
	for gate in _set.gates:
		native_gates[gate] = false
	if _set.empty:
		return # The published HullUI controller really contains no states.
	var library := AnimationLibrary.new()
	for animation_name in _set.library.get_animation_list():
		# Duplicate track storage for actor-specific paths, never texture assets.
		library.add_animation(animation_name, _set.library.get_animation(animation_name).duplicate(false))
	var targets: Array[NodePath] = []
	var factors: Array[float] = []
	var defaults: Array = []
	var enabled_slots: Array[bool] = []
	var node_ids: Dictionary = {}
	for id in bridge.nodes:
		var mapped: Node = bridge.nodes[id]
		if is_instance_valid(mapped):
			node_ids[mapped.get_instance_id()] = str(id)
	for binding in _set.bindings:
		var node := _resolve_path(str(binding.path), actor_root, bridge, node_ids)
		assert(node != null, "Unresolved native animation path: " + str(binding.path))
		var target: Node = node
		var property: String = str(binding.property)
		var factor := 1.0
		match str(binding.kind):
			"graphic", "sprite", "sprite_geometry": target = _graphic(node, false, bridge, node_ids)
			"text": target = _graphic(node, true, bridge, node_ids)
			"position": factor = (1.0 if node is Control else 50.0) * (-1.0 if property.ends_with(":y") else 1.0)
			"rotation": factor = -PI / 180.0
			"scale_z":
				if not node.has_meta("unity_local_scale_z"):
					var transform := bridge.properties(str(node_ids.get(node.get_instance_id(), "")), "RectTransform" if node is Control else "Transform")
					node.set_meta("unity_local_scale_z", float(transform.get("m_LocalScale", {}).get("z", 1.0)))
		assert(target != null, "Native animation has no graphic: " + str(binding.path))
		var enabled := str(binding.kind) != "sprite_geometry" or target is Sprite2D
		enabled_slots.append(enabled)
		if not enabled:
			targets.append(NodePath())
			factors.append(1.0)
			defaults.append(null)
			continue # UI textures do not have Sprite2D's world PPU/pivot.
		if str(binding.kind) == "text":
			var label := target as Label
			if not label.has_theme_color_override("font_color"):
				label.add_theme_color_override("font_color", label.get_theme_color("font_color"))
		var path := NodePath(str(get_path_to(target)) + ":" + property)
		targets.append(path)
		factors.append(factor)
		defaults.append(target.get_indexed(NodePath(property)))
	var reset := Animation.new()
	reset.length = 0.001
	for slot in _set.bindings.size():
		if not enabled_slots[slot]:
			continue
		var binding: Dictionary = _set.bindings[slot]
		var track_type := Animation.TYPE_BEZIER if bool(binding.bezier) else Animation.TYPE_VALUE
		var track := reset.add_track(track_type)
		reset.track_set_path(track, targets[slot])
		if track_type == Animation.TYPE_BEZIER:
			reset.bezier_track_insert_key(track, 0.0, float(defaults[slot]))
		else:
			reset.value_track_set_update_mode(track, Animation.UPDATE_CONTINUOUS)
			reset.track_set_interpolation_type(track, Animation.INTERPOLATION_NEAREST)
			reset.track_insert_key(track, 0.0, defaults[slot])
	for animation_name in library.get_animation_list():
		var animation := library.get_animation(animation_name)
		for track in animation.get_track_count():
			if animation.track_get_type(track) == Animation.TYPE_METHOD:
				animation.track_set_path(track, NodePath("."))
				continue
			var slot := int(str(animation.track_get_path(track)).get_slice(":", 0).trim_prefix("slot_"))
			if not enabled_slots[slot]:
				animation.track_set_enabled(track, false)
				continue
			animation.track_set_path(track, targets[slot])
			var factor: float = factors[slot]
			if factor == 1.0:
				continue
			for key in animation.track_get_key_count(track):
				if animation.track_get_type(track) == Animation.TYPE_BEZIER:
					animation.bezier_track_set_key_value(track, key, animation.bezier_track_get_key_value(track, key) * factor)
					var incoming := animation.bezier_track_get_key_in_handle(track, key)
					var outgoing := animation.bezier_track_get_key_out_handle(track, key)
					animation.bezier_track_set_key_in_handle(track, key, incoming * Vector2(1.0, factor))
					animation.bezier_track_set_key_out_handle(track, key, outgoing * Vector2(1.0, factor))
				else:
					animation.track_set_key_value(track, key, float(animation.track_get_key_value(track, key)) * factor)
	library.add_animation(&"RESET", reset)
	_player = AnimationPlayer.new()
	_player.name = "NativeAnimationPlayer"
	add_child(_player)
	_player.root_node = NodePath("..")
	_player.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	_player.add_animation_library(&"", library)
	_tree = BoundTree.new()
	_tree.name = "NativeAnimationTree"
	_tree.animator = self
	add_child(_tree)
	_tree.root_node = NodePath("..")
	_tree.anim_player = _tree.get_path_to(_player)
	_tree.advance_expression_base_node = NodePath("..")
	_tree.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_MANUAL
	_tree.callback_mode_method = AnimationMixer.ANIMATION_CALLBACK_MODE_METHOD_IMMEDIATE
	_tree.callback_mode_discrete = AnimationMixer.ANIMATION_CALLBACK_MODE_DISCRETE_FORCE_CONTINUOUS
	_tree.deterministic = true
	_tree.tree_root = _set.machine
	_tree.active = true
	_playback = _tree.get("parameters/playback") as AnimationNodeStateMachinePlayback
	_playback.state_started.connect(_state_started)
	_playback.state_finished.connect(_state_finished)

func condition(name: StringName, enabled: bool) -> void:
	assert(_set.parameters.has(name) and int(_set.parameters[name].type) == 4, "Not a native bool condition: " + str(name))
	native_parameters[name] = enabled

func parameter(name: StringName, value: Variant) -> void:
	assert(_set.parameters.has(name), "Unknown native parameter: " + str(name))
	var type: int = int(_set.parameters[name].type)
	assert(type != 9, "Use pulse for native trigger: " + str(name))
	match type:
		1: native_parameters[name] = float(value)
		3: native_parameters[name] = int(value)
		4: native_parameters[name] = bool(value)

func pulse(name: StringName) -> void:
	assert(_set.parameters.has(name) and int(_set.parameters[name].type) == 9, "Not a native trigger: " + str(name))
	native_parameters[name] = true

func advance(delta: float) -> void:
	assert(delta >= 0.0, "Native animation cannot advance negative time")
	if _playback == null or not is_instance_valid(_root) or _root.is_queued_for_deletion():
		return
	native_transition_available = delta > 0.0
	if not _started:
		_started = true
		_playback.start(_set.default_node)
	_advance_tree(0.0)
	var remaining := delta
	# Schedule only pre-baked native method/property boundaries. The native tree
	# alone evaluates conditions, picks transitions, samples curves and blends.
	while remaining > BOUNDARY_EPSILON and is_instance_valid(_root) and not _root.is_queued_for_deletion():
		var step := _boundary_wait(_playback.get_current_node(), _playback.get_current_play_position(), remaining)
		if _playback.get_fading_from_node() != &"":
			step = minf(step, _boundary_wait(_playback.get_fading_from_node(), _playback.get_fading_from_play_position(), remaining))
			var fade_remaining := _playback.get_fading_length() - _playback.get_fading_position()
			if fade_remaining > BOUNDARY_EPSILON:
				step = minf(step, fade_remaining)
		_elapsed += step
		_advance_tree(step)
		remaining = maxf(0.0, remaining - step)
		if not is_instance_valid(_root) or _root.is_queued_for_deletion():
			return
		_advance_tree(0.0) # Native method gates become eligible at this exact time.
		for gate in _opened_gates:
			native_gates[gate] = false
		_opened_gates.clear()

func _boundary_wait(node: StringName, position: float, maximum: float) -> float:
	var definition: Dictionary = _set.states[node]
	for boundary in definition.boundaries:
		var wait: float = float(boundary) - position
		if wait > BOUNDARY_EPSILON:
			return minf(maximum, wait)
	return maximum

func _native_gate(name: StringName, once: bool) -> void:
	if once and _used_gates.has(name):
		return
	if once:
		_used_gates[name] = true
	native_gates[name] = true
	_opened_gates.append(name)

func _native_event(method: String, argument: Variant) -> void:
	_event_methods.append(method)
	_event_arguments.append(argument)

func _native_endpoint(animation: StringName) -> void:
	var dominant := _playback.get_current_node()
	if _playback.get_fading_from_node() != &"" and _playback.get_fading_position() < _playback.get_fading_length() * 0.5:
		dominant = _playback.get_fading_from_node()
	if _player.get_animation(animation).get_meta("source_state") == _set.states[dominant].source_state:
		_endpoint_animation = animation

func _advance_tree(delta: float) -> void:
	if delta > 0.0:
		_endpoint_animation = &""
	_tree.advance(delta)
	if _endpoint_animation != &"":
		# A baked single-pose native animation preserves loop-end event poses.
		_player.play(_endpoint_animation)
		_player.seek(0.0, true, true)
		_player.stop(true)
	# Immediate native method tracks run during mixing, before property apply.
	# Dispatch gameplay only after the native mixer has written the keyed pose.
	var index := 0
	while index < _event_methods.size():
		animation_event.emit(_event_methods[index], _event_arguments[index])
		index += 1
		if not is_instance_valid(_root) or _root.is_queued_for_deletion():
			break
	_event_methods.clear()
	_event_arguments.clear()

func _state_started(node: StringName) -> void:
	_elapsed = 0.0
	_endpoint_animation = &""
	_used_gates.clear()
	for gate in native_gates:
		native_gates[gate] = false
	var definition: Dictionary = _set.states.get(str(node), {})
	if not str(definition.incoming).is_empty():
		# Native recursive traversal must not take another source transition in
		# this Update, even when opposite source thresholds overlap.
		native_transition_available = false
	for trigger in definition.get("triggers", []):
		native_parameters[trigger] = false
	state_entered.emit(str(definition.get("name", "")), definition.get("behaviors", []))

func _state_finished(node: StringName) -> void:
	var definition: Dictionary = _set.states.get(str(node), {})
	state_exited.emit(str(definition.get("name", "")), definition.get("behaviors", []))

func _resolve_path(path: String, actor: Node, bridge: SceneBridge, ids: Dictionary) -> Node:
	var current := actor
	for part in path.split("/", false):
		var found: Node = null
		var owner_id := str(ids.get(current.get_instance_id(), ""))
		for child_id in bridge.scene.get("game_objects", {}).get(owner_id, {}).get("children", []):
			if str(bridge.scene.game_objects[str(child_id)].get("name", "")) == part:
				found = bridge.nodes.get(str(child_id))
				break
		if found == null:
			for child in current.get_children():
				if str(child.get_meta("unity_name", child.name)) == part:
					found = child
					break
		if found == null:
			return null
		current = found
	return current

func _graphic(node: Node, text: bool, bridge: SceneBridge, ids: Dictionary) -> Node:
	var mapping: Dictionary = bridge.texts if text else bridge.graphics
	var id := str(ids.get(node.get_instance_id(), ""))
	if mapping.has(id):
		return mapping[id]
	if (text and node is Label) or (not text and (node is Sprite2D or node is TextureRect)):
		return node
	for child in node.get_children():
		if (text and child is Label) or (not text and (child is Sprite2D or child is TextureRect)):
			return child
	return null
