#!/usr/bin/env python3
"""Publish a validated four-platform beta to the existing Google Drive archive.

Usage: python3 automation/release/publish_drive.py [--manifest dist/release.json]
Use --validate-only for local validation and read-only remote preflight. The
configured remote needs an existing writable Drive authorization and archive
writer access; this command never configures OAuth or prints credentials.
Publication adds an anyone-reader link to the archive root; new children must
inherit that permission. Existing versions, files, and IDs are never replaced.
Serialize publishers for this archive in CI: Drive has no atomic name lock.
"""

import argparse
import configparser
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT_ID = "1O6fBmcNqgVkVYUic88DOX3GTG94vB366"
PLATFORMS = {
    "macos-arm64": "macOS - Apple Silicon - ZIP",
    "windows-x86_64": "Windows - x86_64 - ZIP",
    "android-arm64": "Android - ARM64 - APK",
    "web": "Web - Browser - ZIP",
}
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK_SIZE = 1024 * 1024


class PublicationError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise PublicationError(message)


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def load_json(path):
    require(path.stat().st_size <= CHUNK_SIZE, "Metadata exceeds 1 MiB: " + str(path))
    with path.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=no_duplicate_keys)


def confined_path(value, parent, must_exist=True):
    require(isinstance(value, str) and value, "Expected a repository-relative path")
    posix = PurePosixPath(value)
    require(not posix.is_absolute() and "\\" not in value and
            all(part not in ("", ".", "..") for part in value.split("/")),
            "Unsafe repository-relative path: " + value)
    path = (ROOT / value).resolve(strict=must_exist)
    require(path.is_relative_to(parent.resolve()) and path != parent.resolve(),
            "Path escapes allowed directory: " + value)
    return path


def cli_path(value, must_exist=True):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve(strict=must_exist)
    require(path.is_relative_to((ROOT / "dist").resolve()), "Path must be inside repository dist/: " + str(path))
    return path


def digest_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


@dataclass(frozen=True)
class Upload:
    path: Path
    name: str
    sha256: str
    size: int


def upload_for(path, name=None):
    require(path.is_file(), "Not a regular file: " + str(path))
    sha256, size = digest_file(path)
    return Upload(path, name or path.name, sha256, size)


def validate_manifest(path):
    manifest = load_json(path)
    require(isinstance(manifest, dict) and type(manifest.get("schema")) is int and
            manifest["schema"] == 1, "Unsupported release manifest schema")
    commit = manifest.get("commit")
    version = manifest.get("version")
    require(isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit),
            "Manifest commit must be a full lowercase 40-character Git SHA")
    require(isinstance(version, str) and re.fullmatch(
        r"[0-9]+\.[0-9]+(?:\.[0-9]+)?-beta(?:[.-][0-9A-Za-z]+)*\+[0-9a-f]{12}", version)
        and version.endswith("+" + commit[:12]), "Invalid beta version or commit suffix")
    platforms = manifest.get("platforms")
    require(isinstance(platforms, list) and len(platforms) == len(PLATFORMS),
            "Release must contain exactly the four supported platforms")
    uploads = {}
    seen_paths = set()
    for metadata in platforms:
        require(isinstance(metadata, dict), "Platform metadata must be an object")
        platform = metadata.get("platform")
        require(isinstance(platform, str) and platform in PLATFORMS and platform not in uploads,
                "Unknown or duplicate release platform")
        require(type(metadata.get("schema")) is int and metadata["schema"] == 1 and
                metadata.get("commit") == commit and metadata.get("version") == version,
                "Platform provenance disagrees with release manifest: " + platform)
        metadata_path = confined_path("dist/metadata/" + platform + ".json", ROOT / "dist/metadata")
        require(load_json(metadata_path) == metadata,
                "Platform metadata file disagrees with release manifest: " + platform)
        artifacts = metadata.get("artifacts")
        require(isinstance(artifacts, list) and artifacts, "Platform has no artifacts: " + platform)
        files = []
        names = {"metadata.json"}
        for artifact in artifacts:
            require(isinstance(artifact, dict), "Artifact must be an object")
            artifact_path = confined_path(artifact.get("path"), ROOT / "dist" / platform)
            require(artifact_path not in seen_paths, "Duplicate artifact path")
            seen_paths.add(artifact_path)
            require(artifact_path.name not in names and
                    re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+ -]*", artifact_path.name),
                    "Unsafe or duplicate artifact basename: " + artifact_path.name)
            names.add(artifact_path.name)
            require(isinstance(artifact.get("sha256"), str) and
                    re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]), "Invalid artifact SHA256")
            require(type(artifact.get("size")) is int and artifact["size"] > 0,
                    "Invalid artifact size")
            file = upload_for(artifact_path)
            require(file.sha256 == artifact["sha256"] and file.size == artifact["size"],
                    "Artifact bytes disagree with manifest: " + artifact["path"])
            files.append(file)
        files.append(upload_for(metadata_path, "metadata.json"))
        uploads[platform] = files
    return manifest, uploads, upload_for(path, "release.json")


