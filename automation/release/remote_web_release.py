#!/usr/bin/env python3
"""Trusted isolated deployment operation; all filesystem writes stay in /srv/motherload."""
import contextlib
from enum import Enum
import fcntl
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

# Isolated installed helpers (-I) must load only reviewed root-owned siblings,
# never a policy module from the writable deployment state or environment.
_POLICY_SOURCE = Path(__file__).resolve().with_name('version_policy.py')
_POLICY_SPEC = importlib.util.spec_from_file_location('orebit_version_policy', _POLICY_SOURCE)
_POLICY = importlib.util.module_from_spec(_POLICY_SPEC)
_POLICY_SPEC.loader.exec_module(_POLICY)
valid_identity = _POLICY.valid_identity

BASE = Path('/srv/motherload')
MAX_ARCHIVE = 2 * 1024**3
MAX_EXPANDED = 4 * 1024**3
ALLOWED_SUFFIXES = {'.html', '.js', '.wasm', '.pck', '.png', '.svg', '.ico',
                    '.json', '.webmanifest', '.css', '.txt', '.woff', '.woff2',
                    '.ttf', '.otf', '.ogg', '.mp3', '.wav', '.bin'}
DIAGNOSTIC_ARGUMENTS = (b'--replay', b'--capture', b'--fixed-fps',
                        b'MOTHERLOAD_REPLAY', b'MOTHERLOAD_CAPTURE')


class ReleaseOperation(str, Enum):
    DEPLOY = 'deploy'
    ROLLBACK = 'rollback'
    VERIFY_CURRENT = 'verify-current'


class ResultStatus(str, Enum):
    DEPLOYED = 'deployed'
    VERIFIED_EXISTING = 'verified-existing'
    VERIFIED_CURRENT = 'verified-current'
    ROLLED_BACK = 'rolled-back'
    FAILED = 'failed'


def result_status(result):
    try:
        return ResultStatus(result.get('status'))
    except ValueError:
        return None


class ActivationState(Enum):
    EXISTING_CURRENT = 'existing-current'
    UNACTIVATED = 'unactivated'
    PREVIOUS_OWNED = 'previous-owned'
    CURRENT_OWNED = 'current-owned'
    COMPENSATED = 'compensated'


class RollbackState(Enum):
    READY = 'ready'
    RESTORED = 'restored'
    VERIFIED = 'verified'
    FAILED_UNRESTORED = 'failed-unrestored'
    FAILED_RESTORED = 'failed-restored'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()




def safe_name(name, directory=False):
    require(isinstance(name, str) and name and len(name) < 512, 'Invalid archive filename')
    cleaned = name[:-1] if directory and name.endswith('/') else name
    path = PurePosixPath(cleaned)
    require(not path.is_absolute() and str(path) == cleaned and '\\' not in cleaned
            and all(part not in ('', '.', '..') and not part.startswith('.')
                    and re.fullmatch(r'[A-Za-z0-9_+@ -][A-Za-z0-9_.+@ -]*', part)
                    for part in path.parts), 'Unsafe archive filename: ' + name)
    if not directory:
        require(path.suffix.lower() in ALLOWED_SUFFIXES,
                'Unexpected or sensitive Web file: ' + name)
        require(path.name.lower() not in {'credentials.json', 'secrets.json', 'package.json',
                                          'package-lock.json', 'tsconfig.json', 'id_rsa', 'id_ed25519'},
                'Unexpected sensitive/configuration file: ' + name)
        if path.suffix.lower() == '.json':
            require(path.name == 'build.json' or path.name.endswith('.manifest.json'),
                    'Unexpected JSON file in static Web release: ' + name)
    return cleaned


