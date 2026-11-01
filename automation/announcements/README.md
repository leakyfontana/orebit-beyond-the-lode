# Verified release announcements

The existing **Orebit Intake** bot publishes to `#release-announcements` (`1565584282389454879`). Members can read this channel; the bot can view/read it, send messages, and embed links. Release publication runs independently of model processing and native Tern synchronization.

## Publication contract

The source is a public GitHub release tagged `v0.x.y` in `leakyfontana/orebit-beyond-the-lode`, with `prerelease=false`, title `Orebit 0.x.y`, a full source commit SHA in `target_commitish`, and its `publication.json` asset. CI creates the release as a draft, attaches the receipt, and publishes it only after all required platform artifacts have been publicly uploaded and verified, matching Web deployment has passed integrity checks, and the public Web menu smoke has passed. Transport `candidate-<SHA>` releases never qualify; successful receipt publication hides the transport release as a draft without deleting its assets.

The notifier requires both:

- A published, non-draft, non-prerelease `v0.x.y` release with a schema-1 `kind: "orebit.publication"` receipt. The receipt's plain `version` must match the tag after removing `v`; `commit` and `release_id` must both equal the release's full `target_commitish` SHA. Verified artifact metadata, canonical download URLs, and recorded release notes remain required.
- A completed successful **push** run of `.github/workflows/beta.yml` on the repository's default branch, for the same SHA and source repository.

PRs, failed/incomplete workflows, drafts, missing receipts, mismatched versions/commits, unsupported schemas/platforms, and unverified Web identities cannot produce an announcement. A release receipt alone does not claim original-game parity or physical-device acceptance.

Changing the local version or exporting an APK/ZIP does **not** publish a release or trigger this notifier. Commit the reviewed source through the protected PR → `main` workflow. Local exports and manual working-tree deployments must not be relabeled as verified CI releases or announced without the final matching receipt.

The CI owner maintains `automation/release/receipt.py` and workflow wiring. The notifier owns this directory. No Discord credential is stored in GitHub Actions or the public repository.

Versions have exactly three decimal components, start with `0`, and contain no leading zeroes, prerelease suffix, or build metadata: for example `0.3.2`, tag `v0.3.2`, receipt URL `https://github.com/leakyfontana/orebit-beyond-the-lode/releases/download/v0.3.2/publication.json`. Legacy receipt kinds and beta tags are not accepted. Historical artifact filenames, Drive URLs, checksums, binary bytes, and versions embedded inside those binaries remain unchanged; a beta string in an artifact filename is not a release-version error.

## Message contents

Each release produces one compact Discord embed with native link-button rows:

- A plain `Orebit 0.x.y` title, warm accent, and Discord's native publication timestamp. The footer says **Release**, with no beta label or build hash.
- At most three short, escaped highlights from recorded release notes (commit subjects only when Markdown notes are absent). Conventional housekeeping and explicit CI/deployment notes are omitted from the preview, not rewritten into invented gameplay claims. The complete notes remain available.
- Primary **Play web / Windows / macOS / Android** buttons, only for verified published platforms. A native platform with multiple packages links to its verified folder; otherwise its button opens the actual package. The Web button opens the playable site, not its developer archive.
- A concise **Updating?** section retaining the important platform-specific warnings: reload Web/PWA, keep Windows EXE/DLL files together, Apple Silicon/notarization limitations, and Android's update-without-uninstall/signature warning.
- Secondary **Full release notes** and **Report a bug** buttons. Extra artifact URLs and checksums remain in `publication.json` on the linked GitHub release instead of crowding the announcement.

These are ordinary link buttons alongside an embed, not Components V2 or bot interactions. No interaction endpoint, new bot, or additional service is required.

Mentions are disabled. Release text and metadata are data, not commands, model instructions, or fetch destinations outside the fixed GitHub/Drive/live-site contract.

## VPS runtime

The watcher runs on the existing Arc Monkeys VPS as `orebit-announcements.service`, using the isolated Bun runtime at `/opt/orebit-bot/runtime/bun` and the root-owned application under `/opt/orebit-bot/automation`. The Mac need not be awake, and neither Tern, omp/model authorization, `gh`, nor a GitHub token is required for release announcements.

Publication metadata and receipts are fetched anonymously from the public repository over bounded HTTPS. Redirects are restricted to fixed GitHub asset hosts. An ETag/body-digest check on the public releases Atom feed avoids repeated anonymous API inventory reads when the feed has not changed; pending successful-run checks still continue.

`automation/vps/orebit-announcements.service` configures:

