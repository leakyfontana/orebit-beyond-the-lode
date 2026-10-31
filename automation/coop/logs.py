#!/usr/bin/env python3
"""Query retained co-op events without importing or starting the service.

Only known telemetry fields are emitted. Records are selected by timestamp, not
filesystem order, and printed oldest first. A nonzero exit status means the
result may be incomplete: unreadable/rotating files and invalid records are
reported on stderr, never with their potentially sensitive contents.
"""

import argparse
from collections import Counter
import heapq
import json
import os
from pathlib import Path
import re
import stat
import sys

from telemetry import LEVELS, parse_timestamp, safe_record


DEFAULT_DIRECTORY = "/var/log/orebit-coop"
MAX_LINE_BYTES = 65536
MAX_LIMIT = 10000
ARCHIVE_NAME = re.compile(r"events\.jsonl(?:\.([1-9][0-9]*))?\Z")




def snapshot_files(directory, problems):
    """Capture identities before reading so rotations cannot silently swap files."""
    files = []
    try:
        before = os.stat(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                match = ARCHIVE_NAME.fullmatch(entry.name)
                if match is None:
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    problems["file disappeared or could not be inspected"] += 1
                    continue
                if not stat.S_ISREG(info.st_mode):
                    problems["nonregular log file ignored"] += 1
                    continue
                number = int(match.group(1) or 0)
                files.append((number, Path(directory) / entry.name, info))
        after = os.stat(directory)
        if (before.st_dev, before.st_ino, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_mtime_ns
        ):
            problems["log directory changed during discovery"] += 1
    except OSError:
        problems["log directory could not be read"] += 1
    if not files and not problems:
        problems["no retained log files found"] += 1
    return sorted(files, key=lambda item: item[0], reverse=True)


def read_records(path, expected, problems):
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        problems["log file disappeared or could not be opened"] += 1
        return
    with os.fdopen(descriptor, "rb") as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            problems["log rotated before it could be read"] += 1
            return
        remaining = expected.st_size
        oversized = False
        while remaining:
            try:
                raw = source.readline(min(MAX_LINE_BYTES + 1, remaining))
            except OSError:
                problems["log file could not be read"] += 1
                return
            if not raw:
                problems["log truncated while being read"] += 1
                break
            remaining -= len(raw)
            ended = raw.endswith(b"\n")
            if oversized or len(raw) > MAX_LINE_BYTES:
                if not oversized:
                    problems["oversized record ignored"] += 1
                oversized = not ended
                continue
            if not ended:
                problems["truncated or unterminated record ignored"] += 1
                continue
            try:
                value = json.loads(raw)
                yield safe_record(value)
            except (ValueError, TypeError, RecursionError, OverflowError):
                problems["malformed or unsafe record ignored"] += 1
        after = os.fstat(source.fileno())
        if after.st_size < expected.st_size or (
            after.st_size == expected.st_size and after.st_mtime_ns != expected.st_mtime_ns
        ):
            problems["log changed while being read"] += 1


def limit_argument(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("limit must be an integer") from error
    if not 1 <= number <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"limit must be between 1 and {MAX_LIMIT}")
    return number


def since_argument(value):
    try:
        return parse_timestamp(value)
    except (ValueError, OverflowError) as error:
        raise argparse.ArgumentTypeError("since must be an ISO8601 timestamp") from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=DEFAULT_DIRECTORY, help="retained-log directory (default: %(default)s)")
    parser.add_argument("--request-id")
    parser.add_argument("--session-id")
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--event", help="exact event name")
    parser.add_argument("--level", type=str.upper, choices=sorted(LEVELS), help="exact severity level")
    parser.add_argument("--since", type=since_argument, help="inclusive ISO8601 timestamp; missing timezone means UTC")
    parser.add_argument("--limit", type=limit_argument, default=100, help=f"most recent matches, 1-{MAX_LIMIT} (default: %(default)s)")
    args = parser.parse_args(argv)
    filters = {
        key: getattr(args, key)
        for key in ("request_id", "session_id", "user_id", "event", "level")
        if getattr(args, key) is not None
    }
    problems = Counter()
    files = snapshot_files(args.directory, problems)
    recent = []
    seen_files = set()
    sequence = 0
    for _, path, info in files:
        identity = (info.st_dev, info.st_ino)
        if identity in seen_files:
            problems["duplicate file identity ignored during rotation"] += 1
            continue
        seen_files.add(identity)
        for timestamp, record in read_records(path, info, problems):
            if args.since is not None and timestamp < args.since:
                continue
            if any(record.get(key) != value for key, value in filters.items()):
                continue
            sequence += 1
            item = (timestamp, sequence, record)
            if len(recent) < args.limit:
                heapq.heappush(recent, item)
            elif item[:2] > recent[0][:2]:
                heapq.heapreplace(recent, item)
    for _, _, record in sorted(recent):
        print(json.dumps(record, separators=(",", ":"), ensure_ascii=True, allow_nan=False))
    for reason, count in sorted(problems.items()):
        print(f"logs: {reason}: {count}; results may be incomplete", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
    except OSError:
        print("logs: log files could not be queried; results may be incomplete", file=sys.stderr)
        raise SystemExit(1)
