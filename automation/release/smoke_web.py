#!/usr/bin/env python3
"""Launch the exact Web export to MainMenu in Chromium or WebKit, retaining visual evidence."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from urllib.parse import urlencode, urlsplit
import threading
import time
import urllib.request
import zipfile

from remote_web_release import inspect_archive


def verify_previous_navigation(browser, url, previous, entrypoint, serve, screenshot):
    """A retired immutable launch migrates only when its owner navigates."""
    context = browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='allow')
    page = context.new_page()
    ready = []
    page.on('console', lambda message: ready.append(message.text)
            if 'MOTHERLOAD_READY scene=MainMenu' in message.text else None)
    try:
        serve(previous)
        page.goto(url + '?coop-url=' + url.rstrip('/'), wait_until='domcontentloaded', timeout=120000)
        page.wait_for_function('document.querySelector("canvas")?.width > 0', timeout=30000)
        page.evaluate('navigator.serviceWorker.ready')
        ready.clear()
        page.reload(wait_until='domcontentloaded', timeout=120000)
        page.wait_for_function('navigator.serviceWorker.controller !== null', timeout=30000)
        old_url = page.evaluate("location.hash = 'migration'; location.href")
        deadline = time.monotonic() + 120
        while not ready and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        if not ready:
            raise RuntimeError('Previous Web runtime did not reach MainMenu')
        page.evaluate("""async () => {
            window.__migrationLive = 'running';
            localStorage.setItem('orebit-update-smoke', 'account-sentinel');
            await new Promise((resolve, reject) => {
                const request = indexedDB.open('orebit-update-smoke', 1);
                request.onupgradeneeded = () => request.result.createObjectStore('saves');
                request.onerror = () => reject(request.error);
                request.onsuccess = () => {
                    const db = request.result;
                    const tx = db.transaction('saves', 'readwrite');
                    tx.objectStore('saves').put('save-and-recording-sentinel', 'fixture');
                    tx.oncomplete = () => { db.close(); resolve(); };
                    tx.onerror = () => reject(tx.error);
                };
            });
        }""")
        old_asset = page.evaluate("fetch('index.js').then(r => r.text())")
        retention = page.evaluate("""async () => {
            const version = location.pathname.split('/')[1];
            const active = (await caches.keys()).find(name => name.endsWith(version));
            if (!active) throw new Error('Previous runtime cache is missing');
            const prefix = active.slice(0, -version.length);
            const retired = prefix + 'game-' + 'e'.repeat(64);
            const recent = prefix + 'game-' + 'f'.repeat(64);
            // Model inactive releases newer than the still-open old game.
            for (const name of [retired, recent, 'orebit-unrelated-smoke']) {
                const cache = await caches.open(name);
                await cache.put('/cache-retention-sentinel', new Response('preserved'));
            }
            return { active, retired, recent };
        }""")
        serve(None)
        page.evaluate("""async () => {
            const registration = await navigator.serviceWorker.getRegistration();
            await registration.update();
            const worker = registration.installing || registration.waiting || registration.active;
            if (worker.state === 'activated') return;
            await Promise.race([
                new Promise(resolve => worker.addEventListener('statechange', () => {
                    if (worker.state === 'activated') resolve();
                })),
                new Promise((_, reject) => setTimeout(() => reject(new Error('New worker did not activate')), 30000)),
            ]);
        }""")
        if page.url != old_url or page.evaluate('window.__migrationLive') != 'running':
            raise RuntimeError('Web update navigated a running previous game')
        if page.evaluate("fetch('index.js').then(r => r.text())") != old_asset:
            raise RuntimeError('Web update lost an open previous game runtime asset')
        retained = page.evaluate("""async expected => {
            const names = await caches.keys();
            const unrelated = await caches.match('/cache-retention-sentinel',
                { cacheName: 'orebit-unrelated-smoke' });
            return names.includes(expected.active) && names.includes(expected.recent)
                && !names.includes(expected.retired) && await unrelated?.text() === 'preserved';
        }""", retention)
        if not retained:
            raise RuntimeError('Web update lost an active/offline cache, retained obsolete releases, or cleared unrelated storage')
        # Break the owned origin's sockets: browser offline emulation can leave
        # service-worker network requests online.
        serve(False)
        ready.clear()
        page.reload(wait_until='domcontentloaded', timeout=120000)
        deadline = time.monotonic() + 120
        while not ready and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        if not ready or page.url != old_url:
            raise RuntimeError('Web update lost the coherent previous runtime offline: expected %s, got %s; ready=%r'
                               % (old_url, page.url, bool(ready)))
        serve(None)
        ready.clear()
        page.reload(wait_until='domcontentloaded', timeout=120000)
        page.wait_for_url(lambda actual: urlsplit(actual).path == '/' + entrypoint,
                          wait_until='domcontentloaded', timeout=30000)
        deadline = time.monotonic() + 120
        while not ready and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        if not ready:
            raise RuntimeError('Migrated Web runtime did not reach MainMenu')
        if urlsplit(page.url).fragment != 'migration' or 'coop-url=' not in urlsplit(page.url).query:
            raise RuntimeError('Web migration lost launch query or fragment')
        storage = page.evaluate("""async () => {
            const value = await new Promise((resolve, reject) => {
                const request = indexedDB.open('orebit-update-smoke', 1);
                request.onerror = () => reject(request.error);
                request.onsuccess = () => {
                    const db = request.result;
                    const read = db.transaction('saves').objectStore('saves').get('fixture');
                    read.onsuccess = () => { db.close(); resolve(read.result); };
                    read.onerror = () => reject(read.error);
                };
            });
            return [localStorage.getItem('orebit-update-smoke'), value];
        }""")
        if storage != ['account-sentinel', 'save-and-recording-sentinel']:
            raise RuntimeError('Web migration changed persistent browser data')
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot))
        return {'previous_runtime': True, 'live_game_untouched': True,
                'previous_runtime_offline': True, 'next_navigation_current': True,
                'persistent_data_preserved': True, 'bounded_runtime_caches': True,
                'screenshot': str(screenshot)}
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--zip', type=Path)
    source.add_argument('--url')
    parser.add_argument('--previous-zip', type=Path,
                        help='Also exercise a retired Web release updating on the next navigation (requires --zip)')
    parser.add_argument('--sha', required=True)
    parser.add_argument('--screenshot', type=Path, default=Path('dist/web-menu.png'))
    parser.add_argument('--browser', choices=('chromium', 'webkit'), default='chromium')
    args = parser.parse_args()
    if args.previous_zip and not args.zip:
        parser.error('--previous-zip requires --zip')
    from playwright.sync_api import sync_playwright

    server = None
    callback_requests = []
    callback_lock = threading.Lock()
    with tempfile.TemporaryDirectory(prefix='orebit-web-smoke-') as temporary:
        if args.zip:
            with zipfile.ZipFile(args.zip) as archive:
                build = json.loads(archive.read('build.json'))
            inspect_archive(args.zip, args.sha, build['version'], Path(temporary))
            previous = None
            if args.previous_zip:
                previous = Path(temporary) / 'previous-release'
                with zipfile.ZipFile(args.previous_zip) as archive:
                    previous_build = json.loads(archive.read('build.json'))
                inspect_archive(args.previous_zip, previous_build['commit'], previous_build['version'], previous)
            served = {'directory': temporary}

            class Handler(SimpleHTTPRequestHandler):
                extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.wasm': 'application/wasm', '.json': 'application/json'}
                def translate_path(self, path):
                    self.directory = str(served['directory'])
                    return super().translate_path(path)

                def do_GET(self):
                    if served['directory'] is False:
                        self.close_connection = True
                        return
                    if urlsplit(self.path).path == '/api/fuel-price':
                        # A deterministic menu-smoke fixture, not live AAA verification.
                        body = json.dumps({'price_per_gallon': 4.0,
                                           'date': time.strftime('%Y-%m-%d', time.gmtime()),
                                           'valid_until': int(time.time()) + 3600,
                                           'source': 'aaa'}).encode()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    # Single-use backend redirect; no simulated Discord authorization.
                    if urlsplit(self.path).path == '/coop/auth/discord/callback':
                        with callback_lock:
                            consumed = bool(callback_requests)
                            callback_requests.append(self.headers.get('Service-Worker-Navigation-Preload'))
                        if consumed:
                            self.send_error(400, 'Callback already consumed')
                            return
                        self.send_response(303)
                        self.send_header('Location', '/?' + urlencode({
                            'mode': 'private', 'pwa_callback': 'complete',
                            'coop-url': 'http://127.0.0.1:' + str(self.server.server_port)}))
                        self.end_headers()
                        return
                    super().do_GET()

                def end_headers(self):
                    self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
                    self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
                    self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
                    self.send_header('Cache-Control', 'no-store')
                    super().end_headers()

                def log_message(self, *arguments):
                    pass

            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=temporary))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = 'http://127.0.0.1:' + str(server.server_port) + '/'
        else:
            url = args.url.rstrip('/') + '/'
        navigation_url = url + '?' + urlencode({'coop-url': url.rstrip('/')}) if args.zip else url
        try:
            request = urllib.request.Request(url + 'build.json', headers={'User-Agent': 'OrebitReleaseVerifier/1.0'})
            with urllib.request.urlopen(request, timeout=30) as response:
                build = json.load(response)
            if build.get('commit') != args.sha:
                raise ValueError('Served Web build commit does not match requested source')
            errors = []
            ready = []
            with sync_playwright() as playwright:
                browser = getattr(playwright, args.browser).launch()
                migration = None
                if args.zip and args.previous_zip:
                    def serve(directory):
                        served['directory'] = directory if directory is not None else temporary
                    migration = verify_previous_navigation(
                        browser, url, previous, build['entrypoint'], serve,
                        args.screenshot.with_name(args.screenshot.stem + '-migration' + args.screenshot.suffix))
                page = browser.new_page(viewport={'width': 1280, 'height': 720}, service_workers='allow')
                page.on('pageerror', lambda error: errors.append(str(error)))

                def console(message):
                    if message.type == 'error':
                        errors.append(message.text)
                    if 'MOTHERLOAD_READY scene=MainMenu' in message.text:
                        ready.append(message.text)

                def wait_for_menu():
                    deadline = time.monotonic() + 120
                    while not ready and not errors and time.monotonic() < deadline:
                        page.wait_for_timeout(100)
                    if ready and not errors and args.zip:
                        # The engine starts pricing after menu readiness; await its body
                        # before intentionally destroying this document with navigation.
                        page.wait_for_function(
                            "performance.getEntriesByType('resource').some(entry => "
                            "new URL(entry.name).pathname === '/api/fuel-price' && entry.responseEnd > 0)",
                            timeout=30000)
                    if errors:
                        raise RuntimeError('Web runtime errors: ' + '\n'.join(errors))
                    if not ready:
                        raise RuntimeError('Web export did not reach MainMenu readiness signal')

                page.on('console', console)
                page.goto(navigation_url, wait_until='domcontentloaded', timeout=120000)
                page.wait_for_function('window.crossOriginIsolated === true', timeout=30000)
                page.wait_for_function('document.querySelector("canvas")?.width > 0', timeout=30000)
                wait_for_menu()
                callback_redirect = False
                if args.zip:
                    page.evaluate('navigator.serviceWorker.ready')
                    ready.clear()
                    page.reload(wait_until='domcontentloaded', timeout=120000)
                    page.wait_for_function('navigator.serviceWorker.controller !== null', timeout=30000)
                    wait_for_menu()
                    ready.clear()
                    response = page.goto(url + 'coop/auth/discord/callback?check=pwa', wait_until='domcontentloaded', timeout=120000)
                    if response is None or response.status != 200:
                        raise RuntimeError('Single-use callback failed: HTTP %s; preload requests=%r' % (response.status if response else None, callback_requests))
                    page.wait_for_function("new URLSearchParams(location.search).get('pwa_callback') === 'complete'", timeout=30000)
                    wait_for_menu()
                    if len(callback_requests) != 1:
                        raise RuntimeError('Single-use callback was fetched more than once: %r' % callback_requests)
                    callback_redirect = True
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(args.screenshot))
                browser.close()
            print(json.dumps({'commit': args.sha, 'browser': args.browser, 'url': url, 'menu_ready': True, 'pwa_callback_redirect': callback_redirect, 'migration': migration, 'readiness': ready[-1], 'screenshot': str(args.screenshot)}))
        finally:
            if server:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()
