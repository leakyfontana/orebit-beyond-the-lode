class_name VulcanView
extends Node

# Presentation only: the authority owns movement, excavation and every hurtbox.
# Coordinates are Unity world units, exactly like PortPlayer.position_unity.
# The original art is rasterized once at the terrain's 50 pixels/world unit.
const UNITS := Vector2(1.0, -1.0)
const ART_SIZE := 64
const ART_FRAMES := 6
const ART_FPS := 12.0
const PIXEL := 1.0 / 50.0
const OUTLINE := Color("211a1c")
const SHADOW := Color("49302a")
const SKIN := Color("8c4d35")
const RUST := Color("a9613d")
const RIDGE := Color("c08a55")
const HIGHLIGHT := Color("deb27a")
const EMBER := Color("df783e")
const TOOTH := Color("e1c799")
const TOOTH_SHADOW := Color("a98b66")

static var _art: Array[Texture2D] = []

var host: Node
var network: CoopClient
var _canvas: WormCanvas
var _sprites: Array[Sprite2D] = []
var _points := PackedVector2Array()
var _heading := Vector2.RIGHT
var _clock := 0.0
var _last_server_time := -1.0
var _last_frame := -1
var _motion_left := 0.0

# Dust uses the same pixel grid as the art, not smooth vector particles. A fixed
# population has no per-frame nodes, random allocation or gameplay side effects.
class WormCanvas extends Node2D:
	var points := PackedVector2Array()
	var heading := Vector2.RIGHT
	var age := 0.0
	var activity := 0.0

	func _draw() -> void:
		if points.is_empty() or activity <= 0.0:
			return
		var sideways := Vector2(-heading.y, heading.x)
		for i in 18:
			var phase := fposmod(age * 2.4 + float(i) * 0.381966, 1.0)
			var side := -1.0 if i % 2 == 0 else 1.0
			var origin: Vector2 = points[0] if i < 10 else points[mini(points.size() - 1, (i - 8) / 2)]
			var spread := side * (0.36 + phase * 0.3)
			var position := origin + sideways * spread - heading * (phase * 0.48 - 0.22)
			position = (position * 50.0).round() / 50.0
			var size := 0.06 if i % 3 == 0 else 0.04
			var color := Color("bc8d5c") if i % 3 == 0 else Color("71513b")
			color.a = (1.0 - phase) * activity * 0.75
			draw_rect(Rect2(position, Vector2.ONE * size), color)

func configure(main_host: Node, client: CoopClient) -> void:
	host = main_host
	network = client
	if _art.is_empty():
		for kind in 3:
			_art.append(_make_art(kind))

func scene_loaded(snapshot: Dictionary) -> void:
	clear()
	if host.world_root == null:
		return
	_canvas = WormCanvas.new()
	_canvas.name = "VulcanWorm"
	_canvas.z_index = 15
	_canvas.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	host.world_root.add_child(_canvas)
	_canvas.hide()
	apply_event(snapshot)

func _resize_segments(count: int) -> void:
	for sprite in _sprites:
		sprite.free()
	_sprites.resize(count)
	# Draw from tail to head so the head's lip overlaps its flexible collar.
	for i in range(count - 1, -1, -1):
		var sprite := Sprite2D.new()
		sprite.name = "Head" if i == 0 else ("Tail" if i == count - 1 else "Ring%d" % i)
		sprite.texture = _art[0 if i == 0 else (2 if i == count - 1 else 1)]
		sprite.hframes = ART_FRAMES
		sprite.scale = Vector2.ONE * PIXEL
		sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		_canvas.add_child(sprite)
		_sprites[i] = sprite
	_last_frame = -1

func apply_event(event: Dictionary) -> void:
	if event.has("worm") and event.worm is Dictionary:
		apply_worm(event.worm)

func apply_worm(worm: Dictionary) -> void:
	if not is_instance_valid(_canvas):
		return
	var server_time := float(worm.get("server_time", 0.0))
	if server_time < _last_server_time:
		return
	var segments: Array = worm.get("segments", [])
	if segments.is_empty():
		return
	var count := segments.size()
	# Length belongs to the authority; a release mismatch must not hide the worm.
	if _sprites.size() != count:
		_resize_segments(count)
	# Never interpolate between tile corners or predict unconsumed terrain.
	# Visible centers match the authoritative segments, including length changes.
	# Motion has the server snapshot cadence; skin, jaws and dust animate at 12Hz.
	var moved := false
	for i in count:
		var segment: Array = segments[i]
		var point := Vector2(float(segment[0]), float(segment[1])) * UNITS
		if _points.size() == count and point.distance_squared_to(_points[i]) > 0.000001:
			moved = true
		_sprites[i].position = point
	if _points.size() != count:
		_points.resize(count)
	for i in count:
		_points[i] = _sprites[i].position
	var direction: Array = worm.get("direction", [1, 0])
	var incoming := Vector2(float(direction[0]), -float(direction[1]))
	if not incoming.is_zero_approx():
		_heading = _cardinal(incoming)
	for i in count:
		var tangent := _heading if i == 0 else _cardinal(_points[i - 1] - _points[i])
		_sprites[i].rotation = tangent.angle()
	if moved:
		_motion_left = 0.22
	_clock = maxf(_clock, server_time)
	_last_server_time = server_time
	_canvas.points = _points
	_canvas.heading = _heading
	_canvas.show()
	_update_animation()

