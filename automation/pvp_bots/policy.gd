extends SceneTree

# Keep the real host, vehicle and economy; resolve bot controls at native poses.
class BotHost extends "res://scripts/main.gd":
	var bot_attack_enabled := false
	var bot_attack_target := ""
	var bot_control: Callable
	var _bot_animator: Node

	func _sample_player_triggers() -> void:
		super._sample_player_triggers()
		if player != null and player.animator != _bot_animator:
			_bot_animator = player.animator
			_bot_animator.animation_event.connect(_bot_animation_event)
		_apply_bot_control()

	func _bot_animation_event(method: String, _argument: Variant) -> void:
		# Native FinishFlipping changes the serialized sensors after the fixed
		# phase but before Player.tick. Its own handler is connected first.
		if method == "FinishFlipping":
			_apply_bot_control()

	func _apply_bot_control() -> void:
		if agent_axes != null and player != null and player_alive and not paused and bot_control.is_valid():
			player.sync_physics_pose()
			agent_axes = bot_control.call(agent_axes, player.position_unity)

	func coop_state() -> Dictionary:
		var state := super.coop_state()
		var allowed := bot_attack_enabled and player_alive and player != null
		if allowed:
			var peer: Dictionary = coop.network.peers.get(bot_attack_target, {})
			var peer_state: Dictionary = peer.get("state", {})
			allowed = not peer.is_empty() and str(peer.get("player_id", "")) != coop.network.player_id and bool(peer_state.get("alive", true)) and str(peer_state.get("building", "")).is_empty() and not coop.pvp.building_pending and coop.pvp.building.is_empty()
			if allowed:
				var offset := Vector2(float(peer_state.get("x", 0)), float(peer_state.get("y", 0))) - player.position_unity
				allowed = offset.length_squared() <= 9.0 and offset.y <= 0.65
		if not allowed:
			state.drill_x = 0.0
			state.drill_y = 0.0
		return state

