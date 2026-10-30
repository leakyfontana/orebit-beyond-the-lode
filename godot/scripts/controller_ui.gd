class_name ControllerUI
extends Node

# Controller navigation uses the existing native Controls and their real signals.
# No synthetic mouse clicks, duplicate shop logic, or keyboard item aliases.
const ITEM_NAMES = PortPlayer.ITEM_NAMES
const REPEAT_DELAY := 0.38
const REPEAT_INTERVAL := 0.12

var ui: Node
var _controls: Array[Control] = []
var _original_focus: Dictionary = {}
var _candidates: Array[Control] = []
var _scope: Control
var _menu_open := false
var _direction := Vector2.ZERO
var _repeat_left := 0.0
var _hint: Label
var _hint_panel: PanelContainer
var _highlight: Panel
var _last_hint := ""

func configure(game_ui: Node) -> void:
	ui = game_ui
	process_mode = Node.PROCESS_MODE_ALWAYS
	_collect(ui.host.ui_root)
	var input := get_tree().get_first_node_in_group("game_input") as GameInput
	input.controller_event.connect(_controller_event)
	input.controller_connection_changed.connect(_connection_changed)
	_install_hint()

func _collect(node: Node) -> void:
	if node is BaseButton or node is Slider or node is ScrollContainer:
		var control := node as Control
		_controls.append(control)
		_original_focus[control] = control.focus_mode
	for child in node.get_children():
		_collect(child)

func _install_hint() -> void:
	_hint_panel = PanelContainer.new()
	_hint_panel.name = "ControllerConsumableHint"
	_hint_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ui.host.ui_root.add_child(_hint_panel)
	_hint = Label.new()
	_hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_hint.add_theme_font_size_override("font_size", 24)
	_hint.add_theme_color_override("font_color", Color.WHITE)
	_hint.add_theme_color_override("font_shadow_color", Color.BLACK)
	_hint.add_theme_constant_override("shadow_offset_x", 2)
	_hint.add_theme_constant_override("shadow_offset_y", 2)
	_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_hint_panel.add_child(_hint)
	var background := StyleBoxFlat.new()
	background.bg_color = Color(0.025, 0.035, 0.05, 0.92)
	background.content_margin_left = 16
	background.content_margin_right = 16
	background.content_margin_top = 8
	background.content_margin_bottom = 8
	_hint_panel.add_theme_stylebox_override("panel", background)
	_highlight = Panel.new()
	_highlight.name = "ControllerFocus"
	_highlight.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_highlight.z_index = 4095
	var outline := StyleBoxFlat.new()
	outline.bg_color = Color(0, 0, 0, 0)
	outline.border_color = Color(1, 0.85, 0.2)
	outline.set_border_width_all(4)
	_highlight.add_theme_stylebox_override("panel", outline)
	ui.host.ui_root.add_child(_highlight)

func sync_state(delta: float = 0.0) -> void:
	var gameplay: bool = ui.host.scene_name == "Game" and ui.host.player_alive and not ui.host.paused and ui.host.pending_scene.is_empty() and not get_tree().paused
	GameInput.set_gameplay_available(gameplay)
	_menu_open = not gameplay
	var next_scope := _active_scope()
	var scope_changed := next_scope != _scope
	_scope = next_scope
	_candidates.clear()
	for control in _controls:
		var eligible: bool = _menu_open and control.is_visible_in_tree() and (_scope == control or _scope.is_ancestor_of(control))
		if control is BaseButton:
			eligible = eligible and not control.disabled
		elif control is Slider:
			eligible = eligible and control.editable
		if eligible:
			_candidates.append(control)
		if GameInput.controller_active:
			control.focus_mode = Control.FOCUS_ALL if eligible else Control.FOCUS_NONE
		else:
			control.focus_mode = _original_focus[control]
	var focused := get_viewport().gui_get_focus_owner()
	if GameInput.controller_active and _menu_open:
		if scope_changed or focused == null or not _candidates.has(focused):
			_focus_first()
	elif focused != null and (not focused.is_visible_in_tree() or (GameInput.controller_active and not _menu_open)):
		focused.release_focus()
	if scope_changed:
		_direction = Vector2.ZERO
		_repeat_left = REPEAT_DELAY
	if GameInput.controller_active and _menu_open:
		var direction := GameInput.controller_direction()
		if direction == Vector2.ZERO:
			_direction = Vector2.ZERO
		elif direction != _direction:
			_direction = direction
			_repeat_left = REPEAT_DELAY
			_navigate(direction)
		else:
			_repeat_left -= delta
			if _repeat_left <= 0.0:
				_repeat_left = REPEAT_INTERVAL
				_navigate(direction)
	_update_hint(gameplay)
	_update_highlight()

