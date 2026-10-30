class_name UnityRandom
extends RefCounted

# Published Unity 2022.3 oracle: xorshift128, low 23-bit inclusive floats.
# Float Range is a reversed weighted sum; zero-width float ranges still advance.
const MASK := 0xffffffff
var _s0: int
var _s1: int
var _s2: int
var _s3: int
var _float32 := PackedFloat32Array([0.0])

func _init(seed_value: int = 1) -> void:
	reseed(seed_value)

func reseed(seed_value: int) -> void:
	_s0 = seed_value & MASK
	_s1 = (1812433253 * _s0 + 1) & MASK
	_s2 = (1812433253 * _s1 + 1) & MASK
	_s3 = (1812433253 * _s2 + 1) & MASK

func single(number: float) -> float:
	_float32[0] = number
	return _float32[0]

func _next() -> int:
	var t := (_s0 ^ (_s0 << 11)) & MASK
	_s0 = _s1
	_s1 = _s2
	_s2 = _s3
	_s3 = (_s3 ^ (_s3 >> 19) ^ t ^ (t >> 8)) & MASK
	return _s3

func value() -> float:
	return single(float(_next() & 0x7fffff) / 8388607.0)

func range_float(minimum: float, maximum: float) -> float:
	var weight := value()
	return single(single(single(minimum) * weight) + single(single(maximum) * single(1.0 - weight)))

func range_int(minimum: int, maximum: int) -> int:
	if minimum == maximum:
		return minimum
	if minimum < maximum:
		return minimum + _next() % (maximum - minimum)
	return minimum - _next() % (minimum - maximum)

func get_state() -> Dictionary:
	return {"s0": _signed(_s0), "s1": _signed(_s1), "s2": _signed(_s2), "s3": _signed(_s3)}

func _signed(number: int) -> int:
	return number if number < 0x80000000 else number - 0x100000000
