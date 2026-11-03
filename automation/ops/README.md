# Private recordings-filesystem alerts

This independent Python 3 standard-library monitor checks the filesystem holding VPS gameplay recordings. It uses the existing **Orebit Intake** bot (`1565565791590420520`) in guild `1565550697070596216`, not a webhook or a new credential. It does not change release announcements, bot intake, training policies, gameplay events, or capture admission. No archive listing, reading, upload, deletion, retention change, or migration is implemented.

## Behavior and safety

- The systemd timer runs a real `monitor.py --once` check five minutes after the previous invocation finishes (also two minutes after boot). Low/unchanged samples cause **zero Discord requests**.
- Thresholds are **70%, 80%, 90%, 95% inclusive**. A sample crossing several thresholds sends one message naming every newly reached threshold, not a burst of four messages. Further growth sends only newly reached thresholds. Falling to 65–69% does not rearm; **strictly below 65%** starts a new episode. No recovery message is sent.
- Metrics come from `statvfs` only: total bytes, available-to-unprivileged bytes, free bytes, used/reserved bytes, percentage, filesystem device, host, observation time, and measured path. Usage is `(total - f_bavail * f_frsize) / total`, matching the capture guard's reserved-space-aware basis, rather than silently monitoring a checkout or another mount. The existing **80% recording guard and reserve remain unchanged**.
- Alerts instruct the admin to move gameplay and Minari training archives elsewhere. They contain no player data or archive filenames, disable mentions, and go only to verified private `#ops-alerts`.
- `/var/lib/orebit-bot/ops/alerts.sqlite` is a private `0600` SQLite rollback-journal outbox, in a `0700` directory, with `synchronous=EXTRA`, full-fsync request, atomic commits, and a process lock. Keep this ledger across upgrades/restarts. It records each episode and thresholds before delivery, marks `sending` durably before POST, and marks `sent` **only after a matching bot message is confirmed**. Explicit HTTP rejection leaves the alert pending. Cooldown is persisted before network access, preventing restart/`--once` request loops (minimum five minutes between network attempts).
- Like announcements, an ambiguous POST is never blindly retried after Discord's short nonce window. The next scheduled attempt reconciles bot-authored history markers (at most five pages of 100 messages); confirmed markers mark the intent delivered. An uncertain or bounded scan without a marker remains `sending`, visibly failing the unit for operator review, rather than fabricating success or creating duplicates. A below-65% reading retires undelivered stale warnings and rearms normally. Do not reset the ledger to resolve delivery uncertainty.
- HTTP requests time out after 20 seconds. Rate limits permit at most four attempts, minimum one-second waits, at most 60 seconds per wait and 120 seconds cumulative wait; longer limits stop the invocation. GET 5xx retries are bounded; POST/PATCH transport/5xx outcomes are not automatically replayed. The timer does not retry the entire cycle rapidly. The service has a five-minute execution limit; interrupted sends remain durable and uncertain.
- Changing the configured destination or filesystem device fails closed for operator review, rather than silently reusing another destination's dedup state.

The source capture directory and parent are currently `0700 orebit-coop:orebit-coop`. The bot cannot traverse that parent. The unit therefore binds the **exact capture directory read-only** at `/run/orebit-ops-recordings` inside its private mount namespace. `statvfs` of the mount root requires traversal of `/run`, not traversal of the inaccessible original parent. Source permissions remain `0700`; the bot cannot enumerate/read archives. If recording storage moves or gains a dedicated mount, update `BindReadOnlyPaths` to that actual directory and review the filesystem identity before restarting. Do not replace this with monitoring `/`, and do not loosen archive permissions.

## Discord access: blocked until owner action

Read-only VPS evidence collected 2026-11-02 using the existing credential:

- `/users/@me`: bot **Orebit Intake**, ID `1565565791590420520`, `bot=true`.
- Guild roles and bot membership are readable. Effective guild permissions: `2248473465835073`; **no Administrator, no Manage Channels, no Manage Roles**.
- No visible `ops-alerts` channel was returned; Discord can omit inaccessible channels, so the owner must check for any hidden existing channel before creating one. No Administrator roles were returned.
- `/var/lib/orebit-coop/captures` exists and is `0700`; attempting metadata access as `orebit-bot` fails at the private parent, motivating the read-only mount above.

No channel was created, message sent, unit installed/restarted, or archive opened for this evidence.

### Least-privilege automated route

