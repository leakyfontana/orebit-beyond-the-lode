# Orebit: Beyond the Lode

Godot port derived from [Motherload Recoded](https://nemael.itch.io/motherload-recoded).
The original Unity source remains under `Assets/`; the runtime project is `godot/`.
Beta builds are not a claim of original-game parity acceptance.

## Branching and beta delivery

- `main` is deployable. Use short-lived branches and pull requests.
- Every PR requires **Beta checks**: fresh macOS ARM64, Windows x86-64, Android ARM64,
  and Web builds, including an actual Chromium launch of the Web export to MainMenu.
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