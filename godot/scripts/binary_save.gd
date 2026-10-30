class_name BinarySave
extends RefCounted

# Data-only MS-NRBF codec for the original six-field SaveDataType graph. No CLR
# types are loaded, instantiated, or invoked. Settings deliberately remain JSON.
const ASSEMBLY: String = "Assembly-CSharp, Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"
const CORE: String = "mscorlib, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089"
const STRING: String = "System.String"
const INT: String = "System.Int32"
const TUPLE: String = "System.ValueTuple`4[[System.String, %s],[System.String, %s],[System.String, %s],[System.Boolean, %s]]" % [CORE, CORE, CORE, CORE]
const MAX_BYTES: int = 64 * 1024 * 1024
const MAX_ELEMENTS: int = 4 * 1024 * 1024
const FIELDS: Array = ["player_money", "current_upgrades", "player_items", "my_map", "player_cargo", "transmissions"]

var error: String = ""
var _stream: StreamPeerBuffer = StreamPeerBuffer.new()
var _objects: Dictionary = {}
var _metadata: Dictionary = {}
var _libraries: Dictionary = {}
var _next_id: int = 1
var _depth: int = 0
var _elements: int = 0
var _pending_arrays: Array = []

static func list_type(element: String) -> String:
	return "System.Collections.Generic.List`1[[%s, %s]]" % [element, CORE]

static func dictionary_type(element: String) -> String:
	return "System.Collections.Generic.Dictionary`2[[System.String, %s],[%s, %s]]" % [CORE, element, CORE]

static func pair_type(element: String) -> String:
	return "System.Collections.Generic.KeyValuePair`2[[System.String, %s],[%s, %s]]" % [CORE, element, CORE]

static func comparer_type() -> String:
	return "System.Collections.Generic.GenericEqualityComparer`1[[System.String, %s]]" % CORE

func _fail(message: String) -> void:
	if error.is_empty():
		error = message

func _available(count: int) -> bool:
	if count < 0 or count > _stream.get_available_bytes():
		_fail("Truncated NRBF stream")
		return false
	return error.is_empty()

func _byte() -> int:
	return _stream.get_u8() if _available(1) else 0

func _int() -> int:
	return _stream.get_32() if _available(4) else 0

func _length(value: int) -> int:
	if value < 0 or value > MAX_ELEMENTS:
		_fail("Invalid NRBF collection length")
		return 0
	_elements += value
	if _elements > MAX_ELEMENTS:
		_fail("NRBF graph exceeds collection limit")
		return 0
	return value

func _string() -> String:
	var length: int = 0
	for shift in range(0, 35, 7):
		var part: int = _byte()
		if shift == 28 and part > 7:
			_fail("Invalid NRBF string length")
			return ""
		length |= (part & 127) << shift
		if part < 128:
			if not _available(length):
				return ""
			var bytes: PackedByteArray = _stream.get_data(length)[1]
			var text: String = bytes.get_string_from_utf8()
			if text.to_utf8_buffer() != bytes:
				_fail("Invalid NRBF UTF-8 string")
			return text
	_fail("Invalid NRBF string length")
	return ""

func _primitive(kind: int) -> Variant:
	match kind:
		1:
			var value: int = _byte()
			if value > 1:
				_fail("Invalid NRBF Boolean")
			return value != 0
		8:
			return _int()
	_fail("Unsupported NRBF primitive: " + str(kind))
	return null

func _schema(type: String) -> Dictionary:
	if type == "SaveDataType":
		return {"player_money": [0, 8], "current_upgrades": [3, dictionary_type(STRING)], "player_items": [3, dictionary_type(INT)], "my_map": [3, list_type(list_type(list_type(INT)))], "player_cargo": [3, dictionary_type(INT)], "transmissions": [3, list_type(TUPLE)]}
	for element in [INT, list_type(INT), list_type(list_type(INT)), TUPLE]:
		if type == list_type(element):
			return {"_items": [7, 8] if element == INT else [3, element + "[]"], "_size": [0, 8], "_version": [0, 8]}
	for element in [STRING, INT]:
		if type == dictionary_type(element):
			return {"Version": [0, 8], "Comparer": [3, "System.Collections.Generic.IEqualityComparer`1[[System.String, %s]]" % CORE], "HashSize": [0, 8], "KeyValuePairs": [3, pair_type(element) + "[]"]}
		if type == pair_type(element):
			return {"key": [1, null], "value": [1, null] if element == STRING else [0, 8]}
	if type == TUPLE:
		return {"Item1": [1, null], "Item2": [1, null], "Item3": [1, null], "Item4": [0, 1]}
	if type == comparer_type() or type == "System.Collections.Generic.ObjectEqualityComparer`1[[System.String, %s]]" % CORE:
		return {}
	_fail("NRBF type is outside SaveDataType: " + type)
	return {}

