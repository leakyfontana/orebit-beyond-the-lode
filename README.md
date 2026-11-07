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

Release `0.9.0` replaces the default engine startup image with Orebit's existing
vessel icon on black across desktop and web exports. Android's OS splash uses
the same vessel and background. The browser loader retains real download
progress, with the menu's green border (`#4fd348`) and fill (`#299826`), and fits
both desktop and narrow screens. Gameplay and menus are unchanged.

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

### Required release board reconciliation

The release owner MUST update `automation/Orebit.tasks.md` for **every bug fix
and feature request included in a release**; passing CI or publishing release
notes does not complete the release handoff.

- Before merging the release, reconcile its changes and release notes against
  existing board cards by source identity and linked ticket, including stale
  unchecked cards whose fixes already shipped. Do not implement an already-fixed
  report again merely because its checkbox is unchecked.
- For each fully implemented and verified request, move the existing card to
  **Done** and check it. Preserve its source identity, tags, reporter text and
  ticket link. Append verification commands/results and release status to the
  linked ticket. A locally verified fix must explicitly say **not yet released**;
  partial or unverified requests stay open with their remaining acceptance gaps.
- After successful publication, record the actual version, source commit, release
  URL and verified publication/CI evidence in each included ticket. Failed builds
  and transport candidates are not shipped fixes. Reconcile any rollback with
  the ticket's availability status rather than leaving a false shipping claim.
- Before announcing or handing off the release, compare the published bug/feature
  notes with the saved board and ticket evidence. Every matching request must have
  an accurate lane, checkbox and shipped-version record. Note changes without an
  existing request explicitly; do not invent a completed reporter request.

When the authoritative board is open in Tern, use its existing native board API
and preserve live edits; do not overwrite its buffer from a release worktree.
Keep private board/report contents out of the public repository: update the
authoritative local board and linked tickets through their native document API,
then record the reconciliation in the PR/release handoff. Never force-add intake
records or credentials merely to make a public release commit self-contained.
The intake bot deliberately preserves triage status and does not perform this
release reconciliation automatically.

### Historical version migration

The initial verified four-platform release is `0.1.0`; the branding/controller/physics
release is `0.2.0`; five-player co-op is `0.3.0`; the Safari authentication fix is
`0.3.1`. Release `0.4.0` added Ria transfers, western mining columns and runtime
updates. Release `0.5.0` adds Sinclair pricing using AAA's daily US national
average, US-gallon fuel mechanics, and no device location collection.
Release `0.5.1` fixes single-action Discord sign-in and automatic game return on
Web/PWA and native clients, retains valid sessions across restarts, and simplifies
the mobile account screens without changing Sinclair pricing or account progress.
Release `0.5.2` fixes co-op HUD interception of the Android navigation joystick,
adds the compact green modes/accounts header icon, aligns the player count with
the hull/fuel captions, and fixes compact-window/live-resize header overlap.
Server/account menus reuse the landing-page green styling without duplicate
signed-in names. The native input/layout regression now runs in macOS CI builds.
Release `0.5.3` fixes wide-screen arrival camera confinement, expands interaction
close-button capture targets to at least 48 rendered pixels, and prevents
scripted motion cancellation during bonus popups from causing impact-free crash
damage. Real hard-landing damage remains intact. Native spawn/close/controller
regressions now gate macOS builds, and release handoff requires board reconciliation.

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

## Final-form boss artwork

The Godot copy of Mr. Natas's final-form artwork uses an exterior-background
matte across intro, standing, walking, arm attack, fireball attack and death.
Only border-connected background pixels become transparent; enclosed dark
details and foreground RGB are retained. The intro uses a derived PNG instead
of its opaque JPEG. Original Unity artwork remains unchanged.

Sprite dimensions, atlas regions, pivots, animation tracks, gameplay timings
and collision geometry are unchanged. Detached arms and projectile textures
that already had transparency are not rematted.

Run `godot --headless --path godot --script "$PWD/verification/boss_backdrop_interop.gd"`
to check the actual baked sprite and native-controller animation textures for
opaque corners and retained dark hair.

## Sinclair fuel pricing

The propellant station is Sinclair-branded and advertises its current regular
gasoline price in **USD per US gallon**. Tank contents/capacities, consumption,
upgrades and the 25-gallon reserve all use gallons directly. Existing numerical
fuel values and save fields are retained: this is a unit cutover, not a conversion
or a change to tank range. Engine displacement names such as “2.0 Ltr” are not
fuel-volume units and are unchanged. Dollar buttons buy `dollars / price` gallons;
fill charges round up to whole dollars, matching the game's integer currency.
A budget larger than the remaining tank cost charges only the rounded fill cost.

