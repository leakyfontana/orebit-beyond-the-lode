@tool
extends EditorPlugin

class AuthReturnExport extends EditorExportPlugin:
	func _get_name() -> String:
		return "OrebitAuthReturn"

	func _supports_platform(platform: EditorExportPlatform) -> bool:
		return platform is EditorExportPlatformAndroid

	func _get_android_manifest_application_element_contents(_platform: EditorExportPlatform, _debug: bool) -> String:
		# The URI only resumes the initiating game. Credentials stay in its poll.
		return """
<activity-alias android:name="org.motherloadrecoded.game.AuthReturn"
    android:targetActivity="com.godot.game.GodotApp" android:exported="true">
    <intent-filter>
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data android:scheme="org.motherloadrecoded.game" android:host="auth" android:path="/discord" />
    </intent-filter>
</activity-alias>
"""

var _export_plugin: AuthReturnExport

func _enter_tree() -> void:
	_export_plugin = AuthReturnExport.new()
	add_export_plugin(_export_plugin)

func _exit_tree() -> void:
	remove_export_plugin(_export_plugin)
	_export_plugin = null
