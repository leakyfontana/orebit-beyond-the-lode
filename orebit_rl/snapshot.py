"""Capture and validate an independent, content-pinned Godot runtime.

``python -m orebit_rl.snapshot`` captures the active project once, without
launching Godot. ``--validate [PROJECT]`` checks an existing capture read-only.
Only runtime sources, resources, native extensions and the imported resource
cache are copied; editor state, Android builds and exported games are omitted.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPOSITORY / "godot"
DEFAULT_SNAPSHOT = Path(__file__).with_name("runtime_snapshot")
SOURCE_DIRECTORIES = ("scripts", "scenes", "data", "assets", "animations", "addons", ".godot/imported")
SOURCE_FILES = (
    "project.godot", "main.tscn", ".godot/uid_cache.bin",
    ".godot/extension_list.cfg", ".godot/global_script_class_cache.cfg", ".godot/.gdignore",
)
METADATA_FIELDS = {
    "schema_version", "state", "runtime_project", "source_project", "copy_method",
    "inventory", "file_count", "total_bytes", "fingerprint_sha256", "capture_validation",
}


class SnapshotError(RuntimeError):
    """Unsafe capture, changing source content, or invalid frozen runtime."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fingerprint(inventory: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(inventory)).hexdigest()


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _no_symlink_components(path: Path) -> None:
    for component in (path, *path.parents):
        _require(not component.is_symlink(), f"Symlink paths are not allowed: {component}")


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(REPOSITORY).as_posix()
    except ValueError:
        return str(path)


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _hash_file(path: Path, *, independent: bool) -> dict[str, Any]:
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode), f"Expected a regular, non-symlink runtime file: {path}")
    if independent:
        _require(before.st_nlink == 1, f"Frozen files must not be hardlinked: {path}")
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        _require(_identity(os.fstat(stream.fileno())) == _identity(before), f"File changed before hashing: {path}")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(stream.fileno())
    _require(_identity(before) == _identity(after) == _identity(path.lstat()),
             f"File changed while hashing: {path}")
    return {"size_bytes": before.st_size, "sha256": digest.hexdigest()}


def _temporary_name(name: str) -> bool:
    return (name in {".DS_Store", "Thumbs.db", ".git", "__pycache__"}
            or name.endswith((".tmp", ".temp", ".lock", ".swp", ".swo", "~"))
            or name.startswith((".~", ".#")))


def _walk(root: Path, relative: str, directories: set[str], files: dict[str, Any], *, source: bool) -> None:
    directory = root / relative if relative else root
    _require(stat.S_ISDIR(directory.lstat().st_mode), f"Expected a non-symlink runtime directory: {directory}")
    if relative:
        directories.add(relative)
    with os.scandir(directory) as entries:
        children = sorted(entries, key=lambda entry: entry.name)
    for entry in children:
        if source and _temporary_name(entry.name):
            continue
        name = f"{relative}/{entry.name}" if relative else entry.name
        _require(not entry.is_symlink(), f"Symlinks cannot enter a frozen runtime: {root / name}")
        if entry.is_dir(follow_symlinks=False):
            _walk(root, name, directories, files, source=source)
        elif entry.is_file(follow_symlinks=False):
            files[name] = _hash_file(root / name, independent=not source)
        else:
            raise SnapshotError(f"Non-file runtime entry cannot be captured: {root / name}")


def _inventory(project: Path, *, source: bool) -> dict[str, Any]:
    directories: set[str] = set()
    files: dict[str, Any] = {}
    if source:
        _require(stat.S_ISDIR(project.lstat().st_mode), f"Expected a non-symlink project directory: {project}")
        _require(stat.S_ISDIR((project / ".godot").lstat().st_mode), "Godot import cache must not be a symlink")
        directories.add(".godot")
        for relative in SOURCE_DIRECTORIES:
            _walk(project, relative, directories, files, source=True)
        for relative in SOURCE_FILES:
            files[relative] = _hash_file(project / relative, independent=False)
    else:
        _walk(project, "", directories, files, source=False)
    return {"directories": sorted(directories), "files": dict(sorted(files.items()))}


