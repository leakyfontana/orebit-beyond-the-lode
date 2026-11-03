extends SceneTree

# Native GUI drags and joypad events exercise modal scrolling, focus and transitions without a
# physical controller or real account. Run with an isolated endpoint/token.
const Game = preload("res://scripts/main.gd")
var game: Node
var failures := 0
func _initialize() -> void:
	_run.call_deferred()
func check(ok: bool, text: String) -> void:
	print("PASS " if ok else "FAIL ", text)
	if not ok: failures += 1
func press(button: int) -> void:
	var event := InputEventJoypadButton.new()
	event.device = 0
	event.button_index = button
	event.pressed = true
	Input.parse_input_event(event)
	Input.flush_buffered_events()
	await process_frame
	await process_frame
	event = event.duplicate()
	event.pressed = false
	Input.parse_input_event(event)
	Input.flush_buffered_events()
	await process_frame
func focus_name() -> String:
	var control := root.gui_get_focus_owner()
	return str(control.name) if control != null else "none"
func escape() -> void:
	for pressed in [true, false]:
		var event := InputEventKey.new()
		event.keycode = KEY_ESCAPE
		event.pressed = pressed
		Input.parse_input_event(event)
		Input.flush_buffered_events()
		await process_frame
	await process_frame
func mouse_button_at(position: Vector2, pressed: bool) -> void:
	var event := InputEventMouseButton.new()
	event.position = position
	event.global_position = position
	event.button_index = MOUSE_BUTTON_LEFT
	event.button_mask = MOUSE_BUTTON_MASK_LEFT if pressed else 0
	event.pressed = pressed
	root.push_input(event, true)
	await process_frame
func mouse_drag_at(position: Vector2, relative: Vector2, pressed: bool = true) -> void:
	var event := InputEventMouseMotion.new()
	event.position = position
	event.global_position = position
	event.relative = relative
	event.button_mask = MOUSE_BUTTON_MASK_LEFT if pressed else 0
	root.push_input(event, true)
	await process_frame
func modal_button_gestures() -> void:
	var previous_emulation := Input.emulate_touch_from_mouse
	Input.emulate_touch_from_mouse = true
	root.size = Vector2i(712, 160)
	game.coop.lobby.show_lobby()
	await process_frame
	await process_frame
	var button := game.coop.lobby._body.get_node("UsePassword") as Button
	game.coop.lobby._scroll.ensure_control_visible(button)
	await process_frame
	await process_frame
	var initial_scroll: int = game.coop.lobby._scroll.scroll_vertical
	var start := button.get_global_rect().get_center()
	var drag_step := button.get_global_transform().basis_xform(Vector2(0, -12))
	await mouse_drag_at(start, Vector2.ZERO, false)
	await mouse_button_at(start, true)
	for step in range(1, 9):
		await mouse_drag_at(start + drag_step * step, drag_step)
	# Stop before lifting, avoiding inertia spilling into the controller checks.
	await mouse_drag_at(start + drag_step * 8, Vector2.ZERO)
	await mouse_button_at(start + drag_step * 8, false)
	check(game.coop.lobby._scroll.scroll_vertical > initial_scroll + 24, "a touch-emulated drag starting on a button scrolls the modal")
	check(game.coop.lobby._page == "lobby", "scrolling over a button does not activate its action")
	game.coop.lobby.show_lobby()
	await process_frame
	await process_frame
	button = game.coop.lobby._body.get_node("UsePassword") as Button
	game.coop.lobby._scroll.ensure_control_visible(button)
	await process_frame
	await process_frame
	start = button.get_global_rect().get_center()
	var small_move := button.get_global_transform().basis_xform(Vector2(6, 3))
	await mouse_drag_at(start, Vector2.ZERO, false)
	await mouse_button_at(start, true)
	await mouse_drag_at(start + small_move, small_move)
	await mouse_button_at(start + small_move, false)
	check(game.coop.lobby._page == "password", "a small moving tap still activates the modal button")
	Input.emulate_touch_from_mouse = previous_emulation
	root.size = Vector2i(1280, 720)
	await process_frame
	await process_frame
func check_menu_fit(context: String) -> void:
	for frame in range(4):
		await process_frame
	var scroll: ScrollContainer = game.coop.lobby._scroll
	var fits := scroll.get_v_scroll_bar().max_value <= scroll.get_v_scroll_bar().page + 1.0
	var bounds := scroll.get_global_rect().grow(1.0)
	for control in game.coop.lobby._focus_controls:
		if control.is_visible_in_tree():
			fits = fits and bounds.encloses(control.get_global_rect())
	check(fits, "%s fits without scrolling at %s" % [context, root.size])
