#!/usr/bin/env python3
"""Stage production bots with the current game and verified Linux native artifacts.

Build the Box2D adapter from verification/box2d_build.json's exact sources and
patches first. This does not build, export, modify or publish another platform.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
# Reuse the public release's project allowlist, symlink/secret exclusions and
# capture source fingerprint instead of creating a second staging convention.
sys.path.insert(0, str(ROOT / "automation/release"))
from build import stage_project

ENGINE_ARCHIVE_SHA256 = "cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4"
ENGINE_MEMBER = "Godot_v4.7.2-stable_linux.x86_64"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package(args) -> None:
    if args.output.exists():
        raise ValueError("Output must be a new directory")
    pins = json.loads((ROOT / "verification/box2d_build.json").read_text())
    native = json.loads(args.native_provenance.read_text())
    expected = {
        "physics_patch_sha256": sha256(ROOT / pins["patch"]["path"]),
        "fixture_patch_sha256": sha256(ROOT / pins["box2d_fixture_patch"]["path"]),
        "api_sha256": pins["sources"]["engine_api"]["sha256"],
        "library_sha256": sha256(args.library),
        "build_exit_code": 0,
    }
    if any(native.get(key) != value for key, value in expected.items()):
        raise ValueError("Linux physics provenance differs from the current production source pins")
    if sha256(args.godot_archive) != ENGINE_ARCHIVE_SHA256:
        raise ValueError("Official Godot 4.7.2 Linux archive checksum mismatch")
    policy = json.loads((HERE / "pool.json").read_text())
    if sha256(HERE / "policy.gd") != policy["policy"]["sha256"]:
        raise ValueError("Promoted deterministic policy checksum mismatch")

    args.output.mkdir(parents=True)
    runtime = args.output / "runtime"
    runtime.mkdir()
    with zipfile.ZipFile(args.godot_archive) as archive:
        with archive.open(ENGINE_MEMBER) as source, (runtime / "godot").open("wb") as destination:
            shutil.copyfileobj(source, destination)
    (runtime / "godot").chmod(0o755)
    stage_project(args.output / "game")
    addon = args.output / "game/addons/godot-box2d"
    (addon / "bin").mkdir()
    library_name = "libgodot-box2d.linux.template_release.x86_64.so"
    shutil.copy2(args.library, addon / "bin" / library_name)
    # This generated staging manifest is Linux-only. The tracked cross-platform
    # manifest and its canonical artifacts are deliberately left untouched.
    (addon / "godot-box2d.gdextension").write_text(
        '[configuration]\nentry_symbol = "physics_server_box2d_library_init"\n'
        'compatibility_minimum = "4.7"\n\n[libraries]\n'
        f'linux.debug.x86_64 = "res://addons/godot-box2d/bin/{library_name}"\n'
        f'linux.release.x86_64 = "res://addons/godot-box2d/bin/{library_name}"\n'
    )
    # stdout/stderr already have bounded, redacted supervisor logs. Disable only
    # the duplicate native file logger in this generated bot project, not errors.
    with (args.output / "game/project.godot").open("a") as project:
        project.write("\n[debug]\nfile_logging/enable_file_logging=false\n"
                      "file_logging/enable_file_logging.pc=false\n")
    for name in ("supervisor.py", "worker.gd", "policy.gd", "pool.json", "orebit-pvp-bots.service"):
        shutil.copy2(HERE / name, args.output / name)
    authority = args.output / "authority"
    authority.mkdir()
    for name in ("server.py", "pvp.py", "bot_pool.py"):
        shutil.copy2(ROOT / "automation/coop" / name, authority / name)
    provenance = {
        "schema_version": 1,
        "native_base_revision": policy["native_base_revision"],
        "policy": policy["policy"],
        "godot_archive_url": "https://github.com/godotengine/godot/releases/download/4.7.2-stable/" + ENGINE_MEMBER + ".zip",
        "godot_archive_sha256": ENGINE_ARCHIVE_SHA256,
        "native": native,
        "files": {
            path.relative_to(args.output).as_posix(): sha256(path)
            for path in sorted(args.output.rglob("*")) if path.is_file()
        },
    }
    (args.output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "files": len(provenance["files"]),
                      "provenance_sha256": sha256(args.output / "provenance.json")}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot-archive", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--native-provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    package(parser.parse_args())


if __name__ == "__main__":
    main()
