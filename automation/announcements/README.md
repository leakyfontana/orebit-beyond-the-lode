# Verified beta announcements

The existing **Orebit Intake** bot publishes to `#release-announcements` (`1565584282389454879`). Members can read this channel; the bot can view/read it, send messages, and embed links. The feature-request and bug-report intake code and service are separate and unchanged.

## Publication contract

The source is the GitHub prerelease `beta-<full commit SHA>` in `leakyfontana/orebit-beyond-the-lode`, with its `publication.json` asset. CI creates the release as a draft, attaches the receipt, and publishes it only after all required platform artifacts have been publicly uploaded and verified, matching Web deployment has passed integrity checks, and the public Web menu smoke has passed.

The notifier requires both:

- A published, non-draft beta prerelease with a matching receipt identity, verified artifact metadata, canonical download URLs, and recorded release notes.
- A completed successful **push** run of `.github/workflows/beta.yml` on the repository's default branch, for the same SHA and source repository.

PRs, failed/incomplete workflows, drafts, missing receipts, mismatched versions/commits, unsupported schemas/platforms, and unverified Web identities cannot produce an announcement. A release receipt alone does not claim original-game parity or physical-device acceptance.

The CI owner maintains `automation/release/receipt.py` and workflow wiring. The notifier owns this directory. No Discord credential is stored in GitHub Actions or the public repository.

## Message contents

Each release produces one compact Discord embed with native link-button rows:

- A human-readable beta version, warm accent, and Discord's native publication timestamp. Build hashes stay in the linked release URL, not the visible title/footer.
- At most three short, escaped highlights from recorded release notes (commit subjects only when Markdown notes are absent). Conventional housekeeping and explicit CI/deployment notes are omitted from the preview, not rewritten into invented gameplay claims. The complete notes remain available.
- Primary **Play web / Windows / macOS / Android** buttons, only for verified published platforms. A native platform with multiple packages links to its verified folder; otherwise its button opens the actual package. The Web button opens the playable site, not its developer archive.
- A concise **Updating?** section retaining the important platform-specific warnings: reload Web/PWA, keep Windows EXE/DLL files together, Apple Silicon/notarization limitations, and Android's update-without-uninstall/signature warning.
- Secondary **Full release notes** and **Report a bug** buttons. Extra artifact URLs and checksums remain in `publication.json` on the linked GitHub release instead of crowding the announcement.

These are ordinary link buttons alongside an embed, not Components V2 or bot interactions. No interaction endpoint, new bot, or additional service is required.

Mentions are disabled. Release text and metadata are data, not commands, model instructions, or fetch destinations outside the fixed GitHub/Drive/live-site contract.

## Running locally

Requires the existing Bun installation, `/opt/homebrew/bin/gh` authenticated for the repository, and the existing bot token at:

`~/Library/Application Support/Orebit Intake/discord-token`

The token remains `0600` in its `0700` parent directory. The release outbox, cross-process lock database, and logs live under:

`~/Library/Application Support/Orebit Intake/announcements/`

Runtime state is private and must never be committed. The sender rejects a repository-local state directory. There are no additional package dependencies or new hosted services.

From the repository root:

```sh
bun test automation/announcements/message.test.ts
bun automation/announcements/service.ts --once
bun automation/announcements/install.ts
launchctl print gui/$(id -u)/local.orebit.announcements
```

The independent launch agent polls GitHub once per minute and processes missed releases oldest first. The Mac must be awake, have network access, and retain working GitHub authentication. Tern does not need to be open for release announcements; the separate native-board intake integration retains its own Tern requirement.

To replay a real GitHub Actions run through the same publication gate:

```sh
bun automation/announcements/service.ts --run RUN_ID
```

A failed/non-push run returns `not_successful` without sending. A release already recorded in the private outbox returns `already_announced` without sending. CLI and background publishers share a cross-process lock; if another publisher is active, retry after it finishes.

To stop only this watcher:

```sh
launchctl bootout gui/$(id -u)/local.orebit.announcements
```

After moving the checkout, rerun its installer to update the launch-agent path. Do not change the CI publication receipt namespace or the fixed Discord destination without updating and verifying both sides of the contract.

## Duplicate and crash safety

The key is `repository:full_commit_SHA`, not a run attempt or timestamp. Before POST, the sender durably stores the exact payload and a sending state. It uses a deterministic Discord nonce and the exact canonical release URL in an embed authored by the permitted bot. This URL identifies both existing and redesigned posts without a machine-readable footer. Success is recorded only after a confirmed response or matching channel-history recovery.

On restart or replay, the sender checks the durable outbox and paginated actual channel history. It does not trust another user's text as publication evidence. If a POST times out and history cannot confirm whether it arrived, the intent remains uncertain and is **not blindly resent**, even after Discord's nonce window expires. The service logs this condition for human investigation; inspect actual channel history and the private ledger before deciding whether any recovery is safe. Do not delete/reset a pending intent to force a resend.

## Acceptance procedure

Use a real successful CI publication, not a fabricated receipt: verify exactly one actual Discord announcement, matching version, recorded notes and platform links; replay its real run ID and confirm the message count for that release marker remains one. Process a real failed run ID and confirm no additional announcement. Confirm the original intake service is still running and its channel permissions/✅-only acknowledgment behavior are intact.

## Observed integration checks

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

The initial SSH-firewall deployment failure was resolved by the CI owner's user-approved outbound-only game deployer. Final acceptance passed after its real successful publication, without fabricating a receipt or weakening the notifier gate. Transport `candidate-<SHA>` releases remain excluded; only the final `beta-<SHA>` receipt plus a completed successful trusted push run can announce.

## Readability refresh

Research used publicly indexed release-channel excerpts: [Karakeep's feature-led announcement](https://www.answeroverflow.com/m/1533222782316576848), [CLIPPERS' short version-led release post](https://www.answeroverflow.com/m/1480681897288794275), and [Traycer's sectioned announcement](https://www.answeroverflow.com/m/1519259786296688650). Direct community pages returned rate limits/security checkpoints, so these are textual examples, not claimed visual audits. [Discord's component reference and button guidelines](https://docs.discord.com/developers/components/reference#button-design-guidelines) informed concise labels and native link-button rows.

The existing beta-2 announcement was edited in place, preserving its message ID and verified download destinations. No duplicate release post or mention was sent. That release's recorded changes are build/deployment work, so its card does not invent gameplay highlights. Future announcements use the same renderer; already-sent outbox entries are not automatically reposted or rewritten.

Observed refresh checks:
- Four receipt/security/preview-boundary tests passed.
- The actual Discord API accepted the redesigned embed and all six link buttons; its real browser surface was inspected and screenshot capture succeeded.
- A fresh isolated outbox recovered the existing announcement by its canonical release URL, then replayed without creating a message. This smoke prohibited all POST requests and removed its temporary state afterward.
- The real successful run replay returned `already_announced`; the release still has exactly one message with its original ID and all six verified action links. All 24 announcement/intake regression tests passed. The restarted announcement watcher is running, and the intake service retained its existing PID.

