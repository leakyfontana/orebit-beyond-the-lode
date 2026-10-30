class_name TouchControls
extends Control

var host: Node
var _touch_enabled := false
var _focused := true
var _active := false
var _gameplay_enabled := true
var _joystick_held := false
var _restore_mouse_touch := false
var _previous_mouse_touch := false
var _buttons: Array[TouchScreenButton] = []
@onready var _joystick: VirtualJoystick = $Joystick
@onready var _items: Node2D = $Items

func configure(game_host: Node) -> void:
	host = game_host
	if is_node_ready():
		sync_state()

func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var desktop_override: bool = OS.get_cmdline_user_args().has("--touch-controls")
	_touch_enabled = DisplayServer.is_touchscreen_available() or desktop_override
	if desktop_override and not OS.has_feature("mobile"):
		_previous_mouse_touch = Input.is_emulating_touch_from_mouse()
		_restore_mouse_touch = true
		Input.set_emulate_touch_from_mouse(true)
	for child in _items.get_children():
		var button := child as TouchScreenButton
		_buttons.append(button)
		button.pressed.connect(_item_pressed.bind(button))
		button.released.connect(_item_released.bind(button))
	_joystick.pressed.connect(_stick_pressed)
	_joystick.released.connect(_stick_released)
	resized.connect(_layout_controls)
	visibility_changed.connect(_visibility_changed)
	_layout_controls()
	sync_state()

func _process(_delta: float) -> void:
	sync_state()

# Call immediately from host lifecycle setters as well as the per-frame safety check.
func sync_state() -> void:
	var available: bool = _touch_enabled and _focused and _gameplay_enabled and is_instance_valid(host)
	if available:
		available = host.scene_name == "Game" and host.player_alive and not host.paused and host.pending_scene.is_empty() and not get_tree().paused
	if available == _active:
		return
	_active = available
	if not _active:
		release_all()
	visible = _active
	_joystick.mouse_filter = Control.MOUSE_FILTER_STOP if _active else Control.MOUSE_FILTER_IGNORE

func set_gameplay_enabled(enabled: bool) -> void:
	_gameplay_enabled = enabled
	if is_node_ready():
		sync_state()

func release_all() -> void:
	if not is_node_ready():
		return
	if _joystick_held:
		# VirtualJoystick has no public cancel method. Resizing uses its native
		# reset path, clearing the captured finger and all simulated actions.
		var old_size: Vector2 = _joystick.size
		_joystick.size = old_size + Vector2.ONE
		_joystick.size = old_size
		_joystick_held = false
	for button in _buttons:
		if button.is_pressed():
			# Native visibility handling releases the finger and its InputMap action.
			button.hide()
			button.show()
		button.modulate = Color.WHITE

func _visibility_changed() -> void:
	if not is_visible_in_tree():
		release_all()

func _notification(what: int) -> void:
	match what:
		NOTIFICATION_APPLICATION_FOCUS_OUT, NOTIFICATION_WM_WINDOW_FOCUS_OUT, NOTIFICATION_APPLICATION_PAUSED:
			_focused = false
			if is_node_ready():
				sync_state()
		NOTIFICATION_APPLICATION_FOCUS_IN, NOTIFICATION_WM_WINDOW_FOCUS_IN, NOTIFICATION_APPLICATION_RESUMED:
			_focused = true
			if is_node_ready():
				_layout_controls()
				sync_state()

func _exit_tree() -> void:
	release_all()
	if _restore_mouse_touch:
		Input.set_emulate_touch_from_mouse(_previous_mouse_touch)

func _stick_pressed() -> void:
	_joystick_held = true

func _stick_released(_vector: Vector2) -> void:
	_joystick_held = false

func _item_pressed(button: TouchScreenButton) -> void:
	button.modulate = Color(1.25, 1.25, 1.25, 1.0)

func _item_released(button: TouchScreenButton) -> void:
	button.modulate = Color.WHITE

func _layout_controls() -> void:
	if not is_node_ready() or size.x <= 0.0 or size.y <= 0.0:
		return
	release_all()
	var safe := Rect2(Vector2.ZERO, size)
	if OS.has_feature("mobile"):
		var physical_safe: Rect2i = DisplayServer.get_display_safe_area()
		if physical_safe.has_area():
			# The display safe area is in physical screen coordinates, not the
			# stretched 1920x1080 canvas (nor camera/world coordinates).
			var local_from_screen: Transform2D = (get_viewport().get_screen_transform() * get_global_transform_with_canvas()).affine_inverse()
			safe = safe.intersection(local_from_screen * Rect2(physical_safe))
	if not safe.has_area():
		return
	var unit: float = minf(safe.size.y / 720.0, safe.size.x / 900.0)
	var margin: float = 28.0 * unit
	var diameter: float = 180.0 * unit
	_joystick.position = Vector2(safe.position.x + margin, safe.end.y - margin - diameter)
	_joystick.size = Vector2.ONE * diameter
	_joystick.joystick_size = diameter
	_joystick.tip_size = 72.0 * unit
	var cell: float = 104.0 * unit
	_items.position = Vector2(safe.end.x - margin - cell * 3.0, safe.end.y - margin - cell * 2.0)
	for index in _buttons.size():
		var button: TouchScreenButton = _buttons[index]
		button.scale = Vector2.ONE * unit
		# Each original 50px icon is centered within a 104px touch cell.
		button.position = Vector2(float(index % 3) * cell, float(index / 3) * cell) + Vector2.ONE * (cell - 50.0 * unit) * 0.5
