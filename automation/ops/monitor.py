"""Recordings-filesystem metadata monitor. Does not enumerate or open archives."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import stat
import tempfile
import time
import uuid

from discord_ops import Discord, OpsError, matching_message, token_from_file

THRESHOLDS = (70, 80, 90, 95)
REARM = 65
RETRY_SECONDS = 300
DEFAULT_STATE = "/var/lib/orebit-bot/ops"
DEFAULT_RECORDINGS = "/run/orebit-ops-recordings"


@dataclass(frozen=True)
class Reading:
    total: int
    used: int
    available: int
    free: int
    device: int
    path: str

    def __post_init__(self):
        if (self.total <= 0 or not 0 <= self.available <= self.free <= self.total
                or self.used != self.total - self.available):
            raise OpsError("Invalid filesystem metrics; alert state unchanged")

    @property
    def percent(self):
        # Same reserved-space-aware numerator as the unchanged capture 80% guard.
        return self.used * 100 / self.total

    def at_least(self, threshold):
        return self.used * 100 >= self.total * threshold


def read_disk(path):
    path = str(Path(path).absolute())
    usage = os.statvfs(path)
    total = usage.f_blocks * usage.f_frsize
    available = usage.f_bavail * usage.f_frsize
    return Reading(total, total - available, available,
                   usage.f_bfree * usage.f_frsize, os.stat(path).st_dev, path)


def private_file(path):
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OpsError("Unsafe ops state file")
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


class Ledger:
    def __init__(self, directory):
        directory = Path(directory).absolute()
        source = Path(__file__).resolve().parents[2]
        if directory.resolve() == source or source in directory.resolve().parents:
            raise OpsError("Ops state must be outside the source checkout")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink():
            raise OpsError("Unsafe ops state directory")
        directory.chmod(0o700)
        self.lock_path = directory / "monitor.lock"
        path = directory / "alerts.sqlite"
        for filename in (path, self.lock_path):
            private_file(filename)
        self.db = sqlite3.connect(path, timeout=0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=EXTRA")
        self.db.execute("PRAGMA fullfsync=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                id INTEGER PRIMARY KEY CHECK(id=1), episode TEXT NOT NULL,
                device INTEGER, channel TEXT, next_attempt REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS alerts (
                marker TEXT PRIMARY KEY, episode TEXT NOT NULL, thresholds TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL
                    CHECK(status IN ('pending','sending','sent','cancelled')),
                message_id TEXT,
                CHECK((status='sent' AND message_id IS NOT NULL) OR
                      (status!='sent' AND message_id IS NULL))
            );
        """)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta(id,episode) VALUES(1,?)", (uuid.uuid4().hex,))

    def close(self):
        self.db.close()

    @contextmanager
    def locked(self):
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise OpsError("Another disk monitor owns the delivery lock") from None
            yield
        finally:
            os.close(descriptor)

    def observe(self, reading, channel_id, test=False):
        with self.db:
            meta = self.db.execute("SELECT * FROM meta WHERE id=1").fetchone()
            if meta["channel"] is not None and meta["channel"] != channel_id:
                raise OpsError("Ops channel changed; preserve ledger and review before cutover")
            if meta["device"] is not None and meta["device"] != reading.device:
                raise OpsError("Recordings filesystem changed; operator review required")
            self.db.execute("UPDATE meta SET device=?,channel=? WHERE id=1", (reading.device, channel_id))
            rows = self.db.execute("SELECT * FROM alerts WHERE episode=?", (meta["episode"],)).fetchall()
            if not reading.at_least(REARM):
                if rows:
                    # Retire any stale undelivered intent; recovery must not send an old warning.
                    self.db.execute("UPDATE alerts SET status='cancelled' WHERE episode=? AND status!='sent'",
                                    (meta["episode"],))
                    self.db.execute("UPDATE meta SET episode=?,next_attempt=0 WHERE id=1", (uuid.uuid4().hex,))
                return
            covered = {threshold for row in rows for threshold in json.loads(row["thresholds"])}
            reached = [threshold for threshold in THRESHOLDS if reading.at_least(threshold) and threshold not in covered]
            if not reached:
                return
            marker = "[orebit-ops:%s:%d]" % (meta["episode"], max(reached))
            now = datetime.now(timezone.utc).isoformat()
            heading = "TEST ONLY — SIMULATED disk usage; live alert state unchanged" if test else "Recordings filesystem disk alert"
            content = ("%s\nHost: %s; observed: %s\nFilesystem path: %s; device: %d\n"
                       "Usage: %.2f%%; reached threshold(s): %s%%\n"
                       "Total: %d bytes; used/reserved: %d bytes; available: %d bytes; free: %d bytes\n"
                       "Action: move gameplay recordings and Minari training archives to private object storage elsewhere "
                       "(Backblaze B2 or Cloudflare R2). Migration/deletion is NOT enabled. "
                       "The existing 80%% recording safety guard remains unchanged.\n%s" %
                       (heading, socket.gethostname(), now, reading.path, reading.device, reading.percent,
                        ", ".join(map(str, reached)), reading.total, reading.used, reading.available, reading.free, marker))
            payload = {"content": content, "allowed_mentions": {"parse": []},
                       "nonce": hashlib.sha256(marker.encode()).hexdigest()[:25], "enforce_nonce": True}
            self.db.execute("INSERT INTO alerts VALUES(?,?,?,?, 'pending',NULL)",
                            (marker, meta["episode"], json.dumps(reached), json.dumps(payload)))

    def pending(self):
        return self.db.execute("SELECT * FROM alerts WHERE episode=(SELECT episode FROM meta WHERE id=1) "
                               "AND status IN ('pending','sending') ORDER BY rowid").fetchall()

    def set_status(self, marker, status, message_id=None):
        with self.db:
            self.db.execute("UPDATE alerts SET status=?,message_id=? WHERE marker=?", (status, message_id, marker))


