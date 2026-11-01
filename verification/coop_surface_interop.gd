extends SceneTree

var failures := 0

func _initialize() -> void:
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _run() -> void:
	var private_data := GameData.new()
	var shared_data := GameData.new()
	shared_data.coop_mode = true
	var private_world := WorldData.new(private_data)
	var shared_world := WorldData.new(shared_data)
	private_world.generate(41723)
	shared_world.generate(41723)
	check(shared_data.my_map == private_data.my_map, "Western generation changed the original seeded mine")
	check(shared_data.my_map.size() == 36, "Western generation widened the saved map")
	check(private_world.western_columns.is_empty(), "Private generation allocated co-op terrain")
	check(shared_world.western_columns.size() == 10, "Co-op generation omitted western columns")
	check(private_world.surface_left() == 0 and shared_world.surface_left() == -10, "World left bounds changed")
	var original_before: Array = shared_data.my_map.duplicate(true)
	for x in range(-10, 0):
		check(shared_world.inBounds(x, 0) and shared_world.inBounds(x, 599), "West is not in bounds at every depth")
		check(shared_world.getBlockData(x, 4).filename == "Empty", "West obstructed the walking space")
		check(shared_world.getBlockData(x, 599).name == "Darkness", "West lost the original bottom-depth rules")
		check(shared_world.getRawTile(x, 589)[0] == -999, "West lost the original deep blank chamber")
		check(shared_world.getBlockData(x, 595).name == "Souls", "West lost the original souls row")
		check(not private_world.inBounds(x, 5) and private_world.getRawTile(x, 5).is_empty(), "West entered private coordinates")
		check(private_world.getBlockData(x, 5).filename == "Empty", "West rendered in private mode")
		if x < -1:
			check(shared_world.western_columns[x + 10] != shared_world.western_columns[x + 11], "Western columns duplicated one generated sample")
	for x in [-10, -9, -2, -1]:
		check(shared_world.getBlockData(x, 5).name == "Grass", "Non-slab western surface lost generated grass")
		check(shared_world.doesBlockExistAndIsDiggable(x, 5), "Generated western grass cannot be drilled")
	for outside in [Vector2i(-11, 5), Vector2i(36, 5), Vector2i(-5, -1), Vector2i(-5, 600)]:
		check(not shared_world.inBounds(outside.x, outside.y), "Co-op terrain exceeded its bounds")
		check(shared_world.getRawTile(outside.x, outside.y).is_empty(), "Out-of-bounds raw access wrapped into terrain")
		check(shared_world.getBlockData(outside.x, outside.y).filename == "Empty", "Out-of-bounds terrain rendered")
		check(shared_world.instantDigBlock(outside.x, outside.y).is_empty(), "Out-of-bounds excavation was accepted")

	# Inspect genuinely generated cells, rather than copying synthetic fixtures into
	# both domains. Each terrain class must retain its original gameplay semantics.
	var samples: Dictionary = {}
	for x in range(-10, 0):
		for y in range(6, 588):
			var raw: Array = shared_world.getRawTile(x, y)
			var tile: Dictionary = shared_world.getBlockData(x, y)
			var kind: String = ""
			if raw[0] >= 1 and raw[0] <= 5:
				kind = "Dirt"
			elif raw[0] == 6:
				kind = "Ironium"
				check(tile.ore_value == 30 and tile.weight == 1, "Generated western ore lost its value or cargo weight")
			elif raw[0] >= 25 and raw[0] <= 27:
				kind = "Rock"
			elif raw[0] >= 28 and raw[0] <= 30:
				kind = "Lava"
			elif raw[0] == 31:
				kind = "Gas"
			elif raw[0] == 0:
				kind = "DirtConnector"
			if not kind.is_empty():
				check(tile.name == kind, "Generated western type decoded incorrectly: " + kind)
				check(tile.layer == ("Traversable" if kind == "DirtConnector" else "Diggable"), "Generated western type has the wrong collision layer: " + kind)
				if not samples.has(kind):
					samples[kind] = Vector2i(x, y)
	for kind in ["Dirt", "Ironium", "Rock", "Lava", "Gas", "DirtConnector"]:
		check(samples.has(kind), "Western generation omitted " + kind)
		if not samples.has(kind):
			continue
		var cell: Vector2i = samples[kind]
		if kind == "DirtConnector":
			check(not shared_world.doesBlockExistAndIsDiggable(cell.x, cell.y), "A generated tunnel remained drillable")
			continue
		check(shared_world.doesBlockExistAndIsDiggable(cell.x, cell.y) == (kind != "Rock"), "Western drill acceptance differs for " + kind)
		check(shared_world.doesBlockExistAndIsNotDiggable(cell.x, cell.y) == (kind == "Rock"), "Western rock blocking differs for " + kind)
		var before: Array = shared_world.western_columns.duplicate(true)
		var tile: Dictionary = shared_world.getBlockData(cell.x, cell.y).duplicate()
		if kind == "Rock":
			check(shared_world.instantDigBlock(cell.x, cell.y).has(cell), "Western rock resisted coordinate excavation")
		else:
			var halfway: Dictionary = shared_world.halfwayDigBlock(cell.x, cell.y, cell.y - 1, cell.x, 0)
			check(not halfway.is_empty(), "Western halfway excavation was rejected: " + kind)
			check(shared_world.getRawTile(cell.x, cell.y) == [0, 0], "Halfway excavation did not clear western raw terrain")
			var visible: Dictionary = shared_world.getBlockData(cell.x, cell.y)
			check(visible.name == kind and visible.layer == "Diggable", "Western halfway tile lost its solid identity")
			check(visible.ore_value == tile.ore_value and visible.weight == tile.weight, "Western halfway ore lost its reward")
			check(visible.filename.begins_with("BlockHalfwayDug"), "Western halfway tile did not change its graphic")
			check(shared_world.digBlock(cell.x, cell.y).has(cell), "Western excavation completion omitted its changed cell")
		check(shared_world.getRawTile(cell.x, cell.y) == [0, 0], "Western excavation did not mutate its own cell")
		check(shared_world.getBlockData(cell.x, cell.y).layer == "Traversable", "Excavated western terrain stayed solid")
		check(not shared_world.halfway_blocks.has(cell), "Western excavation left a halfway collision behind")
		_check_other_western_cells(shared_world, before, cell)
		check(shared_data.my_map == original_before, "Negative excavation wrapped into the original saved mine")

	for x in range(-8, -2):
		var pavement := 0 if x == -8 else (2 if x == -3 else 1)
		var slab_before: Array = shared_world.getRawTile(x, 5).duplicate()
		check(shared_world.getBlockData(x, 5).filename == "Pavement" + str(pavement), "Ria slab lost its original concrete textures")
		check(not shared_world.doesBlockExistAndIsDiggable(x, 5) and shared_world.doesBlockExistAndIsNotDiggable(x, 5), "Ria slab became drillable")
		check(shared_world.halfwayDigBlock(x, 5, x, 4, 0).is_empty(), "Partial drilling accepted the slab")
		check(shared_world.digBlock(x, 5).is_empty(), "Drilling completed on the slab")
		check(shared_world.instantDigBlock(x, 5).is_empty(), "Instant excavation accepted the slab")
		check(shared_world.getRawTile(x, 5) == slab_before, "Excavation mutated the Ria slab")
	check(shared_world.halfway_blocks.is_empty(), "Slab excavation left a halfway tile")

	# A controlled neighborhood exercises actual connector graphics and refreshes
	# across x=-1/0, including the original swapped previous-coordinate convention.
	for x in range(-2, 2):
		for y in range(39, 43):
			var raw: Array = shared_world.getRawTile(x, y)
			raw[0] = 1
			raw[1] = 2
	shared_world.instantDigBlock(0, 40)
	check(shared_world.getBlockData(0, 40).filename == "DirtConnectors/46", "Isolated seam tunnel has the wrong graphic")
	var seam_halfway: Dictionary = shared_world.halfwayDigBlock(-1, 40, 40, 0, 0)
	check(seam_halfway.get("refresh_cells", []).has(Vector2i(0, 40)), "Western halfway dig did not refresh its original-domain neighbor")
	check(shared_world.getBlockData(0, 40).filename == "DirtConnectors/43", "Tunnel connectivity did not read the western raw neighbor")
	check(shared_world.digBlock(-1, 40).has(Vector2i(0, 40)), "Western completion did not refresh across the seam")
	check(shared_world.instantDigBlock(0, 41).has(Vector2i(-1, 40)), "Original-domain excavation did not refresh its western tunnel neighbor")

	var private_before: Array = private_data.my_map.duplicate(true)
	check(private_world.halfwayDigBlock(-1, 6, 6, 0, 0).is_empty(), "Private halfway excavation accepted a negative coordinate")
	check(private_world.digBlock(-1, 6).is_empty(), "Private completion accepted a negative coordinate")
	check(private_world.instantDigBlock(-1, 6).is_empty(), "Private instant excavation wrapped into the saved mine")
	check(private_data.my_map == private_before and private_world.halfway_blocks.is_empty(), "Co-op excavation leaked into the private world")
	# Original positive-coordinate overload behavior is intentionally unchanged.
	check(private_world.instantDigBlock(2, 5).has(Vector2i(2, 5)), "Western slab protection changed original private coordinate excavation")
	check(private_world.getRawTile(2, 5) == [0, 0], "Original private coordinate excavation stopped clearing its tile")
	shared_world.halfwayDigBlock(-2, 40, 40, -1, 0)
	shared_data.coop_mode = false
	check(shared_world.getRawTile(-2, 40).is_empty() and shared_world.getBlockData(-2, 40).filename == "Empty", "Western halfway state leaked when leaving co-op mode")
	shared_world.generate(41723)
	check(shared_world.western_columns.is_empty() and shared_world.halfway_blocks.is_empty(), "Private regeneration retained co-op excavation state")
	check(shared_data.my_map == private_before, "Co-op generation or excavation changed the next private seeded mine")

	var player := PortPlayer.new()
	var body := RigidBody2D.new()
	root.add_child(body)
	body.freeze = true
	PhysicsServer2D.body_set_state(body.get_rid(), PhysicsServer2D.BODY_STATE_TRANSFORM, Transform2D(0, Vector2(-5.5, 3.5)))
	player.body = body
	shared_data.coop_mode = true
	player.data = shared_data
	player.createExplosions(2.0, 1.0, 1)
	check(player._explosion_location == Vector2i(-6, 4), "Shared blast mirrored its west-of-zero origin into the original mine")
	player.data = private_data
	player.createExplosions(2.0, 1.0, 1)
	check(player._explosion_location == Vector2i(5, 4), "Western terrain changed private blast coordinate behavior")
	var detector := Node2D.new()
	root.add_child(detector)
	detector.position = Vector2(-5.5, 4.25)
	check(player._detector_cell(detector) == Vector2i(-6, 5), "Drill detector mirrored a negative x coordinate")
	detector.free()
	player.free()
	body.free()
	print("COOP_SURFACE_INTEROP failures=" + str(failures))
	quit(0 if failures == 0 else 1)

func _check_other_western_cells(world: WorldData, before: Array, changed: Vector2i) -> void:
	for column in range(10):
		for y in range(600):
			if Vector2i(column - 10, y) != changed:
				check(world.getRawTile(column - 10, y) == before[column][y], "Negative mutation aliased another western cell")