class Drive:
    def __init__(self, remote, root_id):
        require(re.fullmatch(r"[A-Za-z0-9_-]+", remote), "Remote must be a configured rclone name, without a colon")
        require(re.fullmatch(r"[A-Za-z0-9_-]+", root_id), "Invalid Drive root ID")
        self.remote = remote
        self.root_id = root_id

    def command(self, command, *arguments, folder=None):
        return ["rclone", command, *arguments, "--drive-root-folder-id", folder or self.root_id,
                "--drive-shared-with-me=false", "--drive-auth-owner-only=false",
                "--drive-skip-shortcuts=false", "--drive-skip-gdocs=false",
                "--log-level", "ERROR", "--stats", "0", "--retries", "1"]

    def run(self, command, *arguments, folder=None):
        result = subprocess.run(self.command(command, *arguments, folder=folder),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        require(result.returncode == 0,
                "rclone " + command + " failed (exit " + str(result.returncode) +
                "); check existing remote authorization and archive permissions")
        return result.stdout.decode("utf-8")

    def children(self, folder):
        result = json.loads(self.run("backend", "query", self.remote + ":",
                                     "'" + folder + "' in parents and trashed = false")) or []
        require(isinstance(result, list), "Invalid rclone Drive query response")
        names = set()
        for item in result:
            require(isinstance(item, dict) and item.get("name") and item.get("id"),
                    "Incomplete Drive object listing")
            require(item["name"] not in names,
                    "Duplicate Drive name; refusing ambiguous folder/file: " + item["name"])
            names.add(item["name"])
        return {item["name"]: item for item in result}

    def preflight(self):
        # Redacted config is intentionally the only config inspection. Never
        # request config show/dump or extract/reuse OAuth tokens ourselves.
        result = subprocess.run(["rclone", "config", "redacted", self.remote],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True)
        require(result.returncode == 0, "Cannot inspect the configured rclone remote safely")
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(result.stdout)
        require(self.remote in config and config[self.remote].get("type") == "drive",
                "Configured remote must use the Google Drive backend")
        scope = config[self.remote].get("scope", "drive").strip() or "drive"
        require(any(value.strip().removeprefix("https://www.googleapis.com/auth/") in
                    ("drive", "drive.file") for value in scope.split(",")),
                "Configured remote OAuth scope is read-only; publication requires an existing writable authorization")
        # Listing a public folder alone proves no writer capability. Require the
        # exact root ID to be searchable as writable by the authenticated account.
        writable = json.loads(self.run("backend", "query", self.remote + ":",
                                       "trashed = false and mimeType = '" + FOLDER_MIME +
                                       "' and 'me' in writers")) or []
        require(any(item.get("id") == self.root_id for item in writable),
                "Archive root is not writable by the configured account; refusing publication")
        return self.children(self.root_id)

    @staticmethod
    def check_kind(item, directory):
        require((item.get("mimeType") == FOLDER_MIME) if directory else
                not item.get("mimeType", "").startswith("application/vnd.google-apps."),
                "Unexpected Drive object type: " + item["name"])

    def verify_bytes(self, folder, item, upload):
        self.check_kind(item, False)
        require(int(item.get("size", -1)) == upload.size,
                "Immutable remote file size differs: " + upload.name)
        digest = hashlib.sha256()
        size = 0
        # Stream the full download; never retain an artifact in memory. A
        # temporary stderr file also prevents a blocked diagnostic pipe.
        with tempfile.TemporaryFile() as errors:
            with subprocess.Popen(self.command("cat", self.remote + ":" + upload.name, folder=folder),
                                  stdout=subprocess.PIPE, stderr=errors) as process:
                for chunk in iter(lambda: process.stdout.read(CHUNK_SIZE), b""):
                    size += len(chunk)
                    digest.update(chunk)
                status = process.wait()
        require(status == 0, "Drive roundtrip download failed: " + upload.name)
        require(size == upload.size and digest.hexdigest() == upload.sha256,
                "Immutable remote file SHA256 differs: " + upload.name)

    def verify_public(self, folder, expected, upload=None):
        entries = json.loads(self.run("lsjson", self.remote + ":", "--max-depth", "1", "--metadata",
                                      "--drive-metadata-permissions", "read", folder=folder))
        by_id = {item.get("ID"): item for item in entries}
        for item in expected:
            metadata = by_id.get(item["id"], {}).get("Metadata", {})
            permissions = json.loads(metadata.get("permissions", "[]"))
            require(not any(permission.get("type") == "anyone" and permission.get("role") != "reader"
                            for permission in permissions), "Unexpected public write permission: " + item["name"])
            require(metadata.get("copy-requires-writer-permission") != "true",
                    "Public downloads are restricted: " + item["name"])
            if upload is not None and not any(
                    permission.get("type") == "anyone" and permission.get("role") == "reader"
                    and not permission.get("expirationTime") for permission in permissions):
                # Shared Drive inherited ACLs may be omitted by rclone. Prove
                # actual public readability instead, without OAuth or cookies.
                digest = hashlib.sha256()
                size = 0
                url = ("https://drive.usercontent.google.com/download?id=" + item["id"] +
                       "&export=download&confirm=t")
                with urllib.request.urlopen(url, timeout=120) as response:
                    for chunk in iter(lambda: response.read(CHUNK_SIZE), b""):
                        size += len(chunk)
                        digest.update(chunk)
                require(size == upload.size and digest.hexdigest() == upload.sha256,
                        "Anonymous Drive SHA256 verification failed: " + upload.name)

    def folder(self, parent, name):
        children = self.children(parent)
        if name not in children:
            self.run("mkdir", self.remote + ":" + name, folder=parent)
            children = self.children(parent)
        require(name in children, "Created folder missing from Drive listing: " + name)
        self.check_kind(children[name], True)
        return children[name]

    def publish_file(self, folder, upload):
        children = self.children(folder)
        if upload.name not in children:
            require(digest_file(upload.path) == (upload.sha256, upload.size),
                    "Local file changed since validation: " + str(upload.path))
            # Never update an existing ID, even if another publisher races us.
            # Check again afterwards: Drive permits duplicate names and rclone
            # cannot provide an atomic create-if-absent operation.
            self.run("copyto", str(upload.path), self.remote + ":" + upload.name,
                     "--ignore-existing", "--immutable", "--checksum", folder=folder)
            children = self.children(folder)
        require(upload.name in children, "Uploaded file missing from Drive: " + upload.name)
        item = children[upload.name]
        self.verify_bytes(folder, item, upload)
        self.verify_public(folder, [item], upload)
        return {"id": item["id"], "name": upload.name, "path": str(upload.path.relative_to(ROOT)),
                "url": item.get("webViewLink") or "https://drive.google.com/file/d/" + item["id"] + "/view",
                "sha256": upload.sha256, "size": upload.size, "verification": "download-sha256"}


def preflight_version(drive, root_children, version, uploads, release):
    if version not in root_children:
        return
    version_item = root_children[version]
    drive.check_kind(version_item, True)
    children = drive.children(version_item["id"])
    require(set(children) <= set(PLATFORMS.values()) | {"release.json"},
            "Unexpected content in immutable version folder")
    if "release.json" in children:
        drive.verify_bytes(version_item["id"], children["release.json"], release)
    for platform, files in uploads.items():
        folder = children.get(PLATFORMS[platform])
        if folder is None:
            continue
        drive.check_kind(folder, True)
        existing = drive.children(folder["id"])
        require(set(existing) <= {file.name for file in files},
                "Unexpected content in immutable platform folder: " + platform)
        for file in files:
            if file.name in existing:
                drive.verify_bytes(folder["id"], existing[file.name], file)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="dist/release.json")
    parser.add_argument("--remote", default="orebit-gdrive")
    parser.add_argument("--root-id", default=DEFAULT_ROOT_ID)
    parser.add_argument("--output", default="dist/drive-publication.json")
    parser.add_argument("--validate-only", action="store_true", help="Validate inputs and remote access without any remote mutation")
    args = parser.parse_args()
    try:
        manifest_path = cli_path(args.manifest)
        output_path = cli_path(args.output, must_exist=False)
        manifest, uploads, release = validate_manifest(manifest_path)
        input_paths = {release.path} | {file.path for files in uploads.values() for file in files}
        require(output_path not in input_paths, "Publication output must not overwrite a release input")
        drive = Drive(args.remote, args.root_id)
        root_children = drive.preflight()
        preflight_version(drive, root_children, manifest["version"], uploads, release)
        if args.validate_only:
            print(json.dumps({"validated": True, "remote": args.remote, "root_id": args.root_id,
                              "commit": manifest["commit"], "version": manifest["version"], "mutated": False}))
            return 0
        # This is the first remote mutation, after ALL local bytes and existing
        # immutable content have passed validation. Descendants inherit reader.
        root_url = drive.run("link", args.remote + ":").strip()
        require(root_url.startswith("https://drive.google.com/"), "Unexpected archive share URL")
        version = drive.folder(args.root_id, manifest["version"])
        drive.verify_public(args.root_id, [version])
        result = {"schema": 1, "commit": manifest["commit"], "version": manifest["version"],
                  "remote": args.remote, "root": {"id": args.root_id, "url": root_url},
                  "folder": {"id": version["id"], "url": "https://drive.google.com/drive/folders/" + version["id"]},
                  "platforms": []}
        for platform in PLATFORMS:
            folder = drive.folder(version["id"], PLATFORMS[platform])
            drive.verify_public(version["id"], [folder])
            files = [drive.publish_file(folder["id"], file) for file in uploads[platform]]
            result["platforms"].append({"platform": platform, "folder": {"id": folder["id"],
                                        "url": "https://drive.google.com/drive/folders/" + folder["id"]},
                                        "files": files})
        # The aggregate is the completion marker and is published last.
        result["manifest"] = drive.publish_file(version["id"], release)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_path.parent,
                                         prefix=".drive-publication-", delete=False) as output:
            temporary_path = Path(output.name)
            try:
                json.dump(result, output, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
                os.replace(temporary_path, output_path)
            finally:
                temporary_path.unlink(missing_ok=True)
        print(json.dumps({"published": True, "output": str(output_path.relative_to(ROOT)),
                          "commit": manifest["commit"], "version": manifest["version"]}))
        return 0
    except (PublicationError, OSError, ValueError, configparser.Error) as error:
        print("Drive publication failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
