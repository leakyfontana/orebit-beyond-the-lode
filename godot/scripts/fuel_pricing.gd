class_name FuelPricing
extends Node

var price_per_gallon := 0.0
var price_date := ""
var valid_until := 0.0
var status := "Fetching today's AAA national average…"
var host: Node
var _http: HTTPRequest
var _last_day := ""
var _next_check := 0
var _panel: PanelContainer
var _details: Label
var _sign: Label

func configure(game_host: Node) -> void:
	host = game_host
	process_mode = Node.PROCESS_MODE_ALWAYS
	_http = HTTPRequest.new()
	_http.accept_gzip = not OS.has_feature("web")
	_http.timeout = 25.0
	add_child(_http)
	_http.request_completed.connect(_completed)
	refresh()

func _process(_delta: float) -> void:
	var now := Time.get_ticks_msec()
	if now < _next_check:
		return
	_next_check = now + 60000
	if _last_day != Time.get_date_string_from_system(true) or (price_per_gallon > 0.0 and not available()):
		refresh()

func refresh() -> void:
	_last_day = Time.get_date_string_from_system(true)
	price_per_gallon = 0.0
	price_date = ""
	valid_until = 0.0
	status = "Fetching today's AAA national average…"
	_http.cancel_request()
	var base_url: String = CoopClient.DEFAULT_URL
	if host.coop != null:
		base_url = host.coop.network.base_url
	var result := _http.request(base_url + "/api/fuel-price")
	if result != OK:
		status = "AAA price service unavailable. Retry before purchasing."
	_update_display()

func available() -> bool:
	return price_per_gallon > 0.0 and Time.get_unix_time_from_system() < valid_until

func _completed(result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	var response: Variant = null
	if result == HTTPRequest.RESULT_SUCCESS and code == 200:
		var parser := JSON.new()
		if parser.parse(body.get_string_from_utf8()) == OK:
			response = parser.data
	price_per_gallon = 0.0
	price_date = ""
	valid_until = 0.0
	if result != HTTPRequest.RESULT_SUCCESS or code != 200 or not response is Dictionary:
		status = "Today's AAA price is unavailable. Retry before purchasing."
		_update_display()
		return
	var value: Variant = response.get("price_per_gallon")
	var valid_number := value is float or value is int
	var day := str(response.get("date", ""))
	var expiry: Variant = response.get("valid_until", 0)
	var valid_expiry := (expiry is float or expiry is int) and is_finite(float(expiry)) and float(expiry) > Time.get_unix_time_from_system()
	if not valid_number or not is_finite(float(value)) or float(value) <= 0.0 or not valid_expiry or day.is_empty() or str(response.get("source", "")) != "aaa":
		status = "No valid AAA price for today. Retry before purchasing."
	else:
		price_per_gallon = float(value)
		price_date = day
		valid_until = float(expiry)
		status = "AAA · US national average regular"
	_update_display()

func install_shop_panel(parent: Control) -> void:
	_panel = PanelContainer.new()
	_panel.name = "SinclairPricing"
	_panel.grow_vertical = Control.GROW_DIRECTION_BEGIN
	_panel.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_RIGHT)
	_panel.position = Vector2(-410, -190)
	_panel.size = Vector2(390, 170)
	parent.add_child(_panel)
	var content := VBoxContainer.new()
	_panel.add_child(content)
	_details = Label.new()
	_details.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_details.custom_minimum_size.x = 370
	content.add_child(_details)
	var retry := Button.new()
	retry.text = "Retry today's AAA price"
	retry.pressed.connect(refresh)
	content.add_child(retry)
	var notice := Label.new()
	notice.text = "Same national price for every player.\nNo device location is collected."
	notice.add_theme_font_size_override("font_size", 13)
	content.add_child(notice)
	host.ui.controller_ui.register_panel(_panel, host.bridge.node(host.ui._panel("FuelShopManager")) as Control)
	_panel.hide()
	_update_display()

func show_shop(enabled: bool) -> void:
	if is_instance_valid(_panel):
		_panel.visible = enabled

func install_sign(parent: Node2D, position: Vector2) -> void:
	_sign = Label.new()
	_sign.name = "SinclairPrice"
	_sign.position = position
	_sign.scale = Vector2.ONE / 50.0
	_sign.size = Vector2(86, 16)
	_sign.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_sign.add_theme_font_size_override("font_size", 14)
	_sign.add_theme_color_override("font_color", Color("f3f6df"))
	_sign.add_theme_color_override("font_outline_color", Color("103a25"))
	_sign.add_theme_constant_override("outline_size", 1)
	_sign.z_index = 10
	parent.add_child(_sign)
	_update_display()

func _update_display() -> void:
	var price := "$%.4f / US gal" % price_per_gallon if available() else "Price unavailable"
	if is_instance_valid(_sign):
		_sign.text = "$%.4f" % price_per_gallon if available() else "—"
	if is_instance_valid(_details):
		_details.text = "SINCLAIR · " + price + "\n" + status + ("\n" + price_date if available() else "") + "\nWhole-dollar charges round up."