def _inventory_difference(expected: dict[str, Any], actual: dict[str, Any]) -> str:
    expected_paths = set(expected["files"]) | set(expected["directories"])
    actual_paths = set(actual["files"]) | set(actual["directories"])
    missing = sorted(expected_paths - actual_paths)
    added = sorted(actual_paths - expected_paths)
    changed = sorted(name for name in expected["files"].keys() & actual["files"].keys()
                     if expected["files"][name] != actual["files"][name])
    return f"missing={missing[:5]}, added={added[:5]}, changed={changed[:5]}"


def _valid_relative(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and not PurePosixPath(value).is_absolute() and PurePosixPath(value).as_posix() == value
            and all(part not in {".", ".."} for part in PurePosixPath(value).parts))


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _validate_metadata(metadata: Any) -> None:
    _require(isinstance(metadata, dict) and set(metadata) == METADATA_FIELDS, "Invalid snapshot metadata fields")
    _require(type(metadata["schema_version"]) is int and metadata["schema_version"] == 1,
             "Unsupported snapshot schema")
    _require(metadata["state"] == "immutable" and metadata["runtime_project"] == "godot"
             and metadata["copy_method"] == "independent_byte_copies", "Snapshot is not a frozen runtime capture")
    _require(isinstance(metadata["source_project"], str) and bool(metadata["source_project"]),
             "Snapshot source indication is missing")
    inventory = metadata["inventory"]
    _require(isinstance(inventory, dict) and set(inventory) == {"directories", "files"}, "Invalid snapshot inventory")
    directories, files = inventory["directories"], inventory["files"]
    _require(isinstance(directories, list) and all(_valid_relative(name) for name in directories)
             and directories == sorted(set(directories)), "Invalid snapshot directory inventory")
    _require(isinstance(files, dict) and all(_valid_relative(name) for name in files), "Invalid snapshot file inventory")
    _require(not set(directories).intersection(files), "Snapshot file and directory paths overlap")
    for name, entry in files.items():
        _require(isinstance(entry, dict) and set(entry) == {"size_bytes", "sha256"}
                 and type(entry["size_bytes"]) is int and entry["size_bytes"] >= 0
                 and _valid_hash(entry["sha256"]), f"Invalid snapshot inventory entry: {name}")
    for name in (*directories, *files):
        parent = PurePosixPath(name).parent.as_posix()
        _require(parent == "." or parent in directories, f"Snapshot inventory omits parent directory: {name}")
    _require(set(SOURCE_FILES).issubset(files) and set(SOURCE_DIRECTORIES).issubset(directories),
             "Snapshot omits required runtime roots or import registries")
    _require(any(name.endswith(".gdextension") for name in files), "Snapshot has no native extension configuration")
    _require(any(name.startswith(".godot/imported/") for name in files), "Snapshot imported resource cache is empty")
    _require(type(metadata["file_count"]) is int and metadata["file_count"] == len(files), "Snapshot file count differs")
    _require(type(metadata["total_bytes"]) is int
             and metadata["total_bytes"] == sum(entry["size_bytes"] for entry in files.values()), "Snapshot byte count differs")
    fingerprint = _fingerprint(inventory)
    _require(metadata["fingerprint_sha256"] == fingerprint, "Snapshot inventory fingerprint differs")
    _require(metadata["capture_validation"] == {
        "source_before_sha256": fingerprint, "source_after_sha256": fingerprint, "copied_sha256": fingerprint,
    }, "Snapshot capture validation evidence is incomplete")


def validate_snapshot(project: Path) -> dict[str, Any]:
    """Check every frozen runtime path and byte without writing or launching it.

    ``project`` is the captured ``godot`` directory, whose parent contains
    ``snapshot.json``. The returned metadata includes ``fingerprint_sha256``,
    SHA256 of the canonical complete file-and-directory inventory.
    """
    project = _absolute(Path(project))
    _no_symlink_components(project)
    _require(project.name == "godot", "Snapshot project must be its root's godot directory")
    root = project.parent
    _require({entry.name for entry in root.iterdir()} == {"godot", "snapshot.json", ".gdignore", ".gitignore"},
             "Snapshot root contains missing or unexpected entries")
    metadata_path = root / "snapshot.json"
    _hash_file(metadata_path, independent=True)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _validate_metadata(metadata)
    ignore = root / ".gdignore"
    _hash_file(ignore, independent=True)
    _require(ignore.read_bytes() == b"\n", "Snapshot root .gdignore changed")
    gitignore = root / ".gitignore"
    _hash_file(gitignore, independent=True)
    _require(gitignore.read_bytes() == b"*\n", "Snapshot root .gitignore changed")
    actual = _inventory(project, source=False)
    _require(actual == metadata["inventory"],
             f"Frozen runtime content changed: {_inventory_difference(metadata['inventory'], actual)}")
    return metadata


