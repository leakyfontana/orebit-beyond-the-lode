extends SceneTree

# Real native TileMap redraw through the received mining/detachment event path.
var failures := 0
var host: Node
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

func capture(name: String) -> void:
	if capture_prefix.is_empty():
		return
	await process_frame
	await RenderingServer.frame_post_draw
	root.get_texture().get_image().save_png(capture_prefix + "-" + name + ".png")

func detached_hazard(tile: int, label: String) -> void:
	var source := Vector2i(20, 30)
	var support := source + Vector2i.DOWN
	var patch: Array[Vector2i] = []
	for x in range(17, 24):
		for y in range(27, 34):
			var raw: Array = host.world.getRawTile(x, y)
			raw[0] = 0
			raw[1] = 0
			patch.append(Vector2i(x, y))
	host.world.getRawTile(source.x, source.y)[0] = tile
	host.world.getRawTile(support.x, support.y)[0] = 1
	host.refresh_tiles(patch)
	var empty_atlas: Vector2i = host.terrain.tile_coordinates["DirtConnectors/0"]
	var above := source + Vector2i.UP
	check(host.terrain.tile_layer.get_cell_atlas_coords(above) != empty_atlas, label + " fixture did not render the original earth rim")
	await capture(label + "-supported")
	var network: CoopClient = host.coop.network
	network._receive({"type":"mined", "x":support.x, "y":support.y, "accepted":true, "player_id":"other", "method":"drill", "ore":"Dirt"})
	network._receive({"type":"pvp_tick", "players":[], "terrain_changes":[[support.x,support.y,0],[source.x,source.y,0]], "falling":[{"id":label,"x":20.5,"y":-33.5,"tile":tile}], "bags":[], "impacts":[]})
	check(host.world.getRawTile(source.x, source.y)[0] == 0, label + " detached source remained solid")
	check(host.coop.pvp._replicas.has("falling" + label) and host.coop.pvp._replicas["falling" + label].sprite.is_visible_in_tree(), label + " detached sprite was not presented")
	for offset in WorldData.NEIGHBOURS:
		var cell: Vector2i = source + offset
		check(host.terrain.tile_layer.get_cell_atlas_coords(cell) == empty_atlas, label + " left stale earth crust at " + str(cell))
	check(host.terrain.tile_layer.get_cell_atlas_coords(source) == empty_atlas, label + " vacated cell retained an earth crust")
	await capture(label + "-detached")
	# A repeated tick must retain the clean hole, not restore old edge sprites.
	network._receive({"type":"pvp_tick", "players":[], "terrain_changes":[], "falling":[], "bags":[], "impacts":[]})
	check(host.terrain.tile_layer.get_cell_atlas_coords(above) == empty_atlas, label + " later snapshot restored the stale upper rim")
	# Legitimate borders against remaining earth must survive the redraw.
	var wall := source + Vector2i(2, -1)
	var beside_wall := source + Vector2i(1, -1)
	host.world.getRawTile(wall.x, wall.y)[0] = 1
	host.world.getRawTile(source.x, source.y)[0] = tile
	host.refresh_tiles(patch)
	network._receive({"type":"pvp_tick", "players":[], "terrain_changes":[[source.x,source.y,0]], "falling":[], "bags":[], "impacts":[]})
	var border: Dictionary = host.world.getBlockData(beside_wall.x, beside_wall.y)
	var border_atlas: Vector2i = host.terrain.tile_coordinates[border.filename]
	check(border_atlas != empty_atlas and host.terrain.tile_layer.get_cell_atlas_coords(beside_wall) == border_atlas, label + " erased a legitimate earth border")
	check(host.world.getRawTile(wall.x, wall.y)[0] == 1, label + " changed neighboring solid earth")

func _run() -> void:
	host = load("res://main.tscn").instantiate()
	root.add_child(host)
	await process_frame
	host.coop.network.mode = "pvp"
	host.data = GameData.new()
	host.data.pvp_mode = true
	host.world = WorldData.new(host.data)
	host.audio.state = host.data
	host.coop.network.player_id = "terrain-fixture"
	host.change_scene("Game")
	host._process(0.02)
	host.set_process(false)
	host.set_physics_process(false)
	host.coop.network.set_process(false)
	host.coop.active = true
	# Magnify actual rendered terrain without replacing its TileMap or atlas.
	if not capture_prefix.is_empty():
		host.camera.enabled = false
		var zoom := 90.0
		root.canvas_transform = Transform2D(Vector2(zoom,0), Vector2(0,zoom), Vector2(root.size) * 0.5 - Vector2(20.5,29.5) * zoom)
	await detached_hazard(25, "rock")
	await detached_hazard(28, "lava")
	host.coop.active = false
	host.free()
	await process_frame
	print("PVP_TERRAIN_INTEROP failures=", failures)
	quit(0 if failures == 0 else 1)
