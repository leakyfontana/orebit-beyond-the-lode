#!/usr/bin/env python3
"""Fixed-function outbound Orebit deployer; never execute GitHub workflow/artifact code.

Run as orebit-deploy, with only the installed isolated release helper allowed by
sudo. All mutable files are confined to the game's private state/status trees.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# -I deliberately excludes the script directory from sys.path. Load only this
# root-owned sibling by its concrete path, not an import from writable state.
_HELPER_SOURCE = Path(__file__).resolve().with_name('remote_web_release.py')
_SPEC = importlib.util.spec_from_file_location('orebit_release_helper', _HELPER_SOURCE)
helper = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helper)

REPOSITORY = 'leakyfontana/orebit-beyond-the-lode'
SITE = 'https://play.arcmonkeyswelding.com'
GITHUB = 'https://github.com/' + REPOSITORY
API = 'https://api.github.com/repos/' + REPOSITORY
FEED = GITHUB + '/releases.atom'
STATE = Path('/srv/motherload/puller/state')
STATUS = Path('/srv/motherload/status')
INSTALLED_HELPER = '/srv/motherload/deploy/remote_web_release.py'
USER_AGENT = 'OrebitReleasePuller/1.0'
BUILD_JOBS = {'Release macos-arm64', 'Release windows-x86_64', 'Release android-arm64', 'Release web'}
HEX40 = re.compile(r'[0-9a-f]{40}')
HEX64 = re.compile(r'[0-9a-f]{64}')


class Pending(Exception):
    """Transient public metadata/network readiness; never a deployment attempt."""


class Rejected(Exception):
    """Invalid or terminal candidate; never retry it as a new deployment."""


class FetchFailure(Pending):
    def __init__(self, status=None):
        self.status = status
        super().__init__('Public HTTPS fetch unavailable' + (' (HTTP ' + str(status) + ')' if status else ''))


def require(condition, message):
    if not condition:
        raise Rejected(message)


class DownloadRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        require(parsed.scheme == 'https' and parsed.hostname in {
            'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
            and parsed.username is None and parsed.password is None,
            'Public download redirected outside approved HTTPS asset hosts')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def open_public(url, accept='application/json'):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname in {'github.com', 'api.github.com'}
            and parsed.username is None and parsed.password is None and not parsed.fragment,
            'Noncanonical initial public URL')
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept,
                                                 'Cache-Control': 'no-cache', 'Accept-Encoding': 'identity'})
    try:
        return urllib.request.build_opener(DownloadRedirect()).open(request, timeout=45)
    except urllib.error.HTTPError as error:
        # Never log bodies or final redirect URLs: signed asset URLs are private.
        raise FetchFailure(error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise FetchFailure() from None


def fetch_bytes(url, maximum, accept='application/json'):
    with open_public(url, accept) as response:
        require(response.status == 200, 'Unexpected public HTTPS response')
        content = response.read(maximum + 1)
        require(len(content) <= maximum, 'Public response exceeds permitted size')
        return content


def fetch_json(url, maximum=4 * 1024**2):
    try:
        value = json.loads(fetch_bytes(url, maximum))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise Rejected('Public metadata is not valid JSON') from None
    require(isinstance(value, dict), 'Public JSON metadata must be an object')
    return value


def canonical_asset(commit, name):
    return GITHUB + '/releases/download/candidate-' + commit + '/' + urllib.parse.quote(name, safe='')


def atomic_json(path, value, mode):
    require(path.parent in {STATE / 'records', STATUS}, 'Attempt to write outside state/status')
    require(not path.is_symlink(), 'Refusing symlink state/status file')
    descriptor, temporary = tempfile.mkstemp(prefix='.atomic-', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(value, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def save_record(record):
    require(HEX40.fullmatch(record['commit']), 'Invalid state commit')
    atomic_json(STATE / 'records' / (record['commit'] + '.json'), record, 0o600)


def publish(record, result, rollback=False):
    require(result.get('schema') == 1, 'Helper returned unsupported evidence')
    evidence = dict(result)
    evidence['run_id'] = record['request']['run_id']
    evidence.setdefault('commit', record['commit'])
    evidence.setdefault('version', record['request']['version'])
    evidence.setdefault('site', SITE)
    evidence.setdefault('archive_sha256', record['request']['artifact']['sha256'])
    name = ('rollback-' if rollback else '') + record['commit'] + '.json'
    path = STATUS / name
    if path.is_file() and not path.is_symlink():
        try:
            if json.loads(path.read_text()) == evidence:
                return evidence
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    atomic_json(path, evidence, 0o644)
    return evidence


def refresh_deployment_status(record):
    result = record.get('public_result', record.get('result'))
    if result is None:
        return
    rollback = record.get('rollback_result', {})
    if rollback.get('rolled_back') is True:
        result = rollback
    elif result.get('status') in {'deployed', 'verified-existing'}:
        try:
            current = helper.link_target('current', required=True)
            build = json.loads((current / 'build.json').read_text())
            matches = (current.name == 'sha-' + record['commit']
                       and build.get('commit') == record['commit']
                       and build.get('version') == record['request']['version'])
        except (OSError, ValueError, UnicodeDecodeError):
            matches = False
        if not matches:
            result = {'schema': 1, 'status': 'failed', 'mutated': False,
                      'superseded': True,
                      'error': 'Previously deployed candidate is no longer verifiably current'}
    if record.get('public_result') != result:
        record['public_result'] = result
        save_record(record)
    publish(record, result)


def candidate_links():
    try:
        document = ET.fromstring(fetch_bytes(FEED, 2 * 1024**2, 'application/atom+xml'))
    except ET.ParseError:
        raise Pending('Public release feed is not ready') from None
    prefix = GITHUB + '/releases/tag/candidate-'
    commits = []
    for node in document.iter('{http://www.w3.org/2005/Atom}link'):
        link = node.attrib.get('href', '')
        if link.startswith(prefix) and HEX40.fullmatch(link[len(prefix):]):
            commit = link[len(prefix):]
            if commit not in commits:
                commits.append(commit)
    return commits


def validate_request(record):
    commit = record['commit']
    tag = 'candidate-' + commit
    if 'release_assets' not in record:
        release = fetch_json(API + '/releases/tags/' + tag)
        require(release.get('tag_name') == tag and release.get('target_commitish') == commit
                and release.get('draft') is False and release.get('prerelease') is True
                and release.get('author', {}).get('login') == 'github-actions[bot]',
                'Candidate is not the canonical bot-authored SHA prerelease')
        assets = release.get('assets')
        require(isinstance(assets, list), 'Candidate has no asset inventory')
        record['release_assets'] = [{'name': item.get('name'), 'size': item.get('size'),
                                     'browser_download_url': item.get('browser_download_url')}
                                    for item in assets]
        save_record(record)
    assets = record['release_assets']
    requests = [item for item in assets if item.get('name') == 'deployment-request.json']
    require(len(requests) == 1 and requests[0].get('browser_download_url') == canonical_asset(commit, 'deployment-request.json'),
            'Candidate deployment request asset is missing or noncanonical')
    request = fetch_json(canonical_asset(commit, 'deployment-request.json'), 1024**2)
    require(request.get('schema') == 1 and request.get('kind') == 'orebit.web.deployment-request'
            and request.get('repository') == REPOSITORY and request.get('commit') == commit
            and request.get('site') == SITE and type(request.get('run_id')) is int
            and request['run_id'] > 0, 'Deployment request identity is invalid')
    try:
        helper.valid_identity(commit, request.get('version'))
    except ValueError:
        raise Rejected('Deployment request version is invalid') from None
    artifact = request.get('artifact')
    require(isinstance(artifact, dict), 'Deployment request artifact is invalid')
    name = artifact.get('name')
    require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*\.zip', name)
            and len(name) <= 240, 'Deployment ZIP basename is invalid')
    require(artifact.get('url') == canonical_asset(commit, name)
            and isinstance(artifact.get('sha256'), str) and HEX64.fullmatch(artifact['sha256'])
            and type(artifact.get('size')) is int and 0 < artifact['size'] <= helper.MAX_ARCHIVE,
            'Deployment ZIP location/integrity metadata is invalid')
    matches = [item for item in assets if item.get('name') == name]
    require(len(matches) == 1 and matches[0].get('browser_download_url') == artifact['url']
            and matches[0].get('size') == artifact['size'], 'Candidate ZIP asset inventory differs')
    files = request.get('files')
    require(isinstance(files, list) and 0 < len(files) <= 10000, 'Invalid expected Web file inventory')
    seen = set()
    for item in files:
        require(isinstance(item, dict), 'Invalid expected Web file')
        try:
            name = helper.safe_name(item.get('path'))
        except ValueError:
            raise Rejected('Unsafe expected Web filename') from None
        require(name not in seen and isinstance(item.get('sha256'), str) and HEX64.fullmatch(item['sha256'])
                and type(item.get('size')) is int and 0 <= item['size'] <= helper.MAX_EXPANDED,
                'Invalid expected Web file integrity metadata')
        seen.add(name)
    return request


def run_identity(request, rollback=False):
    run = fetch_json(API + '/actions/runs/' + str(request['run_id']))
    require(run.get('id') == request['run_id'] and run.get('path') == '.github/workflows/beta.yml'
            and run.get('event') == 'push' and run.get('head_branch') == 'main'
            and run.get('head_sha') == request['commit']
            and run.get('repository', {}).get('full_name') == REPOSITORY
            and run.get('head_repository', {}).get('full_name') == REPOSITORY,
            'Candidate workflow run identity differs from trusted main push')
    if rollback:
        return run
    status = run.get('status')
    if status == 'completed':
        require(run.get('conclusion') == 'success', 'Candidate workflow already failed or was cancelled')
        return run
    require(status in {'queued', 'in_progress', 'pending', 'waiting'}, 'Unknown candidate workflow status')
    if status not in {'queued', 'in_progress'}:
        raise Pending('Candidate workflow is waiting')
    return run


def check_ready(request):
    run = run_identity(request)
    if run['status'] == 'completed':
        return False
    jobs = []
    for page in range(1, 11):
        payload = fetch_json(API + '/actions/runs/' + str(request['run_id'])
                             + '/jobs?per_page=100&page=' + str(page))
        batch = payload.get('jobs')
        require(isinstance(batch, list), 'Invalid workflow job metadata')
        jobs.extend(batch)
        if len(jobs) >= payload.get('total_count', len(jobs)):
            break
    else:
        raise Rejected('Workflow job inventory exceeds limit')
    for name in BUILD_JOBS:
        matches = [job for job in jobs if job.get('name') == name]
        if not matches:
            raise Pending('Required release job metadata is not ready')
        require(len(matches) == 1, 'Ambiguous required release job')
        if matches[0].get('status') != 'completed':
            raise Pending('Required release job is not completed')
        require(matches[0].get('conclusion') == 'success', 'A required release job did not succeed')
    drive = [step for job in jobs for step in job.get('steps', [])
             if step.get('name') == 'Publish and verify Drive artifacts']
    if not drive or any(step.get('status') != 'completed' for step in drive):
        raise Pending('Drive publication verification is not completed')
    require(len(drive) == 1 and drive[0].get('conclusion') == 'success',
            'Drive publication verification did not succeed')
    main = fetch_json(API + '/branches/main')
    require(main.get('commit', {}).get('sha') == request['commit'],
            'Candidate is no longer the current main SHA; refusing downgrade')
    return True


def operation_header(request, operation):
    artifact = request['artifact']
    return {'operation': operation, 'site': SITE, 'commit': request['commit'],
            'version': request['version'], 'artifact': {'path': 'dist/web/' + artifact['name'],
            'sha256': artifact['sha256'], 'size': artifact['size']}, 'files': request['files']}


def download_zip(request):
    artifact = request['artifact']
    descriptor, name = tempfile.mkstemp(prefix='.web-', suffix='.zip', dir=STATE)
    path = Path(name)
    try:
        hasher = hashlib.sha256()
        size = 0
        with os.fdopen(descriptor, 'wb') as output, open_public(artifact['url'], 'application/octet-stream') as response:
            require(response.status == 200, 'Unexpected ZIP download response')
            while True:
                chunk = response.read(min(1024**2, artifact['size'] - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                require(size <= artifact['size'], 'Web ZIP exceeds declared size')
                hasher.update(chunk)
                output.write(chunk)
        require(size == artifact['size'] and hasher.hexdigest() == artifact['sha256'],
                'Downloaded ZIP integrity differs from deployment request')
        try:
            files = helper.inspect_archive(path, request['commit'], request['version'])
        except Exception:
            raise Rejected('Downloaded Web ZIP failed safe archive/provenance validation') from None
        require(files == request['files'], 'Downloaded Web file inventory differs from request')
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def invoke_helper(header, archive=None):
    operation = header['operation']
    if operation == 'deploy':
        command = 'deploy ' + header['commit'] + ' ' + header['artifact']['sha256']
    elif operation == 'rollback':
        command = 'rollback ' + header['commit']
    else:
        require(operation == 'verify-current', 'Unsupported fixed helper operation')
        command = 'verify'
    arguments = ['/usr/bin/sudo', '-n', '/usr/bin/python3', '-I', '-u', INSTALLED_HELPER,
                 '--original-command', command]
    with subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        try:
            try:
                process.stdin.write((json.dumps(header, separators=(',', ':')) + '\n').encode())
                if archive is not None:
                    with archive.open('rb') as source:
                        shutil.copyfileobj(source, process.stdin, 1024**2)
            except BrokenPipeError:
                pass
            finally:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
                process.stdin = None
            stdout, _ = process.communicate(timeout=930)
        except BaseException:
            process.terminate()
            try:
                process.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            return {'schema': 1, 'status': 'failed', 'error': 'Privileged operation did not establish completion',
                    'deployment_completion': 'not-established'}
    try:
        result = json.loads(stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {'schema': 1, 'status': 'failed', 'error': 'Privileged helper returned no valid evidence',
                'deployment_completion': 'not-established'}
    if not isinstance(result, dict) or result.get('schema') != 1 or process.returncode and result.get('status') != 'failed':
        return {'schema': 1, 'status': 'failed', 'error': 'Privileged helper result was inconsistent',
                'deployment_completion': 'not-established'}
    return result


def process_candidate(record):
    if 'request' not in record:
        record['request'] = validate_request(record)
        save_record(record)
    request = record['request']
    ready = check_ready(request)
    if not ready:
        # A completed-success workflow may be checked, never newly deployed.
        header = {'operation': 'verify-current', 'site': SITE,
                  'expected': operation_header(request, 'deploy')}
        record['phase'] = 'attempted'
        save_record(record)
        result = invoke_helper(header)
    else:
        archive = download_zip(request)
        try:
            # Downloads can take time; re-check freshness immediately before sudo.
            run = run_identity(request)
            require(run['status'] in {'queued', 'in_progress'}, 'Workflow completed before new deployment')
            main = fetch_json(API + '/branches/main')
            require(main.get('commit', {}).get('sha') == request['commit'],
                    'Main advanced during download; refusing deployment downgrade')
            # Persist before sudo so a service restart cannot deploy it twice.
            record['phase'] = 'attempted'
            save_record(record)
            result = invoke_helper(operation_header(request, 'deploy'), archive)
        finally:
            archive.unlink(missing_ok=True)
    record['result'] = result
    record['phase'] = 'finished'
    save_record(record)
    return publish(record, result)


def process_rollback(record):
    if record.get('rollback_done') or record.get('phase') not in {'attempted', 'finished'}:
        return None
    # Retained historical releases cannot be rolled back over the current one.
    # Poll rollback assets only for the live, genuinely mutating candidate.
    if record.get('result', {}).get('mutated') is not True:
        return None
    if helper.link_target('current', required=True).name != 'sha-' + record['commit']:
        return None
    try:
        request = fetch_json(canonical_asset(record['commit'], 'rollback-request.json'), 65536)
    except FetchFailure as error:
        if error.status == 404:
            return None
        raise
    original = record['request']
    require(request.get('schema') == 1 and request.get('kind') == 'orebit.web.rollback-request'
            and request.get('repository') == REPOSITORY and request.get('commit') == record['commit']
            and request.get('version') == original['version'] and request.get('run_id') == original['run_id']
            and request.get('artifact_sha256') == original['artifact']['sha256'],
            'Rollback request differs from originally attempted candidate')
    run_identity(original, rollback=True)
    # A rerun that only verified an accepted SHA must never roll it back.
    require(record.get('result', {}).get('mutated') is True,
            'Rollback refused: this attempt did not record a live cutover')
    record['rollback_done'] = True
    save_record(record)
    result = invoke_helper(operation_header(original, 'rollback'))
    record['rollback_result'] = result
    save_record(record)
    return publish(record, result, rollback=True)


def prepare_directories():
    for directory, mode in ((STATE, 0o700), (STATUS, 0o755)):
        require(directory.is_dir() and not directory.is_symlink() and directory.resolve() == directory,
                'Parent must provision real scoped state/status directories')
        metadata = directory.stat()
        require(metadata.st_uid == os.geteuid() and metadata.st_mode & 0o777 == mode,
                'State/status directory ownership or permissions differ from contract')
    records = STATE / 'records'
    records.mkdir(mode=0o700, exist_ok=True)
    require(records.is_dir() and not records.is_symlink()
            and records.stat().st_uid == os.geteuid() and records.stat().st_mode & 0o777 == 0o700,
            'Private record directory is unsafe')


def poll_once():
    events = []
    records = {}
    for path in (STATE / 'records').glob('*.json'):
        require(not path.is_symlink() and HEX40.fullmatch(path.stem), 'Invalid private candidate record')
        record = json.loads(path.read_text())
        require(record.get('commit') == path.stem, 'Candidate record identity differs')
        records[path.stem] = record
        # Invalidate stale positive status before any potentially slow HTTPS poll.
        if record['phase'] in {'finished', 'rejected'} and 'result' in record:
            refresh_deployment_status(record)
    try:
        commits = candidate_links()
    except Pending as error:
        commits = []
        events.append({'status': 'pending', 'reason': str(error)})
    for commit in commits:
        if commit not in records:
            records[commit] = {'schema': 1, 'commit': commit, 'phase': 'pending'}
            save_record(records[commit])
    for commit, record in records.items():
        if record['phase'] == 'attempted' and 'result' not in record:
            result = {'schema': 1, 'status': 'failed', 'error': 'Service stopped after durable attempt marker',
                      'deployment_completion': 'not-established'}
            record.update({'phase': 'finished', 'result': result})
            save_record(record)
            publish(record, result)
        if record['phase'] == 'pending':
            try:
                result = process_candidate(record)
                events.append({'commit': commit, 'status': result['status']})
            except Pending as error:
                events.append({'commit': commit, 'status': 'pending', 'reason': str(error)})
            except Rejected as error:
                record['phase'] = 'rejected'
                record['error'] = str(error)
                if 'request' in record:
                    record['result'] = {'schema': 1, 'status': 'failed', 'mutated': False, 'error': str(error)}
                save_record(record)
                if 'result' in record:
                    publish(record, record['result'])
                events.append({'commit': commit, 'status': 'rejected', 'reason': str(error)})
        if record.get('rollback_done') and 'rollback_result' not in record:
            record['rollback_result'] = {
                'schema': 1, 'status': 'failed',
                'error': 'Service stopped after durable rollback attempt marker',
                'deployment_completion': 'not-established'}
            save_record(record)
        if record.get('rollback_done') and 'rollback_result' in record:
            if not (STATUS / ('rollback-' + commit + '.json')).exists():
                publish(record, record['rollback_result'], rollback=True)
        else:
            try:
                result = process_rollback(record)
                if result is not None:
                    events.append({'commit': commit, 'status': result['status'], 'operation': 'rollback'})
            except Pending:
                pass
            except Rejected as error:
                record['rollback_done'] = True
                record['rollback_result'] = {'schema': 1, 'status': 'failed', 'mutated': False, 'error': str(error)}
                save_record(record)
                publish(record, record['rollback_result'], rollback=True)
        if record['phase'] in {'finished', 'rejected'} and 'result' in record:
            refresh_deployment_status(record)
    return {'schema': 1, 'events': events}


def service_loop(arguments):
    while True:
        try:
            print(json.dumps(poll_once(), sort_keys=True), flush=True)
        except KeyboardInterrupt:
            return 0
        except Exception as error:
            # Do not leak signed download URLs or network response bodies to logs.
            print(json.dumps({'schema': 1, 'status': 'poll-failed', 'error_type': type(error).__name__}), flush=True)
            if arguments.once:
                return 1
        if arguments.once:
            return 0
        time.sleep(arguments.interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Poll once without a service loop')
    parser.add_argument('--interval', type=int, default=30)
    arguments = parser.parse_args()
    if arguments.interval < 10:
        parser.error('--interval must be at least 10 seconds')
    try:
        prepare_directories()
    except Exception:
        print(json.dumps({'schema': 1, 'status': 'failed', 'error': 'Private game directories are not provisioned safely'}))
        return 1
    descriptor = os.open(STATE / '.poll.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'schema': 1, 'status': 'failed', 'error': 'Another game puller is active'}))
            return 1
        return service_loop(arguments)


if __name__ == '__main__':
    sys.exit(main())
