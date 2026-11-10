extends SceneTree

# Exercise actual Sprite2D presentation between network snapshots, not just
# after the next render tick: delayed records must never restore intact art.
var host: Node
var failures := 0
var capture_prefix := ""

func _initialize() -> void:
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--capture-prefix="):
			capture_prefix = argument.trim_prefix("--capture-prefix=")
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func snapshot(started: float, clock: float) -> Dictionary:
	return {"type":"pvp_tick", "server_time":clock, "players":[], "terrain_changes":[], "bags":[], "falling":[], "impacts":[
		{"id":"rock-%d" % int(started), "x":8.5, "y":-3.5, "tile":25, "started_at":started, "expires_at":started+2.5},
		{"id":"lava-%d" % int(started), "x":10.5, "y":-3.5, "tile":28, "started_at":started, "expires_at":started+2.5},
	]}

func capture(name: String) -> void:
	if capture_prefix.is_empty():
		return
	for frame in 3:
		await process_frame
	root.get_texture().get_image().save_png(capture_prefix+"-"+name+".png")

func _run() -> void:
	host = load("res://main.tscn").instantiate()
	root.add_child(host)
	await process_frame
	host.data = GameData.new()
	host.data.pvp_mode = true
	host.world = WorldData.new(host.data)
	host.audio.state = host.data
	host.change_scene("Game")
	host._process(0.02)
	host.set_process(false)
	host.set_physics_process(false)
	host.coop.network.set_process(false)
	host.coop.active = true
	host.player.apply_pvp_life(true, Vector2(5.5,-3.5))
	var view: PvpView = host.coop.pvp
	if not capture_prefix.is_empty():
		host.camera.enabled = false
		var patch: Array[Vector2i] = []
		for x in range(5,15):
			for y in range(0,9):
				var raw: Array = host.world.getRawTile(x,y)
				raw[0] = 1 if y >= 5 else 0
				raw[1] = 0
				patch.append(Vector2i(x,y))
		host.refresh_tiles(patch)
		root.canvas_transform = Transform2D(Vector2(120,0),Vector2(0,120),Vector2(root.size)*0.5-Vector2(9.5,3.5)*120)
	# A late initial snapshot must immediately show the final broken pose, not
	# briefly default to the sprite sheet's intact first frame before tick().
	view.apply_event(snapshot(100.0,102.4))
	for key in ["impactsrock-100","impactslava-100"]:
		var sprite: Sprite2D = view._replicas[key].sprite
		check(sprite.frame == 7 and sprite.visible, key+" showed intact art on a late impact snapshot")
	await capture("late-snapshot")
	view.tick(0.11)
	check(view._replicas.is_empty(), "Impact did not expire at its deadline")
	# Server ticks may still carry this impact after local extrapolated expiry.
	# Recreating it used to show intact frame zero for one render frame.
	for packet in 3:
		view.apply_event(snapshot(100.0,102.45))
		check(view._replicas.is_empty(), "Expired impact was recreated from a delayed snapshot")
	await capture("expired-delayed-snapshot")
	# Fresh impacts still play their authored break/splash, then hold the final
	# pose on every visible blink until removal (without restarting on updates).
	view.apply_event(snapshot(110.0,110.0))
	var seen_on := false
	var seen_off := false
	for frame in range(126):
		view.tick(0.02)
		for key in view._replicas:
			var sprite: Sprite2D = view._replicas[key].sprite
			if view.server_time >= 110.4:
				check(sprite.frame == 7, key+" reverted from broken art while blinking")
				seen_on = seen_on or sprite.visible
				seen_off = seen_off or not sprite.visible
		if frame % 5 == 0:
			view.apply_event(snapshot(110.0,110.0+float(frame)*0.02))
			for key in view._replicas:
				if view.server_time >= 110.4:
					check(view._replicas[key].sprite.frame == 7, key+" restarted impact art on a repeated snapshot")
	check(seen_on and seen_off, "Broken residue did not blink before expiry")
	check(view._replicas.is_empty(), "Final stale snapshot resurrected an expired impact")
	host.coop.active = false
	host.free()
	await process_frame
	print("PVP_IMPACT_INTEROP failures=",failures)
	quit(0 if failures == 0 else 1)
