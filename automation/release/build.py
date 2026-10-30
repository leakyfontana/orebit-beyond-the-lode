#!/usr/bin/env python3
"""Build a beta from source in a disposable project; never mutate godot/.

Hosted runners: macos-15 (ARM64), windows-2022, ubuntu-24.04 (Android/Web).
Install Python 3.10+, SCons 4, Git and the native compiler first. Android also
needs JAVA_HOME (17), ANDROID_HOME, platform-tools, platforms;android-36,
build-tools;36.1.0, ndk;29.0.14206865 (official Gradle template), and
ndk;28.1.13356709 (pinned Box2D backend). Web needs emsdk 6.0.13 activated.
Production Android requires the preserved beta key via OREBIT_ANDROID_KEYSTORE,
OREBIT_ANDROID_KEYSTORE_PASSWORD and OREBIT_ANDROID_KEYSTORE_ALIAS. On macOS the
preserved Godot Application Support/Godot/keystores/debug.keystore is accepted
locally with its standard alias/password. No production identity is generated.
--validation uses an ephemeral Android key and writes only dist/validation/.

Godot 4.7.2 and export templates are downloaded with pinned SHA-256 checksums.
The three source commits and engine API hash come from verification/box2d_build.json;
all backend libraries are compiled afresh. --godot overrides only the executable,
not the required version/API check or downloaded templates. Mac exports are ARM64
and ad-hoc signed, not notarized: downloaded apps may require the user's explicit
Gatekeeper approval in Privacy & Security. No Apple account is needed.
"""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
GODOT_VERSION = "4.7.2"
RELEASE_URL = "https://github.com/godotengine/godot-builds/releases/download/4.7.2-stable/"
# Official godot-builds 4.7.2-stable asset digests, not mutable latest links.
ASSETS = {
    "Godot_v4.7.2-stable_export_templates.tpz": "f298490b8d44d934be425a5a65a51bf15f422428b229a06a6e11d9ffea248011",
    "Godot_v4.7.2-stable_linux.x86_64.zip": "cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4",
    "Godot_v4.7.2-stable_macos.universal.zip": "c58a24e31d720be9d62f60cb5627c4e695fb72f21b0cfe1bc9ccaa9a3b3ba63e",
    "Godot_v4.7.2-stable_win64.exe.zip": "731980f9608d61333e5baf54a2ef17210acc7a538446c0cb9969f002aca1e953",
}
TARGETS = {
    "macos-arm64": ("macos", "arm64", "macOS ARM64", "libgodot-box2d.macos.template_release.framework"),
    "windows-x86_64": ("windows", "x86_64", "Windows x86_64", "libgodot-box2d.windows.template_release.x86_64.dll"),
    "android-arm64": ("android", "arm64", "Android arm64", "libgodot-box2d.android.template_release.arm64.so"),
    "web": ("web", "wasm32", "Web", "libgodot-box2d.web.template_release.wasm32.nothreads.wasm"),
}
EXCLUDES = ("data/unity_manifest.json,exports/*,android/*,tools/*,verification/*,"
            "*.import,*.keystore,*.jks,*.pem,*.key,*.env,*.cs,*.meta,*.py,*.ps1,*.sh")
# Public certificate fingerprint of the preserved beta-1/beta-2 APK identity.
BETA_SIGNER_SHA256 = "3f6a839417710379c51f940de8810bde1d67d5542708f30a5ee3380f33f3bdf1"
SECRETS = []


def run(command, cwd=None, env=None):
    """Stream diagnostics with signing passwords redacted, including Gradle errors."""
    command = [str(part) for part in command]
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines = []
    for line in process.stdout:
        for secret in SECRETS:
            line = line.replace(secret, "[REDACTED]")
        print(line, end="", flush=True)
        lines.append(line)
    if process.wait():
        raise RuntimeError("Command failed: " + Path(command[0]).name)
    return "".join(lines).strip()


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(name, directory):
    destination = directory / name
    print("Downloading pinned " + name, flush=True)
    request = urllib.request.Request(RELEASE_URL + name, headers={"User-Agent": "orebit-beta-builder"})
    with urllib.request.urlopen(request, timeout=120) as source, destination.open("wb") as output:
        shutil.copyfileobj(source, output)
    if sha256(destination) != ASSETS[name]:
        raise RuntimeError("Checksum mismatch for " + name)
    return destination