func _type_info(kind: int) -> Variant:
	match kind:
		0, 7:
			return _byte()
		1, 2, 5, 6:
			return null
		3:
			return _string()
		4:
			var name: String = _string()
			var library: int = _int()
			if not _libraries.has(library) or _libraries[library] != ASSEMBLY:
				_fail("Unexpected NRBF class library")
			return name
	_fail("Invalid NRBF binary type")
	return null

func _register(id: int, value: Variant) -> void:
	if id == 0 or _objects.has(id):
		_fail("Duplicate or zero NRBF object ID")
		return
	_objects[id] = value

func _class(record: int) -> Variant:
	var id: int = _int()
	var meta: Dictionary
	if record == 1:
		var metadata_id: int = _int()
		if not _metadata.has(metadata_id):
			_fail("Unknown NRBF metadata reference")
			return null
		meta = _metadata[metadata_id]
	else:
		var type: String = _string()
		var count: int = _length(_int())
		var names: Array = []
		for index in count:
			names.append(_string())
		var schema: Dictionary = _schema(type)
		var kinds: Array = []
		var info: Array = []
		if record == 4 or record == 5:
			for index in count:
				kinds.append(_byte())
			for kind in kinds:
				info.append(_type_info(kind))
		else:
			for name in names:
				if not schema.has(name):
					_fail("Unknown NRBF member")
					return null
				kinds.append(schema[name][0])
				info.append(schema[name][1])
		if record == 3 or record == 5:
			var library: int = _int()
			if _libraries.get(library, "") != ASSEMBLY or type != "SaveDataType":
				_fail("Unexpected NRBF assembly class")
		elif type == "SaveDataType":
			_fail("SaveDataType must identify Assembly-CSharp")
		var seen: Dictionary = {}
		for index in count:
			var name: String = names[index]
			if seen.has(name) or not schema.has(name):
				_fail("Unknown or repeated NRBF member: " + name)
				return null
			seen[name] = true
			# Comparer and backing-array declarations vary between Mono profiles;
			# their actual objects are still restricted and checked below.
			if kinds[index] != schema[name][0] and not (name in ["Comparer", "_items"] and kinds[index] == 2):
				_fail("Unexpected NRBF member encoding: " + name)
			if kinds[index] == 0 and info[index] != schema[name][1]:
				_fail("Unexpected NRBF primitive member")
		for name in schema:
			if not seen.has(name) and name != "KeyValuePairs":
				_fail("Missing NRBF member: " + name)
		meta = {"type": type, "names": names, "kinds": kinds, "info": info}
		_metadata[id] = meta
	var members: Dictionary = {}
	var node: Dictionary = {"type": meta.type, "members": members}
	_register(id, node)
	for index in meta.names.size():
		if not error.is_empty():
			return null
		members[meta.names[index]] = _primitive(meta.info[index]) if meta.kinds[index] == 0 else _value()
	return node

func _array(record: int) -> Variant:
	var id: int = _int()
	var count: int
	var kind: int
	var info: Variant
	if record == 7:
		var shape: int = _byte()
		var rank: int = _int()
		if shape not in [0, 1] or rank != 1:
			_fail("Only rank-one SaveDataType arrays are allowed")
			return null
		count = _length(_int())
		kind = _byte()
		info = _type_info(kind)
	else:
		count = _length(_int())
		kind = 0 if record == 15 else (2 if record == 16 else 1)
		info = _byte() if record == 15 else null
	var values: Array = []
	var node: Dictionary = {"array": values, "kind": kind, "info": info}
	_register(id, node)
	while values.size() < count and error.is_empty():
		var value: Variant = _primitive(info) if kind == 0 else _value()
		if value is Dictionary and value.has("nulls"):
			var nulls: int = value.nulls
			if nulls <= 0 or values.size() + nulls > count:
				_fail("Invalid NRBF null run")
				break
			for index in nulls:
				values.append(null)
		else:
			values.append(value)
	return node

