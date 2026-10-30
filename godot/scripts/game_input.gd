class_name GameInput
extends Node

signal controller_event(event: InputEvent)
signal controller_connection_changed

# Unity-compatible names remain at the boundary; keyboard actions stay digital.
const KEY_ACTIONS: Dictionary = {
	"LeftArrow": &"move_left", "A": &"move_left",
	"RightArrow": &"move_right", "D": &"move_right",
	"UpArrow": &"move_up", "W": &"move_up",
	"DownArrow": &"move_down", "S": &"move_down",
	"I": &"inventory", "Escape": &"pause",
	"Alpha1": &"item_1", "Alpha2": &"item_2", "Alpha3": &"item_3",
	"Alpha4": &"item_4", "Alpha5": &"item_5", "Alpha6": &"item_6",
}

const PHYSICAL_KEYS: Dictionary = {
	"LeftArrow": KEY_LEFT, "A": KEY_A, "RightArrow": KEY_RIGHT, "D": KEY_D,
	"UpArrow": KEY_UP, "W": KEY_W, "DownArrow": KEY_DOWN, "S": KEY_S,
	"I": KEY_I, "Escape": KEY_ESCAPE,
	"Alpha1": KEY_1, "Alpha2": KEY_2, "Alpha3": KEY_3,
	"Alpha4": KEY_4, "Alpha5": KEY_5, "Alpha6": KEY_6,
}

# Eight equal sectors reject slight perpendicular drift without losing diagonals.
const TOUCH_DIAGONAL_RATIO := 0.41421356237
const CONTROLLER_DEADZONE := 0.24
const CONTROLLER_ACTIONS: Array[StringName] = [
	&"controller_left", &"controller_right", &"controller_up", &"controller_down",
	&"controller_use", &"controller_previous", &"controller_next",
	&"controller_inventory", &"controller_pause", &"controller_accept", &"controller_back",
]

static var _allow_mouse_steering: bool = not (OS.has_feature("mobile") or OS.has_feature("web_ios") or OS.has_feature("web_android")) and not OS.get_cmdline_user_args().has("--touch-controls")
static var controller_active := false
static var selected_consumable := 0
static var _focused := true
static var _gameplay_available := false
static var _movement_ready := true
static var _held_buttons: Dictionary = {}
static var _blocked_buttons: Dictionary = {}

static func axis_raw(axis_name: String) -> float:
	var axes := _movement_axes()
	match axis_name:
		"Horizontal":
			return axes.x
		"Vertical":
			return axes.y
	return 0.0

static func _movement_axes() -> Vector2:
	var left := _direction_pressed(&"move_left", KEY_LEFT, KEY_A)
	var right := _direction_pressed(&"move_right", KEY_RIGHT, KEY_D)
	var up := _direction_pressed(&"move_up", KEY_UP, KEY_W)
	var down := _direction_pressed(&"move_down", KEY_DOWN, KEY_S)
	# Held keyboard controls take precedence as a complete digital vector,
	# retaining opposite-key cancellation and source down-before-side diagonals.
	if left or right or up or down:
		return Vector2(int(right) - int(left), int(up) - int(down))
	var touch := Vector2(
		Input.get_action_strength(&"touch_move_right") - Input.get_action_strength(&"touch_move_left"),
		Input.get_action_strength(&"touch_move_up") - Input.get_action_strength(&"touch_move_down")
	)
	if touch != Vector2.ZERO:
		return _sectors(touch)
	if not _focused or not _gameplay_available or not _movement_ready:
		return Vector2.ZERO
	return controller_direction()

static func _sectors(value: Vector2) -> Vector2:
	var threshold := maxf(absf(value.x), absf(value.y)) * TOUCH_DIAGONAL_RATIO
	if threshold == 0.0:
		return Vector2.ZERO
	return Vector2(signf(value.x) if absf(value.x) >= threshold else 0.0, signf(value.y) if absf(value.y) >= threshold else 0.0)

