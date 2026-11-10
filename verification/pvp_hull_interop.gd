extends SceneTree

# Real native pods, peer visuals and world-space bars; no socket or production writes.
var host: Node
var view: PvpView
var network: CoopClient
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

func state(hp: float, hull: String = "Stock Hull", x: float = 5.5) -> Dictionary:
	return {"x":x, "y":-3.5, "alive":true, "building":"", "player_hp":hp,
		"player_fuel":10, "current_upgrades":{"Hull":hull}}

func tick(own: Dictionary, human: Dictionary, bot: Dictionary) -> void:
	# The trusted peer marker must have no effect on public hull presentation.
	var players := [{"player_id":"self", "state":own},
		{"player_id":"human", "name":"Human", "state":human},
		{"player_id":"bot", "name":"Bot", "peer_type":"bot", "state":bot}]
	network._receive(JSON.parse_string(JSON.stringify({"type":"pvp_tick", "players":players})))
	view._process(0.0)

func capture(suffix: String) -> void:
	if capture_prefix.is_empty():
		return
	await process_frame
	await RenderingServer.frame_post_draw
	check(root.get_texture().get_image().save_png(capture_prefix+"-"+suffix+".png") == OK, "Hull screenshot could not be saved")

func _run() -> void:
	host = load("res://main.tscn").instantiate()
	root.add_child(host)
	await process_frame
	host.data = GameData.new()
	host.data.coop_mode = true
	host.data.pvp_mode = true
	host.world = WorldData.new(host.data)
	host.audio.state = host.data
	host.change_scene("Game")
	host._process(0.02)
	host.set_process(false)
	host.set_physics_process(false)
	host.coop.active = true
	network = host.coop.network
	network.set_process(false)
	network.mode = "pvp"
	network.player_id = "self"
	network.connected = true
	view = host.coop.pvp
	view.set_process(false)
	await process_frame
	host.camera.enabled = false
	root.canvas_transform = Transform2D(Vector2(90,0), Vector2(0,90), Vector2(root.size)*0.5-Vector2(8,3.5)*90)
	var own := state(8.5)
	var human := state(12.0, "Ironium Hull", 8.0)
	var bot := state(90.0, "Energy-Shielded Hull", 10.5)
	tick(own, human, bot)
	check(view._local_hull.visible and view._peer_hulls.size() == 2, "Visible PvP pods did not all receive hull bars")
	var local_bar: PvpHullIndicator = view._local_hull
	var human_bar: PvpHullIndicator = view._peer_hulls.human
	var bot_bar: PvpHullIndicator = view._peer_hulls.bot
	check(local_bar.current_hull == 8.5 and local_bar.maximum_hull == 10.0, "Local hull lost fractional authoritative damage")
	check(human_bar.maximum_hull == 17.0 and bot_bar.maximum_hull == 180.0, "Peer hull capacity ignored the public upgrade state")
	await capture("all-pods")
	# Follow rendered presentation, not the last network/physics coordinates.
	host.player.visual.global_position += Vector2(0.35, -0.15)
	var remote: Node2D = host.coop._remote_visuals.human
	remote.global_position += Vector2(-0.25, -0.4)
	remote.rotation = 0.2
	view._process(0.0)
	check(local_bar.global_position.is_equal_approx(host.player.visual.global_position + PvpHullIndicator.OFFSET), "Local bar follows physics rather than the rendered craft")
	check(human_bar.global_position.is_equal_approx(remote.global_position + PvpHullIndicator.OFFSET), "Remote bar follows snapshot rather than the visible peer")
	check(is_zero_approx(human_bar.global_rotation) and human_bar.global_scale.is_equal_approx(Vector2.ONE), "Pod tilt/facing distorted its hull bar")
	var old_scale := human_bar.get_global_transform_with_canvas().x.length()
	root.canvas_transform = Transform2D(Vector2(135,0), Vector2(0,135), Vector2(root.size)*0.5-Vector2(8,3.5)*135)
	check(is_equal_approx(human_bar.get_global_transform_with_canvas().x.length(), old_scale * 1.5), "Hull bar does not follow world camera zoom")
	# Damage/repair and upgrade changes reuse nodes rather than rebuilding UI.
	own.player_hp = 3.25
	human.player_hp = 7.5
	bot.player_hp = 180.0
	tick(own, human, bot)
	check(local_bar.current_hull == 3.25 and human_bar.current_hull == 7.5 and bot_bar.ratio == 1.0, "Authoritative damage/repair did not refresh bars")
	own.player_hp = 50.0
	own.current_upgrades.Hull = "Steel Hull"
	human.player_hp = 999.0
	bot.player_hp = -2.0
	network._receive({"type":"state_sync", "state_revision":network.state_revision + 1, "state":own})
	tick(own, human, bot)
	check(local_bar.maximum_hull == 50.0 and local_bar.ratio == 1.0, "Local upgraded hull capacity stayed at stock")
	check(human_bar.current_hull == 17.0 and human_bar.ratio == 1.0 and bot_bar.ratio == 0.0, "Out-of-range hull overfilled or reversed the native bar")
	# Protected interior, authoritative death, and a stock new life.
	own.building = "ItemShopManager"
	human.building = "ItemShopManager"
	bot.alive = false
	bot.player_hp = 0.0
	tick(own, human, bot)
	check(not local_bar.visible and not human_bar.visible and not bot_bar.visible, "Protected/dead craft left ghost hull bars")
	await capture("hidden")
	own = state(10.0)
	human = state(10.0, "Stock Hull", 8.0)
	bot = state(10.0, "Stock Hull", 10.5)
	network._receive({"type":"state_sync", "state_revision":network.state_revision + 1, "state":own})
	tick(own, human, bot)
	check(local_bar.visible and human_bar.visible and bot_bar.visible, "Building exit/new life did not restore hull indicators")
	check(local_bar.maximum_hull == 10.0 and human_bar.maximum_hull == 10.0 and bot_bar.maximum_hull == 10.0, "New life retained previous hull upgrades")
	own.alive = false
	own.player_hp = 0.0
	tick(own, human, bot)
	check(not local_bar.visible, "Local authoritative death retained a hull bar")
	network._receive({"type":"player_left", "player_id":"human"})
	view._process(0.0)
	check(not view._peer_hulls.has("human") and not human_bar.visible, "Disconnected peer retained a ghost hull bar")
	# Native scene replacement is also the round-load path.
	network.connected = false
	host.coop._snapshot = {"state":state(10.0)}
	host.change_scene("Game")
	host._process(0.02)
	await process_frame
	network.connected = true
	view._process(0.0)
	check(not is_instance_valid(local_bar) and not is_instance_valid(bot_bar), "Round load retained old-world indicators")
	check(view._local_hull.maximum_hull == 10.0 and view._local_hull.ratio == 1.0, "Round load did not initialize fresh stock hull")
	await capture("new-round")
	network.connected = false
	view._process(0.0)
	check(view._local_hull == null and view._peer_hulls.is_empty(), "Connection loss retained hull indicators")
	host.coop.active = false
	host.data.pvp_mode = false
	view._process(0.0)
	check(view._local_hull == null and view._peer_hulls.is_empty(), "Private mode created PvP hull UI")
	host.free()
	await process_frame
	print("PVP_HULL_INTEROP failures=", failures)
	quit(0 if failures == 0 else 1)
