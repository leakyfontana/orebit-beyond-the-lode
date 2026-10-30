#!/usr/bin/env python3
"""Deploy the exact trusted-default-branch Web ZIP, or verify the current public release.

--dry-run validates locally and never connects to the VPS. --verify-current reads
remote/public files without mutation. Deployment uses a restricted SSH key and
strict known_hosts with a fixed, root-owned server helper (never client Python).
No archive content is executed and no nginx/DNS/WordPress setting is changed.
"""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

from remote_web_release import MAX_ARCHIVE, digest, inspect_archive, require, valid_identity, validate_site

ROOT = Path(__file__).resolve().parents[2]


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
    require(metadata.get('schema') == 1 and metadata.get('commit') == commit
            and metadata.get('version') == version, 'Web metadata identity mismatch')
    artifacts = metadata.get('artifacts')
    require(isinstance(artifacts, list) and len(artifacts) == 1,
            'Web platform must identify exactly one runnable ZIP')
    artifact = artifacts[0]
    require(isinstance(artifact, dict), 'Invalid Web artifact')
    name = artifact.get('path')
    require(isinstance(name, str), 'Missing Web artifact path')
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and str(relative) == name and '..' not in relative.parts
            and relative.parts[:2] == ('dist', 'web') and relative.suffix == '.zip',
            'Web artifact must be a repository-relative dist/web/*.zip path')
    archive = ROOT / name
    require(archive.is_file() and not archive.is_symlink()
            and archive.resolve().is_relative_to((ROOT / 'dist' / 'web').resolve()),
            'Web artifact escapes distribution directory or is not a regular file')
    require(type(artifact.get('size')) is int and 0 < artifact['size'] <= MAX_ARCHIVE
            and isinstance(artifact.get('sha256'), str)
            and re.fullmatch(r'[0-9a-f]{64}', artifact['sha256']), 'Invalid Web artifact integrity metadata')
    require(archive.stat().st_size == artifact['size'] and digest(archive) == artifact['sha256'],
            'Local Web ZIP integrity mismatch')
    files = inspect_archive(archive, commit, version)
    return archive, {'commit': commit, 'version': version, 'artifact': artifact, 'files': files}


def git(*arguments):
    return subprocess.check_output(['git', '-C', str(ROOT), *arguments], text=True,
                                   stderr=subprocess.PIPE).strip()


def require_trusted_default_branch(commit):
    """PRs may validate, but may not open SSH or obtain the deployment credential."""
    require(git('rev-parse', 'HEAD') == commit, 'Release commit is not the checked-out trusted source')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        require(os.environ.get('GITHUB_EVENT_NAME') == 'push', 'Only default-branch push events may deploy')
        event_path = os.environ.get('GITHUB_EVENT_PATH')
        require(event_path, 'GitHub push event payload is required')
        event = json.loads(Path(event_path).read_text())
        repository = event.get('repository', {})
        default_branch = repository.get('default_branch')
        require(isinstance(default_branch, str) and default_branch,
                'GitHub event has no default branch')
        require(repository.get('full_name') == 'leakyfontana/orebit-beyond-the-lode'
                and os.environ.get('GITHUB_REPOSITORY') == repository['full_name']
                and os.environ.get('GITHUB_REF') == 'refs/heads/' + default_branch
                and event.get('ref') == 'refs/heads/' + default_branch
                and event.get('after') == commit and os.environ.get('GITHUB_SHA') == commit,
                'Deployment requires this repository\'s exact default-branch push SHA')
    else:
        default_ref = git('symbolic-ref', 'refs/remotes/origin/HEAD')
        require(default_ref.startswith('refs/remotes/origin/'), 'Cannot identify origin default branch')
        branch = default_ref.removeprefix('refs/remotes/origin/')
        require(git('symbolic-ref', '--short', 'HEAD') == branch
                and git('rev-parse', default_ref) == commit,
                'Local deployment requires checked-out origin default branch at its fetched SHA')


