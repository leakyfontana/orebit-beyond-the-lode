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

enum DeviceMode { POINTER, CONTROLLER }
enum MovementOwner { KEYBOARD, TOUCH, CONTROLLER, UNAVAILABLE }
enum FocusState { FOCUSED, UNFOCUSED }
enum GameplayState { UNAVAILABLE, AVAILABLE }
enum MovementState { READY, WAITING_FOR_NEUTRAL }
enum ButtonState { HELD, BLOCKED_UNTIL_RELEASE, RELEASED }
enum ConsumableCursor { FIRST, SECOND, THIRD, FOURTH, FIFTH, SIXTH }

static var _allow_mouse_steering: bool = not (OS.has_feature("mobile") or OS.has_feature("web_ios") or OS.has_feature("web_android")) and not OS.get_cmdline_user_args().has("--touch-controls")
static var device_mode := DeviceMode.POINTER
static var consumable_cursor := ConsumableCursor.FIRST
static var focus_state := FocusState.FOCUSED
static var gameplay_state := GameplayState.UNAVAILABLE
static var movement_state := MovementState.READY
static var _button_states: Dictionary = {}
static var _movement_vector := Vector2.ZERO

static var controller_active: bool:
	get:
		return device_mode == DeviceMode.CONTROLLER
	set(value):
		device_mode = DeviceMode.CONTROLLER if value else DeviceMode.POINTER

static var _focused: bool:
	get:
		return focus_state == FocusState.FOCUSED
	set(value):
		focus_state = FocusState.FOCUSED if value else FocusState.UNFOCUSED

static var _gameplay_available: bool:
	get:
		return gameplay_state == GameplayState.AVAILABLE
	set(value):
		gameplay_state = GameplayState.AVAILABLE if value else GameplayState.UNAVAILABLE

static var _movement_ready: bool:
	get:
		return movement_state == MovementState.READY
	set(value):
		movement_state = MovementState.READY if value else MovementState.WAITING_FOR_NEUTRAL

static var selected_consumable: int:
	get:
		return consumable_cursor
	set(value):
		consumable_cursor = value as ConsumableCursor

# Diagnostic views only; the event path owns the single button-state map.
static var _held_buttons: Dictionary:
	get:
		var buttons: Dictionary = {}
		for key in _button_states:
			buttons[key] = true
		return buttons

static var _blocked_buttons: Dictionary:
	get:
		var buttons: Dictionary = {}
		for key in _button_states:
			if _button_states[key] == ButtonState.BLOCKED_UNTIL_RELEASE:
				buttons[key] = true
		return buttons

static func axis_raw(axis_name: String) -> float:
	var axes := _movement_axes()
	match axis_name:
		"Horizontal":
			return axes.x
		"Vertical":
			return axes.y
	return 0.0

static func _movement_axes() -> Vector2:
	match _resolve_movement_owner():
		MovementOwner.KEYBOARD, MovementOwner.TOUCH:
			return _movement_vector
		MovementOwner.CONTROLLER:
			return controller_direction()
	return Vector2.ZERO

static func _resolve_movement_owner() -> MovementOwner:
	var left := _direction_pressed(&"move_left", KEY_LEFT, KEY_A)
	var right := _direction_pressed(&"move_right", KEY_RIGHT, KEY_D)
	var up := _direction_pressed(&"move_up", KEY_UP, KEY_W)
	var down := _direction_pressed(&"move_down", KEY_DOWN, KEY_S)
	# Held keyboard controls take precedence as a complete digital vector,
	# retaining opposite-key cancellation and source down-before-side diagonals.
	if left or right or up or down:
		_movement_vector = Vector2(int(right) - int(left), int(up) - int(down))
		return MovementOwner.KEYBOARD
	var touch := Vector2(
		Input.get_action_strength(&"touch_move_right") - Input.get_action_strength(&"touch_move_left"),
		Input.get_action_strength(&"touch_move_up") - Input.get_action_strength(&"touch_move_down")
	)
	if touch != Vector2.ZERO:
		_movement_vector = _sectors(touch)
		return MovementOwner.TOUCH
	if not _focused or not _gameplay_available or not _movement_ready:
		return MovementOwner.UNAVAILABLE
	return MovementOwner.CONTROLLER

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
	movement_state = MovementState.WAITING_FOR_NEUTRAL
	for key in _button_states:
		_button_states[key] = ButtonState.BLOCKED_UNTIL_RELEASE

static func set_gameplay_available(available: bool) -> void:
	var next := GameplayState.AVAILABLE if available else GameplayState.UNAVAILABLE
	if next != gameplay_state:
		cancel_controller_controls()
		gameplay_state = next

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	add_to_group("game_input")
	get_tree().quit_on_go_back = false
	if OS.get_name() == "Android":
		# Android also emits a window Back request; route that once in Main.
		for event in InputMap.action_get_events(&"pause"):
			if event is InputEventKey and event.physical_keycode == KEY_BACK:
				InputMap.action_erase_event(&"pause", event)
	Input.joy_connection_changed.connect(_joy_connection_changed)

func _process(_delta: float) -> void:
	if _focused and _controller_raw().length() <= CONTROLLER_DEADZONE:
		movement_state = MovementState.READY

func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton and not event.canceled and event.device != InputEvent.DEVICE_ID_EMULATION:
		device_mode = DeviceMode.POINTER
	elif event is InputEventMouseMotion and event.device != InputEvent.DEVICE_ID_EMULATION and event.relative.length_squared() > 0.0:
		device_mode = DeviceMode.POINTER
	if not (event is InputEventJoypadButton or event is InputEventJoypadMotion):
		return
	# Own joypad events before GUI defaults (notably built-in ui_accept's B mapping).
	# Native InputMap state is still maintained by Godot, never by OS polling.
	get_viewport().set_input_as_handled()
	if event is InputEventJoypadButton:
		var key := Vector2i(event.device, event.button_index)
		if not event.pressed:
			_button_states.erase(key)
			controller_event.emit(event)
			return
		match _button_states.get(key, ButtonState.RELEASED):
			ButtonState.HELD, ButtonState.BLOCKED_UNTIL_RELEASE:
				return
		_button_states[key] = ButtonState.HELD
		if not _focused:
			return
		device_mode = DeviceMode.CONTROLLER
	elif not _focused:
		return
	elif absf(event.axis_value) > CONTROLLER_DEADZONE:
		device_mode = DeviceMode.CONTROLLER
	controller_event.emit(event)

func _joy_connection_changed(device: int, connected: bool) -> void:
	cancel_controller_controls()
	if not connected:
		for key in _button_states.keys():
			if key.x == device:
				_button_states.erase(key)
		for action in CONTROLLER_ACTIONS:
			Input.action_release(action)
		if Input.get_connected_joypads().is_empty():
			device_mode = DeviceMode.POINTER
	controller_connection_changed.emit()

func _notification(what: int) -> void:
	match what:
		NOTIFICATION_APPLICATION_FOCUS_OUT, NOTIFICATION_WM_WINDOW_FOCUS_OUT, NOTIFICATION_APPLICATION_PAUSED:
			focus_state = FocusState.UNFOCUSED
			cancel_controller_controls()
		NOTIFICATION_APPLICATION_FOCUS_IN, NOTIFICATION_WM_WINDOW_FOCUS_IN, NOTIFICATION_APPLICATION_RESUMED:
			focus_state = FocusState.FOCUSED

func _exit_tree() -> void:
	cancel_controller_controls()
	_button_states.clear()
	gameplay_state = GameplayState.UNAVAILABLE