class BotBrain extends RefCounted:
	const DIRECTIONS := [Vector2i.DOWN, Vector2i.LEFT, Vector2i.RIGHT, Vector2i.UP]
	const BANK_GOAL := 1000000
	# Existing native TransmissionManager rewards; claims remain server-owned.
	const DEPTH_BONUS_VALUES := {1: 1000, 2: 3000, 7: 25000}
	const PLAN_RADIUS := 14
	const SHELTER_CLEAR_USEC := 2_000_000
	const FAILED_GOAL_LIMIT := 32
	const GOAL_PATH_LIMIT := 96
	var host: Node
	var mode := ""
	var target := Vector2i(-1, -1)
	var _route: Array[Vector2i] = []
	var _returning := false
	var _was_alive := false
	var _shops: Dictionary = {}
	var _depth_bonus_rows: Dictionary = {}
	var _plan_after := 0.0
	var _service_after := 0.0
	var _stuck_time := 0.0
	var _navigation_goal := Vector2(INF, INF)
	var _progress_goal := Vector2(INF, INF)
	var _progress_distance := INF
	var _blocked: Dictionary = {}
	var _name := "Practice_Bot"
	var _life_player: Node
	var _service_stage := ""
	var _shop_script := ""
	var _shop_traded := false
	var _defense_id := ""
	var _defense_after := 0.0
	var _threat_count := 0
	var _shelter := false
	var _shelter_clear_deadline_usec := 0
	var _survey := false
	var _survey_destination := -1
	var _bags: Dictionary = {}
	var _bag_id := ""
	var _bag_cell := Vector2i(-1, -1)
	var _bag_after := 0.0
	var _fuel_after := 0.0
	var _fuel_anchor := Vector2i(-1, -1)
	var _fuel_route: Array[Vector2i] = []
	var _fuel_route_offsets: Dictionary = {}
	var _fuel_approach_cost := INF
	var _fuel_empty_reserve := INF
	var _fuel_loaded_reserve := INF
	var _fuel_horizontal_step := 0.08
	var _fuel_vertical_step := 0.16 / 1.5
	var _investment: Dictionary = {}
	var _invested := false
	var _best_ore_unit_value := 0.0
	var _capacity_limited_unit_value := 0.0
	var _fuel_unlock_cost := INF
	var _fuel_unlock_cell := Vector2i(-1, -1)
	var _goal_attempt: Dictionary = {}
	var _failed_goals: Dictionary = {}
	# One actual world owns expedition/economy knowledge; ordinary life resets
	# must not make a refilled copy of the same failed trip look productive.
	var _memory_world: WorldData
	var _fight_time := 0.0
	var _fight_id := ""
	var _route_control := false
	var _control_rejected := false
	var _rejected_time := 0.0
	var _waypoint_failures: Dictionary = {}
	var _escape_waypoint := Vector2i(-1, -1)
	var _escape_after := 0.0

	func _init(main_host: Node, _random_seed: int = -1) -> void:
		host = main_host
		_memory_world = host.world
		# Method Callables are weak: discarded fixture brains cannot own input.
		host.bot_control = _native_control
		if host.coop != null:
			# A standard method Callable is weak; unlike a capturing lambda it
			# does not keep discarded RefCounted fixture brains subscribed.
			host.coop.network.world_event.connect(_cash_event)

	func _cash_event(event: Dictionary) -> void:
		if str(event.get("type", "")) != "pvp_tick":
			return
		var latest: Dictionary = {}
		for record in event.get("bags", []):
			if not record is Dictionary:
				continue
			var id: String = str(record.get("id", ""))
			var amount: float = float(record.get("amount", 0))
			var point := Vector2(float(record.get("x", 0)), float(record.get("y", 0)))
			if not id.is_empty() and amount > 0.0 and is_finite(amount) and is_finite(point.x) and is_finite(point.y):
				latest[id] = {"point": point, "amount": amount}
		# Every tick is a full public snapshot, including an empty bag list.
		_bags = latest
		if not _bag_id.is_empty() and not _bags.has(_bag_id):
			_clear_cash_goal()

	func _clear_cash_goal() -> void:
		if not _bag_id.is_empty():
			_route.clear()
			_plan_after = 0.0
		_bag_id = ""
		_bag_cell = Vector2i(-1, -1)

	func _sync_world_memory() -> bool:
		if _memory_world == host.world:
			return false
		_memory_world = host.world
		_failed_goals.clear()
		_goal_attempt.clear()
		_best_ore_unit_value = 0.0
		_fuel_unlock_cost = INF
		_fuel_unlock_cell = Vector2i(-1, -1)
		_bags.clear()
		return true

	func _observe_goal_fuel() -> void:
		if not _goal_attempt.is_empty() and _was_alive and _life_player == host.player and host.player_alive:
			_goal_attempt.spent = maxf(float(_goal_attempt.spent), float(_goal_attempt.fuel) - host.data.player_fuel)

	func _refresh_fuel_unlock() -> void:
		# A local scan or respawn need not rediscover a still-existing seam.
		# Excavation or an already sufficient tank makes its unlock obsolete.
		if _raw(_fuel_unlock_cell) < 6 or _raw(_fuel_unlock_cell) > 24 or _fuel_unlock_cost <= host.data.player_max_fuel:
			_fuel_unlock_cost = INF
			_fuel_unlock_cell = Vector2i(-1, -1)

	func _observe_fuel_unlock(cell: Vector2i, needed: float) -> void:
		if not is_finite(_fuel_approach_cost):
			return
		# Capacity funds a complete trip from the fuel shop, not just the
		# remainder observed after arriving at a deep working face.
		var full_needed := needed + _fuel_approach_cost
		if cell == _fuel_unlock_cell:
			_fuel_unlock_cost = full_needed
			_refresh_fuel_unlock()
		elif full_needed > host.data.player_max_fuel and full_needed < _fuel_unlock_cost:
			_fuel_unlock_cost = full_needed
			_fuel_unlock_cell = cell

	func reset() -> void:
		_sync_world_memory()
		_observe_goal_fuel()
		_finish_goal_attempt()
		_clear_cash_goal()
		_bag_after = 0.0
		_route.clear()
		_shops.clear()
		_depth_bonus_rows.clear()
		_fuel_after = 0.0
		_fuel_anchor = Vector2i(-1, -1)
		_fuel_route.clear()
		_fuel_route_offsets.clear()
		_fuel_approach_cost = INF
		_fuel_empty_reserve = INF
		_fuel_loaded_reserve = INF
		_capacity_limited_unit_value = 0.0
		_reset_navigation()
		_blocked.clear()
		_waypoint_failures.clear()
		_returning = false
		_was_alive = false
		_life_player = null
		_service_stage = ""
		_shop_script = ""
		_shop_traded = false
		_plan_after = 0.0
		_service_after = 0.0
		_stuck_time = 0.0
		_navigation_goal = Vector2(INF, INF)
		_progress_goal = Vector2(INF, INF)
		_progress_distance = INF
		_defense_id = ""
		_defense_after = 0.0
		_threat_count = 0
		_shelter = false
		_shelter_clear_deadline_usec = 0
		_survey = false
		_survey_destination = -1
		_investment.clear()
		_invested = false
		_fight_time = 0.0
		_fight_id = ""
		target = Vector2i(-1, -1)
		host.agent_axes = Vector2.ZERO
		host.bot_attack_enabled = false
		host.bot_attack_target = ""
		mode = ""

	func tick(delta: float) -> void:
		_route_control = false
		if _sync_world_memory():
			reset()
		_observe_goal_fuel()
		host.agent_axes = Vector2.ZERO
		_navigation_goal = Vector2(INF, INF)
		host.bot_attack_enabled = false
		host.bot_attack_target = ""
		if host.scene_name != "Game" or host.player == null or not host.player_alive:
			if _was_alive:
				print("PRACTICE_BOT_DIED name=", _name)
			_bags.clear()
			reset()
			return
		_name = str(host.coop.network.username) if host.coop != null else "Practice_Bot"
		if not _was_alive or _life_player != host.player:
			if _was_alive:
				_bags.clear()
			reset()
			_was_alive = true
			_life_player = host.player
			print("PRACTICE_BOT_ALIVE name=", _name, " hull=", host.data.player_hp)
			_find_shops()
		_plan_after = maxf(0.0, _plan_after - delta)
		_service_after = maxf(0.0, _service_after - delta)
		_bag_after = maxf(0.0, _bag_after - delta)
		_fuel_after = maxf(0.0, _fuel_after - delta)
		for cell in _blocked.keys():
			_blocked[cell] -= delta
			if _blocked[cell] <= 0.0:
				_blocked.erase(cell)
		var position: Vector2 = host.player.position_unity
		var defender := _defense_target(position, delta)
		if _handle_panels():
			_clear_cash_goal()
			return
		if host.paused:
			_clear_cash_goal()
			return
		_update_fuel_route(position)
		var reserve := _fuel_reserve(_cell(position))
		var cargo: int = host.data.player_current_cargo_weight
		if not _returning and cargo >= maxi(1, host.data.player_max_cargo_weight - 1) and host.data.player_fuel > reserve:
			_capacity_limited_unit_value = float(_cargo_value()) / host.data.player_max_cargo_weight
		if host.data.player_fuel <= reserve or cargo >= maxi(1, host.data.player_max_cargo_weight - 1) or _repair_trip_available(cargo) or (cargo > 0 and _bank_ready()):
			if not _returning:
				_clear_cash_goal()
				_route.clear()
				_service_stage = "sell" if cargo > 0 else _after_sale()
			_returning = true
		if cargo > 0 and _bank_ready():
			_service_stage = "sell"
		if not _returning and _cell(position).y <= 4 and cargo == 0:
			var service := _after_sale()
			if service != "fuel":
				_returning = true
				_service_stage = service
		if _returning:
			_finish_goal_attempt()
		if not defender.is_empty():
			_clear_cash_goal()
			var enemy_hull := float(defender.state.get("player_hp", host.data.player_max_hp))
			var protect: bool = host.data.player_money + _cargo_value() >= 5000 or _cargo_value() >= 1000
			if protect or _fight_time >= 2.0 or host.data.player_hp <= host.data.player_max_hp * 0.35 or enemy_hull > host.data.player_hp * 1.75 or _threat_count > 1 or host.data.player_fuel <= reserve:
				_escape_tick(position, defender)
			else:
				_attack_tick(position, defender, "retaliate")
			return
		if host.player.is_digging_side or host.player.is_digging_bottom:
			_clear_cash_goal()
			# Stock digging finishes asynchronously, including the server's mine reply.
			_stuck_time = 0.0
			_rejected_time = 0.0
			_control_rejected = false
			return
		if _service_after > 0.0:
			_clear_cash_goal()
			return
		if host.data.player_money >= BANK_GOAL:
			_set_mode("banked", "awaiting round authority")
			return
		if _navigation_escape(position, delta):
			pass
		elif _cash_tick(position):
			pass
		elif _returning:
			_return_tick(position)
		else:
			_mining_tick(position)
		var axes: Vector2 = _avoid_peers(host.agent_axes, position)
		host.agent_axes = _avoid_hazards(axes, position)
		# Only a new waypoint or a new closest approach is progress. Oscillation
		# against a collider must not keep resetting the recovery deadline.
		var goal_distance: float = position.distance_to(_navigation_goal) if _navigation_goal.is_finite() else INF
		if not _navigation_goal.is_finite():
			_stuck_time = 0.0
			_progress_goal = Vector2(INF, INF)
			_progress_distance = INF
		elif _navigation_goal != _progress_goal or goal_distance < _progress_distance - 0.1:
			_progress_goal = _navigation_goal
			_progress_distance = goal_distance
			_stuck_time = 0.0
		else:
			_stuck_time += delta
		# A rejected control still has intent. Do not let a no-op, a fresh plan,
		# or small alignment oscillations reset the rejection deadline.
		_rejected_time = _rejected_time + delta if _control_rejected else 0.0
		_control_rejected = false
		if _stuck_time > 2.5 or _rejected_time > 2.5:
			_recover_navigation(position)

	func _cash_score(bag: Dictionary, start: Vector2i, finish: Vector2i, steps: int) -> float:
		var point: Vector2 = bag.point
		if not _open(finish) or _blocked.has(finish) or not _waypoint_retry_allowed(finish) or _peer_occupies(finish):
			return -INF
		for peer in host.coop.network.peers.values():
			if _peer_near(peer, point):
				return -INF
		# Banking/fuel trips never descend or leave their immediate corridor
		# for cash. In particular an emergency escape remains an escape.
		if _returning and (steps > 3 or finish.y > start.y or _shelter or _defense_after > 0.0):
			return -INF
		var travel_fuel := float(steps) * maxf(_fuel_horizontal_step, _fuel_vertical_step)
		var reserve := _fuel_reserve(finish, travel_fuel)
		if host.data.player_fuel <= reserve + travel_fuel + 0.5:
			return -INF
		var quote: float = host.fuel_pricing.price_per_gallon if host.fuel_pricing != null and host.fuel_pricing.available() else 0.0
		var profit: float = float(bag.amount) - travel_fuel * 2.0 * quote
		if profit < maxf(5.0, quote * 0.1):
			return -INF
		return profit / (0.5 + float(steps) * 0.3)

	func _cash_tick(position: Vector2) -> bool:
		if _bags.is_empty() or host.coop.network.has_pending_actions():
			_clear_cash_goal()
			return false
		var start := _cell(position)
		if not _open(start):
			_clear_cash_goal()
			return false
		if not _bag_id.is_empty():
			var bag: Dictionary = _bags.get(_bag_id, {})
			if bag.is_empty():
				_clear_cash_goal()
			else:
				var finish := _cell(bag.point)
				var moved := finish != _bag_cell
				var steps: int = _route.size() if not moved else absi(finish.x - start.x) + absi(finish.y - start.y)
				var safe := _cash_score(bag, start, finish, steps) > 0.0
				for cell in _route:
					if not _open(cell) or _blocked.has(cell) or not _waypoint_retry_allowed(cell):
						safe = false
						break
				if not _route.is_empty() and _peer_occupies(_route[0]):
					safe = false
				if not safe:
					_clear_cash_goal()
				elif not moved:
					_set_mode("cash", _bag_id)
					# Keep the final open waypoint for native braking until the
					# server's next full snapshot confirms contact collection.
					if _route.is_empty():
						_route.append(_bag_cell)
					_follow_route(position)
					return true
				elif _bag_after > 0.0:
					# A falling/moving bag invalidates the old route immediately,
					# but cannot trigger a new breadth-first search every frame.
					_route.clear()
					return true
				else:
					_clear_cash_goal()
		if _bag_after > 0.0:
			return false
		_bag_after = 0.6
		# One bounded open-only BFS serves the whole public snapshot. No bag
		# pursuit ever drills a shortcut or treats solid ore as a transit tile.
		var queue: Array[Vector2i] = [start]
		var previous: Dictionary = {}
		var distances: Dictionary = {start: 0}
		var index := 0
		var limit: int = 3 if _returning else PLAN_RADIUS * 2
		while index < queue.size() and index < 960:
			var cell: Vector2i = queue[index]
			index += 1
			var steps: int = distances[cell]
			if steps >= limit:
				continue
			for direction in DIRECTIONS:
				var next: Vector2i = cell + direction
				if distances.has(next) or next.x < host.world.surface_left() or next.x >= host.data.earthWidth or next.y < 2 or next.y > _depth_limit() or absi(next.x - start.x) > PLAN_RADIUS:
					continue
				if not _open(next) or _blocked.has(next) or not _waypoint_retry_allowed(next) or _peer_occupies(next):
					continue
				var travel_fuel := float(steps + 1) * maxf(_fuel_horizontal_step, _fuel_vertical_step)
				if host.data.player_fuel <= _fuel_reserve(next, travel_fuel) + travel_fuel + 0.5:
					continue
				distances[next] = steps + 1
				previous[next] = cell
				queue.append(next)
		var chosen := ""
		var best := 0.0
		var destination := Vector2i(-1, -1)
		for id in _bags:
			var bag: Dictionary = _bags[id]
			var finish := _cell(bag.point)
			if not distances.has(finish):
				continue
			var score := _cash_score(bag, start, finish, int(distances[finish]))
			if score > best:
				best = score
				chosen = str(id)
				destination = finish
		if chosen.is_empty():
			return false
		_bag_id = chosen
		_bag_cell = destination
		_route = _reconstruct(previous, start, destination)
		if _route.is_empty():
			_route.append(destination)
		_survey = false
		_set_mode("cash", chosen)
		_follow_route(position)
		return true

	func _update_fuel_route(position: Vector2) -> void:
		var start := _cell(position)
		if start == _fuel_anchor and _fuel_after > 0.0:
			return
		# Cell transitions and a modest terrain/recovery refresh share one bounded
		# search. Hot planner reserve lookups never search the world themselves.
		_fuel_anchor = start
		_fuel_after = 0.75
		var horizontal_speed: float = host.data.player_horizontal_speed
		var vertical_speed: float = host.data.player_vertical_speed
		# Clear stock-pod ascent measured about 4.8 tiles/s in native checks.
		# Budget at 2.5 tiles/s, retaining the separate recovery/corner margin.
		_fuel_horizontal_step = 0.16 / maxf(0.5, minf(2.5, horizontal_speed * 0.5))
		_fuel_vertical_step = 0.16 / maxf(0.5, minf(2.5, vertical_speed * 0.5))
		_fuel_route = _surface_route(start)
		if start.y > 4 and _fuel_route.is_empty():
			_fuel_route = _surface_route(start, true)
		if start.y > 4 and _fuel_route.is_empty():
			# A pose-specific collision must not erase the only opened escape.
			# Retry known air only after preferred safe searches are exhausted.
			_fuel_route = _surface_route(start, true, true)
		_fuel_empty_reserve = INF
		_fuel_loaded_reserve = INF
		_fuel_approach_cost = INF
		_fuel_route_offsets.clear()
		_fuel_route_offsets[start] = 0.0
		if start.y > 4 and _fuel_route.is_empty():
			# A disconnected pocket is an emergency, not a cheap imaginary ascent.
			return
		if not _shops.has("FuelShopManager") or not _shops.has("MineralBuyerManager"):
			_find_shops()
		if not _shops.has("FuelShopManager"):
			return
		var route_fuel := 0.0
		var approach_fuel := 0.0
		var previous := start
		var previous_direction := Vector2i.ZERO
		var turns := 0
		for cell in _fuel_route:
			var direction := cell - previous
			var movement_fuel := _fuel_vertical_step if direction.y != 0 else _fuel_horizontal_step
			route_fuel += movement_fuel
			approach_fuel += movement_fuel
			if not _open(cell):
				# Stock drilling burns .33/s; the authored step is .4 * drill speed.
				route_fuel += _dig_fuel(cell)
			# A future goal already on the escape route must not pay for retracing
			# the completed prefix and then ascending that same prefix again.
			_fuel_route_offsets[cell] = -route_fuel
			if previous_direction != Vector2i.ZERO and direction != previous_direction:
				turns += 1
			previous_direction = direction
			previous = cell
		var exit := position if start.y <= 4 else Vector2(previous.x + 0.5, -previous.y + 0.5)
		var fuel_door: Vector2 = _shops["FuelShopManager"]
		_fuel_approach_cost = approach_fuel + _surface_fuel(exit, fuel_door)
		# Two seconds idle settling, five seconds powered recovery, and a capped
		# corner allowance. Neither depth nor path length multiplies this margin.
		var margin := 0.08 * 2.0 + 0.16 * 5.0 + 0.16 * 0.2 * mini(turns, 10)
		_fuel_empty_reserve = route_fuel + _surface_fuel(exit, fuel_door) + margin
		if _shops.has("MineralBuyerManager"):
			var buyer_door: Vector2 = _shops["MineralBuyerManager"]
			_fuel_loaded_reserve = route_fuel + _surface_fuel(exit, buyer_door) + _surface_fuel(buyer_door, fuel_door) + margin

	func _surface_fuel(from: Vector2, to: Vector2) -> float:
		# Surface navigation lifts above the pavement before settling at a door.
		return absf(to.x - from.x) * _fuel_horizontal_step + (maxf(0.0, -2.7 - from.y) + maxf(0.0, -2.7 - to.y)) * _fuel_vertical_step

	func _fuel_reserve(cell: Vector2i, return_travel: float = 0.0, carrying_ore: bool = false) -> float:
		var loaded: bool = carrying_ore or host.data.player_current_cargo_weight > 0
		var reserve := _fuel_loaded_reserve if loaded else _fuel_empty_reserve
		# Future nodes retreat through their newly opened outbound tunnel, or join
		# the cached escape route directly. Both are constant-time budget lookups.
		# The depth floor is an alternative lower bound, never added to the route.
		var connector := minf(return_travel, float(_fuel_route_offsets.get(cell, INF)))
		return maxf(reserve + connector, float(maxi(0, cell.y - 4)) * _fuel_vertical_step + 0.96)

	func _peer_near(peer: Dictionary, position: Vector2) -> bool:
		var state: Dictionary = peer.get("state", {})
		return str(peer.get("player_id", "")) != host.coop.network.player_id and bool(state.get("alive", true)) and str(state.get("building", "")).is_empty() and position.distance_squared_to(Vector2(float(state.get("x", 0)), float(state.get("y", 0)))) <= 9.0

	func _aimed_at_us(peer: Dictionary, position: Vector2) -> bool:
		var state: Dictionary = peer.state
		var drill := Vector2(float(state.get("drill_x", 0)), float(state.get("drill_y", 0)))
		if drill.length_squared() < 0.25 or drill.y > 0.5:
			return false
		var offset := position - Vector2(float(state.get("x", 0)), float(state.get("y", 0)))
		var direction := drill.normalized()
		return offset.dot(direction) > 0.0 and absf(offset.cross(direction)) < 0.9

	func _defense_target(position: Vector2, delta: float) -> Dictionary:
		_defense_after = maxf(0.0, _defense_after - delta)
		_threat_count = 0
		var chosen: Dictionary = {}
		var nearest := INF
		var inside: bool = host.coop.pvp.building_pending or not host.coop.pvp.building.is_empty()
		for peer in host.coop.network.peers.values():
			if not _peer_near(peer, position):
				continue
			# Hull loss does not identify an attacker: crashes and terrain
			# must not manufacture a fight with an idle nearby miner.
			if _aimed_at_us(peer, position):
				_threat_count += 1
				var state: Dictionary = peer.state
				var distance := position.distance_squared_to(Vector2(float(state.get("x", 0)), float(state.get("y", 0))))
				if distance < nearest:
					nearest = distance
					chosen = peer
		if inside:
			_defense_id = ""
			_defense_after = 0.0
			_fight_id = ""
			_fight_time = 0.0
			if _shelter and _threat_count > 0:
				# Native shop entry pauses game time, but incoming PvP threats
				# and the quiet-time exit condition still use real time.
				_shelter_clear_deadline_usec = Time.get_ticks_usec() + SHELTER_CLEAR_USEC
			return {}
		if not chosen.is_empty():
			_defense_id = str(chosen.player_id)
			_defense_after = 2.0
		elif _defense_after > 0.0:
			chosen = host.coop.network.peers.get(_defense_id, {})
			if chosen.is_empty() or not _peer_near(chosen, position):
				chosen = {}
		if chosen.is_empty():
			_defense_id = ""
			_defense_after = 0.0
		var fight := str(chosen.get("player_id", ""))
		if fight != _fight_id:
			_fight_id = fight
			_fight_time = 0.0
		if not fight.is_empty():
			_fight_time += delta
		return chosen

	func _attack_tick(position: Vector2, peer: Dictionary, value: String) -> void:
		var state: Dictionary = peer.state
		var offset := Vector2(float(state.x), float(state.y)) - position
		# The native drill only reaches sideways or down. Lifting toward an
		# overhead craft cannot retaliate and enters its downward drill corridor.
		if offset.y > 0.65:
			_escape_tick(position, peer)
			return
		host.bot_attack_enabled = true
		host.bot_attack_target = str(peer.player_id)
		_set_mode(value, str(peer.get("name", "Miner")))
		var axes := Vector2.ZERO
		if absf(offset.x) > 0.65:
			axes.x = signf(offset.x)
		if offset.y < -0.65:
			axes.y = -1.0
		host.agent_axes = _avoid_hazards(axes, position)

	func _escape_tick(position: Vector2, peer: Dictionary) -> void:
		_set_mode("escape", str(peer.get("name", "Miner")))
		_returning = true
		_service_stage = "sell" if host.data.player_current_cargo_weight > 0 else "fuel"
		# Surface doors are normal protected interiors, not invulnerability granted
		# by the brain. Entry must still cross the authored trigger and server ack.
		if _cell(position).y <= 4:
			var safest := ""
			var best := INF
			var enemy := Vector2(float(peer.state.x), float(peer.state.y))
			for shop in _shops:
				var door: Vector2 = _shops[shop]
				if (door - position).normalized().dot((enemy - position).normalized()) > 0.3:
					continue
				var cost := position.distance_to(door)
				if cost < best:
					best = cost
					safest = shop
			if not safest.is_empty():
				var door: Vector2 = _shops[safest]
				if absf(position.x - door.x) <= 0.75 and absf(position.y - door.y) <= 0.8:
					_shelter = true
					_shelter_clear_deadline_usec = Time.get_ticks_usec() + SHELTER_CLEAR_USEC
					host.ui._set_panel(safest, true)
				else:
					var shelter_axes := _surface_axes(position, door)
					if enemy.y > position.y + 0.6:
						shelter_axes.y = minf(0.0, shelter_axes.y)
					host.agent_axes = _avoid_hazards(shelter_axes, position)
				return
		var offset := position - Vector2(float(peer.state.x), float(peer.state.y))
		var cell := _cell(position)
		var axes := Vector2.ZERO
		# Side drills cannot reach a craft that lifts clear of their corridor.
		# When attacked from above, leave laterally rather than climb into it.
		if offset.y >= -0.6 and _open(cell + Vector2i.UP):
			axes.y = 1.0
		if absf(offset.x) > 0.2:
			var side := Vector2i(int(signf(offset.x)), 0)
			if _open(cell + side):
				axes.x = float(side.x)
		elif axes.y == 0.0:
			for side in [Vector2i.LEFT, Vector2i.RIGHT]:
				if _open(cell + side):
					axes.x = float(side.x)
					break
		# A narrow shaft may have no lateral exit. Release lift and descend
		# through known open space rather than route upward into the attacker.
		if axes == Vector2.ZERO and offset.y < -0.6 and _open(cell + Vector2i.DOWN) and _open(host.player.getBlockPositionBottomPlayer()):
			axes.y = -1.0
		if axes == Vector2.ZERO:
			_route = _surface_route(cell)
			_follow_route(position)
			axes = host.agent_axes
			# A surface route is only a fallback, not permission to approach the
			# threat. In particular its first ascent must not undo the test above.
			if axes.y * offset.y < 0.0:
				axes.y = 0.0
			if axes.x * offset.x < 0.0:
				axes.x = 0.0
		else:
			_route.clear()
		host.agent_axes = _avoid_hazards(axes, position)


	func _find_shops() -> void:
		for trigger in host.scene_triggers:
			if str(trigger.script) == "TransmissionTrigger":
				var index := int(trigger.properties.get("transmission_index", -1))
				if DEPTH_BONUS_VALUES.has(index):
					var marker: Node2D = host.bridge.nodes.get(trigger.id)
					if marker != null:
						_depth_bonus_rows[index] = ceili(marker.global_position.y + 0.5)
			if str(trigger.script) != "ShopDoorCollision":
				continue
			var owner: String = host.bridge.component_owner(trigger.properties.get("linked_shop_object", {}))
			for script in GameUI.SHOP_SCRIPTS:
				if owner == host.ui._panel(script):
					var door: Node2D = host.bridge.nodes.get(trigger.id)
					if door != null:
						_shops[script] = door.global_position / Vector2(1, -1)

	func _next_depth_bonus() -> Vector2i:
		var bonus := Vector2i(-1, 0)
		for index in _depth_bonus_rows:
			if bool(host.data.transmissions[index].displayed):
				continue
			var row := int(_depth_bonus_rows[index])
			if bonus.x < 0 or row < bonus.x:
				bonus = Vector2i(row, int(DEPTH_BONUS_VALUES[index]))
		return bonus

	func _handle_panels() -> bool:
		var authority: PvpView = host.coop.pvp
		if _shop_script.is_empty():
			for script in GameUI.SHOP_SCRIPTS:
				if bool(host.ui.panel_active.get(script, false)):
					_shop_script = script
					_shop_traded = false
					break
		if not _shop_script.is_empty():
			# Entry and exit both suspend navigation, even while the panel is
			# hidden. Only the server-confirmed interior permits a transaction.
			if authority.building_pending:
				return true
			if authority.building == _shop_script:
				if host.coop.network.has_pending_actions():
					return true
				if not _shop_traded:
					if _shop_script == "MineralBuyerManager":
						_shop_traded = _sell()
					elif _shop_script == "FuelShopManager":
						_shop_traded = _refuel()
					elif _shop_script == "UpgradeShopUI":
						_shop_traded = _buy_upgrade()
					elif _shop_script == "ItemShopManager":
						_shop_traded = _repair()
					else:
						_shop_traded = true
				if _shelter and Time.get_ticks_usec() < _shelter_clear_deadline_usec:
					return true
				_shelter = false
				if _shop_traded and bool(host.ui.panel_active.get(_shop_script, false)):
					host.ui._close_panel(_shop_script)
				return true
			if authority.building.is_empty() and not bool(host.ui.panel_active.get(_shop_script, false)):
				var completed := _shop_script
				var traded := _shop_traded
				_shop_script = ""
				_shop_traded = false
				if traded:
					if completed == "MineralBuyerManager":
						_service_stage = _after_sale()
						_returning = true
					elif completed == "ItemShopManager":
						_service_stage = _after_repair()
						_returning = true
					elif completed == "UpgradeShopUI":
						_investment.clear()
						_service_stage = "fuel"
						_returning = true
					elif completed == "FuelShopManager":
						_returning = host.data.player_current_cargo_weight > 0
						_service_stage = "sell" if _returning else ""
						_plan_after = 0.0
						_invested = false
				_service_after = 0.6
			return true
		if authority.building_pending or not authority.building.is_empty():
			return true
		for script in GameUI.PANEL_SCRIPTS:
			if not GameUI.SHOP_SCRIPTS.has(script) and bool(host.ui.panel_active.get(script, false)):
				host.ui._close_panel(script)
		return false
	# These are banking/spending decisions, not a winner or reset authority.
	func _cargo_value() -> int:
		var total := 0
		for mineral in host.data.player_cargo:
			total += int(host.data.player_cargo[mineral]) * int(host.data.minerals[mineral].ore_value)
		return total

	func _bank_ready() -> bool:
		return host.data.player_money + _cargo_value() >= BANK_GOAL

	func _depth_limit() -> int:
		# The actual tank and per-node drilling budget constrain reach, rather
		# than an arbitrary shallow row hiding valuable seams.
		return mini(host.data.earthHeight - 13, 4 + floori(maxf(0.0, host.data.player_max_fuel - 1.0) / maxf(0.001, _fuel_vertical_step)))

	func _dig_fuel(cell: Vector2i) -> float:
		var modifier: float = host.player.getDepthModifier(-cell.y)
		return maxf(_fuel_horizontal_step, _fuel_vertical_step) + 0.33 * (1.0 / maxf(0.1, 0.4 * host.data.player_dig_speed * modifier) + 0.5)

	func _fuel_money() -> int:
		if host.fuel_pricing == null or not host.fuel_pricing.available():
			return -1
		return ceili(host.data.player_max_fuel * host.fuel_pricing.price_per_gallon)

	func _service_money() -> int:
		var fuel := _fuel_money()
		if fuel < 0:
			return -1
		return fuel + maxi(0, host.data.player_max_hp - host.data.player_hp) * 15 + 20

	func _mineral_reward(raw: int) -> Dictionary:
		# Terrain sprites have legacy display prices for some treasures.
		# GameData supplies native pickup awards; its prices match the authority.
		return host.data.minerals[WorldData.minerals_list[raw - 6].name]

	func _observe_ore(mineral: Dictionary) -> void:
		if int(mineral.weight) <= host.data.player_max_cargo_weight:
			_best_ore_unit_value = maxf(_best_ore_unit_value, float(mineral.ore_value) / maxi(1, int(mineral.weight)))

	func _finish_goal_attempt() -> void:
		if _goal_attempt.is_empty():
			return
		var cell: Vector2i = _goal_attempt.cell
		_observe_goal_fuel()
		var spent := float(_goal_attempt.spent)
		# A disappeared goal is success/exhaustion, not evidence of a bad trip.
		# Require sampled fuel expenditure or exhausted native recovery, so a
		# full bay, first input clamp or immediate service replan cannot poison
		# a goal that was never meaningfully attempted.
		if _raw(cell) == int(_goal_attempt.raw) and (spent >= 0.5 or bool(_goal_attempt.get("rejected", false))):
			var path: Dictionary = {}
			for waypoint in _goal_attempt.path:
				path[waypoint] = _raw(waypoint)
				var support: Vector2i = waypoint + Vector2i.DOWN
				path[support] = _raw(support)
			if not _failed_goals.has(cell) and _failed_goals.size() >= FAILED_GOAL_LIMIT:
				_failed_goals.erase(_failed_goals.keys()[0])
			_failed_goals[cell] = {
				"raw": _goal_attempt.raw, "path": path,
				"trip_fuel": _goal_attempt.trip_fuel,
				"drill": host.data.player_dig_speed, "tank": host.data.player_max_fuel
			}
		else:
			_failed_goals.erase(cell)
		_goal_attempt.clear()

	func _goal_retry_allowed(cell: Vector2i, trip_fuel: float) -> bool:
		if not _failed_goals.has(cell):
			return true
		var failure: Dictionary = _failed_goals[cell]
		# Refilling, waiting, cash changes and unrelated excavation are not an
		# improved expedition. Only equipment, its corridor, or a materially
		# cheaper newly planned route can invalidate the remembered outcome.
		var improved: bool = _raw(cell) != int(failure.raw) or host.data.player_dig_speed > float(failure.drill) or host.data.player_max_fuel > float(failure.tank)
		improved = improved or trip_fuel + 0.5 < float(failure.trip_fuel) * 0.75
		if not improved:
			for waypoint in failure.path:
				var old_raw := int(failure.path[waypoint])
				if old_raw != 0 and old_raw != -999 and old_raw >= -100 and _open(waypoint):
					improved = true
					break
		if improved:
			_failed_goals.erase(cell)
		return improved

	func _begin_goal_attempt(cell: Vector2i, trip_fuel: float) -> void:
		if not _goal_attempt.is_empty() and _goal_attempt.cell == cell:
			return
		_finish_goal_attempt()
		# Keep the original corridor even after navigation consumes waypoints;
		# snapshot its terrain only when the attempted expedition is abandoned.
		var path: Array[Vector2i] = []
		for index in range(mini(_route.size(), GOAL_PATH_LIMIT)):
			path.append(_route[index])
		_goal_attempt = {"cell": cell, "raw": _raw(cell), "fuel": host.data.player_fuel, "spent": 0.0, "trip_fuel": trip_fuel, "path": path}

	func _funded_fuel_upgrade(reserve: int, cash: int) -> Dictionary:
		var names: Array = GameUI.UPGRADE_NAMES.Fuel
		var current := names.find(str(host.data.current_upgrades.Fuel))
		var index := current + 1
		if current < 0 or index >= names.size():
			return {}
		var next_upgrade: Dictionary = host.data.upgrades.Fuel[names[index]]
		var full_refill := _fuel_money()
		var depth_bonus := _next_depth_bonus()
		var unlock_raw := _raw(_fuel_unlock_cell)
		var best: Dictionary = {}
		var best_cost := 0
		for opportunity in 2:
			var needed := _fuel_unlock_cost
			var revenue := 0.0
			var refill_loads := 1.0
			if opportunity == 0:
				if not is_finite(needed) or unlock_raw < 6 or unlock_raw > 24:
					continue
				# A known treasure pays once; regular cargo can repay in loads.
				revenue = float(_mineral_reward(unlock_raw).ore_value) if unlock_raw >= 16 else floori(_best_ore_unit_value * host.data.player_max_cargo_weight) * 3.0
				refill_loads = 1.0 if unlock_raw >= 16 else 3.0
			else:
				if depth_bonus.x < 0:
					continue
				needed = 2.0 * maxi(0, depth_bonus.x - 4) * _fuel_vertical_step + 0.96
				revenue = float(depth_bonus.y)
			if needed <= host.data.player_max_fuel:
				continue
			var total_price := int(next_upgrade.price)
			var target_index := index
			var target_effect := float(next_upgrade.effect)
			while target_effect < needed and target_index + 1 < names.size():
				target_index += 1
				var upgrade: Dictionary = host.data.upgrades.Fuel[names[target_index]]
				total_price += int(upgrade.price)
				target_effect = float(upgrade.effect)
			if target_effect < needed:
				continue
			var refill_delta := maxi(0, ceili(target_effect * host.fuel_pricing.price_per_gallon) - full_refill)
			var payback := revenue - refill_delta * refill_loads
			# Fund the complete sufficient chain, not a stranded intermediate.
			if total_price <= payback and cash - total_price >= reserve + refill_delta:
				if best.is_empty() or total_price < best_cost:
					best = {"category": "Fuel", "index": index, "price": int(next_upgrade.price)}
					best_cost = total_price
		return best

	func _choose_upgrade() -> Dictionary:
		var reserve := _service_money()
		if _bank_ready() or reserve < 0 or _invested:
			return {}
		var cash: int = host.data.player_money
		var fuel_upgrade := _funded_fuel_upgrade(reserve, cash)
		if not fuel_upgrade.is_empty():
			return fuel_upgrade
		var remaining_goal := BANK_GOAL - cash - _cargo_value()
		# Preserve the first bay unlock when no funded earning-access tank
		# takes precedence. Later bays still need actual capacity evidence.
		if host.data.player_max_cargo_weight < 12 and cash >= 750 + reserve:
			return {"category": "Cargo", "index": 1, "price": 750}
		var load_value := floori(_best_ore_unit_value * host.data.player_max_cargo_weight)
		for category in ["Cargo", "Drill"]:
			if category == "Cargo" and _capacity_limited_unit_value <= 0.0:
				continue
			var names: Array = GameUI.UPGRADE_NAMES[category]
			var current := names.find(str(host.data.current_upgrades[category]))
			var index := current + 1
			if current < 0 or index >= names.size():
				continue
			var upgrade: Dictionary = host.data.upgrades[category][names[index]]
			var price: int = int(upgrade.price)
			var payback := 0.0
			if category == "Cargo":
				var added_capacity: float = float(upgrade.effect) - host.data.player_max_cargo_weight
				var full_load_value: float = _capacity_limited_unit_value * host.data.player_max_cargo_weight
				var payoff_loads := minf(3.0, float(remaining_goal) / full_load_value)
				payback = _capacity_limited_unit_value * maxf(0.0, added_capacity) * payoff_loads
			else:
				# A drill must repay before the winning sale, not merely over
				# four hypothetical loads after this race has already ended.
				payback = minf(load_value * 4.0, float(remaining_goal)) * (1.0 - host.data.player_dig_speed / float(upgrade.effect))
			if price <= payback and cash - price >= reserve:
				return {"category": category, "index": index, "price": price}
		return {}

	func _after_repair() -> String:
		_investment = _choose_upgrade()
		return "upgrade" if not _investment.is_empty() else "fuel"

	func _repair_trip_available(cargo: int) -> bool:
		if host.data.player_hp > host.data.player_max_hp * 0.5:
			return false
		# Empty, cash-starved returns cannot repair anything. Earn a load
		# within the normal fuel budget instead of idling until fuel death.
		if cargo > 0:
			return true
		var fuel := _fuel_money()
		return fuel >= 0 and host.data.player_money - fuel >= 15

	func _after_sale() -> String:
		var fuel := _fuel_money()
		if not _bank_ready() and fuel >= 0 and host.data.player_hp < host.data.player_max_hp and host.data.player_money - fuel >= 15:
			return "repair"
		return _after_repair()

	func _buy_upgrade() -> bool:
		if not _shop_ready("UpgradeShopUI"):
			return false
		_investment = _choose_upgrade()
		if _investment.is_empty():
			return true
		var category: String = _investment.category
		host.ui.displayCategory(category)
		host.ui.displayPotentialUpgrade(int(_investment.index))
		host.ui.buyUpgrade()
		host.coop.network.send_state()
		_invested = true
		if category == "Cargo":
			# A larger bay needs its own real full-load evidence.
			_capacity_limited_unit_value = 0.0
		_fuel_after = 0.0
		_route.clear()
		return true

	func _repair() -> bool:
		if not _shop_ready("ItemShopManager"):
			return false
		var fuel := _fuel_money()
		if host.data.player_money >= BANK_GOAL or fuel < 0:
			return true
		# Unsold winning cargo is not banked cash. Preserve a critical hull
		# on the way to the buyer, but do not delay a healthy winning haul.
		if _bank_ready() and not _repair_trip_available(host.data.player_current_cargo_weight):
			return true
		var missing: int = maxi(0, host.data.player_max_hp - host.data.player_hp)
		var points := mini(missing, floori(float(maxi(0, host.data.player_money - fuel)) / 15.0))
		if points > 0:
			host.ui.addHull(points * 15)
			host.coop.network.send_state()
		return true


	func _shop_ready(script: String) -> bool:
		return bool(host.ui.panel_active.get(script, false)) and host.coop.pvp.building == script and not host.coop.pvp.building_pending and not host.coop.network.has_pending_actions()

	func _sell() -> bool:
		if not _shop_ready("MineralBuyerManager"):
			return false
		if host.data.player_current_cargo_weight <= 0:
			return true
		var before: int = host.data.player_money
		for mineral in host.data.player_cargo:
			if int(host.data.player_cargo[mineral]) > 0:
				_observe_ore(host.data.minerals[mineral])
		host.ui.sellAllMinerals()
		host.coop.network.send_state()
		print("PRACTICE_BOT_SOLD name=", _name, " earned=", host.data.player_money - before, " money=", host.data.player_money)
		return true

	func _refuel() -> bool:
		if not _shop_ready("FuelShopManager"):
			return false
		var missing: float = host.data.player_max_fuel - host.data.player_fuel
		if missing <= 0.0 or host.data.player_money <= 0 or host.data.player_money >= BANK_GOAL:
			return true
		if _bank_ready():
			# A winning haul still needs enough real fuel to reach the buyer.
			var position: Vector2 = host.player.position_unity
			_update_fuel_route(position)
			if host.data.player_fuel > _fuel_reserve(_cell(position)):
				return true
		if host.fuel_pricing == null or not host.fuel_pricing.available():
			_set_mode("fuel_wait", "AAA price")
			return false
		var budget := mini(host.data.player_money, ceili(missing * host.fuel_pricing.price_per_gallon))
		if budget <= 0:
			return true
		var before: int = host.data.player_money
		host.ui.addFuel(budget)
		host.coop.network.send_state()
		print("PRACTICE_BOT_REFUELED name=", _name, " paid=", before - host.data.player_money, " fuel=", host.data.player_fuel)
		return true

	func _return_tick(position: Vector2) -> void:
		_set_mode("return", _service_stage)
		if _cell(position).y > 4:
			if _route.is_empty():
				# Reuse the budgeted open route, or a supported side/downward
				# emergency connection. No second search every frame.
				_route.assign(_fuel_route)
			_follow_route(position)
			return
		_route.clear()
		if host.coop.network.has_pending_actions():
			return
		if _service_stage == "sell" and host.data.player_current_cargo_weight <= 0:
			_service_stage = _after_sale()
		if _service_stage.is_empty():
			_service_stage = "sell" if host.data.player_current_cargo_weight > 0 else _after_sale()
		if _service_stage == "fuel" and host.data.player_fuel >= host.data.player_max_fuel * 0.75 and host.data.player_current_cargo_weight == 0:
			_returning = false
			_service_stage = ""
			_plan_after = 0.0
			_invested = false
			return
		var shop: String = {"sell": "MineralBuyerManager", "repair": "ItemShopManager", "upgrade": "UpgradeShopUI"}.get(_service_stage, "FuelShopManager")
		if not _shops.has(shop):
			_find_shops()
			return
		var door: Vector2 = _shops[shop]
		if absf(position.x - door.x) > 0.75 or absf(position.y - door.y) > 0.8:
			host.agent_axes = _surface_axes(position, door)
			return
		host.ui._set_panel(shop, true)

	func _mining_tick(position: Vector2) -> void:
		_set_mode("mine", str(target))
		# Another miner may have exhausted the goal while we were travelling.
		# A surface survey also rechecks seams rather than crossing the whole map
		# blindly past newly reachable ore.
		if (_survey and _plan_after <= 0.0) or (not _survey and target.x >= 0 and _open(target)):
			_route.clear()
		if not _route.is_empty() and _route[0].y >= 5 and _peer_occupies(_route[0]):
			_blocked[_route[0]] = 4.0
			_route.clear()
			_plan_after = 0.0
		if _route.is_empty() and _plan_after <= 0.0:
			_plan_after = 0.6
			_plan_mine(_cell(position))
			if _route.is_empty() and _cell(position).y <= 4 and host.data.player_current_cargo_weight == 0 and host.data.player_fuel > 2.0:
				if host.data.player_fuel >= host.data.player_max_fuel * 0.75 or host.data.player_money <= 0:
					_plan_survey(_cell(position))
			if _route.is_empty():
				_returning = true
				_service_stage = "sell" if host.data.player_current_cargo_weight > 0 else _after_sale()
				return
		_follow_route(position)

	func _plan_survey(start: Vector2i) -> void:
		_survey = true
		# An exhausted local seam is a reason to survey another surface column,
		# not to idle at the shops or drill random dirt until the tank is empty.
		if _survey_destination < host.world.surface_left() or absi(start.x - _survey_destination) <= 1:
			_survey_destination = host.data.earthWidth - 2 if start.x < host.data.earthWidth / 2 else host.world.surface_left() + 1
		var destination := _survey_destination
		if start.y < 4 and _open(Vector2i(start.x, 4)):
			_route.append(Vector2i(start.x, 4))
		var step := 1 if destination > start.x else -1
		for x in range(start.x + step, destination + step, step):
			var cell := Vector2i(x, 4)
			if not _open(cell) or _blocked.has(cell) or not _waypoint_retry_allowed(cell):
				break
			_route.append(cell)
		if not _route.is_empty():
			target = _route.back()
			print("PRACTICE_BOT_TARGET name=", _name, " mode=survey tile=", target, " steps=", _route.size())

	func _plan_mine(start: Vector2i) -> void:
		_survey = false
		_refresh_fuel_unlock()
		var depth_bonus := _next_depth_bonus()
		var full_refill := _fuel_money()
		var service_capital := _service_money()
		# Preparation cannot overcome a tank that cannot make even the
		# fully opened vertical round trip to this authored reward.
		var can_prepare: bool = depth_bonus.x > 0 and full_refill >= 0 and 2.0 * maxi(0, depth_bonus.x - 4) * _fuel_vertical_step + 0.96 < host.data.player_max_fuel
		var frontier: Array[Vector2i] = [start]
		var costs: Dictionary = {start: 0.0}
		var return_costs: Dictionary = {start: 0.0}
		# Vector2i carries cumulative (cargo weight, native pickup value).
		var path_pickups: Dictionary = {start: Vector2i.ZERO}
		var previous: Dictionary = {}
		var visited: Dictionary = {}
		var best := Vector2i(-1, -1)
		var best_score := -INF
		var capacity_blocked := false
		var descent := Vector2i(-1, -1)
		var spare: int = host.data.player_max_cargo_weight - host.data.player_current_cargo_weight
		var bottom: Vector2i = host.player.getBlockPositionBottomPlayer()
		var bottom_raw := _raw(bottom)
		if bottom == start and bottom_raw >= 6 and bottom_raw <= 24:
			costs[start] = _dig_fuel(start)
			var starting_reward := _mineral_reward(bottom_raw)
			path_pickups[start] = Vector2i(int(starting_reward.weight) if bottom_raw <= 15 else 0, int(starting_reward.ore_value))
		while not frontier.is_empty() and visited.size() < 960:
			var cheapest := 0
			var first: Vector2i = frontier[0]
			# Open descent has zero search priority cost, so exhausted shallow
			# workings cannot hide existing deep shafts behind the node limit.
			# Every reweighted edge remains nonnegative; fuel admission and
			# whole-trip profit scoring still use the undiscounted actual costs.
			var cheapest_priority := float(costs[first]) - maxi(0, first.y - start.y) * _fuel_vertical_step
			for index in range(1, frontier.size()):
				var candidate_cell: Vector2i = frontier[index]
				var priority := float(costs[candidate_cell]) - maxi(0, candidate_cell.y - start.y) * _fuel_vertical_step
				if priority < cheapest_priority:
					cheapest = index
					cheapest_priority = priority
			var cell: Vector2i = frontier[cheapest]
			frontier.remove_at(cheapest)
			if visited.has(cell):
				continue
			visited[cell] = true
			var pickups: Vector2i = path_pickups[cell]
			var raw := _raw(cell)
			var is_pickup := raw >= 6 and raw <= 24
			var bonus_value: int = depth_bonus.y if depth_bonus.x >= 0 and cell.y >= depth_bonus.x else 0
			if can_prepare and raw >= 1 and raw <= 5 and cell.y > start.y and cell.y < depth_bonus.x:
				# Retain cash for this service cycle and, conservatively, a
				# complete refill per remaining vertical row. Preparation is
				# new excavation, never another trip into already-open air.
				var future_refills := (depth_bonus.x - cell.y) * full_refill
				if depth_bonus.y > future_refills and host.data.player_money >= future_refills + service_capital:
					bonus_value = depth_bonus.y - future_refills
			if is_pickup or bonus_value > 0:
				var pickup_weight := 0
				if is_pickup:
					var mineral := _mineral_reward(raw)
					pickup_weight = int(mineral.weight) if raw < 16 else 0
					if raw < 16:
						_observe_ore(mineral)
				var reserve := _fuel_reserve(cell, float(return_costs[cell]), pickups.x > 0)
				if is_pickup and pickup_weight <= host.data.player_max_cargo_weight:
					_observe_fuel_unlock(cell, float(costs[cell]) + reserve + 0.25)
				if (cell != start or cell == bottom) and not _blocked.has(cell) and _waypoint_retry_allowed(cell) and float(costs[cell]) + reserve + 0.25 < host.data.player_fuel:
					# Rank the entire trip, not just the one-way shaft. Avoid paying
					# fuel and travel time for a poor seam when a rich one is feasible.
					var trip_fuel := float(costs[cell]) + reserve
					var quote: float = host.fuel_pricing.price_per_gallon if host.fuel_pricing != null and host.fuel_pricing.available() else 0.0
					var profit := float(pickups.y + bonus_value) - trip_fuel * quote
					if not _goal_retry_allowed(cell, trip_fuel):
						continue
					if pickup_weight > spare or pickups.x > spare:
						if pickup_weight > spare and pickup_weight <= host.data.player_max_cargo_weight and profit > 0.0:
							capacity_blocked = true
						continue
					var score := profit / (0.55 + float(costs[cell]) + reserve * 0.4)
					# Stable tie-breaking avoids synchronized equal-cost choices.
					score *= 1.0 + float(absi((_name + str(cell)).hash()) % 17) * 0.003
					if score > maxf(0.0, best_score):
						best_score = score
						best = cell
				# Look through affordable pickups, but commit only the first
				# mineral below. Forecast cargo includes every intervening ore,
				# including an uncollected starting bottom-detector pickup.
				if is_pickup and ((cell == start and cell != bottom) or pickups.x > spare):
					continue
			# Bounded replanning can descend an existing shaft in sections even
			# when a broad open surface consumes the local search allowance.
			if _open(cell) and cell.y >= start.y + 8 and cell.y > descent.y and float(costs[cell]) + _fuel_reserve(cell, float(return_costs[cell]), spare < host.data.player_max_cargo_weight) + 1.0 < host.data.player_fuel:
				descent = cell
			for direction in DIRECTIONS:
				var next: Vector2i = cell + direction
				if next.x < host.world.surface_left() or next.x >= host.data.earthWidth or next.y < 4 or next.y > _depth_limit() or absi(next.x - start.x) > PLAN_RADIUS or _blocked.has(next) or not _waypoint_retry_allowed(next):
					continue
				var open := _open(next)
				if not open and (not _safe_dig(next) or direction == Vector2i.UP):
					continue
				# Side drilling needs support at departure and at the landing.
				if not open and direction.x != 0 and (not _drill_landing_in_bounds(next, float(direction.x)) or _open(cell + Vector2i.DOWN) or _open(next + Vector2i.DOWN)):
					continue
				if next.y >= 5 and _peer_occupies(next):
					continue
				var movement_fuel := _fuel_vertical_step if direction.y != 0 else _fuel_horizontal_step
				var cost := float(costs[cell]) + (movement_fuel if open else _dig_fuel(next))
				var return_fuel := minf(float(return_costs[cell]) + movement_fuel, float(_fuel_route_offsets.get(next, INF)))
				var next_raw := _raw(next)
				var reserve := _fuel_reserve(next, return_fuel, pickups.x > 0 or (next_raw >= 6 and next_raw <= 15))
				if cost + reserve + 0.25 >= host.data.player_fuel:
					if next_raw >= 6 and next_raw <= 24:
						var next_mineral: Dictionary = _mineral_reward(next_raw)
						if next_raw >= 16 or int(next_mineral.weight) <= host.data.player_max_cargo_weight:
							if next_raw < 16:
								_observe_ore(next_mineral)
							var needed := cost + reserve + 0.25
							_observe_fuel_unlock(next, needed)
					continue
				if not costs.has(next) or cost < float(costs[next]):
					costs[next] = cost
					return_costs[next] = return_fuel
					var reward := Vector2i.ZERO
					if next_raw >= 6 and next_raw <= 24:
						var mineral_reward := _mineral_reward(next_raw)
						reward = Vector2i(int(mineral_reward.weight) if next_raw <= 15 else 0, int(mineral_reward.ore_value))
					path_pickups[next] = pickups + reward
					previous[next] = cell
					frontier.append(next)
		if best.x < 0:
			# Heavy ore can fill the usable bay without reaching its weight
			# threshold. Require a profitable, reachable blocked pickup and
			# no fittable alternative before using this load as bay evidence.
			if capacity_blocked:
				_capacity_limited_unit_value = float(_cargo_value()) / host.data.player_max_cargo_weight
			if descent.x >= 0 and not frontier.is_empty() and host.data.player_current_cargo_weight == 0:
				# Only a truncated search needs an intermediate open-shaft goal.
				# A completed search has already exhausted this reachable window;
				# revisiting its deepest air burns fuel without expanding coverage.
				_survey = true
				target = descent
				_route = _reconstruct(previous, start, descent)
			return
		target = best
		if best == start:
			_route.assign([best])
		else:
			_route = _reconstruct(previous, start, best)
		# A valuable seam may sit behind cheap ore. Execute only its first
		# pickup, then replan against actual cargo and authority terrain.
		for index in range(_route.size()):
			var waypoint: Vector2i = _route[index]
			var waypoint_raw := _raw(waypoint)
			if waypoint_raw >= 6 and waypoint_raw <= 24:
				target = waypoint
				_route.resize(index + 1)
				break
		var target_raw := _raw(target)
		var target_pickups: Vector2i = path_pickups[target]
		_survey = target_raw < 6 or target_raw > 24
		_begin_goal_attempt(target, float(costs[target]) + _fuel_reserve(target, float(return_costs[target]), target_pickups.x > 0))
		var label := "Depth bonus" if _survey else str(WorldData.minerals_list[target_raw - 6].name)
		print("PRACTICE_BOT_TARGET name=", _name, " mode=mine tile=", target, " mineral=", label, " steps=", _route.size())

	func _surface_route(start: Vector2i, allow_dig: bool = false, retry_open: bool = false) -> Array[Vector2i]:
		var queue: Array[Vector2i] = [start]
		var previous: Dictionary = {}
		var visited: Dictionary = {}
		var priorities: Dictionary = {start: 0.0}
		var service_x := float(start.x) + 0.5
		var service := "MineralBuyerManager" if host.data.player_current_cargo_weight > 0 else "FuelShopManager"
		if _shops.has(service):
			var door: Vector2 = _shops[service]
			service_x = door.x
		var index := 0
		while index < queue.size() and index < 3200:
			# Optimize fuel for1600expansions, then spend at most1600more on
			# ascent-first feasibility. Reuse the frontier/parents: an optimization
			# budget exhausted in a wide cave must not erase an opened escape.
			var fuel_ranked := index < 1600
			var cheapest := index
			for candidate in range(index + 1, queue.size()):
				if fuel_ranked:
					var priority: float = priorities[queue[candidate]]
					var best_priority: float = priorities[queue[cheapest]]
					if priority < best_priority or (priority == best_priority and queue[candidate].y < queue[cheapest].y):
						cheapest = candidate
				elif queue[candidate].y < queue[cheapest].y:
					cheapest = candidate
			var swap := queue[index]
			queue[index] = queue[cheapest]
			queue[cheapest] = swap
			var cell := queue[index]
			index += 1
			visited[cell] = true
			if cell.y <= 4:
				return _reconstruct(previous, start, cell)
			var service_distance := absf(float(cell.x) + 0.5 - service_x)
			for direction in [Vector2i.UP, Vector2i.LEFT, Vector2i.RIGHT, Vector2i.DOWN]:
				var next: Vector2i = cell + direction
				if next.y < 4 or next.y > mini(host.data.earthHeight - 13, maxi(_depth_limit(), start.y + 2)) or not host.world.inBounds(next.x, next.y) or visited.has(next):
					continue
				var opened := _open(next)
				if (_blocked.has(next) or not _waypoint_retry_allowed(next)) and (not retry_open or not opened):
					continue
				if not opened:
					if not allow_dig or direction == Vector2i.UP or not _safe_dig(next):
						continue
					if direction.x != 0 and (not _drill_landing_in_bounds(next, float(direction.x)) or _open(cell + Vector2i.DOWN) or _open(next + Vector2i.DOWN)):
						continue
				# Reweight by the admissible vertical-plus-service-distance
				# lower bound. Ascent consumes that bound; detours still cost fuel.
				var edge_fuel := (_fuel_vertical_step if direction.y != 0 else _fuel_horizontal_step) + float(direction.y) * _fuel_vertical_step
				edge_fuel += (absf(float(next.x) + 0.5 - service_x) - service_distance) * _fuel_horizontal_step
				if not opened:
					edge_fuel += _dig_fuel(next)
				var priority := float(priorities[cell]) + maxf(0.0, edge_fuel)
				if priority >= float(priorities.get(next, INF)):
					continue
				if not priorities.has(next):
					queue.append(next)
				priorities[next] = priority
				previous[next] = cell
		return []

	func _reconstruct(previous: Dictionary, start: Vector2i, finish: Vector2i) -> Array[Vector2i]:
		var result: Array[Vector2i] = []
		var cell := finish
		while cell != start:
			result.append(cell)
			cell = previous[cell]
		result.reverse()
		return result

	func _reset_navigation() -> void:
		_route_control = false
		_control_rejected = false
		_rejected_time = 0.0
		_escape_waypoint = Vector2i(-1, -1)
		_escape_after = 0.0

	func _native_control(axes: Vector2, position: Vector2) -> Vector2:
		if host.player.is_digging_bottom or host.player.is_digging_side or host.player.is_in_shop or host.player.pvp_building_hidden:
			return Vector2.ZERO
		# Only route-owned input is recomputed. Combat, shop approach and active
		# escape retain their deliberate axes, subject to the same sensor check.
		if _route_control:
			host.agent_axes = Vector2.ZERO
			_follow_route(position)
			axes = _avoid_peers(host.agent_axes, position)
		return _avoid_hazards(axes, position)

	func _waypoint_retry_allowed(cell: Vector2i) -> bool:
		if not _waypoint_failures.has(cell):
			return true
		var failure: Dictionary = _waypoint_failures[cell]
		for nearby in failure.terrain:
			if _raw(nearby) != int(failure.terrain[nearby]):
				_waypoint_failures.erase(cell)
				return true
		return int(failure.count) < 2

	func _recover_navigation(position: Vector2) -> void:
		if not _route.is_empty():
			var failed := _route[0]
			_waypoint_retry_allowed(failed)
			var count := int(_waypoint_failures.get(failed, {}).get("count", 0)) + 1
			var terrain: Dictionary = {failed: _raw(failed)}
			for direction in DIRECTIONS:
				var nearby: Vector2i = failed + direction
				terrain[nearby] = _raw(nearby)
			if not _waypoint_failures.has(failed) and _waypoint_failures.size() >= GOAL_PATH_LIMIT:
				_waypoint_failures.erase(_waypoint_failures.keys()[0])
			_waypoint_failures[failed] = {"count": count, "terrain": terrain}
			_blocked[failed] = 30.0 if _returning else 8.0
			# A first clamp/flip is not a failed ore expedition. Only exhausted
			# physical recovery can record failure without meaningful fuel use.
			if count >= 2 and not _goal_attempt.is_empty():
				_goal_attempt.rejected = true
				_finish_goal_attempt()
		_fuel_after = 0.0
		_clear_cash_goal()
		_route.clear()
		_route_control = false
		_plan_after = 0.0
		_stuck_time = 0.0
		_rejected_time = 0.0
		_progress_goal = Vector2(INF, INF)
		_progress_distance = INF
		host.agent_axes = Vector2.ZERO
		# Vacate the collision using ordinary controls before planning again.
		# Prefer lift, but an open sideways exit also works under a solid roof.
		var current := _cell(position)
		for direction in [Vector2i.UP, Vector2i.LEFT, Vector2i.RIGHT]:
			var escape: Vector2i = current + direction
			if _open(escape) and not _blocked.has(escape) and not _peer_occupies(escape):
				_escape_waypoint = escape
				_escape_after = 0.8
				_navigation_escape(position, 0.0)
				break

	func _navigation_escape(position: Vector2, delta: float) -> bool:
		_escape_after = maxf(0.0, _escape_after - delta)
		if _escape_after <= 0.0 or not _open(_escape_waypoint):
			_escape_waypoint = Vector2i(-1, -1)
			return false
		var point := Vector2(_escape_waypoint.x + 0.5, -_escape_waypoint.y + 0.5)
		if position.distance_squared_to(point) < 0.09:
			_escape_after = 0.0
			return false
		_navigation_goal = point
		var offset := point - position
		var axes := Vector2.ZERO
		if absf(offset.x) > 0.25:
			axes.x = _horizontal_axis(offset.x)
		if offset.y > 0.2:
			axes.y = 1.0
		host.agent_axes = _avoid_hazards(axes, position)
		return true

	func _follow_route(position: Vector2) -> void:
		_route_control = true
		while not _route.is_empty():
			var point := Vector2(_route[0].x + 0.5, -_route[0].y + 0.5)
			if absf(position.x - point.x) > 0.38 or absf(position.y - point.y) > 0.42 or not _open(_route[0]):
				break
			_route.pop_front()
		if _route.is_empty():
			return
		var next := _route[0]
		var point := Vector2(next.x + 0.5, -next.y + 0.5)
		_navigation_goal = point
		var offset := point - position
		var axes := Vector2.ZERO
		var current := _cell(position)
		if not _waypoint_retry_allowed(next) and not (_returning and _open(next)):
			_control_rejected = true
			host.agent_axes = Vector2.ZERO
			return
		if not _open(next):
			var bottom: Vector2i = host.player.getBlockPositionBottomPlayer()
			if not _safe_dig(next):
				_control_rejected = true
			elif next == bottom:
				axes.y = -1.0
			elif next.y > current.y or next.x == current.x:
				# Aim the serialized bottom detector, not the asymmetric pod root.
				var marker: Vector2 = host.player._bottom_target.global_position / PortPlayer.UNITS
				var sensor_offset: float = point.x - marker.x
				if absf(sensor_offset) > 0.15:
					axes.x = _horizontal_axis(sensor_offset)
				elif bottom.y < next.y and _open(bottom):
					axes.y = -1.0
				elif bottom.y > next.y and _open(current + Vector2i.UP):
					axes.y = 1.0
				else:
					_control_rejected = true
			elif next.y == current.y and next.x != current.x:
				# Grounding and facing are native state, not inferred from Rock
				# versus other Ground shapes. Let the stock flip/settle complete.
				if not _drill_landing_in_bounds(next, signf(offset.x)) or _open(next + Vector2i.DOWN):
					_control_rejected = true
				else:
					axes.x = signf(offset.x)
			else:
				_control_rejected = true
		else:
			if absf(offset.x) > (0.40 if next.x == current.x else 0.16):
				axes.x = _horizontal_axis(offset.x)
			var velocity: Vector2 = host.player.velocity_unity
			var floor_step := axes.x != 0.0 and next.x != current.x and not _open(next + Vector2i.DOWN)
			# Carry lift through track clearance rather than stabilizing below
			# a raised floor inside the normal vertical deadband.
			var clear_floor := floor_step and (offset.y > 0.03 or (offset.y > -0.04 and velocity.y > 0.0))
			if clear_floor or offset.y > 0.35 or velocity.y < -3.0:
				axes.y = 1.0
			elif offset.y < -0.55 and absf(offset.x) < 0.3:
				axes.y = -1.0
		host.agent_axes = axes

	func _horizontal_axis(offset: float) -> float:
		var velocity: float = host.player.velocity_unity.x
		if offset * velocity > 0.0 and absf(offset) < absf(velocity) * 0.18:
			return -signf(velocity)
		return signf(offset)

	func _surface_axes(position: Vector2, door: Vector2) -> Vector2:
		_navigation_goal = door
		var axes := Vector2(_horizontal_axis(door.x - position.x), 0)
		if absf(door.x - position.x) < 0.4:
			axes.x = 0
		# Fly above pavement/building collisions, then settle into the real door.
		# Brake surface falls just as route-following does before terrain contact.
		if position.y < -3.7 or (absf(door.x - position.x) > 1.5 and position.y < -2.7) or host.player.velocity_unity.y < -3.0:
			axes.y = 1
		return axes

	func _avoid_peers(axes: Vector2, position: Vector2) -> Vector2:
		for peer in host.coop.network.peers.values():
			var state: Dictionary = peer.get("state", {})
			if str(peer.get("player_id", "")) == host.coop.network.player_id or not bool(state.get("alive", true)) or not str(state.get("building", "")).is_empty():
				continue
			var offset := Vector2(float(state.get("x", 0)), float(state.get("y", 0))) - position
			if absf(offset.x) < 1.3 and absf(offset.y) < 1.05 and axes.x * offset.x > 0:
				if position.y >= -4.0 and _open(_cell(position) + Vector2i.UP):
					axes.y = 1
				else:
					axes.x = -signf(offset.x)
		return axes

	func _peer_occupies(cell: Vector2i) -> bool:
		var point := Vector2(cell.x + 0.5, -cell.y + 0.5)
		for peer in host.coop.network.peers.values():
			var state: Dictionary = peer.get("state", {})
			if str(peer.get("player_id", "")) == host.coop.network.player_id or not bool(state.get("alive", true)) or not str(state.get("building", "")).is_empty():
				continue
			if point.distance_squared_to(Vector2(float(state.get("x", 0)), float(state.get("y", 0)))) < 1.44:
				return true
		return false

	func _avoid_hazards(axes: Vector2, position: Vector2) -> Vector2:
		var intended := _route[0] if _route_control and not _route.is_empty() else Vector2i(-1, -1)
		var rejected := false
		if axes.y < 0.0:
			var bottom: Vector2i = host.player.getBlockPositionBottomPlayer()
			if not _open(bottom) and (not _safe_dig(bottom) or (intended.x >= 0 and bottom != intended)):
				axes.y = 0.0
				rejected = true
			elif not _open(bottom) and not _drill_landing_in_bounds(bottom, 1.0 if host.player.isFacingRight else -1.0):
				# Bottom drilling uses the same facing-dependent landing offset.
				# Finish a real inward flip before requesting the boundary dig.
				axes.y = 0.0
				axes.x = 1.0 if bottom.x == 0 else -1.0
		# Player.tick only side-drills while grounded and facing the input.
		# Opposite input must remain available to request the native flip.
		if axes.y >= 0.0 and axes.x != 0.0 and host.player.isOnGround and (axes.x > 0.0) == host.player.isFacingRight:
			var side: Vector2i = host.player.getBlockPositionSidePlayer()
			# A cancelled dig can leave the hull in its own still-solid cell.
			# Safe native excavation there frees the hull instead of clamping
			# the only lateral escape; unrelated seam drilling remains denied.
			if not _open(side) and (not _drill_landing_in_bounds(side, axes.x) or not _safe_dig(side) or (intended.x >= 0 and side != intended and side != _cell(position))):
				axes.x = 0.0
				rejected = true
		if rejected:
			_control_rejected = true
			# Stop falling into the denied detector while recovery accrues.
			# This is real lift into known air, never a position/collision edit.
			if _open(_cell(position) + Vector2i.UP):
				axes.y = 1.0
		return axes

	func _drill_landing_in_bounds(cell: Vector2i, direction_x: float) -> bool:
		# Native drill completion targets center +/- .25, but the authority
		# requires a .4 hull margin. Boundary ore needs an inward-facing dig.
		return cell.x > 0 if direction_x < 0.0 else cell.x < host.data.earthWidth - 1

	func _cell(position: Vector2) -> Vector2i:
		return Vector2i(floori(position.x), -floori(position.y))

	func _raw(cell: Vector2i) -> int:
		var raw: Array = host.world.getRawTile(cell.x, cell.y)
		return int(raw[0]) if not raw.is_empty() else -8

	func _open(cell: Vector2i) -> bool:
		var raw := _raw(cell)
		return raw == 0 or raw == -999 or raw < -100

	func _earth_anchor(raw: int) -> bool:
		# Match the authority: hazards and invincible scenery do not anchor
		# another hazard; ordinary earth, grass and minerals do.
		return raw == -1 or raw == -2 or (raw >= 1 and raw <= 24)

	func _safe_dig(cell: Vector2i) -> bool:
		if not _earth_anchor(_raw(cell)):
			return false
		for direction in DIRECTIONS:
			# Below-pod debris falls away. Roof/side releases can enter the
			# native landing before the stock hull has time to get clear.
			if direction == Vector2i.DOWN:
				continue
			var hazard: Vector2i = cell + direction
			var hazard_raw := _raw(hazard)
			while hazard_raw >= 25 and hazard_raw <= 30:
				var anchored := false
				for support_direction in DIRECTIONS:
					var support: Vector2i = hazard + support_direction
					if support != cell and _earth_anchor(_raw(support)):
						anchored = true
						break
				if anchored:
					break
				var below := hazard + Vector2i.DOWN
				if below == cell or _open(below):
					return false
				# An unsupported stack stays put only while something solid
				# beneath it will remain after this excavation.
				hazard = below
				hazard_raw = _raw(hazard)
		return true

	func _set_mode(value: String, detail: String) -> void:
		if mode != value:
			mode = value
			print("PRACTICE_BOT_MODE name=", _name, " mode=", mode, " target=", detail)

