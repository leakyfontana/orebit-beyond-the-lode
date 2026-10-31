# Orebit: Beyond the Lode

Godot port derived from [Motherload Recoded](https://nemael.itch.io/motherload-recoded).
The original Unity source remains under `Assets/`; the runtime project is `godot/`.
Beta builds are not a claim of original-game parity acceptance.

## Branching and beta delivery

- `main` is deployable. Use short-lived branches and pull requests.
- Every PR requires **Beta checks**: fresh macOS ARM64, Windows x86-64, Android ARM64,
  and Web builds, including an actual Chromium launch of the Web export to MainMenu.
  Co-op HTTP/WebSocket, persistence and logging regressions must also pass.
- Squash-merge after required checks pass; force pushes, deletion and admin bypass
  are disabled. No separate beta branch or manual beta-tag step.
- A passing push to `main` rebuilds all four platforms from pinned dependencies.
  Android preserves the existing beta signer; macOS uses ad-hoc signing, not
  notarization, so downloaded apps may require explicit Gatekeeper approval.
- Releases use the source beta version plus the first twelve commit characters,
  in [Drive](https://drive.google.com/drive/folders/1O6fBmcNqgVkVYUic88DOX3GTG94vB366)
  under **version → platform**. Older artifacts and shared links are retained.
- After Drive verification, CI publishes a bot-authored `candidate-<commit>` prerelease.
  The outbound-only VPS service validates the main-push run, four successful build
  jobs, Drive verification, current main SHA, and exact Web ZIP before deployment.
- The same Web ZIP deploys to <https://play.arcmonkeyswelding.com/> using immutable
  `/srv/motherload/releases/sha-<commit>` directories and an atomic `current` switch.
  Hash/header failures roll back; a failed public browser check requests a guarded
  rollback. Read-only HTTPS deployment status is served under
  `/__orebit_deployment__/`. No inbound upload endpoint, firewall exception, DNS
  change, self-hosted GitHub runner, or other-site modification is required.

Production credentials live only in the `beta-release` GitHub environment, restricted
to `main`. PRs use disposable Android signing and receive no deployment secrets.
CI has no VPS credential. The nologin `orebit-deploy` system service can invoke only
the root-owned game release helper through sudo; it never executes workflow or
artifact code. The existing administrator SSH key is never placed in CI.

`.github/workflows/beta.yml` is the release entrypoint. `automation/release/build.py`
documents exact toolchains with `--help`; `manifest.py` verifies all four outputs;
`publish_drive.py` supports read-only `--validate-only`; `deploy_web.py` supports
`--dry-run`, `--verify-current` and guarded `--rollback`. The administrator installs
the reviewed `pull_deploy.py` and `remote_web_release.py` under
`/srv/motherload/deploy/`, the supplied `orebit-deploy.service` and narrow sudoers
policy, and `status.nginx.conf` only in the game HTTPS vhost. Private poller state is
under `/srv/motherload/puller/state`; public status is under `/srv/motherload/status`.
After protocol changes, update the installed service/helper before publishing a
client that requires them. Candidate prereleases are not successful beta receipts.

Only after Drive, Web integrity and public browser checks succeed does `receipt.py`
publish a prerelease `beta-<full-commit>` with a durable `publication.json` asset.
The [local announcement notifier](automation/announcements/README.md) consumes that
receipt plus the completed successful workflow run; its Discord token stays local.

Re-run **failed jobs**, not all completed platform builds, when recovering before
a deployment attempt: immutable commit versions reject different bytes. Inspect
the public deployment status first; the service records terminal attempts durably
and does not automatically redeploy them after a crash or failure. Fix a terminal
failure through a reviewed new commit. A failed build never selects a new live
release. Deployment evidence is retained as the `beta-publication-evidence` workflow
artifact and successful receipts as prerelease assets. Do not announce candidates
without a verified receipt.

## Private play and cross-platform co-op

The startup chooser keeps private on-device play separate from a shared co-op
world with at most five connected miners. Anonymous play requires no account;
the load/entry prompts explain that only account player progress survives leaving.
Co-op never reads or writes the private binary save. The server persists shared
excavations, and account money, cargo, upgrades, items, transmissions and position.
Physics runs locally; the server arbitrates excavation and awards each tile once.
Pausing affects only the local player, not the server or other miners.

The separate Python service lives in `automation/coop/`. Run locally:

```sh
python3 -m venv /tmp/orebit-coop
/tmp/orebit-coop/bin/pip install -r automation/coop/requirements.txt
/tmp/orebit-coop/bin/python automation/coop/server.py --db /tmp/orebit-coop.sqlite3
verification/tools/Godot.app/Contents/MacOS/Godot --path godot -- --mode=coop --coop-url=http://127.0.0.1:8765
```

Without `--mode`, the game offers the mode choice. `--mode=private` preserves the
existing menu flow; deterministic replays default to private mode. Web supports
`?mode=coop` and URL-encoded `coop-url`/`coop-world` parameters, but never tokens in
URLs. Cross-origin development browsers require their exact origin in the
service's comma-separated `OREBIT_ALLOWED_ORIGINS`; production defaults to its
own HTTPS origin.

Production uses `https://play.arcmonkeyswelding.com/coop`. Install the supplied
`orebit-coop.service` as a dedicated `orebit-coop` user with a virtual environment
at `/srv/orebit-coop/venv`, service sources in `/srv/orebit-coop/`, and persistent
SQLite state in `/var/lib/orebit-coop/`. Include `coop.nginx.conf` only in the game
HTTPS vhost. The service binds loopback port 8765; no new public port is needed.
The unit caps memory at 768 MiB and CPU at one core. Back up the SQLite database
with SQLite's online backup API; do not copy a live database without its WAL.
Run only one service worker: membership is process-owned.

Native accounts use Argon2id passwords and expiring, revocable sessions.
Discord accounts require `OREBIT_DISCORD_CLIENT_ID` and
`OREBIT_DISCORD_CLIENT_SECRET` in root-readable `/etc/orebit-coop.env`, plus this
registered redirect URI:
`https://play.arcmonkeyswelding.com/coop/auth/discord/callback`.
Set `OREBIT_PUBLIC_URL=https://play.arcmonkeyswelding.com/coop`. Never put OAuth
secrets in exports or source control. Discord authorization returns credentials
only to the initiating client's expiring, single-use poll, not in the browser URL.
Missing configuration disables Discord sign-in explicitly; native and anonymous
play remain available.

Production Discord sign-in uses the separate **Orebit** application
`1565858737863000256`; the intake application is not reused. Live native-client
authorization, server entry, account restoration on rejoin and session revocation
have been exercised against the VPS.

### Server diagnostics

The service writes privacy-filtered JSON events to journald and
`/var/log/orebit-coop/events.jsonl`. The service unit creates the persistent log
directory as `0750`; every active/rotated file is protected as `0640`. Logs survive
service restarts. Default rotation is 10 MiB per file with nine archives: at most
100 MiB total. Retention is size-based, **not a guaranteed number of days**.
`OREBIT_LOG_MAX_BYTES` and `OREBIT_LOG_BACKUP_COUNT` control this bound;
`OREBIT_LOG_LEVEL` defaults to `INFO`. Local runs use stdout unless
`OREBIT_LOG_DIR` is set.

Every HTTP response/WS upgrade has a server-generated `X-Request-ID`; JSON errors
also return `request_id`. WebSocket events use that ID as `session_id`. Each event
includes UTC time, a process `boot_id` and a source-derived `build_id` (override
with `OREBIT_BUILD_ID`). Session summaries retain message/state/mining counts;
individual mining decisions include tile/action/outcome, not player-state bodies.
Successful health checks and pending OAuth polls are omitted to reduce noise.

Inspect or follow the journal, or query retained files across rotations:

```sh
ssh arcmonkeys-prod 'sudo journalctl -t orebit-coop --since "1 hour ago" -o cat'
ssh arcmonkeys-prod 'sudo python3 /srv/orebit-coop/logs.py --event session_error --limit 50'
```

`logs.py` also accepts `--request-id`, `--session-id`, `--user-id`, `--level`,
`--since` (ISO8601), and `--directory`. Results are chronological NDJSON containing
the most recent matching events. A nonzero exit reports incomplete results from
rotation races, unreadable files or malformed/truncated records; diagnostic output
never echoes the damaged content. Deploy `telemetry.py` and `logs.py` alongside
`server.py`; the reader and writer share the same privacy schema.

Passwords, tokens, OAuth codes/verifiers, URLs/query strings, headers, usernames,
IP addresses and player-state payloads are excluded. Error diagnostics retain
exception type and stack file/function/line, not exception text or local variables.
Third-party logger text is filtered too. A failed file sink emits a rate-limited
`log_sink_error` directly to the journal/stdout so loss of file logging is visible.
These logs are machine-local diagnostics, **not an off-host backup or distributed
tracing/alerting service**.

Behavioral regressions:

```sh
/tmp/orebit-coop/bin/python -m unittest discover -s automation/coop -p 'test_*.py' -v
verification/tools/Godot.app/Contents/MacOS/Godot --headless --path godot --script "$PWD/verification/coop_state_interop.gd" -- --mode=private
```

Ticket implementation/runtime acceptance is verified across macOS, Windows,
Android and Web, including a simultaneous five-client VPS session and native/
Discord account persistence. Local working-tree exports and these checks do not
replace the beta-release CI/publication gates or publish updated game clients.