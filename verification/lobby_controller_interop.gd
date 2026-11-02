extends SceneTree

# Native joypad events exercise modal focus and page transitions without a
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
func _run() -> void:
	root.size = Vector2i(1280, 720)
	game = Game.new()
	game.data.settings_file = "user://sweep-ui-settings.json"
	game.data.savefile = "user://sweep-ui-save.data"
	root.add_child(game)
	await process_frame
	await process_frame
	(get_first_node_in_group("game_input") as GameInput).notification(Node.NOTIFICATION_APPLICATION_FOCUS_IN)
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
	print("LOBBY_CONTROLLER_INTEROP failures=", failures)
	game.queue_free()
	await process_frame
	quit(0 if failures == 0 else 1)
