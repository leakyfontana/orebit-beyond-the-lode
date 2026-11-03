class_name CoopLobby
extends CanvasLayer

const ACCENT := Color("4fd348")
const INK := Color("091307")
const TEXT := Color("dcedd4")
const MUTED := Color("a4ba97")
const TARGET_SIZE := 48.0

var host: Node
var client: CoopClient
var modal := true
var _paused_before_lobby := false
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
var _auth_heading: Label
var _auth_submit: Button
var _auth_toggle: Button
var _cancel_button: Button
var _hud: VBoxContainer
var _hud_label: Label
var _menu_font: Font
var _hud_scene := ""
var _header_ink_rects: Dictionary = {}
var _header_source_root: Control
var _header_offsets: Dictionary = {}
var _message := ""
var _page := "mode"
var _auth_kind := "login"
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
		margin.add_theme_constant_override("margin_" + side, 16)
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
	_body.add_theme_constant_override("separation", 12)
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
	style.content_margin_left = 14
	style.content_margin_right = 14
	style.content_margin_top = 10
	style.content_margin_bottom = 10
	return style

func _style_button(button: Button, primary: bool) -> void:
	button.custom_minimum_size = Vector2(TARGET_SIZE, TARGET_SIZE)
	button.add_theme_font_size_override("font_size", 16)
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
	panel_size.y = minf(panel_size.y, maxf(180, _body.get_combined_minimum_size().y + 32))
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
	_auth_heading = null
	_auth_submit = null
	_auth_toggle = null
	_cancel_button = null
	_actions.clear()
	_fields.clear()
	_focus_controls.clear()
	_scroll.scroll_vertical = 0

func _label(text: String, small: bool = false) -> Label:
	var label := Label.new()
	label.text = text
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", 16 if small else 24)
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
	_style_button(button, primary)
	button.pressed.connect(action)
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	if container == null:
		_body.add_child(button)
	else:
		container.add_child(button)
	_actions.append(button)
	_focus_controls.append(button)
	return button

func _field(label_text: String, value: String, control_name: String, secret: bool = false) -> LineEdit:
	var label := _label(label_text, true)
	label.add_theme_color_override("font_color", TEXT)
	var field := LineEdit.new()
	field.name = control_name
	field.text = value
	field.secret = secret
	field.custom_minimum_size = Vector2(TARGET_SIZE, TARGET_SIZE)
	field.expand_to_text_length = false
	field.add_theme_font_size_override("font_size", 16)
	field.add_theme_color_override("font_color", TEXT)
	field.add_theme_color_override("font_uneditable_color", MUTED)
	field.add_theme_color_override("caret_color", ACCENT)
	field.add_theme_stylebox_override("normal", _surface(INK, Color("426539")))
	field.add_theme_stylebox_override("read_only", _surface(Color("172014"), Color("35472e")))
	var focus := _surface(Color(0, 0, 0, 0), ACCENT)
	focus.set_border_width_all(3)
	field.add_theme_stylebox_override("focus", focus)
	# Keep native editing, paste/context menu and virtual keyboard behavior.
	_body.add_child(field)
	_fields.append(field)
	_focus_controls.append(field)
	return field

func _open_page(page: String) -> void:
	leaderboard.close()
	if not modal:
		_paused_before_lobby = host.paused
	_page = page
	modal = true
	host.paused = true
	_shade.show()
	_panel.show()
	_hud.hide()
	_clear()

func _finish_page() -> void:
	_status = _label("", true)
	_status.name = "AuthStatus"
	_cancel_button = _button("Cancel sign-in", _cancel_auth, "CancelAuth")
	_actions.erase(_cancel_button)
	_auth_state_changed()
	_resize()
	_resize.call_deferred()
	if GameInput.controller_active:
		_focus_initial.call_deferred()