| Setting | Value |
| --- | --- |
| Service user | `orebit-bot` |
| `OREBIT_DISCORD_TOKEN_FILE` | `/var/lib/orebit-bot/credentials/discord-token` |
| `OREBIT_ANNOUNCEMENTS_STATE_DIR` | `/var/lib/orebit-bot/announcements` |
| Durable outbox | `/var/lib/orebit-bot/announcements/delivery.sqlite` |

The token/database files are `0600` in `0700` private directories outside the checkout. No secret is placed in unit environment values. The unit has a read-only application tree, private writable announcement state, no privileged capabilities, restart policy, and resource limits. Runtime state must never be committed.

On the VPS:

```sh
sudo systemctl status orebit-announcements.service
sudo journalctl -u orebit-announcements.service --no-pager
```

The enabled service polls once per minute and processes missed releases oldest first. Stop only this watcher with `sudo systemctl stop orebit-announcements.service`. Do not restart the retired `local.orebit.announcements` Mac launch agent: independent copies of the outbox would create competing publishers.

To replay a real GitHub Actions run through the same publication gate on the VPS:

```sh
cd /opt/orebit-bot
sudo -n -H -u orebit-bot env \
  HOME=/var/lib/orebit-bot \
  OREBIT_DISCORD_TOKEN_FILE=/var/lib/orebit-bot/credentials/discord-token \
  OREBIT_ANNOUNCEMENTS_STATE_DIR=/var/lib/orebit-bot/announcements \
  /opt/orebit-bot/runtime/bun \
  /opt/orebit-bot/automation/announcements/service.ts --run 41127800649
```

A failed/non-push run returns `not_successful` without sending. A release already recorded in the private outbox returns `already_announced` without sending. CLI and background publishers share a cross-process lock; if another publisher is active, retry after it finishes. Local announcement checks are `bun test automation/announcements`; these cover discovery, receipts, rendering, the trusted-run gate, and durable delivery without contacting production services. Do not start a second local publisher.

Migration quiesced the old Mac watcher, made an integrity-checked SQLite `.backup`, and copied its three sent intents privately before starting the VPS worker. A private rollback snapshot and the disabled old launch-agent definition remain on the Mac. Do not reset/delete the outbox to recover a missed publication. The existing CI publication namespace, Discord destination, and unrelated game/deployment services were not changed.

### Canonical-version cutover compatibility

Deploy this directory together and restart the existing VPS watcher after the historical release metadata/receipt migration. The Bun runtime, service unit, credentials, Discord destination, and SQLite schema are unchanged. Keep the existing private outbox: its `repository:full_commit_SHA` keys and nonce inputs have not changed, so previously sent records deduplicate migrated versions without contacting Discord or rewriting old messages. Do not reset the ledger or edit historical Discord announcements as part of this cutover.

Approved historical versions are `0.1.0` for `0f02ab84a6f3b113ce5af5509bc20fc29989dc85`, `0.2.0` for `eb058b5f8ae2fc1832655e8d1a5a1f27c6d8c739`, `0.3.0` for `9a326753bdddfc640fd3f36663f762d6e1bfdea7`, and `0.3.1` for `56673383442465e861661a3d6b93f6a53e1fa7c1`; the next source feature version is `0.4.0`. Historical receipt migration changes `kind` and `version`, not artifact identities or original embedded versions.

Before upgrading, inspect any `pending` or `sending` records with an old beta URL: the new sender deliberately rejects those frozen payloads rather than silently migrating or resending an uncertain intent. Preserve the payload and inspect actual channel history with an operator. Sent records need no conversion. History-only recovery for new intents uses the canonical `v0.x.y` URL; it is not a substitute for retaining historical commit-key sent records.


## Duplicate and crash safety

The key is `repository:full_commit_SHA`, not a version, run attempt, or timestamp. Before POST, the sender durably stores the exact payload and a sending state. It uses a deterministic commit-derived Discord nonce and the exact canonical `v0.x.y` release URL in an embed authored by the permitted bot. Reconciliation uses the URL from that durable payload, never an arbitrary user's text or a reconstructed commit tag. Success is recorded only after a confirmed response or matching channel-history recovery.

On restart or replay, the sender checks the durable outbox and paginated actual channel history. It does not trust another user's text as publication evidence. If a POST times out and history cannot confirm whether it arrived, the intent remains uncertain and is **not blindly resent**, even after Discord's nonce window expires. The service logs this condition for human investigation; inspect actual channel history and the private ledger before deciding whether any recovery is safe. Do not delete/reset a pending intent to force a resend.