def inspect_archive(archive_path, commit, version, destination=None):
    """Validate every member before extracting regular files without ZipFile.extract."""
    valid_identity(commit, version)
    files = []
    seen = set()
    expanded = 0
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        require(0 < len(members) <= 10000, 'Invalid Web ZIP entry count')
        for info in members:
            name = safe_name(info.filename, info.is_dir())
            require(name.casefold() not in seen, 'Duplicate archive entry: ' + name)
            seen.add(name.casefold())
            kind = stat.S_IFMT(info.external_attr >> 16)
            require(kind in (0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG),
                    'Archive links/devices are forbidden: ' + name)
            require(not info.flag_bits & 1, 'Encrypted archive member forbidden')
            expanded += info.file_size
            require(expanded <= MAX_EXPANDED, 'Expanded Web ZIP is too large')
        for info in members:
            if info.is_dir():
                continue
            name = info.filename
            hasher = hashlib.sha256()
            size = 0
            target = None
            if destination is not None:
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, contextlib.ExitStack() as stack:
                sink = stack.enter_context(open(target, 'xb')) if target else None
                previous = b''
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    hasher.update(chunk)
                    size += len(chunk)
                    if name.endswith(('.js', '.html', '.json')):
                        text = previous + chunk
                        require(not any(arg in text for arg in DIAGNOSTIC_ARGUMENTS),
                                'Packaged diagnostic startup arguments: ' + name)
                        previous = text[-64:]
                    if sink:
                        sink.write(chunk)
            require(size == info.file_size, 'Archive member size mismatch')
            files.append({'path': name, 'sha256': hasher.hexdigest(), 'size': size})
        names = {item['path'] for item in files}
        require({'index.html', 'build.json'} <= names and any(n.endswith('.wasm') for n in names)
                and any(n.endswith('.pck') for n in names), 'Web ZIP lacks runnable root files')
        require(archive.getinfo('build.json').file_size <= 65536, 'build.json too large')
        build = json.loads(archive.read('build.json'))
        require(build.get('commit') == commit and build.get('version') == version,
                'Web build.json identity differs from release manifest')
    return sorted(files, key=lambda item: item['path'])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Public verification unexpectedly redirected')


def validate_site(site):
    parsed = urllib.parse.urlsplit(site)
    require(parsed.scheme == 'https' and parsed.hostname and parsed.username is None
            and parsed.password is None and not parsed.query and not parsed.fragment
            and parsed.path in ('', '/'), 'Site must be an HTTPS origin')
    return site.rstrip('/')


def public_verify(site, files, commit=None, version=None, require_build=True):
    """Verify origin responses, not browser caches; never disable TLS verification."""
    site = validate_site(site)
    expected = {item['path']: item for item in files}
    paths = (['build.json'] if require_build or 'build.json' in expected else []) + ['index.html']
    wasm = sorted(p for p in expected if p.endswith('.wasm'))
    require(wasm, 'Current Web release has no wasm files')
    paths += wasm
    opener = urllib.request.build_opener(NoRedirect())
    # Identify the release verifier honestly for the public CDN's client policy.
    opener.addheaders = [('User-Agent', 'OrebitReleaseVerifier/1.0')]
    evidence = []
    for name in paths:
        require(name in expected, 'Missing public verification file: ' + name)
        url = site + '/' + urllib.parse.quote(name, safe='/') + '?release_check=' + uuid.uuid4().hex
        request = urllib.request.Request(url, headers={'Accept-Encoding': 'identity',
                                                     'Cache-Control': 'no-cache'})
        with opener.open(request, timeout=45) as response:
            require(response.status == 200, 'Unexpected public HTTP status')
            headers = response.headers
            require(headers.get('Cross-Origin-Opener-Policy') == 'same-origin'
                    and headers.get('Cross-Origin-Embedder-Policy') == 'require-corp'
                    and headers.get('Cross-Origin-Resource-Policy') == 'same-origin'
                    and headers.get('X-Content-Type-Options') == 'nosniff',
                    'Public isolation/security headers missing: ' + name)
            require(headers.get('Content-Encoding', 'identity') == 'identity',
                    'Unexpected encoding for identity verification: ' + name)
            mime = headers.get_content_type()
            wanted = ('application/wasm' if name.endswith('.wasm') else
                      'text/html' if name.endswith('.html') else 'application/json')
            require(mime == wanted, 'Incorrect public MIME type: ' + name)
            hasher = hashlib.sha256()
            size = 0
            build_bytes = bytearray()
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                size += len(chunk)
                require(size <= expected[name]['size'], 'Public file exceeds expected size: ' + name)
                hasher.update(chunk)
                if name == 'build.json':
                    build_bytes.extend(chunk)
            require(size == expected[name]['size'] and hasher.hexdigest() == expected[name]['sha256'],
                    'Public content integrity mismatch: ' + name)
            if name == 'build.json':
                build = json.loads(build_bytes)
                if commit is not None:
                    require(build.get('commit') == commit and build.get('version') == version,
                            'Public build identity mismatch')
            evidence.append({'path': name, 'status': 200, 'sha256': hasher.hexdigest(),
                             'size': size, 'content_type': mime, 'isolation_headers': True})
        if name.endswith('.wasm'):
            request = urllib.request.Request(url, method='HEAD', headers={
                'Accept-Encoding': 'gzip', 'Cache-Control': 'no-cache'})
            with opener.open(request, timeout=45) as response:
                require(response.status == 200 and response.headers.get_content_type() == 'application/wasm'
                        and response.headers.get('Content-Encoding') == 'gzip',
                        'Precompressed WASM MIME/encoding verification failed: ' + name)
            evidence[-1]['gzip_content_type'] = 'application/wasm'
            evidence[-1]['gzip_content_encoding'] = 'gzip'
    return evidence


