class_name DotNetRandom
extends RefCounted

# Legacy .NET/Mono System.Random subtractive generator, not Godot's RNG.
const MBIG: int = 2147483647
const MSEED: int = 161803398
var seed_array: PackedInt64Array = PackedInt64Array()
var inext: int = 0
var inextp: int = 21
var seed_value: int

func _init(explicit_seed: Variant = null) -> void:
	# .NET used signed Environment.TickCount; Godot supplies a millisecond time seed.
	var seed_number: int = int(Time.get_unix_time_from_system() * 1000.0) if explicit_seed == null else int(explicit_seed)
	seed_number = ((seed_number + 2147483648) & 0xffffffff) - 2147483648
	seed_value = seed_number
	var subtraction: int = MBIG if seed_number == -2147483648 else absi(seed_number)
	var mj: int = MSEED - subtraction
	seed_array.resize(56)
	seed_array[55] = mj
	var mk: int = 1
	for i in range(1, 55):
		var ii: int = (21 * i) % 55
		seed_array[ii] = mk
		mk = _signed32(mj - mk)
		if mk < 0:
			mk += MBIG
		mj = seed_array[ii]
	for _pass in range(4):
		for i in range(1, 56):
			seed_array[i] = _signed32(seed_array[i] - seed_array[1 + ((i + 30) % 55)])
			if seed_array[i] < 0:
				seed_array[i] += MBIG

func _signed32(value: int) -> int:
	return ((value + 2147483648) & 0xffffffff) - 2147483648

func InternalSample() -> int:
	inext += 1
	if inext >= 56:
		inext = 1
	inextp += 1
	if inextp >= 56:
		inextp = 1
	var result: int = seed_array[inext] - seed_array[inextp]
	if result == MBIG:
		result -= 1
	if result < 0:
		result += MBIG
	seed_array[inext] = result
	return result

func Sample() -> float:
	return float(InternalSample()) * (1.0 / float(MBIG))

func Next(max_value: Variant = null) -> int:
	if max_value == null:
		return InternalSample()
	assert(int(max_value) >= 0, "System.Random.Next(maxValue): maxValue must be non-negative")
	# Next(0) returns zero but still consumes a sample, as in System.Random.
	return int(Sample() * int(max_value))

func NextDouble() -> float:
	return Sample()
