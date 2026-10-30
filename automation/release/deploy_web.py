#!/usr/bin/env python3
"""Publish an immutable Web candidate for the outbound-only game deployment service.

No CI-to-VPS SSH, inbound deployment endpoint, or server credential is used.
Candidates are not successful beta receipts. The service validates the trusted
push run and exact ZIP before invoking the scoped atomic deployment helper.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from remote_web_release import MAX_ARCHIVE, digest, inspect_archive, public_verify, require, valid_identity

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'leakyfontana/orebit-beyond-the-lode'
SITE = 'https://play.arcmonkeyswelding.com'
STATUS_PATH = '/__orebit_deployment__/'
USER_AGENT = 'OrebitReleaseVerifier/1.0'


def repository_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_web_manifest(path):
    manifest = json.loads(path.read_text())
    require(manifest.get('schema') == 1, 'Unsupported aggregate release manifest')
    commit, version = manifest.get('commit'), manifest.get('version')
    valid_identity(commit, version)
    platforms = manifest.get('platforms')
    require(isinstance(platforms, list), 'Aggregate platforms must be metadata objects')
    web = [item for item in platforms if isinstance(item, dict) and item.get('platform') == 'web']
    require(len(web) == 1, 'Aggregate must contain exactly one Web platform')
    metadata = web[0]
    require(metadata.get('schema') == 1 and metadata.get('commit') == commit and metadata.get('version') == version, 'Web metadata identity mismatch')
    artifacts = metadata.get('artifacts')
    require(isinstance(artifacts, list) and len(artifacts) == 1, 'Expected one runnable Web ZIP')
    artifact = artifacts[0]
    name = artifact.get('path')
    require(isinstance(name, str), 'Missing Web artifact path')
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and str(relative) == name and '..' not in relative.parts and relative.parts[:2] == ('dist', 'web') and relative.suffix == '.zip', 'Web artifact must be a confined dist/web ZIP')
    archive = ROOT / name
    require(archive.is_file() and not archive.is_symlink() and archive.resolve().is_relative_to((ROOT / 'dist/web').resolve()), 'Web artifact escapes its directory')
    require(type(artifact.get('size')) is int and 0 < artifact['size'] <= MAX_ARCHIVE and isinstance(artifact.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', artifact['sha256']), 'Invalid Web artifact integrity metadata')
    require(archive.stat().st_size == artifact['size'] and digest(archive) == artifact['sha256'], 'Local Web ZIP integrity mismatch')
    files = inspect_archive(archive, commit, version)
    return archive, {'commit': commit, 'version': version, 'artifact': artifact, 'files': files}


def git(*arguments):
    return subprocess.check_output(['git', '-C', str(ROOT), *arguments], text=True, stderr=subprocess.PIPE).strip()


def require_trusted_default_branch(commit):
    require(git('rev-parse', 'HEAD') == commit, 'Release commit differs from checked-out trusted source')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        require(os.environ.get('GITHUB_EVENT_NAME') == 'push', 'Only default-branch push events may publish')
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        repository = event.get('repository', {})
        branch = repository.get('default_branch')
        require(isinstance(branch, str) and branch and repository.get('full_name') == REPOSITORY and os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and os.environ.get('GITHUB_REF') == 'refs/heads/' + branch and event.get('ref') == 'refs/heads/' + branch and event.get('after') == commit and os.environ.get('GITHUB_SHA') == commit, 'Publication requires the exact default-branch push SHA')
    else:
        default = git('symbolic-ref', 'refs/remotes/origin/HEAD')
        require(default.startswith('refs/remotes/origin/') and git('symbolic-ref', '--short', 'HEAD') == default.removeprefix('refs/remotes/origin/') and git('rev-parse', default) == commit, 'Local publication requires the fetched origin default branch')


def gh(*arguments, allow_missing=False):
    process = subprocess.run(['gh', *arguments], cwd=ROOT, text=True, capture_output=True)
    if process.returncode:
        if allow_missing and 'HTTP 404' in process.stderr:
            return None
        raise RuntimeError('GitHub publication command failed: ' + process.stderr.strip())
    return process.stdout.strip()


def fetch_json(url, missing_ok=False):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Cache-Control': 'no-cache'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(1024 * 1024 + 1)
            require(len(body) <= 1024 * 1024, 'Oversized deployment metadata')
            return json.loads(body)
    except urllib.error.HTTPError as error:
        if missing_ok and error.code == 404:
            return None
        raise


def asset_url(tag, name):
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]*', name), 'Invalid candidate asset basename')
    return f'https://github.com/{REPOSITORY}/releases/download/{tag}/' + urllib.parse.quote(name, safe='')


def validate_asset(release, path):
    assets = [item for item in release.get('assets', []) if item['name'] == path.name]
    require(len(assets) == 1, 'Candidate asset missing or duplicated: ' + path.name)
    asset = assets[0]
    expected = digest(path)
    require(asset['size'] == path.stat().st_size, 'Immutable candidate asset size differs')
    if asset.get('digest'):
        require(asset['digest'] == 'sha256:' + expected, 'Immutable candidate asset digest differs')
    else:
        if release['draft']:
            with tempfile.NamedTemporaryFile(prefix='orebit-draft-asset-') as downloaded:
                subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/releases/assets/{asset["id"]}', '-H', 'Accept: application/octet-stream'], cwd=ROOT, stdout=downloaded, stderr=subprocess.PIPE, check=True)
                downloaded.flush()
                require(Path(downloaded.name).stat().st_size == path.stat().st_size and digest(Path(downloaded.name)) == expected, 'Immutable draft asset bytes differ')
            return
        request = urllib.request.Request(asset_url(release['tag_name'], path.name), headers={'User-Agent': USER_AGENT})
        actual = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(request, timeout=120) as response:
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                size += len(chunk)
                require(size <= path.stat().st_size, 'Candidate asset exceeds expected size')
                actual.update(chunk)
        require(size == path.stat().st_size and actual.hexdigest() == expected, 'Immutable candidate asset bytes differ')


def find_release(tag):
    published = gh('api', f'repos/{REPOSITORY}/releases/tags/{tag}', allow_missing=True)
    if published is not None:
        return json.loads(published)
    # GitHub's tag endpoint does not resolve unpublished drafts. Authenticated
    # release listing does; use the immutable numeric ID for later draft reads.
    for page in range(1, 101):
        releases = json.loads(gh('api', f'repos/{REPOSITORY}/releases?per_page=100&page={page}'))
        matches = [release for release in releases if release['tag_name'] == tag]
        require(len(matches) <= 1, 'Ambiguous draft candidate tag')
        if matches:
            return matches[0]
        if len(releases) < 100:
            return None
    raise ValueError('Release inventory exceeds safe candidate lookup limit')


def publish_candidate(archive, header, run_id):
    commit, version = header['commit'], header['version']
    latest = git('ls-remote', 'origin', 'refs/heads/main').split()
    require(latest and latest[0] == commit, 'Newer main commit exists; refusing stale deployment candidate')
    tag = 'candidate-' + commit
    request = {'schema': 1, 'kind': 'orebit.web.deployment-request', 'repository': REPOSITORY, 'commit': commit, 'version': version, 'run_id': run_id, 'site': SITE, 'artifact': {'name': archive.name, 'url': asset_url(tag, archive.name), 'sha256': header['artifact']['sha256'], 'size': header['artifact']['size']}, 'files': header['files']}
    request_path = ROOT / 'dist/deployment-request.json'
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + '\n')
    release = find_release(tag)
    if release is None:
        release = json.loads(gh('api', '--method', 'POST', f'repos/{REPOSITORY}/releases', '-f', 'tag_name=' + tag, '-f', 'target_commitish=' + commit, '-f', 'name=Orebit deployment candidate ' + version, '-f', 'body=Pending Web deployment verification; not a successful beta publication or announcement receipt.', '-F', 'prerelease=true', '-F', 'draft=true'))
    require(release['target_commitish'] == commit and release.get('prerelease'), 'Candidate release identity differs')
    for path in (archive, request_path):
        if any(item['name'] == path.name for item in release.get('assets', [])):
            validate_asset(release, path)
        else:
            require(release['draft'], 'Published candidate is immutable; refusing to repair missing assets')
            gh('release', 'upload', tag, '--repo', REPOSITORY, str(path))
            release = json.loads(gh('api', f'repos/{REPOSITORY}/releases/{release["id"]}'))
    if release['draft']:
        gh('release', 'edit', tag, '--repo', REPOSITORY, '--draft=false')
    return request


def wait_status(header, run_id, rollback, timeout):
    name = ('rollback-' if rollback else '') + header['commit'] + '.json'
    url = SITE + STATUS_PATH + name
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fetch_json(url + '?check=' + str(time.time_ns()), missing_ok=True)
        if result is not None:
            require(result.get('schema') == 1 and result.get('commit') == header['commit'] and result.get('version') == header['version'] and result.get('run_id') == run_id and result.get('site', '').rstrip('/') == SITE, 'Deployment status identity differs')
            require(result.get('archive_sha256') == header['artifact']['sha256'], 'Deployment status artifact hash differs')
            wanted = ('rolled-back',) if rollback else ('deployed', 'verified-existing')
            require(result.get('status') in wanted and result.get('public_checks'), 'Outbound deployment failed: ' + str(result.get('error', result.get('status'))))
            return result
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    raise TimeoutError('Timed out waiting for the outbound game deployment service')


def request_rollback(header, run_id):
    tag = 'candidate-' + header['commit']
    request = {'schema': 1, 'kind': 'orebit.web.rollback-request', 'repository': REPOSITORY, 'commit': header['commit'], 'version': header['version'], 'run_id': run_id, 'artifact_sha256': header['artifact']['sha256']}
    path = ROOT / 'dist/rollback-request.json'
    path.write_text(json.dumps(request, indent=2, sort_keys=True) + '\n')
    release = json.loads(gh('api', f'repos/{REPOSITORY}/releases/tags/{tag}'))
    if any(item['name'] == path.name for item in release.get('assets', [])):
        validate_asset(release, path)
    else:
        gh('release', 'upload', tag, '--repo', REPOSITORY, str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'dist/release.json')
    parser.add_argument('--timeout', type=int, default=900)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--verify-current', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    try:
        require(1 <= args.timeout <= 1800, 'Deployment status timeout must be 1..1800 seconds')
        manifest = repository_path(args.manifest)
        if args.verify_current and not manifest.is_file():
            build = fetch_json(SITE + '/build.json')
            valid_identity(build.get('commit'), build.get('version'))
            status = fetch_json(SITE + STATUS_PATH + build['commit'] + '.json')
            require(status.get('status') in ('deployed', 'verified-existing') and status.get('commit') == build['commit'], 'No verified publication status for current Web build')
            print(json.dumps({'schema': 1, 'status': 'verified-current', 'mutated': False, 'commit': build['commit'], 'version': build['version'], 'site': SITE, 'verification': 'public-build-identity-and-deployment-status'}))
            return 0
        archive, header = load_web_manifest(manifest)
        if args.dry_run:
            print(json.dumps({'schema': 1, 'status': 'validated', 'mutated': False, 'commit': header['commit'], 'version': header['version'], 'files': len(header['files'])}))
            return 0
        if args.verify_current:
            checks = public_verify(SITE, header['files'], header['commit'], header['version'])
            print(json.dumps({'schema': 1, 'status': 'verified-current', 'mutated': False, 'commit': header['commit'], 'version': header['version'], 'site': SITE, 'public_checks': checks}))
            return 0
        require_trusted_default_branch(header['commit'])
        run_id = int(os.environ.get('GITHUB_RUN_ID', '0'))
        require(run_id > 0, 'Publication requires the real trusted push workflow run ID')
        before = fetch_json(SITE + '/build.json', missing_ok=True) if not args.rollback else None
        if args.rollback:
            request_rollback(header, run_id)
        else:
            publish_candidate(archive, header, run_id)
        result = wait_status(header, run_id, args.rollback, args.timeout)
        if before and before.get('commit') == header['commit'] and not args.rollback:
            result = {**result, 'status': 'verified-existing', 'original_deployment_mutated': result.get('mutated'), 'mutated': False}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(json.dumps({'schema': 1, 'status': 'failed', 'error': str(error), 'deployment_completion': 'not-established'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
