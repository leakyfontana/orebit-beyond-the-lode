# Orebit: Beyond the Lode

Godot port derived from [Motherload Recoded](https://nemael.itch.io/motherload-recoded).
The original Unity source remains under `Assets/`; the runtime project is `godot/`.
Beta builds are not a claim of original-game parity acceptance.

## Branching and release delivery

- `main` is deployable. Use short-lived branches and pull requests.
- Every PR requires **Beta checks**: fresh macOS ARM64, Windows x86-64, Android ARM64,
  and Web builds, including an actual Chromium launch of the Web export to MainMenu.
  Co-op HTTP/WebSocket, persistence, migration and logging regressions must also pass.
- Squash-merge after required checks pass; force pushes, deletion and admin bypass
  are disabled. No separate release branch or manual release-tag step.
- A passing push to `main` rebuilds all four platforms from pinned dependencies.
  Android preserves the existing beta signer; macOS uses ad-hoc signing, not
  notarization, so downloaded apps may require explicit Gatekeeper approval.
- Releases use a unique plain `0.MINOR.PATCH` version in GitHub and
  [Drive](https://drive.google.com/drive/folders/1O6fBmcNqgVkVYUic88DOX3GTG94vB366)
  under **version → platform**. All versions below `1.0.0` are inherently beta:
  no `beta`, prerelease suffix, or commit suffix is added to their version.
- Increment MINOR for a feature release and reset PATCH to zero; increment PATCH
  for fixes. Every published version is immutable and must increase numerically.
  Update the source version before merging a release; CI rejects reused versions.
  Commit identity remains separate provenance, not part of the display version.
- After Drive verification, CI publishes a temporary bot-authored `candidate-<commit>`
  transport prerelease, not an independently versioned game release.
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
client that requires them. Deployment candidates are not successful release receipts.

Only after Drive, Web integrity and public browser checks succeed does `receipt.py`
publish a normal `v0.MINOR.PATCH` release with a durable `publication.json` asset
(`orebit.publication`, schema 1), then hide the completed transport candidate as a
draft. Its assets remain intact; only pending candidates appear in the public feed.
The [local announcement notifier](automation/announcements/README.md) consumes that
receipt plus the completed successful workflow run; its Discord token stays local.

Re-run **failed jobs**, not all completed platform builds, when recovering before
a deployment attempt: immutable commit versions reject different bytes. Inspect
the public deployment status first; the service records terminal attempts durably
and does not automatically redeploy them after a crash or failure. Fix a terminal
failure through a reviewed new commit. A failed build never selects a new live
release. Deployment evidence is retained as the `beta-publication-evidence` workflow
artifact and successful receipts as release assets. Do not announce candidates
without a verified receipt.

### Historical version migration

The initial verified four-platform release is `0.1.0`; the branding/controller/physics
release is `0.2.0`; five-player co-op is `0.3.0`; the Safari authentication fix is
`0.3.1`. The next feature version in source is `0.4.0`, adding the Ria transfer
branch and fully mineable western columns alongside the pending runtime updates.

| Commit | Original version | Canonical version |
| --- | --- | --- |
| `0f02ab84a6f3` | `1.0-beta.2+0f02ab84a6f3` | `0.1.0` |
| `eb058b5f8ae2` | `1.0-beta.8+eb058b5f8ae2` | `0.2.0` |
| `9a326753bddd` | `1.0-beta.8+9a326753bddd` | `0.3.0` |
| `566733834424` | `1.0-beta.8+566733834424` | `0.3.1` |

Historical GitHub titles, tags, and publication receipt version metadata use the
canonical versions. Original binary bytes, embedded versions, artifact filenames,
Drive locations, and integrity hashes remain unchanged. The table records the
provenance distinction; old artifact names are not new release version labels.
Completed deployment candidates are internal draft records, not extra releases.

Check the policy without publishing or rebuilding artifacts:

```sh
python3 automation/release/version_policy.py --sha "$(git rev-parse HEAD)"
python3 -m unittest discover -s automation/release -p 'test_*.py' -v
bun test automation/announcements
```

The guard reads fresh origin tags. `--allow-existing` is reserved for an exact
same-version, same-commit publication retry, never a new release or downgrade.
The required **Beta checks** status name and protected environment retain their
existing infrastructure names; public versions and announcements do not.

## Private play and cross-platform co-op

The startup chooser keeps private on-device play separate from a shared co-op
world with at most five connected miners. Anonymous play requires no account;
the load/entry prompts explain that only account player progress survives leaving.
Co-op never reads or writes the private binary save. The server persists shared
excavations, and account money, cargo, upgrades, items, transmissions and position.
Physics runs locally; the server arbitrates excavation and awards each tile once.
Pausing affects only the local player, not the server or other miners.

Co-op adds ten full-depth mining columns west of the fuel station (x=-10…-1),
with the shared **Ria Money Transfer** branch on an indestructible concrete
base (x=-8…-3). Its weathered, nearest-filtered artwork uses the original shops'
stone/metal textures, beveled foundation and machinery with Ria's orange fascia.
Drive to the entrance at (-5.5, -3.5), choose **Visit ria · Money Transfer**,
select another connected miner, and enter a positive whole-dollar amount.
Transfers have no fee; the server atomically debits and credits the exact amount,
rejects insufficient funds and departed recipients, and prevents stale progress
updates from restoring pre-transfer balances. Wait for confirmation before leaving.
Only account progress persists after leaving; anonymous balances remain temporary.
The western columns use the original depth-dependent generation rules for dirt,
metals, treasures, tunnels and hazards; drilling and explosives behave as in the
original mine, and excavations synchronize and persist across rejoining/restarts.
Generation continues the original RNG after columns x=0…35, preserving their
seeded layouts and existing excavation/account progress. Private worlds and saves
are unchanged. Ria's concrete remains indestructible, but the earth below it is
ordinary mineable terrain.

The service automatically migrates the excavation table's coordinate constraint
in a transaction, retaining existing rows and account state. Update the service
before running clients that mine western columns; older services reject negative
excavation coordinates.

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

Web account requests leave response decompression to browser Fetch, including
sign-out revocation. Safari can retain `Content-Encoding: gzip` after decoding
the body; enabling Godot's HTTPRequest gzip decoding on Web attempts to decode
that body twice and reports the account service as unavailable. Native requests
retain Godot's gzip support.

The repaired local Web export has completed real Discord authorization and
returned to an authenticated Orebit account in iOS 26.5 simulator Safari.
Real session revocation also passed. Sanitized results and screenshots are under
`verification/captures/discord-safari-auth/`; this is not a production deployment
receipt or a physical-iPhone acceptance claim.

### Account interaction and session lifetime

Co-op offers one primary **Continue with Discord** action, with password and
anonymous entry as alternatives. Web/PWA uses same-tab authorization: a validated,
state-bound callback returns to the initiating game and its private pending poll.
Neither the Orebit session nor the poll credential travels in the return URL.
The packaged PWA worker handles game assets/entry pages, but leaves backend
navigation and redirects to the browser. The archive-based Chromium CI smoke
enables service workers and verifies a backend callback redirect reaches the game
instead of an offline fallback; this routing check does not simulate Discord auth.
Native clients use the external browser; desktop clients foreground the game
when their poll succeeds, and Android resumes through
`org.motherloadrecoded.game://auth/discord`. The Android export plugin registers
that fixed return URI; it is not a separate Discord provider redirect.

Saved sessions are checked through `GET /api/auth/session` on startup, without
issuing a replacement token or extending their expiry. The existing lifetime is
30 days. Reloading or restarting reuses a valid session; explicit sign-out revokes
it, and expiry or a server rejection returns the player to sign-in. A temporary
network failure does not erase the saved session. Web closes and synchronizes its
persistent user file before the next reload. Install the updated co-op service
before releasing these clients: they require the session lookup and callback
return support. The additive OAuth-state migration leaves account/player data
unchanged.

The modal uses progressive disclosure for password/server options, persistent
field labels, password paste/reveal, visible busy/cancel states, and scrollable
safe-area/keyboard-aware layouts. Controls are at least 48 CSS pixels on Web or
48 density-independent native units; typography uses a scalable font. These
decisions follow [Apple's button guidance](https://developer.apple.com/design/human-interface-guidelines/buttons),
[WCAG's 44×44 enhanced targets](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html),
and [accessible authentication guidance](https://www.w3.org/WAI/WCAG22/Understanding/accessible-authentication-minimum.html).
Same-tab Web navigation avoids the asynchronous popup/user-activation and opener
constraints documented for [`Window.open`](https://developer.mozilla.org/en-US/docs/Web/API/Window/open).
Discord retains identify-only authorization, state and PKCE; its documented
[`prompt=none`](https://docs.discord.com/developers/topics/oauth2) skips redundant
consent for already-approved scopes. Native browser/return handling follows
[RFC 8252](https://www.rfc-editor.org/rfc/rfc8252).

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
verification/tools/Godot.app/Contents/MacOS/Godot --headless --path godot --script "$PWD/verification/coop_surface_interop.gd" -- --mode=private
```

Ticket implementation/runtime acceptance is verified across macOS, Windows,
Android and Web, including a simultaneous five-client VPS session and native/
Discord account persistence. Local working-tree exports and these checks do not
replace the beta-release CI/publication gates or publish updated game clients.