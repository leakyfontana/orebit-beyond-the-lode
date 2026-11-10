class_name CoopLobby
extends CanvasLayer

enum Visibility { MODAL, HUD }
enum Page { MODE, LOBBY, PASSWORD, SERVER }
enum PauseReturn { RUNNING, PAUSED }
enum ConnectionAdmission { OFFLINE, CONNECTING, CONNECTED }
enum Account { ANONYMOUS, AUTHENTICATED }
enum AuthKind { LOGIN, SIGNUP }

const ACCENT := Color("4fd348")
const INK := Color("091307")
const TEXT := Color("dcedd4")
const MUTED := Color("a4ba97")
const TARGET_SIZE := 48.0
const MENU_ROW_HEIGHT := 44.0

var host: Node
var client: CoopClient
var visibility: Visibility = Visibility.MODAL
var modal: bool:
	get:
		return visibility == Visibility.MODAL
	set(value):
		visibility = Visibility.MODAL if value else Visibility.HUD
var _pause_return: PauseReturn = PauseReturn.RUNNING
var _root: Control
var _shade: ColorRect
var _panel: PanelContainer
var _scroll: ScrollContainer
var _body: VBoxContainer
var _status: Label
var _identity: Label
var _url: LineEdit
var _username: LineEdit
var _password: LineEdit
var _password_reveal: Button
var _auth_heading: Label
var _auth_submit: Button
var _auth_toggle: Button
var _cancel_button: Button
var _page_navigation: HBoxContainer
var _hud: VBoxContainer
var _hud_label: Label
var _menu_font: Font
var _hud_scene := ""
var _header_ink_rects: Dictionary = {}
var _header_source_root: Control
var _header_offsets: Dictionary = {}
var _message := ""
var _page: Page = Page.MODE
var _auth_kind: AuthKind = AuthKind.LOGIN
var _username_draft := ""
var _lobby_state := ""
var _actions: Array[Button] = []
var _fields: Array[LineEdit] = []
var _focus_controls: Array[Control] = []
var _direction := 0
var _repeat_left := 0.0
var _web_window: JavaScriptObject
var _web_viewport: JavaScriptObject
var _web_resize_callback: JavaScriptObject

