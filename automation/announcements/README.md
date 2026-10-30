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

Each release produces one Discord message containing:

- Its beta version.
- Release notes from recorded commit changes, not inferred gameplay claims. Long notes are excerpted with links to the full release notes and receipt.
- Download links and update instructions for the platforms listed in the verified receipt. Unpublished platforms are not invented.
- Android update-over-existing-install guidance, complete Windows ZIP/DLL guidance, Apple Silicon macOS app/Gatekeeper guidance, and/or Web/PWA reload guidance as applicable.

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

The key is `repository:full_commit_SHA`, not a run attempt or timestamp. Before POST, the sender durably stores the exact payload and a sending state. It uses a deterministic Discord nonce and an exact bot-authored footer marker. Success is recorded only after a confirmed response or matching channel-history recovery.

On restart or replay, the sender checks the durable outbox and paginated actual channel history. It does not trust another user's text as publication evidence. If a POST times out and history cannot confirm whether it arrived, the intent remains uncertain and is **not blindly resent**, even after Discord's nonce window expires. The service logs this condition for human investigation; inspect actual channel history and the private ledger before deciding whether any recovery is safe. Do not delete/reset a pending intent to force a resend.

## Acceptance procedure

Use a real successful CI publication, not a fabricated receipt: verify exactly one actual Discord announcement, matching version, recorded notes and platform links; replay its real run ID and confirm the message count for that release marker remains one. Process a real failed run ID and confirm no additional announcement. Confirm the original intake service is still running and its channel permissions/✅-only acknowledgment behavior are intact.
