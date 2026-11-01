#!/usr/bin/env python3
"""Launch the exact Web export to MainMenu in Chromium, retaining visual evidence."""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--zip', type=Path)
    source.add_argument('--url')
    parser.add_argument('--sha', required=True)
    parser.add_argument('--screenshot', type=Path, default=Path('dist/web-menu.png'))
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    server = None
    callback_requests = []
    callback_lock = threading.Lock()
    with tempfile.TemporaryDirectory(prefix='orebit-web-smoke-') as temporary:
        if args.zip:
            with zipfile.ZipFile(args.zip) as archive:
                build = json.loads(archive.read('build.json'))
            inspect_archive(args.zip, args.sha, build['version'], Path(temporary))

            class Handler(SimpleHTTPRequestHandler):
                extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.wasm': 'application/wasm', '.json': 'application/json'}

                def do_GET(self):
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
                browser = playwright.chromium.launch()
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
            print(json.dumps({'commit': args.sha, 'url': url, 'menu_ready': True, 'pwa_callback_redirect': callback_redirect, 'readiness': ready[-1], 'screenshot': str(args.screenshot)}))
        finally:
            if server:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()