var leaderboard: PvpLeaderboard
func configure(main_host: Node, network: CoopClient) -> void:
	host = main_host
	client = network
	layer = 110
	process_mode = Node.PROCESS_MODE_ALWAYS
	_root = Control.new()
	_root.name = "AuthViewport"
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var auth_theme := Theme.new()
	var auth_font := load("res://assets/TextMesh Pro/Fonts/LiberationSans.ttf").duplicate() as FontFile
	auth_font.multichannel_signed_distance_field = true
	auth_theme.default_font = auth_font
	_root.theme = auth_theme
	# Reuse the native Arial Black atlas used by NEW GAME / CONTINUE GAME.
	_menu_font = load(str(host.manifest.native_font_paths["cf2bfdd882792dd47b13907720f8ab17"])) as Font
	add_child(_root)
	_shade = ColorRect.new()
	_shade.color = Color(0.015, 0.025, 0.012, 0.96)
	_shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_root.add_child(_shade)
	_panel = PanelContainer.new()
	_panel.name = "AuthPanel"
	var panel_style := _surface(Color("101b0e"), Color("426539"), 4)
	for side in ["left", "right", "top", "bottom"]:
		panel_style.set("content_margin_" + side, 0.0)
	_panel.add_theme_stylebox_override("panel", panel_style)
	_root.add_child(_panel)
	var margin := MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 12)
	_panel.add_child(margin)
	_scroll = ScrollContainer.new()
	_scroll.name = "AuthScroll"
	_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_scroll.follow_focus = true
	_scroll.scroll_deadzone = 12
	_scroll.add_theme_stylebox_override("panel", StyleBoxEmpty.new())
	margin.add_child(_scroll)
	_body = VBoxContainer.new()
	_body.name = "AuthPage"
	_body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_body.add_theme_constant_override("separation", 6)
	_scroll.add_child(_body)
	_body.minimum_size_changed.connect(_resize, CONNECT_DEFERRED)
	_hud = VBoxContainer.new()
	_hud.name = "CoopAccountHUD"
	_hud.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_hud.add_theme_constant_override("separation", 4)
	_root.add_child(_hud)
	_hud_label = Label.new()
	_hud_label.name = "CoopHeaderStatus"
	_hud_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_hud_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
	_hud_label.autowrap_mode = TextServer.AUTOWRAP_OFF
	_hud_label.add_theme_font_size_override("font_size", 12)
	_hud_label.add_theme_color_override("font_color", TEXT)
	_hud_label.add_theme_color_override("font_shadow_color", Color.BLACK)
	_hud_label.add_theme_constant_override("shadow_offset_x", 1)
	_hud_label.add_theme_constant_override("shadow_offset_y", 1)
	_root.add_child(_hud_label)
	_hud.visibility_changed.connect(func(): _hud_label.visible = _hud.visible)
	_hud_label.minimum_size_changed.connect(_resize, CONNECT_DEFERRED)
	var account := Button.new()
	account.name = "GameModesAccount"
	account.text = "MODES\nACCOUNTS"
	account.tooltip_text = "Choose game mode or manage your server account"
	_style_button(account, false)
	account.autowrap_mode = TextServer.AUTOWRAP_OFF
	account.add_theme_font_size_override("font_size", 13)
	account.add_theme_color_override("font_shadow_color", Color.BLACK)
	account.add_theme_color_override("font_focus_color", Color.WHITE)
	account.add_theme_constant_override("shadow_offset_x", 1)
	account.add_theme_constant_override("shadow_offset_y", 2)
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		account.add_theme_stylebox_override(state, StyleBoxEmpty.new())
	var account_icon := TextureRect.new()
	account_icon.name = "AccountIcon"
	account_icon.texture = preload("res://assets/coop_account.svg")
	account_icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	account_icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	account_icon.mouse_filter = Control.MOUSE_FILTER_IGNORE
	account_icon.show_behind_parent = true
	account_icon.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	account.add_child(account_icon)
	account.mouse_filter = Control.MOUSE_FILTER_STOP
	account.pressed.connect(_open_modes)
	_hud.add_child(account)
	_hud.minimum_size_changed.connect(_resize, CONNECT_DEFERRED)
	leaderboard = PvpLeaderboard.new()
	_root.add_child(leaderboard)
	leaderboard.configure(self)
	client.status_changed.connect(_set_status)
	client.identity_changed.connect(_refresh_identity)
	client.auth_state_changed.connect(_auth_state_changed)
	get_viewport().size_changed.connect(_resize)
	var input := get_tree().get_first_node_in_group("game_input") as GameInput
	if input != null:
		input.controller_event.connect(_controller_event)
	if OS.has_feature("web"):
		_web_window = JavaScriptBridge.get_interface("window")
		_web_viewport = _web_window.visualViewport
		_web_resize_callback = JavaScriptBridge.create_callback(_web_resized)
		_web_window.addEventListener("resize", _web_resize_callback)
		if _web_viewport != null:
			_web_viewport.addEventListener("resize", _web_resize_callback)
			_web_viewport.addEventListener("scroll", _web_resize_callback)
	show_mode()

func _surface(background: Color, border: Color, radius: int = 3) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = background
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(radius)
	style.content_margin_left = 10
	style.content_margin_right = 10
	style.content_margin_top = 8
	style.content_margin_bottom = 8
	return style

func _style_button(button: Button, primary: bool) -> void:
	button.custom_minimum_size = Vector2(TARGET_SIZE, TARGET_SIZE)
	button.add_theme_font_size_override("font_size", 15)
	button.add_theme_font_override("font", _menu_font)
	button.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	button.add_theme_color_override("font_color", ACCENT)
	button.add_theme_color_override("font_hover_color", TEXT)
	button.add_theme_color_override("font_pressed_color", TEXT)
	button.add_theme_color_override("font_disabled_color", Color("718168"))
	# The landing buttons use green type with dark-green hover/pressed fills.
	button.add_theme_stylebox_override("normal", _surface(Color("162c10") if primary else Color(0.03, 0.07, 0.02, 0.82), ACCENT if primary else Color("426539")))
	button.add_theme_stylebox_override("hover", _surface(Color(0.1424814, 0.4528302, 0.1260235, 0.95), ACCENT))
	button.add_theme_stylebox_override("pressed", _surface(Color("113f0f"), ACCENT))
	button.add_theme_stylebox_override("disabled", _surface(Color("172014"), Color("35472e")))
	var focus := _surface(Color(0, 0, 0, 0), ACCENT)
	focus.set_border_width_all(3)
	button.add_theme_stylebox_override("focus", focus)

