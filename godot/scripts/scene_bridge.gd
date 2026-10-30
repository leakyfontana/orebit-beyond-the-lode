class_name SceneBridge
extends Node

signal invoked(target_id: String, method: String, argument: Variant)

var manifest: Dictionary
var scene: Dictionary
var nodes: Dictionary = {}
var graphics: Dictionary = {}
var texts: Dictionary = {}
var sliders: Dictionary = {}
var textures: Dictionary = {}
var buttons: Dictionary = {}
var button_tweens: Dictionary = {}
var _component_cache: Dictionary = {}
var _scroll_states: Dictionary = {}
var _source_text_layouts: Dictionary = {}
var _source_font_metrics: Dictionary = {}
var world_root: Node2D
var ui_root: Control
var scene_name: String

func _init(source: Dictionary) -> void:
	manifest = source

func build(which: String, world_parent: Node2D, ui_parent: Control) -> void:
	scene_name = which
	scene = manifest.scenes[which]
	world_root = world_parent
	ui_root = ui_parent
	instantiate_native(world_parent, ui_parent)

func instantiate_native(world_parent: Node2D, ui_parent: Control) -> void:
	_component_cache.clear()
	_scroll_states.clear()
	var packed := load(str(scene.native_scene_path)) as PackedScene
	var instance := packed.instantiate()
	_clear_scene_ownership(instance)
	var bindings: Dictionary = instance.get_meta("bindings")
	for entry in [["nodes", nodes], ["graphics", graphics], ["texts", texts], ["sliders", sliders], ["buttons", buttons]]:
		for id in bindings[entry[0]]:
			entry[1][id] = instance.get_node(bindings[entry[0]][id])
	for child in instance.get_node("World").get_children():
		child.reparent(world_parent, false)
	for child in instance.get_node("UI").get_children():
		child.reparent(ui_parent, false)
	instance.free()
	_install_source_text_layouts()
	for id in buttons:
		for component in components(id):
			var p: Dictionary = component.get("properties", {})
			if not p.has("m_OnClick"):
				continue
			var button: Button = buttons[id]
			button.mouse_entered.connect(_button_appearance.bind(p, "Highlighted"))
			button.mouse_exited.connect(_button_appearance.bind(p, "Normal"))
			button.button_down.connect(_button_appearance.bind(p, "Pressed"))
			button.button_up.connect(_button_appearance.bind(p, "Highlighted"))
			button.pressed.connect(_invoke_calls.bind(p.m_OnClick.get("m_PersistentCalls", {}).get("m_Calls", [])))
	call_deferred("_finish_layout")

func _clear_scene_ownership(target: Node) -> void:
	target.owner = null
	for index in target.get_child_count():
		_clear_scene_ownership(target.get_child(index))


func object(id: String) -> Dictionary:
	return scene.objects.get(id, {})

func components(id: String) -> Array:
	if _component_cache.has(id):
		return _component_cache[id]
	var result: Array = []
	for component_id in scene.game_objects.get(id, {}).get("component_ids", []):
		result.append(object(str(component_id)))
	_component_cache[id] = result
	return result

func properties(id: String, script_name: String) -> Dictionary:
	for component in components(id):
		if component.get("script", "") == script_name or component.get("type", "") == script_name:
			return component.get("properties", {})
	return {}

func component_owner(reference: Variant) -> String:
	var id := reference_id(reference)
	if scene.game_objects.has(id):
		return id
	return reference_id(object(id).get("properties", {}).get("m_GameObject", {}))

func reference_id(reference: Variant) -> String:
	if reference is Dictionary:
		return str(reference.get("fileID", "0"))
	return str(reference)

func node(reference: Variant) -> Node:
	return nodes.get(component_owner(reference))

func set_active(reference: Variant, active: bool) -> void:
	var target := node(reference)
	if target is CanvasItem:
		target.visible = active

