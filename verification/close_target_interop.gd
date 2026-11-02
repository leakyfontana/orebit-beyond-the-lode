extends SceneTree
const Game = preload("res://scripts/main.gd")
var failures := 0
func _initialize() -> void:
	_run.call_deferred()
func _run() -> void:
	var game := Game.new()
	root.size = Vector2i(1920, 1080)
	root.content_scale_size = Vector2i(1920, 1080)
	root.content_scale_mode = Window.CONTENT_SCALE_MODE_CANVAS_ITEMS
	game.data.settings_file = "user://close-target-settings.json"
	game.data.savefile = "user://close-target-save.data"
	root.add_child(game)
	game.set_process(false)
	game.set_physics_process(false)
	game.coop.lobby.hide_lobby(true)
	game.pending_scene = ""
	game.seed_value = 12345
	game._seed_is_explicit = true
	game._load_scene("Game")
	game.pending_scene = ""
	game.player_alive = true
	game.body.freeze = true
	for viewport_size in [Vector2i(1920, 1080), Vector2i(1280, 720), Vector2i(900, 400)]:
		root.size = viewport_size
		await process_frame
		await process_frame
		for script in ["FuelShopManager", "MineralBuyerManager", "ItemShopManager", "UpgradeShopUI", "InventoryUIManager", "OptionsUIManager", "HelpUUIManager", "TransmissionManager"]:
			game.ui._set_panel(script, true)
			await process_frame
			if OS.get_cmdline_user_args().has("--capture-close") and viewport_size == Vector2i(900, 400) and script == "FuelShopManager":
				await RenderingServer.frame_post_draw
				root.get_texture().get_image().save_png("/tmp/orebit-sweep-close.png")
			var panel: Control = game.bridge.node(game.ui._panel(script))
			var close := panel.find_child("CloseButton", true, false) as Control
			var button: Button
			for id in game.bridge.buttons:
				var candidate: Button = game.bridge.buttons[id]
				if close.is_ancestor_of(candidate): button = candidate
			assert(button != null)
			var screen_rect: Rect2 = root.get_stretch_transform() * button.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, button.size)
			# Click near the edge of a 48-pixel target, outside the old tiny X.
			var point := screen_rect.get_center() + Vector2(22, 0)
			var local_point: Vector2 = root.get_stretch_transform().affine_inverse() * point
			var motion := InputEventMouseMotion.new()
			motion.position = local_point
			root.push_input(motion, true)
			await process_frame
			for pressed in [true, false]:
				var event := InputEventMouseButton.new()
				event.button_index = MOUSE_BUTTON_LEFT
				event.pressed = pressed
				event.position = local_point
				root.push_input(event, true)
				await process_frame
			var closed := not panel.is_visible_in_tree()
			print("CLOSE_TARGET ", viewport_size, " ", script, " screen_size=", screen_rect.size, " edge_click_closed=", closed)
			if not closed: failures += 1
			game.ui._set_panel(script, false)
	print("CLOSE_TARGET_INTEROP failures=", failures)
	game.free()
	quit(0 if failures == 0 else 1)
