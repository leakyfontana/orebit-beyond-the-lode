class_name NativeAnimationSet
extends Resource

## Import-time schema. No Unity curves or controller objects are needed at runtime.
## library tracks address binding slots until NativeAnimator binds an actor once.
@export var schema_version: int = 1
@export var controller_id: String = ""
@export var source_sha256: String = ""
@export var library: AnimationLibrary
@export var machine: AnimationNodeStateMachine
@export var default_node: StringName
@export var bindings: Array[Dictionary] = []
@export var parameters: Dictionary = {}
## Native node name -> {name, behaviors, triggers, boundaries, length, loop}.
@export var states: Dictionary = {}
@export var gates: PackedStringArray = PackedStringArray()
## Deliberately empty original controllers are valid native, non-playing resources.
@export var empty: bool = false
