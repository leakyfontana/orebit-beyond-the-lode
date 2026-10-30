#!/usr/bin/env python3
"""Publish a durable announcement receipt only after verified Drive and Web success."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile

from deploy_web import require_trusted_default_branch
from manifest import aggregate, ROOT, PLATFORMS

REPOSITORY = 'leakyfontana/orebit-beyond-the-lode'
SITE = 'https://play.arcmonkeyswelding.com/'
NAMES = {'android-arm64': 'Android ARM64', 'windows-x86_64': 'Windows x86-64', 'macos-arm64': 'macOS ARM64', 'web': 'Web/PWA'}


def command(*arguments):
    return subprocess.check_output(arguments, cwd=ROOT, text=True).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def release_notes(commit):
    releases = json.loads(command('gh', 'api', f'repos/{REPOSITORY}/releases?per_page=100'))
    previous = next((r for r in releases if not r['draft'] and r['tag_name'].startswith('beta-') and r['tag_name'] != 'beta-' + commit), None)
    revision = previous['tag_name'] + '..' + commit if previous else commit
    recorded = command('git', 'log', '--reverse', '--format=%H%x09%s', revision, '--', 'godot', 'automation/release', '.github', '.gitignore')
    commits = []
    for line in recorded.splitlines():
        sha, subject = line.split('\t', 1)
        commits.append({'commit': sha, 'subject': subject})
    markdown = '\n'.join('- ' + item['subject'] + ' (`' + item['commit'][:12] + '`)' for item in commits)
    if not markdown:
        markdown = 'No additional recorded source changes since the previous successful beta publication.'
    return {'markdown': markdown, 'commits': commits}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'dist/release.json')
    parser.add_argument('--drive', type=Path, default=ROOT / 'dist/drive-publication.json')
    parser.add_argument('--deployment', type=Path, default=ROOT / 'dist/vps-deployment.json')
    parser.add_argument('--web-smoke', type=Path, default=ROOT / 'dist/public-web-smoke.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/publication.json')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    require(manifest == aggregate(manifest['commit']), 'Aggregate does not match current verified artifacts')
    commit, version = manifest['commit'], manifest['version']
    require_trusted_default_branch(commit)
    drive, deployment, smoke = [json.loads(path.read_text()) for path in (args.drive, args.deployment, args.web_smoke)]
    require(drive.get('schema') == 1 and drive.get('commit') == commit and drive.get('version') == version, 'Drive publication identity differs')
    require(deployment.get('status') in ('deployed', 'verified-existing') and deployment.get('commit') == commit and deployment.get('version') == version and deployment.get('site', '').rstrip('/') == SITE.rstrip('/') and deployment.get('public_checks'), 'Web deployment was not verified')
    require(smoke.get('menu_ready') is True and smoke.get('commit') == commit and smoke.get('url', '').rstrip('/') == SITE.rstrip('/'), 'Public browser verification did not pass')
    published = {p['platform']: p for p in drive.get('platforms', [])}
    require(set(published) == set(PLATFORMS), 'Not all four platforms were published')
    platforms = []
    for metadata in manifest['platforms']:
        platform = metadata['platform']
        result = published[platform]
        by_path = {f['path']: f for f in result['files']}
        files = []
        for artifact in metadata['artifacts']:
            uploaded = by_path.get(artifact['path'], {})
            require(uploaded.get('verification') == 'download-sha256' and all(uploaded.get(k) == artifact[k] for k in ('sha256', 'size')), 'Artifact publication lacks matching downloaded integrity evidence')
            require(uploaded.get('url', '').startswith('https://drive.google.com/'), 'Missing public Drive artifact URL')
            files.append({k: uploaded[k] for k in ('name', 'url', 'sha256', 'size')})
        folder_url = result['folder']['url']
        require(folder_url.startswith('https://drive.google.com/drive/folders/'), 'Missing public platform folder')
        platforms.append({'platform': platform, 'name': NAMES[platform], 'url': folder_url, 'artifacts': files})
    tag = 'beta-' + commit
    prior = subprocess.run(['gh', 'release', 'view', tag, '--repo', REPOSITORY, '--json', 'isDraft,assets,targetCommitish'], cwd=ROOT, capture_output=True, text=True)
    if prior.returncode == 0 and not json.loads(prior.stdout)['isDraft']:
        with tempfile.TemporaryDirectory(prefix='orebit-receipt-') as temporary:
            subprocess.run(['gh', 'release', 'download', tag, '--repo', REPOSITORY, '--pattern', 'publication.json', '--dir', temporary], check=True)
            existing = json.loads((Path(temporary) / 'publication.json').read_text())
        require(existing.get('schema') == 1 and existing.get('kind') == 'orebit.beta.publication' and existing.get('commit') == commit and existing.get('version') == version and existing.get('platforms') == platforms, 'Existing immutable publication receipt differs')
        args.output.write_text(json.dumps(existing, indent=2) + '\n')
        print(json.dumps({'status': 'verified-existing', 'release': f'https://github.com/{REPOSITORY}/releases/tag/{tag}', 'receipt': f'https://github.com/{REPOSITORY}/releases/download/{tag}/publication.json'}))
        return
    receipt = {'schema': 1, 'kind': 'orebit.beta.publication', 'repository': REPOSITORY, 'release_id': commit, 'version': version, 'commit': commit, 'published_at': datetime.now(timezone.utc).isoformat(), 'platforms': platforms, 'web': {'url': SITE, 'commit': commit, 'verified': True}, 'notes': release_notes(commit)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    notes = args.output.with_name('release-notes.md')
    notes.write_text(receipt['notes']['markdown'] + '\n\nWeb: ' + SITE + '\n\nAll four downloads and their integrity evidence are in publication.json. Beta builds are not original-game parity acceptance. macOS is ad-hoc signed, not notarized.\n')
    if prior.returncode:
        subprocess.run(['gh', 'release', 'create', tag, '--repo', REPOSITORY, '--target', commit, '--title', 'Orebit ' + version, '--notes-file', str(notes), '--prerelease', '--draft'], check=True)
    else:
        require(json.loads(prior.stdout)['targetCommitish'] == commit, 'Draft release target differs')
    subprocess.run(['gh', 'release', 'upload', tag, '--repo', REPOSITORY, str(args.output), '--clobber'], check=True)
    subprocess.run(['gh', 'release', 'edit', tag, '--repo', REPOSITORY, '--draft=false'], check=True)
    print(json.dumps({'status': 'published', 'release': f'https://github.com/{REPOSITORY}/releases/tag/{tag}', 'receipt': f'https://github.com/{REPOSITORY}/releases/download/{tag}/publication.json'}))


if __name__ == '__main__':
    main()