var host: Node
var brain: BotBrain
var bot_name := "Practice_Bot_1"
var credentials_path := ""
var bot_seed := -1
var _retry_after := 3.0

func _initialize() -> void:
	for argument in OS.get_cmdline_user_args():
		if str(argument).begins_with("--bot-name="):
			bot_name = str(argument).trim_prefix("--bot-name=")
		elif str(argument).begins_with("--bot-credentials="):
			credentials_path = str(argument).trim_prefix("--bot-credentials=")
		elif str(argument).begins_with("--bot-seed="):
			bot_seed = int(str(argument).trim_prefix("--bot-seed="))
	_start.call_deferred()

func _start() -> void:
	var credentials: Variant = JSON.parse_string(FileAccess.get_file_as_string(credentials_path))
	if not credentials is Dictionary or not credentials.has(bot_name):
		push_error("Practice bot requires its local test-account credentials")
		quit(1)
		return
	# Do not set agent_axes until _ready has installed the native clock and co-op.
	host = BotHost.new()
	root.add_child(host)
	await process_frame
	var network: CoopClient = host.coop.network
	network.token = str(credentials[bot_name].token)
	network.username = bot_name
	network.mode = "pvp"
	host.agent_axes = Vector2.ZERO
	brain = BotBrain.new(host, bot_seed)
	network.joined_world.connect(func(_snapshot: Dictionary): print("PRACTICE_BOT_JOINED name=", bot_name, " player=", network.player_id))
	network.connection_lost.connect(func(message: String):
		brain.reset()
		print("PRACTICE_BOT_DISCONNECTED name=", bot_name, " reason=", message))
	network.join_world()

func _process(delta: float) -> bool:
	if host == null or host.coop == null or brain == null:
		return false
	var network: CoopClient = host.coop.network
	if not network.connected:
		brain.reset()
		_retry_after -= delta
		if _retry_after <= 0.0 and not network.connecting:
			_retry_after = 3.0
			network.mode = "pvp"
			network.join_world()
		return false
	brain.tick(delta)
	return false