func _value() -> Variant:
	_depth += 1
	if _depth > 64:
		_fail("NRBF nesting limit exceeded")
		_depth -= 1
		return null
	var value: Variant = null
	while error.is_empty():
		var record: int = _byte()
		match record:
			1, 2, 3, 4, 5:
				value = _class(record)
			6:
				var id: int = _int()
				value = _string()
				_register(id, value)
			7, 15, 16, 17:
				value = _array(record)
			8:
				value = _primitive(_byte())
			9:
				value = {"ref": _int()}
			10:
				value = null
			12:
				var id: int = _int()
				var name: String = _string()
				if name not in [ASSEMBLY, CORE] or _libraries.has(id):
					_fail("Unexpected NRBF library")
				_libraries[id] = name
				continue
			13:
				value = {"nulls": _byte()}
			14:
				value = {"nulls": _int()}
			_:
				_fail("Unsupported NRBF record: " + str(record))
		break
	_depth -= 1
	return value

func _resolve(value: Variant) -> Variant:
	if value is Dictionary and value.has("ref"):
		if not _objects.has(value.ref):
			_fail("Unresolved NRBF reference")
			return null
		return _objects[value.ref]
	return value

func _members(value: Variant, type: String) -> Dictionary:
	var node: Variant = _resolve(value)
	if not node is Dictionary or node.get("type", "") != type:
		_fail("Expected NRBF " + type)
		return {}
	return node.members

func _text(value: Variant) -> String:
	var result: Variant = _resolve(value)
	if not result is String:
		_fail("Expected non-null NRBF string")
		return ""
	return result

func _integer(value: Variant) -> int:
	if not value is int or value < -2147483648 or value > 2147483647:
		_fail("Expected NRBF Int32")
		return 0
	return value

func _array_values(value: Variant) -> Array:
	var node: Variant = _resolve(value)
	if not node is Dictionary or not node.has("array"):
		_fail("Expected NRBF backing array")
		return []
	return node.array

func _list(value: Variant, element: String, depth: int = 0) -> Array:
	if depth > 3:
		_fail("Invalid SaveDataType list depth")
		return []
	var members: Dictionary = _members(value, list_type(element))
	if not error.is_empty():
		return []
	var backing: Array = _array_values(members._items)
	var size: int = _integer(members._size)
	if size < 0 or size > backing.size():
		_fail("Invalid NRBF List size")
		return []
	var result: Array = []
	for index in size:
		if not error.is_empty():
			break
		if element == INT:
			result.append(_integer(backing[index]))
		elif element == TUPLE:
			var tuple: Dictionary = _members(backing[index], TUPLE)
			if not error.is_empty():
				break
			if not tuple.Item4 is bool:
				_fail("Expected transmission Boolean")
			result.append({"text": _text(tuple.Item1), "signature": _text(tuple.Item2), "picture_name": _text(tuple.Item3), "displayed": tuple.Item4})
		elif element == list_type(INT):
			result.append(_list(backing[index], INT, depth + 1))
		elif element == list_type(list_type(INT)):
			result.append(_list(backing[index], list_type(INT), depth + 1))
	return result

func _dictionary(value: Variant, element: String) -> Dictionary:
	var members: Dictionary = _members(value, dictionary_type(element))
	if not error.is_empty():
		return {}
	var comparer: Variant = _resolve(members.Comparer)
	if comparer != null:
		if not comparer is Dictionary or comparer.get("type", "") not in [comparer_type(), "System.Collections.Generic.ObjectEqualityComparer`1[[System.String, %s]]" % CORE]:
			_fail("Unexpected dictionary comparer")
	var hash_size: int = _integer(members.HashSize)
	if hash_size < 0 or hash_size > MAX_ELEMENTS:
		_fail("Invalid dictionary HashSize")
	var result: Dictionary = {}
	if not members.has("KeyValuePairs"):
		if hash_size != 0:
			_fail("Missing dictionary entries")
		return result
	for entry in _array_values(members.KeyValuePairs):
		var pair: Dictionary = _members(entry, pair_type(element))
		if not error.is_empty():
			break
		var key: String = _text(pair.key)
		if result.has(key):
			_fail("Duplicate dictionary key")
		result[key] = _text(pair.value) if element == STRING else _integer(pair.value)
	return result

