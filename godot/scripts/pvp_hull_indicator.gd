class_name PvpHullIndicator
extends Node2D

# World units, like the pod/nameplate: camera zoom scales the whole indicator.
const OFFSET := Vector2(0.0, -1.45)
const BAR := Rect2(-0.84, 0.0, 1.68, 0.13)
const INSET := 0.025
const FONT = preload("res://assets/MyFonts/214_Arial Black.ttf")

var current_hull := 0.0
var maximum_hull := 10.0
var ratio := 0.0
var _label: Label

func _init() -> void:
	name = "HullHealth"
	z_index = 40
	_label = Label.new()
	_label.name = "HullValue"
	_label.position = Vector2(-1.0, -0.29)
	_label.scale = Vector2.ONE * 0.0125
	_label.size = Vector2(160, 22)
	_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_label.add_theme_font_override("font", FONT)
	_label.add_theme_font_size_override("font_size", 16)
	_label.add_theme_color_override("font_color", Color("dedac6"))
	_label.add_theme_color_override("font_outline_color", Color("11190e"))
	_label.add_theme_constant_override("outline_size", 4)
	add_child(_label)

static func capacity(state: Dictionary) -> float:
	var hull := str(state.get("current_upgrades", {}).get("Hull", GameData.DEFAULT_UPGRADES.Hull))
	var definition: Dictionary = GameData.UPGRADE_TABLE.Hull.get(hull, GameData.UPGRADE_TABLE.Hull[GameData.DEFAULT_UPGRADES.Hull])
	return float(definition.effect)

func update_hull(current: float, maximum: float) -> void:
	maximum = maxf(0.0, maximum)
	current = clampf(current, 0.0, maximum)
	if current == current_hull and maximum == maximum_hull and not _label.text.is_empty():
		return
	current_hull = current
	maximum_hull = maximum
	ratio = clampf(current / maximum, 0.0, 1.0) if maximum > 0.0 else 0.0
	_label.text = "%s/%s" % [String.num(current, 1), String.num(maximum, 1)]
	queue_redraw()

func follow(target: Node2D, present: bool) -> void:
	visible = present and target.is_visible_in_tree()
	# Sibling, not a child of the craft: neither facing nor pod tilt flips it.
	global_position = target.global_position + OFFSET

func _draw() -> void:
	draw_rect(BAR.grow(0.025), Color("11190e"))
	draw_rect(BAR, Color("77786a"))
	var track := BAR.grow(-INSET)
	draw_rect(track, Color("11190e"))
	var fill := Color("24b817")
	if ratio <= 0.25:
		fill = Color("e45b42")
	elif ratio <= 0.5:
		fill = Color("fff000")
	draw_rect(Rect2(track.position, Vector2(track.size.x * ratio, track.size.y)), fill)