func _active_scope() -> Control:
	# A popup or help overlay owns focus, not the still-visible menu behind it.
	for script in ["PopupManager", "HelpUUIManager"]:
		for id in ui.script_components.get(script, []):
			var panel := ui.bridge.node(id) as Control
			if panel != null and panel.is_visible_in_tree():
				return panel
	for script in ui.PANEL_SCRIPTS:
		if ui.script_components.has(script):
			var panel := ui.bridge.node(ui._panel(script)) as Control
			if panel != null and panel.is_visible_in_tree():
				return panel
	return ui.host.ui_root as Control

func _focus_first() -> void:
	var focused := get_viewport().gui_get_focus_owner()
	if focused != null:
		focused.release_focus()
	if not _candidates.is_empty():
		_candidates[0].grab_focus()

func _controller_event(event: InputEvent) -> void:
	sync_state()
	if not (event is InputEventJoypadButton) or not event.pressed:
		return
	if event.is_action_pressed(&"controller_back"):
		_close_current()
	elif event.is_action_pressed(&"controller_pause"):
		if _menu_open:
			_close_current()
		else:
			ui.open_options()
	elif event.is_action_pressed(&"controller_inventory"):
		if not _menu_open:
			ui.open_inventory()
	elif event.is_action_pressed(&"controller_accept"):
		if _menu_open:
			var focused := get_viewport().gui_get_focus_owner()
			if focused is BaseButton and _candidates.has(focused) and not focused.disabled:
				focused.pressed.emit()
			elif focused is ScrollContainer:
				_focus_next(focused, 1)
	elif not _menu_open:
		if event.is_action_pressed(&"controller_previous"):
			GameInput.selected_consumable = posmod(GameInput.selected_consumable - 1, ITEM_NAMES.size())
		elif event.is_action_pressed(&"controller_next"):
			GameInput.selected_consumable = posmod(GameInput.selected_consumable + 1, ITEM_NAMES.size())
		elif event.is_action_pressed(&"controller_use") and ui.host.player != null:
			ui.host.player.use_item(GameInput.selected_consumable)
	sync_state()

func _close_current() -> void:
	for id in ui.script_components.get("PopupManager", []):
		if ui._visible(id):
			ui.bridge.set_active(id, false)
			return
	if ui.script_components.has("MainMenuManager"):
		var help: Variant = ui._properties("MainMenuManager").get("helpUI", {})
		if ui._visible(help):
			ui.closeInstructions()
		return
	for script in ui.PANEL_SCRIPTS:
		if ui.script_components.has(script) and ui._visible(ui._panel(script)):
			ui._close_panel(script)
			return