func _resize() -> void:
	if not is_instance_valid(_root):
		return
	var viewport_size := get_viewport().get_visible_rect().size
	var screen_scale := get_viewport().get_screen_transform().get_scale().abs()
	var pixels := viewport_size * screen_scale
	var available := Rect2(Vector2.ZERO, pixels)
	if OS.has_feature("web"):
		# Canvas backing pixels can include DPR. Layout uses CSS pixels, not the
		# game's stretched 1920x1080 units, including Safari's visual viewport.
		var metrics: Variant = JSON.parse_string(str(JavaScriptBridge.eval("JSON.stringify((()=>{const c=document.querySelector('canvas');if(!c)return null;const r=c.getBoundingClientRect(),v=window.visualViewport;const x=v?v.offsetLeft:0,y=v?v.offsetTop:0,w=v?v.width:innerWidth,h=v?v.height:innerHeight;return {w:r.width,h:r.height,x:Math.max(0,x-r.left),y:Math.max(0,y-r.top),right:Math.min(r.width,x+w-r.left),bottom:Math.min(r.height,y+h-r.top)}})())")))
		if metrics is Dictionary and float(metrics.get("w", 0)) > 0 and float(metrics.get("h", 0)) > 0:
			pixels = Vector2(float(metrics.w), float(metrics.h))
			available = Rect2(Vector2(float(metrics.x), float(metrics.y)), Vector2(maxf(1, float(metrics.right) - float(metrics.x)), maxf(1, float(metrics.bottom) - float(metrics.y))))
	else:
		var density := maxf(1.0, DisplayServer.screen_get_scale())
		if OS.get_name() == "Android":
			# Godot's Android scale is capped to its default game viewport.
			# Density DPI preserves actual dp-sized controls on short screens.
			density = maxf(1.0, DisplayServer.screen_get_dpi() / 160.0)
		elif OS.get_name() == "Windows":
			density = maxf(1.0, DisplayServer.screen_get_dpi() / 96.0)
		pixels /= density
		available = Rect2(Vector2.ZERO, pixels)
		if OS.has_feature("mobile"):
			var safe := DisplayServer.get_display_safe_area()
			if safe.has_area():
				var viewport_from_screen := get_viewport().get_screen_transform().affine_inverse()
				var local_safe: Rect2 = viewport_from_screen * Rect2(safe)
				available = available.intersection(Rect2(local_safe.position * screen_scale / density, local_safe.size * screen_scale / density))
	if pixels.x <= 0 or pixels.y <= 0 or not available.has_area():
		return
	# Cancel game stretch for this tree only; use CSS pixels on Web and
	# density-independent screen units natively, including Retina/Android.
	_root.scale = viewport_size / pixels
	_root.size = pixels
	var gutter := 12.0
	var panel_size := Vector2(minf(480, available.size.x - gutter * 2), minf(740, available.size.y - gutter * 2))
	panel_size.y = minf(panel_size.y, maxf(128, _body.get_combined_minimum_size().y + 24))
	panel_size = panel_size.max(Vector2.ONE)
	_panel.position = available.position + (available.size - panel_size) * 0.5
	_panel.size = panel_size
	_layout_hud(available, gutter)
	leaderboard.layout(available, _leaderboard_center, _leaderboard_size)

func _header_rect(control: Control) -> Rect2:
	var transform := _root.get_global_transform_with_canvas().affine_inverse() * control.get_global_transform_with_canvas()
	return transform * Rect2(Vector2.ZERO, control.size)

func _header_art_rect(control: Control) -> Rect2:
	var bounds := _header_rect(control)
	for child in control.get_children():
		if child is TextureRect:
			var texture: Texture2D = child.texture
			if not _header_ink_rects.has(texture):
				# Read the original icon's transparent padding only once per texture.
				var image := texture.get_image()
				var used := image.get_used_rect()
				var pixels := Vector2(image.get_size())
				_header_ink_rects[texture] = Rect2(Vector2(used.position) / pixels, Vector2(used.size) / pixels)
			var ink: Rect2 = _header_ink_rects[texture]
			return Rect2(bounds.position + ink.position * bounds.size, ink.size * bounds.size)
	return bounds

func _restore_header_controls(controls: Array[Control]) -> void:
	if _header_source_root != host.ui_root:
		_header_source_root = host.ui_root
		_header_offsets.clear()
	for control in controls:
		if not _header_offsets.has(control):
			# Anchor offsets survive viewport resizing; derived positions do not.
			_header_offsets[control] = Vector2(control.offset_left, control.offset_right)
		var offsets: Vector2 = _header_offsets[control]
		control.offset_left = offsets.x
		control.offset_right = offsets.y

func _shift_header_controls(controls: Array[Control], horizontal: float) -> void:
	for control in controls:
		var nested := false
		for other in controls:
			if other != control and other.is_ancestor_of(control):
				nested = true
				break
		if not nested:
			var parent_from_header: Transform2D = control.get_parent().get_global_transform_with_canvas().affine_inverse() * _root.get_global_transform_with_canvas()
			control.position += parent_from_header.basis_xform(Vector2(horizontal, 0))

var _leaderboard_center := Vector2.ZERO
var _leaderboard_size := Vector2(48, 48)