def _publish(staging: Path, destination: Path) -> None:
    """Atomically rename without replacing even a concurrently-created target."""
    if os.name == "nt":
        os.rename(staging, destination)  # Windows rename refuses existing targets.
        return
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = library.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(staging), os.fsencode(destination), 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(staging), -100, os.fsencode(destination), 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise SnapshotError("This platform lacks atomic no-replace snapshot publication")
    if result != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise SnapshotError(f"Snapshot destination already exists: {destination}")
        raise OSError(code, os.strerror(code), str(destination))


def capture_snapshot(source_project: Path = DEFAULT_SOURCE, destination: Path = DEFAULT_SNAPSHOT) -> dict[str, Any]:
    """Publish one independent capture, or fail without a ready destination.

    Source contents and selected pathsets must agree before and after copying;
    copied contents must match that same inventory. No source file is written,
    no existing destination is replaced, and no capture failure is retried.
    """
    source_project, destination = _absolute(Path(source_project)), _absolute(Path(destination))
    _no_symlink_components(source_project)
    _no_symlink_components(destination)
    _require(not os.path.lexists(destination), f"Snapshot destination already exists: {destination}")
    _require(destination.parent.is_dir(), f"Snapshot destination parent does not exist: {destination.parent}")
    _require(not destination.is_relative_to(source_project) and not source_project.is_relative_to(destination),
             "Snapshot source and destination must not contain one another")
    before = _inventory(source_project, source=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.capture-", dir=destination.parent))
    try:
        project = staging / "godot"
        project.mkdir()
        for relative in before["directories"]:
            (project / relative).mkdir()
        for relative in before["files"]:
            shutil.copy2(source_project / relative, project / relative, follow_symlinks=False)
        after = _inventory(source_project, source=True)
        _require(after == before,
                 f"Active runtime changed during snapshot capture; no snapshot published: {_inventory_difference(before, after)}")
        copied = _inventory(project, source=False)
        _require(copied == before,
                 f"Copied runtime differs from the initial source; no snapshot published: {_inventory_difference(before, copied)}")
        fingerprint = _fingerprint(before)
        metadata = {
            "schema_version": 1, "state": "immutable", "runtime_project": "godot",
            "source_project": _display_path(source_project), "copy_method": "independent_byte_copies",
            "inventory": before, "file_count": len(before["files"]),
            "total_bytes": sum(entry["size_bytes"] for entry in before["files"].values()),
            "fingerprint_sha256": fingerprint,
            "capture_validation": {"source_before_sha256": fingerprint,
                                   "source_after_sha256": _fingerprint(after), "copied_sha256": _fingerprint(copied)},
        }
        _validate_metadata(metadata)
        (staging / ".gdignore").write_bytes(b"\n")
        (staging / ".gitignore").write_bytes(b"*\n")
        (staging / "snapshot.json").write_text(json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                               encoding="utf-8")
        _publish(staging, destination)
        return metadata
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Active Godot project to copy read-only")
    parser.add_argument("--destination", type=Path, default=DEFAULT_SNAPSHOT, help="New snapshot root; must not exist")
    parser.add_argument("--validate", type=Path, nargs="?", const=DEFAULT_SNAPSHOT / "godot",
                        help="Validate a frozen project instead of capturing; defaults to the standard snapshot")
    arguments = parser.parse_args()
    try:
        if arguments.validate is not None:
            project = _absolute(arguments.validate)
            metadata = validate_snapshot(project)
            status = "valid"
        else:
            destination = _absolute(arguments.destination)
            metadata = capture_snapshot(arguments.source, destination)
            project = destination / "godot"
            status = "ready"
        print(json.dumps({"status": status, "snapshot_project": _display_path(project),
                          "snapshot_metadata": _display_path(project.parent / "snapshot.json"),
                          "fingerprint_sha256": metadata["fingerprint_sha256"],
                          "file_count": metadata["file_count"], "total_bytes": metadata["total_bytes"]}, sort_keys=True))
        return 0
    except (SnapshotError, OSError, ValueError) as error:
        print(json.dumps({"status": "error", "error": type(error).__name__, "message": str(error)}, sort_keys=True),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
