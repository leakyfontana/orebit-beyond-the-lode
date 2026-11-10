# Co-op service

## Vulcan isolation and authority

Vulcan joins use `mode: "vulcan"` on the existing WebSocket endpoint. Native and
Discord authentication requests select the same scope with `mode: "vulcan"`;
GET session validation and logout also accept `?mode=vulcan`. The configured
SQLite database filename plus `.vulcan` stores separate users, password hashes,
tokens, OAuth flows, saved states, seed, excavations and worm runtime. Tokens
cannot cross scopes. Co-op and PvP retain their existing authentication database.
The client keeps Vulcan identity and pending native OAuth in a separate session
file. Include both databases in consistent online SQLite backups; do not copy a
live database without its WAL.

`joined` and `vulcan_tick` contain a `worm` snapshot with fifteen head-first world
coordinate `segments`, cardinal `direction`, `speed`, `step_interval`,
`target_player_id`, `last_drill` and `server_time`. State packets add a boolean
`drilling`, reporting actual drill activity rather than merely held movement.
Fresh drilling packets select the nearest active driller; short drill bursts are
recorded even between simulation ticks. Without an active driller, the worm
chooses random legal non-reversing cardinal steps instead of pursuing old noise.
Speed is 2.25 tiles/second (37.5% of stock flight speed). Only the head kills miners,
including swept head/player movement; the body is harmless but still excavates.
Updates and simulation share the world lock. Excavation and death are saved
before publication; the worm awards no ore. Tick `terrain_changes` contain
`[tile_x, depth, 0]`. Saved ten-tile trails retain their head/path and grow the
extra tail segments as they move, without inventing a path through scenery.
Clients render the snapshot's segment count; they do not impose another length.
Older ten-segment Android clients must be updated for the fifteen-segment world.

`worm_death` and `worm_respawn` include `player_id`, authoritative `state`,
`state_revision`, `respawn_at` and `server_time`. Death loses cargo/consumables
but preserves money/upgrades. Respawn after three seconds restores upgraded
hull/fuel at the Co-op surface pad. Revisions reject stale pre-death inventories;
only authority can revive. Authenticated reconnect handoff preserves the current
life and does not reset the worm or grant invulnerability. Guest persistence is
unchanged. Simulation advances only while miners are connected.

Run deterministic mechanics and real HTTP/WebSocket regressions with:

```sh
python -m unittest discover -s automation/coop -p 'test_*.py'
```

`test_vulcan.py` covers scope rejection, durable independent progress, reconnect,
target selection, random roaming, safe body contact, swept head kills, all-body
excavation, retained money, resource loss, stale writes, respawn and saved-trail
growth. Scoped Discord callback/poll, cancellation and pending-flow restart cases
live in `test_auth.py`.

## Internal state models

Service startup/shutdown, OAuth transitions, capture admission/publication, and
log ownership use explicit enum states without changing wire or storage schemas.
PvP uses `SimulationPhase` instead of `failed`, `SavePhase` for runtime save
eligibility (`stage_runtime()` stages a mutation), and `BodyMotionPhase` for
gravity results. Replay admission and economy reconciliation return enums rather
than boolean decisions. Fuel quotes use private enum-governed cache state while
retaining the bounded system `curl` transport and Eastern-midnight expiry.
Deploy the backend files together and restart the service; no new data migration
or engine build is required.


## Signed-in connection recovery

A recovery `join` may include the previous `resume_player_id`. Under the target
world's lock, an existing logical player can be reused only with the same
authenticated user and token digest. Check this before capacity: a valid resume
uses its existing slot. Normal duplicate joins, other tokens and anonymous
callers do not acquire that player's socket or state.

Socket ownership is checked inside the world lock before mutations and removal.
Handoff preserves authoritative state/revision, PvP motion/life/round state and
capture sequencing. Retiring transport closure is service-owned, asynchronous
and bounded; an old send failure or finalizer cannot close/remove the replacement.
If the old player has already been removed, authenticated saved-state restoration
uses the normal join path.