func set_particles(reference: Variant, emitting: bool) -> void:
	var target := node(reference)
	if target == null:
		return
	for child in target.get_children():
		if child is GPUParticles2D:
			if emitting and not child.emitting:
				child.restart()
			child.emitting = emitting

func set_text(reference: Variant, value: String) -> void:
	var id := component_owner(reference)
	if texts.has(id):
		if _source_text_layouts.has(id):
			_source_text_layouts[id].raw = value
			_source_text_layouts[id].width = -1.0
			_wrap_source_text(id)
		else:
			texts[id].text = value
		if _scroll_states.has(id):
			_refresh_scroll(_scroll_states[id])

func set_image(reference: Variant, path: String) -> void:
	var id := component_owner(reference)
	if graphics.has(id):
		graphics[id].texture = texture_path(path)

func set_value(reference: Variant, value: float) -> void:
	var id := component_owner(reference)
	if sliders.has(id):
		sliders[id].value = value

func get_value(reference: Variant) -> float:
	var id := component_owner(reference)
	return sliders[id].value if sliders.has(id) else 0.0

func texture_path(path: String) -> Texture2D:
	if textures.has(path):
		return textures[path]
	if not ResourceLoader.exists(path):
		return null
	var texture: Texture2D = load(path)
	textures[path] = texture
	return texture

func sprite(reference: Dictionary) -> Texture2D:
	var key: String = reference.get("sprite_key", "")
	if key.is_empty():
		return texture_path(str(reference.get("path", "")))
	if textures.has(key):
		return textures[key]
	var path: String = manifest.get("native_sprite_paths", {}).get(key, "")
	if path.is_empty():
		push_error("Missing baked sprite resource: " + key)
		return null
	var texture := load(path) as Texture2D
	textures[key] = texture
	return texture

func _vector(value: Dictionary, default: Vector2 = Vector2.ZERO) -> Vector2:
	return Vector2(float(value.get("x", default.x)), float(value.get("y", default.y)))

func _color(value: Dictionary) -> Color:
	return Color(float(value.get("r", 1)), float(value.get("g", 1)), float(value.get("b", 1)), float(value.get("a", 1)))


func _invoke_calls(calls: Array) -> void:
	for event in calls:
		if int(event.get("m_CallState", 0)) == 0:
			continue
		var argument: Variant = null
		var arguments: Dictionary = event.get("m_Arguments", {})
		match int(event.get("m_Mode", 1)):
			2: argument = arguments.get("m_ObjectArgument", {})
			3: argument = int(arguments.get("m_IntArgument", 0))
			4: argument = float(arguments.get("m_FloatArgument", 0))
			5: argument = str(arguments.get("m_StringArgument", ""))
			6: argument = bool(arguments.get("m_BoolArgument", false))
		invoked.emit(reference_id(event.get("m_Target", {})), str(event.get("m_MethodName", "")), argument)

func _source_text_layout_data(p: Dictionary, text_size: float) -> Dictionary:
	# Import-time only: the runtime catalog deliberately excludes font manifests.
	# Store these recovered metrics in the native Label's PackedScene metadata.
	var reference: Dictionary = p.get("m_fontAsset", {})
	var guid := str(reference.get("guid", ""))
	var info: Dictionary = manifest.get("fonts", {}).get(guid, {})
	if info.get("glyphs", []).is_empty():
		return {}
	if not _source_font_metrics.has(guid):
		var glyphs := {}
		var characters := {}
		var pairs := {}
		for glyph in info.glyphs:
			glyphs[int(glyph.m_Index)] = glyph
		for character in info.characters:
			var glyph: Dictionary = glyphs[int(character.m_GlyphIndex)]
			characters[int(character.m_Unicode)] = Vector2(float(glyph.m_Metrics.m_HorizontalAdvance) * float(character.get("m_Scale", 1)) * float(glyph.get("m_Scale", 1)), int(character.m_GlyphIndex))
		for pair in info.get("feature_table", {}).get("m_GlyphPairAdjustmentRecords", []):
			var first: Dictionary = pair.m_FirstAdjustmentRecord
			var second: Dictionary = pair.m_SecondAdjustmentRecord
			pairs[Vector2i(int(first.m_GlyphIndex), int(second.m_GlyphIndex))] = Vector2(float(first.m_GlyphValueRecord.m_XAdvance), float(second.m_GlyphValueRecord.m_XAdvance))
		_source_font_metrics[guid] = {"characters": characters, "pairs": pairs}
	var source_font: Dictionary = manifest.serialized_assets[guid].objects[str(reference.get("fileID", "11400000"))].properties
	var spacing := float(source_font.get("normalSpacingOffset", 0)) + float(p.get("m_characterSpacing", 0))
	if (int(p.get("m_fontStyle", 0)) & 1) != 0:
		spacing += float(source_font.get("boldSpacing", 0))
	return {
		"metrics": _source_font_metrics[guid], "kerning": bool(p.get("m_enableKerning", true)),
		"scale": text_size / float(info.face_info.m_PointSize) * float(info.face_info.get("m_Scale", 1)),
		"spacing": spacing * text_size * 0.01,
		"word_spacing": float(p.get("m_wordSpacing", 0)) * text_size * 0.01,
	}