Every player uses [AAA's daily US regular national average](https://gasprices.aaa.com/),
not a median or a local price. Pricing does not read device location, request
location permission, resolve a ZIP code, or send coordinates to another provider.
There are no location bridges, geocoding services, provider accounts or API keys
in the pricing path.

Both private and co-op clients use public `GET /api/fuel-price` on the existing
co-op service, with no request body or player-specific pricing inputs. The server
fetches AAA once for concurrent consumers and caches the dated national quote
through US Eastern midnight. Responses contain only `price_per_gallon`, provider
`date`, `valid_until` (Unix seconds) and `source` (`aaa`).

The displayed price also determines gallon purchases. If AAA has no valid price
for the current day, the service returns HTTP 503 and the station shows unavailable;
it never invents a price, uses an expired quote, or charges for an unavailable
purchase. **Retry today's AAA price** refreshes the quote. Install the updated
service before shipping clients, with `curl` available on the service's `PATH`.
AAA fetching uses a bounded, HTTPS-only curl subprocess because AAA challenges
Python's HTTP/TLS client on the production host. No challenge cookies, browser
automation, pricing credentials or platform permissions are needed.

The earlier Ria agent's successful artwork workflow assembled and repainted
original shop rasters after a flat-vector storefront was rejected. Sinclair follows
that precedent: Shop125–130 fuel machinery and framing, Shop110–121 masonry/vents,
weathered green/white fascia and a custom dinosaur emblem, at 50 pixels per tile
with nearest filtering. Unlike the historical Ria output, Sinclair retains a
reproducible Pillow recipe: `verification/generate_sinclair_station.py`.
Original shop/Ria images and historical Unity reference code remain unchanged.

Verification:

```sh
python -m unittest discover -s automation/coop -p 'test_*.py' -v
verification/tools/Godot.app/Contents/MacOS/Godot --headless --path godot --script ../verification/fuel_pricing_interop.gd
```

## Mode menu correction

**0.7.1** fixes paused touch scrolling and slightly moving taps in
the mode/account menus. SceneTree pause still freezes gameplay; the engine UI
clock keeps running, and paused frames do not accumulate simulation catch-up.
Menu scrolling uses a 12-unit drag threshold instead of cancelling a tap on the
first pixel of finger movement.

Private and online mode choices remain available while a saved sign-in is being
checked. Choosing Private cancels that check without deleting the saved sign-in.
Escape, Android Back, and controller Back return from account/server pages and
dismiss the mode chooser to the prior game/menu pause state.
Android Back has one owner: the window Back request routes through the current
modal/game UI. Its duplicate physical-key Pause binding is removed only on Android,
so one press cannot skip two pages; desktop Back bindings remain unchanged.

Mode choices share a row; account and server actions share compact footers.
Repeated explanations are removed, while automatic-recording disclosure, the
unsaved-guest warning and the server-switch sign-out warning remain. Menu controls
keep 44-point touch targets, field accessibility names and inline password
visibility. Normal portrait and short-landscape views fit without scrolling;
the scroll container remains available for reduced/keyboard-constrained viewports.
Button presses propagate to that container so a drag over a button scrolls rather
than swallowing input or activating the button. Entering a mode clears its completed
connection message instead of retaining a stale “Joining” label.

The focused `verification/lobby_controller_interop.gd` regression covers drag/tap
boundaries, compact views and error/cancellation states at 320×568 and 712×311,
single-step Android Back, Escape, controller navigation, and a single Private
selection during pending session validation.

The Web worker activates routing updates without forcing a running game to reload.
On the next online navigation, a retired `game-<hash>/index.html` launch resolves
through the stable root bootstrap instead of repeatedly serving its deprecated
cached menu. Launch query parameters and fragments are preserved. Open older games
retain their cached runtime assets, including during an origin outage; cache
cleanup retains the current bundle, one previous bundle, and any active older
bundles rather than accumulating every release. Saves, accounts and recordings in
origin storage are not cleared.

For a stale Web menu, open <https://play.arcmonkeyswelding.com/index.html> online;
do not clear site data. `automation/release/smoke_web.py --previous-zip` exercises
the retired-release update path alongside `--zip`, including an untouched running
document, offline fallback, next-navigation migration and persistent-data survival.
Release status and remaining device acceptance checks are tracked on the release
board; local verification is not a publication receipt.

## Vulcan experimental outpost · 0.8.0

Choose **Vulcan**, launch with `--mode=vulcan`, or open `?mode=vulcan` on Web.
Play alone or share the five-miner outpost. Gameplay and world generation follow
Co-op, including the western extension, shops and upgrades. Vulcan has separate
accounts, sessions, saved player progress and terrain; existing Private, Co-op
and PvP data are not imported or reset. Guest progress ends on departure.

Drilling attracts **Shai-Hulud**, one shared ten-tile worm. It follows the nearest
actively drilling miner, then the last drilling location after drilling stops.
It moves in four cardinal directions at 5.4 tiles/second, 90% of the stock
engine's 6.0 flying speed. Every body segment consumes traversed earth without
awarding ore. Contact with any segment kills the miner, clears carried minerals
and consumable items, and retains money and purchased upgrades. Respawn occurs
automatically after three seconds with restored hull and fuel.

The worm initially rests below the mine at `(18.5, -19.5)`, with nine segments
behind it. It does not advance while nobody is connected, and there is no
offline catch-up. It stays underground; surface shops, the respawn pad and
immutable scenery remain intact. Movement, excavation and death are server-owned.

The original animated pixel art uses rust/ochre segmented hide, mineral-cutting
jaws, granular texture and traveling contraction bands. Visual research covered
[Schoenherr illustrations and the 1984 practical creature](https://monsterlegacy.net/2014/04/28/monster-gallery-dune-1984/),
[the 2021 film's annular hide and baleen-inspired mouth](https://www.syfy.com/syfy-wire/dune-sandworm-vfx-design),
and [Recircle/TED-Ed's angular animated treatment](https://www.stashmedia.tv/ted-ed-why-read-dune-recircle/).
No reference image is shipped or sampled. The two-jaw design and animation are
original; visible segment positions follow authoritative snapshots without
predicting diagonal shortcuts through the mine.

Deploy `automation/coop/vulcan.py` with the updated service before publishing the
client. Include `<configured-db>.vulcan` in online SQLite backups alongside the
existing database; each database's WAL must be handled through SQLite's backup
API. See [service documentation](automation/coop/README.md) for isolation and
protocol details.

## Million-dollar PvP rounds · 0.7.0

Choose **PvP**, launch with `--mode=pvp`, or use
`?mode=pvp` on Web. The first server-accepted **held cash** balance reaching
**$1,000,000 or more** wins; unsold cargo and lifetime earnings do not count.
The winner is announced in-game and a fresh round starts automatically.
Transactions are serialized by the authority; simultaneous contenders cannot
produce two winners. Co-op and PvP retain separate five-player worlds.
**Practice bots are not included in this release.**
Private saves, co-op progress, accounts and archived recordings are unchanged.

PvP uses the original 36-column mine and Sinclair, without Ria or the western
extension. A green podium icon joins the existing top-right header controls.
Its live leaderboard ranks all connected PvP players by authoritative held cash,
including yourself, with updates after joins, departures, economic changes and
round resets. Equal balances use player ID for stable display ordering, not
victory ordering. The modal follows the green menu palette, supports short
viewports and closes with Close/Escape/controller back. Viewing it pauses only
the local player and grants no server-side protection.

- Stock hull is 10 HP. Directional drill contact works on the ground and in flight;
  damage integrates elapsed time rather than packet count. Passive player contact
  causes no damage. Genuine hard terrain landings can still damage hull.
- Explosives consume inventory and cannot damage their owner. The server owns
  combat, cash collection and death/respawn deadlines. Motion acknowledgements
  rebase corrections over newer local movement instead of rewinding the vehicle.
- Unsupported rock/lava falls with normal gravity. Detachment redraws neighboring
  earth borders. Impact plays the break/splash animation, then keeps its final
  broken/puddle frame while blinking faster until removal at 2.5 seconds. Late
  snapshots cannot restore intact sprites or resurrect expired residue.
- Death transfers all cash, mineral cargo and consumable items to the money bag.
  Bags fall onto solid earth, fall again when support is removed, and can be
  collected by touching or hovering within 0.1 tile of hull clearance. Earth
  blocks collection. Cash and consumables transfer independently of bay space.
  Mineral units are randomly selected from those that fit the collector's
  remaining weighted bay capacity; uncollected minerals stay in the bag.
  Serialized pickup prevents duplicate loot, including competing collectors.
- After ten seconds, respawn restores stock upgrades, full stock hull and fuel,
  with no cash, cargo or consumables; transmissions remain for that round.
  Fuel exhaustion preserves the original wreck animation and sounds and uses
  the same loot-drop/respawn sequence.
- The translucent respawn overlay keeps the live mine visible and reuses the
  original metal frame, green CRT glass and Arial Black menu motif. It waits for
  authoritative respawn rather than leaving a zero-second countdown onscreen.
- Fuel, mineral, upgrade and item shops are server-authorized safe interiors:
  entering removes the vehicle from the mine, pauses fuel and prevents damage,
  attacks, mining, outside pickups and obstruction. Entry requires proximity to
  the real door. A blocked exit remains protected until a safe position is found.
  Inventory, help and options do not grant safety.
- PvP account state persists for the current round; anonymous progress ends on
  departure. A win atomically changes the seed and round ID, clears terrain
  edits, bags and hazards, and resets **all** PvP saves, including offline users,
  to the stock $20 start. Transmission rewards cannot be farmed through death
  or stale state. Co-op/private saves and account identities are not reset.

Deploy `pvp.py`, `server.py` and `capture.py` together before publishing 0.7.0
clients. PvP join now advertises `pvp_rounds: 1`; older PvP clients receive an
explicit update-required error rather than entering an incompatible world.
Every PvP mutation carries the current `round_id`. A stale prior-round request
cannot alter the new world. The per-recipient `round_started` snapshot includes
that player's completed state and the fresh state; clients retire pending
transactions and rebuild the world without carrying old local purchases over.
Keep existing OAuth configuration and the SQLite database. See
[authority/storage details](automation/coop/README.md) and
[private disk alerts and storage recommendations](automation/ops/README.md).

Initial damage values remain playtest tunables:

| Attack | Default | Service environment variable |
| --- | ---: | --- |
| Dynamite | 4 HP | `OREBIT_PVP_DYNAMITE_DAMAGE` |
| Plastic explosives | 7 HP | `OREBIT_PVP_PLASTIC_DAMAGE` |
| Falling rock | 3 HP | `OREBIT_PVP_ROCK_DAMAGE` |
| Falling/drilled lava | 5 HP | `OREBIT_PVP_LAVA_DAMAGE` |
| Drill contact | 2 HP/second | `OREBIT_PVP_DRILL_DPS` |

Verification uses disposable databases and isolated native fixtures:

```sh
python -m unittest discover -s automation/coop -p 'test_*.py' -v
python verification/pvp_sandbox_smoke.py
verification/tools/Godot.app/Contents/MacOS/Godot --headless --path godot --script ../verification/pvp_impact_interop.gd -- --mode=private --coop-url=http://127.0.0.1:1 --coop-token= --seed=1
```

macOS CI additionally runs the native PvP state, crash, drill, terrain, impact,
fuel and building regressions. The five-client WebSocket smoke checks independent
co-op/PvP capacity, combat, bag collection and real ten-second respawn. Impact art
can be regenerated with `verification/generate_impact_art.py` and Pillow.

## Private play and cross-platform co-op

The startup chooser keeps private on-device play separate from a shared co-op
world with at most five connected miners. Anonymous play requires no account;
the load/entry prompts explain that only account player progress survives leaving.
Co-op never reads or writes the private binary save. The server persists shared
excavations, and account money, cargo, upgrades, items, transmissions and position.
Physics runs locally; the server arbitrates excavation and awards each tile once.
Pausing affects only the local player, not the server or other miners.

Excavating a mineral does not guarantee it fits in the cargo bay: capacity is
measured by mineral weight. Multiplayer shows the cargo-full warning and omits
the pickup sound when the confirmed result adds no mineral. Already-applied
mining replies do not repeat pickup feedback. Capacity, sale values and economic
reconciliation are unchanged. `verification/coop_mineral_feedback_interop.gd`
covers fitting, no-fit and sale-while-reply-pending outcomes.

The **MODES / ACCOUNTS** action is a borderless dark-green two-miner icon with
light-green landing-menu typography. Its visible artwork matches INV's size and
extends the icon row to the right of Help/Options with the existing visual
spacing. The compact co-op player count sits at the far left on the Hull/Fuel
caption line. Account/server-progress labels are omitted from gameplay. The
server menus reuse the green palette and show the signed-in username only once.
Decorative HUD containers and status text ignore pointer input; only their buttons
capture touches, so the co-op overlay cannot mask the navigation joystick.

On compact 16:9 viewports, the gauge/depth/warning group reserves space for the
single-line count, and the original right-hand icons reserve a separate action
slot instead of letting the new icon cover Help. Native anchor offsets are
preserved across live resizing; both action text lines fit within its touch target.

Run the native-touch regression after importing the Godot project:

```sh
verification/tools/Godot.app/Contents/MacOS/Godot --headless --path godot --script ../verification/coop_input_interop.gd -- --touch-controls --mode=private --coop-url=http://127.0.0.1:1 --coop-token=
```

It checks private/co-op movement commands, directional changes, release, pause
cancellation, and opening/returning from the account menu. Layout checks cover
16:9, 16:10, narrow and ultrawide viewports, caption alignment, nonoverlap,
touch-sized targets, complete action text, and live-resize/fresh-scene equivalence.
The isolated endpoint and empty explicit token prevent the probe from contacting
external account or pricing services. The macOS CI build runs the same command.
Real-device acceptance also requires dragging/releasing the stick in co-op and
inspecting the Android header/menu; synthetic input is not a physical-device pass.

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

Co-op offers a primary **Discord sign-in** action, with password and
anonymous entry as alternatives. Web/PWA uses same-tab authorization: a validated,
state-bound callback returns to the initiating game and its private pending poll.
Neither the Orebit session nor the poll credential travels in the return URL.
The packaged PWA worker handles game assets/entry pages, but leaves backend
navigation and redirects to the browser. Navigation preload is disabled: a
speculative callback request can consume single-use OAuth state before normal
navigation repeats it. The archive-based Chromium CI smoke enables service
workers and exercises a single-use backend redirect, rejecting duplicate fetches
and offline fallbacks; this routing check does not simulate Discord auth.
Its local service URL also supplies a deterministic fuel-price fixture and awaits
that startup response before deliberate reloads, so it neither contacts production
pricing nor cancels the engine's pending fetch. Console/runtime errors still fail
the smoke. Public-site verification uses the real service, not that fixture.
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

### Multiplayer connection recovery — 0.7.2

Signed-in Co-op and PvP automatically recover an interrupted game connection for
up to 35 seconds. The green **Reconnecting…** modal retains the current game and
private-save context while disabling local controls. PvP simulation, damage and
respawn timers continue on the server; reconnecting does not grant protection or
a new life. Success rebuilds the visible game from the authoritative snapshot,
including its active camera, rather than replaying uncertain local actions.

In 0.7.3, an excavation left unconfirmed for 20 seconds also starts signed-in recovery,
even if the socket still appears open. Pending excavation requests are discarded,
not replayed; the authoritative snapshot restores terrain and player position.
Anonymous excavation timeouts remain terminal because their progress cannot be
recovered through authenticated session ownership.

Recovery joins include the previous server-issued `resume_player_id`. The service
hands off an existing player only when the target world, authenticated account
and token match. This uses the same player slot; the old socket cannot mutate or
remove its replacement. A different login or anonymous caller cannot take it
over. Deploy the updated service before these clients. No database migration,
account reset, capture deletion, TLS downgrade or additional public port is needed.

Unconfirmed purchases, transfers, mining and other actions are not retried.
Explicit Leave, sign-out, account expiry, server/mode changes and server policy or
save failures end recovery. Exhausting the deadline returns an honest connection
error with the private save restored and the saved sign-in retained. Initial
connection errors and anonymous progress semantics are unchanged.

The native recovery regression runs in macOS release/PR validation using a
temporary, isolated user-data override that is removed before export. For manual
checks, run `verification/coop_state_interop.gd` only against a staged project
whose custom user-data directory is not the installed game's directory. Its
auth-expiry cases intentionally clear their fixture session file.

### Always-on gameplay capture

Normal private, co-op, PvP and Vulcan gameplay is recorded automatically, including
anonymous play; there is no opt-in switch. Capture uses the configured co-op
HTTP service even during private play. The isolated bot/training environment is
not started by capture or export. This section describes the capture protocol
and operating procedure, not a receipt for published clients or a VPS deployment.
The mode chooser distinguishes device-local private saves from server-stored
gameplay recordings and discloses automatic recording in every mode.
Manifest `actor` distinguishes normal runtime controls (`human`) from a configured
replay runner (`replay`). Replay archives are not human demonstrations; export
rejects mixing actor types and labels Minari provenance accordingly. Automated
capture verification must use an isolated local service/archive root, not upload
test fixtures to the live dataset.

The client obtains an opaque, short-lived session capability from
`POST /api/captures/session`, then uploads gzip JSONL to
`POST /api/captures/{session_id}/chunks/{chunk_index}` with a separate Bearer
capture token. Anonymous capability issuance is intentionally available; every
chunk upload requires its capability, not a public arbitrary-file upload.
Co-op/PvP link the capability to their WebSocket session for sanitized server
event correlation. Tokens remain in memory and are never archived or put in URLs.
The server validates a fixed allowlisted schema and writes canonical gzip JSONL,
not arbitrary JSON or raw WebSocket packets.

Archives contain observations before and after each applied movement interval,
item use, shop entry/exit, purchases, sales and cargo drops, plus money/hull/fuel
deltas, physics ticks, elapsed milliseconds and episode boundaries. Each chunk
includes a checkpoint, seed, engine version and a SHA-256 runtime-source
fingerprint; the fingerprint is **not** a release commit or complete binary hash.
Observations include numeric player state, inventory, cargo, upgrade tier indices
and a row-major visible local 9×9 terrain grid. Grid codes are -1 unknown/not
visible, 0 traversable, 1 soil, 2 other solid, 3 lava, 4 gas and 10–19 minerals.
This is a partial observation, **not** a full world/RNG snapshot or a promise of
bit-exact replay. Credentials, chat, names, account identifiers, IP addresses and
raw network messages are excluded. Random capture/episode IDs correlate archives,
not accounts; behavioral captures are still private operator data.

The source fingerprint concatenates each filename's UTF-8 bytes followed by its
file bytes, without separators, in this fixed `godot/scripts/` order:
`main.gd`, `port_player.gd`, `game_ui.gd`, `coop_client.gd`, `coop_session.gd`,
`world_data.gd`, `game_data.gd`, `gameplay_capture.gd`. Before a direct Godot
export, run `python3 verification/bake_capture_build.py` against the source project
(or `--project <staged-project>` for a staging copy), **then** export that same
project without changing those sources. The generated embedded fingerprint keeps
provenance available when export strips script text. Release staging and
`verification/build_web.py` perform this baking automatically.

Physics ticks are at 50 Hz and may repeat while paused. Chunk rotation does not
end an episode. Private death is terminal; scene changes, disconnect and deliberate
shutdown are truncations. PvP and Vulcan death/respawn are life events, not match termination.
A normal PvP round end is terminal (`round_end`) for winners and losers; the
recipient's authoritative completed state is captured before the fresh world is
loaded. New rounds begin new episodes. Existing archives remain readable; use
the updated exporter/validator for recordings containing the new boundary.
Separate authoritative records retain allowlisted outcomes and safe correlation
sequences (and hashed request correlation where available), not account identities.
An absent authoritative record is missing evidence, not an inferred success.

#### Storage, failures and operator access

`OREBIT_CAPTURE_DIR` overrides the archive root; otherwise it is `captures/`
beside the service database. The VPS operator root is
`/var/lib/orebit-coop/captures`, outside the public Web root, with service-owned
0700 directories and 0600 files. Service code lives in `/srv/orebit-coop`.
Session chunks are `<root>/<32hex-session>/<8digit-index>.jsonl.gz`;
authoritative events are under the same session's
`authority/<12digit-first-sequence>-<12digit-last-sequence>.jsonl.gz`, batched
at up to 128 records or approximately one second. Copy both trees together using
private operator access; there is no public archive browsing/download endpoint.
The existing HTTPS `/coop` proxy is used; it needs no new public port.

Storage pauses admission/writes at **80% filesystem usage**, accounting for the
incoming write and a 16 MiB safety reserve. It never deletes archives to make room.
Current protocol bounds are 256 KiB compressed / 2 MiB decompressed per upload,
1,000 transitions per chunk, 4,096 chunk indices and a conservative 256 MiB
session budget (compressed transition bytes plus raw authority reservations).
Capabilities expire after 24 hours, at most 512 are active, and each permits
120 chunk requests per minute.
Capacity/rate limits, service restarts, expired capabilities and network failures
must not pause gameplay or change game outcomes.

The client flushes after at most 100 transitions, approximately 128 KiB raw data,
or two seconds, and retains about 8 MiB of pending transition data in memory.
Failed requests retry with exponential backoff capped at 60 seconds; an insecure
non-loopback endpoint is not used. When the queue fills, newer chunks are dropped,
with loss ranges reported when subsequent records survive. This is bounded
buffering, **not** guaranteed capture delivery: there is no durable client spool.
A deliberate window close allows only a bounded two-second flush grace; crashes,
browser/tab termination and prolonged outages can lose the unsent tail, including
its terminal record. Keep incomplete archives; do not invent transitions or
declare an open chunk terminal. Server authoritative event buffering has a
256-record pending queue and may leave sequence gaps under overload/storage
failure. Surviving `server_gap` events report known authority-loss ranges; losing
the socket before that notice can leave only missing referenced sequence evidence.

For an isolated local run, set an explicit archive root rather than an existing
private-data location:

```sh
OREBIT_CAPTURE_DIR=/tmp/orebit-capture /tmp/orebit-coop/bin/python \
  automation/coop/server.py --db /tmp/orebit-capture.sqlite3
# Launch a normal client with --coop-url=http://127.0.0.1:8765.
```

#### Validate and export to Minari

The standalone exporter does not import the RL environment, launch Godot or
train anything. Validation uses the server's strict stdlib-only schema validator.
Export uses the real installed **Minari 0.5.4** HDF5 backend and **Gymnasium
1.4.0**, with NumPy 2.x and Pillow (required by Minari's backend import).
Dependencies are isolated from training requirements:

```sh
python3 -m venv /tmp/orebit-capture-export
/tmp/orebit-capture-export/bin/python -m pip install -r orebit_rl/capture-requirements.txt
python3 orebit_rl/capture_export.py validate /tmp/orebit-capture
MINARI_DATASETS_PATH=/tmp/orebit-minari /tmp/orebit-capture-export/bin/python \
  orebit_rl/capture_export.py export /tmp/orebit-capture --dataset-id orebit/capture-v0
```

Use an archive root, a single session directory, or explicit chunk files as inputs.
Schema/build/engine/mode mismatches, changed episode provenance, overlapping
sequences, mismatched checkpoints and contiguous state/tick discontinuities are
rejected. Different seeds/episodes join only under consistent dataset provenance.
Session-global chunk indices need not start at zero for each episode; transition
sequence zero establishes its start. Default export requires a captured start and
terminal/truncated end and no gaps. `--allow-incomplete` explicitly preserves open
tails and splits missing chunks/transitions into separately annotated Minari
segments: it never bridges missing intervals or synthesizes termination/truncation.
Inspect `options.capture_complete` and `options.capture_incomplete_json` before
using such segments. Export into a new dataset ID/version; existing datasets are
not overwritten. Large exports are assembled in memory: select session subsets
instead of passing an unbounded production archive tree.
An episode can span renewed upload capabilities: its random episode ID, immutable
episode provenance and exact adjacent sequence/tick/state must match before
chunks from different upload sessions are joined. Per-transition
`infos.capture_session_id` retains the actual upload session for each source chunk.

Observations are a Gymnasium `Dict` of float64 `state` and int64 `tiles` Boxes.
The ordered state names are saved in `dataset.storage.metadata["orebit_capture"]`.

State order begins `x,y,vx,vy,fuel,hp,max_fuel,max_hp,money,cargo_capacity,alive,
paused,facing,in_shop,digging,grounded`, then `item_0..5` (Reserve Fuel Tank, Hull
Repair Nanobots, Dynamite, Plastic Explosives, Quantum Teleporter, Matter
Transmitter), `cargo_0..9` (Ironium, Bronzium, Silverium, Goldium, Platinium,
Einsteinium, Emerald, Ruby, Diamond, Amazonite), `upgrade_0..5` (Drill, Hull,
Engine, Fuel, Radiator, Cargo tier indices), then `cargo_weight`. Inventory/cargo
values are counts; upgrade values are indices, not names or prices.
After `cargo_weight`, four episode-local peer slots each contain
`peer_N_present,peer_N_x,peer_N_y,peer_N_facing,peer_N_alive` for N=0–3, in that
order. A slot is populated only when the actual remote miner and its Pod visual
are visible in the scene tree and its rendered center is inside the viewport;
hidden/offscreen/absent peers and every slot in private mode are zeroed.
`alive=1` means that visible rendered miner exists, not access to hidden health.
Slot assignment stays stable while the episode-local remote object exists and is
released only when that object is freed; no identifiers/names are archived.
Opponent inventory, upgrades and hidden state are not observations.

The final four fields are `ui_panel_mask`, `selected_shop_item`,
`selected_upgrade_category`, `selected_upgrade_tier` (63 state values total).
Panel-mask bits 0–7 are fuel shop, mineral buyer, item shop, upgrade shop, help,
options, inventory and transmission. Selected shop item is -1 when absent, or the
item-table index (the six inventory items listed above followed by Core Teleporter).
Upgrade selection is -1 when absent; category uses Drill/Hull/Engine/Fuel/Radiator/
Cargo=0–5 and tier uses its upgrade-table index. Selection fields are populated
only while their corresponding shop is visible.

Actions use a lossless float64 Box encoding:
`[move_x, move_y, command_count, kind, item, amount, category, ...]`.
There are enough four-number command slots for the largest recorded action
(at least one); unused slots are zero and `command_count` identifies valid slots.
Kind codes are 1-based alphabetical command enum order, with zero reserved for
padding; the full mapping/slot count is stored in dataset metadata. Exact ordered
commands and sanitized events are additionally preserved in `infos.commands_json`
and `infos.events_json` (HDF5 loads strings as bytes). Server sequence pointers
remain in events; their authoritative archives remain separate and must be kept
alongside source chunks for outcome/reconstruction audits.
For shop entry/exit, category -1 means generic pause/inventory/transmission,
0 fuel shop, 1 mineral buyer, 2 item shop and 3 upgrade shop; purchase/upgrade
commands retain their own recorded item/category/amount values. A server event's
`session_id` is its authority sequence domain, which can differ from the upload
manifest's session after capability renewal. Resolve `(event.session_id,
event.server_sequence)` against the corresponding authority tree, not blindly
against the current chunk's session.

For T transitions there are **T+1 observations and infos**, and T actions,
rewards, termination flags and truncation flags. `infos[0]` is the checkpoint
(`has_transition=false`); `infos[i+1]` records transition i, its source chunk
hash/index/upload-session, ticks, reason and unmodified reward components. The episode manifest
is retained in `options.capture_manifest_json`. Rewards default to **zero**:
capture imposes no training objective. Optional `--money-weight`, `--hp-weight`
and `--fuel-weight` compute the linear combination of recorded deltas; e.g.
`--money-weight 1 --hp-weight 0 --fuel-weight 0`. All components remain in infos
regardless of weights, and weights are recorded in dataset metadata.

After exporting genuine gameplay, load and inspect alignment and boundary flags:

```sh
MINARI_DATASETS_PATH=/tmp/orebit-minari /tmp/orebit-capture-export/bin/python - <<'PY'
import json
import minari
dataset = minari.load_dataset("orebit/capture-v0")
print(dataset.observation_space, dataset.action_space)
print(dataset.storage.metadata["orebit_capture"])
for episode in dataset.iterate_episodes():
    n = len(episode.actions)
    assert len(episode.observations["state"]) == n + 1
    assert len(episode.observations["tiles"]) == n + 1
    assert len(episode.infos["has_transition"]) == n + 1
    assert len(episode.rewards) == len(episode.terminations) == len(episode.truncations) == n
    print(episode.id, n, episode.terminations[-1], episode.truncations[-1])
    print(episode.actions[0], json.loads(episode.infos["commands_json"][1]))
PY
```

Local acceptance exercised native movement, item use, shop purchases/sales and
private death during an upload outage, then recovered a complete archive.
Minari loading verified 96 transitions, 97 observations, diagonal movement,
semantic commands and a true terminal flag. The compiled Web export also uploaded
a valid gzip chunk with the matching embedded source fingerprint in Chromium.
The filesystem admission guard rejected recording on a full host volume; smoke
uploads used a separate empty test volume without weakening that guard.
The native crash probe advances `Box2DClock` explicitly and verifies the body is
still falling before exercising freeze/cancel. Awaiting render/physics signals
does not guarantee an exact native step count when a render frame stalls.
Operator commands above use illustrative paths and dataset IDs. Primary APIs:
[Minari create_dataset_from_buffers](https://minari.farama.org/main/api/minari_functions/)
and [EpisodeBuffer](https://minari.farama.org/main/api/data_collector/episode_buffer/).
No environment recovery is registered: the capture is observational data, not a
fabricated Gymnasium simulator.

#### Planned Backblaze B2 migration (not enabled)

VPS disk is the current archive sink. No B2 credentials, uploads, lifecycle
deletion or active local deletion are configured by this feature. A future
reviewed migration must first inventory immutable local chunk and authoritative
objects, recording session/path, schema, compressed-byte SHA-256 and byte count.
Use a private B2 bucket and a least-privilege upload credential kept only in the
operator secret store. Upload by immutable content-addressed/versioned keys;
retry idempotently and never overwrite different bytes at an existing key.

Read back each uploaded object and verify byte count, SHA-256, gzip integrity,
JSONL schema and manifest identity against the local inventory. Persist a
durable local-to-B2 receipt/index, audit completeness and perform sampled restores
plus a real Minari export/load before changing readers. Keep local archives
intact throughout cutover, maintain the disk admission guard, and treat failed or
unverified uploads as local-only, not migrated. Only a separately approved
retention/deletion policy after verified restores may consider deleting local
copies; migration itself must never silently reclaim them. B2 lifecycle rules
and retention periods require their own explicit review.

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