def real_directory(path):
    require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
            'Expected real scoped directory: ' + str(path))


def link_target(name, required=False):
    link = BASE / name
    if not link.is_symlink():
        require(not required and not link.exists(), 'Expected release symlink: ' + name)
        return None
    target = link.resolve(strict=True)
    require(target.parent == BASE / 'releases' and target.is_dir(), 'Symlink escapes release root')
    return target


def replace_link(name, target):
    temporary = BASE / ('.' + name + '-' + uuid.uuid4().hex)
    try:
        temporary.symlink_to(target)
        os.replace(temporary, BASE / name)
    finally:
        temporary.unlink(missing_ok=True)


def verify_files(root, files):
    actual = set()
    for path in root.rglob('*'):
        require(not path.is_symlink(), 'Release contains a symlink')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
        else:
            require(path.is_dir(), 'Release contains non-regular file')
    require(actual == {item['path'] for item in files}, 'Release file inventory differs')
    for item in files:
        path = root / item['path']
        require(path.stat().st_size == item['size'] and digest(path) == item['sha256'],
                'Staged/released file integrity mismatch: ' + item['path'])


def make_immutable(root):
    for path in root.rglob('*'):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def atomic_manifest(path, value):
    content = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    if path.exists() or path.is_symlink():
        require(not path.is_symlink() and path.read_bytes() == content,
                'Existing immutable release manifest differs')
        return
    temporary = BASE / ('.manifest-' + uuid.uuid4().hex)
    try:
        with open(temporary, 'xb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o444)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def interrupt(signum, frame):
    raise RuntimeError('Deployment interrupted by signal ' + str(signum))


def current_inventory(current):
    files = []
    for path in current.rglob('*'):
        require(not path.is_symlink(), 'Current release contains a symlink')
        if path.is_file() and (path.name in ('build.json', 'index.html') or path.suffix == '.wasm'):
            name = safe_name(path.relative_to(current).as_posix())
            files.append({'path': name, 'sha256': digest(path), 'size': path.stat().st_size})
    return files


def save_rollback_record(commit, value):
    path = BASE / 'manifests' / ('sha-' + commit + '.rollback.json')
    temporary = BASE / ('.rollback-' + uuid.uuid4().hex)
    try:
        with open(temporary, 'x') as output:
            json.dump(value, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o444)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def release_inventory(root):
    files = []
    for path in root.rglob('*'):
        require(not path.is_symlink(), 'Prior release contains a symlink')
        if path.is_file():
            name = path.relative_to(root).as_posix()
            safe_name(name[:-3] if name.endswith('.gz') else name)
            files.append({'path': name, 'sha256': digest(path), 'size': path.stat().st_size})
        else:
            require(path.is_dir(), 'Prior release contains a special file')
    return sorted(files, key=lambda item: item['path'])


class Activation:
    """Own only the link changes made by this locked deployment attempt."""

    def __init__(self, current, previous, release):
        self.current = current
        self.previous = previous
        self.release = release
        self.state = (ActivationState.EXISTING_CURRENT if current == release
                      else ActivationState.UNACTIVATED)

    @property
    def mutated(self):
        return self.state in {ActivationState.CURRENT_OWNED, ActivationState.COMPENSATED}

    def activate(self, commit, version, artifact):
        if self.state is ActivationState.EXISTING_CURRENT:
            return
        require(self.state is ActivationState.UNACTIVATED, 'Deployment already activated')
        save_rollback_record(commit, {'schema': 1, 'commit': commit, 'version': version,
                                     'archive_sha256': artifact['sha256'], 'from': str(self.current),
                                     'previous_before': str(self.previous) if self.previous is not None else None,
                                     'from_files': release_inventory(self.current)})
        # Claim previous before its write, including a failure during that write.
        # Current's atomic rename remains the only live cutover.
        self.state = ActivationState.PREVIOUS_OWNED
        replace_link('previous', self.current)
        replace_link('current', self.release)
        self.state = ActivationState.CURRENT_OWNED

    def compensate(self, failure, site):
        observed = link_target('current', required=True)
        if (self.state in {ActivationState.PREVIOUS_OWNED, ActivationState.CURRENT_OWNED}
                and observed == self.release and self.current != self.release):
            failure['mutated'] = True
            replace_link('current', self.current)
            self.state = ActivationState.COMPENSATED
            failure['rolled_back'] = True
        elif self.state is ActivationState.CURRENT_OWNED:
            failure['rollback_skipped'] = 'Current no longer selects this deployment'
        if (self.state is ActivationState.COMPENSATED
                or self.state is ActivationState.PREVIOUS_OWNED and observed == self.current):
            if self.previous is None:
                (BASE / 'previous').unlink(missing_ok=True)
            else:
                replace_link('previous', self.previous)
        failure['current'] = str(link_target('current', required=True))
        if self.state is ActivationState.COMPENSATED:
            failure['rollback_public_checks'] = public_verify(
                site, current_inventory(self.current),
                require_build=(self.current / 'build.json').is_file())


class Rollback:
    def __init__(self, current, prior, previous):
        self.current = current
        self.prior = prior
        self.previous = previous
        self.state = RollbackState.READY
        self.details = {}
        self.error = None
        self.observed = None

    def restore(self, site):
        require(self.state is RollbackState.READY, 'Rollback already consumed')
        require(link_target('current', required=True) == self.current, 'Current changed before rollback')
        replace_link('current', self.prior)
        self.state = RollbackState.RESTORED
        if self.previous is None:
            (BASE / 'previous').unlink(missing_ok=True)
        else:
            replace_link('previous', self.previous)
        self.details['previous'] = str(self.previous) if self.previous is not None else None
        self.details['public_checks'] = public_verify(
            site, current_inventory(self.prior), require_build=(self.prior / 'build.json').is_file())
        require(link_target('current', required=True) == self.prior, 'Current changed during rollback verification')
        self.state = RollbackState.VERIFIED

    def fail(self, error):
        # A failed verification must never re-publish the failed candidate.
        self.error = str(error)
        self.observed = link_target('current', required=True)
        restored = link_target('current', required=True) == self.prior
        self.state = (RollbackState.FAILED_RESTORED
                      if self.state in {RollbackState.RESTORED, RollbackState.VERIFIED} or restored
                      else RollbackState.FAILED_UNRESTORED)

    def evidence(self, header):
        restored = self.state in {RollbackState.VERIFIED, RollbackState.FAILED_RESTORED}
        evidence = {'schema': 1,
                    'status': (ResultStatus.ROLLED_BACK.value if self.state is RollbackState.VERIFIED
                               else ResultStatus.FAILED.value),
                    'rolled_back': restored, 'mutated': restored,
                    'commit': header['commit'], 'version': header['version'],
                    'site': header['site'], 'failed_release': str(self.current), 'release': str(self.prior)}
        evidence.update(self.details)
        if self.error is not None:
            evidence.update({'error': self.error, 'current': str(self.observed)})
        return evidence


def rollback_release(header):
    commit, version = header['commit'], header['version']
    valid_identity(commit, version)
    require(not sys.stdin.buffer.read(1), 'Unexpected payload for rollback')
    descriptor = os.open(BASE / '.deploy.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'r+') as lock:
        require(stat.S_ISREG(os.fstat(lock.fileno()).st_mode), 'Deployment lock is not a regular file')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = link_target('current', required=True)
        require(current == BASE / 'releases' / ('sha-' + commit),
                'Rollback refused: current no longer selects this manifest SHA')
        build = json.loads((current / 'build.json').read_text())
        require(build.get('commit') == commit and build.get('version') == version,
                'Rollback current build identity differs from manifest')
        record_path = BASE / 'manifests' / ('sha-' + commit + '.rollback.json')
        require(record_path.is_file() and not record_path.is_symlink(),
                'This deployment has no recorded prior release')
        record = json.loads(record_path.read_text())
        require(record['commit'] == commit and record['version'] == version
                and record['archive_sha256'] == header['artifact']['sha256'],
                'Rollback record does not match exact Web artifact')
        prior = Path(record['from'])
        require(prior.parent == BASE / 'releases' and prior != current,
                'Invalid recorded rollback target')
        real_directory(prior)
        require(link_target('previous', required=True) == prior,
                'Rollback refused: previous no longer selects recorded prior release')
        old_previous = Path(record['previous_before']) if record['previous_before'] else None
        if old_previous is not None:
            require(old_previous.parent == BASE / 'releases', 'Invalid recorded previous target')
            real_directory(old_previous)
        verify_files(prior, record['from_files'])
        rollback = Rollback(current, prior, old_previous)
        try:
            rollback.restore(header['site'])
        except BaseException as error:
            rollback.fail(error)
        return rollback.evidence(header)


def run_remote(original_command):
    started = time.time()
    header_line = sys.stdin.buffer.readline(1024 * 1024 + 1)
    require(len(header_line) <= 1024 * 1024 and header_line.endswith(b'\n'), 'Invalid operation header')
    header = json.loads(header_line)
    site = validate_site(header['site'])
    require(site == 'https://play.arcmonkeyswelding.com', 'Installed helper only serves the game origin')
    deployment_command = re.fullmatch(r'deploy ([0-9a-f]{40}) ([0-9a-f]{64})', original_command)
    rollback_command = re.fullmatch(r'rollback ([0-9a-f]{40})', original_command)
    require(original_command == 'verify' or deployment_command is not None or rollback_command is not None,
            'Only verify, deploy <fullsha> <zipsha256>, or rollback <fullsha> commands are permitted')
    operation = (ReleaseOperation.VERIFY_CURRENT if original_command == 'verify' else
                 ReleaseOperation.ROLLBACK if rollback_command is not None else ReleaseOperation.DEPLOY)
    require(header.get('operation') == operation.value, 'Command and operation header differ')
    real_directory(BASE)
    real_directory(BASE / 'releases')
    real_directory(BASE / 'manifests')
    if operation is ReleaseOperation.ROLLBACK:
        require(rollback_command.group(1) == header.get('commit'), 'Rollback command/header SHA differs')
        return rollback_release(header)
    if operation is ReleaseOperation.VERIFY_CURRENT:
        current = link_target('current', required=True)
        files = current_inventory(current)
        build_path = current / 'build.json'
        build = json.loads(build_path.read_text()) if build_path.is_file() else {}
        if 'expected' in header:
            expected = header['expected']
            require(build.get('commit') == expected['commit'] and build.get('version') == expected['version'],
                    'Current release identity differs from supplied manifest')
            wanted = {item['path']: item for item in expected['files']}
            require(all(wanted.get(item['path']) == item for item in files),
                    'Current files differ from supplied manifest')
        evidence = public_verify(site, files, build.get('commit'), build.get('version'),
                                 require_build=build_path.is_file())
        require(link_target('current', required=True) == current, 'Current changed during verification')
        return {'schema': 1, 'status': ResultStatus.VERIFIED_CURRENT.value, 'mutated': False, 'site': site,
                'release': str(current), 'commit': build.get('commit'), 'version': build.get('version'),
                'provenance': 'build.json' if build else 'legacy-release-without-build.json',
                'public_checks': evidence}
    require(operation is ReleaseOperation.DEPLOY, 'Unknown operation')
    commit, version = header['commit'], header['version']
    valid_identity(commit, version)
    artifact = header['artifact']
    require(type(artifact['size']) is int and 0 < artifact['size'] <= MAX_ARCHIVE
            and re.fullmatch(r'[0-9a-f]{64}', artifact['sha256']), 'Invalid ZIP integrity metadata')
    require(deployment_command.group(1) == commit and deployment_command.group(2) == artifact['sha256'],
            'Forced command identity differs from incoming ZIP manifest')
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, interrupt)
    descriptor = os.open(BASE / '.deploy.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'r+') as lock:
        require(stat.S_ISREG(os.fstat(lock.fileno()).st_mode), 'Deployment lock is not a regular file')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = link_target('current', required=True)
        previous = link_target('previous')
        stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=BASE))
        release = BASE / 'releases' / ('sha-' + commit)
        activation = Activation(current, previous, release)
        try:
            archive_path = stage / 'web.zip'
            with open(archive_path, 'xb') as output:
                remaining = artifact['size']
                while remaining:
                    chunk = sys.stdin.buffer.read(min(1024 * 1024, remaining))
                    require(chunk, 'Truncated ZIP transfer')
                    output.write(chunk)
                    remaining -= len(chunk)
            require(not sys.stdin.buffer.read(1), 'Unexpected bytes after Web ZIP')
            require(digest(archive_path) == artifact['sha256'], 'Transferred ZIP SHA mismatch')
            content = stage / 'content'
            content.mkdir()
            files = inspect_archive(archive_path, commit, version, content)
            require(files == header['files'], 'Local/remote Web manifest differs')
            originals = list(files)
            for item in originals:
                path = content / item['path']
                if path.suffix in {'.js', '.wasm', '.pck', '.html', '.css', '.json', '.svg', '.webmanifest'}:
                    compressed = Path(str(path) + '.gz')
                    with open(path, 'rb') as source, open(compressed, 'xb') as raw:
                        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as output:
                            shutil.copyfileobj(source, output, 1024 * 1024)
                    files.append({'path': item['path'] + '.gz', 'sha256': digest(compressed),
                                  'size': compressed.stat().st_size})
            files.sort(key=lambda item: item['path'])
            verify_files(content, files)
            manifest = {'schema': 1, 'commit': commit, 'version': version,
                        'platform': 'web', 'artifact': artifact, 'files': files}
            if release.exists() or release.is_symlink():
                real_directory(release)
                verify_files(release, files)
            else:
                make_immutable(content)
                os.replace(content, release)
            atomic_manifest(BASE / 'manifests' / (release.name + '.json'), manifest)
            require(link_target('current', required=True) == current, 'Current changed outside deployment lock')
            activation.activate(commit, version, artifact)
            evidence = public_verify(site, originals, commit, version)
            require(link_target('current', required=True) == release, 'Another actor replaced current')
            return {'schema': 1,
                    'status': (ResultStatus.DEPLOYED.value if activation.mutated
                               else ResultStatus.VERIFIED_EXISTING.value),
                    'mutated': activation.mutated, 'commit': commit, 'version': version, 'site': site,
                    'release': str(release), 'previous': str(current if activation.mutated else previous),
                    'archive_sha256': artifact['sha256'], 'public_checks': evidence,
                    'duration_seconds': round(time.time() - started, 3)}
        except BaseException as error:
            failure = {'schema': 1, 'status': ResultStatus.FAILED.value, 'error': str(error), 'commit': commit,
                       'version': version, 'site': site, 'rolled_back': False, 'mutated': activation.mutated,
                       'duration_seconds': round(time.time() - started, 3)}
            try:
                activation.compensate(failure, site)
            except BaseException as rollback_error:
                failure['rollback_error'] = str(rollback_error)
            return failure
        finally:
            if stage.exists():
                for root, directories, names in os.walk(stage):
                    Path(root).chmod(0o700)
                shutil.rmtree(stage)


def main():
    try:
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM):
            signal.signal(number, interrupt)
        signal.alarm(900)
        require(len(sys.argv) == 3 and sys.argv[1] == '--original-command',
                'Invoke only through the installed forced-command wrapper')
        result = run_remote(sys.argv[2])
    except BaseException as error:
        result = {'schema': 1, 'status': ResultStatus.FAILED.value, 'error': str(error),
                  'deployment_completion': 'not-established'}
    print(json.dumps(result, sort_keys=True), flush=True)
    return 1 if result_status(result) is ResultStatus.FAILED else 0


if __name__ == '__main__':
    sys.exit(main())
