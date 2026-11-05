extends SceneTree

const SceneBridgeScript = preload("res://scripts/scene_bridge.gd")
const GROUPS = ["P2Standing", "P2Walking", "P2ArmAttack", "P2FireballAttack", "P2Intro", "P2Death"]
var failures: Array[String] = []

func _initialize() -> void:
	var catalog = load("res://data/game_assets.res")
	var bridge = SceneBridgeScript.new(catalog.data)
	var groups: Dictionary = {}
	for key in catalog.data.sprites:
		var definition: Dictionary = catalog.data.sprites[key]
		var path := str(definition.get("path", ""))
		if not path.contains("/BossAnimation/P2"):
			continue
		var texture: Texture2D = bridge.sprite({"sprite_key": key})
		if texture == null:
			failures.append("Missing final-form texture: " + path)
			continue
		if texture.get_width() < 150 or texture.get_height() < 200:
			continue # Detached arm and projectile effects are not body backplates.
		groups[path.get_base_dir().get_file()] = true
		_check_background(texture, "baked sprite " + path)
		if path.ends_with("P2Standing/1755.png") or path.ends_with("P2Intro/1752.png") or path.ends_with("P2Intro/1752.jpg"):
			var hair: Color = texture.get_image().get_pixel(95, 35)
			if hair.a < 0.99 or maxf(hair.r, maxf(hair.g, hair.b)) > 0.12:
				failures.append("Dark hair detail erased or recolored: " + path)
	for group in GROUPS:
		if not groups.has(group):
			failures.append("Final-form state missing from baked sprites: " + group)
	# Animation tracks have their own texture references; checking only the
	# catalog would miss an old JPEG still rendered by an intro/attack clip.
	var controller = load("res://animations/controllers/b1b821fdb4f0b7d458d90288e3fc67a3.tres")
	for name in controller.library.get_animation_list():
		var animation: Animation = controller.library.get_animation(name)
		if not animation.resource_name.begins_with("P2"):
			continue
		var checked: Dictionary = {}
		for track in animation.get_track_count():
			if animation.track_get_type(track) != Animation.TYPE_VALUE:
				continue
			for index in animation.track_get_key_count(track):
				var value = animation.track_get_key_value(track, index)
				if value is Texture2D and value.get_width() >= 150 and value.get_height() >= 200 and not checked.has(value):
					checked[value] = true
					_check_background(value, "animation " + animation.resource_name)
	bridge.free()
	for failure in failures:
		push_error(failure)
	print("BOSS_BACKDROP_INTEROP failures=%d" % failures.size())
	quit(0 if failures.is_empty() else 1)

func _check_background(texture: Texture2D, label: String) -> void:
	var image := texture.get_image()
	for point in [Vector2i.ZERO, Vector2i(image.get_width() - 1, 0), Vector2i(0, image.get_height() - 1), Vector2i(image.get_width() - 1, image.get_height() - 1)]:
		if image.get_pixelv(point).a > 0.001:
			failures.append("Opaque rectangular backplate in %s at %s" % [label, point])