func _layout_hud(available: Rect2, gutter: float) -> void:
	var artwork_size := Vector2(48, 48)
	var minimum_target := Vector2(maxf(TARGET_SIZE, _menu_font.get_string_size("ACCOUNTS", HORIZONTAL_ALIGNMENT_LEFT, -1, 8).x + 2), TARGET_SIZE)
	var target_size := artwork_size.max(minimum_target)
	var center := Vector2(available.end.x - gutter - TARGET_SIZE * 0.5, available.position.y + gutter + TARGET_SIZE * 0.5)
	var label_left := gutter
	var label_right := label_left + 88
	var label_center_y := center.y
	if host.scene_name == "Game" and is_instance_valid(host.ui_root):
		var icons: Array[Control] = []
		for control_name in ["InventoryButton", "HelpButton", "OptionsButton"]:
			var control := host.ui_root.find_child(control_name, true, false) as Control
			if control != null:
				icons.append(control)
		var gauges: Array[Control] = []
		var properties: Dictionary = host.ui._properties("UIManager")
		for key in ["HullUI", "FuelUI", "DepthUI", "low_fuel_text", "very_low_fuel_text"]:
			var control := host.bridge.node(properties.get(key, {})) as Control
			if control != null and not gauges.has(control):
				gauges.append(control)
		_restore_header_controls(icons + gauges)
		var inventory := host.ui_root.find_child("InventoryButton", true, false) as Control
		var help := host.ui_root.find_child("HelpButton", true, false) as Control
		if inventory != null and help != null:
			var inventory_art := _header_art_rect(inventory)
			var help_art := _header_art_rect(help)
			artwork_size = inventory_art.size
			target_size = artwork_size.max(minimum_target)
			var spacing := help_art.get_center().x - inventory_art.get_center().x
			center = Vector2(maxf(help_art.get_center().x + spacing, help_art.end.x + gutter * 0.5 + target_size.x * 0.5), inventory_art.get_center().y)
			_leaderboard_center = inventory_art.get_center() - Vector2(maxf(spacing, target_size.x + gutter * 0.5), 0)
			# Reserve the extra icon's slot instead of clamping it over Help.
			var overflow := maxf(0, center.x + target_size.x * 0.5 - (available.end.x - gutter))
			_shift_header_controls(icons, -overflow)
			center.x -= overflow
			_leaderboard_center.x -= overflow
		var hull := host.ui_root.find_child("HullUI", true, false) as Control
		if hull != null:
			var hull_bounds := _header_rect(hull)
			var label_width := _hud_label.get_theme_font("font").get_string_size(_hud_label.text, HORIZONTAL_ALIGNMENT_LEFT, -1, _hud_label.get_theme_font_size("font_size")).x
			# At 16:9 there is no authored left margin. Reserve one for the count
			# and move the whole gauge/depth/warning group together.
			var shift := maxf(0, label_left + label_width + gutter - hull_bounds.position.x)
			_shift_header_controls(gauges, shift)
			hull_bounds = _header_rect(hull)
			label_right = hull_bounds.position.x - gutter
			# Hull/Fuel captions are baked into their 147px-tall sprites, with
			# the text centered at source row 37 (not the full meter's center).
			label_center_y = hull_bounds.position.y + hull_bounds.size.y * (37.0 / 147.0)
	target_size = artwork_size.max(minimum_target)
	_leaderboard_size = target_size
	center.y = maxf(center.y, available.position.y + gutter + target_size.y * 0.5)
	var account := _hud.get_node("GameModesAccount") as Button
	var text_width := _menu_font.get_string_size("ACCOUNTS", HORIZONTAL_ALIGNMENT_LEFT, -1, 13).x
	account.add_theme_font_size_override("font_size", maxi(8, floori(13 * (target_size.x - 2) / text_width)))
	account.custom_minimum_size = target_size
	_hud.position = center - target_size * 0.5
	_hud.size = target_size
	var icon := account.get_node("AccountIcon") as TextureRect
	icon.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	icon.offset_left = -artwork_size.x * 0.5
	icon.offset_right = artwork_size.x * 0.5
	icon.offset_top = -artwork_size.y * 0.5
	icon.offset_bottom = artwork_size.y * 0.5
	_hud_label.size = Vector2(maxf(1, label_right - label_left), 0)
	_hud_label.size.y = _hud_label.get_combined_minimum_size().y
	_hud_label.position = Vector2(label_left, label_center_y - _hud_label.get_character_bounds(0).get_center().y)

func _web_resized(_arguments: Array) -> void:
	_resize.call_deferred()

func _exit_tree() -> void:
	if _web_window != null and _web_resize_callback != null:
		_web_window.removeEventListener("resize", _web_resize_callback)
		if _web_viewport != null:
			_web_viewport.removeEventListener("resize", _web_resize_callback)
			_web_viewport.removeEventListener("scroll", _web_resize_callback)