func _install_source_text_layouts() -> void:
	_source_text_layouts.clear()
	for id in texts:
		var label: Label = texts[id]
		# World-space popup labels retain their original 3D text sizing path.
		if not nodes[id] is Control or not label.has_meta("source_text_layout"):
			continue
		var state: Dictionary = label.get_meta("source_text_layout").duplicate()
		state.merge({
			"raw": label.text, "width": -1.0, "updating": false,
			"native_autowrap": label.autowrap_mode, "native_clip": label.clip_text,
		})
		_source_text_layouts[id] = state
		# Keep the recovered native font and Label renderer. Only line breaking
		# differs: TMP tests visible glyphs before adding their style spacing,
		# and never rejects a line because its following space overflows.
		# TMPro_UGUI_Private: visible-character bounds check and xAdvance.
		label.resized.connect(_wrap_source_text.bind(id))
		_wrap_source_text(id)

func _wrap_source_text(id: String) -> void:
	var state: Dictionary = _source_text_layouts[id]
	var label: Label = texts[id]
	if state.updating or state.width == label.size.x or label.size.x <= 0.0:
		return
	state.updating = true
	state.width = label.size.x
	var raw: String = state.raw
	var characters: Dictionary = state.metrics.characters
	var pairs: Dictionary = state.metrics.pairs
	# Recovered glyph metrics describe ordinary single-glyph Latin text, not
	# missing-font fallback, Unicode shaping/format controls, or tab/CR layout.
	# Keep the complete string on its existing native shaping path in those
	# cases: measuring isolated fallback code points would split clusters and
	# cannot recover TMP fallback metrics that were never present in the atlas.
	for offset in raw.length():
		var code := raw.unicode_at(offset)
		if code == 10:
			continue
		if code < 32 or code > 255 or (code >= 127 and code <= 160) or code == 173 or not characters.has(code):
			label.autowrap_mode = state.native_autowrap
			label.clip_text = state.native_clip
			label.text = raw
			state.updating = false
			return
	label.autowrap_mode = TextServer.AUTOWRAP_OFF
	label.clip_text = true
	var lines := PackedStringArray()
	var line_start := 0
	var last_break := -1
	var break_end := -1
	var advance := 0.0
	var index := 0
	while index < raw.length():
		var code := raw.unicode_at(index)
		if code == 10:
			lines.append(raw.substr(line_start, index - line_start))
			line_start = index + 1
			last_break = -1
			advance = 0.0
			index += 1
			continue
		var character: Vector2 = characters[code]
		var glyph_advance: float = character.x * float(state.scale)
		var is_space := code == 32 or code == 13
		# The epsilon is TMP's own marginWidth + 0.0001f, not a fit tolerance.
		if not is_space and advance + glyph_advance > label.size.x + 0.0001 and index > line_start:
			var end := break_end if last_break >= line_start else index
			lines.append(raw.substr(line_start, end - line_start))
			line_start = last_break + 1 if last_break >= line_start else index
			index = line_start
			last_break = -1
			advance = 0.0
			continue
		var adjustment := 0.0
		if state.kerning:
			if index + 1 < raw.length() and raw.unicode_at(index + 1) != 10:
				var next: Vector2 = characters[raw.unicode_at(index + 1)]
				adjustment += float(pairs.get(Vector2i(int(character.y), int(next.y)), Vector2.ZERO).x)
			if index > line_start:
				var previous: Vector2 = characters[raw.unicode_at(index - 1)]
				adjustment += float(pairs.get(Vector2i(int(previous.y), int(character.y)), Vector2.ZERO).y)
		advance += glyph_advance + adjustment * float(state.scale) + float(state.spacing)
		if is_space:
			advance += float(state.word_spacing)
			last_break = index
			break_end = index
		elif code == 45:
			last_break = index
			break_end = index + 1
		index += 1
	lines.append(raw.substr(line_start))
	label.text = "\n".join(lines)
	state.updating = false

