#!/usr/bin/env python3
"""Require unique, numerically increasing plain 0.x.y public release versions.

The CLI reads fresh origin tags, not a checkout's possibly stale local tags.
Commit provenance is separate from the public version; only an explicit retry
may reuse a version whose canonical tag resolves to the exact same commit.
"""
import argparse
import configparser
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
VERSION = re.compile(r'0\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
PUBLIC_TAG = re.compile(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')


def version_tuple(version):
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError('Public version must be plain 0.x.y without leading zeros, prerelease labels or build metadata')
    return tuple(map(int, version.split('.')))


def valid_identity(commit, version):
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected full lowercase commit SHA')
    version_tuple(version)


def source_version():
    presets = configparser.ConfigParser(interpolation=None)
    presets.read(ROOT / 'godot/export_presets.cfg', encoding='utf-8')
    version = json.loads(presets['preset.1.options']['version/name'])
    version_tuple(version)
    if json.loads(presets['preset.3.options']['application/short_version']) != version:
        raise ValueError('Android and macOS source release versions differ')
    return version


def public_tags(output):
    """Resolve annotated tags to their peeled commit, independent of line order."""
    tags, peeled = {}, {}
    for line in output.splitlines():
        commit, ref = line.split()
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError('Invalid origin tag object identity')
        if not ref.startswith('refs/tags/'):
            continue
        tag = ref.removeprefix('refs/tags/')
        annotated = tag.endswith('^{}')
        if annotated:
            tag = tag[:-3]
        if PUBLIC_TAG.fullmatch(tag):
            (peeled if annotated else tags)[tag] = commit
    tags.update(peeled)
    return tags


def validate_version(version, commit, tags, allow_existing=False):
    current = version_tuple(version)
    valid_identity(commit, version)
    tag = 'v' + version
    if tag in tags and not (allow_existing and tags[tag] == commit):
        raise ValueError('Public version already exists: ' + tag)
    for existing in tags:
        match = PUBLIC_TAG.fullmatch(existing)
        if match and tuple(map(int, match.groups())) >= current and existing != tag:
            raise ValueError('Public version must be greater than every existing public version: ' + existing)
    return tag


def validate_remote_version(version, commit, allow_existing=False):
    # ls-remote sees new/deleted/retargeted tags even in shallow CI checkouts.
    output = subprocess.check_output(['git', 'ls-remote', '--tags', 'origin'], cwd=ROOT, text=True)
    return validate_version(version, commit, public_tags(output), allow_existing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', help='Public version; defaults to checked-out export presets')
    parser.add_argument('--sha', required=True, help='Full source commit SHA')
    parser.add_argument('--allow-existing', action='store_true', help='Allow an exact same-version, same-commit publication retry')
    args = parser.parse_args()
    try:
        version = source_version() if args.version is None else args.version
        valid_identity(args.sha, version)
        tag = validate_remote_version(version, args.sha, args.allow_existing)
    except (OSError, ValueError, KeyError, configparser.Error, subprocess.SubprocessError) as error:
        parser.exit(1, 'Release version rejected: ' + str(error) + '\n')
    print(json.dumps({'version': version, 'commit': args.sha, 'tag': tag, 'validated': True}))


if __name__ == '__main__':
    main()
