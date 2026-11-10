class_name TerrainView
extends Node2D

enum ColliderValidity { INVALID, CURRENT }
enum ColliderResidency { OUTSIDE_WINDOW, MISSING, RESIDENT }

const FUEL_STATION_TILES := ["Shop125", "Shop126", "Shop127", "Shop128", "Shop129", "Shop130"]
# Preserve the old observable invalid-center value without storing it as state.
const LEGACY_INVALID_CENTER := Vector2i(-1000, -1000)

var world: WorldData
var data: GameData
var tile_layer: TileMapLayer
var colliders: Dictionary = {}
var tile_coordinates: Dictionary
var _physics_center := Vector2i.ZERO
var physics_center: Vector2i:
	get:
		return LEGACY_INVALID_CENTER if collider_validity == ColliderValidity.INVALID else _physics_center
	set(value):
		if value == LEGACY_INVALID_CENTER:
			_invalidate_colliders()
		else:
			_physics_center = value
			collider_validity = ColliderValidity.CURRENT
var collider_validity := ColliderValidity.INVALID
var physics_body: StaticBody2D
var tile_shape := RectangleShape2D.new()

func configure(world_data: WorldData, state: GameData, scene_bridge: SceneBridge) -> void:
	world = world_data
	data = state
	var tiles := load(str(scene_bridge.manifest.native_terrain_tileset)) as TileSet
	tile_coordinates = tiles.get_meta("coordinates")
	tile_layer = TileMapLayer.new()
	tile_layer.tile_set = tiles
	tile_layer.scale = Vector2.ONE / 50.0
	tile_layer.position.y = -1.0
	tile_layer.collision_enabled = false
	tile_layer.navigation_enabled = false
	tile_layer.occlusion_enabled = false
	add_child(tile_layer)
	for x in range(world.surface_left(), data.earthWidth):
		for y in data.earthHeight:
			_update_tile(Vector2i(x, y))
	z_index = 1
	tile_shape.size = Vector2.ONE
	physics_body = StaticBody2D.new()
	physics_body.collision_layer = 1
	physics_body.collision_mask = 2
	var material := PhysicsMaterial.new()
	material.friction = 0.0
	material.bounce = 0.0
	physics_body.physics_material_override = material
	add_child(physics_body)
	physics_body.add_to_group("Ground")

func follow(position_unity: Vector2) -> void:
	var center := Vector2i(floori(position_unity.x), ceili(-position_unity.y))
	if center != physics_center:
		_publish_physics_center(center)

func refresh(cells: Array) -> void:
	for cell in cells:
		_retire_collider(cell)
		_update_tile(cell)
	_invalidate_colliders()

func _invalidate_colliders() -> void:
	collider_validity = ColliderValidity.INVALID

func _publish_physics_center(center: Vector2i) -> void:
	_physics_center = center
	collider_validity = ColliderValidity.CURRENT
	_update_colliders()

func collider_residency(cell: Vector2i) -> ColliderResidency:
	if absi(cell.x - physics_center.x) > 12 or absi(cell.y - physics_center.y) > 12:
		return ColliderResidency.OUTSIDE_WINDOW
	return ColliderResidency.RESIDENT if colliders.has(cell) else ColliderResidency.MISSING

func _retire_collider(cell: Vector2i) -> void:
	if colliders.has(cell):
		colliders[cell].queue_free()
		colliders.erase(cell)

func _solid(cell: Vector2i) -> bool:
	return world.getBlockData(cell.x, cell.y).get("layer", "Traversable") != "Traversable"

func _update_colliders() -> void:
	for cell in colliders.keys():
		if collider_residency(cell) == ColliderResidency.OUTSIDE_WINDOW:
			_retire_collider(cell)
	for x in range(maxi(world.surface_left(), physics_center.x - 12), mini(data.earthWidth, physics_center.x + 13)):
		for y in range(maxi(0, physics_center.y - 12), mini(data.earthHeight, physics_center.y + 13)):
			var cell := Vector2i(x, y)
			if collider_residency(cell) == ColliderResidency.MISSING and _solid(cell):
				var shape := CollisionShape2D.new()
				shape.shape = tile_shape
				shape.position = Vector2(x + 0.5, y - 0.5)
				physics_body.add_child(shape)
				colliders[cell] = shape

func _update_tile(cell: Vector2i) -> void:
	var tile: Dictionary = world.getBlockData(cell.x, cell.y)
	# Sinclair's single raster replaces the old six shop tiles, not their physics.
	if tile.filename == "Empty" or tile.filename in FUEL_STATION_TILES:
		tile_layer.erase_cell(cell)
		return
	assert(tile_coordinates.has(tile.filename), "Missing baked terrain tile: " + str(tile.filename))
	tile_layer.set_cell(cell, 0, tile_coordinates[tile.filename], _rotation_flags(int(tile.rotation)))

static func _rotation_flags(rotation: int) -> int:
	match posmod(rotation - 2, 4):
		1: return TileSetAtlasSource.TRANSFORM_TRANSPOSE | TileSetAtlasSource.TRANSFORM_FLIP_V
		2: return TileSetAtlasSource.TRANSFORM_FLIP_H | TileSetAtlasSource.TRANSFORM_FLIP_V
		3: return TileSetAtlasSource.TRANSFORM_TRANSPOSE | TileSetAtlasSource.TRANSFORM_FLIP_H
	return 0
