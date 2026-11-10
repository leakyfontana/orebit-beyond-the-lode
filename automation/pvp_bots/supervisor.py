#!/usr/bin/env python3
"""Run the frozen native PvP policy in isolated, normally authenticated clients.

Required environment: OREBIT_PVP_BOT_CONTROL_KEY (never an argument),
OREBIT_PVP_BOT_CREDENTIALS (0600 provisioned JSON), OREBIT_PVP_BOT_GAME
(native project directory), OREBIT_PVP_BOT_GODOT (native Godot executable).
OREBIT_PVP_BOT_ENDPOINT defaults to http://127.0.0.1:8765.
State defaults to /var/lib/orebit-pvp-bots; --state-dir overrides it.
No third-party Python packages are required. SIGTERM/SIGINT drain workers.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import dataclass
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import stat
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
TOKEN_MARGIN = 300
LOG = logging.getLogger("pvp-pool")


class PoolError(Exception):
    """A fixed, secret-free operational error code."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def private_json(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise PoolError("private_file_permissions")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise PoolError("invalid_private_json")
    return value


def save_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, separators=(",", ":"))
    os.replace(temporary, path)


def request_json(endpoint: str, route: str, *, bearer: str = "", body: dict | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = urllib.request.Request(endpoint + route, data=data, headers=headers)
    # Never forward the control bearer or passwords across HTTP redirects or
    # ambient proxy configuration. Explicit HTTPS uses the normal CA trust store.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=3) as response:
            payload = response.read(131073)
            if len(payload) > 131072:
                raise PoolError("http_response_too_large")
            value = json.loads(payload)
    except urllib.error.HTTPError as error:
        raise PoolError("http_status_" + str(error.code)) from None
    except (OSError, ValueError, urllib.error.URLError):
        raise PoolError("http_unavailable_or_invalid_json") from None
    if not isinstance(value, dict):
        raise PoolError("http_response_not_object")
    return value


@dataclass
class Account:
    slot: int
    user_id: int
    username: str
    password: str
    directory: Path
    process: asyncio.subprocess.Process | None = None
    starting: asyncio.Task | None = None
    readers: tuple = ()
    cancel_start: bool = False
    started_at: float = 0
    retry_at: float = 0
    failures: int = 0
    stopping_at: float = 0
    joined: bool = False
    token_expires: int = 0
    logger: logging.Logger | None = None

    def path(self, name: str) -> Path:
        return self.directory / name

    def status(self) -> dict:
        try:
            value = json.loads(self.path("status.json").read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}


class Supervisor:
    def __init__(self, args):
        os.umask(0o077)
        self.endpoint = args.endpoint.rstrip("/")
        url = urllib.parse.urlsplit(self.endpoint)
        if (url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                or url.query or url.fragment or (url.scheme == "http" and url.hostname not in ("127.0.0.1", "localhost", "::1"))):
            raise PoolError("endpoint_requires_https_or_loopback_http")
        self.key = os.environ.get("OREBIT_PVP_BOT_CONTROL_KEY", "")
        if not self.key:
            raise PoolError("missing_control_key")
        self.game = Path(args.game).resolve(strict=True)
        self.godot = Path(args.godot).resolve(strict=True)
        if not (self.game / "project.godot").is_file() or not os.access(self.godot, os.X_OK):
            raise PoolError("missing_native_runtime")
        manifest = json.loads((HERE / "pool.json").read_text())
        if hashlib.sha256((HERE / "policy.gd").read_bytes()).hexdigest() != manifest["policy"]["sha256"]:
            raise PoolError("frozen_policy_checksum_mismatch")
        self.state = Path(args.state_dir).resolve()
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.state, 0o700)
        self.lock = self.state.joinpath("supervisor.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PoolError("supervisor_already_running") from None
        credentials = private_json(Path(args.credentials))
        records = credentials.get("accounts", [])
        if credentials.get("schema_version") != 1 or not isinstance(records, list) or len(records) != 5:
            raise PoolError("expected_five_provisioned_accounts")
        self.accounts: dict[int, Account] = {}
        for record in records:
            if (not isinstance(record, dict) or type(record.get("slot")) is not int
                    or record["slot"] not in range(1, 6) or type(record.get("user_id")) is not int
                    or record["user_id"] <= 0 or not isinstance(record.get("username"), str)
                    or not record["username"] or not isinstance(record.get("password"), str)
                    or not 8 <= len(record["password"]) <= 128):
                raise PoolError("invalid_provisioned_account")
            account = Account(record["slot"], record["user_id"], record["username"], record["password"], self.state / ("slot-" + str(record["slot"])))
            if account.slot in self.accounts or any(a.user_id == account.user_id or a.username == account.username for a in self.accounts.values()):
                raise PoolError("duplicate_provisioned_account")
            account.directory.mkdir(mode=0o700, exist_ok=True)
            os.chmod(account.directory, 0o700)
            account.logger = logging.getLogger("pvp-worker-" + str(account.slot))
            account.logger.setLevel(logging.INFO)
            account.logger.propagate = False
            handler = RotatingFileHandler(account.path("worker.log"), maxBytes=2 * 1024 * 1024, backupCount=2)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            account.logger.addHandler(handler)
            self.accounts[account.slot] = account
        self.stop_event = asyncio.Event()
        self.login_lock = asyncio.Lock()
        self.logins: deque[float] = deque()
        self.lease = self.state / "supervisor.lease"
        self.lease.touch(mode=0o600)
        self.last_plan_at = 0.0
        self.last_poll_error = ""

    def validate_plan(self, plan: dict) -> tuple[int, set[int]]:
        humans, target = plan.get("humans"), plan.get("target_bots")
        if (type(plan.get("enabled")) is not bool or plan.get("capacity") != 5
                or plan.get("world_id") != "public:pvp" or not isinstance(plan.get("round_id"), str)
                or type(humans) is not int or not 0 <= humans <= 5 or type(target) is not int
                or target != (5 - humans if plan["enabled"] else 0)):
            raise PoolError("invalid_pool_capacity_plan")
        bots, connected = plan.get("bots"), plan.get("connected_bots")
        if not isinstance(bots, list) or not isinstance(connected, list):
            raise PoolError("invalid_pool_membership")
        registered = set()
        for bot in bots:
            if not isinstance(bot, dict):
                raise PoolError("invalid_registered_bot")
            account = self.accounts.get(bot.get("slot"))
            if account is None or bot.get("user_id") != account.user_id or bot.get("name") != account.username or account.slot in registered:
                raise PoolError("registered_account_mismatch")
            registered.add(account.slot)
        if registered != set(self.accounts):
            raise PoolError("incomplete_bot_registry")
        ids = set()
        for bot in connected:
            if not isinstance(bot, dict) or not isinstance(bot.get("player_id"), str) or not bot["player_id"]:
                raise PoolError("invalid_connected_bot")
            user_id = bot.get("user_id")
            if user_id not in {a.user_id for a in self.accounts.values()} or user_id in ids:
                raise PoolError("unknown_or_duplicate_connected_bot")
            ids.add(user_id)
        if len(ids) > 5 - humans:
            raise PoolError("pool_exceeds_capacity")
        return target, ids

    async def token(self, account: Account) -> dict:
        try:
            cached = private_json(account.path("token.json"))
            if (cached.get("user_id") == account.user_id and cached.get("endpoint") == self.endpoint
                    and isinstance(cached.get("token"), str) and cached["token"]
                    and int(cached.get("expires_at", 0)) > time.time() + TOKEN_MARGIN):
                return cached
        except (OSError, ValueError, PoolError):
            pass
        # Share one bounded login budget across all clients, below the backend's
        # 30/600s limit even when every password/token is invalid. Cached normal
        # sessions survive supervisor restarts and ordinary reconnects.
        async with self.login_lock:
            if account.cancel_start:
                raise asyncio.CancelledError
            now = time.monotonic()
            while self.logins and self.logins[0] <= now - 600:
                self.logins.popleft()
            if len(self.logins) >= 20:
                raise PoolError("login_budget_cooldown")
            self.logins.append(now)
            value = await asyncio.to_thread(request_json, self.endpoint, "/api/auth/login", body={"username": account.username, "password": account.password, "mode": "pvp"})
        if (value.get("user", {}).get("id") != account.user_id or not isinstance(value.get("token"), str)
                or not 20 <= len(value["token"]) <= 200 or type(value.get("expires_at")) is not int
                or value["expires_at"] <= time.time() + TOKEN_MARGIN):
            raise PoolError("login_identity_or_expiry_mismatch")
        cached = {"token": value["token"], "expires_at": value["expires_at"], "user_id": account.user_id, "endpoint": self.endpoint}
        save_json(account.path("token.json"), cached)
        return cached

    def backoff(self, account: Account, *, login: bool = False) -> None:
        account.failures = min(account.failures + 1, 8)
        account.retry_at = time.monotonic() + max(60 if login else 2, min(60, 2 ** account.failures)) + account.slot * 0.15

    async def start(self, account: Account) -> None:
        try:
            if account.cancel_start:
                return
            token = await self.token(account)
            if account.cancel_start:
                return
            account.token_expires = token["expires_at"]
            for filename in ("stop", "status.json", "status.json.tmp"):
                account.path(filename).unlink(missing_ok=True)
            environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH") if key in os.environ}
            for key, name in (("HOME", "home"), ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("XDG_RUNTIME_DIR", "run")):
                path = account.path(name)
                path.mkdir(mode=0o700, exist_ok=True)
                environment[key] = str(path)
            save_json(account.path("worker.json"), {"slot": account.slot, "username": account.username, "endpoint": self.endpoint,
                "state_dir": str(account.directory), "token_file": str(account.path("token.json")), "stop_file": str(account.path("stop")),
                "status_file": str(account.path("status.json")), "lease_file": str(self.lease)})
            account.process = await asyncio.create_subprocess_exec(str(self.godot), "--headless", "--path", str(self.game),
                "--script", str(HERE / "worker.gd"), "--audio-driver", "Dummy", "--",
                "--worker-config=" + str(account.path("worker.json")), "--mode=private", "--coop-token=", "--coop-url=" + self.endpoint,
                env=environment, cwd=self.game, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=16384)
            account.started_at = time.monotonic()
            account.stopping_at = 0
            account.joined = False
            account.readers = tuple(asyncio.create_task(self.capture(account, stream, label, token["token"])) for stream, label in ((account.process.stdout, "stdout"), (account.process.stderr, "stderr")))
            LOG.info("worker_started slot=%s pid=%s", account.slot, account.process.pid)
            if account.cancel_start:
                self.stop(account)
        except asyncio.CancelledError:
            # If cancellation coincides with spawn, retain ownership and drain it.
            if account.process is not None:
                self.stop(account)
            raise
        except Exception as error:
            self.backoff(account, login=True)
            LOG.error("worker_start_failed slot=%s code=%s", account.slot, str(error) if isinstance(error, PoolError) else type(error).__name__)
        finally:
            account.starting = None

    async def capture(self, account: Account, stream, label: str, token: str) -> None:
        buffer = b""
        while chunk := await stream.read(4096):
            buffer += chunk
            while b"\n" in buffer or len(buffer) > 8192:
                if b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                else:
                    line, buffer = buffer[:8192], buffer[8192:]
                self.log_line(account, line, label, token)
        if buffer:
            self.log_line(account, buffer, label, token)

    def log_line(self, account: Account, raw: bytes, label: str, token: str) -> None:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line or line.startswith("PRACTICE_BOT_"):
            return
        for secret in (self.key, account.password, token):
            line = line.replace(secret, "[redacted]")
        account.logger.log(logging.ERROR if label == "stderr" else logging.INFO, "%s %s", label, line)
        if label == "stderr":
            LOG.error("worker_error slot=%s %s", account.slot, line)

    def stop(self, account: Account) -> None:
        if account.starting is not None:
            account.cancel_start = True
        if account.process is not None and not account.stopping_at:
            account.path("stop").touch(mode=0o600)
            account.stopping_at = time.monotonic()
            LOG.info("worker_stopping slot=%s", account.slot)

    async def reap(self) -> None:
        now = time.monotonic()
        for account in self.accounts.values():
            process = account.process
            if process is None:
                continue
            if process.returncode is None:
                if account.stopping_at and now - account.stopping_at > 5:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                continue
            await process.wait()
            await asyncio.gather(*account.readers, return_exceptions=True)
            status = account.status()
            if status.get("reason") == "auth_expired":
                account.path("token.json").unlink(missing_ok=True)
            LOG.info("worker_exited slot=%s code=%s reason=%s", account.slot, process.returncode, status.get("reason", "no_status"))
            if account.stopping_at:
                account.retry_at = now + 2
            else:
                self.backoff(account)
            account.process = None
            account.readers = ()
            account.joined = False
            account.stopping_at = 0

    def reconcile(self, target: int, connected: set[int]) -> None:
        now = time.monotonic()
        pending = []
        for account in self.accounts.values():
            if account.process is None:
                if account.starting is not None:
                    pending.append(account)
                continue
            status = account.status()
            if account.user_id in connected:
                account.joined = True
                if now - account.started_at > 60:
                    account.failures = 0
                if time.time() + TOKEN_MARGIN >= account.token_expires:
                    self.stop(account)
            elif account.joined:
                # The server already chose the victim. Never replace that choice
                # by stopping a different (better-scoring) connected bot.
                self.stop(account)
            elif not account.stopping_at:
                pending.append(account)
            if now - account.started_at > 30 and (not status or time.time() - float(status.get("updated_at", 0)) > 5):
                self.stop(account)
            if not account.joined and now - account.started_at > 35:
                self.stop(account)
            if not target:
                self.stop(account)
        available = max(0, target - len(connected))
        for account in pending[available:]:
            self.stop(account)
        occupied = min(len(pending), available)
        for account in self.accounts.values():
            if occupied >= available:
                break
            if (account.user_id not in connected and account.process is None and account.starting is None and now >= account.retry_at):
                account.cancel_start = False
                account.starting = asyncio.create_task(self.start(account))
                occupied += 1

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop_event.set)
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                self.lease.touch()
                await self.reap()
                try:
                    plan = await asyncio.to_thread(request_json, self.endpoint, "/api/pvp/bot-pool", bearer=self.key)
                    target, connected = self.validate_plan(plan)
                    self.last_plan_at = time.monotonic()
                    self.last_poll_error = ""
                    self.reconcile(target, connected)
                except Exception as error:
                    code = str(error) if isinstance(error, PoolError) else type(error).__name__
                    if code != self.last_poll_error:
                        LOG.error("pool_poll_failed code=%s", code)
                        self.last_poll_error = code
                    # Do not launch from stale capacity. Existing native sessions
                    # may continue through a short control-plane interruption.
                    if time.monotonic() - self.last_plan_at > 15:
                        for account in self.accounts.values():
                            self.stop(account)
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=max(0.05, 1 - (time.monotonic() - started)))
                except asyncio.TimeoutError:
                    pass
        finally:
            starting = [a.starting for a in self.accounts.values() if a.starting is not None]
            for account in self.accounts.values():
                self.stop(account)
            await asyncio.gather(*starting, return_exceptions=True)
            deadline = time.monotonic() + 8
            while any(a.process is not None for a in self.accounts.values()) and time.monotonic() < deadline:
                self.lease.touch()
                await self.reap()
                await asyncio.sleep(0.1)
            for account in self.accounts.values():
                if account.process is not None:
                    try:
                        account.process.kill()
                    except ProcessLookupError:
                        pass
                    await account.process.wait()
            self.lease.unlink(missing_ok=True)
            self.lock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", default=os.environ.get("OREBIT_PVP_BOT_ENDPOINT", "http://127.0.0.1:8765"))
    parser.add_argument("--credentials", default=os.environ.get("OREBIT_PVP_BOT_CREDENTIALS"))
    parser.add_argument("--game", default=os.environ.get("OREBIT_PVP_BOT_GAME"))
    parser.add_argument("--godot", default=os.environ.get("OREBIT_PVP_BOT_GODOT"))
    parser.add_argument("--state-dir", default="/var/lib/orebit-pvp-bots")
    args = parser.parse_args()
    if not all((args.credentials, args.game, args.godot)):
        parser.error("credentials, game and godot paths are required (flags or OREBIT_PVP_BOT_* environment)")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(Supervisor(args).run())
    except (PoolError, OSError, ValueError, KeyError) as error:
        LOG.error("supervisor_failed code=%s", str(error) if isinstance(error, PoolError) else type(error).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