def remote_operation(host, header, archive=None):
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*', host), 'Invalid SSH host/alias')
    if header['operation'] == 'verify-current':
        command = 'verify'
    elif header['operation'] == 'rollback':
        command = 'rollback ' + header['commit']
    else:
        command = 'deploy ' + header['commit'] + ' ' + header['artifact']['sha256']
    ssh = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
           '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
           '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', host, command]
    # One SSH process keeps the server-side flock through transfer, smoke and rollback.
    # The forced-command key runs installed trusted code; stdin contains data only.
    with subprocess.Popen(ssh, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as process:
        try:
            try:
                process.stdin.write((json.dumps(header, separators=(',', ':')) + '\n').encode())
                if archive is not None:
                    with archive.open('rb') as source_file:
                        shutil.copyfileobj(source_file, process.stdin, 1024 * 1024)
            except BrokenPipeError:
                pass
            finally:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
                process.stdin = None
            stdout, stderr = process.communicate(timeout=900)
        except BaseException:
            # A dropped SSH channel signals the helper, which rolls back while locked.
            process.terminate()
            try:
                process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise
    if not stdout.strip():
        raise RuntimeError('SSH deployment operation failed (exit ' + str(process.returncode)
                           + '); check existing key, pinned known_hosts and sudo -n access: '
                           + stderr.decode(errors='replace').strip()[:2000])
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError('Remote deployment did not return machine-readable evidence') from error
    require(isinstance(result, dict) and result.get('schema') == 1, 'Invalid remote evidence')
    if process.returncode and result.get('status') != 'failed':
        raise RuntimeError('SSH exited unexpectedly; remote evidence cannot establish completion')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default='dist/release.json',
                        help='Aggregate manifest (relative paths resolve from repository root)')
    parser.add_argument('--host', default='arcmonkeys-prod')
    parser.add_argument('--site', default='https://play.arcmonkeyswelding.com')
    parser.add_argument('--restricted', action='store_true', default=True,
                        help='Use fixed forced-command protocol (always enabled; no arbitrary SSH execution)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--verify-current', action='store_true', help='Read-only current/public integrity check')
    mode.add_argument('--dry-run', action='store_true', help='Validate locally, without SSH or publication')
    mode.add_argument('--rollback', action='store_true',
                      help='Restore this manifest SHA deployment’s recorded prior release, only if still current')
    args = parser.parse_args()
    try:
        site = validate_site(args.site)
        if args.verify_current:
            header = {'operation': 'verify-current', 'site': site}
            # An explicitly supplied manifest additionally pins the current build.
            if '--manifest' in sys.argv[1:] or any(arg.startswith('--manifest=') for arg in sys.argv[1:]):
                _, expected = load_web_manifest(repository_path(args.manifest))
                header['expected'] = expected
            result = remote_operation(args.host, header)
        else:
            archive, header = load_web_manifest(repository_path(args.manifest))
            if args.dry_run:
                result = {'schema': 1, 'status': 'validated-not-deployed', 'mutated': False,
                          'commit': header['commit'], 'version': header['version'],
                          'artifact': header['artifact'], 'file_count': len(header['files']),
                          'site': site, 'ssh_connected': False}
            elif args.rollback:
                require_trusted_default_branch(header['commit'])
                header.update({'operation': 'rollback', 'site': site})
                result = remote_operation(args.host, header)
            else:
                require_trusted_default_branch(header['commit'])
                header.update({'operation': 'deploy', 'site': site})
                result = remote_operation(args.host, header, archive)
        print(json.dumps(result, sort_keys=True))
        return 1 if result.get('status') == 'failed' else 0
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({'schema': 1, 'status': 'failed', 'error': str(error),
                          'deployment_completion': 'not-established'}, sort_keys=True))
        return 1


if __name__ == '__main__':
    sys.exit(main())
