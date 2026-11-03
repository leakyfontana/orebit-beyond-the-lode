# Co-op service

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
