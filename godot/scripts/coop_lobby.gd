class_name CoopLobby
extends CanvasLayer

var host: Node
var client: CoopClient
var modal := true
var _paused_before_lobby := false
var _root: Control
var _shade: ColorRect
var _panel: PanelContainer
var _body: VBoxContainer
var _status: Label
var _identity: Label
var _url: LineEdit
var _world: LineEdit
var _username: LineEdit
var _password: LineEdit
var _hud: HBoxContainer
var _hud_label: Label
var _message := ""
var _page := "mode"
var _join_button: Button
var _discord_open: Button

func configure(main_host: Node, network: CoopClient) -> void:
	host = main_host
	client = network
	layer = 110
	process_mode = Node.PROCESS_MODE_ALWAYS
	_root = Control.new()
	_root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)
	_shade = ColorRect.new()
	_shade.color = Color(0.015, 0.025, 0.045, 0.94)
	_shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_root.add_child(_shade)
	_panel = PanelContainer.new()
	_root.add_child(_panel)
	var margin := MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 18)
	_panel.add_child(margin)
	var scroll := ScrollContainer.new()
	margin.add_child(scroll)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_body = VBoxContainer.new()
	_body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_body.add_theme_constant_override("separation", 9)
	scroll.add_child(_body)
	_hud = HBoxContainer.new()
	_hud.position = Vector2(12, 12)
	_hud.add_theme_constant_override("separation", 12)
	_root.add_child(_hud)
	_hud_label = Label.new()
	_hud.add_child(_hud_label)
	var account := Button.new()
	account.text = "Game modes / account"
	account.pressed.connect(_open_modes)
	_hud.add_child(account)
	client.status_changed.connect(_set_status)
	client.identity_changed.connect(_refresh_identity)
	get_viewport().size_changed.connect(_resize)
	show_mode()

func _resize() -> void:
	var size := get_viewport().get_visible_rect().size
	var panel_size := Vector2(minf(550, size.x - 24), minf(690, size.y - 24))
	_panel.position = (size - panel_size) * 0.5
	_panel.size = panel_size

func _clear() -> void:
	for child in _body.get_children():
		_body.remove_child(child)
		child.queue_free()
	_status = null
	_identity = null
	_join_button = null
	_discord_open = null

func _label(text: String, small: bool = false) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", 14 if small else 18)
	_body.add_child(label)
	return label

func _button(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size.y = 42
	button.pressed.connect(action)
	_body.add_child(button)
	return button

func _field(placeholder: String, value: String = "", secret: bool = false) -> LineEdit:
	var field := LineEdit.new()
	field.placeholder_text = placeholder
	field.text = value
	field.secret = secret
	field.custom_minimum_size.y = 38
	_body.add_child(field)
	return field

func show_mode() -> void:
	if not modal:
		_paused_before_lobby = host.paused
	_page = "mode"
	modal = true
	_shade.show()
	_panel.show()
	_hud.hide()
	host.paused = true
	_clear()
	_label("OREBIT · Choose your game")
	_label("Private play stays on this device. Co-op shares one server world with up to five miners.", true)
	_button("Private · on this device", _choose_private)
	_button("Co-op · shared server", show_lobby)
	_label("No account is required for co-op. Sign up or sign in to keep your player progress on the server.", true)
	_resize()

func show_lobby() -> void:
	if not modal:
		_paused_before_lobby = host.paused
	_page = "lobby"
	modal = true
	host.paused = true
	_shade.show()
	_panel.show()
	_hud.hide()
	_clear()
	_label("Co-op server · up to 5 miners")
	_identity = _label("")
	_label("Accounts keep money, cargo, upgrades, items and position on this server. Anonymous progress ends when you leave. Private saves are never used here.", true)
	_url = _field("Server HTTPS address", client.base_url)
	_world = _field("World", client.world_id)
	_world.editable = false
	if client.connected:
		_button("Return to shared world", hide_lobby)
		_button("Leave server", _leave)
	else:
		_join_button = _button("Join server" if not client.token.is_empty() else "Join anonymously", _join)
	_username = _field("Username")
	_password = _field("Password (minimum 8 characters)", "", true)
	_button("Sign in with username / password", func(): _native_auth("login"))
	_button("Create username / password account", func(): _native_auth("signup"))
	_button("Sign in with Discord", _discord_auth)
	_discord_open = _button("Open Discord sign-in", func(): OS.shell_open(client.discord_url))
	_discord_open.visible = not client.discord_url.is_empty()
	_button("Sign out / cancel sign-in", _sign_out)
	_button("Back to mode choice", _back)
	_status = _label(_message, true)
	_refresh_identity()
	_resize()

func hide_lobby(reset_pause: bool = false) -> void:
	modal = false
	_shade.hide()
	_panel.hide()
	host.paused = false if reset_pause else _paused_before_lobby
	refresh_hud()

func refresh_hud() -> void:
	if not is_instance_valid(_hud_label):
		return
	_hud.visible = not modal and (host.is_coop or host.scene_name == "MainMenu")
	_hud_label.text = "Co-op · %d/5 · %s" % [client.peers.size(), "Account · server progress" if not client.token.is_empty() else "Anonymous · sign up to keep server progress"] if host.is_coop else "Private · on this device"

func _choose_private() -> void:
	if not host.leave_coop():
		return
	hide_lobby(true)
	host.change_scene("MainMenu")

func _back() -> void:
	if client.connected:
		hide_lobby()
	else:
		show_mode()

func _leave() -> void:
	if not host.leave_coop():
		return
	host.change_scene("MainMenu")
	show_lobby()

func _join() -> void:
	if client.connecting:
		return
	client.set_endpoint(_url.text.strip_edges().trim_suffix("/"))
	if not client.endpoint_is_secure():
		_set_status("Use an HTTPS server address (localhost HTTP is supported for development).")
		return
	client.join_world()

func _prepare_auth() -> bool:
	if client.connected or client.connecting:
		_set_status("Leave the server first to sign in. Your account will restore its own progress when you rejoin.")
		return false
	client.set_endpoint(_url.text.strip_edges().trim_suffix("/"))
	if not client.endpoint_is_secure():
		_set_status("Use HTTPS to protect your sign-in details.")
		return false
	return true

func _native_auth(kind: String) -> void:
	if _prepare_auth():
		var password := _password.text
		_password.text = ""
		client.authenticate(kind, _username.text.strip_edges(), password)

func _discord_auth() -> void:
	if _prepare_auth():
		client.discord_login()

func _sign_out() -> void:
	if client.connected:
		_set_status("Leave the server before signing out.")
		return
	client.logout()
	show_lobby()

func _refresh_identity() -> void:
	if is_instance_valid(_identity):
		_identity.text = "Anonymous play" if client.token.is_empty() else "Signed in: " + client.username
	if is_instance_valid(_join_button):
		_join_button.text = "Join anonymously" if client.token.is_empty() else "Join server"
	refresh_hud()

func _set_status(message: String) -> void:
	_message = message
	if is_instance_valid(_status):
		_status.text = message
	if is_instance_valid(_discord_open):
		_discord_open.visible = not client.discord_url.is_empty()

func disconnected(message: String) -> void:
	_message = message
	show_lobby()

func _open_modes() -> void:
	if host.is_coop:
		show_lobby()
	else:
		show_mode()
