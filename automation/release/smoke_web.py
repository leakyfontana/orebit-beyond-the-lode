#!/usr/bin/env python3
"""Launch the exact Web export to MainMenu in Chromium, retaining visual evidence."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
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
    with tempfile.TemporaryDirectory(prefix='orebit-web-smoke-') as temporary:
        if args.zip:
            with zipfile.ZipFile(args.zip) as archive:
                build = json.loads(archive.read('build.json'))
            inspect_archive(args.zip, args.sha, build['version'], Path(temporary))

            class Handler(SimpleHTTPRequestHandler):
                extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.wasm': 'application/wasm', '.json': 'application/json'}

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
                page = browser.new_page(viewport={'width': 1280, 'height': 720}, service_workers='block')
                page.on('pageerror', lambda error: errors.append(str(error)))

                def console(message):
                    if message.type == 'error':
                        errors.append(message.text)
                    if 'MOTHERLOAD_READY scene=MainMenu' in message.text:
                        ready.append(message.text)

                page.on('console', console)
                # Exercise the private MainMenu, not the startup mode chooser.
                navigation_url = url + '?mode=private'
                page.goto(navigation_url, wait_until='domcontentloaded', timeout=120000)
                page.wait_for_function('window.crossOriginIsolated === true', timeout=30000)
                page.wait_for_function('document.querySelector("canvas")?.width > 0', timeout=30000)
                deadline = time.monotonic() + 120
                while not ready and not errors and time.monotonic() < deadline:
                    page.wait_for_timeout(100)
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(args.screenshot))
                browser.close()
            if errors:
                raise RuntimeError('Web runtime errors: ' + '\n'.join(errors))
            if not ready:
                raise RuntimeError('Web export did not reach MainMenu readiness signal')
            print(json.dumps({'commit': args.sha, 'url': url, 'navigation_url': navigation_url, 'menu_ready': True, 'readiness': ready[-1], 'screenshot': str(args.screenshot)}))
        finally:
            if server:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()