func _navigate(direction: Vector2) -> void:
	var focused := get_viewport().gui_get_focus_owner()
	if focused == null or not _candidates.has(focused):
		_focus_first()
		return
	# Left/right adjust native sliders; up/down still leave the slider.
	if focused is Slider and direction.x != 0.0:
		var step := maxf(focused.step, (focused.max_value - focused.min_value) * 0.1)
		focused.value += direction.x * step
		return
	# A leaves a focused scroll region even when both axes scroll.
	if focused is ScrollContainer:
		if direction.y != 0.0 and focused.vertical_scroll_mode != ScrollContainer.SCROLL_MODE_DISABLED:
			focused.scroll_vertical -= int(direction.y * 80)
			return
		if direction.x != 0.0 and focused.horizontal_scroll_mode != ScrollContainer.SCROLL_MODE_DISABLED:
			focused.scroll_horizontal += int(direction.x * 80)
			return
	var axis := Vector2(direction.x, 0) if direction.x != 0.0 else Vector2(0, -direction.y)
	var origin: Vector2 = focused.get_global_rect().get_center()
	var best: Control
	var best_score := INF
	for candidate in _candidates:
		if candidate == focused:
			continue
		var offset := candidate.get_global_rect().get_center() - origin
		var forward := offset.dot(axis)
		if forward <= 1.0:
			continue
		var across := absf(offset.cross(axis))
		var score := forward + across * 3.0
		if score < best_score:
			best_score = score
			best = candidate
	if best != null:
		best.grab_focus()
	else:
		_focus_next(focused, 1 if axis.x + axis.y > 0.0 else -1)
	var selected := get_viewport().gui_get_focus_owner()
	if selected != null:
		var ancestor := selected.get_parent()
		while ancestor != null:
			if ancestor is ScrollContainer:
				ancestor.ensure_control_visible(selected)
			ancestor = ancestor.get_parent()

func _focus_next(focused: Control, offset: int) -> void:
	if not _candidates.is_empty():
		_candidates[posmod(_candidates.find(focused) + offset, _candidates.size())].grab_focus()

func _update_hint(gameplay: bool) -> void:
	_hint_panel.visible = GameInput.controller_active and gameplay
	if not _hint_panel.visible:
		return
	var name: String = ITEM_NAMES[GameInput.selected_consumable]
	var count := int(ui.data.player_items.get(name, 0))
	var text := "LB / RB   %s  ×%d   [X] Use     [Y] Inventory   [Start] Options" % [name, count]
	if text != _last_hint:
		_hint.text = text
		_last_hint = text
	var safe := Rect2(Vector2.ZERO, ui.host.ui_root.size)
	if is_instance_valid(ui.host.touch_controls):
		var touch_safe: Rect2 = ui.host.touch_controls.get_hud_safe_rect()
		if touch_safe.has_area():
			safe = touch_safe
	var minimum := _hint_panel.get_combined_minimum_size()
	var fit := minf(1.0, safe.size.x / maxf(minimum.x, 1.0))
	_hint_panel.scale = Vector2.ONE * fit
	_hint_panel.size = minimum
	_hint_panel.position = Vector2(safe.get_center().x - minimum.x * fit * 0.5, safe.end.y - minimum.y * fit - 12)
	var boss_health: Control = ui._boss_health
	if is_instance_valid(boss_health) and boss_health.is_visible_in_tree():
		var to_ui: Transform2D = ui.host.ui_root.get_global_transform_with_canvas().affine_inverse()
		var boss_rect: Rect2 = (to_ui * boss_health.get_global_transform_with_canvas()) * Rect2(Vector2.ZERO, boss_health.size)
		if Rect2(_hint_panel.position, minimum * fit).intersects(boss_rect):
			_hint_panel.position.y = boss_rect.position.y - minimum.y * fit - 12

func _update_highlight() -> void:
	var focused := get_viewport().gui_get_focus_owner()
	_highlight.visible = GameInput.controller_active and _menu_open and focused != null and _candidates.has(focused)
	if _highlight.visible:
		var rect: Rect2 = ui.host.ui_root.get_global_transform().affine_inverse() * focused.get_global_rect()
		_highlight.position = rect.position - Vector2.ONE * 4
		_highlight.size = rect.size + Vector2.ONE * 8

func _connection_changed() -> void:
	_direction = Vector2.ZERO
	_repeat_left = REPEAT_DELAY
	sync_state()

func _exit_tree() -> void:
	GameInput.set_gameplay_available(false)
	if is_instance_valid(_hint_panel):
		_hint_panel.queue_free()
	if is_instance_valid(_highlight):
		_highlight.queue_free()