func decode(bytes: PackedByteArray) -> Dictionary:
	if bytes.size() > MAX_BYTES:
		_fail("Save exceeds NRBF size limit")
		return {}
	_stream.data_array = bytes
	_stream.big_endian = false
	if _byte() != 0:
		_fail("Not an NRBF SerializedStreamHeader")
	var root_id: int = _int()
	var header_id: int = _int()
	var major: int = _int()
	var minor: int = _int()
	if root_id <= 0 or header_id != -1 or major != 1 or minor != 0:
		_fail("Unsupported NRBF stream header")
	while error.is_empty() and _stream.get_available_bytes() > 0:
		if _stream.data_array[_stream.get_position()] == 11:
			_byte()
			if _stream.get_available_bytes() != 0:
				_fail("Trailing NRBF data")
			var root: Dictionary = _members({"ref": root_id}, "SaveDataType")
			if not error.is_empty():
				return {}
			var result: Dictionary = {"player_money": _integer(root.player_money), "current_upgrades": _dictionary(root.current_upgrades, STRING), "player_items": _dictionary(root.player_items, INT), "my_map": _list(root.my_map, list_type(list_type(INT))), "player_cargo": _dictionary(root.player_cargo, INT), "transmissions": _list(root.transmissions, TUPLE)}
			return result if error.is_empty() else {}
		_value()
	_fail("Missing NRBF MessageEnd")
	return {}

func _put_string(text: String) -> void:
	var bytes: PackedByteArray = text.to_utf8_buffer()
	var length: int = bytes.size()
	while length >= 128:
		_stream.put_u8((length & 127) | 128)
		length >>= 7
	_stream.put_u8(length)
	_stream.put_data(bytes)

func _id() -> int:
	var result: int = _next_id
	_next_id += 1
	return result

func _put_info(kind: int, info: Variant) -> void:
	if kind in [0, 7]:
		_stream.put_u8(info)
	elif kind == 3:
		_put_string(info)

func _put_class(type: String, members: Dictionary) -> void:
	var id: int = _id()
	if not _metadata.has(type):
		_metadata[type] = {}
	var variants: Dictionary = _metadata[type]
	# The only optional schema member is Dictionary.KeyValuePairs. Its empty
	# and populated layouts must not share a ClassWithId metadata record.
	var member_count := members.size()
	if variants.has(member_count):
		_stream.put_u8(1)
		_stream.put_32(id)
		_stream.put_32(variants[member_count])
	else:
		variants[member_count] = id
		_stream.put_u8(5 if type == "SaveDataType" else 4)
		_stream.put_32(id)
		_put_string(type)
		_stream.put_32(members.size())
		for name in members:
			_put_string(name)
		var schema: Dictionary = _schema(type)
		for name in members:
			_stream.put_u8(schema[name][0])
		for name in members:
			_put_info(schema[name][0], schema[name][1])
		if type == "SaveDataType":
			_stream.put_32(1)
	var schema: Dictionary = _schema(type)
	for name in members:
		if schema[name][0] == 0:
			if schema[name][1] == 1:
				_stream.put_u8(1 if members[name] else 0)
			else:
				_stream.put_32(members[name])
		else:
			_put_value(members[name])

func _put_value(value: Variant) -> void:
	if value == null:
		_stream.put_u8(10)
	elif value is String:
		_stream.put_u8(6)
		_stream.put_32(_id())
		_put_string(value)
	elif value is Dictionary and value.has("array"):
		# SerializationInfo array members require reference fixups in Mono's
		# formatter. Emit their definitions after the containing objects.
		var id := _id()
		_stream.put_u8(9)
		_stream.put_32(id)
		_pending_arrays.append({"id": id, "value": value})
	else:
		_put_class(value.type, value.members)