static func _controller_raw() -> Vector2:
	return Vector2(
		Input.get_action_raw_strength(&"controller_right") - Input.get_action_raw_strength(&"controller_left"),
		Input.get_action_raw_strength(&"controller_up") - Input.get_action_raw_strength(&"controller_down"))

static func controller_direction() -> Vector2:
	var value := _controller_raw()
	return _sectors(value) if _focused and value.length() > CONTROLLER_DEADZONE else Vector2.ZERO

static func _direction_pressed(action: StringName, arrow: Key, letter: Key) -> bool:
	return Input.is_action_pressed(action) or Input.is_physical_key_pressed(arrow) or Input.is_physical_key_pressed(letter)

static func key_pressed(key_name: String) -> bool:
	var action: StringName = KEY_ACTIONS.get(key_name, &"")
	var physical_key: Key = PHYSICAL_KEYS.get(key_name, KEY_NONE)
	return not action.is_empty() and (Input.is_action_pressed(action) or Input.is_physical_key_pressed(physical_key))

static func key_down(key_name: String) -> bool:
	var action: StringName = KEY_ACTIONS.get(key_name, &"")
	return not action.is_empty() and Input.is_action_just_pressed(action)

static func mouse_steering_allowed() -> bool:
	# A controller stays the active pointing mode until real desktop mouse input.
	# Touch -> mouse emulation remains enabled for the original Control menus.
	return _allow_mouse_steering and not controller_active

static func cancel_controller_controls() -> void:
	_movement_ready = false
	for key in _held_buttons:
		_blocked_buttons[key] = true

static func set_gameplay_available(available: bool) -> void:
	if available != _gameplay_available:
		cancel_controller_controls()
		_gameplay_available = available

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("game_input")
	get_tree().quit_on_go_back = false
	Input.joy_connection_changed.connect(_joy_connection_changed)

func _process(_delta: float) -> void:
	if _focused and _controller_raw().length() <= CONTROLLER_DEADZONE:
		_movement_ready = true

func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton and not event.canceled and event.device != InputEvent.DEVICE_ID_EMULATION:
		controller_active = false
	elif event is InputEventMouseMotion and event.device != InputEvent.DEVICE_ID_EMULATION and event.relative.length_squared() > 0.0:
		controller_active = false
	if not (event is InputEventJoypadButton or event is InputEventJoypadMotion):
		return
	# Own joypad events before GUI defaults (notably built-in ui_accept's B mapping).
	# Native InputMap state is still maintained by Godot, never by OS polling.
	get_viewport().set_input_as_handled()
	if event is InputEventJoypadButton:
		var key := Vector2i(event.device, event.button_index)
		if not event.pressed:
			_held_buttons.erase(key)
			_blocked_buttons.erase(key)
			controller_event.emit(event)
			return
		if _held_buttons.has(key):
			return
		_held_buttons[key] = true
		if not _focused or _blocked_buttons.has(key):
			return
		controller_active = true
	elif not _focused:
		return
	elif absf(event.axis_value) > CONTROLLER_DEADZONE:
		controller_active = true
	controller_event.emit(event)

func _joy_connection_changed(device: int, connected: bool) -> void:
	cancel_controller_controls()
	if not connected:
		for key in _held_buttons.keys():
			if key.x == device:
				_held_buttons.erase(key)
				_blocked_buttons.erase(key)
		for action in CONTROLLER_ACTIONS:
			Input.action_release(action)
		if Input.get_connected_joypads().is_empty():
			controller_active = false
	controller_connection_changed.emit()

func _notification(what: int) -> void:
	match what:
		NOTIFICATION_APPLICATION_FOCUS_OUT, NOTIFICATION_WM_WINDOW_FOCUS_OUT, NOTIFICATION_APPLICATION_PAUSED:
			_focused = false
			cancel_controller_controls()
		NOTIFICATION_APPLICATION_FOCUS_IN, NOTIFICATION_WM_WINDOW_FOCUS_IN, NOTIFICATION_APPLICATION_RESUMED:
			_focused = true

func _exit_tree() -> void:
	cancel_controller_controls()
	_held_buttons.clear()
	_blocked_buttons.clear()
	_gameplay_available = false
