class_name CoopTransfer
extends CanvasLayer

enum Visit { CLOSED, OPEN }
enum Eligibility { UNAVAILABLE, OUT_OF_REACH, ELIGIBLE }
enum Submission { READY, WAITING_FOR_SERVER }

const DOOR := Vector2(-5.5, -3.5)
const ORANGE := Color("ff6100")
var host: Node
var client: CoopClient
var visit: Visit = Visit.CLOSED
var modal: bool:
	get:
		return visit == Visit.OPEN
	set(value):
		visit = Visit.OPEN if value else Visit.CLOSED
var recipient: OptionButton
var amount: LineEdit
var status: Label
var balance: Label
var visit_button: Button
var _root: Control
var _shade: ColorRect
var _panel: PanelContainer
var _send: Button

func configure(main_host: Node, network: CoopClient) -> void:
	host = main_host
	client = network
	name = "RiaTransfer"
	layer = 105
	process_mode = Node.PROCESS_MODE_ALWAYS
	_root = Control.new()
	_root.name = "Root"
	_root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)
	visit_button = Button.new()
	visit_button.name = "VisitRia"
	visit_button.text = "Visit ria · Money Transfer"
	visit_button.custom_minimum_size = Vector2(260, 44)
	visit_button.pressed.connect(open_visit)
	_root.add_child(visit_button)
	_shade = ColorRect.new()
	_shade.color = Color(0.015, 0.025, 0.045, 0.87)
	_shade.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_root.add_child(_shade)
	_panel = PanelContainer.new()
	_panel.name = "Panel"
	var style := StyleBoxFlat.new()
	style.bg_color = Color("faf7f3")
	style.border_color = ORANGE
	style.set_border_width_all(3)
	_panel.add_theme_stylebox_override("panel", style)
	_root.add_child(_panel)
	var margin := MarginContainer.new()
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 20)
	_panel.add_child(margin)
	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	margin.add_child(scroll)
	var body := VBoxContainer.new()
	body.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 12)
	scroll.add_child(body)
	var heading := _label(body, "ria  |  Money Transfer")
	heading.add_theme_font_size_override("font_size", 28)
	heading.add_theme_color_override("font_color", ORANGE)
	_label(body, "Shared co-op branch · " + client.world_id)
	_label(body, "Send dollars to another miner currently connected to this world. No fee: the recipient receives exactly what you send.")
	balance = _label(body, "")
	balance.name = "Balance"
	_label(body, "Recipient")
	recipient = OptionButton.new()
	recipient.name = "Recipient"
	recipient.custom_minimum_size.y = 42
	body.add_child(recipient)
	_label(body, "Amount · whole dollars")
	amount = LineEdit.new()
	amount.name = "Amount"
	amount.placeholder_text = "e.g. 7"
	amount.virtual_keyboard_type = LineEdit.KEYBOARD_TYPE_NUMBER
	amount.max_length = 16
	amount.custom_minimum_size.y = 42
	body.add_child(amount)
	amount.text_submitted.connect(func(_text: String): submit_transfer())
	_send = Button.new()
	_send.name = "Send"
	_send.text = "Send money"
	_send.custom_minimum_size.y = 44
	_send.pressed.connect(submit_transfer)
	body.add_child(_send)
	status = _label(body, "")
	status.name = "Status"
	status.custom_minimum_size.y = 48
	var close := Button.new()
	close.text = "Leave branch"
	close.custom_minimum_size.y = 42
	close.pressed.connect(close_visit)
	body.add_child(close)
	get_viewport().size_changed.connect(_resize)
	_shade.hide()
	_panel.hide()
	visit_button.hide()
	_resize()

func _label(parent: Node, text: String) -> Label:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_color_override("font_color", Color("272b31"))
	parent.add_child(label)
	return label

func _resize() -> void:
	var size := get_viewport().get_visible_rect().size
	var panel_size := Vector2(minf(490, size.x - 24), minf(610, size.y - 24))
	_panel.position = (size - panel_size) * 0.5
	_panel.size = panel_size
	visit_button.position = Vector2((size.x - 260) * 0.5, size.y - 115)

func visit_eligibility() -> Eligibility:
	if not host.is_coop or not client.connected or host.scene_name != "Game" or not host.player_alive or host.player == null:
		return Eligibility.UNAVAILABLE
	var distance: Vector2 = host.player.position_unity - DOOR
	if absf(distance.x) <= 1.5 and absf(distance.y) <= 1.5:
		return Eligibility.ELIGIBLE
	return Eligibility.OUT_OF_REACH

func can_visit() -> bool:
	return visit_eligibility() == Eligibility.ELIGIBLE

