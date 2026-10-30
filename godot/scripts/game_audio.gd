class_name GameAudio
extends Node

var definitions: Dictionary
var state: GameData
var sounds: Dictionary = {}
var music: Dictionary = {}
var one_shot_streams: Dictionary = {}
var one_shots: Dictionary = {}
var paused: Array[String] = []
var rng: UnityRandom
var evidence_capture: AudioEvidenceCapture

# AudioManager's serialized array order (MainMenu.unity:958-1373), not JSON key
# order. Even zero-width volume ranges consume the shared Unity RNG.
const SOUND_ORDER := [
	"ComputerTypeLetter2", "Error2", "Purchase", "SelectUpgrade",
	"SelectUpgradeCategory", "SellMinerals", "MineralGet", "GetSideDrillOut",
	"GetRotorOut", "Drill", "IdlePlayer", "RotorPlayer", "Dynamite", "C4",
	"MatterTransmitter", "QuantumTeleporter", "Nanobots", "Refuel", "DrillClink",
	"MothershipArrive", "MothershipIdle", "MothershipLeave", "Transmission",
	"LowFuelWarning", "VeryLowFuelWarning", "PlayerCrash", "NoItemAvailable",
	"SatanStep", "SatanStep2", "P1Laugh", "P1Death", "P1Damage1", "P1Damage2",
	"P2Breakout", "P2Death", "P2ExtendArm", "P2HitArm", "P2RetractArm",
	"P2Fireball", "P2Fireloop", "JettisonMineral", "Lava", "KillPlayer",
]
const MUSIC_ORDER := ["MainLevelMusic", "ShopMusic", "BossMusic"]

func configure(source: Dictionary, game_state: GameData, random_source: UnityRandom) -> void:
	definitions = source
	state = game_state
	rng = random_source
	var capture_directory := ""
	var has_replay := false
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--replay="):
			has_replay = not argument.trim_prefix("--replay=").is_empty()
		elif argument.begins_with("--capture="):
			capture_directory = argument.trim_prefix("--capture=")
	if has_replay and not capture_directory.is_empty():
		evidence_capture = AudioEvidenceCapture.new()
		add_child(evidence_capture)
		if not evidence_capture.start(capture_directory):
			evidence_capture.finish_capture()
			get_tree().quit(1)
			return
	for category in ["sounds", "music"]:
		for key in definitions.get(category, {}):
			var entry: Dictionary = definitions[category][key]
			var path: String = entry.get("clip", {}).get("path", "")
			if not ResourceLoader.exists(path):
				push_error("Missing original audio clip: " + key + " " + path)
				continue
			var player := AudioStreamPlayer.new()
			player.name = key
			var clip: AudioStream = _clip_with_loop(load(path), false)
			player.stream = _clip_with_loop(clip, true) if bool(entry.get("loop", false)) else clip
			add_child(player)
			if category == "sounds":
				sounds[key] = player
				one_shot_streams[key] = clip
				one_shots[key] = []
			else:
				music[key] = player

func _clip_with_loop(clip: AudioStream, looped: bool) -> AudioStream:
	# Loop inside the mixer, never via a main-thread finished signal. Keep the
	# one-shot resource non-looping, even for a looping AudioSource's clip.
	var stream: AudioStream = clip.duplicate()
	if stream is AudioStreamWAV:
		stream.loop_mode = AudioStreamWAV.LOOP_FORWARD if looped else AudioStreamWAV.LOOP_DISABLED
		stream.loop_begin = 0
		stream.loop_end = roundi(stream.get_length() * stream.mix_rate)
	elif stream is AudioStreamMP3 or stream is AudioStreamOggVorbis:
		stream.loop = looped
		stream.loop_offset = 0.0
	else:
		push_error("Unsupported original audio stream type: " + stream.get_class())
		return null
	return stream

func _settings(key: String, is_music: bool) -> void:
	var group := music if is_music else sounds
	if not group.has(key):
		push_error("Undefined original audio: " + key)
		return
	var entry: Dictionary = definitions["music" if is_music else "sounds"][key]
	var volume := _volume(entry, is_music)
	var variance := rng.single(float(entry.get("pitchVariance", 0)))
	var pitch := rng.single(rng.single(float(entry.get("pitch", 1))) * rng.single(1.0 + rng.range_float(-variance / 2.0, variance / 2.0)))
	if is_music:
		group[key].volume_linear = volume
		group[key].pitch_scale = minf(pitch, 3.0)
	else:
		_set_sound_volume(key, volume)
		_set_sound_pitch(key, pitch)