func _clear() -> void:
	for child in _body.get_children():
		_body.remove_child(child)
		child.queue_free()
	_status = null
	_identity = null
	_url = null
	_username = null
	_password = null
	_password_reveal = null
	_auth_heading = null
	_auth_submit = null
	_auth_toggle = null
	_cancel_button = null
	_page_navigation = null
	_actions.clear()
	_fields.clear()
	_focus_controls.clear()
	_scroll.scroll_vertical = 0

func _label(text: String, small: bool = false) -> Label:
	var label := Label.new()
	label.text = text
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", 13 if small else 20)
	label.add_theme_color_override("font_color", MUTED if small else TEXT)
	if not small:
		label.add_theme_font_override("font", _menu_font)
		label.add_theme_color_override("font_color", ACCENT)
	_body.add_child(label)
	return label

func _button(text: String, action: Callable, control_name: String, primary: bool = false, container: Container = null) -> Button:
	var button := Button.new()
	button.name = control_name
	button.text = text
	# A press on a button may become a drag in the enclosing ScrollContainer.
	button.mouse_filter = Control.MOUSE_FILTER_PASS
	_style_button(button, primary)
	button.custom_minimum_size = Vector2(MENU_ROW_HEIGHT, MENU_ROW_HEIGHT)
	button.pressed.connect(action)
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	if container == null:
		_body.add_child(button)
	else:
		container.add_child(button)
	_actions.append(button)
	_focus_controls.append(button)
	return button

func _row() -> HBoxContainer:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 6)
	_body.add_child(row)
	return row

func _field(label_text: String, value: String, control_name: String, secret: bool = false, container: Container = null) -> LineEdit:
	var field := LineEdit.new()
	field.name = control_name
	field.text = value
	field.secret = secret
	field.placeholder_text = label_text
	field.accessibility_name = label_text
	field.tooltip_text = label_text
	field.custom_minimum_size = Vector2(MENU_ROW_HEIGHT, MENU_ROW_HEIGHT)
	field.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	field.expand_to_text_length = false
	field.add_theme_font_size_override("font_size", 15)
	field.add_theme_color_override("font_color", TEXT)
	field.add_theme_color_override("font_uneditable_color", MUTED)
	field.add_theme_color_override("caret_color", ACCENT)
	field.add_theme_stylebox_override("normal", _surface(INK, Color("426539")))
	field.add_theme_stylebox_override("read_only", _surface(Color("172014"), Color("35472e")))
	var focus := _surface(Color(0, 0, 0, 0), ACCENT)
	focus.set_border_width_all(3)
	field.add_theme_stylebox_override("focus", focus)
	# Keep native editing, paste/context menu and virtual keyboard behavior.
	if container == null:
		_body.add_child(field)
	else:
		container.add_child(field)
	_fields.append(field)
	_focus_controls.append(field)
	return field

func _open_page(page: Page) -> void:
	leaderboard.close()
	if not modal:
		_pause_return = PauseReturn.PAUSED if host.paused else PauseReturn.RUNNING
	_page = page
	visibility = Visibility.MODAL
	host.paused = true
	_shade.show()
	_panel.show()
	_hud.hide()
	_clear()

func _finish_page() -> void:
	if _page_navigation == null:
		_page_navigation = _row()
	_cancel_button = _button("Cancel", _cancel_auth, "CancelAuth", false, _page_navigation)
	_actions.erase(_cancel_button)
	_status = _label("", true)
	_status.name = "AuthStatus"
	_auth_state_changed()
	_resize()
	_resize.call_deferred()
	if client.recovering:
		# Move keyboard focus off any underlying shop control as well.
		_focus_initial()
	elif GameInput.controller_active:
		_focus_initial.call_deferred()

func show_mode() -> void:
	_open_page(Page.MODE)
	_label("Choose mode")
	_label("Gameplay is recorded and uploaded for bot training. No chat, credentials or account IDs.", true)
	var choices := _row()
	_button("Private", _choose_private, "ChoosePrivate", true, choices)
	_button("Co-op", func(): _choose_server("coop"), "ChooseCoop", false, choices)
	_button("PvP", func(): _choose_server("pvp"), "ChoosePvp", false, choices)
	_label("PvP: first to $1M held cash wins; each win starts a new round.", true)
	_button("Vulcan", func(): _choose_server("vulcan"), "ChooseVulcan")
	_label("Experimental outpost · isolated accounts and worlds. Play solo or with other miners.", true)
	_finish_page()

func _choose_server(mode: String) -> void:
	if _busy() and not client.session_checking:
		return
	if (client.connected or client.recovering) and client.mode != mode:
		if not host.leave_coop():
			return
		host.change_scene("MainMenu")
	client.select_mode(mode)
	_message = ""
	show_lobby()