Clients bound recovery to 35 seconds, hold local controls and rebuild from the
joined snapshot without replaying unconfirmed actions. PvP authority continues
during that interruption. Explicit leave, sign-out, expiry and server failures
remain terminal; anonymous persistence is unchanged. Deploy this additive service
change before the 0.7.2 clients, preserving the existing database and archives.

## PvP round authority and death loot

PvP uses the isolated `<configured-world-id>:pvp` database world. The first server-accepted credit that makes a miner's **held cash at least $1,000,000** wins; cargo value, spending, and co-op balances do not count. Validated sale/state reconciliation, transmission bonuses, cash-paying mined treasures, money transfers, and death-bag pickups all check the threshold. A reconnecting historical saved balance already over the threshold also finishes its round.

The existing PvP `world_lock` orders joins, every WebSocket mutation, simulation ticks, persistence, and publication. A tick stops at the first winning bag recipient, before another bag/recipient can overtake. Fresh terrain generation runs in a worker thread while that lock remains held. There is no scheduled/delayed reset task.

A single SQLite transaction records the new seed, new opaque `round_id`, and previous winner, resets **all** PvP saved player states (including offline accounts), clears PvP terrain overrides/excavations and runtime, and saves connected players at distinct stock spawn pads. Connected players' request deduplication, damage/blast cooldowns, motion sequence/credit, teleport permission, and building/death state are reset before publication. Cash returns to the stock starting $20; upgrades, consumables, cargo, and transmissions return to stock. Accounts, tokens, co-op/private worlds, and capture archives are not reset. A failed reset freezes PvP authority rather than later saving an uncommitted winner; restart resumes the last durable transaction. SQLite retains the current round identity and last winner across restarts without replaying a gameplay announcement.

### WebSocket contract

- PvP join advertises integer `pvp_rounds: 1`. Clients without round support receive `client_update_required` before consuming a player slot; co-op join is unchanged.
- `joined`, PvP snapshots (`pvp_tick`), state synchronization/acknowledgments, and mutation results include the current string `round_id`.
- Every PvP `state`, `mine`, `transfer`, `blast`, `damage`, `claim_transmission`, and `building` request **must** carry the exact current `round_id`. Dispatch checks it under `world_lock`, before touching state, request IDs, motion sequence, or cooldowns. Missing/stale IDs receive `round_rejected` (`code: "stale_round"`, current `round_id`, original `request_id`) followed by a current `state_sync`; the connection stays open. Co-op requests are unchanged.
- A winning action does not send an old-round success acknowledgment. Instead, each connected PvP player receives exactly one `round_started` event: the recipient-specific `joined` shape (`player_id`, public `world_id`, `seed`, `excavated`, `players`, `state`, `state_revision`, `round_id`, and normal PvP snapshot details) plus `winner: {player_id, name, amount, round_id}` and that recipient's `completed_state`. The winner's `round_id` identifies the completed round; the top-level ID identifies the new round. This is the single in-game winner announcement, not a Discord gameplay announcement.
- Clients must atomically discard queued old-round mutations/motion and economic baselines, replace peers and terrain from `round_started`, then display its winner. Public peer snapshots include `state.player_money` for a live connected-player leaderboard. Reconnecting clients receive the durable current `joined` snapshot, not a repeated winner event.
- The client records `completed_state` before replacing the world and closes the old recording with terminal `round_end`, not a disconnect/scene truncation. New worlds start new capture episodes; a winning pickup's final cash/inventory is not replaced by the stock start in the archived ending. Stale-round control replies do not open account/error dialogs over the winner announcement.
- Direct mechanics methods are internal and expect the caller to hold `world_lock`; round rejection belongs to WebSocket dispatch. Internal test messages can include the current `world.round_id` just like production messages.

### Death bags

A lethal authoritative damage application creates at most one bag containing the victim's cash, mineral cargo, and consumables, then zeros those holdings on the victim. Bag creation, pickup, and player/runtime saves share the same world lock. Upgrades are not loot. Legacy saved cash-only bags load with empty cargo/items.

