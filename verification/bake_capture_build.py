#!/usr/bin/env python3
"""Embed capture runtime provenance before Godot strips script source on export."""

import argparse
import hashlib
from pathlib import Path


SOURCE_NAMES = (
    "main.gd", "port_player.gd", "game_ui.gd", "coop_client.gd",
    "coop_session.gd", "world_data.gd", "game_data.gd", "gameplay_capture.gd",
)


def bake(project: Path) -> str:
    scripts = project / "scripts"
    digest = hashlib.sha256()
    for name in SOURCE_NAMES:
        digest.update(name.encode("utf-8"))
        digest.update((scripts / name).read_bytes())
    fingerprint = digest.hexdigest()
    (scripts / "gameplay_capture_build.gd").write_text(
        "class_name GameplayCaptureBuild\nextends RefCounted\n\n"
        f'const SOURCE_SHA256 := "{fingerprint}"\n', encoding="utf-8",
    )
    return fingerprint


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1] / "godot")
    args = parser.parse_args()
    print(bake(args.project))


if __name__ == "__main__":
    main()