func show_lobby() -> void:
	_open_page(Page.LOBBY)
	_lobby_state = _state_key()
	_label("Vulcan" if client.mode == "vulcan" else ("PvP ($1M)" if client.mode == "pvp" else "Co-op"))
	if client.mode == "vulcan":
		_label("Drilling attracts Shai-Hulud; otherwise it roams randomly. Only its mouth kills miners; its body is safe to touch. Death loses cargo and items, but keeps your money. Respawn automatically on the surface.", true)
	_identity = _label("", true)
	_identity.name = "AccountIdentity"
	if client.recovering:
		_label("Restoring server-confirmed progress. Unconfirmed actions are not retried." + (" PvP continues." if client.mode == "pvp" else ""), true)
		_button("Leave", _leave, "LeaveServer", true)
		_button("Sign out", _sign_out, "SignOut")
	elif client.connected:
		_button("Resume", hide_lobby, "ReturnToWorld", true)
		_button("Leave", _leave, "LeaveServer")
	elif _account() == Account.AUTHENTICATED:
		_button("Join", _join, "JoinServer", true)
		_button("Sign out", _sign_out, "SignOut")
	else:
		_button("Discord sign-in", _discord_auth, "ContinueDiscord", true)
		_button("Username / password", _show_password, "UsePassword")
		_button("Guest (unsaved)", _join, "JoinAnonymous")
	_page_navigation = _row()
	if not client.connected:
		_button("Server", _show_server, "AdvancedServer", false, _page_navigation)
	_button("Modes", show_mode, "BackToModes", false, _page_navigation)
	_finish_page()

func _show_password() -> void:
	if _busy():
		return
	_open_page(Page.PASSWORD)
	_auth_heading = _label("")
	_username = _field("Username", _username_draft, "AuthUsername")
	_username.text_submitted.connect(func(_text: String): _password.grab_focus())
	var password_row := _row()
	_password = _field("Password", "", "AuthPassword", true, password_row)
	_password.placeholder_text = "Password (8+ characters)"
	_password.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_PASSWORD
	_password.text_submitted.connect(func(_text: String): _native_auth(_auth_wire_kind()))
	_password_reveal = _button("Show", _toggle_password, "RevealPassword", false, password_row)
	_password_reveal.toggle_mode = true
	_password_reveal.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_password_reveal.autowrap_mode = TextServer.AUTOWRAP_OFF
	_password_reveal.accessibility_name = "Show password"
	_password_reveal.tooltip_text = "Show password"
	_auth_submit = _button("", func(): _native_auth(_auth_wire_kind()), "SubmitPassword", true)
	_page_navigation = _row()
	_auth_toggle = _button("", _toggle_auth_kind, "SwitchPasswordMode", false, _page_navigation)
	_button("Back", show_lobby, "PasswordBack", false, _page_navigation)
	_update_password_mode()
	_finish_page()

func _update_password_mode() -> void:
	_auth_heading.text = "Sign in" if _auth_kind == AuthKind.LOGIN else "Create account"
	_auth_submit.text = "Sign in" if _auth_kind == AuthKind.LOGIN else "Create account"
	_auth_toggle.text = "Sign up" if _auth_kind == AuthKind.LOGIN else "Sign in"

func _toggle_auth_kind() -> void:
	if _busy():
		return
	_auth_kind = AuthKind.SIGNUP if _auth_kind == AuthKind.LOGIN else AuthKind.LOGIN
	_message = ""
	_update_password_mode()
	_update_status()

func _auth_wire_kind() -> String:
	return "login" if _auth_kind == AuthKind.LOGIN else "signup"

func _toggle_password() -> void:
	if is_instance_valid(_password):
		_password.secret = not _password.secret
		_password_reveal.set_pressed_no_signal(not _password.secret)
		_password_reveal.text = "Show" if _password.secret else "Hide"
		_password_reveal.accessibility_name = "Show password" if _password.secret else "Hide password"
		_password_reveal.tooltip_text = _password_reveal.accessibility_name

func _show_server() -> void:
	if _busy() or client.connected:
		return
	_open_page(Page.SERVER)
	_label("PvP server" if client.mode == "pvp" else "Co-op server")
	_label("Switching servers signs you out; progress stays on the old server.", true)
	_url = _field("Server HTTPS address", client.base_url, "ServerAddress")
	_url.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_URL
	_url.text_submitted.connect(func(_text: String): _save_server())
	_page_navigation = _row()
	_button("Save", _save_server, "SaveServer", true, _page_navigation)
	_button("Default", _default_server, "DefaultServer", false, _page_navigation)
	_button("Back", show_lobby, "ServerBack", false, _page_navigation)
	_finish_page()

func _default_server() -> void:
	if not _busy():
		_url.text = CoopClient.DEFAULT_URL