def extract_zip(archive, destination, members=None):
    """Extract trusted, checksum-verified tools, preserving Unix executable bits."""
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            if members is not None and entry.filename not in members:
                continue
            parts = PurePosixPath(entry.filename).parts
            if not parts or entry.filename.startswith("/") or ".." in parts or "\\" in entry.filename:
                raise RuntimeError("Unsafe tool archive member")
            target = destination.joinpath(*parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                link = source.read(entry).decode("utf-8")
                resolved = (target.parent / link).resolve()
                if not resolved.is_relative_to(destination.resolve()):
                    raise RuntimeError("Tool archive symlink escapes extraction directory")
                target.symlink_to(link)
            else:
                with source.open(entry) as data, target.open("wb") as output:
                    shutil.copyfileobj(data, output)
                if mode & 0o777:
                    target.chmod(mode & 0o777)


def bootstrap_tools(work, godot_override, target):
    templates_archive = download("Godot_v4.7.2-stable_export_templates.tpz", work)
    template_names = {
        "macos": {"macos.zip"},
        "windows": {"windows_debug_x86_64.exe", "windows_release_x86_64.exe"},
        "android": {"android_debug.apk", "android_release.apk", "android_source.zip"},
        "web": {"web_dlink_nothreads_debug.zip", "web_dlink_nothreads_release.zip"},
    }[target] | {"version.txt"}
    extract_zip(templates_archive, work / "export_templates",
                {"templates/" + name for name in template_names})
    templates_archive.unlink()
    templates = work / "export_templates/templates"
    if (templates / "version.txt").read_text().strip() != "4.7.2.stable":
        raise RuntimeError("Unexpected export template version")
    if godot_override:
        godot = Path(godot_override).expanduser().resolve()
    else:
        system_asset = {"Darwin": "macos.universal.zip", "Windows": "win64.exe.zip", "Linux": "linux.x86_64.zip"}
        archive = download("Godot_v4.7.2-stable_" + system_asset[platform.system()], work)
        editor = work / "editor"
        extract_zip(archive, editor)
        archive.unlink()
        if platform.system() == "Darwin":
            godot = editor / "Godot.app/Contents/MacOS/Godot"
        elif platform.system() == "Windows":
            godot = editor / "Godot_v4.7.2-stable_win64_console.exe"
        else:
            godot = editor / "Godot_v4.7.2-stable_linux.x86_64"
    if not run([godot, "--version"]).startswith("4.7.2.stable."):
        raise RuntimeError("The engine must be official Godot 4.7.2 stable")
    return godot, templates


def checkout(source, destination):
    run(["git", "init", "--quiet", destination])
    run(["git", "-C", destination, "remote", "add", "origin", source["url"]])
    run(["git", "-C", destination, "fetch", "--quiet", "--depth=1", "origin", source["commit"]])
    run(["git", "-C", destination, "checkout", "--quiet", "--detach", "FETCH_HEAD"])


def bootstrap_sources(work, godot, provenance):
    sources = provenance["sources"]
    adapter = work / "box2d-source"
    checkout(sources["adapter"], adapter)
    checkout(sources["box2d_submodule"], adapter / "box2d")
    cpp = work / "godot-cpp-10"
    checkout(sources["godot_cpp"], cpp)
    for directory, patch in ((adapter, provenance["patch"]["path"]),
                             (adapter / "box2d", provenance["box2d_fixture_patch"]["path"]),
                             (cpp, "verification/godot-cpp-msvc-conformance.patch")):
        run(["git", "-C", directory, "apply", ROOT / patch])
    api_directory = work / "engine-api-4.7.2"
    api_directory.mkdir()
    run([godot, "--headless", "--dump-extension-api"], cwd=api_directory)
    api = api_directory / "extension_api.json"
    if sha256(api) != sources["engine_api"]["sha256"]:
        raise RuntimeError("Godot engine API differs from pinned Box2D build provenance")
    return adapter, api


def compile_backend(adapter, api, target, arch, jobs):
    arguments = [sys.executable, "-m", "SCons", "-C", adapter,
                 "platform=" + target, "arch=" + arch, "target=template_release",
                 "precision=single", "custom_api_file=" + str(api), "-j" + str(jobs)]
    if target == "web":
        arguments += ["threads=no"]
    elif target == "android":
        arguments += ["ndk_version=28.1.13356709", "android_api_level=24"]
    elif target == "windows":
        arguments += ["use_static_cpp=yes", "msvc_version=14.3"]
        vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
        installation = run([vswhere, "-latest", "-products", "*", "-requires",
                            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"])
        setup = Path(installation) / "VC/Auxiliary/Build/vcvars64.bat"
        if not setup.is_file():
            raise RuntimeError("MSVC v143 x64 developer tools are required")
        arguments += ["msvc_setup_script=" + str(setup)]
    environment = os.environ.copy()
    if target == "macos":
        environment["PATH"] = "/usr/bin:" + environment.get("PATH", "")
    run(arguments, env=environment)


def stage_project(destination):
    destination.mkdir()
    # Copy only runtime project roots, never exports, editor caches, Android's
    # previous Gradle assets, native binaries or repository-private automation.
    allowed = {"project.godot", "export_presets.cfg", "main.tscn", "scripts", "data",
               "assets", "animations", "scenes", "addons"}
    def ignored(directory, names):
        if any((Path(directory) / name).is_symlink() for name in names):
            raise RuntimeError("Runtime project symlinks are not accepted for release staging")
        return [name for name in names if name.startswith(".") or name in {"bin", "tools", "exports", "__pycache__"}
                or name.endswith((".keystore", ".jks", ".pem", ".key", ".env"))]
    for name in sorted(allowed):
        source = ROOT / "godot" / name
        if source.is_symlink():
            raise RuntimeError("Runtime project roots cannot be symlinks")
        if source.is_dir():
            shutil.copytree(source, destination / name, ignore=ignored)
        elif source.is_file():
            shutil.copy2(source, destination / name)
        else:
            raise RuntimeError("Missing source runtime project path: " + name)


def read_presets(path):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def write_presets(parser, path):
    with path.open("w", encoding="utf-8", newline="\n") as output:
        parser.write(output, space_around_delimiters=False)


def install_library(adapter, project, name):
    source = adapter / "bin/addons/godot-box2d/bin" / name
    destination = project / "addons/godot-box2d/bin" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return destination


def android_signer(work, validation):
    if validation:
        key = work / "validation.keystore"
        password, alias = "android", "androiddebugkey"
        run(["keytool", "-genkeypair", "-noprompt", "-keystore", key, "-storepass", password,
             "-keypass", password, "-alias", alias, "-dname", "CN=Orebit PR Validation",
             "-keyalg", "RSA", "-keysize", "2048", "-validity", "30"])
    else:
        explicit = os.environ.get("OREBIT_ANDROID_KEYSTORE")
        local_key = Path.home() / "Library/Application Support/Godot/keystores/debug.keystore"
        key = Path(explicit).expanduser().resolve() if explicit else local_key
        password = os.environ.get("OREBIT_ANDROID_KEYSTORE_PASSWORD", "" if explicit else "android")
        alias = os.environ.get("OREBIT_ANDROID_KEYSTORE_ALIAS", "" if explicit else "androiddebugkey")
        if not key.is_file() or not password or not alias:
            raise RuntimeError("Preserved beta signer required: set OREBIT_ANDROID_KEYSTORE, OREBIT_ANDROID_KEYSTORE_PASSWORD and OREBIT_ANDROID_KEYSTORE_ALIAS; no replacement key is generated")
    SECRETS.append(password)
    if not validation:
        # Export only the public DER certificate; passwords stay out of argv/logs.
        key_environment = os.environ.copy()
        key_environment["OREBIT_SIGNER_STOREPASS"] = password
        certificate = subprocess.run(
            ["keytool", "-exportcert", "-keystore", str(key), "-alias", alias,
             "-storepass:env", "OREBIT_SIGNER_STOREPASS"],
            env=key_environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        if hashlib.sha256(certificate).hexdigest() != BETA_SIGNER_SHA256:
            raise RuntimeError("Android key does not match the preserved published beta signer; refusing identity change")
    return key, password, alias


def configure_android(work, project, templates, options, environment, signer):
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    java = os.environ.get("JAVA_HOME")
    if not sdk or not java:
        raise RuntimeError("Android requires ANDROID_HOME and JAVA_HOME (Java 17)")
    environment["ANDROID_HOME"] = sdk
    key, password, alias = signer
    environment["GODOT_ANDROID_KEYSTORE_DEBUG_PATH"] = str(key)
    environment["GODOT_ANDROID_KEYSTORE_DEBUG_USER"] = alias
    environment["GODOT_ANDROID_KEYSTORE_DEBUG_PASSWORD"] = password
    # Android is built on Ubuntu only. An isolated XDG config prevents touching
    # the user's Godot editor settings and makes SDK selection non-interactive.
    config = work / "config"
    environment["XDG_CONFIG_HOME"] = str(config)
    settings = config / "godot/editor_settings-4.7.tres"
    settings.parent.mkdir(parents=True)
    settings.write_text('[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
                        + 'export/android/android_sdk_path=' + json.dumps(sdk) + '\n'
                        + 'export/android/java_sdk_path=' + json.dumps(java) + '\n'
                        + 'export/android/debug_keystore=' + json.dumps(str(key)) + '\n'
                        + 'export/android/debug_keystore_user=' + json.dumps(alias) + '\n'
                        + 'export/android/debug_keystore_pass=' + json.dumps(password) + '\n', encoding="utf-8")
    source = templates / "android_source.zip"
    build = project / "android/build"
    extract_zip(source, build)
    (build.parent / ".gdignore").write_text("", encoding="utf-8")
    # With a custom source template Godot identifies it by absolute path + MD5.
    identifier = source.as_posix() + " [" + hashlib.md5(source.read_bytes()).hexdigest() + "]"
    (build.parent / ".build_version").write_text(identifier + "\n", encoding="utf-8")
    # Godot appends /build to this preset value.
    options["gradle_build/gradle_build_directory"] = '"res://android"'


def package_zip(directory, destination):
    """Stable ordering/timestamps; preserve executable modes and app symlinks."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if any(part.startswith(".") or part == "__MACOSX" for part in relative.parts) or path.suffix == ".import":
                raise RuntimeError("Unexpected private/sidecar export output: " + relative.as_posix())
            if path.is_dir() and not path.is_symlink():
                continue
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = path.lstat().st_mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            if path.is_symlink():
                archive.writestr(info, os.readlink(path))
            else:
                with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as output:
                    shutil.copyfileobj(source, output)


def build(args):
    system, machine = platform.system(), platform.machine().lower()
    expected = {"macos-arm64": "Darwin", "windows-x86_64": "Windows", "android-arm64": "Linux", "web": "Linux"}
    if system != expected[args.platform] or (args.platform == "macos-arm64" and machine != "arm64"):
        raise RuntimeError("Use the platform-specific hosted runner documented in --help")
    if system != "Darwin" and machine not in {"x86_64", "amd64"}:
        raise RuntimeError("Windows/Android/Web build hosts must be x86_64")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != args.sha:
        raise RuntimeError("--sha must equal the checked-out full HEAD commit")
    presets = read_presets(ROOT / "godot/export_presets.cfg")
    source_version = json.loads(presets["preset.1.options"]["version/name"])
    version = source_version + "+" + args.sha[:12]
    provenance = json.loads((ROOT / "verification/box2d_build.json").read_text())
    target, arch, preset_name, library = TARGETS[args.platform]
    output_root = ROOT / ("dist/validation" if args.validation else "dist")
    metadata_path = output_root / "metadata" / (args.platform + ".json")
    # Never leave an older successful manifest behind after a failed rebuild.
    metadata_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="orebit-release-") as temporary:
        work = Path(temporary)
        signer = android_signer(work, args.validation) if target == "android" else None
        godot, templates = bootstrap_tools(work, args.godot, target)
        adapter, api = bootstrap_sources(work, godot, provenance)
        project = work / "project"
        stage_project(project)
        environment = os.environ.copy()
        if target in {"android", "web"}:
            compile_backend(adapter, api, "linux", "x86_64", args.jobs)
            host_library = "libgodot-box2d.linux.template_release.x86_64.so"
            install_library(adapter, project, host_library)
            extension = project / "addons/godot-box2d/godot-box2d.gdextension"
            with extension.open("a", encoding="utf-8") as output:
                for mode in ("debug", "release"):
                    output.write('\nlinux.' + mode + '.x86_64 = "res://addons/godot-box2d/bin/' + host_library + '"\n')
        compile_backend(adapter, api, target, arch, args.jobs)
        install_library(adapter, project, library)
        for section in presets.sections():
            if not section.endswith(".options"):
                presets[section]["exclude_filter"] = json.dumps(EXCLUDES)
            else:
                for key in ("custom_template/debug", "custom_template/release", "gradle_build/android_source_template"):
                    if key in presets[section]:
                        name = PurePosixPath(json.loads(presets[section][key])).name
                        presets[section][key] = json.dumps((templates / name).as_posix())
        options = presets[{"macos": "preset.3.options", "windows": "preset.0.options", "android": "preset.1.options", "web": "preset.2.options"}[target]]
        if target == "android":
            options["version/code"] = str(1000 + args.run_number)
            options["version/name"] = json.dumps(version)
            configure_android(work, project, templates, options, environment, signer)
        elif target == "macos":
            options["application/version"] = json.dumps(str(1000 + args.run_number))
        write_presets(presets, project / "export_presets.cfg")
        run([godot, "--headless", "--editor", "--path", project, "--import"], cwd=work, env=environment)
        export = work / "export"
        export.mkdir()
        filename = {"macos": "MotherloadRecoded.app", "windows": "MotherloadRecoded.exe", "android": "MotherloadRecoded.apk", "web": "index.html"}[target]
        run([godot, "--headless", "--path", project,
             "--export-debug" if target == "android" else "--export-release", preset_name, export / filename], cwd=work, env=environment)
        if not (export / filename).exists():
            raise RuntimeError("Godot did not produce the expected export")
        if target == "macos":
            frameworks = list((export / filename).rglob(library))
            if len(frameworks) != 1:
                raise RuntimeError("Exported app is missing its matching native Box2D framework")
        elif target == "windows" and not list(export.rglob(library)):
            raise RuntimeError("Exported Windows directory is missing its matching Box2D DLL")
        elif target == "android":
            with zipfile.ZipFile(export / filename) as apk:
                if "lib/arm64-v8a/" + library not in apk.namelist():
                    raise RuntimeError("APK is missing the matching ARM64 Box2D library")
        elif target == "web":
            if not list(export.glob("*.wasm")):
                raise RuntimeError("Web export has no WebAssembly runtime")
            (export / "build.json").write_text(json.dumps({"commit": args.sha, "version": version}, indent=2) + "\n", encoding="utf-8")
        destination = output_root / args.platform
        destination.mkdir(parents=True, exist_ok=True)
        artifact = destination / ("MotherloadRecoded-" + version + "-" + args.platform + (".apk" if target == "android" else ".zip"))
        if target == "android":
            shutil.copy2(export / filename, artifact)
        else:
            package_zip(export, artifact)
        metadata = {"schema": 1, "commit": args.sha, "version": version, "platform": args.platform,
                    "artifacts": [{"path": artifact.relative_to(ROOT).as_posix(), "sha256": sha256(artifact), "size": artifact.stat().st_size}]}
        if args.validation:
            metadata["validation"] = True
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print("Built " + artifact.relative_to(ROOT).as_posix())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platform", required=True, choices=TARGETS)
    parser.add_argument("--sha", required=True, help="Full 40-character checked-out commit SHA")
    parser.add_argument("--run-number", required=True, type=int, help="Monotonic CI run number; Android versionCode is 1000 + N")
    parser.add_argument("--jobs", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    parser.add_argument("--godot", help="Existing official 4.7.2 executable (API hash remains enforced)")
    parser.add_argument("--validation", action="store_true", help="PR-only build, ephemeral Android signer, dist/validation/ output")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("--sha must be a full lowercase commit SHA")
    if args.jobs < 1 or not 1 <= args.run_number <= 2_099_999_000:
        parser.error("--jobs must be positive and --run-number must keep Android versionCode <= 2100000000")
    try:
        build(args)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        message = str(error)
        for secret in SECRETS:
            message = message.replace(secret, "[REDACTED]")
        parser.exit(1, "Build failed: " + message + "\n")


if __name__ == "__main__":
    main()
