"""Isolated service behavior over HTTP; local Discord simulation is not an E2E claim."""
import argparse
import asyncio
import base64
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

import server


class ProviderTransport:
    """Route only Discord's two service calls to a real local HTTP simulator."""
    def __init__(self, base, **kwargs):
        self.base = base
        self.http = ClientSession(**kwargs)

    def post(self, url, **kwargs):
        if url != "https://discord.com/api/oauth2/token":
            raise AssertionError("Unexpected provider endpoint")
        return self.http.post(self.base + "/token", **kwargs)

    def get(self, url, **kwargs):
        if url != "https://discord.com/api/v10/users/@me":
            raise AssertionError("Unexpected provider endpoint")
        return self.http.get(self.base + "/identity", **kwargs)

    async def close(self):
        await self.http.close()


class AuthServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="orebit-auth-test-")
        self.db = Path(self.directory.name) / "state.sqlite3"
        self.now = 1900000000
        self.clock = patch.object(server, "time", SimpleNamespace(time=lambda: self.now, monotonic=time.monotonic))
        self.clock.start()
        self.environment = patch.dict(os.environ, {
            "OREBIT_PUBLIC_URL": "https://game.example/coop",
            "OREBIT_ALLOWED_ORIGINS": "https://game.example,https://preview.example,http://localhost:8060,http://127.0.0.1:8060,http://[::1]:8060,http://insecure.example",
            "OREBIT_DISCORD_CLIENT_ID": "test-client",
            "OREBIT_DISCORD_CLIENT_SECRET": "private-provider-secret",
            "OREBIT_WORLD_ID": "auth-test",
        })
        self.environment.start()
        self.codes = {}
        self.identities = {}
        self.provider_calls = 0
        provider = web.Application()
        provider.router.add_post("/token", self.provider_token)
        provider.router.add_get("/identity", self.provider_identity)
        self.provider = TestServer(provider)
        await self.provider.start_server()
        self.provider_base = str(self.provider.make_url("/")).rstrip("/")
        self.http = ClientSession()
        self.sockets = []
        await self.start()

    async def start(self):
        app = server.create_app(argparse.Namespace(db=str(self.db)))
        self.service = TestServer(app)
        with patch.object(server, "ClientSession", lambda **kwargs: ProviderTransport(self.provider_base, **kwargs)):
            await self.service.start_server()
        self.base = str(self.service.make_url("/")).rstrip("/")

    async def stop(self):
        for socket in self.sockets:
            await socket.close()
        self.sockets.clear()
        await self.service.close()

    async def asyncTearDown(self):
        await self.stop()
        await self.http.close()
        await self.provider.close()
        self.environment.stop()
        self.clock.stop()
        self.directory.cleanup()

    async def provider_token(self, request):
        self.provider_calls += 1
        data = await request.post()
        authorization = self.codes.pop(data.get("code"), None)
        if authorization is None:
            return web.json_response({"error": "invalid_grant"}, status=400)
        if authorization.get("unavailable"):
            return web.json_response({"error": "temporarily_unavailable"}, status=503)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(data.get("code_verifier", "").encode()).digest()).decode().rstrip("=")
        if (challenge != authorization["challenge"] or data.get("grant_type") != "authorization_code"
                or data.get("redirect_uri") != "https://game.example/coop/auth/discord/callback"
                or data.get("client_id") != "test-client" or data.get("client_secret") != "private-provider-secret"):
            return web.json_response({"error": "invalid_grant"}, status=400)
        access = "simulated-provider-access-" + str(self.provider_calls)
        self.identities[access] = authorization["identity"]
        return web.json_response({"access_token": access, "token_type": "Bearer"})

    async def provider_identity(self, request):
        identity = self.identities.get(request.headers.get("Authorization", "").removeprefix("Bearer "))
        if identity is None:
            return web.json_response({"error": "invalid_token"}, status=401)
        return web.json_response(identity)

    async def json_request(self, method, path, **kwargs):
        async with self.http.request(method, self.base + path, **kwargs) as response:
            return response, await response.json()

    async def start_flow(self, return_url=None):
        body = {} if return_url is None else {"return_url": return_url}
        response, flow = await self.json_request("POST", "/api/auth/discord/start", json=body)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        params = parse_qs(urlsplit(flow["authorization_url"]).query)
        self.assertEqual(params["prompt"], ["none"])
        self.assertEqual(params["scope"], ["identify"])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(flow["expires_at"], self.now + server.OAUTH_LIFETIME)
        return flow, params

    def provider_code(self, params, identity=None, unavailable=False):
        code = "provider-code-" + str(len(self.codes) + self.provider_calls)
        self.codes[code] = {"challenge": params["code_challenge"][0], "identity": identity or {"id": "12345", "global_name": "Discord Miner"}, "unavailable": unavailable}
        return code

    async def callback(self, params, **query):
        query = {"state": params["state"][0], **query}
        async with self.http.get(self.base + "/auth/discord/callback?" + urlencode(query), allow_redirects=False) as response:
            return response, await response.text()

    async def poll(self, flow):
        return await self.json_request("POST", "/api/auth/discord/poll", json={"poll_token": flow["poll_token"]})

    async def join(self, token=""):
        socket = await self.http.ws_connect(self.base + "/api/ws")
        self.sockets.append(socket)
        await socket.send_json({"type": "join", "token": token})
        return socket, await socket.receive_json(timeout=5)

    async def test_trusted_game_return_validation(self):
        accepted = [
            "https://game.example/", "https://game.example/game-abc/index.html?quality=high&world=public",
            "https://preview.example/game/", "http://localhost:8060/index.html",
            "http://127.0.0.1:8060/index.htm", "http://[::1]:8060/",
        ]
        for url in accepted:
            with self.subTest(url=url):
                await self.start_flow(url)
        invalid = [
            "//game.example/", "/index.html", "https://attacker.example/", "http://game.example/",
            "http://insecure.example/", "https://game.example.attacker.example/",
            "https://game.example@attacker.example/", "https://user:password@game.example/",
            "https://game.example/#fragment", "https://game.example/#", "https://game.example/\\evil/",
            "https://game.example/\nindex.html", "https://game.example/./index.html", "https://game.example/../index.html",
            "https://game.example/%2e%2e/index.html", "https://game.example/%252fapi/index.html",
            "https://game.example/api/", "https://game.example/coop/auth/discord/callback",
            "https://game.example/auth/", "https://game.example/oauth/", "https://game.example/healthz/",
            "https://game.example/redirect?to=https://attacker.example", "https://game.example//index.html",
            "https://game.example/?code=private", "https://game.example/?st%61te=private",
            "https://game.example/?POLL_TOKEN=private", "https://game.example/?access_token=private",
            "https://game.example/?session_token=private", "https://game.example/?" + "x" * 2048,
            "org.motherloadrecoded.game://auth/discord?x=1", "org.motherloadrecoded.game://auth/discord#done",
            "org.motherloadrecoded.game://auth/discord/", "org.motherloadrecoded.game://auth:123/discord",
            "org.motherloadrecoded.game://user@auth/discord", "other-app://auth/discord",
            "", 42, ["https://game.example/"],
        ]
        for index, url in enumerate(invalid):
            with self.subTest(url=url):
                response, result = await self.json_request("POST", "/api/auth/discord/start", json={"return_url": url}, headers={"X-Real-IP": "192.0.2." + str(index + 1)})
                self.assertEqual(response.status, 400)
                self.assertEqual(result["error"], "invalid_return_url")
                if str(url):
                    self.assertNotIn(str(url), result["message"])
        response, _ = await self.json_request("POST", "/api/auth/discord/start", json={}, headers={"Origin": "https://attacker.example"})
        self.assertEqual(response.status, 403)

    async def test_state_bound_success_single_use_poll_and_account_progress(self):
        original = "https://game.example/game-abc/index.html?quality=high&orebit_auth=failed"
        flow, params = await self.start_flow(original)
        other, other_params = await self.start_flow("https://preview.example/game/")
        _, pending = await self.poll(flow)
        self.assertEqual(pending, {"status": "pending"})
        code = self.provider_code(params)
        response, _ = await self.callback(params, code=code, return_url="https://attacker.example/")
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "https://game.example/game-abc/index.html?quality=high&orebit_auth=complete")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        for secret in (code, params["state"][0], flow["poll_token"], "private-provider-secret"):
            self.assertNotIn(secret, response.headers["Location"])
        response, replay_page = await self.callback(params, code=code)
        self.assertEqual(response.status, 400)
        self.assertNotIn("Location", response.headers)
        self.assertNotIn(code, replay_page)
        self.assertEqual(self.provider_calls, 1)
        _, untouched = await self.poll(other)
        self.assertEqual(untouched, {"status": "pending"})
        response, account = await self.poll(flow)
        self.assertEqual(response.status, 200)
        self.assertEqual(account["status"], "complete")
        self.assertEqual(account["user"]["name"], "Discord Miner")
        response, replay = await self.poll(flow)
        self.assertEqual(response.status, 401)
        self.assertEqual(replay["error"], "expired_completion")
        socket, joined = await self.join(account["token"])
        self.assertEqual(joined["type"], "joined")
        await socket.send_json({"type": "state", "state": {"player_money": 71}, "state_revision": 0})
        await socket.send_json({"type": "ping"})
        self.assertEqual((await socket.receive_json(timeout=5))["type"], "pong")
        await self.stop()
        await self.start()
        repeat, repeat_params = await self.start_flow("https://game.example/")
        await self.callback(repeat_params, code=self.provider_code(repeat_params))
        _, signed_in = await self.poll(repeat)
        self.assertEqual(signed_in["user"]["id"], account["user"]["id"])
        _, restored = await self.join(signed_in["token"])
        self.assertEqual(restored["state"]["player_money"], 71)
        self.assertEqual(restored["seed"], joined["seed"])

    async def test_cancel_failure_and_unknown_state_never_redirect_elsewhere(self):
        for failure in ("cancel", "provider"):
            with self.subTest(failure=failure):
                flow, params = await self.start_flow("https://preview.example/game/?mode=touch")
                query = {"error": "access_denied", "error_description": "private-provider-description"} if failure == "cancel" else {"code": self.provider_code(params, unavailable=True)}
                response, _ = await self.callback(params, **query)
                self.assertEqual(response.status, 303)
                self.assertEqual(response.headers["Location"], "https://preview.example/game/?mode=touch&orebit_auth=failed")
                _, result = await self.poll(flow)
                self.assertEqual(result["status"], "failed")
                self.assertNotIn("private-provider", result["message"])
                response, _ = await self.poll(flow)
                self.assertEqual(response.status, 401)
                response, _ = await self.callback(params, **query)
                self.assertEqual(response.status, 400)
                self.assertNotIn("Location", response.headers)
        response, page = await self.callback({"state": ["unknown-state-that-is-long-enough"]}, code="private-code", return_url="https://attacker.example/")
        self.assertEqual(response.status, 400)
        self.assertNotIn("Location", response.headers)
        self.assertNotIn("private-code", page)

    async def test_expired_callback_and_completion_are_rejected(self):
        flow, params = await self.start_flow("https://game.example/")
        self.now += server.OAUTH_LIFETIME
        response, _ = await self.callback(params, code=self.provider_code(params))
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "https://game.example/?orebit_auth=failed")
        self.assertEqual(self.provider_calls, 0)
        response, result = await self.poll(flow)
        self.assertEqual(response.status, 401)
        self.assertEqual(result["error"], "expired_completion")
        response, _ = await self.callback(params, code="already-expired-code")
        self.assertEqual(response.status, 400)
        self.assertNotIn("Location", response.headers)

    async def test_completed_flow_expires_without_issuing_a_session(self):
        flow, params = await self.start_flow("https://game.example/")
        response, _ = await self.callback(params, code=self.provider_code(params))
        self.assertEqual(response.status, 303)
        self.now = flow["expires_at"]
        response, result = await self.poll(flow)
        self.assertEqual(response.status, 401)
        self.assertEqual(result["error"], "expired_completion")
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tokens").fetchone()[0], 0)

    async def test_android_fixed_return_is_bound_to_state_and_contains_no_credentials(self):
        destination = "org.motherloadrecoded.game://auth/discord"
        for complete in (True, False):
            with self.subTest(complete=complete):
                flow, params = await self.start_flow(destination)
                query = {"code": self.provider_code(params)} if complete else {"error": "access_denied"}
                response, _ = await self.callback(params, **query)
                self.assertEqual(response.status, 303)
                marker = "complete" if complete else "failed"
                self.assertEqual(response.headers["Location"], destination + "?orebit_auth=" + marker)
                _, result = await self.poll(flow)
                self.assertEqual(result["status"], marker)

    async def test_native_callback_page_and_bodyless_start(self):
        response, flow = await self.json_request("POST", "/api/auth/discord/start")
        self.assertEqual(response.status, 200)
        params = parse_qs(urlsplit(flow["authorization_url"]).query)
        code = self.provider_code(params)
        response, page = await self.callback(params, code=code)
        self.assertEqual(response.status, 200)
        self.assertNotIn("Location", response.headers)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        for secret in (code, params["state"][0], flow["poll_token"]):
            self.assertNotIn(secret, page)
        _, result = await self.poll(flow)
        self.assertEqual(result["status"], "complete")
        failed, failed_params = await self.start_flow()
        response, page = await self.callback(failed_params, error="access_denied")
        self.assertEqual(response.status, 400)
        _, result = await self.poll(failed)
        self.assertEqual(result["status"], "failed")

    async def test_session_lookup_logout_expiry_and_native_progress(self):
        credentials = {"username": "Native_Miner", "password": "paste-friendly-long-password"}
        response, account = await self.json_request("POST", "/api/auth/signup", json=credentials)
        self.assertEqual(response.status, 200)
        headers = {"Authorization": "Bearer " + account["token"]}
        for _ in range(2):
            response, session = await self.json_request("GET", "/api/auth/session", headers=headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(session, {"expires_at": account["expires_at"], "user": account["user"]})
            self.assertNotIn("token", session)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.now += 1
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*),MAX(expires_at) FROM tokens").fetchone(), (1, account["expires_at"]))
        for authorization in (None, "Basic abc", "Bearer short", "Bearer " + "x" * 43):
            response, result = await self.json_request("GET", "/api/auth/session", headers={} if authorization is None else {"Authorization": authorization})
            self.assertEqual(response.status, 401)
            self.assertEqual(result["error"], "invalid_token")
        socket, joined = await self.join(account["token"])
        await socket.send_json({"type": "state", "state": {"player_money": 99}, "state_revision": 0})
        await socket.send_json({"type": "ping"})
        self.assertEqual((await socket.receive_json(timeout=5))["type"], "pong")
        logout, _ = await asyncio.gather(
            self.json_request("POST", "/api/auth/logout", headers=headers),
            socket.receive(timeout=5),
        )
        response, _ = logout
        self.assertEqual(response.status, 200)
        self.assertTrue(socket.closed)
        self.assertEqual(socket.close_code, 1008)
        response, _ = await self.json_request("GET", "/api/auth/session", headers=headers)
        self.assertEqual(response.status, 401)
        response, login = await self.json_request("POST", "/api/auth/login", json={**credentials, "username": "native_miner"})
        self.assertEqual(response.status, 200)
        self.assertEqual(login["user"], account["user"])
        _, restored = await self.join(login["token"])
        self.assertEqual(restored["state"]["player_money"], 99)
        self.assertEqual(restored["seed"], joined["seed"])
        _, anonymous = await self.join()
        self.assertEqual(anonymous["state"], {})
        self.now = login["expires_at"]
        response, result = await self.json_request("GET", "/api/auth/session", headers={"Authorization": "Bearer " + login["token"]})
        self.assertEqual(response.status, 401)
        self.assertEqual(result["error"], "invalid_token")
        _, expired_join = await self.join(login["token"])
        self.assertEqual(expired_join["code"], "invalid_token")
        response, _ = await self.json_request("POST", "/api/auth/logout", headers={"Authorization": "Bearer " + login["token"]})
        self.assertEqual(response.status, 401)

    async def test_legacy_database_migrates_without_losing_pending_flow_or_account(self):
        credentials = {"username": "Legacy_Miner", "password": "legacy-password-long"}
        _, account = await self.json_request("POST", "/api/auth/signup", json=credentials)
        socket, joined = await self.join(account["token"])
        await socket.send_json({"type": "state", "state": {"player_money": 123}, "state_revision": 0})
        await socket.send_json({"type": "ping"})
        self.assertEqual((await socket.receive_json(timeout=5))["type"], "pong")
        flow, params = await self.start_flow()
        await self.stop()
        # Removing the additive column reproduces the released OAuth table format.
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("ALTER TABLE oauth DROP COLUMN return_url")
            db.commit()
        await self.start()
        response, session = await self.json_request("GET", "/api/auth/session", headers={"Authorization": "Bearer " + account["token"]})
        self.assertEqual(response.status, 200)
        self.assertEqual(session["user"], account["user"])
        _, restored = await self.join(account["token"])
        self.assertEqual(restored["state"]["player_money"], 123)
        self.assertEqual(restored["seed"], joined["seed"])
        _, pending = await self.poll(flow)
        self.assertEqual(pending, {"status": "pending"})
        response, _ = await self.callback(params, error="access_denied")
        self.assertEqual(response.status, 400)
        self.assertNotIn("Location", response.headers)
        _, failed = await self.poll(flow)
        self.assertEqual(failed["status"], "failed")
        await self.start_flow("https://game.example/")


if __name__ == "__main__":
    unittest.main()