## Acceptance procedure

Use a real successful CI publication, not a fabricated receipt: verify exactly one actual Discord announcement, matching version, recorded notes and platform links; replay its real run ID and confirm the message count for that release marker remains one. Process a real failed run ID and confirm no additional announcement. Confirm the original intake service is still running and its channel permissions/✅-only acknowledgment behavior are intact.

## Observed integration checks

The observations below are historical audit facts from before the canonical-version cutover. Old beta labels, release URLs, and test counts describe what was observed then, not the current publication contract or newly exercised checks.


- Five message/receipt boundary tests passed; both Bun entry points compiled.
- The installed watcher successfully queried the real repository and remained running without publishing a placeholder.
- Real failed default-branch push `41008296489` returned `not_successful`; the release-channel message count stayed zero.
- Real successful PR validation `41006889317` also returned `not_successful`; the release-channel message count stayed zero.
- A fresh synthetic intake request was recorded once with ✅ and no textual reply while the release watcher was running. Its verification card was marked Done.
- Successful production push [41074342741](https://github.com/leakyfontana/orebit-beyond-the-lode/actions/runs/41074342741) automatically produced exactly one [Discord announcement](https://discord.com/channels/1565550697070596216/1565584282389454879/1565744400976322560) for `1.0-beta.2+0f02ab84a6f3`.
- The announcement's version, recorded notes, and Android/macOS/Web/Windows download links matched the published `publication.json` receipt for commit `0f02ab84a6f3b113ce5af5509bc20fc29989dc85`. Platform-specific update instructions were inspected in the actual Discord message.
- `bun automation/announcements/service.ts --run 41074342741` returned `already_announced`; the matching release-marker message count remained `1 -> 1`.
- Reprocessing failed push `41008296489` after publication returned `not_successful`; the matching message count remained `1 -> 1`.
- The private outbox contains one `sent` record matching message `1565744400976322560`. Both launch agents remained running; token and outbox permissions were verified as `0600` in `0700` private state.
- Initial verification inspected actual Discord browser text and API contents. Its relay screenshot capture timed out; a later readability refresh successfully captured the actual redesigned Discord surface.

The initial SSH-firewall deployment failure was resolved by the CI owner's user-approved outbound-only game deployer. Final acceptance passed after its real successful publication, without fabricating a receipt or weakening the notifier gate. At that time, transport `candidate-<SHA>` releases were excluded and only a final `beta-<SHA>` receipt plus a completed successful trusted push run could announce. The current equivalent is the canonical `v0.x.y` receipt and the same successful trusted push gate described above.

## Readability refresh

Research used publicly indexed release-channel excerpts: [Karakeep's feature-led announcement](https://www.answeroverflow.com/m/1533222782316576848), [CLIPPERS' short version-led release post](https://www.answeroverflow.com/m/1480681897288794275), and [Traycer's sectioned announcement](https://www.answeroverflow.com/m/1519259786296688650). Direct community pages returned rate limits/security checkpoints, so these are textual examples, not claimed visual audits. [Discord's component reference and button guidelines](https://docs.discord.com/developers/components/reference#button-design-guidelines) informed concise labels and native link-button rows.

The existing beta-2 announcement was edited in place, preserving its message ID and verified download destinations. No duplicate release post or mention was sent. That release's recorded changes are build/deployment work, so its card does not invent gameplay highlights. Future announcements use the same renderer; already-sent outbox entries are not automatically reposted or rewritten.

Observed refresh checks:
- Four receipt/security/preview-boundary tests passed.
- The actual Discord API accepted the redesigned embed and all six link buttons; its real browser surface was inspected and screenshot capture succeeded.
- A fresh isolated outbox recovered the existing announcement by its canonical release URL, then replayed without creating a message. This smoke prohibited all POST requests and removed its temporary state afterward.
- The real successful run replay returned `already_announced`; the release still has exactly one message with its original ID and all six verified action links. All 24 announcement/intake regression tests passed. The restarted announcement watcher is running, and the intake service retained its existing PID.

## Beta 8 publication audit

The audit found GitHub `main`, the live site, and the only verified release still on beta 2 while beta 7/8 packages existed locally. There was no missing announcement for a successfully published release; the newer game source had not been committed/published through CI.

With the owner's approval, the reviewed beta-8 source and its required untracked controller/material/Web-bundle dependencies were snapshotted in an isolated worktree. [PR #4](https://github.com/leakyfontana/orebit-beyond-the-lode/pull/4) passed all four fresh platform builds, Chromium Web startup, and **Beta checks**, then squash-merged without bypassing branch protection.

[Production run 41127800649](https://github.com/leakyfontana/orebit-beyond-the-lode/actions/runs/41127800649) published **`1.0-beta.8+eb058b5f8ae2`**. All four production builds, aggregate verification, Drive publication/verification, matching Web deployment, public menu smoke, and durable receipt publication passed.

Independent acceptance:
- All four beta-2 and beta-8 public artifacts were downloaded anonymously and matched their receipt sizes and SHA-256 values.
- The actual public beta-8 browser reached MainMenu with the Orebit branding, matching commit/version/entrypoint, cross-origin isolation, and no browser errors. Its screenshot was captured. Browser-tool console callbacks timed out, but native console history and the actual surface established readiness without changing the game or weakening CI checks.
- The running watcher automatically posted [the beta-8 announcement](https://discord.com/channels/1565550697070596216/1565584282389454879/1565838177615482982), with all six action links matching the verified publication. Actual Discord text/API contents were inspected; its additional screenshot attempt timed out.
- Replaying the successful production run returned `already_announced`. Both verified beta releases have exactly one bot message and one durable `sent` outbox row; the existing beta-2 message remained unchanged.
- The existing 24 automation regressions and the real Godot controller/input fixture smoke passed. No new game feature, credential/permission change, or intake modification was required. Publication completed in the first of the three approved fix-and-verify cycles.


## VPS cutover checks

- The real VPS fetched the public release inventory, trusted successful-run evidence, and beta-8 receipt without `gh` or a GitHub credential. An unchanged second feed poll made no additional API inventory reads.
- All three sent outbox records migrated. `orebit-announcements.service` is active and enabled for boot; the old Mac watcher is stopped and disabled.
- After a service restart, successful run `41127800649` returned `already_announced` and real failed push `41008296489` returned `not_successful`. The same three release-channel message IDs remained; no additional announcement was posted.
- The worker's observed journal contained no source, publication, or fatal errors. All 35 intake-state/revision/queue/sync/message regressions passed.
- VPS intake/model processing and native Mac synchronization subsequently passed their separate live cutover acceptance. The Mac now runs only the synchronization consumer; both old local producers are stopped and disabled.

- Real successful PR validation `41006889317` also returned `not_successful` on the VPS, confirming that candidate/PR checks cannot publish through the final-release gate.

- Deployed-gate negative probes used copies of the real published beta metadata with only draft/candidate/incomplete guard fields changed. Draft and `candidate-*` inputs returned `waiting_for_publication`; an in-progress run returned `not_successful`. These were bounded rejection probes, not fabricated releases or announcements.

## Historical announcement version migration

With the owner's explicit approval, all four existing release-channel posts were
edited in place to their canonical versions. No message was added or deleted:

| Version | Existing announcement | Recorded changes |
| --- | --- | --- |
| `0.1.0` | [Original post](https://discord.com/channels/1565550697070596216/1565584282389454879/1565744400976322560) | Initial verified four-platform delivery and outbound Web deployment |
| `0.2.0` | [Original post](https://discord.com/channels/1565550697070596216/1565584282389454879/1565838177615482982) | Branding, controller navigation, metre-scale physics |
| `0.3.0` | [Original post](https://discord.com/channels/1565550697070596216/1565584282389454879/1565900087865905303) | Five-player cross-platform co-op and persistent server diagnostics |
| `0.3.1` | [Original post](https://discord.com/channels/1565550697070596216/1565584282389454879/1566487091737530419) | Safari Discord authentication response decoding |

Each post now has explicit recorded release notes, a canonical GitHub release
link, and matching Windows/macOS/Android artifact buttons. **Play latest web**
intentionally points to the live site, not an archived version. Per the owner's
preference, release messages do not include Web ZIP downloads. Existing update
warnings and publication timestamps remain. Original binary filenames, embedded
versions, hashes, and file IDs remain.

The watcher was stopped during migration. Private message and SQLite backups were
taken before edits; sent ledger payloads were updated without changing commit keys,
message IDs, or delivery states. Discord API read-back confirmed exactly one post
per version, matching text and native artifact links, with no Web ZIP buttons.
Drive metadata confirmed artifact IDs, names, sizes, public-reader permissions,
and version folders.
The restarted watcher was active; replay of real successful run `41323758657`
returned `already_announced`. No mention or new-post operation was used.

Browser visual verification was unavailable because the browser session redirected
to Discord login; the message-content evidence above comes from authenticated
Discord API responses, not a visual claim.

