#!/usr/bin/env python3
"""Aggregate and integrity-check all four platform artifacts before publication."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = ('android-arm64', 'macos-arm64', 'web', 'windows-x86_64')


def sha256(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def aggregate(commit):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected a full lowercase commit SHA')
    metadata = []
    version = None
    for platform in PLATFORMS:
        item = json.loads((ROOT / 'dist' / 'metadata' / (platform + '.json')).read_text())
        if item.get('schema') != 1 or item.get('platform') != platform or item.get('commit') != commit:
            raise ValueError('Platform identity mismatch: ' + platform)
        candidate = item.get('version', '')
        if not isinstance(candidate, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]*', candidate) or not candidate.endswith('+' + commit[:12]):
            raise ValueError('Invalid version/SHA identity: ' + platform)
        if version is not None and candidate != version:
            raise ValueError('Platform versions differ')
        version = candidate
        artifacts = item.get('artifacts')
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError('Missing platform artifacts: ' + platform)
        names = set()
        directory = (ROOT / 'dist' / platform).resolve()
        for artifact in artifacts:
            name = artifact.get('path')
            if not isinstance(name, str):
                raise ValueError('Invalid artifact path')
            path = ROOT / name
            if name in names or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory):
                raise ValueError('Artifact outside its platform directory or duplicated: ' + name)
            names.add(name)
            if type(artifact.get('size')) is not int or path.stat().st_size != artifact['size'] or sha256(path) != artifact.get('sha256'):
                raise ValueError('Artifact integrity mismatch: ' + name)
        metadata.append(item)
    return {'schema': 1, 'commit': commit, 'version': version, 'platforms': metadata}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / 'release.json')
    args = parser.parse_args()
    release = aggregate(args.sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(release, indent=2) + '\n')
    print(json.dumps({'manifest': str(args.output), 'commit': release['commit'], 'version': release['version'], 'platforms': list(PLATFORMS)}))


if __name__ == '__main__':
    main()