func show_mode() -> void:
	_open_page("mode")
	_label("OREBIT · Choose your game")
	_label("Private saves stay on this device. Co-op shares one server world with up to five miners.", true)
	_label("Gameplay recording is automatic in all modes. Recordings are uploaded to the game server for bot training; chat, credentials and account identifiers are excluded.", true)
	_button("Private · this device", _choose_private, "ChoosePrivate", true)
	_button("Co-op · shared server", func(): _choose_server("coop"), "ChooseCoop")
	_button("PvP · race to $1,000,000", func(): _choose_server("pvp"), "ChoosePvp")
	_label("First to $1,000,000 held cash wins; every win starts a fresh PvP world.", true)
	_label("Accounts keep Co-op progress and the current PvP round. Private saves are separate. No account is required.", true)
	_finish_page()

func _choose_server(mode: String) -> void:
	if _busy() and not client.session_checking:
		return
	if client.connected and client.mode != mode:
		if not host.leave_coop():
			return
		host.change_scene("MainMenu")
	client.mode = mode
	_message = ""
	show_lobby()

func show_lobby() -> void:
	_open_page("lobby")
	_lobby_state = _state_key()
	_label("PvP · race to $1,000,000" if client.mode == "pvp" else "Co-op · shared world")
	_identity = _label("", true)
	_identity.name = "AccountIdentity"
	if client.mode == "pvp":
		_label("First to $1,000,000 held cash wins and resets the PvP world and every miner's equipment. Death drops cash, minerals and items; respawn in 10 seconds with a stock vehicle. Loot that cannot fit stays in the bag. Explosives cannot hurt their owner.", true)
	if client.connected:
		_label("Your PvP round is ready. Return to play, or leave before changing accounts." if client.mode == "pvp" else "Your shared world is ready. Return to play, or leave before changing accounts.", true)
		_button("Return to PvP" if client.mode == "pvp" else "Return to shared world", hide_lobby, "ReturnToWorld", true)
		_button("Leave server", _leave, "LeaveServer")
	elif not client.token.is_empty():
		_label("Your account keeps money, cargo, upgrades, items and position " + ("until the current PvP round ends." if client.mode == "pvp" else "in this Co-op world."), true)
		_button("Join server", _join, "JoinServer", true)
		_button("Sign out", _sign_out, "SignOut")
	else:
		_label(("Keep progress in this PvP round" if client.mode == "pvp" else "Keep your Co-op progress") + " with an account. Private saves stay separate.", true)
		_button("Continue with Discord", _discord_auth, "ContinueDiscord", true)
		_button("Use username / password", _show_password, "UsePassword")
		_label("Just exploring? Anonymous progress ends when you leave the server.", true)
		_button("Play anonymously", _join, "JoinAnonymous")
	var navigation := HBoxContainer.new()
	navigation.add_theme_constant_override("separation", 12)
	_body.add_child(navigation)
	if not client.connected:
		_button("Server options", _show_server, "AdvancedServer", false, navigation)
	_button("Back to modes" if not client.connected else "Game modes", show_mode, "BackToModes", false, navigation)
	_finish_page()

func _show_password() -> void:
	if _busy():
		return
	_open_page("password")
	_auth_heading = _label("")
	_label("This account keeps separate Co-op and PvP progress on this server only.", true)
	_username = _field("Username", _username_draft, "AuthUsername")
	_username.placeholder_text = "Your username"
	_username.text_submitted.connect(func(_text: String): _password.grab_focus())
	_password = _field("Password", "", "AuthPassword", true)
	_password.placeholder_text = "At least 8 characters"
	_password.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_PASSWORD
	_password.text_submitted.connect(func(_text: String): _native_auth(_auth_kind))
	var reveal := _button("Show password", _toggle_password, "RevealPassword")
	reveal.toggle_mode = true
	_auth_submit = _button("", func(): _native_auth(_auth_kind), "SubmitPassword", true)
	_auth_toggle = _button("", _toggle_auth_kind, "SwitchPasswordMode")
	_button("Back to PvP" if client.mode == "pvp" else "Back to co-op", show_lobby, "PasswordBack")
	_update_password_mode()
	_finish_page()

func _update_password_mode() -> void:
	_auth_heading.text = "Sign in" if _auth_kind == "login" else "Create account"
	_auth_submit.text = "Sign in" if _auth_kind == "login" else "Create account"
	_auth_toggle.text = "Create an account instead" if _auth_kind == "login" else "I already have an account"

