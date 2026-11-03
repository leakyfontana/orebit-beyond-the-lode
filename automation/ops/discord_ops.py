"""Private ops-only Discord REST client; never imports or changes announcements."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

GUILD = "1565550697070596216"
BOT = "1565565791590420520"
VIEW, SEND, HISTORY = 1 << 10, 1 << 11, 1 << 16
BOT_PERMISSIONS = VIEW | SEND | HISTORY
MANAGE_CHANNELS, MANAGE_ROLES, ADMIN = 1 << 4, 1 << 28, 1 << 3
SNOWFLAKE = re.compile(r"[1-9][0-9]{0,19}\Z")


class OpsError(Exception):
    """Only locally authored, credential-free messages cross the CLI boundary."""

    def __init__(self, message, rejected=False):
        super().__init__(message)
        self.rejected = rejected


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Discord:
    def __init__(self, token, sleep=time.sleep, opener=None):
        if not token or any(c.isspace() for c in token):
            raise OpsError("Invalid existing Discord credential")
        self.token, self.sleep = token, sleep
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def request(self, path, method="GET", body=None):
        waited = 0
        for attempt in range(4):
            request = urllib.request.Request(
                "https://discord.com/api/v10" + path,
                data=None if body is None else json.dumps(body).encode(), method=method,
                headers={"Authorization": "Bot " + self.token,
                         "Content-Type": "application/json",
                         "User-Agent": "DiscordBot (Orebit Ops, 1.0)"})
            try:
                with self.opener.open(request, timeout=20) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                status = error.code
                if status == 429:
                    try:
                        delay = json.load(error)["retry_after"]
                    except (ValueError, KeyError, TypeError):
                        raise OpsError("Invalid Discord rate limit; retry next scheduled cycle", True) from None
                    finally:
                        error.close()
                    if (type(delay) not in (int, float) or not math.isfinite(delay) or delay < 0
                            or delay > 60 or waited + max(1, delay) > 120 or attempt == 3):
                        raise OpsError("Discord rate limit retry bound exceeded", True)
                    delay = max(1, delay)
                    waited += delay
                    self.sleep(delay)
                    continue
                error.close()
                # Never replay a POST/PATCH after ambiguous HTTP/network outcomes.
                if method == "GET" and status >= 500 and attempt < 2:
                    self.sleep(2 ** attempt)
                    continue
                raise OpsError("Discord HTTP %d; operation not confirmed" % status,
                               400 <= status < 500 and status != 408) from None
            except (OSError, ValueError):
                raise OpsError("Discord request outcome is uncertain") from None
        raise OpsError("Discord retry bound exceeded", True)

    def identity(self):
        user = self.request("/users/@me")
        if user.get("id") != BOT or user.get("bot") is not True:
            raise OpsError("Token is not the permitted Orebit bot")
        return user

    def guild_access(self):
        self.identity()
        roles = self.request("/guilds/%s/roles" % GUILD)
        member = self.request("/guilds/%s/members/%s" % (GUILD, BOT))
        permissions = 0
        for role in roles:
            if role["id"] == GUILD or role["id"] in member["roles"]:
                permissions |= int(role["permissions"])
        return roles, permissions

    def find_channel(self):
        channels = self.request("/guilds/%s/channels" % GUILD)
        matches = [c for c in channels if c.get("name") == "ops-alerts"]
        if len(matches) > 1:
            raise OpsError("Multiple ops-alerts channels; owner must resolve ambiguity")
        return matches[0] if matches else None

    def verify(self, channel_id):
        if not SNOWFLAKE.fullmatch(channel_id):
            raise OpsError("Invalid ops channel ID")
        roles, _ = self.guild_access()
        channel = self.request("/channels/" + channel_id)
        verify_channel(channel, roles)
        if channel.get("id") != channel_id:
            raise OpsError("Discord returned a different ops channel identity")
        return channel

    def reconcile(self, channel_id, marker):
        before = None
        # Never turn a bounded/partial scan into permission to replay an uncertain POST.
        for _ in range(5):
            path = "/channels/%s/messages?limit=100" % channel_id
            if before:
                path += "&before=" + before
            page = self.request(path)
            if not isinstance(page, list) or len(page) > 100:
                raise OpsError("Invalid ops history; uncertain delivery retained")
            if not page:
                return None
            ids = []
            for message in page:
                identifier = message.get("id", "")
                if (not SNOWFLAKE.fullmatch(identifier) or message.get("channel_id") != channel_id
                        or (before and int(identifier) >= int(before))):
                    raise OpsError("Invalid ops history identity")
                ids.append(identifier)
                if matching_message(message, channel_id, marker):
                    return identifier
            before = min(ids, key=int)
        raise OpsError("Ops history scan bound reached; uncertain delivery retained")


def matching_message(message, channel_id, marker):
    return (isinstance(message, dict) and SNOWFLAKE.fullmatch(message.get("id", "")) is not None
            and message.get("channel_id") == channel_id and message.get("type") == 0
            and not message.get("webhook_id") and message.get("author", {}).get("id") == BOT
            and message.get("author", {}).get("bot") is True
            and message.get("content", "").endswith("\n" + marker))


def overwrites(roles):
    if any(role["id"] == GUILD and int(role["permissions"]) & ADMIN for role in roles):
        raise OpsError("Everyone has Administrator; channel privacy cannot be enforced")
    entries = [{"id": GUILD, "type": 0, "allow": "0", "deny": str(VIEW)},
               {"id": BOT, "type": 1, "allow": str(BOT_PERMISSIONS), "deny": "0"}]
    entries.extend({"id": role["id"], "type": 0, "allow": str(BOT_PERMISSIONS), "deny": "0"}
                   for role in roles if role["id"] != GUILD and int(role["permissions"]) & ADMIN)
    return entries


def verify_channel(channel, roles):
    if (channel.get("guild_id") != GUILD or channel.get("type") != 0
            or channel.get("name") != "ops-alerts" or channel.get("parent_id") is not None):
        raise OpsError("Destination is not the standalone private ops text channel")
    expected = {(o["id"], o["type"]): (int(o["allow"]), int(o["deny"])) for o in overwrites(roles)}
    actual = {(o["id"], o["type"]): (int(o["allow"]), int(o["deny"]))
              for o in channel.get("permission_overwrites", [])}
    if actual != expected or len(actual) != len(channel.get("permission_overwrites", [])):
        raise OpsError("Ops privacy overwrites differ; owner must repair before sending")
    # Administrator roles and the guild owner bypass overwrites by Discord design.


def token_from_file():
    try:
        return Path(os.environ.get("OREBIT_DISCORD_TOKEN_FILE",
                    "/var/lib/orebit-bot/credentials/discord-token")).read_text().strip()
    except OSError:
        raise OpsError("Existing Discord token file is unavailable") from None


def main():
    parser = argparse.ArgumentParser(description="Inspect or explicitly configure private #ops-alerts")
    parser.add_argument("--apply", action="store_true", help="Create/repair channel (requires operator approval)")
    args = parser.parse_args()
    discord = Discord(token_from_file())
    roles, permissions = discord.guild_access()
    channel = discord.find_channel()
    administrator = bool(permissions & ADMIN)
    if args.apply:
        required = MANAGE_CHANNELS | (MANAGE_ROLES if channel else 0)
        if not administrator and permissions & required != required:
            raise OpsError("Channel configuration lacks required Manage Channels/Manage Permissions access")
        if not administrator and permissions & BOT_PERMISSIONS != BOT_PERMISSIONS:
            raise OpsError("Bot lacks guild permissions needed for initial overwrites")
        body = {"name": "ops-alerts", "type": 0, "parent_id": None,
                "topic": "Private infrastructure alerts; no gameplay announcements or archive contents.",
                "permission_overwrites": overwrites(roles)}
        if channel:
            # PATCH requires Manage Roles when changing permission_overwrites.
            channel = discord.request("/channels/" + channel["id"], "PATCH", body)
        else:
            channel = discord.request("/guilds/%s/channels" % GUILD, "POST", body)
        channel = discord.verify(channel["id"])
    valid = False
    if channel:
        try:
            verify_channel(channel, roles)
            valid = True
        except OpsError:
            pass
    print(json.dumps({"bot_id": BOT, "guild_id": GUILD, "channel_id": channel["id"] if channel else None,
                      "private_configuration_valid": valid, "administrator": administrator,
                      "manage_channels": bool(permissions & MANAGE_CHANNELS),
                      "manage_permissions": bool(permissions & MANAGE_ROLES),
                      "admin_role_ids": [r["id"] for r in roles if int(r["permissions"]) & ADMIN]}))


if __name__ == "__main__":
    try:
        main()
    except OpsError as error:
        print(json.dumps({"outcome": "error", "error": str(error)}))
        raise SystemExit(1)
    except Exception:
        print(json.dumps({"outcome": "error", "error": "Ops configuration failed; no credential details logged"}))
        raise SystemExit(1)