func _finish_layout() -> void:
	for id in scene.game_objects:
		var target := nodes.get(id) as Control
		if target == null:
			continue
		for component in components(id):
			var p: Dictionary = component.get("properties", {})
			if p.has("m_OnClick"):
				_button_appearance(p, "Normal", true)
			if p.has("m_ShowMaskGraphic") and not bool(p.m_ShowMaskGraphic) and graphics.has(id):
				graphics[id].visible = false
			if p.has("m_MinValue") and sliders.has(id):
				var slider: Slider = sliders[id]
				slider.value_changed.connect(_slider_visuals.bind(p))
				slider.gui_input.connect(_slider_keyboard.bind(slider, p))
				slider.mouse_entered.connect(_button_appearance.bind(p, "Highlighted"))
				slider.mouse_exited.connect(_button_appearance.bind(p, "Normal"))
				slider.drag_started.connect(_button_appearance.bind(p, "Pressed"))
				slider.drag_ended.connect(_slider_drag_ended.bind(p))
				_slider_visuals(slider.value, p)
				_button_appearance(p, "Normal", true)
			if p.has("m_Content") and p.has("m_Viewport"):
				_install_scroll(target, p)

func _slider_drag_ended(_changed: bool, p: Dictionary) -> void:
	_button_appearance(p, "Highlighted")

func _slider_keyboard(event: InputEvent, slider: Slider, p: Dictionary) -> void:
	if not slider.editable:
		return
	var direction := int(p.get("m_Direction", 0))
	var forward := "ui_right" if direction < 2 else "ui_up"
	var backward := "ui_left" if direction < 2 else "ui_down"
	var change := 0
	if event.is_action_pressed(forward, true):
		change = 1
	elif event.is_action_pressed(backward, true):
		change = -1
	if change != 0:
		if direction == 1 or direction == 3:
			change = -change
		# Unity Slider's continuous keyboard step is a tenth of its range.
		var step := 1.0 if bool(p.get("m_WholeNumbers", false)) else (slider.max_value - slider.min_value) * 0.1
		slider.value += change * step
		slider.accept_event()

func _slider_visuals(value: float, p: Dictionary) -> void:
	var extent := float(p.get("m_MaxValue", 1)) - float(p.get("m_MinValue", 0))
	var ratio := (value - float(p.get("m_MinValue", 0))) / extent if extent != 0 else 0.0
	var direction := int(p.get("m_Direction", 0))
	var reversed := direction == 1 or direction == 2
	var first := SIDE_LEFT if direction < 2 else SIDE_TOP
	var last := SIDE_RIGHT if direction < 2 else SIDE_BOTTOM
	var handle := node(p.get("m_HandleRect", {})) as Control
	if handle != null:
		var anchor := 1.0 - ratio if reversed else ratio
		handle.set_anchor(first, anchor, true)
		handle.set_anchor(last, anchor, true)
	var fill := node(p.get("m_FillRect", {})) as Control
	if fill != null:
		fill.set_anchor(first, 1.0 - ratio if reversed else 0.0, true)
		fill.set_anchor(last, 1.0 if reversed else ratio, true)

