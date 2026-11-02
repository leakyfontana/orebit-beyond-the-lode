extends SceneTree

# Run headlessly with --touch-controls --mode=private and the isolated endpoint
# arguments checked below. Native touch events traverse the real co-op overlay
# and joystick; assertions observe the input adapter and sampled player movement.
# External services/accounts are excluded; saves/settings use fixture paths.
const Game = preload("res://scripts/main.gd")
var _game: Node
var _stick: VirtualJoystick
var _cases: Array = []
var _passed := true
var _previous_mouse_emulation := false

func _initialize() -> void:
	_run.call_deferred()

func _run() -> void:
	var arguments := OS.get_cmdline_user_args()
	if not arguments.has("--touch-controls") or not arguments.has("--mode=private") or not arguments.has("--coop-url=http://127.0.0.1:1") or not arguments.has("--coop-token="):
		push_error("Co-op touch probe requires --touch-controls --mode=private --coop-url=http://127.0.0.1:1 --coop-token=")
		quit(2)
		return
	_previous_mouse_emulation = Input.is_emulating_mouse_from_touch()
	Input.set_emulate_mouse_from_touch(true)
	root.size = Vector2i(1920, 1080)
	_game = Game.new()
	_game.data.settings_file = "user://coop-input-interop-settings.json"
	_game.data.savefile = "user://coop-input-interop-save.data"
	root.add_child(_game)
	_game.set_process(false)
	_game.set_physics_process(false)
	_game.seed_value = 12345
	_game._seed_is_explicit = true
	_game.coop.lobby.hide_lobby(true)
	await _load_game()
	_stick = _game.touch_controls.get_node("Joystick") as VirtualJoystick
	await _directions("private")

	# Use the real successful-join callback without a transport or account change.
	_game.coop.lobby.show_lobby()
	_game.coop._joined({"seed": 12345, "state": {}, "excavated": []})
	await _load_game()
	await _directions("co-op after joining")
	await _header_layouts()

	await _touch(true)
	await _drag(Vector2(0.8, 0.0))
	_game.paused = true
	_observe("pause cancels held co-op movement", Vector2.ZERO)
	_game.paused = false
	await _drag(Vector2(-0.8, 0.0))
	_observe("resume ignores the cancelled finger", Vector2.ZERO)
	await _touch(false)
	await _directions("co-op after pause")

	# Menus use Godot's touch-to-mouse emulation, unlike the native joystick.
	# Send screen-coordinate events through Input to exercise that real path.
	var account := _game.coop.lobby.find_child("GameModesAccount", true, false) as Button
	assert(account != null, "Missing account-menu fixture control")
	var point: Vector2 = account.get_global_transform_with_canvas() * (account.size * 0.5)
	await _menu_touch(point, true)
	await _menu_touch(point, false)
	_check("account control remains touch-clickable", _game.coop.lobby.modal)
	_observe("opening game modes clears movement", Vector2.ZERO)
	_game.coop.lobby.hide_lobby()
	await process_frame
	await process_frame
	await _directions("co-op after returning from modes")

	_game.free()
	Input.set_emulate_mouse_from_touch(_previous_mouse_emulation)
	print("COOP_INPUT_INTEROP ", JSON.stringify({"passed": _passed, "cases": _cases}))
	quit(0 if _passed else 1)

func _load_game() -> void:
	_game.pending_scene = ""
	_game._load_scene("Game")
	# The disabled host does not advance the source arrival animation. Match the
	# existing controller consumer fixture's completed-arrival player state.
	_game.player_alive = true
	_game.player.is_in_shop = false
	_game.player._is_teleporting = false
	_game.body.freeze = true
	_game.touch_controls.notification(Node.NOTIFICATION_APPLICATION_FOCUS_IN)
	await process_frame
	await process_frame

func _point(offset: Vector2) -> Vector2:
	return _stick.get_global_transform_with_canvas() * (_stick.size * _stick.initial_offset_ratio + offset * _stick.joystick_size * 0.5)

func _touch(pressed: bool) -> void:
	var event := InputEventScreenTouch.new()
	event.index = 0
	event.pressed = pressed
	event.position = _point(Vector2.ZERO)
	root.push_input(event, true)
	await process_frame

func _drag(offset: Vector2) -> void:
	var event := InputEventScreenDrag.new()
	event.index = 0
	event.position = _point(offset)
	root.push_input(event, true)
	await process_frame

