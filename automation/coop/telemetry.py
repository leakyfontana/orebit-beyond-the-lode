"""Bounded, privacy-preserving service diagnostics using only the standard library."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid


_BOOT_ID = uuid.uuid4().hex
_BUILD_ID = "unknown"
_CONTEXT = ContextVar("orebit_log_context", default={})
_LOG = logging.getLogger("orebit.coop")
_LEVEL_NAMES = {10: "DEBUG", 20: "INFO", 30: "WARNING", 40: "ERROR", 50: "CRITICAL"}
LEVELS = frozenset(_LEVEL_NAMES.values())
_EVENTS = frozenset({
    "startup", "shutdown", "startup_fatal", "asyncio_error", "http_request",
    "session_upgrade", "session_join", "session_leave", "session_error",
    "mining_decision", "auth_success", "auth_failure", "external_log", "log_sink_error",
})
_ROUTES = frozenset({
    "/api/auth/{action}", "/api/auth/logout", "/api/auth/discord/start",
    "/api/auth/discord/poll", "/auth/discord/callback", "/api/ws", "/healthz",
    "/{path}", "<unmatched>",
})
_ERROR_CODES = frozenset({
    "rate_limited", "invalid_json", "invalid_username", "invalid_password",
    "username_taken", "invalid_credentials", "invalid_token", "discord_unavailable",
    "invalid_completion", "expired_completion", "invalid_state", "invalid_mine",
    "busy", "join_required", "world_not_found", "server_full", "already_connected",
    "invalid_message", "origin_forbidden", "http_error", "server_error",
    "discord_cancelled", "discord_failed", "invalid_callback", "connection_timeout",
    "connection_error", "duplicate_mine", "request_cancelled",
})
_ENUM_FIELDS = {
    "route": _ROUTES,
    "method": frozenset({"GET", "HEAD", "POST", "OPTIONS", "PUT", "PATCH", "DELETE", "CONNECT", "TRACE"}),
    "error_code": _ERROR_CODES,
    "operation": frozenset({"native_signup", "native_login", "native_logout", "discord_start", "discord_callback", "discord_poll"}),
    "action": frozenset({"drill", "blast"}),
}
_INT_FIELDS = frozenset({
    "user_id", "status", "x", "y", "members", "joining", "received", "sent",
    "state_updates", "mine_accepted", "mine_rejected", "mine_duplicates", "close_code",
})
_ID_PATTERNS = {
    "request_id": re.compile(r"[0-9a-f]{32}\Z"),
    "session_id": re.compile(r"[0-9a-f]{32}\Z"),
    "player_id": re.compile(r"[0-9a-f]{16}\Z"),
    "world_id": re.compile(r"[A-Za-z0-9_-]{1,32}\Z"),
}
_NAME = re.compile(r"[A-Za-z0-9_.<>-]{1,128}\Z")
_BUILD_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_FIELD_NAMES = frozenset(_ENUM_FIELDS) | _INT_FIELDS | frozenset(_ID_PATTERNS) | {"duration_ms", "accepted"}


def _safe_fields(fields, *, strict=False):
    safe = {}
    for key, value in fields.items():
        if key in _ENUM_FIELDS:
            if isinstance(value, str) and value in _ENUM_FIELDS[key]:
                safe[key] = value
        elif key in _INT_FIELDS:
            if type(value) is int and 0 <= value <= 2**63 - 1:
                safe[key] = value
        elif key in _ID_PATTERNS:
            if isinstance(value, str) and _ID_PATTERNS[key].fullmatch(value):
                safe[key] = value
        elif key == "duration_ms":
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                safe[key] = round(value, 3)
        elif key == "accepted" and type(value) is bool:
            safe[key] = value
        if strict and key in _FIELD_NAMES and key not in safe:
            raise ValueError("Invalid telemetry field")
    return safe


def _diagnostics(error):
    """Never stringify exceptions or use traceback formatting (which includes source)."""
    name = type(error).__name__
    result = {"error_type": name if _NAME.fullmatch(name) else "Exception"}
    stack = []
    trace = error.__traceback__
    while trace is not None and len(stack) < 32:
        code = trace.tb_frame.f_code
        filename = Path(code.co_filename).name
        function = code.co_name
        stack.append({
            "file": filename if _NAME.fullmatch(filename) else "<unknown>",
            "function": function if _NAME.fullmatch(function) else "<unknown>",
            "line": trace.tb_lineno,
        })
        trace = trace.tb_next
    result["stack"] = stack
    return result


def parse_timestamp(value):
    """Parse query timestamps, treating a missing timezone as UTC."""
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def safe_record(value):
    """Return (UTC timestamp, safe record); reject invalid known fields.

    The offline query uses this same schema as the writer. Unknown fields are
    omitted, never echoed, including arbitrary messages and exception payloads.
    Importing this module does not configure logging or start the service.
    """
    if not isinstance(value, dict):
        raise ValueError("Invalid telemetry record")
    timestamp = parse_timestamp(value.get("timestamp"))
    name, level = value.get("event"), value.get("level")
    if not isinstance(name, str) or name not in _EVENTS or not isinstance(level, str) or level not in LEVELS:
        raise ValueError("Invalid event or level")
    result = {key: value[key] for key in ("timestamp", "level", "event")}
    result.update(_safe_fields(value, strict=True))
    for key, pattern in (("boot_id", _ID_PATTERNS["request_id"]), ("build_id", _BUILD_PATTERN), ("error_type", _NAME)):
        if key in value:
            item = value[key]
            if not isinstance(item, str) or not pattern.fullmatch(item):
                raise ValueError("Invalid telemetry identifier")
            result[key] = item
    if "stack" in value:
        stack = value["stack"]
        if not isinstance(stack, list) or len(stack) > 32:
            raise ValueError("Invalid telemetry stack")
        frames = []
        for frame in stack:
            if not isinstance(frame, dict) or set(frame) != {"file", "function", "line"}:
                raise ValueError("Invalid telemetry frame")
            if type(frame["line"]) is not int or frame["line"] < 0:
                raise ValueError("Invalid telemetry line")
            if any(not isinstance(frame[key], str) or not _NAME.fullmatch(frame[key]) for key in ("file", "function")):
                raise ValueError("Invalid telemetry frame name")
            frames.append({key: frame[key] for key in ("file", "function", "line")})
        result["stack"] = frames
    return timestamp, result


class _JSONFormatter(logging.Formatter):
    def format(self, record):
        # In particular, do NOT call record.getMessage(), formatException(), or
        # inspect arbitrary extras: aiohttp/asyncio may include credential URLs.
        name = getattr(record, "_orebit_event", None)
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": _LEVEL_NAMES.get(record.levelno, "ERROR"),
            "event": name if isinstance(name, str) and name in _EVENTS else "external_log",
            "boot_id": _BOOT_ID,
            "build_id": _BUILD_ID,
        }
        payload.update(_safe_fields(_CONTEXT.get()))
        fields = getattr(record, "_orebit_fields", None)
        if isinstance(fields, dict):
            payload.update(_safe_fields(fields))
        error = getattr(record, "_orebit_error", None)
        if not isinstance(error, BaseException) and record.exc_info:
            error = record.exc_info[1]
        if isinstance(error, BaseException):
            payload.update(_diagnostics(error))
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


class _RotatingJSONHandler(RotatingFileHandler):
    """Keep file I/O failures visible without recursing into the failed sink."""
    def __init__(self, filename, *, fallback, **kwargs):
        self._fallback = fallback
        self._last_sink_error = float("-inf")
        super().__init__(filename, **kwargs)

    def _open(self):
        # Set creation permissions atomically, independently of a caller's umask.
        # Every rotated archive inherits this protected active file's mode.
        descriptor = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
        try:
            os.fchmod(descriptor, 0o640)
            return os.fdopen(descriptor, self.mode, encoding=self.encoding, errors=self.errors)
        except BaseException:
            os.close(descriptor)
            raise

    def handleError(self, record):
        # emit() holds the handler lock, so this rate limit is shared by threads.
        now = time.monotonic()
        if now - self._last_sink_error < 60:
            return
        self._last_sink_error = now
        failure = logging.LogRecord("orebit.coop", logging.ERROR, "", 0, "", (), None)
        failure._orebit_event = "log_sink_error"
        failure._orebit_error = sys.exc_info()[1]
        self._fallback.handle(failure)


@contextmanager
def log_context(**fields):
    """Task-local correlation; asyncio.to_thread also copies this context."""
    token = _CONTEXT.set(_safe_fields({**_CONTEXT.get(), **fields}))
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def event(name, *, level=logging.INFO, error=None, **fields):
    _LOG.log(level, "", extra={
        "_orebit_event": name,
        "_orebit_fields": _safe_fields(fields),
        "_orebit_error": error,
    })


def _build_id():
    configured = os.environ.get("OREBIT_BUILD_ID", "")
    if _BUILD_PATTERN.fullmatch(configured):
        return configured
    source = hashlib.sha256()
    for name in ("server.py", "telemetry.py", "terrain.py", "requirements.txt"):
        source.update(name.encode("ascii"))
        source.update(Path(__file__).with_name(name).read_bytes())
    return source.hexdigest()


def _uncaught(error_type, error, trace):
    event("startup_fatal", level=logging.CRITICAL, error=error)


def configure_logging(log_dir=None):
    """Configure stdout and, when requested, a 10 MiB + 9 archive JSONL log.

    Install the safe stdout sink first so configuration/startup failures can be
    reported without Python's default exception message/source-line rendering.
    Invalid retention settings fail startup rather than silently unbounding logs.
    """
    global _BUILD_ID
    logging.raiseExceptions = False
    root = logging.getLogger()
    for logger in [root] + [item for item in logging.Logger.manager.loggerDict.values() if isinstance(item, logging.Logger)]:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        if logger is not root:
            logger.propagate = True
    formatter = _JSONFormatter()
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    root.addHandler(stdout)
    logging.lastResort = stdout
    level = os.environ.get("OREBIT_LOG_LEVEL", "INFO").upper()
    root.setLevel(level if level in LEVELS else "INFO")
    _LOG.setLevel(logging.NOTSET)
    logging.captureWarnings(True)
    sys.excepthook = _uncaught
    threading.excepthook = lambda args: _uncaught(args.exc_type, args.exc_value, args.exc_traceback)
    sys.unraisablehook = lambda args: event("asyncio_error", level=logging.ERROR, error=args.exc_value)
    _BUILD_ID = _build_id()
    maximum = int(os.environ.get("OREBIT_LOG_MAX_BYTES", "10485760"))
    backups = int(os.environ.get("OREBIT_LOG_BACKUP_COUNT", "9"))
    if maximum <= 0 or not 1 <= backups <= 100:
        raise ValueError("Invalid bounded log retention settings")
    directory = os.environ.get("OREBIT_LOG_DIR") if log_dir is None else log_dir
    if directory:
        target = Path(directory).expanduser()
        target.mkdir(mode=0o750, parents=True, exist_ok=True)
        handler = _RotatingJSONHandler(target / "events.jsonl", fallback=stdout, maxBytes=maximum, backupCount=backups, encoding="utf-8")
        handler.setFormatter(formatter)
        root.addHandler(handler)
