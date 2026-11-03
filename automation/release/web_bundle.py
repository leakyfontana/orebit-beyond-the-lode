#!/usr/bin/env python3
"""Pin Godot's pack, runtime and native extensions to one immutable URL namespace.

Run after a normal Web export and before archiving/publishing the directory.
The root HTML, manifest and worker are stable entry points; saved games remain
in the same origin's Godot /userfs database. No live client is reloaded here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def _replace_once(text, pattern, replacement, description):
    result, count = re.subn(pattern, lambda _: replacement, text, flags=re.DOTALL)
    if count != 1:
        raise ValueError('Unexpected Godot Web template: ' + description)
    return result


def stage_web_bundle(directory):
    directory = Path(directory)
    paths = sorted(directory.iterdir())
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValueError('Stage a fresh, flat Godot Web export, not an existing bundle')
    # An editor watching exports/ imports generated icons; its sidecars are not
    # Web runtime assets and the release packager correctly refuses them.
    sidecars = [path for path in paths if path.suffix == '.import']
    paths = [path for path in paths if path.suffix != '.import']
    html = (directory / 'index.html').read_text(encoding='utf-8')
    worker = (directory / 'index.service.worker.js').read_text(encoding='utf-8')
    manifest = json.loads((directory / 'index.manifest.json').read_text(encoding='utf-8'))
    cached_match = re.search(r'const CACHED_FILES = (\[[^\n]*\]);', worker)
    cacheable_match = re.search(r'const CACHEABLE_FILES = (\[[^\n]*\]);', worker)
    if cached_match is None or cacheable_match is None:
        raise ValueError('Expected the pinned Godot PWA worker')
    cached = json.loads(cached_match.group(1))
    cacheable = json.loads(cacheable_match.group(1))
    names = {path.name for path in paths}
    if not set(cached + cacheable + ['index.manifest.json']) <= names:
        raise ValueError('Godot export is missing a referenced Web asset')
    fingerprint = hashlib.sha256()
    for path in paths:
        if path.name == 'build.json':
            continue
        fingerprint.update(path.name.encode('utf-8') + b'\0')
        content = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                content.update(chunk)
        fingerprint.update(content.digest())
    prefix = 'game-' + fingerprint.hexdigest()
    entrypoint = prefix + '/index.html'
    html = _replace_once(html, r'"serviceWorker":"index\.service\.worker\.js"',
                         '"serviceWorker":"../index.service.worker.js"', 'worker registration')
    html = _replace_once(html, r'href="index\.manifest\.json"',
                         'href="../index.manifest.json"', 'manifest link')
    root_files = {'index.service.worker.js', 'index.manifest.json', 'build.json'}
    cached = ['index.html', 'index.manifest.json'] + [
        name if name in root_files else prefix + '/' + name for name in cached]
    cached = list(dict.fromkeys(cached))
    worker = _replace_once(worker, r"const CACHE_VERSION = '[^']*';",
                           "const CACHE_VERSION = '" + prefix + "';", 'bundle cache version')
    worker = _replace_once(worker, r'const CACHED_FILES = \[[^\n]*\];',
                           'const CACHED_FILES = ' + json.dumps(cached) + ';', 'precache list')
    worker = _replace_once(worker, r'const CACHEABLE_FILES = \[[^\n]*\];',
                           'const CACHEABLE_FILES = ' + json.dumps([prefix + '/' + name for name in cacheable]) + ';', 'lazy cache list')
    worker = _replace_once(worker, r"const OFFLINE_URL = '[^']*';",
                           "const OFFLINE_URL = '" + prefix + "/index.offline.html';", 'offline page')
    # The root worker also covers single-use backend callbacks. Speculative
    # preload consumes them even when the fetch handler leaves navigation alone.
    worker = _replace_once(worker, r'self\.registration\.navigationPreload\.enable\(\)',
                           'self.registration.navigationPreload.disable()', 'disable root navigation preload')
    # Activate routing without reloading clients. Keep active runtimes and one
    # previous offline bundle, rather than accumulating every release forever.
    worker = _replace_once(worker,
                           r'cache\.addAll\(CACHED_FILES\)\)\);',
                           'cache.addAll(CACHED_FILES)).then(() => self.skipWaiting()));',
                           'activate next-navigation update')
    worker = _replace_once(worker,
                           r"event\.waitUntil\(caches\.keys\(\)\.then\(\n\t\tfunction \(keys\) \{.*?\n\t\t\}\n\t\)",
                           'event.waitUntil((async () => {\n'
                           '\t\tconst keys = await caches.keys();\n'
                           '\t\tconst previous = keys.filter(key => key.startsWith(CACHE_PREFIX)\n'
                           '\t\t\t&& /^game-[0-9a-f]{64}$/.test(key.slice(CACHE_PREFIX.length)) && key !== CACHE_NAME);\n'
                           '\t\tconst keep = new Set([CACHE_NAME]);\n'
                           '\t\tif (previous.length) keep.add(previous[previous.length - 1]);\n'
                           '\t\tfor (const client of await self.clients.matchAll({ type: "window", includeUncontrolled: true })) {\n'
                           '\t\t\tconst match = new URL(client.url).pathname.match(/\\/(game-[0-9a-f]{64})\\//);\n'
                           '\t\t\tif (match) keep.add(CACHE_PREFIX + match[1]);\n'
                           '\t\t}\n'
                           '\t\tawait Promise.all(previous.filter(key => !keep.has(key)).map(key => caches.delete(key)));\n'
                           '\t})()', 'retain active and previous runtime caches')
    worker = _replace_once(worker,
                           r"\t\tconst referrer = event\.request\.referrer \|\| '';.*?\n\t\tconst isCacheable = [^\n]*;",
                           "\t\tconst base = self.registration.scope;\n"
                           "\t\tconst local = url.startsWith(base) ? url.slice(base.length).split('?')[0] : '';\n"
                           "\t\tconst legacy = /^(game-[0-9a-f]{64})\\/(.+)$/.exec(local);\n"
                           "\t\tif (legacy && legacy[1] !== CACHE_VERSION) {\n"
                           "\t\t\tif (isNavigate && legacy[2] === 'index.html') {\n"
                           "\t\t\t\tconst launch = new URL('index.html', base);\n"
                           "\t\t\t\tlaunch.search = new URL(url).search;\n"
                           "\t\t\t\tevent.respondWith((async () => {\n"
                           "\t\t\t\t\ttry {\n"
                           "\t\t\t\t\t\tconst response = await fetch(launch.href);\n"
                           "\t\t\t\t\t\tif (response.ok) return ensureCrossOriginIsolationHeaders(response);\n"
                           "\t\t\t\t\t} catch (_) { /* Keep the previous bundle usable offline. */ }\n"
                           "\t\t\t\t\tconst cached = await caches.match(event.request, {\n"
                           "\t\t\t\t\t\tcacheName: CACHE_PREFIX + legacy[1], ignoreSearch: true,\n"
                           "\t\t\t\t\t});\n"
                           "\t\t\t\t\tconst offline = cached || await caches.match(OFFLINE_URL, { cacheName: CACHE_NAME });\n"
                           "\t\t\t\t\treturn offline ? ensureCrossOriginIsolationHeaders(offline) : Response.error();\n"
                           "\t\t\t\t})());\n"
                           "\t\t\t\treturn;\n"
                           "\t\t\t}\n"
                           "\t\t\tif (!isNavigate) {\n"
                           "\t\t\t\tevent.respondWith((async () => {\n"
                           "\t\t\t\t\tconst cached = await caches.match(event.request, { cacheName: CACHE_PREFIX + legacy[1] });\n"
                           "\t\t\t\t\treturn cached || fetch(event.request);\n"
                           "\t\t\t\t})());\n"
                           "\t\t\t\treturn;\n"
                           "\t\t\t}\n"
                           "\t\t}\n"
                           "\t\tconst isCacheable = FULL_CACHE.includes(local);\n"
                           "\t\t// Leave backend navigation and its redirects to the browser.\n"
                           "\t\tif (isNavigate && !isCacheable && !(url === base || url.startsWith(base + '?'))) return;",
                           'cache URL scope')
    # A fresh navigation should discover a newer bundle even while the previous
    # worker is active. Offline navigation still uses a coherent cached bundle.
    worker = _replace_once(worker,
                           r'\t\t\t\tif \(isNavigate\) \{.*?\n\t\t\t\t\}\n(?=\t\t\t\tlet cached)',
                           '\t\t\t\tif (isNavigate) {\n'
                           '\t\t\t\t\ttry {\n'
                           '\t\t\t\t\t\tconst response = await fetchAndCache(event, cache, isCacheable);\n'
                           '\t\t\t\t\t\tif (response.ok) return response;\n'
                           '\t\t\t\t\t} catch (_) { /* Use this bundle offline. */ }\n'
                           '\t\t\t\t\tconst page = await cache.match(event.request, { ignoreSearch: true })\n'
                           '\t\t\t\t\t\t|| await cache.match("index.html") || await cache.match(OFFLINE_URL);\n'
                           '\t\t\t\t\treturn page ? ensureCrossOriginIsolationHeaders(page) : Response.error();\n'
                           '\t\t\t\t}\n', 'navigation cache policy')
    # Keep the existing installed-app identity and launch URL at the root.
    manifest['id'] = './index.html'
    manifest['start_url'] = './index.html'
    manifest['scope'] = './'
    for icon in manifest.get('icons', []):
        icon['src'] = prefix + '/' + icon['src']
    title = re.search(r'<title>.*?</title>', html, re.DOTALL)
    bootstrap = ('<!doctype html>\n<html><head><meta charset="utf-8">\n'
                 '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                 + (title.group(0) if title else '<title>Game</title>') + '\n'
                 '<meta name="apple-mobile-web-app-capable" content="yes">\n'
                 '<link rel="manifest" href="index.manifest.json">\n'
                 '<link rel="apple-touch-icon" href="' + prefix + '/index.apple-touch-icon.png">\n'
                 '<script>const entry = new URL("/' + entrypoint + '", location.origin);'
                 'entry.search = location.search; entry.hash = location.hash;'
                 'location.replace(entry.href);</script></head>\n'
                 '<body><a href="/' + entrypoint + '">Open game</a></body></html>\n')
    metadata = None
    if 'build.json' in names:
        metadata = json.loads((directory / 'build.json').read_text(encoding='utf-8'))
        metadata['entrypoint'] = entrypoint
    bundle = directory / prefix
    bundle.mkdir()
    for path in sidecars:
        path.unlink()
    for path in paths:
        if path.name not in root_files:
            path.rename(bundle / path.name)
    (bundle / 'index.html').write_text(html, encoding='utf-8')
    (directory / 'index.html').write_text(bootstrap, encoding='utf-8')
    (directory / 'index.service.worker.js').write_text(worker, encoding='utf-8')
    (directory / 'index.manifest.json').write_text(json.dumps(manifest, separators=(',', ':')) + '\n', encoding='utf-8')
    if metadata is not None:
        (directory / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return entrypoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps({'entrypoint': stage_web_bundle(args.directory)}))


if __name__ == '__main__':
    main()
