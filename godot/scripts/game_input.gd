class_name GameInput
extends Node

# Unity-compatible names remain at the boundary; all devices share InputMap actions.
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

static var _allow_mouse_steering: bool = not (OS.has_feature("mobile") or OS.has_feature("web_ios") or OS.has_feature("web_android")) and not OS.get_cmdline_user_args().has("--touch-controls")
static var _web_mobile: bool = OS.has_feature("web_ios") or OS.has_feature("web_android")

static func axis_raw(axis_name: String) -> float:
	# Do not use get_axis/get_vector: the original axes are digital, including diagonals.
	match axis_name:
		"Horizontal":
			return float(int(_direction_pressed(&"move_right", KEY_RIGHT, KEY_D)) - int(_direction_pressed(&"move_left", KEY_LEFT, KEY_A)))
		"Vertical":
			return float(int(_direction_pressed(&"move_up", KEY_UP, KEY_W)) - int(_direction_pressed(&"move_down", KEY_DOWN, KEY_S)))
	return 0.0

static func _direction_pressed(action: StringName, arrow: Key, letter: Key) -> bool:
	# A native joystick releases its actions on centering. A physically held key
	# must still win when keyboard and touch are used together.
	# Fractional browser touch coordinates leave a small orthogonal joystick
	# strength. Apply the joystick's 0.18 deadzone per axis before digitizing.
	var pressed: bool = Input.get_action_strength(action) > 0.18 if _web_mobile else Input.is_action_pressed(action)
	return pressed or Input.is_physical_key_pressed(arrow) or Input.is_physical_key_pressed(letter)

static func key_pressed(key_name: String) -> bool:
	var action: StringName = KEY_ACTIONS.get(key_name, &"")
	var physical_key: Key = PHYSICAL_KEYS.get(key_name, KEY_NONE)
	return not action.is_empty() and (Input.is_action_pressed(action) or Input.is_physical_key_pressed(physical_key))

static func key_down(key_name: String) -> bool:
	var action: StringName = KEY_ACTIONS.get(key_name, &"")
	return not action.is_empty() and Input.is_action_just_pressed(action)

static func mouse_steering_allowed() -> bool:
	# Keep touch -> mouse emulation enabled for the original Control-based menus.
	# It must never turn a joystick/item/menu finger into mouse flight on mobile.
	return _allow_mouse_steering

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	get_tree().quit_on_go_back = false

