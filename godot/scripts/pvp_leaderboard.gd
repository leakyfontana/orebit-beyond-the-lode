class_name PvpLeaderboard
extends Control

var lobby: CoopLobby
var host: Node
var client: CoopClient
var icon_button: Button
var modal := false
var _shade: ColorRect
var _panel: PanelContainer
var _names: Array[Label] = []
var _balances: Array[Label] = []
var _winner: Label
var _winner_until := 0
var _close_button: Button

func configure(owner_lobby: CoopLobby) -> void:
	lobby = owner_lobby
	host = lobby.host
	client = lobby.client
	name = "PvpLeaderboard"
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	process_mode = Node.PROCESS_MODE_ALWAYS
	icon_button = Button.new()
	icon_button.name = "LeaderboardButton"
	icon_button.tooltip_text = "Live PvP leaderboard · first to $1,000,000"
	icon_button.accessibility_name = "PvP leaderboard"
	lobby._style_button(icon_button, false)
	for state in ["normal", "hover", "pressed", "disabled"]:
		icon_button.add_theme_stylebox_override(state, StyleBoxEmpty.new())
	var art := TextureRect.new()
	art.texture = preload("res://assets/pvp_leaderboard.svg")
	art.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	art.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	art.mouse_filter = Control.MOUSE_FILTER_IGNORE
	art.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	icon_button.add_child(art)
	icon_button.pressed.connect(open)
	add_child(icon_button)
	_shade = ColorRect.new()
	_shade.color = Color(0.015, 0.025, 0.012, 0.9)
	_shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_shade)
	_panel = PanelContainer.new()
	_panel.name = "LeaderboardModal"
	_panel.add_theme_stylebox_override("panel", lobby._surface(Color("101b0e"), CoopLobby.ACCENT, 4))
	add_child(_panel)
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 12)
	_panel.add_child(body)
	body.minimum_size_changed.connect(lobby._resize, CONNECT_DEFERRED)
	var title := _label("PvP leaderboard")
	title.add_theme_font_override("font", lobby._menu_font)
	title.add_theme_font_size_override("font_size", 22)
	title.add_theme_color_override("font_color", CoopLobby.ACCENT)
	body.add_child(title)
	body.add_child(_label("First to $1,000,000 held cash wins.\nConnected players · unsold cargo is not cash."))
	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(scroll)
	var rows := VBoxContainer.new()
	rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rows.add_theme_constant_override("separation", 12)
	scroll.add_child(rows)
	for index in range(5):
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 12)
		rows.add_child(row)
		var player_name := _label("")
		player_name.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		player_name.autowrap_mode = TextServer.AUTOWRAP_OFF
		player_name.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		row.add_child(player_name)
		_names.append(player_name)
		var balance := _label("")
		balance.autowrap_mode = TextServer.AUTOWRAP_OFF
		balance.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		row.add_child(balance)
		_balances.append(balance)
	_close_button = Button.new()
	_close_button.name = "CloseLeaderboard"
	_close_button.text = "Close"
	lobby._style_button(_close_button, false)
	_close_button.pressed.connect(close)
	body.add_child(_close_button)
	_winner = _label("")
	_winner.name = "PvpWinnerAnnouncement"
	_winner.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_winner.add_theme_color_override("font_color", CoopLobby.ACCENT)
	_winner.add_theme_font_override("font", lobby._menu_font)
	_winner.add_theme_stylebox_override("normal", lobby._surface(Color("101b0e"), CoopLobby.ACCENT))
	_winner.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_winner)
	_shade.hide()
	_panel.hide()
	_winner.hide()
	icon_button.hide()

func _label(text: String) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_color_override("font_color", CoopLobby.TEXT)
	label.add_theme_font_size_override("font_size", 16)
	return label

func layout(available: Rect2, icon_center: Vector2, icon_size: Vector2) -> void:
	icon_button.position = icon_center - icon_size * 0.5
	icon_button.size = icon_size
	var panel_size := Vector2(minf(480, available.size.x - 24), minf(410, available.size.y - 24))
	_panel.position = available.position + (available.size - panel_size) * 0.5
	_panel.size = panel_size
	var header_bottom := icon_center.y + icon_size.y * 0.5
	if host.scene_name == "Game":
		var options := host.ui_root.find_child("OptionsButton", true, false) as Control
		if options != null:
			header_bottom = maxf(header_bottom, lobby._header_art_rect(options).end.y)
	_winner.position = Vector2(available.position.x + maxf(12, (available.size.x - 560) * 0.5), maxf(available.position.y + 112, header_bottom + 12))
	_winner.size = Vector2(minf(560, available.size.x - 24), 0)

func open() -> void:
	if modal or lobby.modal or not icon_button.visible or host.paused or host.ui.isUIOpen():
		return
	modal = true
	host.paused = true
	_shade.show()
	_panel.show()
	refresh()
	_close_button.grab_focus()

func close() -> void:
	if not modal:
		return
	modal = false
	_shade.hide()
	_panel.hide()
	host.paused = lobby.modal
	if icon_button.visible:
		icon_button.grab_focus()

func refresh() -> void:
	var active: bool = host.is_coop and client.connected and client.mode == "pvp" and host.scene_name == "Game" and host.pending_scene.is_empty()
	icon_button.visible = active and not lobby.modal
	if not active or lobby.modal:
		close()
	if not modal:
		return
	var players: Array = client.peers.values()
	players.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var cash_a := int(a.get("state", {}).get("player_money", 0))
		var cash_b := int(b.get("state", {}).get("player_money", 0))
		return cash_a > cash_b if cash_a != cash_b else str(a.player_id) < str(b.player_id)
	)
	for index in range(_names.size()):
		var present := index < players.size()
		_names[index].get_parent().visible = present
		if present:
			var peer: Dictionary = players[index]
			var display_name := str(peer.get("name", "Miner"))
			_names[index].text = "%d. %s%s" % [index + 1, display_name, " (you)" if str(peer.player_id) == client.player_id else ""]
			_names[index].tooltip_text = display_name
			_balances[index].text = "$" + host.ui._grouped(int(peer.get("state", {}).get("player_money", 0)))

func announce(winner: Dictionary) -> void:
	if winner.is_empty():
		return
	_winner.text = "%s wins with $%s!\nFresh round - first to $1,000,000." % [str(winner.get("name", "Miner")), host.ui._grouped(int(winner.get("amount", 1000000)))]
	_winner_until = Time.get_ticks_msec() + 10000
	_winner.show()

func _process(_delta: float) -> void:
	_winner.visible = Time.get_ticks_msec() < _winner_until and host.scene_name == "Game" and not modal and not lobby.modal