Cash and consumables transfer independently of cargo capacity. Mineral pickup repeatedly chooses a random fitting **unit**, with each eligible unit equally likely, and deducts its actual mineral weight from the collector's current bay capacity. The loop is bounded by the largest bay (120 weight units), even for very large stacks. Non-fitting minerals, capped consumable stacks, and cash that would exceed the balance cap remain in the bag. A full/busy collector cannot destroy the remainder; another collector can take it, and it survives service restart. Inventory counters are finite whole units bounded by 1,000,000,000; invalid historical bag counters are treated as empty. A bag disappears only when its cash, cargo, and consumables are all empty.

### Behavioral smoke checks

Use only temporary test databases, never a live player-data database. From `automation/coop` with its Python requirements installed:

```sh
python -m unittest test_pvp.PvpMechanicsTest test_pvp.PvpNetworkTest
```

The real subprocess/WebSocket scenario `PvpNetworkTest.test_real_competing_sales_durable_round_offline_reset_and_stale_routes` seeds synthetic near-winning accounts in its temporary database, races sales, checks exactly one winner/reset per connected recipient, rejects stale/missing IDs on every mutation route, checks offline reset and co-op retention, and restarts the service to check durable seed/round identity. Mechanics cases cover every cash credit path, first-winner tick ordering, failed SQLite reset rollback, death-loot conservation, weighted/full bays, bounded counters, and reloaded remaining loot.

## Human-priority production PvP bot pool

The public PvP world has **five real connected players**, not five placeholder
scoreboard rows. `orebit-pvp-bots.service` keeps five deterministic native clients
warm when no humans are present and targets `5 - humans` thereafter. A human
joining a full bot-containing room atomically replaces its lowest-ranked bot:
minimum integer held cash, then greatest `player_id` on a cash tie, matching the
existing leaderboard order. Humans are never eviction candidates. Five humans
mean zero bots; a sixth human receives the normal full-room response.

Human replacement preserves five logical members under the PvP world lock.
Departure, worker failure and service startup require a brief real-client refill;
health and snapshots report the actual population during that interval. Invalid
joins, duplicate accounts and unsupported clients do not evict anyone. Retiring
socket cleanup cannot remove or mutate a replacement. Eviction saves the bot's
ordinary profile without death loot, a wallet grant or an equipment reset.

Trusted identities come only from the main store's `pvp_bot_accounts` registry,
never names or client flags. Dedicated bot accounts may join PvP only. Vulcan's
separate identity namespace, normal co-op, existing accounts and million-dollar
round transactions remain unchanged. Native workers discard the entire policy
brain after a new round, not just its route. The promoted cycle-66 policy and its
checksum are recorded in `automation/pvp_bots/pool.json`; this is deterministic
gameplay, **not an RL training run or approval to begin one**.

### Runtime and credentials

- Code: `/srv/orebit-pvp-bots/current`, an immutable release with `provenance.json`.
- Native game: `current/game`; official Godot 4.7.2 Linux: `current/runtime/godot`.
  `automation/pvp_bots/package.py` reuses normal release staging and requires the
  exact current `verification/box2d_build.json` API, physics and fixture patches.
  Experimental native libraries and stripped-down physics are not substitutes.
  Linux extension mapping and duplicate file-logging disablement affect only the
  generated bot project; errors remain in bounded supervisor logs.
- State and worker logs: `/var/lib/orebit-pvp-bots`, mode `0700`, dedicated
  `orebit-pvp-bots` user. Each slot has isolated HOME/XDG, save/settings, normal
  cached tokens and bounded redacted logs. One failing worker does not stop four
  healthy opponents. Native gameplay runs at normal elapsed time, capped at
  50 FPS, without `--fixed-fps` or resource/economy privileges.
- Private configuration: `/etc/orebit-pvp-bots.env`, mode `0600`, supplies
  `OREBIT_PVP_BOT_CONTROL_KEY`. Both authority and worker service load it through
  systemd; the authority drop-in is `orebit-coop.service.d/pvp-bots.conf`.
  Never put the key, passwords or tokens in command arguments or release files.
