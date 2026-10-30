#!/usr/bin/env python3
"""Build the existing Box2D backend and export the Godot Web/PWA preset."""
import argparse
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "verification/tools"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", default=str(TOOLS / "Godot.app/Contents/MacOS/Godot"))
    parser.add_argument("--scons", help="Override the SCons executable; defaults to the repository Python environment")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if shutil.which("emcc") is None:
        parser.error("Emscripten must be installed and emcc available on PATH")
    templates = TOOLS / "export_templates/templates"
    names = ["web_dlink_nothreads_debug.zip", "web_dlink_nothreads_release.zip"]
    missing = [name for name in names if not (templates / name).is_file()]
    if missing:
        with zipfile.ZipFile(TOOLS / "Godot_v4.7.2-stable_export_templates.tpz") as archive:
            for name in missing:
                archive.extract("templates/" + name, TOOLS / "export_templates")
    scons = [args.scons] if args.scons else [str(TOOLS / "asset-inspection/bin/python"), "-m", "SCons"]
    subprocess.run([*scons, "-C", str(TOOLS / "box2d-source"), "platform=web",
                    "arch=wasm32", "target=template_release", "precision=single",
                    "threads=no", "-j" + str(args.jobs)], cwd=ROOT, check=True)
    library = "libgodot-box2d.web.template_release.wasm32.nothreads.wasm"
    shutil.copy2(TOOLS / "box2d-source/bin/addons/godot-box2d/bin" / library,
                 ROOT / "godot/addons/godot-box2d/bin" / library)
    output = ROOT / "godot/exports/web/index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([args.godot, "--headless", "--path", str(ROOT / "godot"),
                    "--export-release", "Web", str(output)], cwd=ROOT, check=True)
    print("Web/PWA export: " + str(output))


if __name__ == "__main__":
    main()
