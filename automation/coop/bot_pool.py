#!/usr/bin/env python3
"""Provision dedicated ordinary accounts for the server-owned PvP bot registry."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from server import Store, USERNAME


class ProvisionError(Exception):
    pass


def read_accounts(path, prefix):
    """Never follow a credentials symlink or accept a publicly readable file."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "r", encoding="utf-8") as source:
        metadata = os.fstat(source.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.getuid()):
            raise ProvisionError("Accounts must be an owner-held regular file with mode 0600.")
        try:
            raw = source.read(65537)
            if len(raw) > 65536:
                raise ValueError("oversized")
            document = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProvisionError("Accounts file is not a valid private account document.") from None
    if (not isinstance(document, dict) or set(document) != {"schema_version", "accounts"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or not isinstance(document["accounts"], list) or len(document["accounts"]) != 5):
        raise ProvisionError("Accounts file must contain schema_version 1 and five accounts.")
    accounts = document["accounts"]
    for account in accounts:
        if (not isinstance(account, dict) or set(account) != {"slot", "user_id", "username", "password"}
                or type(account["slot"]) is not int or not 1 <= account["slot"] <= 5
                or type(account["user_id"]) is not int or not 1 <= account["user_id"] < 2**63
                or account["username"] != prefix + str(account["slot"])
                or not isinstance(account["password"], str) or not 8 <= len(account["password"]) <= 128):
            raise ProvisionError("Accounts file has invalid account fields.")
    if ({a["slot"] for a in accounts} != set(range(1, 6))
            or len({a["user_id"] for a in accounts}) != 5):
        raise ProvisionError("Accounts file slots and user IDs must be unique.")
    return sorted(accounts, key=lambda a: a["slot"])


def publish_accounts(path, accounts):
    """Publish once, before commit; a rolled-back provision can reuse this file."""
    descriptor, temporary = tempfile.mkstemp(prefix=".pvp-accounts-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump({"schema_version": 1, "accounts": accounts}, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        # Unlike replace(), link() cannot overwrite credentials created elsewhere.
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def provision(db_path, accounts_path, prefix="Orebit_Bot_"):
    names = [prefix + str(slot) for slot in range(1, 6)]
    if not all(USERNAME.fullmatch(name) for name in names):
        raise ProvisionError("Prefix must produce valid 3-24 character account usernames.")
    database = Path(db_path).expanduser().resolve()
    path = Path(accounts_path).expanduser().absolute()
    if path.resolve() == database:
        raise ProvisionError("Accounts and database paths must be different.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = Store(str(database))
    hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
    try:
        def create(db):
            # Serialize both name ownership and credential publication with other
            # provisioners and with normal HTTP account creation.
            db.execute("BEGIN IMMEDIATE")
            accounts = read_accounts(path, prefix)
            registered = {(r["slot"], r["user_id"]) for r in db.execute("SELECT slot,user_id FROM pvp_bot_accounts")}
            new_file = accounts is None
            if new_file:
                if registered:
                    raise ProvisionError("Registered bots already exist; restore their private accounts file instead.")
                for name in names:
                    if db.execute("SELECT 1 FROM users WHERE username=?", (name.lower(),)).fetchone():
                        raise ProvisionError("A requested bot username already belongs to an account; refusing adoption.")
                next_id = db.execute("SELECT coalesce(max(id),0)+1 FROM users").fetchone()[0]
                accounts = [{"slot": slot, "user_id": next_id + slot - 1,
                             "username": name, "password": secrets.token_urlsafe(32)}
                            for slot, name in enumerate(names, 1)]
            expected = {(a["slot"], a["user_id"]) for a in accounts}
            if not registered <= expected:
                raise ProvisionError("Registry does not match the private accounts file.")
            for account in accounts:
                user = db.execute("SELECT * FROM users WHERE id=?", (account["user_id"],)).fetchone()
                if user is not None:
                    if ((account["slot"], account["user_id"]) not in registered
                            or user["username"] != account["username"].lower()
                            or user["display_name"] != account["username"]):
                        raise ProvisionError("Existing account is not this registered bot; refusing adoption.")
                    try:
                        hasher.verify(user["password_hash"], account["password"])
                    except (VerificationError, InvalidHashError, TypeError):
                        raise ProvisionError("Private credentials do not match the registered bot account.") from None
                else:
                    if db.execute("SELECT 1 FROM users WHERE username=?", (account["username"].lower(),)).fetchone():
                        raise ProvisionError("A requested bot username already belongs to an account; refusing adoption.")
                    db.execute("INSERT INTO users(id,username,display_name,password_hash,created_at) VALUES(?,?,?,?,?)",
                               (account["user_id"], account["username"].lower(), account["username"],
                                hasher.hash(account["password"]), int(time.time())))
                    db.execute("INSERT INTO pvp_bot_accounts(user_id,slot) VALUES(?,?)", (account["user_id"], account["slot"]))
            if new_file:
                publish_accounts(path, accounts)
            return len(accounts)
        return store._run(create)
    finally:
        store.connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("provision", help="Provision five private PvP-only bot accounts")
    command.add_argument("--db", required=True)
    command.add_argument("--accounts", required=True)
    command.add_argument("--prefix", default="Orebit_Bot_")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        count = provision(args.db, args.accounts, args.prefix)
    except (ProvisionError, OSError) as error:
        # Error messages never interpolate document values, passwords or tokens.
        parser.exit(1, f"Provisioning refused: {error}\n")
    print(f"Provisioned {count} dedicated PvP bot accounts; private credentials mode 0600.")


if __name__ == "__main__":
    main()