func _install_scroll(target: Control, p: Dictionary) -> void:
	var viewport_control := node(p.m_Viewport) as Control
	var content := node(p.m_Content) as Control
	if viewport_control == null or content == null:
		return
	viewport_control.clip_contents = true
	var scroll := viewport_control.get_node_or_null("NativeScroll") as ScrollContainer
	if scroll == null:
		scroll = ScrollContainer.new()
		scroll.name = "NativeScroll"
		viewport_control.add_child(scroll)
		scroll.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		scroll.add_theme_stylebox_override("panel", StyleBoxEmpty.new())
		scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_SHOW_NEVER if bool(p.get("m_Horizontal", false)) else ScrollContainer.SCROLL_MODE_DISABLED
		scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_SHOW_NEVER if bool(p.get("m_Vertical", true)) else ScrollContainer.SCROLL_MODE_DISABLED
		var body := Control.new()
		body.name = "ContentBounds"
		body.mouse_filter = Control.MOUSE_FILTER_IGNORE
		body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		scroll.add_child(body)
		content.reparent(body, false)
	var state := {"target": target, "viewport": viewport_control, "content": content, "scroll": scroll, "p": p, "updating": false, "drag": false, "touch": -1}
	_scroll_states[component_owner(p.m_Content)] = state
	scroll.gui_input.connect(_scroll_input.bind(state))
	target.resized.connect(_refresh_scroll.bind(state))
	var label: Label = texts.get(component_owner(p.m_Content))
	if label != null:
		label.minimum_size_changed.connect(_refresh_scroll.bind(state))
	for axis in 2:
		var bar := node(p.get("m_HorizontalScrollbar" if axis == 0 else "m_VerticalScrollbar", {})) as Control
		if bar != null:
			bar.mouse_filter = Control.MOUSE_FILTER_STOP
			bar.focus_mode = Control.FOCUS_ALL
			bar.gui_input.connect(_scrollbar_input.bind(state, axis))
		var native_bar: ScrollBar = scroll.get_h_scroll_bar() if axis == 0 else scroll.get_v_scroll_bar()
		native_bar.value_changed.connect(_scroll_value_changed.bind(state))
		native_bar.changed.connect(_scroll_range_changed.bind(state))
	_refresh_scroll(state)

func _refresh_scroll(state: Dictionary) -> void:
	if state.updating:
		return
	state.updating = true
	var target: Control = state.target
	var viewport_control: Control = state.viewport
	var content: Control = state.content
	var scroll: ScrollContainer = state.scroll
	var p: Dictionary = state.p
	var body := scroll.get_node("ContentBounds") as Control
	var content_id := component_owner(p.m_Content)
	var rect: Dictionary = object(str(scene.game_objects[content_id].transform_id)).get("properties", {})
	var size_delta := _vector(rect.get("m_SizeDelta", {}))
	var anchored := _vector(rect.get("m_AnchoredPosition", {}))
	var label: Label = texts.get(content_id)
	# ScrollRect starts at full size, then reserves only the auto-expanded
	# bars that are actually needed. Its serialized -17 offsets are not fixed.
	var available := target.size
	var needed := [false, false]
	for _pass_index in 2:
		content.set_anchors_preset(Control.PRESET_TOP_LEFT)
		content.position = Vector2(anchored.x, -anchored.y)
		content.size.x = available.x + size_delta.x
		if label != null:
			label.size.x = content.size.x
		var preferred_height := available.y + size_delta.y
		for component in components(content_id):
			var fit: Dictionary = component.get("properties", {})
			if int(fit.get("m_VerticalFit", 0)) == 2 and label != null:
				preferred_height = label.get_minimum_size().y
		content.size.y = preferred_height
		needed = [bool(p.get("m_Horizontal", false)) and content.size.x > available.x, bool(p.get("m_Vertical", true)) and content.size.y > available.y]
		available = target.size
		for axis in 2:
			var key := "m_HorizontalScrollbar" if axis == 0 else "m_VerticalScrollbar"
			var bar := node(p.get(key, {})) as Control
			if bar == null:
				continue
			var visibility := int(p.get(key + "Visibility", 0))
			bar.visible = visibility == 0 or needed[axis]
			if visibility == 2 and needed[axis]:
				available[1 - axis] -= bar.size[1 - axis] + float(p.get(key + "Spacing", 0))
	viewport_control.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	viewport_control.offset_right = available.x - target.size.x
	viewport_control.offset_bottom = available.y - target.size.y
	body.custom_minimum_size = Vector2(maxf(available.x, content.size.x), maxf(0, content.size.y))
	body.size = Vector2(maxf(available.x, content.size.x), maxf(available.y, content.size.y))
	for axis in 2:
		var bar := node(p.get("m_HorizontalScrollbar" if axis == 0 else "m_VerticalScrollbar", {})) as Control
		if bar != null:
			if axis == 0:
				bar.offset_right = available.x - target.size.x
			else:
				bar.offset_bottom = available.y - target.size.y
	state.updating = false
	_scroll_value_changed(0, state)