func _toggle_auth_kind() -> void:
	if _busy():
		return
	_auth_kind = "signup" if _auth_kind == "login" else "login"
	_message = ""
	_update_password_mode()
	_update_status()

func _toggle_password() -> void:
	if is_instance_valid(_password):
		_password.secret = not _password.secret
		var reveal := _body.get_node("RevealPassword") as Button
		reveal.set_pressed_no_signal(not _password.secret)
		reveal.text = "Show password" if _password.secret else "Hide password"

func _show_server() -> void:
	if _busy() or client.connected:
		return
	_open_page("server")
	_label("Advanced · " + ("PvP" if client.mode == "pvp" else "Co-op") + " server")
	_label("Use the default Orebit server unless you run your own. Changing servers signs out this account; progress stays on its original server.", true)
	_url = _field("Server HTTPS address", client.base_url, "ServerAddress")
	_url.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_URL
	_url.text_submitted.connect(func(_text: String): _save_server())
	_label(("PvP world" if client.mode == "pvp" else "Shared world") + ": " + client.world_id, true)
	_button("Save server address", _save_server, "SaveServer", true)
	_button("Use default server", _default_server, "DefaultServer")
	_button("Back without changes", show_lobby, "ServerBack")
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
	modal = false
	_shade.hide()
	_panel.hide()
	host.paused = false if reset_pause else _paused_before_lobby
	refresh_hud()

func refresh_hud() -> void:
	if not is_instance_valid(_hud_label):
		return
	leaderboard.refresh()
	var header_text := "%s · %d/5" % ["PvP" if client.mode == "pvp" else "Co-op", client.peers.size()] if host.is_coop else "Private"
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
	if _page == "password" or _page == "server":
		show_lobby()
	elif _page == "mode" or client.connected:
		hide_lobby()
	else:
		show_mode()

func _leave() -> void:
	if _busy() or not host.leave_coop():
		return
	host.change_scene("MainMenu")
	show_lobby()

func _join() -> void:
	if _busy() or client.connected:
		return
	if not client.endpoint_is_secure():
		_set_status("Use an HTTPS server address in Advanced before joining.")
		return
	_message = "Connecting to the PvP round…" if client.mode == "pvp" else "Connecting to the shared world…"
	client.join_world()
	_auth_state_changed()

func _prepare_auth() -> bool:
	if _busy() or client.connected:
		return false
	if not client.endpoint_is_secure():
		_set_status("Use an HTTPS server address in Advanced to protect your sign-in.")
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
	_message = ""
	client.logout()
	_message = "Signed out. You can sign in again or play anonymously."
	show_lobby()

func _busy() -> bool:
	return client.auth_busy or client.session_checking or client.connecting

func _state_key() -> String:
	return str(client.connected) + ":" + str(not client.token.is_empty())

func _refresh_identity() -> void:
	_message = ""
	_auth_state_changed()
	refresh_hud()

func _auth_state_changed() -> void:
	if _page == "lobby" and _lobby_state != _state_key():
		show_lobby()
		return
	if _page == "password" and not client.token.is_empty() and not client.auth_busy and not client.session_checking:
		show_lobby()
		return
	if is_instance_valid(_identity):
		if client.session_checking:
			_identity.text = "Checking saved sign-in…"
		elif not client.token.is_empty():
			_identity.text = "Signed in as " + client.username
		else:
			_identity.text = "Playing anonymously" if client.connected else "Not signed in"
	for button in _actions:
		button.disabled = _busy() and not (_page == "mode" and client.session_checking)
	for field in _fields:
		field.editable = not _busy()
	if is_instance_valid(_cancel_button):
		_cancel_button.visible = client.auth_busy or client.session_checking
		_cancel_button.text = "Cancel session check" if client.session_checking else "Cancel sign-in"
	_update_status()
	_link_focus()

func _update_status() -> void:
	if not is_instance_valid(_status):
		return
	if client.session_checking:
		_status.text = "Checking your saved session…"
	elif client.auth_busy:
		_status.text = _message if not _message.is_empty() else "Signing in…"
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
			_native_auth(_auth_kind)
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