def cycle(ledger, discord, reading, channel_id, test=False, clock=time.time):
    with ledger.locked():
        ledger.observe(reading, channel_id, test)
        pending = ledger.pending()
        result = {"outcome": "sampled", "percent": reading.percent, "total_bytes": reading.total,
                  "used_reserved_bytes": reading.used, "available_bytes": reading.available,
                  "free_bytes": reading.free, "device": reading.device, "path": reading.path,
                  "test": test, "delivered": 0}
        if not pending:
            return result
        now = clock()
        if now < ledger.db.execute("SELECT next_attempt FROM meta WHERE id=1").fetchone()[0]:
            result["outcome"] = "retry_deferred"
            return result
        # Persist cooldown before requests; restart/--once cannot hammer Discord.
        with ledger.db:
            ledger.db.execute("UPDATE meta SET next_attempt=? WHERE id=1", (now + RETRY_SECONDS,))
        discord.verify(channel_id)
        for intent in pending:
            marker = intent["marker"]
            if intent["status"] == "sending":
                identifier = discord.reconcile(channel_id, marker)
                if identifier:
                    ledger.set_status(marker, "sent", identifier)
                    result["delivered"] += 1
                    continue
                raise OpsError("Disk alert outcome uncertain; retained without reposting; owner review required")
            ledger.set_status(marker, "sending")  # Durable BEFORE the POST, like announcements.
            try:
                response = discord.request("/channels/%s/messages" % channel_id, "POST", json.loads(intent["payload"]))
                if not matching_message(response, channel_id, marker):
                    raise OpsError("Disk alert response could not confirm delivery")
            except OpsError as error:
                if error.rejected:
                    ledger.set_status(marker, "pending")
                # Uncertain requests reconcile next scheduled cycle, never blind replay.
                raise
            ledger.set_status(marker, "sent", response["id"])
            result["delivered"] += 1
        return result


def main():
    parser = argparse.ArgumentParser(description="Metadata-only recordings filesystem checker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Read real filesystem and process live persistent alerts")
    mode.add_argument("--test-delivery", type=float, metavar="PERCENT",
                      help="Send clearly labelled synthetic alert using isolated temporary state; no disk filling")
    parser.add_argument("--recordings-path", default=os.environ.get("OREBIT_OPS_RECORDINGS_PATH", DEFAULT_RECORDINGS))
    parser.add_argument("--state-dir", default=os.environ.get("OREBIT_OPS_STATE_DIR", DEFAULT_STATE))
    parser.add_argument("--channel-id", default=os.environ.get("OREBIT_OPS_CHANNEL_ID"))
    args = parser.parse_args()
    if not args.channel_id:
        raise OpsError("Configure the verified private ops channel ID first")
    discord = Discord(token_from_file())
    if args.test_delivery is not None:
        if not math.isfinite(args.test_delivery) or not 70 <= args.test_delivery <= 100:
            raise OpsError("Test delivery percentage must be between 70 and 100")
        total = 1024 ** 4
        used = round(total * args.test_delivery / 100)
        reading = Reading(total, used, total - used, total - used, 0, "SIMULATED (no filesystem read)")
        # Deliberately ignore --state-dir for testing: live state cannot be reset/touched.
        with tempfile.TemporaryDirectory(prefix="orebit-ops-test-") as directory:
            ledger = Ledger(directory)
            try:
                result = cycle(ledger, discord, reading, args.channel_id, test=True)
            finally:
                ledger.close()
    else:
        reading = read_disk(args.recordings_path)
        ledger = Ledger(args.state_dir)
        try:
            result = cycle(ledger, discord, reading, args.channel_id)
        finally:
            ledger.close()
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except OpsError as error:
        print(json.dumps({"outcome": "error", "error": str(error)}))
        raise SystemExit(1)
    except Exception:
        print(json.dumps({"outcome": "error", "error": "Disk monitor failed; live ledger retained; no credential details logged"}))
        raise SystemExit(1)
