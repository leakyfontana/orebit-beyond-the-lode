class_name AudioEvidenceCapture
extends Node

# Records the actual Master bus mix without replacing or changing the audio.
# Float32 WAVE preserves the effect's samples, including values outside [-1, 1].
const HEADER_SIZE := 58
const DRAIN_FRAMES := 8192
var effect: AudioEffectCapture
var wav: FileAccess
var directory := ""
var sample_rate := 0
var frames := 0
var drain_blocks := 0
var start_usec := 0
var first_drain_usec := -1
var last_drain_usec := -1
var simulation_seconds := 0.0
var start_frame := 0
var failure := ""
var finished := false
var result := false

func start(output_directory: String) -> bool:
	directory = output_directory
	start_usec = Time.get_ticks_usec()
	start_frame = Engine.get_process_frames()
	sample_rate = int(AudioServer.get_mix_rate())
	process_mode = Node.PROCESS_MODE_ALWAYS
	if DirAccess.make_dir_recursive_absolute(directory) != OK:
		_fail("Cannot create audio evidence directory: " + directory)
		return false
	wav = FileAccess.open(directory.path_join("audio.wav"), FileAccess.WRITE_READ)
	if wav == null:
		_fail("Cannot open audio.wav: " + error_string(FileAccess.get_open_error()))
		return false
	# AudioEffectCapture exposes a stereo pair, not a complete surround mix.
	if AudioServer.get_speaker_mode() != AudioServer.SPEAKER_MODE_STEREO:
		_fail("AudioEffectCapture evidence requires actual stereo speaker output")
	if sample_rate <= 0:
		_fail("Missing actual audio mix rate")
	var header := PackedByteArray()
	header.resize(HEADER_SIZE)
	wav.store_buffer(header)
	effect = AudioEffectCapture.new()
	effect.buffer_length = 10.0
	AudioServer.add_bus_effect(0, effect)
	return failure.is_empty()

func _process(delta: float) -> void:
	if finished or effect == null:
		return
	simulation_seconds += delta
	if int(AudioServer.get_mix_rate()) != sample_rate:
		_fail("Audio sample rate changed during capture")
	_drain()

func _drain() -> void:
	if wav == null or effect == null:
		return
	var available := effect.get_frames_available()
	while available > 0:
		var count := mini(available, DRAIN_FRAMES)
		var buffer := effect.get_buffer(count)
		if buffer.size() != count:
			_fail("Master capture returned fewer actual frames than requested")
			return
		var bytes := buffer.to_byte_array()
		if bytes.size() != count * 8:
			_fail("Master capture is not the supported interleaved stereo float32 representation")
			return
		if (frames + count) * 8 > 4294967295 - HEADER_SIZE:
			_fail("Audio exceeds RIFF/WAVE 32-bit size limit")
			return
		wav.store_buffer(bytes)
		if wav.get_error() != OK:
			_fail("Writing actual audio samples failed: " + error_string(wav.get_error()))
			return
		frames += count
		drain_blocks += 1
		last_drain_usec = Time.get_ticks_usec()
		if first_drain_usec < 0:
			first_drain_usec = last_drain_usec
		available -= count

func _fail(message: String) -> void:
	if failure.is_empty():
		failure = message
		push_error("AUDIO_CAPTURE_FAILED: " + message)