func _menu_touch(point: Vector2, pressed: bool) -> void:
	var event := InputEventScreenTouch.new()
	event.index = 0
	event.pressed = pressed
	event.position = root.get_screen_transform() * point
	Input.parse_input_event(event)
	Input.flush_buffered_events()
	await process_frame

func _directions(label: String) -> void:
	await _touch(true)
	_observe(label + ": center", Vector2.ZERO)
	await _drag(Vector2(0.8, 0.025))
	_observe(label + ": right rejects down drift", Vector2.RIGHT)
	await _drag(Vector2(0.0, -0.8))
	_observe(label + ": up", Vector2(0, 1))
	await _drag(Vector2(-0.8, 0.025))
	_observe(label + ": left clears prior direction", Vector2.LEFT)
	await _drag(Vector2(0.0, 0.8))
	_observe(label + ": down", Vector2(0, -1))
	await _drag(Vector2(0.6, -0.6))
	_observe(label + ": deliberate diagonal", Vector2.ONE)
	await _touch(false)
	_observe(label + ": release", Vector2.ZERO)

func _header_layouts() -> void:
	var lobby: CoopLobby = _game.coop.lobby
	var account := lobby.find_child("GameModesAccount", true, false) as Button
	var help := _game.ui_root.find_child("HelpButton", true, false) as Control
	var hull := _game.ui_root.find_child("HullUI", true, false) as Control
	for viewport_size in [Vector2i(1280, 720), Vector2i(2400, 1080), Vector2i(900, 400), Vector2i(1280, 800)]:
		root.size = viewport_size
		await process_frame
		await process_frame
		lobby._resize()
		var action := lobby._header_rect(account)
		var label := lobby._header_rect(lobby._hud_label)
		var meter := lobby._header_rect(hull)
		var visible_help := lobby._header_art_rect(help)
		var caption_y := meter.position.y + meter.size.y * 37.0 / 147.0
		var font := lobby._hud_label.get_theme_font("font")
		var line_height := font.get_height(lobby._hud_label.get_theme_font_size("font_size"))
		var prefix := "header at " + str(viewport_size)
		_check(prefix + ": action fits viewport without covering Help",
			action.position.x >= visible_help.end.x and action.end.x <= lobby._root.size.x and action.position.y >= 0)
		_check(prefix + ": count stays on one caption line clear of Hull",
			label.end.x <= meter.position.x and label.size.y <= line_height + 1 and absf(label.get_center().y - caption_y) < 1)
		_check(prefix + ": action keeps a touch-sized target", action.size.x >= 48 and action.size.y >= 48)
		var button_font := account.get_theme_font("font")
		var text_size := button_font.get_multiline_string_size(account.text, HORIZONTAL_ALIGNMENT_CENTER, -1, account.get_theme_font_size("font_size"))
		_check(prefix + ": both icon text lines fit", text_size.x <= action.size.x and text_size.y <= action.size.y)
		lobby._resize()
		lobby._resize()
		_check(prefix + ": repeated layout does not drift", lobby._header_rect(account).is_equal_approx(action) and lobby._header_rect(hull).is_equal_approx(meter))
	root.size = Vector2i(1280, 720)
	await process_frame
	await process_frame
	lobby._resize()
	var resized_action := lobby._header_rect(account)
	var resized_meter := lobby._header_rect(hull)
	# A live resize must agree with a newly loaded scene at the same dimensions.
	await _load_game()
	_stick = _game.touch_controls.get_node("Joystick") as VirtualJoystick
	lobby._resize()
	var fresh_hull := _game.ui_root.find_child("HullUI", true, false) as Control
	_check("resized header matches fresh scene", lobby._header_rect(account).is_equal_approx(resized_action) and lobby._header_rect(fresh_hull).is_equal_approx(resized_meter))
	root.size = Vector2i(1920, 1080)
	await process_frame
	await process_frame

func _observe(label: String, expected: Vector2) -> void:
	var actual := Vector2(GameInput.axis_raw("Horizontal"), GameInput.axis_raw("Vertical"))
	_game.player._read_axes()
	var movement := Vector2(_game.player.moveX, _game.player.moveY)
	var expected_movement := expected * Vector2(_game.data.player_horizontal_speed, _game.data.player_vertical_speed)
	var passed := actual == expected and movement == expected_movement
	_cases.append({"case": label, "passed": passed, "expected": [expected.x, expected.y], "actual": [actual.x, actual.y], "player_movement": [movement.x, movement.y]})
	_passed = _passed and passed

func _check(label: String, passed: bool) -> void:
	_cases.append({"case": label, "passed": passed})
	_passed = _passed and passed