- `GET /api/pvp/bot-pool` requires a separate Bearer control key and is unavailable
  without configuration. It returns actual membership and desired bot count;
  normal player tokens do not authorize it. The supervisor uses loopback port
  8765, with no additional public port or TLS downgrade.

Provision ordinary Argon2 accounts as the authority's database owner:

```sh
/srv/orebit-coop/venv/bin/python /srv/orebit-coop/bot_pool.py provision \
  --db /var/lib/orebit-coop/coop.sqlite3 \
  --accounts /var/lib/orebit-coop/pvp-bot-accounts.json
```

The CLI is idempotent, publishes owner-held `0600` credentials, refuses to adopt
existing human usernames and grants no game state. Install a `0600` copy owned by
`orebit-pvp-bots` at `/var/lib/orebit-pvp-bots/accounts.json`; retain the original
private provisioning document. Do not delete credentials to resolve a mismatch.
Supervisor settings also accept `OREBIT_PVP_BOT_ENDPOINT`,
`OREBIT_PVP_BOT_CREDENTIALS`, `OREBIT_PVP_BOT_GAME` and `OREBIT_PVP_BOT_GODOT`.
The service uses standard-library Python, CPU quota 150% and memory maximum 2 GiB.

### Deployment, proof and rollback

Before public enablement, back up **both** databases with SQLite online backups,
guard live source hashes against concurrent releases, and deploy `server.py`,
`pvp.py` and `bot_pool.py` together. Import the staged Linux game with its real
engine/library, then make its code/cache root-owned and read-only to the worker.
Prove five native clients, real mining and wall-clock pacing inside the worker
resource limits against an isolated authority/database. Exercise human priority,
five-human capacity, refill, one-worker failure and native round reconstruction.
Synthetic near-winning states belong only in isolated test databases; never
force a production win/reset as a deployment check.

The real HTTP/WebSocket and provisioning regressions are:

```sh
python -m unittest discover -s automation/coop -p 'test_bot_pool.py' -v
```

Observe `systemctl status orebit-pvp-bots`, the unit journal, private rotating slot
logs and `/coop/healthz`'s truthful `modes.pvp.{players,humans,bots}`. The normal
production client's PvP entry still joins a bot-filled room; no client release is
required. Use the normal game, not an older loopback-only playtest APK.

Bot-only rollback is `systemctl disable --now orebit-pvp-bots`: leave authority,
accounts, credentials and game data intact, allowing normal human-only PvP.
For authority rollback, stop the bot unit, restore the backed-up `server.py` and
`pvp.py` together, remove only this rollout's authority drop-in, reload systemd
and restart `orebit-coop`. Keep the additive registry and all live databases;
restoring an old database would discard legitimate progress and is not a normal
code rollback. Do not restart unrelated services or change the public client.

### CI-built native client updates

The Web build produces `dist/pvp-bots/Orebit-<version>-pvp-bots.zip` and
`native-bots.json` inside `beta-production-web` (validation builds use
`dist/validation/pvp-bots`). Failure to package/import/check the native runtime
fails that required build. The ZIP includes the official Linux engine, freshly
compiled pinned Box2D, current game scripts/imported runtime assets, unchanged
promoted policy and supervisor; it contains no accounts, tokens or database.
`native-bots.json` binds archive checksum/size and provenance checksum to the
exact source commit and release version.

The existing outbound publisher automatically deploys **Web**, not this worker
service. After required PR checks, squash merge and successful main publication,
the operator downloads that exact successful **main-push** CI artifact, verifies
its commit/version/archive/provenance/full file inventory, and installs a new
root-owned immutable `/srv/orebit-pvp-bots/releases/` directory. Stop only
`orebit-pvp-bots`, atomically switch `current`, then restart that unit and prove
normal authenticated fill/contact against the existing authority. Do not edit
scripts on the VPS, build a different artifact locally, restore a database, or
restart `orebit-coop` for a client-only update. Preserve the previous symlink
target for worker-only rollback and retain `/var/lib/orebit-pvp-bots` unchanged.
The native package is assembled by CI; the scoped operator cutover is not an
automatic worker deployment and must not be described as one.