func _save_server() -> void:
	if _busy() or client.connected:
		return
	var endpoint := _url.text.strip_edges().trim_suffix("/")
	# Validate before set_endpoint: editing an invalid URL must not sign out.
	var local := RegEx.new()
	local.compile("^http://(127\\.0\\.0\\.1|localhost)(:[0-9]+)?(/|$)")
	if not endpoint.begins_with("https://") and local.search(endpoint) == null:
		_set_status("Use an HTTPS address. Localhost HTTP is supported for development.")
		return
	client.set_endpoint(endpoint)
	_message = "Server address saved."
	show_lobby()

func hide_lobby(reset_pause: bool = false) -> void:
	if client.recovering and not reset_pause:
		show_lobby()
		return
	if reset_pause:
		_message = ""
	visibility = Visibility.HUD
	_shade.hide()
	_panel.hide()
	host.paused = client.recovering or (false if reset_pause else _pause_return == PauseReturn.PAUSED)
	refresh_hud()

func refresh_hud() -> void:
	if not is_instance_valid(_hud_label):
		return
	leaderboard.refresh()
	var header_text := "%s · %d/5" % ["Vulcan" if client.mode == "vulcan" else ("PvP" if client.mode == "pvp" else "Co-op"), client.peers.size()] if host.is_coop else "Private"
	if client.recovering:
		header_text = "Reconnecting…"
	var needs_layout: bool = _hud_label.text != header_text or _hud_scene != host.scene_name or not _hud.visible
	_hud.visible = not modal and (host.is_coop or host.scene_name == "MainMenu")
	if _hud_label.text != header_text:
		_hud_label.text = header_text
	_hud_scene = host.scene_name
	if needs_layout and _hud.visible:
		_resize.call_deferred()

func _choose_private() -> void:
	if (_busy() and not client.session_checking) or not host.leave_coop():
		return
	if client.session_checking:
		client.cancel_auth(false)
	hide_lobby(true)
	host.change_scene("MainMenu")

func _back() -> void:
	if client.session_checking:
		client.cancel_auth(false)
	elif _busy():
		return
	if client.recovering and _page == Page.MODE:
		show_lobby()
		return
	if _page == Page.PASSWORD or _page == Page.SERVER:
		show_lobby()
	elif _page == Page.MODE or client.connected:
		hide_lobby()
	else:
		show_mode()

func _leave() -> void:
	if _busy() or not host.leave_coop():
		return
	host.change_scene("MainMenu")
	show_lobby()

func _join() -> void:
	if _busy() or client.connected or client.recovering:
		return
	if not client.endpoint_is_secure():
		_set_status("Use HTTPS in Server settings before joining.")
		return
	_message = "Connecting to the PvP round…" if client.mode == "pvp" else "Connecting to the shared world…"
	client.join_world()
	_auth_state_changed()

func _prepare_auth() -> bool:
	if _busy() or client.connected or client.recovering:
		return false
	if not client.endpoint_is_secure():
		_set_status("Use HTTPS in Server settings to protect your sign-in.")
		return false
	_message = ""
	return true

func _native_auth(kind: String) -> void:
	if not is_instance_valid(_password) or not _prepare_auth():
		return
	_username_draft = _username.text.strip_edges()
	var password := _password.text
	_password.text = ""
	client.authenticate(kind, _username_draft, password)
	_auth_state_changed()

func _discord_auth() -> void:
	if _prepare_auth():
		client.discord_login()
		_auth_state_changed()

func _cancel_auth() -> void:
	# Cancel only the in-flight authentication, never an unrelated valid session.
	if client.auth_busy or client.session_checking:
		client.cancel_auth()
		_message = "Sign-in cancelled."
		_auth_state_changed()

func _sign_out() -> void:
	if _busy() or client.connected:
		return
	if client.recovering:
		if not host.leave_coop():
			return
		host.change_scene("MainMenu")
	_message = ""
	client.logout()
	_message = "Signed out. You can sign in again or play anonymously."
	show_lobby()

func _busy() -> bool:
	return client.auth_busy or client.session_checking or (client.connecting and not client.recovering)

func _connection_admission() -> ConnectionAdmission:
	if client.connected:
		return ConnectionAdmission.CONNECTED
	if client.connecting:
		return ConnectionAdmission.CONNECTING
	return ConnectionAdmission.OFFLINE

func _account() -> Account:
	return Account.ANONYMOUS if client.token.is_empty() else Account.AUTHENTICATED

func _state_key() -> String:
	return str(_connection_admission() == ConnectionAdmission.CONNECTED) + ":" + str(client.recovering) + ":" + str(_account())

func _refresh_identity() -> void:
	_message = ""
	_auth_state_changed()
	refresh_hud()

