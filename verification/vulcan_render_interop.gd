extends SceneTree

# Run with a real renderer, not --headless: verifies pixels, not just node flags.
class RenderHost extends Node2D:
	var world_root := Node2D.new()

var _results: Array[Dictionary] = []
var _view: VulcanView
var _viewport: SubViewport

func _initialize() -> void:
	call_deferred("_run")

func _snapshot(count: int, server_time: float) -> Dictionary:
	var segments: Array = []
	for i in count:
		segments.append([18.5 - i, -3.5])
	return {"worm": {"segments": segments, "direction": [1, 0], "server_time": server_time}}

func _run() -> void:
	var container := SubViewportContainer.new()
	root.add_child(container)
	_viewport = SubViewport.new()
	_viewport.size = Vector2i(1056, 384)
	_viewport.transparent_bg = true
	_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	container.add_child(_viewport)
	var host := RenderHost.new()
	_viewport.add_child(host)
	host.add_child(host.world_root)
	host.world_root.position = Vector2(32, 40)
	host.world_root.scale = Vector2.ONE * 48.0
	_view = VulcanView.new()
	host.add_child(_view)
	_view.configure(host, null)
	# Initial load, growth, shrink, stale packet and scene re-entry all need pixels.
	_view.scene_loaded(_snapshot(10, 1794268800.0))
	if not await _visible(10, "initial"):
		return
	_view.apply_event(_snapshot(15, 1794268800.1))
	if not await _visible(15, "growth"):
		return
	_view.apply_event(_snapshot(8, 1794268800.2))
	if not await _visible(8, "shrink"):
		return
	_view.apply_event(_snapshot(15, 1794268799.0))
	if not await _visible(8, "stale"):
		return
	_view.clear()
	_view.scene_loaded(_snapshot(15, 1794268801.0))
	if not await _visible(15, "reentry"):
		return
	_finish(true, "")

func _visible(count: int, stage: String) -> bool:
	_view.tick(0.1)
	await process_frame
	await RenderingServer.frame_post_draw
	var image := _viewport.get_texture().get_image()
	for i in 18:
		var center := Vector2(32, 40) + Vector2(18.5 - i, 3.5) * 48.0
		var alpha := image.get_pixelv(Vector2i(center)).a
		if (alpha > 0.5) != (i < count):
			_finish(false, "%s: segment %d alpha=%f expected_visible=%s" % [stage, i, alpha, i < count])
			return false
	image.save_png("user://vulcan-render-%s.png" % stage)
	_results.append({"stage": stage, "visible_segments": count})
	return true

func _finish(passed: bool, failure: String) -> void:
	var result := {"passed": passed, "failure": failure, "observations": _results,
		"platform": OS.get_name(), "renderer": RenderingServer.get_current_rendering_method()}
	var file := FileAccess.open("user://vulcan-render-result.json", FileAccess.WRITE)
	file.store_string(JSON.stringify(result))
	file.close()
	print("VULCAN_RENDER_INTEROP " + JSON.stringify(result))
	# Leave the Android surface available briefly for an OS screenshot.
	if OS.has_feature("android"):
		await create_timer(10.0).timeout
	quit(0 if passed else 1)