func _volume(entry: Dictionary, is_music: bool) -> float:
	var variance := rng.single(float(entry.get("volumeVariance", 0)))
	var volume := rng.single(rng.single(float(entry.get("volume", 1))) * rng.single(1.0 + rng.range_float(-variance / 2.0, variance / 2.0)))
	volume = rng.single(volume * rng.single(state.music_volume if is_music else state.sound_volume))
	return clampf(volume, 0.0, 1.0)

func PlayMusic(key: String) -> void:
	StopAllMusic()
	if music.has(key):
		_settings(key, true)
		music[key].play()

func PlaySound(key: String) -> void:
	if sounds.has(key):
		_settings(key, false)
		sounds[key].stream_paused = false
		sounds[key].play()

func PlaySoundOneShot(key: String) -> void:
	if not sounds.has(key):
		push_error("Undefined original sound: " + key)
		return
	_settings(key, false)
	var voice := AudioStreamPlayer.new()
	voice.stream = one_shot_streams[key]
	voice.volume_db = sounds[key].volume_db
	voice.pitch_scale = sounds[key].pitch_scale
	add_child(voice)
	one_shots[key].append(voice)
	voice.finished.connect(_finish_one_shot.bind(key, voice))
	voice.play()

func _finish_one_shot(key: String, voice: AudioStreamPlayer) -> void:
	one_shots[key].erase(voice)
	voice.queue_free()

func _set_sound_volume(key: String, volume: float) -> void:
	sounds[key].volume_linear = volume
	for voice: AudioStreamPlayer in one_shots[key]:
		voice.volume_linear = volume

func _set_sound_pitch(key: String, pitch: float) -> void:
	# AudioSource clips cap pitch at 3. All shipped pitch settings/callers are
	# positive; do not replace the source's float32 sum with a 0.01 floor.
	pitch = minf(pitch, 3.0)
	sounds[key].pitch_scale = pitch
	for voice: AudioStreamPlayer in one_shots[key]:
		voice.pitch_scale = pitch

func _sound_is_playing(key: String) -> bool:
	var player: AudioStreamPlayer = sounds[key]
	if player.playing and not player.stream_paused:
		return true
	for voice: AudioStreamPlayer in one_shots[key]:
		if voice.playing and not voice.stream_paused:
			return true
	return false

func _pause_sound(key: String, pause: bool) -> void:
	sounds[key].stream_paused = pause
	for voice: AudioStreamPlayer in one_shots[key]:
		voice.stream_paused = pause

func StopSound(key: String) -> void:
	if sounds.has(key):
		sounds[key].stop()
		sounds[key].stream_paused = false
		# Godot does not emit finished on stop; release explicitly as well.
		for voice: AudioStreamPlayer in one_shots[key]:
			voice.stop()
			voice.queue_free()
		one_shots[key].clear()

func StopAllMusic() -> void:
	for player in music.values():
		player.stop()

func StopAllSounds() -> void:
	# Source checks isPlaying, so a paused-only source is not stopped here.
	for key in sounds:
		if _sound_is_playing(key):
			StopSound(key)

func PauseSounds() -> void:
	paused.clear()
	for key in sounds:
		if _sound_is_playing(key):
			_pause_sound(key, true)
			paused.append(key)

func ResumeSounds() -> void:
	# The source remembers AudioSources, not the individual voices at pause.
	for key in paused:
		_pause_sound(key, false)

func ChangeSoundPitch(key: String, value_to_add: float) -> void:
	if sounds.has(key):
		_set_sound_pitch(key, rng.single(rng.single(float(definitions.sounds[key].get("pitch", 1))) + rng.single(value_to_add)))

func setNewVolumeLevels() -> void:
	# Source updates volume only, music first; pitch draws would shift shared RNG.
	for key in MUSIC_ORDER:
		if music.has(key):
			music[key].volume_linear = _volume(definitions.music[key], true)
	for key in SOUND_ORDER:
		if sounds.has(key):
			_set_sound_volume(key, _volume(definitions.sounds[key], false))

func finish_capture() -> bool:
	return evidence_capture.finish_capture() if evidence_capture != null else true