func _put_array(id: int, value: Dictionary) -> void:
	if value.element == INT:
		_stream.put_u8(15)
		_stream.put_32(id)
		_stream.put_32(value.array.size())
		_stream.put_u8(8)
		for number in value.array:
			_stream.put_32(number)
	else:
		_stream.put_u8(7)
		_stream.put_32(id)
		_stream.put_u8(0)
		_stream.put_32(1)
		_stream.put_32(value.array.size())
		_stream.put_u8(3)
		_put_string(value.element)
		for entry in value.array:
			_put_value(entry)

func _make_list(values: Array, element: String) -> Dictionary:
	var backing: Array = []
	_length(values.size())
	for value in values:
		if element == INT:
			backing.append(_integer(value))
		elif element == TUPLE:
			if not value is Dictionary or not value.has_all(["text", "signature", "picture_name", "displayed"]) or not value.displayed is bool:
				_fail("Invalid transmission")
				return {}
			backing.append({"type": TUPLE, "members": {"Item1": _text(value.text), "Item2": _text(value.signature), "Item3": _text(value.picture_name), "Item4": value.displayed}})
		else:
			if not value is Array:
				_fail("Invalid map list")
				return {}
			backing.append(_make_list(value, INT if element == list_type(INT) else list_type(INT)))
	return {"type": list_type(element), "members": {"_items": {"array": backing, "element": element}, "_size": values.size(), "_version": values.size()}}

func _make_dictionary(values: Dictionary, element: String) -> Dictionary:
	var pairs: Array = []
	_length(values.size())
	for key in values:
		pairs.append({"type": pair_type(element), "members": {"key": _text(key), "value": _text(values[key]) if element == STRING else _integer(values[key])}})
	# Match Dictionary's prime-bucket convention, with room for every entry.
	# HashSize zero represents an empty dictionary without KeyValuePairs.
	var capacity: int = 0 if pairs.is_empty() else 3
	while capacity < pairs.size() or not _is_prime(capacity):
		capacity += 2
	var members: Dictionary = {"Version": values.size(), "Comparer": {"type": comparer_type(), "members": {}}, "HashSize": capacity}
	if capacity > 0:
		members.KeyValuePairs = {"array": pairs, "element": pair_type(element)}
	return {"type": dictionary_type(element), "members": members}

func _is_prime(number: int) -> bool:
	if number == 0:
		return true
	var divisor: int = 3
	while divisor * divisor <= number:
		if number % divisor == 0:
			return false
		divisor += 2
	return true

func encode(saved: Dictionary) -> PackedByteArray:
	if not saved.has_all(FIELDS):
		_fail("Incomplete SaveDataType")
		return PackedByteArray()
	for name in ["current_upgrades", "player_items", "player_cargo"]:
		if not saved[name] is Dictionary:
			_fail("Invalid SaveDataType dictionary")
			return PackedByteArray()
	if not saved.my_map is Array or not saved.transmissions is Array:
		_fail("Invalid SaveDataType list")
		return PackedByteArray()
	var members: Dictionary = {"player_money": _integer(saved.player_money), "current_upgrades": _make_dictionary(saved.current_upgrades, STRING), "player_items": _make_dictionary(saved.player_items, INT), "my_map": _make_list(saved.my_map, list_type(list_type(INT))), "player_cargo": _make_dictionary(saved.player_cargo, INT), "transmissions": _make_list(saved.transmissions, TUPLE)}
	if not error.is_empty():
		return PackedByteArray()
	_stream.big_endian = false
	_stream.put_u8(0)
	_stream.put_32(1)
	_stream.put_32(-1)
	_stream.put_32(1)
	_stream.put_32(0)
	_stream.put_u8(12)
	_stream.put_32(1)
	_put_string(ASSEMBLY)
	_put_class("SaveDataType", members)
	var pending_index := 0
	while pending_index < _pending_arrays.size():
		var pending: Dictionary = _pending_arrays[pending_index]
		_put_array(int(pending.id), pending.value)
		pending_index += 1
	_stream.put_u8(11)
	if _stream.get_size() > MAX_BYTES:
		_fail("Save exceeds NRBF size limit")
		return PackedByteArray()
	return _stream.data_array