func compact_menu_views() -> void:
	for viewport_size in [Vector2i(320, 568), Vector2i(712, 311)]:
		root.size = viewport_size
		game.coop.lobby._message = ""
		game.coop.lobby._auth_kind = "login"
		game.coop.lobby.show_mode()
		await check_menu_fit("mode chooser")
		game.coop.lobby.show_lobby()
		await check_menu_fit("Co-op account menu")
		game.coop.network.mode = "pvp"
		game.coop.lobby.show_lobby()
		await check_menu_fit("PvP account menu")
		game.coop.lobby._show_password()
		await check_menu_fit("password sign-in")
		game.coop.lobby._toggle_auth_kind()
		await check_menu_fit("account creation")
		game.coop.lobby._set_status("Could not sign in. Check your username and password.")
		await check_menu_fit("account validation error")
		game.coop.lobby._message = ""
		game.coop.network.token = "synthetic-layout-session"
		game.coop.network.session_checking = true
		game.coop.lobby._auth_state_changed()
		await check_menu_fit("pending session cancellation")
		game.coop.network.session_checking = false
		game.coop.network.token = ""
		game.coop.network.mode = "coop"
		game.coop.lobby.show_lobby()
		game.coop.lobby._show_server()
		await check_menu_fit("server connection")
		game.coop.lobby._set_status("Use an HTTPS address. Localhost HTTP is supported for development.")
		await check_menu_fit("server validation error")
	game.coop.lobby._message = ""
	game.coop.lobby._auth_kind = "login"
	root.size = Vector2i(1280, 720)
	await process_frame
	await process_frame
func _run() -> void:
	root.size = Vector2i(1280, 720)
	game = Game.new()
	game.data.settings_file = "user://sweep-ui-settings.json"
	game.data.savefile = "user://sweep-ui-save.data"
	root.add_child(game)
	await process_frame
	await process_frame
	(get_first_node_in_group("game_input") as GameInput).notification(Node.NOTIFICATION_APPLICATION_FOCUS_IN)
	await modal_button_gestures()
	await compact_menu_views()
	game.coop.lobby.show_mode()
	await press(JOY_BUTTON_DPAD_DOWN)
	check(focus_name() == "ChoosePrivate", "Dpad establishes modal controller focus")
	await press(JOY_BUTTON_DPAD_DOWN)
	check(focus_name() == "ChooseCoop", "Dpad selects co-op")
	await press(JOY_BUTTON_A)
	check(game.coop.lobby._page == "lobby", "A opens co-op menu")
	await press(JOY_BUTTON_DPAD_DOWN)
	check(focus_name() == "UsePassword", "Dpad selects password sign-in")
	await press(JOY_BUTTON_A)
	check(game.coop.lobby._page == "password", "A opens password sign-in")
	await press(JOY_BUTTON_DPAD_UP)
	check(focus_name() == "AuthPassword", "Dpad reaches password field")
	await press(JOY_BUTTON_B)
	check(game.coop.lobby._page == "lobby", "B leaves sign-in")
	await press(JOY_BUTTON_DPAD_DOWN)
	await press(JOY_BUTTON_DPAD_DOWN)
	await press(JOY_BUTTON_DPAD_DOWN)
	await press(JOY_BUTTON_A)
	check(game.coop.lobby._page == "server", "controller opens server options")
	await press(JOY_BUTTON_B)
	check(game.coop.lobby._page == "lobby", "B leaves server options")
	game.coop.lobby._show_server()
	await process_frame
	game.notification(Node.NOTIFICATION_WM_GO_BACK_REQUEST)
	await process_frame
	check(game.coop.lobby._page == "lobby", "native Back returns exactly one level from server options")
	game.notification(Node.NOTIFICATION_WM_GO_BACK_REQUEST)
	await process_frame
	check(game.coop.lobby.modal and game.coop.lobby._page == "mode", "next native Back returns exactly one level to modes")
	game.notification(Node.NOTIFICATION_WM_GO_BACK_REQUEST)
	await process_frame
	check(not game.coop.lobby.modal and not game.paused, "native Back dismisses modes without opening another UI")
	game.coop.lobby.show_lobby()
	await escape()
	check(game.coop.lobby._page == "mode", "Escape returns from server lobby to modes")
	await escape()
	check(not game.coop.lobby.modal and not game.paused, "Escape dismisses modes to prior private menu")
	game.coop.lobby.show_mode()
	game.coop.network.token = "synthetic-pending-session"
	game.coop.network.session_checking = true
	game.coop.lobby._auth_state_changed()
	game.coop.lobby._body.find_child("ChoosePrivate", true, false).grab_focus()
	await press(JOY_BUTTON_A)
	check(not game.coop.lobby.modal and not game.paused, "one Private selection works during saved-session validation")
	check(not game.coop.network.session_checking and game.coop.network.token == "synthetic-pending-session", "Private cancels validation without discarding saved sign-in")
	print("LOBBY_CONTROLLER_INTEROP failures=", failures)
	game.queue_free()
	await process_frame
	quit.call_deferred(0 if failures == 0 else 1)