func tick(delta: float) -> void:
	if not is_instance_valid(_canvas) or not _canvas.visible:
		return
	_clock += delta
	_motion_left = maxf(0.0, _motion_left - delta)
	_update_animation()

func clear() -> void:
	if is_instance_valid(_canvas):
		_canvas.hide()
		_canvas.queue_free()
	_canvas = null
	_sprites.clear()
	_points.clear()
	_clock = 0.0
	_last_server_time = -1.0
	_last_frame = -1
	_motion_left = 0.0

func _update_animation() -> void:
	var frame := floori(_clock * ART_FPS)
	if frame == _last_frame:
		return
	_last_frame = frame
	for i in _sprites.size():
		_sprites[i].frame = posmod(frame - i * 2, ART_FRAMES)
	_canvas.age = _clock
	_canvas.activity = minf(1.0, _motion_left * 8.0)
	_canvas.queue_redraw()

static func _cardinal(direction: Vector2) -> Vector2:
	if absf(direction.x) >= absf(direction.y):
		return Vector2(1.0 if direction.x >= 0.0 else -1.0, 0.0)
	return Vector2(0.0, 1.0 if direction.y >= 0.0 else -1.0)

# Original ironstone hide, ochre annular ridges, ember fissures and two opposing
# mineral-cutting jaws. No external image or Dune artwork is shipped or sampled.
# References/design rationale are recorded in the project's README Vulcan notes.
static func _make_art(kind: int) -> Texture2D:
	var image := Image.create(ART_SIZE * ART_FRAMES, ART_SIZE, false, Image.FORMAT_RGBA8)
	image.fill(Color.TRANSPARENT)
	for frame in ART_FRAMES:
		for y in ART_SIZE:
			for x in ART_SIZE:
				var color := _art_pixel(kind, frame, x, y)
				if color.a > 0.0:
					image.set_pixel(frame * ART_SIZE + x, y, color)
	return ImageTexture.create_from_image(image)

static func _art_pixel(kind: int, frame: int, x: int, y: int) -> Color:
	var u := float(x - 32)
	var v := float(y - 32)
	if absf(u) > 27.0:
		return Color.TRANSPARENT
	var radius := 21.0 - 3.0 * pow(absf(u) / 27.0, 6.0)
	if kind == 0 and u > -6.0:
		radius = sqrt(maxf(0.0, 1.0 - pow((u - 1.0) / 29.0, 2.0))) * 23.0
	elif kind == 2:
		# The armored tail retains its full-width silhouette.
		radius -= maxf(0.0, -u) * 0.075
	if absf(v) > radius:
		return Color.TRANSPARENT
	if absf(v) > radius - 2.0 or absf(u) > 26.0:
		return OUTLINE
	var grain := posmod(x * 73 + y * 151 + (x * y * 19), 29)
	var band := posmod(x + int(v * v / 110.0) + frame * 10 / ART_FRAMES, 10)
	var color := SKIN
	if v > radius * 0.58:
		color = SHADOW
	elif band >= 8:
		color = SHADOW
	elif band == 0:
		color = HIGHLIGHT if v < 2.0 else RIDGE
	elif band <= 2:
		color = RIDGE
	elif grain < 7:
		color = RUST
	elif grain > 25:
		color = SHADOW
	# Broken dorsal scutes and sparse hot mineral seams replace a smooth tube.
	if v < -radius * 0.48 and band > 2 and band < 8:
		color = RIDGE if grain < 8 else RUST
	if posmod(x + y / 3, 19) == 0 and posmod(y / 7, 3) == 1 and band > 2:
		color = EMBER if grain < 19 else OUTLINE
	if absf(v) > radius - 4.0 and v < 0.0:
		color = RIDGE
	if kind == 2 and u < -16.0:
		color = SHADOW if band > 3 else RIDGE
	if kind != 0 or u < -3.0:
		return color
	var jaw_cycle := 3 - absi(frame - 3)
	var opening := 10.0 + float(jaw_cycle)
	var mouth_x := (u - 11.0) / 16.0
	var mouth_y := v / opening
	var mouth := mouth_x * mouth_x + mouth_y * mouth_y
	if mouth > 1.2:
		return color
	if mouth > 1.0:
		return RIDGE if v < 0.0 else SHADOW
	color = OUTLINE
	if mouth < 0.15:
		color = Color("623025") if grain < 19 else Color("7e3c28")
	var edge := sqrt(maxf(0.0, 1.0 - mouth_x * mouth_x)) * opening
	var tooth_length := 3.0 + float(posmod(x / 5, 3))
	if posmod(x, 5) < 2 and absf(v) > edge - tooth_length:
		color = TOOTH if v < 0.0 else TOOTH_SHADOW
	if u > 23.0 and absf(v) > 2.0 and absf(v) < 6.0:
		color = TOOTH
	return color
