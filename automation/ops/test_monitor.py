import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

from discord_ops import (ADMIN, BOT, BOT_PERMISSIONS, Discord, GUILD, OpsError, VIEW,
                         overwrites, verify_channel)
from monitor import Ledger, Reading, cycle

CHANNEL = "1565584282389454880"


def reading(percent, device=7):
    return Reading(10000, percent * 100, (100 - percent) * 100,
                   (100 - percent) * 100, device, "/recordings")


class DiscordStore:
    """Deterministic remote accept/reject/ambiguous outcomes, backed by message identities."""
    def __init__(self):
        self.messages = []
        self.outcome = "accept"
        self.posts = 0
        self.checks = 0
        self.scans = 0

    def verify(self, channel):
        self.checks += 1

    def request(self, path, method, body):
        self.posts += 1
        if self.outcome == "reject":
            raise OpsError("explicit HTTP 403", rejected=True)
        message = {"id": str(100 + len(self.messages)), "channel_id": CHANNEL,
                   "type": 0, "author": {"id": BOT, "bot": True}, **body}
        self.messages.append(message)
        if self.outcome == "accepted_then_disconnected":
            raise OpsError("response lost")
        if self.outcome == "not_accepted_but_uncertain":
            self.messages.pop()
            raise OpsError("request outcome unknown")
        return message

    def reconcile(self, channel, marker):
        self.scans += 1
        for message in self.messages:
            if message["content"].endswith("\n" + marker):
                return message["id"]
        return None


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = Ledger(self.directory.name)
        self.discord = DiscordStore()
        self.now = 1000

    def tearDown(self):
        self.ledger.close()
        self.directory.cleanup()

    def tick(self, percent, **kwargs):
        result = cycle(self.ledger, self.discord, reading(percent), CHANNEL,
                       clock=lambda: self.now, **kwargs)
        self.now += 300
        return result

    def restart(self):
        self.ledger.close()
        self.ledger = Ledger(self.directory.name)

    def test_exact_thresholds_and_persistent_dedup(self):
        for percent in (0, 64, 65, 69):
            self.assertEqual(self.tick(percent)["delivered"], 0)
        self.assertEqual(self.discord.checks, 0)
        for threshold in (70, 80, 90, 95):
            self.assertEqual(self.tick(threshold)["delivered"], 1)
            self.restart()
            self.assertEqual(self.tick(threshold)["delivered"], 0)
        self.assertEqual(self.discord.posts, 4)
        self.assertIn("reached threshold(s): 95%", self.discord.messages[-1]["content"])
        self.assertEqual(self.tick(100)["delivered"], 0)

    def test_jump_coalesces_all_reached_thresholds(self):
        self.assertEqual(self.tick(96)["delivered"], 1)
        row = self.ledger.db.execute("SELECT thresholds,status FROM alerts").fetchone()
        self.assertEqual(json.loads(row["thresholds"]), [70, 80, 90, 95])
        self.assertEqual(row["status"], "sent")
        self.assertIn("available: 400 bytes", self.discord.messages[0]["content"])
        self.assertIn("Minari training archives", self.discord.messages[0]["content"])
        self.assertEqual(self.tick(99)["delivered"], 0)

    def test_hysteresis_only_rearms_strictly_below_65(self):
        self.tick(95)
        for percent in (80, 70, 69, 65, 95):
            self.assertEqual(self.tick(percent)["delivered"], 0)
        self.tick(64)
        self.restart()
        self.assertEqual(self.tick(70)["delivered"], 1)
        self.assertEqual(self.discord.posts, 2)
        markers = self.ledger.db.execute("SELECT marker FROM alerts").fetchall()
        self.assertNotEqual(markers[0][0], markers[1][0])

    def test_explicit_failure_does_not_mark_delivered_and_cooldown_survives_restart(self):
        self.discord.outcome = "reject"
        with self.assertRaises(OpsError):
            self.tick(70)
        self.assertEqual(self.ledger.pending()[0]["status"], "pending")
        self.restart()
        self.now = 1100
        self.assertEqual(self.tick(70)["outcome"], "retry_deferred")
        self.assertEqual(self.discord.posts, 1)
        self.discord.outcome = "accept"
        self.now = 1300
        self.assertEqual(self.tick(70)["delivered"], 1)
        self.assertEqual(self.discord.posts, 2)

    def test_accepted_response_loss_reconciles_after_restart_without_duplicate(self):
        self.discord.outcome = "accepted_then_disconnected"
        with self.assertRaises(OpsError):
            self.tick(80)
        self.assertEqual(self.ledger.pending()[0]["status"], "sending")
        self.restart()
        self.now += 300
        self.assertEqual(self.tick(80)["delivered"], 1)
        self.assertEqual(self.discord.posts, 1)
        self.assertEqual(self.discord.scans, 1)
        self.assertEqual(self.ledger.pending(), [])

    def test_uncertain_absent_message_is_never_blindly_replayed(self):
        self.discord.outcome = "not_accepted_but_uncertain"
        with self.assertRaises(OpsError):
            self.tick(70)
        self.restart()
        for _ in range(3):
            self.now += 300
            with self.assertRaises(OpsError):
                self.tick(70)
        self.assertEqual(self.discord.posts, 1)
        self.assertEqual(self.ledger.pending()[0]["status"], "sending")
        self.tick(64)
        self.assertEqual(self.ledger.pending(), [])
        self.discord.outcome = "accept"
        self.assertEqual(self.tick(70)["delivered"], 1)

    def test_recovery_cancels_rejected_stale_warning(self):
        self.discord.outcome = "reject"
        with self.assertRaises(OpsError):
            self.tick(90)
        self.assertEqual(self.tick(64)["delivered"], 0)
        self.assertEqual(self.discord.posts, 1)
        self.discord.outcome = "accept"
        self.assertEqual(self.tick(80)["delivered"], 1)
        self.assertIn("70, 80%", self.discord.messages[0]["content"])
        self.assertNotIn("90%", self.discord.messages[0]["content"])

    def test_channel_or_filesystem_change_fails_without_changing_state(self):
        self.tick(70)
        before = list(self.ledger.db.execute("SELECT * FROM meta").fetchone())
        for sample, channel in ((reading(80, 8), CHANNEL), (reading(80), "123")):
            with self.assertRaises(OpsError):
                cycle(self.ledger, self.discord, sample, channel, clock=lambda: self.now)
            self.assertEqual(list(self.ledger.db.execute("SELECT * FROM meta").fetchone()), before)
        self.assertEqual(self.discord.posts, 1)

    def test_reserved_blocks_match_recording_guard_and_fractional_boundary(self):
        sample = Reading(1000, 700, 300, 400, 7, "/recordings")
        self.assertEqual(sample.percent, 70)
        self.assertTrue(sample.at_least(70))
        self.assertFalse(Reading(1001, 700, 301, 400, 7, "/recordings").at_least(70))
        with self.assertRaises(OpsError):
            Reading(1000, 600, 300, 400, 7, "/recordings")

    def test_state_private_and_isolated_test_label(self):
        self.tick(95, test=True)
        self.assertIn("TEST ONLY — SIMULATED", self.discord.messages[0]["content"])
        self.assertEqual(self.discord.messages[0]["allowed_mentions"], {"parse": []})
        self.assertEqual(Path(self.directory.name).stat().st_mode & 0o777, 0o700)
        self.assertEqual((Path(self.directory.name) / "alerts.sqlite").stat().st_mode & 0o777, 0o600)

    def test_concurrent_monitor_cannot_send(self):
        second = Ledger(self.directory.name)
        try:
            with self.ledger.locked():
                with self.assertRaises(OpsError):
                    cycle(second, self.discord, reading(95), CHANNEL)
            self.assertEqual(self.discord.posts, 0)
        finally:
            second.close()


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.roles = [{"id": GUILD, "permissions": "0"}, {"id": "42", "permissions": str(ADMIN)}]
        self.channel = {"id": CHANNEL, "guild_id": GUILD, "name": "ops-alerts", "type": 0,
                        "parent_id": None, "permission_overwrites": overwrites(self.roles)}

    def test_explicit_everyone_deny_bot_allow_admin_visibility(self):
        verify_channel(self.channel, self.roles)
        self.assertEqual(self.channel["permission_overwrites"][0]["deny"], str(VIEW))
        self.assertEqual(self.channel["permission_overwrites"][1]["allow"], str(BOT_PERMISSIONS))
        self.assertEqual(self.channel["permission_overwrites"][2]["id"], "42")

    def test_public_or_extra_member_or_category_or_missing_admin_fails_closed(self):
        changes = [[], self.channel["permission_overwrites"] +
                   [{"id": "77", "type": 1, "allow": str(VIEW), "deny": "0"}],
                   self.channel["permission_overwrites"][:-1]]
        for entries in changes:
            with self.assertRaises(OpsError):
                verify_channel({**self.channel, "permission_overwrites": entries}, self.roles)
        with self.assertRaises(OpsError):
            verify_channel({**self.channel, "parent_id": "123"}, self.roles)

    def test_everyone_administrator_is_rejected_before_constructing_creation_payload(self):
        with self.assertRaises(OpsError):
            overwrites([{"id": GUILD, "permissions": str(ADMIN)}])


class RateLimitTests(unittest.TestCase):
    def test_429_waits_are_bounded_and_not_zero_delay_spam(self):
        class Limited:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise urllib.error.HTTPError(request.full_url, 429, "limited", {},
                                             io.BytesIO(b'{"retry_after":0}'))
        opener, waits = Limited(), []
        discord = Discord("test-token", sleep=waits.append, opener=opener)
        with self.assertRaises(OpsError) as caught:
            discord.request("/users/@me")
        self.assertTrue(caught.exception.rejected)
        self.assertEqual(opener.calls, 4)
        self.assertEqual(waits, [1, 1, 1])

    def test_post_server_error_is_not_retried(self):
        class Failed:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise urllib.error.HTTPError(request.full_url, 503, "unavailable", {}, io.BytesIO())
        opener = Failed()
        discord = Discord("test-token", sleep=lambda _: None, opener=opener)
        with self.assertRaises(OpsError) as caught:
            discord.request("/channels/123/messages", "POST", {"content": "test"})
        self.assertFalse(caught.exception.rejected)
        self.assertEqual(opener.calls, 1)


if __name__ == "__main__":
    unittest.main()