func _scroll_range_changed(state: Dictionary) -> void:
	_scroll_value_changed(0, state)

func _scroll_value_changed(_value: float, state: Dictionary) -> void:
	var scroll: ScrollContainer = state.scroll
	for axis in 2:
		var p: Dictionary = state.p
		var bar_id := component_owner(p.get("m_HorizontalScrollbar" if axis == 0 else "m_VerticalScrollbar", {}))
		var native_bar: ScrollBar = scroll.get_h_scroll_bar() if axis == 0 else scroll.get_v_scroll_bar()
		for component in components(bar_id):
			var bar_properties: Dictionary = component.get("properties", {})
			if not bar_properties.has("m_HandleRect"):
				continue
			_button_appearance(bar_properties, "Normal", true)
			var handle := node(bar_properties.m_HandleRect) as Control
			if handle == null:
				continue
			var fraction := minf(1, native_bar.page / native_bar.max_value) if native_bar.max_value > 0 else 1.0
			var start: float = native_bar.value / native_bar.max_value if native_bar.max_value > 0 else 0.0
			handle.set_anchor(SIDE_LEFT if axis == 0 else SIDE_TOP, start, true)
			handle.set_anchor(SIDE_RIGHT if axis == 0 else SIDE_BOTTOM, start + fraction, true)

func _scroll_input(event: InputEvent, state: Dictionary) -> void:
	var scroll: ScrollContainer = state.scroll
	# Touch also emits emulated mouse input; only the real pointer may drag.
	if state.touch >= 0 and (event is InputEventMouseMotion or event is InputEventMouseButton):
		scroll.accept_event()
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		state.drag = event.pressed
		scroll.accept_event()
	elif event is InputEventMouseMotion and state.drag:
		_drag_scroll(event.relative, state)
	elif event is InputEventScreenTouch:
		state.touch = event.index if event.pressed else -1
		scroll.accept_event()
	elif event is InputEventScreenDrag and event.index == state.touch:
		_drag_scroll(event.relative, state)
	if event is InputEventMouseButton and event.pressed and event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
		var axis := 1 if bool(state.p.get("m_Vertical", true)) else 0
		var bar: ScrollBar = scroll.get_v_scroll_bar() if axis == 1 else scroll.get_h_scroll_bar()
		var direction := -1.0 if event.button_index == MOUSE_BUTTON_WHEEL_UP else 1.0
		bar.value += direction * float(state.p.get("m_ScrollSensitivity", 1))
		scroll.accept_event()