func finish_capture() -> bool:
	if finished:
		return result
	finished = true
	set_process(false)
	# Removing the effect takes the audio-server lock, so an in-flight mix has
	# completed before the final drain and counters are read. No wait/padding.
	if effect != null:
		var effect_index := -1
		for index in AudioServer.get_bus_effect_count(0):
			if AudioServer.get_bus_effect(0, index) == effect:
				effect_index = index
				break
		if effect_index >= 0:
			AudioServer.remove_bus_effect(0, effect_index)
		else:
			_fail("Master capture effect was removed before finish")
		_drain()
	var end_usec := Time.get_ticks_usec()
	var pushed_frames := effect.get_pushed_frames() if effect != null else 0
	var discarded_frames := effect.get_discarded_frames() if effect != null else 0
	if pushed_frames == 0 or frames == 0:
		_fail("No actual Master DSP frames: missing mixed-output evidence")
	if discarded_frames != 0:
		_fail("Master capture buffer overflowed; actual samples were lost")
	if frames != pushed_frames:
		_fail("Stored frame count differs from actual Master capture frames")
	if int(AudioServer.get_mix_rate()) != sample_rate:
		_fail("Audio sample rate changed during capture")
	if wav != null:
		var header := PackedByteArray()
		header.resize(HEADER_SIZE)
		_put_tag(header, 0, "RIFF")
		header.encode_u32(4, frames * 8 + HEADER_SIZE - 8)
		_put_tag(header, 8, "WAVE")
		_put_tag(header, 12, "fmt ")
		header.encode_u32(16, 18)
		header.encode_u16(20, 3) # WAVE_FORMAT_IEEE_FLOAT, not quantized PCM16.
		header.encode_u16(22, 2)
		header.encode_u32(24, sample_rate)
		header.encode_u32(28, sample_rate * 8)
		header.encode_u16(32, 8)
		header.encode_u16(34, 32)
		header.encode_u16(36, 0)
		_put_tag(header, 38, "fact")
		header.encode_u32(42, 4)
		header.encode_u32(46, frames)
		_put_tag(header, 50, "data")
		header.encode_u32(54, frames * 8)
		wav.seek(0)
		wav.store_buffer(header)
		wav.flush()
		if wav.get_error() != OK:
			_fail("Finalizing audio.wav failed: " + error_string(wav.get_error()))
		wav.close()
	result = failure.is_empty()
	var metadata := {
		"success": result, "error": failure, "engine": "Godot",
		"capture_point": "Master bus AudioEffectCapture, after preceding bus effects, before Master fader/mute and device conversion",
		"driver": AudioServer.get_driver_name(), "master_volume_db": AudioServer.get_bus_volume_db(0),
		"master_muted": AudioServer.is_bus_mute(0), "sample_rate": sample_rate, "channels": 2,
		"format_tag": 3, "bits_per_sample": 32, "frames": frames, "samples": frames * 2,
		"duration_seconds": float(frames) / sample_rate if sample_rate > 0 else 0.0,
		"wall_duration_seconds": float(end_usec - start_usec) / 1000000.0,
		"simulation_duration_seconds": simulation_seconds,
		"simulation_clock": "Accumulated capture Node _process(delta), PROCESS_MODE_ALWAYS; a main-thread engine clock observation, not per-sample or replay-frame timestamps",
		"start_frame": start_frame, "end_frame": Engine.get_process_frames(),
		"pushed_frames": pushed_frames, "discarded_frames": discarded_frames, "drain_blocks": drain_blocks,
		"first_drain_wall_seconds": float(first_drain_usec - start_usec) / 1000000.0 if first_drain_usec >= 0 else -1.0,
		"last_drain_wall_seconds": float(last_drain_usec - start_usec) / 1000000.0 if last_drain_usec >= 0 else -1.0,
		"timing_limitation": "PCM follows the real audio/DSP clock, not fixed-frame simulation. Rendering load and fixed-frame replay can change wall time per replay frame. Drain times are main-thread observations, not sample timestamps. No PCM-to-simulation alignment, device latency, or cross-engine timing parity is established. Samples are not padded, resampled, normalized, trimmed, or synthesized. This pre-fader bus tap cannot establish device output or audible sound; silence must be assessed from actual samples."
	}
	var metadata_file := FileAccess.open(directory.path_join("audio.json"), FileAccess.WRITE)
	if metadata_file == null:
		_fail("Cannot write audio.json: " + error_string(FileAccess.get_open_error()))
		result = false
	else:
		metadata_file.store_string(JSON.stringify(metadata, "\t", true, true))
		metadata_file.flush()
		if metadata_file.get_error() != OK:
			_fail("Writing audio.json failed: " + error_string(metadata_file.get_error()))
			result = false
		metadata_file.close()
	return result

func _put_tag(header: PackedByteArray, offset: int, tag: String) -> void:
	for index in 4:
		header[offset + index] = tag.unicode_at(index)

func _exit_tree() -> void:
	if not finished and not directory.is_empty():
		finish_capture()
