#!/usr/bin/env python3
"""Publish a durable announcement receipt only after verified Drive and Web success."""
import argparse
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import subprocess
import tempfile

from deploy_web import (ReleaseState, find_release, gh, release_state,
                        require_trusted_default_branch)
from manifest import aggregate, ROOT, PLATFORMS
from version_policy import PUBLIC_TAG, validate_remote_version, version_tuple
from remote_web_release import ResultStatus, result_status

REPOSITORY = 'leakyfontana/orebit-beyond-the-lode'
SITE = 'https://play.arcmonkeyswelding.com/'
NAMES = {'android-arm64': 'Android ARM64', 'windows-x86_64': 'Windows x86-64', 'macos-arm64': 'macOS ARM64', 'web': 'Web/PWA'}


class PublicationState(Enum):
    ABSENT = 'absent'
    DRAFT = 'draft'
    RECEIPT_STAGED = 'receipt-staged'
    PUBLIC_UNVERIFIED = 'public-unverified'
    PUBLIC_VERIFIED = 'public-verified'
    CANDIDATE_HIDDEN = 'candidate-hidden'


class Publication:
    def __init__(self, tag, commit, version, release):
        self.tag = tag
        self.commit = commit
        self.version = version
        self.release = release
        self.state = {ReleaseState.ABSENT: PublicationState.ABSENT,
                      ReleaseState.DRAFT: PublicationState.DRAFT,
                      ReleaseState.PUBLIC: PublicationState.PUBLIC_UNVERIFIED}[release_state(release)]

    def verify_existing(self, platforms):
        require(self.state is PublicationState.PUBLIC_UNVERIFIED, 'Publication is not public')
        prior = self.release
        require(prior['target_commitish'] == self.commit and prior['prerelease'] is False and prior['name'] == 'Orebit ' + self.version, 'Existing public release identity differs')
        with tempfile.TemporaryDirectory(prefix='orebit-receipt-') as temporary:
            subprocess.run(['gh', 'release', 'download', self.tag, '--repo', REPOSITORY, '--pattern', 'publication.json', '--dir', temporary], check=True)
            existing = json.loads((Path(temporary) / 'publication.json').read_text())
        require(existing.get('schema') == 1 and existing.get('kind') == 'orebit.publication' and existing.get('release_id') == self.commit and existing.get('commit') == self.commit and existing.get('version') == self.version and existing.get('platforms') == platforms, 'Existing immutable publication receipt differs')
        self.state = PublicationState.PUBLIC_VERIFIED
        return existing

    def prepare_draft(self, notes):
        if self.state is PublicationState.ABSENT:
            subprocess.run(['gh', 'release', 'create', self.tag, '--repo', REPOSITORY, '--target', self.commit, '--title', 'Orebit ' + self.version, '--notes-file', str(notes), '--prerelease=false', '--draft'], check=True)
            self.state = PublicationState.DRAFT
        else:
            require(self.state is PublicationState.DRAFT, 'Public publication is immutable')
            require(self.release['target_commitish'] == self.commit, 'Draft release target differs')

    def stage_receipt(self, output):
        require(self.state is PublicationState.DRAFT, 'Publication requires a draft')
        subprocess.run(['gh', 'release', 'upload', self.tag, '--repo', REPOSITORY, str(output), '--clobber'], check=True)
        self.state = PublicationState.RECEIPT_STAGED

    def publish(self, notes):
        require(self.state is PublicationState.RECEIPT_STAGED, 'Publication requires a staged receipt')
        subprocess.run(['gh', 'release', 'edit', self.tag, '--repo', REPOSITORY, '--title', 'Orebit ' + self.version, '--notes-file', str(notes), '--prerelease=false', '--draft=false'], check=True)
        self.state = PublicationState.PUBLIC_VERIFIED

    def hide_transport(self):
        require(self.state is PublicationState.PUBLIC_VERIFIED, 'Candidate must remain public until receipt succeeds')
        hide_candidate(self.commit)
        self.state = PublicationState.CANDIDATE_HIDDEN


