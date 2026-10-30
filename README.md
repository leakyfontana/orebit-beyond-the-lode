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
- The same Web ZIP deploys to <https://play.arcmonkeyswelding.com/> using immutable
  `/srv/motherload/releases/sha-<commit>` directories and an atomic `current` switch.
  Hash/header failures roll back; a failed post-deploy browser check also restores
  the prior release when this run changed the live pointer. Other VPS sites and DNS
  are not modified.

Production credentials live only in the `beta-release` GitHub environment, restricted
to `main`. PRs use disposable Android signing and receive no deployment secrets.
The VPS key is restricted to a root-owned game-only forced-command helper; never
put the existing unrestricted administrator key in CI.

`.github/workflows/beta.yml` is the release entrypoint. `automation/release/build.py`
documents exact toolchains with `--help`; `manifest.py` verifies all four outputs;
`publish_drive.py` supports read-only `--validate-only`; `deploy_web.py` supports
`--dry-run`, `--verify-current` and guarded `--rollback`. The installed server helper
is maintained through the administrator's existing SSH access, not through the CI
key. After changing its protocol, install the reviewed helper and fixed wrapper
under `/srv/motherload/deploy/` before publishing a client that requires it.

Only after Drive, Web integrity and public browser checks succeed does `receipt.py`
publish a prerelease `beta-<full-commit>` with a durable `publication.json` asset.
The [local announcement notifier](automation/announcements/README.md) consumes that
receipt plus the completed successful workflow run; its Discord token stays local.

Re-run **failed jobs**, not all completed platform builds, when recovering a transient
publication failure: immutable commit versions reject different bytes. A failed
build never selects a new live release. Deployment evidence is retained as the
`beta-publication-evidence` workflow artifact and successful receipts as prerelease
assets. Do not announce candidates without a verified receipt.