func _drag_scroll(relative: Vector2, state: Dictionary) -> void:
	var scroll: ScrollContainer = state.scroll
	if bool(state.p.get("m_Horizontal", false)):
		scroll.scroll_horizontal -= roundi(relative.x)
	if bool(state.p.get("m_Vertical", true)):
		scroll.scroll_vertical -= roundi(relative.y)
	scroll.accept_event()

func _scrollbar_input(event: InputEvent, state: Dictionary, axis: int) -> void:
	var source_bar := node(state.p.get("m_HorizontalScrollbar" if axis == 0 else "m_VerticalScrollbar", {})) as Control
	var scroll: ScrollContainer = state.scroll
	var native_bar: ScrollBar = scroll.get_h_scroll_bar() if axis == 0 else scroll.get_v_scroll_bar()
	var position := Vector2.ZERO
	var begin := false
	var move := false
	var drag_key := "bar_drag_" + str(axis)
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		begin = event.pressed
		if not event.pressed:
			state.erase(drag_key)
		position = event.position
	elif event is InputEventMouseMotion and state.has(drag_key):
		move = true
		position = event.position
	elif event is InputEventScreenTouch:
		begin = event.pressed
		if not event.pressed:
			state.erase(drag_key)
		position = event.position
	elif event is InputEventScreenDrag and state.has(drag_key):
		move = true
		position = event.position
	elif event is InputEventKey and event.pressed:
		if event.keycode in [KEY_UP, KEY_LEFT]:
			native_bar.value -= native_bar.step
		elif event.keycode in [KEY_DOWN, KEY_RIGHT]:
			native_bar.value += native_bar.step
		source_bar.accept_event()
	if begin:
		for component in components(component_owner(state.p.get("m_HorizontalScrollbar" if axis == 0 else "m_VerticalScrollbar", {}))):
			var p: Dictionary = component.get("properties", {})
			if not p.has("m_HandleRect"):
				continue
			var handle := node(p.m_HandleRect) as Control
			if handle == null:
				continue
			var handle_position := source_bar.get_global_transform().affine_inverse() * handle.global_position
			if position[axis] >= handle_position[axis] and position[axis] <= handle_position[axis] + handle.size[axis]:
				var fraction: float = native_bar.page / native_bar.max_value if native_bar.max_value > 0 else 1.0
				var travel: float = (handle.get_parent() as Control).size[axis] * (1.0 - fraction)
				state[drag_key] = {"position": position[axis], "value": native_bar.value, "travel": travel}
			else:
				native_bar.value += native_bar.page * (-1.0 if position[axis] < handle_position[axis] else 1.0)
		source_bar.grab_focus()
		source_bar.accept_event()
	elif move:
		var drag: Dictionary = state[drag_key]
		if float(drag.travel) > 0:
			native_bar.value = float(drag.value) + (position[axis] - float(drag.position)) / float(drag.travel) * maxf(0, native_bar.max_value - native_bar.page)
		source_bar.accept_event()

func _button_appearance(p: Dictionary, state: String, immediate: bool = false) -> void:
	var id := component_owner(p.get("m_TargetGraphic", {}))
	var graphic: CanvasItem = graphics.get(id, texts.get(id))
	if graphic == null:
		return
	if int(p.get("m_Transition", 1)) == 1:
		var colors: Dictionary = p.get("m_Colors", {})
		var color := _color(colors.get("m_" + state + "Color", {}))
		color *= float(colors.get("m_ColorMultiplier", 1))
		var duration := float(colors.get("m_FadeDuration", 0))
		if button_tweens.has(id) and button_tweens[id].is_valid():
			button_tweens[id].kill()
		if immediate or duration <= 0:
			graphic.modulate = color
		else:
			var tween := create_tween()
			tween.set_ignore_time_scale(true)
			tween.tween_property(graphic, "modulate", color, duration)
			button_tweens[id] = tween
	elif int(p.get("m_Transition", 1)) == 2 and graphic is TextureRect:
		var reference: Dictionary = p.get("m_SpriteState", {}).get("m_" + state + "Sprite", {})
		if reference_id(reference) != "0":
			graphic.texture = sprite(reference)