func _auth_state_changed() -> void:
	if _page == Page.LOBBY and _lobby_state != _state_key():
		show_lobby()
		return
	if _page == Page.PASSWORD and _account() == Account.AUTHENTICATED and not client.auth_busy and not client.session_checking:
		show_lobby()
		return
	if is_instance_valid(_identity):
		_identity.text = client.username if _account() == Account.AUTHENTICATED else ("Guest" if client.connected else "")
		_identity.visible = not _identity.text.is_empty()
	for button in _actions:
		button.disabled = _busy() and not (_page == Page.MODE and client.session_checking)
	for field in _fields:
		field.editable = not _busy()
	if is_instance_valid(_cancel_button):
		_cancel_button.visible = client.auth_busy or client.session_checking
		_cancel_button.accessibility_name = "Cancel session check" if client.session_checking else "Cancel sign-in"
		_cancel_button.tooltip_text = _cancel_button.accessibility_name
	_update_status()
	_link_focus()

func _update_status() -> void:
	if not is_instance_valid(_status):
		return
	if client.session_checking:
		_status.text = "Checking your saved session…"
	elif client.auth_busy:
		_status.text = _message if not _message.is_empty() else "Signing in…"
	elif client.recovering:
		_status.text = "Reconnecting…"
	elif client.connecting:
		_status.text = "Connecting to the PvP round…" if client.mode == "pvp" else "Connecting to the shared world…"
	else:
		_status.text = _message
	_status.visible = not _status.text.is_empty()

func _set_status(message: String) -> void:
	_message = message
	_auth_state_changed()

func disconnected(message: String) -> void:
	_message = message
	show_lobby()

func _open_modes() -> void:
	if host.is_coop:
		show_lobby()
	else:
		show_mode()

func _eligible_focus() -> Array[Control]:
	var eligible: Array[Control] = []
	for control in _focus_controls:
		if not control.is_visible_in_tree():
			continue
		if control is Button and control.disabled:
			continue
		if control is LineEdit and not control.editable:
			continue
		eligible.append(control)
	return eligible

func _link_focus() -> void:
	var eligible := _eligible_focus()
	for index in eligible.size():
		var control := eligible[index]
		var previous := control.get_path_to(eligible[posmod(index - 1, eligible.size())])
		var next := control.get_path_to(eligible[(index + 1) % eligible.size()])
		control.focus_previous = previous
		control.focus_next = next
		control.focus_neighbor_top = previous
		control.focus_neighbor_bottom = next
	var focused := get_viewport().gui_get_focus_owner()
	if modal and focused != null and _root.is_ancestor_of(focused) and not eligible.has(focused):
		_focus_initial.call_deferred()

func _focus_initial() -> void:
	if not modal:
		return
	var eligible := _eligible_focus()
	if eligible.is_empty():
		return
	# Do not summon a mobile keyboard until a field is deliberately selected.
	for control in eligible:
		if control is Button:
			control.grab_focus()
			return
	eligible[0].grab_focus()

func _focus_step(step: int) -> void:
	var eligible := _eligible_focus()
	if eligible.is_empty():
		return
	var index := eligible.find(get_viewport().gui_get_focus_owner())
	var control := eligible[posmod(index + step, eligible.size())]
	control.grab_focus()
	_scroll.ensure_control_visible(control)

func _input(event: InputEvent) -> void:
	if event is InputEventJoypadButton or event is InputEventJoypadMotion:
		return
	if modal and (event.is_action_pressed(&"pause") or event.is_action_pressed(&"ui_cancel")) and not event.is_echo():
		_back()
		get_viewport().set_input_as_handled()

func _controller_event(event: InputEvent) -> void:
	if not modal or not (event is InputEventJoypadButton) or not event.pressed:
		return
	if event.is_action_pressed(&"controller_back") or event.is_action_pressed(&"controller_pause"):
		_back()
	elif event.is_action_pressed(&"controller_accept"):
		var focused := get_viewport().gui_get_focus_owner()
		if focused is Button and _eligible_focus().has(focused):
			focused.pressed.emit()
		elif focused == _username and is_instance_valid(_password):
			_password.grab_focus()
		elif focused == _password:
			_native_auth(_auth_wire_kind())
		else:
			_focus_initial()

func _process(delta: float) -> void:
	if not modal or not GameInput.controller_active:
		_direction = 0
		return
	var vertical := GameInput.controller_direction().y
	var direction := -1 if vertical > 0.5 else (1 if vertical < -0.5 else 0)
	if direction == 0:
		_direction = 0
	elif direction != _direction:
		_direction = direction
		_repeat_left = 0.38
		_focus_step(direction)
	else:
		_repeat_left -= delta
		if _repeat_left <= 0:
			_repeat_left = 0.12
			_focus_step(direction)