An owner temporarily grants the existing bot **Manage Channels** at guild level (not Administrator). Initial [Create Guild Channel](https://docs.discord.com/developers/resources/guild#create-guild-channel) with complete `permission_overwrites` requires **Manage Channels only**; every allowed/denied permission must already be held by the bot at guild level. Our bot needs View Channel, Send Messages, Read Message History (bitfield `68608`); there is no attachment/embed/mention-everyone requirement.

Editing existing channel overwrites requires **Manage Permissions / Manage Roles**, in addition to Manage Channels for this configuration operation ([Modify Channel](https://docs.discord.com/developers/resources/channel#modify-channel), [Edit Channel Permissions](https://docs.discord.com/developers/resources/channel#edit-channel-permissions)). Do not grant that permission for first-time creation unnecessarily. After creation/repair, revoke temporary management grants; monitoring only needs the channel permissions above and read-only guild role/member access.

The inspect command is read-only. `--apply` is the only channel-changing command, and is **not part of installation or startup**. It refuses ambiguous duplicate names, checks guild/bot identities, creates the channel with private overwrites in the initial request (never creates publicly then hides it), or replaces existing overwrites explicitly. It puts the channel outside categories, ensuring no future category permission sync can expose it.

### Manual owner route (requires no bot management grant)

In the guild identified above, the owner creates a standalone text channel named exactly **ops-alerts**, with no category. Configure these **exact** channel overwrites; remove all other member/role overwrites:

| Principal | Type | Allow | Deny |
| --- | --- | --- | --- |
| `@everyone` (role ID `1565550697070596216`) | role | none (`0`) | View Channel (`1024`) |
| `Orebit Intake` (member ID `1565565791590420520`) | member | View Channel, Send Messages, Read Message History (`68608`) | none (`0`) |
| Each existing role with Discord Administrator permission | role | View Channel, Send Messages, Read Message History (`68608`) | none (`0`) |

There are currently no Administrator roles, so the first two rows suffice. The guild owner always retains visibility; Administrator roles bypass channel overwrites by Discord design ([permission hierarchy](https://docs.discord.com/developers/topics/permissions#permission-overwrites)). Do not grant Administrator to the bot or create a new admin role for this feature. Non-admin members must not receive View Channel. If genuine admin roles are later added/removed, rerun inspection and repair the exact configuration before enabling delivery; the sender deliberately fails closed when overwrites drift. `@everyone` holding Administrator is explicitly rejected as impossible to keep private.

Copy the resulting channel ID into `/etc/orebit-ops.env` as `OREBIT_OPS_CHANNEL_ID=ACTUAL_ID`. The runtime checks the name, guild, type, standalone placement, and exact privacy overwrites **before every delivery/reconciliation cycle**, so merely entering a public channel ID cannot leak ops messages.

## Local integrated tests (no Discord or recordings access)

From the checkout root, the integration owner runs:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s automation/ops -p 'test_*.py' -v
```

The deterministic suite covers exact thresholds, jump coalescing, persistent restart dedup, strict recovery hysteresis, explicit rejection/cooldown across restarts, accepted-but-lost responses, uncertain non-delivery without replay, stale cancellation, filesystem/destination identity changes, reserved blocks, privacy overwrite failures, process exclusion, and bounded rate limits/no POST 5xx replay. Temporary SQLite stores and a deterministic remote-message model are isolated from production. No tests or formatters were run during implementation; integrated execution is the parent's responsibility.

## Approved deployment plan and exact commands

**Do not execute channel changes, sends, installation or service changes until the integration owner approves.** No new packages or runtimes are required: VPS `/usr/bin/python3` and its standard-library SQLite are used, consistent with the existing Python authority. The monitor is independent of the bot/training application tree except for its own new directory and existing token file.

1. Have the integration owner run the local suite above and inspect both unit files. Have the guild owner resolve channel permissions by one of the routes above. Do not restart announcements or intake.
2. Stage only the new ops files and units (local checkout root):

```sh
ssh arcmonkeys-prod 'mkdir -p /tmp/orebit-ops-release'
scp automation/ops/discord_ops.py automation/ops/monitor.py automation/ops/test_monitor.py automation/ops/README.md automation/vps/orebit-ops.service automation/vps/orebit-ops.timer arcmonkeys-prod:/tmp/orebit-ops-release/
ssh arcmonkeys-prod 'sudo install -d -m 0755 /opt/orebit-bot/automation/ops && sudo install -m 0644 /tmp/orebit-ops-release/discord_ops.py /tmp/orebit-ops-release/monitor.py /opt/orebit-bot/automation/ops/ && sudo install -d -o orebit-bot -g orebit-queue -m 0700 /var/lib/orebit-bot/ops'
```

3. Inspect Discord read-only (no tokens in arguments/output):

```sh
ssh arcmonkeys-prod 'sudo -u orebit-bot env PYTHONDONTWRITEBYTECODE=1 OREBIT_DISCORD_TOKEN_FILE=/var/lib/orebit-bot/credentials/discord-token /usr/bin/python3 /opt/orebit-bot/automation/ops/discord_ops.py'
```

Only if separately authorized, with the owner's temporary minimum grant, create/repair:

```sh
ssh arcmonkeys-prod 'sudo -u orebit-bot env PYTHONDONTWRITEBYTECODE=1 OREBIT_DISCORD_TOKEN_FILE=/var/lib/orebit-bot/credentials/discord-token /usr/bin/python3 /opt/orebit-bot/automation/ops/discord_ops.py --apply'
```

If a mutation has an uncertain outcome, inspect before trying again; do not loop `--apply`. Confirm `private_configuration_valid=true` and the channel ID; ask the owner to confirm normal members cannot view the channel. Revoke temporary bot management access.

4. On the VPS, substitute the real inspected channel ID once; it is a public identifier, not a credential:

```sh
OPS_CHANNEL_ID=ACTUAL_INSPECTED_CHANNEL_ID
printf 'OREBIT_OPS_CHANNEL_ID=%s\n' "$OPS_CHANNEL_ID" | sudo tee /etc/orebit-ops.env >/dev/null
sudo chmod 0600 /etc/orebit-ops.env
sudo install -m 0644 /tmp/orebit-ops-release/orebit-ops.service /tmp/orebit-ops-release/orebit-ops.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/orebit-ops.service /etc/systemd/system/orebit-ops.timer
```

5. Optional **explicitly authorized test send**, from the VPS with `OPS_CHANNEL_ID` still set:

```sh
sudo -u orebit-bot env PYTHONDONTWRITEBYTECODE=1 OREBIT_DISCORD_TOKEN_FILE=/var/lib/orebit-bot/credentials/discord-token OREBIT_OPS_CHANNEL_ID="$OPS_CHANNEL_ID" /usr/bin/python3 /opt/orebit-bot/automation/ops/monitor.py --test-delivery 95
```

This sends **one clearly labelled TEST ONLY / SIMULATED** message naming 70/80/90/95, using temporary state. It does not measure/fill the filesystem or touch `/var/lib/orebit-bot/ops`, even if `--state-dir` is supplied. Repeating this explicit test sends another labelled test by design. Production dedup remains untouched. Failure is nonzero, never a fake delivery success. Do not use a public test channel: the same private-channel verification always applies.

6. Run one real sample using the installed unit (its command is the actual `--once` CLI, with the private filesystem mount). This can send a **real** warning if thresholds are already reached, so authorize it as a live send:

```sh
sudo systemctl start orebit-ops.service
sudo systemctl status --no-pager orebit-ops.service
sudo journalctl -u orebit-ops.service -n 20 --no-pager
```

Check logged device/total/available metrics against metadata-only `sudo stat -f /var/lib/orebit-coop/captures`; do not list archive files. Confirm there is no permission/mount error and any message is private. The command-line equivalent for an already accessible actual recordings root is:

```sh
OREBIT_OPS_CHANNEL_ID=ACTUAL_ID OREBIT_DISCORD_TOKEN_FILE=/path/to/existing/token python3 automation/ops/monitor.py --once --recordings-path=/actual/recordings --state-dir=/private/persistent/ops
```

Do not run that command as root against the production ledger; the installed service runs as `orebit-bot` and preserves ownership.

7. Only after the real sample succeeds, start periodic checks:

```sh
sudo systemctl enable --now orebit-ops.timer
sudo systemctl list-timers --all orebit-ops.timer --no-pager
```

Rollback is `sudo systemctl disable --now orebit-ops.timer`; stop a currently running sample if needed with `sudo systemctl stop orebit-ops.service`. Keep the private channel and ledger. No changes to capture storage, the 80% guard, announcements, or training are needed in either direction. Never delete/reset the ledger as an upgrade step. Staging can be removed after the owner confirms deployment; retain source and durable state.

## Archive recommendation: evidence, not migration

Primary-source pricing checked 2026-11-02; recheck before purchasing:

| Option | Published storage | Retrieval / egress | Fit |
| --- | --- | --- | --- |
| [Backblaze B2 pricing](https://www.backblaze.com/cloud-storage/pricing) | Starts at **$6.95/TB/month**, first 10 GB free; no minimum file size/duration fee | Free egress up to **3× average monthly stored data**; above that **$0.01/GB**, with some partner routes free; pay-as-you-go A/B/C API calls free (see [transaction pricing](https://www.backblaze.com/cloud-storage/transaction-pricing)) | Recommended lower-cost archive when monthly restores/training downloads stay below the 3× allowance. |
| [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/) | Standard **$0.015/GB-month** (about $15 per decimal TB); Infrequent Access **$0.01/GB-month** | Internet egress free; Standard has no retrieval fee. IA retrieval **$0.01/GB**, **30-day** minimum storage duration; Class A/B operation fees apply. Standard free tier: 10 GB-month, 1M A / 10M B requests/month. | Recommended alternative when frequent/repeated training downloads make unlimited free egress more valuable than B2's cheaper storage. Use Standard for repeatedly read training data, not IA by default. |

Use **private object storage**, narrowly scoped credentials, and an independently approved retention/restore/checksum/access plan before any migration. Objects must not become public to solve a disk alert. Small compressed chunks can make request count relevant; pricing alone is not an approved migration design. B2 vs R2 depends on measured stored volume and monthly download volume; this feature collects filesystem metrics only and does not inspect archives to estimate those volumes. **No provider bucket, credentials, upload, lifecycle/delete rule, auto-cleanup, or migration job is created or enabled.**
