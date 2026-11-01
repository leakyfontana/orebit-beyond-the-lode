extends SceneTree

var failures := 0

func _initialize() -> void:
	_run.call_deferred()

func check(condition: bool, message: String) -> void:
	if not condition:
		failures += 1
		push_error(message)

func _run() -> void:
	var host = load("res://scripts/main.gd").new()
	host.agent_axes = Vector2.ZERO
	host.seed_value = 12345
	host.data.settings_file = "user://fuel-pricing-test-settings.json"
	host.data.savefile = "user://fuel-pricing-test-save.data"
	root.add_child(host)
	host.pending_scene = ""
	host.data.setNewGameData()
	host._load_scene("Game")
	var pricing := FuelPricing.new()
	host.add_child(pricing)
	pricing.set_process(false)
	host.fuel_pricing = pricing
	var day := Time.get_date_string_from_system(true)
	pricing._completed(HTTPRequest.RESULT_SUCCESS, 200, [], JSON.stringify({"price_per_gallon": 4.0, "date": day, "valid_until": Time.get_unix_time_from_system() + 3600, "source": "aaa"}).to_utf8_buffer())
	host.data.player_money = 100
	host.data.player_fuel = 5.0
	host.data.player_max_fuel = 10.0
	host.ui.addFuel(3)
	check(host.data.player_money == 97 and is_equal_approx(host.data.player_fuel, 5.75), "$3 must buy 0.75 US gallon at $4/gal")
	host.ui.fillFuel()
	check(host.data.player_money == 80 and host.data.player_fuel == 10.0, "Fill must debit the actual 4.25-gallon cost, not the gallon count")
	host.ui.addFuel(3)
	check(host.data.player_money == 80 and host.data.player_fuel == 10.0, "A full tank must not be charged")
	host.data.player_fuel = 9.9
	host.ui.addFuel(20)
	check(host.data.player_money == 79 and host.data.player_fuel == 10.0, "A large dollar budget must only charge the rounded-up amount needed to fill")
	host.data.player_money = 0
	host.data.player_fuel = 2.0
	host.ui.addFuel(3)
	check(host.data.player_money == 0 and host.data.player_fuel == 2.0, "Insufficient funds must not add fuel")
	host.data.player_money = 100
	pricing._completed(HTTPRequest.RESULT_SUCCESS, 503, [], "{}".to_utf8_buffer())
	host.ui.fillFuel()
	check(host.data.player_money == 100 and host.data.player_fuel == 2.0, "Unavailable pricing must not debit money or dispense fuel")
	pricing.price_per_gallon = 4.0
	pricing.valid_until = Time.get_unix_time_from_system() - 1
	host.ui.addFuel(3)
	check(host.data.player_money == 100 and host.data.player_fuel == 2.0, "A previous day's price must not be used for a new purchase")
	pricing.valid_until = Time.get_unix_time_from_system() + 3600
	pricing.price_per_gallon = 4.1732
	host.data.player_fuel = 0.0
	host.ui.addFuel(3)
	check(host.data.player_money == 97 and is_equal_approx(host.data.player_fuel, 3.0 / 4.1732), "Fractional gas prices must use gallons directly without charging an extra floating-point dollar")
	host.data.player_max_fuel = 100.0
	host.data.player_fuel = 50.0
	host.data.addFuel(25.0)
	check(host.data.player_fuel == 75.0, "Reserve fuel must add 25 gallons without unit conversion")
	DirAccess.remove_absolute(host.data.settings_file)
	host.free()
	await process_frame
	print("FUEL_PRICING_INTEROP failures=" + str(failures))
	quit(1 if failures else 0)