func submission_state() -> Submission:
	return Submission.WAITING_FOR_SERVER if client.transfer_pending else Submission.READY

func tick() -> void:
	var eligibility := visit_eligibility()
	visit_button.visible = eligibility == Eligibility.ELIGIBLE and not modal and not host.paused and not host.ui.isUIOpen()
	if modal:
		if eligibility != Eligibility.ELIGIBLE:
			close_visit()
		else:
			_refresh_balance()

func open_visit() -> void:
	if modal or not can_visit() or host.paused or host.ui.isUIOpen():
		return
	visit = Visit.OPEN
	visit_button.hide()
	_shade.show()
	_panel.show()
	host.enterShop()
	host.audio.PlayMusic("ShopMusic")
	status.text = "Choose a connected player and enter a positive whole-dollar amount."
	refresh_recipients()
	_refresh_balance()
	recipient.grab_focus()

func close_visit() -> void:
	if not modal:
		return
	if submission_state() == Submission.WAITING_FOR_SERVER:
		status.text = "Wait for server confirmation before leaving the branch."
		return
	visit = Visit.CLOSED
	_shade.hide()
	_panel.hide()
	if host.player != null and host.scene_name == "Game":
		host.exitShop()
		host.audio.PlayMusic("MainLevelMusic")
	client.send_state()

func scene_loaded() -> void:
	visit = Visit.CLOSED
	_shade.hide()
	_panel.hide()
	visit_button.hide()
	if host.is_coop and host.scene_name == "Game":
		_build_storefront()

func refresh_recipients() -> void:
	var selected_id := ""
	if recipient.selected >= 0:
		selected_id = str(recipient.get_item_metadata(recipient.selected))
	recipient.clear()
	for id in client.peers:
		if str(id) == client.player_id:
			continue
		var peer: Dictionary = client.peers[id]
		recipient.add_item(str(peer.get("name", "Miner")) + " · " + str(id).left(6))
		var index := recipient.item_count - 1
		recipient.set_item_metadata(index, str(id))
		if str(id) == selected_id:
			recipient.select(index)
	recipient.disabled = recipient.item_count == 0
	if recipient.item_count == 0:
		status.text = "No other miners are connected to this world. Invite someone to join."
	_refresh_balance()

func _refresh_balance() -> void:
	balance.text = "Available balance: $%d" % host.data.player_money
	_send.disabled = not client.connected or client.has_pending_actions() or recipient.item_count == 0
	var waiting := submission_state() == Submission.WAITING_FOR_SERVER
	_send.text = "Waiting for server…" if waiting else "Send money"
	amount.editable = not waiting
	recipient.disabled = waiting or recipient.item_count == 0

func submit_transfer() -> void:
	if not modal or not can_visit():
		return
	if client.has_pending_actions():
		status.text = "Wait for the current server transaction to finish."
		return
	if recipient.selected < 0:
		status.text = "Select another connected player first."
		return
	var id := str(recipient.get_item_metadata(recipient.selected))
	if id == client.player_id or not client.peers.has(id):
		status.text = "That player is no longer connected. Select another recipient."
		refresh_recipients()
		return
	var text := amount.text.strip_edges()
	if text.is_empty() or not text.is_valid_int():
		status.text = "Enter a positive whole-dollar amount, without decimals or symbols."
		return
	for character in text:
		if character < "0" or character > "9":
			status.text = "Enter a positive whole-dollar amount, without decimals or symbols."
			return
	var dollars := int(text)
	if dollars <= 0 or dollars > host.data.player_money:
		status.text = "Enter an amount from $1 to your available balance ($%d)." % host.data.player_money
		return
	if client.transfer_money(id, dollars):
		status.text = "Sending $%d… Waiting for server confirmation." % dollars
	else:
		status.text = "Unable to send. Check your connection and try again."
	_refresh_balance()

func transfer_result(event: Dictionary) -> void:
	status.text = str(event.get("message", "Transfer request finished."))
	if bool(event.get("accepted", false)):
		amount.clear()
		host.audio.PlaySoundOneShot("Purchase")
	_refresh_balance()

func _build_storefront() -> void:
	# Shop110–121 establish the native 50 px/tile textured industrial style.
	# The branch shares their bevels, roof vents and weathered bunker materials;
	# its orange enamel sign carries the Ria identity at the same raster density.
	# The co-op surface extension owns the non-drillable concrete and collision.
	var building := Sprite2D.new()
	building.name = "RiaMoneyTransfer"
	building.texture = preload("res://assets/ria_branch.png")
	building.centered = false
	building.position = Vector2(-7.5, 1.0)
	building.scale = Vector2.ONE / 50.0
	building.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	building.z_index = 5
	host.world_root.add_child(building)
