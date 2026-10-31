#!/usr/bin/env python3
"""Single-process Orebit co-op HTTP/WebSocket service.

Run: python3 server.py --host 127.0.0.1 --port 8765 --db /var/lib/orebit-coop/coop.sqlite3
TLS terminates at the trusted reverse proxy. Do not run multiple workers: live
membership is intentionally owned by this process. All durable mutations use
SQLite transactions; shutdown closes sockets and all acknowledged state is saved.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from collections import OrderedDict
from contextlib import ExitStack
import copy
from dataclasses import dataclass, field
import hashlib
import html
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlencode, urlsplit

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from terrain import HEIGHT, WIDTH, WEIGHTS, award, generate, tile_name
from telemetry import configure_logging, event as log_event, log_context

TOKEN_LIFETIME = 30 * 86400
OAUTH_LIFETIME = 600
MAX_BODY = 32768
MAX_STATE = 16384
USERNAME = re.compile(r"[A-Za-z0-9_-]{3,24}\Z")
STATE_KEYS = {
    "player_money", "current_upgrades", "player_items", "player_cargo",
    "transmissions", "player_hp", "player_fuel", "x", "y", "facing", "alive",
}
ITEMS = {"Reserve Fuel Tank", "Hull Repair Nanobots", "Dynamite", "Plastic Explosives", "Quantum Teleporter", "Matter Transmitter"}
UPGRADES = {"Drill", "Hull", "Engine", "Fuel", "Radiator", "Cargo"}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def encode(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


async def provider_json(response):
    try:
        await response.content.readexactly(MAX_BODY + 1)
    except asyncio.IncompleteReadError as completed:
        value = json.loads(completed.partial)
        if not isinstance(value, dict):
            raise ValueError("Invalid provider response")
        return value
    raise ValueError("Provider response exceeded size limit")


class APIError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


class Store:
    def __init__(self, path: str):
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(str(target), check_same_thread=False, timeout=10)
        os.chmod(target, 0o600)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.connection.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                display_name TEXT NOT NULL, password_hash TEXT,
                discord_id TEXT UNIQUE, created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tokens (
                hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS token_user ON tokens(user_id);
            CREATE TABLE IF NOT EXISTS oauth (
                state_hash TEXT PRIMARY KEY, poll_hash TEXT NOT NULL UNIQUE,
                verifier TEXT NOT NULL, expires_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', user_id INTEGER REFERENCES users(id),
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS worlds (
                id TEXT PRIMARY KEY, seed INTEGER NOT NULL, created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS player_states (
                world_id TEXT NOT NULL REFERENCES worlds(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL, PRIMARY KEY(world_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS excavations (
                world_id TEXT NOT NULL REFERENCES worlds(id),
                x INTEGER NOT NULL CHECK(x>=0 AND x<36),
                y INTEGER NOT NULL CHECK(y>=0 AND y<600),
                user_id INTEGER REFERENCES users(id), created_at INTEGER NOT NULL,
                PRIMARY KEY(world_id,x,y)
            );
        """)
        self.connection.commit()

    def _run(self, fn, *args):
        with self.lock, self.connection:
            return fn(self.connection, *args)

    async def run(self, fn, *args):
        return await asyncio.to_thread(self._run, fn, *args)

    async def close(self):
        await asyncio.to_thread(self.connection.close)


@dataclass(eq=False)
class Player:
    socket: web.WebSocketResponse
    player_id: str
    name: str
    user_id: int | None
    token_hash: str | None
    token_expires: int
    state: dict
    revision: int
    messages: float = 250.0
    refilled_at: float = field(default_factory=time.monotonic)
    requests: OrderedDict = field(default_factory=OrderedDict)
    session_id: str = ""
    received: int = 0
    sent: int = 0
    state_updates: int = 0
    mine_accepted: int = 0
    mine_rejected: int = 0
    mine_duplicates: int = 0

    def public(self):
        return {"player_id": self.player_id, "name": self.name, "state": self.state}