def command(*arguments):
    return subprocess.check_output(arguments, cwd=ROOT, text=True).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def release_notes(commit, version):
    releases = []
    for page in range(1, 101):
        batch = json.loads(command('gh', 'api', f'repos/{REPOSITORY}/releases?per_page=100&page={page}'))
        releases.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('Public release inventory exceeds safe lookup limit')
    current = version_tuple(version)
    previous = [r for r in releases if not r['draft'] and not r['prerelease']
                and PUBLIC_TAG.fullmatch(r['tag_name'])
                and tuple(map(int, PUBLIC_TAG.fullmatch(r['tag_name']).groups())) < current]
    previous = max(previous, key=lambda r: tuple(map(int, PUBLIC_TAG.fullmatch(r['tag_name']).groups())), default=None)
    revision = previous['tag_name'] + '..' + commit if previous else commit
    recorded = command('git', 'log', '--reverse', '--format=%H%x09%s', revision, '--', 'godot', 'automation/release', '.github', '.gitignore')
    commits = []
    for line in recorded.splitlines():
        sha, subject = line.split('\t', 1)
        commits.append({'commit': sha, 'subject': subject})
    markdown = '\n'.join('- ' + item['subject'] + ' (`' + item['commit'][:12] + '`)' for item in commits)
    if not markdown:
        markdown = 'No additional recorded source changes since the previous successful publication.'
    return {'markdown': markdown, 'commits': commits}


def hide_candidate(commit):
    """Retain transport assets privately only after the public receipt succeeds."""
    candidate = find_release('candidate-' + commit)
    if release_state(candidate) is not ReleaseState.ABSENT:
        require(candidate['target_commitish'] == commit and candidate['prerelease'] is True, 'Candidate identity differs')
        if release_state(candidate) is ReleaseState.PUBLIC:
            gh('api', '--method', 'PATCH', f'repos/{REPOSITORY}/releases/{candidate["id"]}', '-F', 'draft=true')


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
    tag = validate_remote_version(version, commit, allow_existing=True)
    drive, deployment, smoke = [json.loads(path.read_text()) for path in (args.drive, args.deployment, args.web_smoke)]
    require(drive.get('schema') == 1 and drive.get('commit') == commit and drive.get('version') == version, 'Drive publication identity differs')
    require(result_status(deployment) in {ResultStatus.DEPLOYED, ResultStatus.VERIFIED_EXISTING} and deployment.get('commit') == commit and deployment.get('version') == version and deployment.get('site', '').rstrip('/') == SITE.rstrip('/') and deployment.get('public_checks'), 'Web deployment was not verified')
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
    publication = Publication(tag, commit, version, find_release(tag))
    if publication.state is PublicationState.PUBLIC_UNVERIFIED:
        existing = publication.verify_existing(platforms)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(existing, indent=2) + '\n')
        publication.hide_transport()
        print(json.dumps({'status': 'verified-existing', 'release': f'https://github.com/{REPOSITORY}/releases/tag/{tag}', 'receipt': f'https://github.com/{REPOSITORY}/releases/download/{tag}/publication.json'}))
        return
    receipt = {'schema': 1, 'kind': 'orebit.publication', 'repository': REPOSITORY, 'release_id': commit, 'version': version, 'commit': commit, 'published_at': datetime.now(timezone.utc).isoformat(), 'platforms': platforms, 'web': {'url': SITE, 'commit': commit, 'verified': True}, 'notes': release_notes(commit, version)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    notes = args.output.with_name('release-notes.md')
    notes.write_text(receipt['notes']['markdown'] + '\n\nWeb: ' + SITE + '\n\nAll four downloads and their integrity evidence are in publication.json. These builds are not original-game parity acceptance. macOS is ad-hoc signed, not notarized.\n')
    publication.prepare_draft(notes)
    publication.stage_receipt(args.output)
    publication.publish(notes)
    publication.hide_transport()
    print(json.dumps({'status': 'published', 'release': f'https://github.com/{REPOSITORY}/releases/tag/{tag}', 'receipt': f'https://github.com/{REPOSITORY}/releases/download/{tag}/publication.json'}))


if __name__ == '__main__':
    main()