class Service:
    def __init__(self, args):
        self.store = Store(args.db)
        self.world_id = os.environ.get("OREBIT_WORLD_ID", "public")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", self.world_id):
            raise ValueError("OREBIT_WORLD_ID must be 1-32 ASCII letters, digits, underscore or hyphen")
        self.public_url = os.environ.get("OREBIT_PUBLIC_URL", "http://127.0.0.1:8765").rstrip("/")
        parsed = urlsplit(self.public_url)
        if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("OREBIT_PUBLIC_URL must be the externally accessible service base URL")
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Public service URLs must use HTTPS")
        self.callback = self.public_url + "/auth/discord/callback"
        default_origin = f"{parsed.scheme}://{parsed.netloc}"
        self.origins = set(filter(None, (s.strip() for s in os.environ.get("OREBIT_ALLOWED_ORIGINS", default_origin).split(","))))
        self.client_id = os.environ.get("OREBIT_DISCORD_CLIENT_ID", "")
        self.client_secret = os.environ.get("OREBIT_DISCORD_CLIENT_SECRET", "")
        self.hash_password = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
        self.password_slots = asyncio.Semaphore(4)
        self.dummy_hash = self.hash_password.hash(secrets.token_urlsafe(32))
        self.members: dict[str, Player] = {}
        self.joining = 0
        self.world_lock = asyncio.Lock()
        self.rate_limits = OrderedDict()
        self.seed = 0
        self.terrain = []
        self.excavated = set()
        self.http: ClientSession | None = None

    async def startup(self, app):
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: log_event("asyncio_error", level=logging.ERROR, error=context.get("exception"))
        )
        def load(db):
            now = int(time.time())
            db.execute("DELETE FROM tokens WHERE expires_at<=?", (now,))
            db.execute("DELETE FROM oauth WHERE expires_at<=?", (now,))
            db.execute("INSERT OR IGNORE INTO worlds(id,seed,created_at) VALUES(?,?,?)", (self.world_id, secrets.randbelow(2147483646) + 1, now))
            seed = db.execute("SELECT seed FROM worlds WHERE id=?", (self.world_id,)).fetchone()[0]
            cells = {(r[0], r[1]) for r in db.execute("SELECT x,y FROM excavations WHERE world_id=?", (self.world_id,))}
            return seed, cells
        self.seed, self.excavated = await self.store.run(load)
        self.terrain = await asyncio.to_thread(generate, self.seed)
        self.http = ClientSession(timeout=ClientTimeout(total=20), raise_for_status=True)
        log_event("startup", world_id=self.world_id, members=len(self.members))

    async def shutdown(self, app):
        players = list(self.members.values())
        results = await asyncio.gather(*(p.socket.close(code=1001, message=b"Server shutting down; reconnect to resume") for p in players), return_exceptions=True)
        for player, result in zip(players, results):
            if isinstance(result, BaseException):
                log_event("session_error", level=logging.ERROR, error=result, world_id=self.world_id, request_id=player.session_id, session_id=player.session_id, player_id=player.player_id, user_id=player.user_id)

    async def cleanup(self, app):
        if self.http:
            await self.http.close()
        await self.store.close()
        log_event("shutdown", world_id=self.world_id, members=len(self.members))

    def rate_limit(self, request, bucket: str, count: int, seconds: int):
        # Reverse proxy must overwrite, rather than append untrusted forwarded IPs.
        peer = request.remote or "unknown"
        if peer in ("127.0.0.1", "::1"):
            peer = request.headers.get("X-Real-IP", peer)
        key = (bucket, peer)
        now = time.monotonic()
        started, used = self.rate_limits.pop(key, (now, 0))
        if now - started >= seconds:
            started, used = now, 0
        self.rate_limits[key] = (started, used + 1)
        while len(self.rate_limits) > 8192:
            self.rate_limits.popitem(last=False)
        if used >= count:
            raise APIError("rate_limited", "Too many requests. Please try again later.", 429)

    async def body(self, request):
        if request.content_type != "application/json":
            raise APIError("invalid_json", "Send an application/json object.")
        try:
            value = await request.json(loads=json.loads)
        except (ValueError, UnicodeError):
            raise APIError("invalid_json", "Request must contain valid JSON.")
        if not isinstance(value, dict):
            raise APIError("invalid_json", "Request must contain a JSON object.")
        return value

    def issue_token(self, db, user):
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        expires = now + TOKEN_LIFETIME
        db.execute("DELETE FROM tokens WHERE expires_at<=?", (now,))
        # Bound outstanding credentials per account without storing raw tokens.
        db.execute("DELETE FROM tokens WHERE hash IN (SELECT hash FROM tokens WHERE user_id=? ORDER BY created_at DESC LIMIT -1 OFFSET 7)", (user["id"],))
        db.execute("INSERT INTO tokens(hash,user_id,expires_at,created_at) VALUES(?,?,?,?)", (digest(token), user["id"], expires, now))
        return {"token": token, "expires_at": expires, "user": {"id": user["id"], "name": user["display_name"]}}

    async def native_auth(self, request):
        signup = request.match_info["action"] == "signup"
        self.rate_limit(request, "auth", 30, 600)
        if signup:
            self.rate_limit(request, "signup", 5, 3600)
        body = await self.body(request)
        username, password = body.get("username"), body.get("password")
        if not isinstance(username, str) or not USERNAME.fullmatch(username):
            raise APIError("invalid_username", "Username must be 3-24 letters, digits, underscores or hyphens.")
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise APIError("invalid_password", "Password must be 8-128 characters.")
        normalized = username.lower()
        async with self.password_slots:
            if signup:
                hashed = await asyncio.to_thread(self.hash_password.hash, password)
                def create(db):
                    try:
                        cursor = db.execute("INSERT INTO users(username,display_name,password_hash,created_at) VALUES(?,?,?,?)", (normalized, username, hashed, int(time.time())))
                    except sqlite3.IntegrityError:
                        raise APIError("username_taken", "That username is already registered.", 409)
                    user = db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
                    return self.issue_token(db, user)
                response = await self.store.run(create)
            else:
                user = await self.store.run(lambda db: db.execute("SELECT * FROM users WHERE username=?", (normalized,)).fetchone())
                if user:
                    request["user_id"] = user["id"]
                try:
                    await asyncio.to_thread(self.hash_password.verify, user["password_hash"] if user else self.dummy_hash, password)
                except (VerificationError, InvalidHashError):
                    raise APIError("invalid_credentials", "Username or password was not recognized.", 401)
                if user is None:
                    raise APIError("invalid_credentials", "Username or password was not recognized.", 401)
                replacement = await asyncio.to_thread(self.hash_password.hash, password) if self.hash_password.check_needs_rehash(user["password_hash"]) else None
                def login(db):
                    if replacement:
                        db.execute("UPDATE users SET password_hash=? WHERE id=?", (replacement, user["id"]))
                    return self.issue_token(db, user)
                response = await self.store.run(login)
        request["user_id"] = response["user"]["id"]
        log_event("auth_success", operation="native_signup" if signup else "native_login", user_id=request["user_id"])
        return web.json_response(response)

    async def lookup_token(self, token: str):
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            raise APIError("invalid_token", "Your sign-in expired. Sign in again.", 401)
        user = await self.store.run(lambda db: db.execute("SELECT u.*,t.expires_at FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.hash=? AND t.expires_at>?", (digest(token), int(time.time()))).fetchone())
        if not user:
            raise APIError("invalid_token", "Your sign-in expired. Sign in again.", 401)
        return user

    async def logout(self, request):
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise APIError("invalid_token", "A bearer token is required.", 401)
        token = authorization[7:]
        user = await self.lookup_token(token)
        request["user_id"] = user["id"]
        hashed = digest(token)
        await self.store.run(lambda db: db.execute("DELETE FROM tokens WHERE hash=?", (hashed,)))
        for player in list(self.members.values()):
            if player.token_hash == hashed:
                await player.socket.close(code=1008, message=b"Signed out")
        log_event("auth_success", operation="native_logout", user_id=user["id"])
        return web.json_response({"status": "signed_out"})

    def discord_configured(self):
        if not self.client_id or not self.client_secret:
            raise APIError("discord_unavailable", "Discord sign-in is not configured on this server. Use username/password or contact the server operator.", 503)

    async def discord_start(self, request):
        self.discord_configured()
        self.rate_limit(request, "discord_start", 10, 600)
        state, poll, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        expires = int(time.time()) + OAUTH_LIFETIME
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        def create(db):
            db.execute("DELETE FROM oauth WHERE expires_at<=?", (int(time.time()),))
            db.execute("INSERT INTO oauth(state_hash,poll_hash,verifier,expires_at) VALUES(?,?,?,?)", (digest(state), digest(poll), verifier, expires))
        await self.store.run(create)
        log_event("auth_success", operation="discord_start")
        params = {"client_id": self.client_id, "response_type": "code", "redirect_uri": self.callback, "scope": "identify", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        return web.json_response({"authorization_url": "https://discord.com/oauth2/authorize?" + urlencode(params), "poll_token": poll, "expires_at": expires})

    def callback_page(self, text: str, status: int = 200):
        return web.Response(text="<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Orebit sign-in</title><body><h1>Orebit sign-in</h1><p>" + html.escape(text) + "</p></body></html>", content_type="text/html", status=status, headers={"Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})

    async def discord_callback(self, request):
        self.discord_configured()
        self.rate_limit(request, "discord_callback", 30, 600)
        state = request.query.get("state", "")
        if not 20 <= len(state) <= 200:
            request["error_code"] = "invalid_callback"
            return self.callback_page("This sign-in link is invalid or expired. Start again in Orebit.", 400)
        hashed = digest(state)
        def claim(db):
            row = db.execute("SELECT * FROM oauth WHERE state_hash=? AND status='pending' AND expires_at>?", (hashed, int(time.time()))).fetchone()
            if row:
                db.execute("UPDATE oauth SET status='processing' WHERE state_hash=?", (hashed,))
            return row
        flow = await self.store.run(claim)
        if flow is None:
            request["error_code"] = "invalid_callback"
            return self.callback_page("This sign-in link has expired or was already used. Start again in Orebit.", 400)
        code = request.query.get("code", "")
        if request.query.get("error") or not code or len(code) > 2048:
            request["error_code"] = "discord_cancelled"
            await self.store.run(lambda db: db.execute("UPDATE oauth SET status='failed',error='Discord authorization was cancelled.' WHERE state_hash=?", (hashed,)))
            return self.callback_page("Discord sign-in was cancelled. Return to Orebit to try again.", 400)
        try:
            async with self.http.post("https://discord.com/api/oauth2/token", data={"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code", "code": code, "redirect_uri": self.callback, "code_verifier": flow["verifier"]}) as response:
                token_data = await provider_json(response)
            access_token = token_data.get("access_token")
            if not isinstance(access_token, str) or len(access_token) > 4096:
                raise ValueError("Invalid Discord token response")
            async with self.http.get("https://discord.com/api/v10/users/@me", headers={"Authorization": "Bearer " + access_token}) as response:
                identity = await provider_json(response)
            discord_id = identity.get("id", "")
            if not isinstance(discord_id, str) or not re.fullmatch(r"[0-9]{1,24}", discord_id):
                raise ValueError("Invalid Discord identity")
            display = identity.get("global_name") or identity.get("username") or "Discord miner"
            display = "".join(c for c in str(display) if c.isprintable())[:40] or "Discord miner"
            def complete(db):
                db.execute("INSERT INTO users(discord_id,display_name,created_at) VALUES(?,?,?) ON CONFLICT(discord_id) DO UPDATE SET display_name=excluded.display_name", (discord_id, display, int(time.time())))
                user = db.execute("SELECT id FROM users WHERE discord_id=?", (discord_id,)).fetchone()
                db.execute("UPDATE oauth SET status='complete',user_id=?,verifier='' WHERE state_hash=?", (user["id"], hashed))
                return user["id"]
            request["user_id"] = await self.store.run(complete)
        except (asyncio.TimeoutError, ValueError, KeyError, web.HTTPException) as error:
            request["error_code"], request["log_error"] = "discord_failed", error
            await self.store.run(lambda db: db.execute("UPDATE oauth SET status='failed',error='Discord sign-in failed. Please try again.',verifier='' WHERE state_hash=?", (hashed,)))
            return self.callback_page("Discord sign-in failed. Return to Orebit and try again.", 502)
        except Exception as error:
            request["error_code"], request["log_error"] = "discord_failed", error
            await self.store.run(lambda db: db.execute("UPDATE oauth SET status='failed',error='Discord is temporarily unavailable. Please try again.',verifier='' WHERE state_hash=?", (hashed,)))
            return self.callback_page("Discord is temporarily unavailable. Return to Orebit and try again.", 502)
        log_event("auth_success", operation="discord_callback", user_id=request["user_id"])
        return self.callback_page("Signed in successfully. You may close this tab and return to Orebit.")

    async def discord_poll(self, request):
        self.rate_limit(request, "discord_poll", 900, 600)
        body = await self.body(request)
        secret = body.get("poll_token", "")
        if not isinstance(secret, str) or not 20 <= len(secret) <= 200:
            raise APIError("invalid_completion", "Invalid sign-in completion secret.", 401)
        def poll(db):
            row = db.execute("SELECT * FROM oauth WHERE poll_hash=? AND expires_at>?", (digest(secret), int(time.time()))).fetchone()
            if not row:
                raise APIError("expired_completion", "This sign-in has expired or was already completed. Start again.", 401)
            if row["status"] == "complete":
                user = db.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
                result = self.issue_token(db, user)
                db.execute("DELETE FROM oauth WHERE poll_hash=?", (digest(secret),))
                return {"status": "complete", **result}
            if row["status"] == "failed":
                db.execute("DELETE FROM oauth WHERE poll_hash=?", (digest(secret),))
                return {"status": "failed", "message": row["error"]}
            return {"status": "pending"}
        result = await self.store.run(poll)
        if result["status"] == "complete":
            request["user_id"] = result["user"]["id"]
            log_event("auth_success", operation="discord_poll", user_id=request["user_id"])
        elif result["status"] == "failed":
            request["error_code"] = "discord_failed"
            result["request_id"] = request["request_id"]
        return web.json_response(result)

    async def health(self, request):
        return web.json_response({"status": "ok", "protocol": 1, "world_id": self.world_id, "players": len(self.members), "capacity": 5, "discord_configured": bool(self.client_id and self.client_secret)})

    async def send(self, player, message):
        try:
            await asyncio.wait_for(player.socket.send_str(encode(message)), timeout=5)
            player.sent += 1
        except (ConnectionError, RuntimeError, asyncio.TimeoutError) as error:
            with log_context(request_id=player.session_id, session_id=player.session_id, player_id=player.player_id, user_id=player.user_id):
                log_event("session_error", level=logging.WARNING, error=error, error_code="connection_error")
            await player.socket.close(code=1001, message=b"Connection too slow; reconnect to resume")

    async def broadcast(self, message, exclude=None):
        await asyncio.gather(*(self.send(p, message) for p in list(self.members.values()) if p is not exclude))

    def validate_state(self, state):
        if not isinstance(state, dict) or set(state) - STATE_KEYS:
            raise APIError("invalid_state", "Invalid player state fields.")
        try:
            if len(encode(state).encode()) > MAX_STATE:
                raise APIError("invalid_state", "Player state is too large.")
        except (ValueError, TypeError, RecursionError):
            raise APIError("invalid_state", "Player state is not finite JSON.")
        for key, value in state.items():
            if key in ("facing", "alive"):
                if not isinstance(value, bool):
                    raise APIError("invalid_state", "Invalid player flags.")
            elif key in ("x", "y", "player_hp", "player_fuel", "player_money"):
                if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e15:
                    raise APIError("invalid_state", "Invalid player numeric value.")
                if key == "x" and not -5 <= value <= WIDTH + 5:
                    raise APIError("invalid_state", "Player position is outside this world.")
                if key == "y" and not -HEIGHT - 10 <= value <= 20:
                    raise APIError("invalid_state", "Player position is outside this world.")
                minimum = {"player_money": 0, "player_hp": -10000, "player_fuel": -100}.get(key)
                if minimum is not None and value < minimum:
                    raise APIError("invalid_state", "Player resource is outside the supported range.")
            elif key == "current_upgrades":
                if not isinstance(value, dict) or set(value) - UPGRADES or any(not isinstance(v, str) or len(v) > 64 for v in value.values()):
                    raise APIError("invalid_state", "Invalid upgrades.")
            elif key in ("player_items", "player_cargo"):
                allowed = ITEMS if key == "player_items" else set(WEIGHTS)
                if not isinstance(value, dict) or set(value) - allowed or any(type(v) not in (int, float) or not math.isfinite(v) or v != int(v) or not 0 <= v <= 1000000000 for v in value.values()):
                    raise APIError("invalid_state", "Invalid inventory.")
            elif key == "transmissions":
                if not isinstance(value, list) or len(value) > 32:
                    raise APIError("invalid_state", "Invalid transmissions.")
                for entry in value:
                    if not isinstance(entry, dict) or len(entry) > 12 or any(not isinstance(k, str) or len(k) > 64 or type(v) not in (str, bool, int, float) or (isinstance(v, str) and len(v) > 4096) or (type(v) in (int, float) and (not math.isfinite(v) or abs(v) > 1e15)) for k, v in entry.items()):
                        raise APIError("invalid_state", "Invalid transmission entry.")
        return state

    def save_state(self, db, player, state, revision):
        if player.user_id is not None:
            db.execute("INSERT INTO player_states(world_id,user_id,state,revision,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(world_id,user_id) DO UPDATE SET state=excluded.state,revision=excluded.revision,updated_at=excluded.updated_at", (self.world_id, player.user_id, encode(state), revision, int(time.time())))

    async def update_state(self, player, message):
        state = self.validate_state(message.get("state"))
        revision = message.get("state_revision")
        if type(revision) not in (int, float) or revision != player.revision:
            await self.send(player, {"type": "state_sync", "state": player.state, "state_revision": player.revision})
            return
        await self.store.run(self.save_state, player, state, player.revision)
        player.state = state
        player.state_updates += 1
        await self.broadcast({"type": "state", "player_id": player.player_id, "state": state}, exclude=player)

    async def mine(self, player, message):
        request_id = message.get("request_id")
        x, y, method = message.get("x"), message.get("y"), message.get("method", "drill")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 64:
            player.mine_rejected += 1
            log_event("mining_decision", level=logging.WARNING, action=method, accepted=False, error_code="invalid_mine")
            raise APIError("invalid_mine", "Mining needs a unique request_id of 1-64 characters.")
        if request_id in player.requests:
            # A retried packet never awards twice or replays an obsolete state snapshot.
            player.mine_duplicates += 1
            log_event("mining_decision", action=method, accepted=False, error_code="duplicate_mine")
            await self.send(player, {"type": "state_sync", "state": player.state, "state_revision": player.revision})
            return
        if type(x) not in (int, float) or type(y) not in (int, float) or not math.isfinite(x) or not math.isfinite(y) or x != int(x) or y != int(y) or not 0 <= x < WIDTH or not 0 <= y < HEIGHT or method not in ("drill", "blast"):
            player.mine_rejected += 1
            log_event("mining_decision", level=logging.WARNING, action=method, accepted=False, error_code="invalid_mine")
            raise APIError("invalid_mine", "Mining coordinates or method are invalid.")
        x, y = int(x), int(y)
        name = tile_name(self.terrain[x][y])
        accepted = bool(name and (x, y) not in self.excavated and (method == "blast" or name != "Rock"))
        event = {"type": "mined", "request_id": request_id, "player_id": player.player_id, "x": x, "y": y, "method": method, "accepted": accepted, "ore": name if accepted and method == "drill" else ""}
        if accepted:
            state = award(copy.deepcopy(player.state), event["ore"])
            revision = player.revision + 1
            def commit(db):
                try:
                    db.execute("INSERT INTO excavations(world_id,x,y,user_id,created_at) VALUES(?,?,?,?,?)", (self.world_id, x, y, player.user_id, int(time.time())))
                except sqlite3.IntegrityError:
                    return False
                self.save_state(db, player, state, revision)
                return True
            try:
                accepted = await self.store.run(commit)
            except Exception as error:
                player.mine_rejected += 1
                log_event("mining_decision", level=logging.ERROR, error=error, action=method, x=x, y=y, accepted=False, error_code="server_error")
                raise
            if accepted:
                self.excavated.add((x, y))
                player.state, player.revision = state, revision
                event.update(state=state, state_revision=revision)
            else:
                self.excavated.add((x, y))
                event.update(accepted=False, ore="")
        if event["accepted"]:
            player.mine_accepted += 1
        else:
            player.mine_rejected += 1
        log_event("mining_decision", action=method, x=x, y=y, accepted=event["accepted"])
        player.requests[request_id] = None
        if len(player.requests) > 512:
            player.requests.popitem(last=False)
        if event["accepted"]:
            await self.broadcast(event)
        else:
            await self.send(player, event)

    async def websocket(self, request):
        if self.joining >= 32:
            raise APIError("busy", "Server is busy. Please try again.", 503)
        self.rate_limit(request, "connect", 60, 600)
        socket = web.WebSocketResponse(heartbeat=20, receive_timeout=60, max_msg_size=MAX_BODY, compress=False)
        socket.headers["X-Request-ID"] = request["request_id"]
        await socket.prepare(request)
        started = time.monotonic()
        with ExitStack() as contexts:
            contexts.enter_context(log_context(session_id=request["request_id"]))
            log_event("session_upgrade", status=101, duration_ms=(started - request["started"]) * 1000)
            player = None
            received = 0
            self.joining += 1
            try:
                first = await asyncio.wait_for(socket.receive(), timeout=10)
                if first.type != WSMsgType.TEXT:
                    raise APIError("join_required", "Send a join object first.")
                received += 1
                try:
                    join = json.loads(first.data)
                except (ValueError, RecursionError):
                    raise APIError("invalid_json", "Join must be valid JSON.")
                if not isinstance(join, dict) or join.get("type") != "join":
                    raise APIError("join_required", "Send a join object first.")
                if join.get("world_id", self.world_id) != self.world_id:
                    raise APIError("world_not_found", "That server world does not exist.", 404)
                token = join.get("token", "")
                user = await self.lookup_token(token) if token else None
                if user:
                    request["user_id"] = user["id"]
                    contexts.enter_context(log_context(user_id=user["id"]))
                async with self.world_lock:
                    if len(self.members) >= 5:
                        raise APIError("server_full", "This server has five players. Please try again when a place opens.", 409)
                    if user and any(p.user_id == user["id"] for p in self.members.values()):
                        raise APIError("already_connected", "This account is already connected to this server.", 409)
                    row = await self.store.run(lambda db: db.execute("SELECT state,revision FROM player_states WHERE world_id=? AND user_id=?", (self.world_id, user["id"])).fetchone()) if user else None
                    player = Player(socket, secrets.token_hex(8), user["display_name"] if user else "Anonymous " + secrets.token_hex(2), user["id"] if user else None, digest(token) if user else None, user["expires_at"] if user else 0, json.loads(row["state"]) if row else {}, row["revision"] if row else 0)
                    player.session_id = request["request_id"]
                    player.received = received
                    request["player_id"] = player.player_id
                    contexts.enter_context(log_context(player_id=player.player_id))
                    self.members[player.player_id] = player
                    log_event("session_join", members=len(self.members), joining=self.joining)
                    await self.send(player, {"type": "joined", "player_id": player.player_id, "world_id": self.world_id, "seed": self.seed, "excavated": sorted(self.excavated), "players": [p.public() for p in self.members.values()], "state": player.state, "state_revision": player.revision})
                    await self.broadcast({"type": "player_joined", "player": player.public()}, exclude=player)
                async for incoming in socket:
                    if incoming.type != WSMsgType.TEXT:
                        if incoming.type == WSMsgType.ERROR:
                            request["error_code"] = "connection_error"
                            log_event("session_error", level=logging.WARNING, error=socket.exception(), error_code="connection_error")
                        break
                    player.received += 1
                    now = time.monotonic()
                    player.messages = min(250.0, player.messages + (now - player.refilled_at) * 60)
                    player.refilled_at = now
                    player.messages -= 1
                    if player.messages < 0:
                        raise APIError("rate_limited", "Too many game messages. Reconnect to resume.", 429)
                    if player.user_id is not None and player.token_expires <= int(time.time()):
                        raise APIError("invalid_token", "Your sign-in expired. Sign in again.", 401)
                    try:
                        message = json.loads(incoming.data)
                    except (ValueError, RecursionError):
                        raise APIError("invalid_json", "Game messages must be valid JSON.")
                    if not isinstance(message, dict):
                        raise APIError("invalid_message", "Game messages must be JSON objects.")
                    async with self.world_lock:
                        if message.get("type") == "state":
                            await self.update_state(player, message)
                        elif message.get("type") == "mine":
                            await self.mine(player, message)
                        elif message.get("type") == "ping":
                            await self.send(player, {"type": "pong"})
                        elif message.get("type") == "leave":
                            break
                        else:
                            raise APIError("invalid_message", "Unknown game message type.")
            except APIError as error:
                request["error_code"] = error.code
                log_event("session_error", level=logging.WARNING, error=error, error_code=error.code)
                if not socket.closed:
                    await socket.send_str(encode({"type": "error", "code": error.code, "message": error.message, "request_id": request["request_id"]}))
                    if player:
                        player.sent += 1
                    await socket.close(code=1008, message=error.code.encode()[:100])
            except (asyncio.TimeoutError, ConnectionError) as error:
                request["error_code"] = "connection_timeout" if isinstance(error, asyncio.TimeoutError) else "connection_error"
                log_event("session_error", level=logging.WARNING, error=error, error_code=request["error_code"])
                await socket.close(code=1001, message=b"Connection timed out; reconnect to resume")
            except asyncio.CancelledError:
                request["error_code"] = "request_cancelled"
                log_event("session_error", level=logging.WARNING, error_code="request_cancelled")
                raise
            except Exception as error:
                request["error_code"] = "server_error"
                log_event("session_error", level=logging.ERROR, error=error, error_code="server_error")
                if not socket.closed:
                    await socket.send_str(encode({"type": "error", "code": "server_error", "message": "The server could not save this action. Reconnect to resume your last saved state.", "request_id": request["request_id"]}))
                    if player:
                        player.sent += 1
                    await socket.close(code=1011, message=b"Server failure")
            finally:
                self.joining -= 1
                try:
                    if player:
                        async with self.world_lock:
                            self.members.pop(player.player_id, None)
                            await self.broadcast({"type": "player_left", "player_id": player.player_id})
                finally:
                    log_event(
                        "session_leave", duration_ms=(time.monotonic() - started) * 1000,
                        close_code=socket.close_code, members=len(self.members), joining=self.joining,
                        received=player.received if player else received, sent=player.sent if player else 0,
                        state_updates=player.state_updates if player else 0,
                        mine_accepted=player.mine_accepted if player else 0,
                        mine_rejected=player.mine_rejected if player else 0,
                        mine_duplicates=player.mine_duplicates if player else 0,
                        error_code=request.get("error_code"),
                    )
        return socket


def create_app(args):
    service = Service(args)

    @web.middleware
    async def security(request, handler):
        request["request_id"] = secrets.token_hex(16)
        request["started"] = time.monotonic()
        resource = request.match_info.route.resource
        route = resource.canonical if resource is not None else "<unmatched>"
        operation = {
            "/api/auth/logout": "native_logout",
            "/api/auth/discord/start": "discord_start",
            "/api/auth/discord/poll": "discord_poll",
            "/auth/discord/callback": "discord_callback",
        }.get(route)
        if route == "/api/auth/{action}":
            operation = "native_signup" if request.match_info["action"] == "signup" else "native_login"
        with log_context(request_id=request["request_id"], route=route, method=request.method, world_id=service.world_id):
            response = None
            try:
                origin = request.headers.get("Origin")
                if origin and origin not in service.origins:
                    request["error_code"] = "origin_forbidden"
                    response = web.json_response({"error": "origin_forbidden", "message": "This browser origin is not allowed.", "request_id": request["request_id"]}, status=403)
                elif request.method == "OPTIONS":
                    response = web.Response(status=204)
                else:
                    try:
                        response = await handler(request)
                    except APIError as error:
                        request["error_code"], request["log_error"] = error.code, error
                        response = web.json_response({"error": error.code, "message": error.message, "request_id": request["request_id"]}, status=error.status)
                    except web.HTTPException as error:
                        request["error_code"], request["log_error"] = "http_error", error
                        response = web.json_response({"error": "http_error", "message": error.reason, "request_id": request["request_id"]}, status=error.status)
                    except Exception as error:
                        request["error_code"], request["log_error"] = "server_error", error
                        response = web.json_response({"error": "server_error", "message": "The server is temporarily unavailable. Please try again.", "request_id": request["request_id"]}, status=500)
                # WebSocket headers have already been sent at prepare time.
                if not response.prepared:
                    response.headers["X-Request-ID"] = request["request_id"]
                    response.headers["Cache-Control"] = "no-store"
                    response.headers["X-Content-Type-Options"] = "nosniff"
                    response.headers["Referrer-Policy"] = "no-referrer"
                    if origin and origin in service.origins:
                        response.headers["Access-Control-Allow-Origin"] = origin
                        response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
                        response.headers["Vary"] = "Origin"
                        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
                return response
            except asyncio.CancelledError:
                request["error_code"] = "request_cancelled"
                raise
            finally:
                status = response.status if response is not None else (499 if request.get("error_code") == "request_cancelled" else 500)
                error_code = request.get("error_code") or ("http_error" if status >= 400 else None)
                level = logging.ERROR if status >= 500 or error_code == "server_error" else (logging.WARNING if error_code else logging.INFO)
                fields = {
                    "status": status, "duration_ms": (time.monotonic() - request["started"]) * 1000,
                    "error_code": error_code, "user_id": request.get("user_id"),
                    "player_id": request.get("player_id"), "operation": operation,
                    "session_id": request["request_id"] if route == "/api/ws" else None,
                }
                if operation and error_code:
                    log_event("auth_failure", level=level, error=request.get("log_error"), **fields)
                if error_code or route not in ("/healthz", "/api/auth/discord/poll"):
                    log_event("http_request", level=level, error=request.get("log_error"), **fields)

    app = web.Application(client_max_size=MAX_BODY, middlewares=[security])
    app.router.add_post("/api/auth/{action:signup|login}", service.native_auth)
    app.router.add_post("/api/auth/logout", service.logout)
    app.router.add_post("/api/auth/discord/start", service.discord_start)
    app.router.add_post("/api/auth/discord/poll", service.discord_poll)
    app.router.add_get("/auth/discord/callback", service.discord_callback)
    app.router.add_get("/api/ws", service.websocket)
    app.router.add_get("/healthz", service.health)
    app.router.add_options("/{path:.*}", lambda request: web.Response(status=204))
    app.on_startup.append(service.startup)
    app.on_shutdown.append(service.shutdown)
    app.on_cleanup.append(service.cleanup)
    return app


def main():
    parser = argparse.ArgumentParser(description="Persistent five-player Orebit co-op service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=os.environ.get("OREBIT_DB", "coop.sqlite3"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        configure_logging()
        # Access logs would expose the OAuth callback's single-use authorization code.
        web.run_app(create_app(args), host=args.host, port=args.port, access_log=None, print=None)
    except Exception as error:
        log_event("startup_fatal", level=logging.CRITICAL, error=error)
        raise


if __name__ == "__main__":
    main()
