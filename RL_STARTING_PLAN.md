# Orebit: starting reinforcement learning

## Runnable environment: implemented

The environment is a proper Gymnasium environment, with pinned dependencies
isolated in `.venv-rl/`. Recreate the Python environment from the repository root:

```sh
python3.13 -m venv .venv-rl
.venv-rl/bin/python -m pip install --only-binary=:all: -r orebit_rl/requirements.txt
```

Verify the real runtime:

```sh
.venv-rl/bin/python -m orebit_rl.check && .venv-rl/bin/python -m orebit_rl.smoke
```

The resolved dependency lock is `orebit_rl/requirements.txt`: Gymnasium 1.4.0,
Stable-Baselines3 2.9.2, PyTorch 2.15.0, NumPy 2.5.4, and pinned transitive
dependencies. It was installed and checked on CPython 3.13 / macOS ARM64 without
changing global packages or the game's existing dependencies.

The worker uses the installed Godot executable at
`verification/tools/Godot.app/Contents/MacOS/Godot`, or an explicit `godot_bin`,
`GODOT_BIN`, or `godot` on PATH. The existing baked resources and native Box2D
extension remain prerequisites; the Python setup does not import or replace them.
Run Python examples with `.venv-rl/bin/python`.

```python
from orebit_rl import Action, OrebitEnv

with OrebitEnv() as env:
    observation, info = env.reset(seed=12345)
    while True:
        observation, reward, terminated, truncated, info = env.step(Action.DOWN)
        if terminated or truncated:
            print(info["reason"], info["raw_observation"]["cargo"])
            break
```

`OrebitEnv` subclasses `gymnasium.Env`, with `Discrete(5)` actions and a
`Box(-1, 1, shape=(677,), dtype=float32)` observation space. Importing `orebit_rl`
also registers `OrebitCollect-v0` for `gymnasium.make`. It is headless-only:
`render_mode=None`. Its flat observations are suitable for SB3's `MlpPolicy`.
The first saved CPU PPO model and validation comparison are recorded below.

- `reset(seed=None, options=None)` starts a fresh headless Godot process.
  Explicit seeds are nonnegative signed-32-bit integers and reproduce that world.
  With no seed, the next world seed is drawn from Gymnasium's persistent RNG;
  resetting with an explicit seed also resets that RNG. No failed-seed retries
  or hidden world filtering occur.
- Reset options are `max_steps` (default 300) and optional `initial_fuel` for
  controlled resource scenarios.
- `step(action)` accepts `Action.IDLE`, `LEFT`, `RIGHT`, `UP`, or `DOWN` (integers
  0–4). A decision advances five fixed physics/render cycles at 50 Hz, or stops
  early on success/failure. Simulation blocks while Python chooses an action.
- Observations are fresh, finite normalized NumPy vectors, not game dictionaries.
  `info["raw_observation"]` preserves the unmodified tile patch, position/velocity,
  flags, resources, cargo, scene, and pause state for diagnostics and evaluation.
  This raw state is not supplied to the policy.
- Other `info` fields include seed, target/start, decision count, actual physics
  ticks, simulated seconds, backend class, modal rule, and terminal reason.
- Collection earns +0.999 including the decision cost. Resource/death/scene
  failure earns -1.001. Other decisions cost -0.001. A time limit sets
  `truncated=True`; success/failure sets `terminated=True`.
- `close()` or the context manager reaps the worker and removes temporary files.
  Transport/startup errors raise `OrebitError` with engine logs. A terminal
  episode requires a new reset.

### Observation encoding

The first 648 features encode a row-major 9×9 tile patch, with eight one-hot
channels per tile. Categories are 0 outside, 1 traversable, 2 other diggable,
3 mineral, 4 rock, 5 lava, 6 gas, 7 indestructible. One-hot encoding avoids
suggesting that category 6 is numerically “more” than category 3. Tile rows
increase downward; world-coordinate y increases upward.

The remaining 29 scalars follow `SCALAR_NAMES` in `orebit_rl/environment.py`:

- World x/y use `tanh(x/36)` and `tanh(y/600)`, referencing the current map
  dimensions. Within-tile x/y fractions map to [-1, 1].
- Velocity x/y use `tanh(v/10)` with a reference speed of 10 world units/second.
- Facing, grounded, flying, digging, and paused flags use 0/1.
- Fuel/max-fuel and hull/max-hull ratios clip to [-1, 1], retaining signed
  depletion; cargo-weight/capacity clips to [0, 1].
- Maximum fuel, hull, and cargo capacity use `tanh(value/reference)` with
  references 10, 10, and 7 respectively.
- Ten mineral counts use `tanh(count)` in the documented `MINERAL_NAMES` order.
- The final two features are whether the scene is Game and the elapsed
  physics-tick fraction of the configured episode limit, clipped to [0, 1].

Categorical values, finite numbers, and positive capacities are checked before
encoding; malformed worker state fails rather than being replaced by invented
observations. Extreme finite ratios are intentionally bounded; raw values remain
available in `info`. The scale constants describe the current stock-game task,
not learned running statistics.

**Controlled start, not full gameplay:** the worker lets the normal mothership
arrival finish, then scans naturally generated minerals row-major at tile rows
6–40, excluding outer columns. The authored body bounds must fit traversable
terrain above the ore, pass native collision queries, and settle grounded with
its bottom detector on that ore. The only placement is before episode start;
terrain is never rewritten and cargo is never granted. Seeds without a valid
start fail explicitly. This selector is not the future held-out seed manifest.
Stock hull/fuel are restored after settling unless a fuel override is supplied.
Only informational transmissions are dismissed through the game's existing
close behavior, including authored bonuses; shops are not automatically serviced.

Game save/settings paths and engine logs point to a temporary episode directory
before game startup reads settings. Co-op initialization is disabled only in the
RL worker, preventing access to its persistent personal session. Normal game and
replay modes retain their existing input behavior.

**Verification:** Gymnasium's and SB3's default environment checkers both passed
against the real runtime, followed by the smoke, on attempt 1 of the authorized
maximum 5 for this integration. No checker warnings were emitted.
`pip check` also reported no broken requirements in `.venv-rl`.

On local Godot 4.7.2 with the actual `Box2DDirectSpaceState2D`, seed 12345
selected ore at tile (9, 8). Holding DOWN collected one Bronzium in 13 decisions /
63 physics ticks / 1.26 simulated seconds. Same-seed reset and action-prefix
observations matched after a 0.1-second client delay. Actual fuel consumption
terminated after one tick and preserved a negative normalized fuel ratio; a
one-decision limit truncated after five ticks. A NumPy `int64` action sampled
from the declared action space was accepted by the real worker.

The checks above establish the narrow game interface, not learned-policy quality.
The fixed seed manifest and runtime benchmark are recorded below; the proposed
80/100 learned-agent target has **not** been evaluated.

## Frozen seed manifest and measured throughput

Completed artifacts:

- `orebit_rl/seed_manifest.json`: 200 training, 50 validation, and 100 test
  seeds, disjoint and fixed before training. All 350 passed real start checks
  and collected mineral using the fixed DOWN controller. No seeds were rejected.
- `orebit_rl/runtime_snapshot/godot`: the pinned runtime used for verification
  and benchmarking. Its 4,320 independently copied files total 72,913,805 bytes.
  `snapshot.json` inventories every captured path and content hash. This local
  snapshot is intentionally ignored by Git; keep it to reproduce these results.
- `orebit_rl/benchmark_results.json`: complete timings, settings, per-step
  counters, and manifest/runtime/benchmark fingerprints.

The manifest SHA256 is
`1ebd5841a920156399c43a8f025cb690e01e3b524ca54c10c621c32bbb55983d`.
Its `runtime_project` points to the snapshot, not the actively edited game.
Verification and benchmarking automatically select that pinned project and
refuse a conflicting override or modified snapshot. Active Godot files and
personal saves were not modified by this work.

### Generation, screening, and provenance

Candidates are SHA256-derived nonnegative int32 seeds in a deterministic
counter sequence. Screening requires an unpaused, grounded, full-resource,
empty-cargo start above natural mineral, followed by actual collection with a
fixed DOWN controller. The first 200 accepted candidates become training starts,
the next 50 validation, and the next 100 test starts. This is preflight
solvability screening, not policy tuning or learned-agent evaluation. Natural
setup/scripted failures are recorded; infrastructure failures abort.

Two initial 350-candidate scans passed their gameplay checks but were invalidated
by concurrent edits to the active game. Their original evidence remains in
`seed_manifest.partial.json` and `seed_manifest.provenance-drift.partial.json`.
With explicit user approval, a separate runtime was frozen, then every one of
the 350 existing records was re-evaluated against it. No seed membership changed;
all initial observations and scripted outcomes matched the second scan exactly.
Only after that full replay and unchanged before/after fingerprints was the
schema-2 manifest published. Its `revalidation` field audits the original partial
hash, provenance fingerprint, 350 evaluations, and zero changed records.

The capture compares original inputs before and after copying, checks copied
bytes independently, and publishes only a consistent self-contained runtime.
It includes native libraries and imported resources, but excludes exports,
Android build files and editor state. Files are not linked to the active game.
Revalidation and benchmarking also validate snapshot contents after execution.
Python environment/solver code, engine version/binary, packages, and runtime
inputs are fingerprinted; changes fail explicitly rather than silently
reinterpreting earlier evidence.

Commands actually exercised for the successful frozen-runtime path:

```sh
.venv-rl/bin/python -m orebit_rl.snapshot
.venv-rl/bin/python -m orebit_rl.seeds --revalidate-partial orebit_rl/seed_manifest.partial.json --path orebit_rl/runtime_snapshot/godot
.venv-rl/bin/python -m orebit_rl.benchmark
```

To validate the retained capture without running gameplay:

```sh
.venv-rl/bin/python -m orebit_rl.snapshot --validate
```

To independently replay the complete final manifest later, use
`.venv-rl/bin/python -m orebit_rl.seeds --verify` (another 350 game resets).
The successful full revalidation above already replayed every record; a further
full `--verify` pass was not run against the same snapshot within this task.
Generation refuses an existing manifest; partial evidence is never silently
resumed. Explicit partial revalidation requires a complete prior scan, a frozen
runtime, and a new real evaluation of every candidate without replacing seeds.
For a new experiment, capture a new snapshot and generate a new manifest with
`--path` and `--manifest`, rather than overwriting these fixed splits.

Total seed evaluations used: 1,053 of the approved 1,200, including both
invalidated scans, the complete frozen replay, and three benchmark resets.
The work remained within the five verification-and-fix-cycle limit. No model
training or dependency installation was performed during this milestone.

### Measured runtime throughput

The benchmark used the first three **training** seeds only: 200 IDLE decisions
per episode, no warmup, one fresh isolated worker per episode. All three reached
their configured time limit normally. Across 600 decisions, the game advanced
3,000 actual physics ticks / 60 simulated seconds.

| Measurement window | Decisions per wall-clock second |
| --- | ---: |
| Synchronous step calls only | 283.18 |
| Reset plus step calls | 97.58 |
| Whole episodes, including recording and shutdown | 91.55 |

Mean fresh-process reset cost was 1.343 seconds. Step latency was 3.48 ms median
and 4.22 ms at p95. Step calls advanced simulated time at 28.32 times real time.
Whole-episode timing excludes one-off CLI imports and provenance pre/postflight
checks; the result artifact records those methodological boundaries.

These are game/transport/observation-encoding measurements, not policy inference
or PPO optimization throughput. The 200-decision IDLE episodes amortize resets;
short successful mining episodes will have different effective throughput.
Timings depend on machine load and do not imply an estimated training duration.
Benchmark output is preserved by default; use an explicit alternate `--output`
or `--overwrite` for a deliberately requested new measurement.

## First trained PPO baseline

One CPU PPO run completed **20,480 decisions** in 32.1 minutes, within the
approved 90-minute wall cap. It used only the 200 training seeds, with seeded
shuffled permutations. All 200 were visited. The episode trace records 1,220
completed episodes and one unfinished episode at the decision limit; unfinished
work is not counted as a completed success.

The model is a `MlpPolicy` with two 64-unit Tanh layers. Training used seed
20261030, 512-step rollouts, batch size 64, 10 epochs per rollout, learning rate
0.0003, gamma 0.99, and one CPU thread. It executed 40 full rollouts / 3,200
optimizer steps. Initial/final policy hashes differ and all saved parameters
are finite. The saved checkpoint was reloaded on CPU with matching parameters,
spaces, and decision count. No validation-driven model selection or additional
training run was performed.

Artifacts:

- `orebit_rl/ppo_baseline/model.zip`: the saved PPO model.
- `orebit_rl/ppo_baseline/training.json`: parameters, budgets, provenance,
  optimizer-update and reload evidence.
- `orebit_rl/ppo_baseline/episodes.jsonl`: actual train-seed episode records.
- `orebit_rl/ppo_baseline/validation.json`: complete comparison and per-episode
  actions/outcomes.
- `orebit_rl/ppo_baseline/validation.episodes.jsonl`: durable evaluation trace.

Commands exercised:

```sh
.venv-rl/bin/python -m orebit_rl.train
.venv-rl/bin/python -m orebit_rl.evaluate --split validation
```

Existing run directories and evaluation evidence are refused, not overwritten
or automatically resumed. A new training run requires a deliberately selected
new `--run-dir` and a new approved budget. The evaluator reloads the checkpoint
from disk, verifies its hashes/runtime/software, and never calls learning.
It accepts validation only; test evaluation is not enabled.

### Validation comparison

The final checkpoint used deterministic action selection. The baseline sampled
uniformly from the five actions, independently seeded per world with
`SeedSequence([20261031, world_seed])`. Both ran on the same 50 validation seeds
with a 300-decision episode limit; no failures or worlds were omitted.

| Policy | Successful validation episodes | Median simulated seconds to collection |
| --- | ---: | ---: |
| Saved PPO checkpoint | 50 / 50 | 1.26 |
| Uniform random actions | 50 / 50 | 1.72 |

There was **no success-rate improvement**. PPO collected faster; the paired
median time difference was -0.46 simulated seconds. This is an observed
comparison on fixed validation worlds, not a claim of statistical significance.
All 100 test seeds remain unused for gameplay: artifact auditing found no test
seed in training traces or either validation policy's episodes.

This exercise is saturated on success rate. Starting directly above ore and
ending at the first collection does not demonstrate navigation, mineral
selection, returning, selling, refueling, upgrades, or full-game competence.
The next useful task should require additional gameplay decisions, rather than
merely extending training on this already-easy setup. The earlier proposed
20-percentage-point success advantage cannot be shown on this validation set
while random already succeeds on every world; no held-out test claim is made.

## Recommendation

The environment, fixed splits, runtime benchmark, saved CPU PPO baseline, and random-action validation comparison are complete. Before increasing training, choose a harder controlled task that distinguishes useful gameplay from random actions. Keep the test split reserved for final learned-policy evaluation.

The artifacts and measurements above are implemented and observed. Further curriculum and full-game performance criteria remain **proposals**. The saved model handles only the current shallow-ore exercise. Automated bug reporting is out of scope.

In reinforcement learning (RL), an agent repeatedly observes the game, chooses an action, and receives a numeric reward. Its policy is the model mapping observations to actions. An episode is one attempt. Training changes the policy; evaluation measures a frozen policy without further learning.

## Verified source evidence

The runtime is `godot/`, not the original Unity source in `Assets/` (`README.md:3-5`). Useful integration points already exist:

| Source | Existing capability and implication |
| --- | --- |
| `godot/scripts/main.gd` — `_ready` | Accepts seed/replay/capture arguments and loads the baked game asset catalog. Agent mode additionally isolates co-op initialization. |
| `godot/scripts/replay_runner.gd` — `configure` | Redirects replay save/settings paths and opens diagnostic logs. |
| `godot/scripts/replay_runner.gd` — `pre_tick` | Applies scheduled axes, key events, UI invocations, and checkpoints; the replay itself is not an interactive ML API. |
| `godot/scripts/replay_runner.gd` — `post_tick` | Logs resources, cargo, upgrades, map, position, and velocity. |
| `godot/scripts/port_player.gd` — `tick`, `_read_axes` | Downward movement starts bottom digging; horizontal movement on the ground starts side digging. Agent axes replace normal input only in the RL worker. |
| `godot/scripts/port_player.gd` — `_try_start_dig`, `dig` | Successful mineral collection updates cargo at completion, through the real mining sequence. |
| `godot/scripts/game_data.gd` — `resetCargo`, `sellCargo`, `addMineralInCargo` | Collection/sale semantics include cargo-capacity rejection. |
| `godot/scripts/world_data.gd` — `getBlockData`, `halfwayDigBlock` | Halfway-dug state differs from raw map state; zeroed cells do not prove completed collection. |
| `godot/scripts/game_ui.gd` — `startNewGame` | Sets new-game data and requests the Game scene. |
| `godot/scripts/game_data.gd` — `setNewGameData` | Deliberately does not reset all terrain/transient state; the worker uses a fresh process instead. |
| `godot/scripts/main.gd` — `_load_scene` | Generates terrain only when the generated flag is false, then initializes the player. |
| `godot/scripts/game_data.gd` — `initPlayer` | Restores hull but preserves fuel when it equals five; the worker specifies starting resources. |
| `godot/scripts/main.gd` — `_process`, `_physics_process` | Render-dependent digging/animations and physics must both advance. |
| `godot/project.godot` — `[physics]` | Configures Box2D at 50 Hz. The worker checks the actual native backend class. |
| `verification/scenarios/ticket_critical_drilling.json` | Existing fuel diagnostic demonstrates seed, UI, checkpoint, and axis automation, not a learning benchmark. |

## First gameplay task and numeric evaluation target

**Proposed task: collect at least one mineral into cargo while still alive.** Stop immediately on success; returning to the surface, selling, shopping, upgrades, consumables, and boss combat are excluded from this first task. This teaches movement and mining without requiring the full economic game loop.

The current exercise uses a controlled shallow-ore start with real terrain and collisions. Its deterministic selector, stock resources, empty cargo, and no-post-start-teleport rule are described above. It is deliberately easier than normal surface-spawn gameplay and must remain labeled as such.

The fixed DOWN controller demonstrated actual collection on all 350 selected seeds. Those seeds were selected for valid starts and scripted solvability, not learned-model performance. Invalid or unreachable starts must never be discarded merely because a learned policy failed.

- **Success:** total mineral counts in `player_cargo` increases from zero to at least one, with `player_alive == true`, HP > 0, and fuel > 0 in the same completed-step snapshot.
- **Failure:** death, nonpositive HP/fuel, or transition out of the gameplay scene before success.
- **Time limit:** 30 simulated seconds after the playable start, scored as failure for the success-rate metric. In the learning API, mark this as truncation rather than natural termination.
- **Target:** at least **80 successful episodes out of 100 held-out episode seeds**, and at least **20 percentage points above a uniformly random-action policy** on the identical episodes. These are proposed acceptance thresholds, not a prediction.
- The fixed manifest contains 200 training, 50 validation, and 100 test seeds. They have been screened for solvability only; train on training seeds, tune on validation seeds, and reserve test seeds for final learned-policy evaluation. Record any future invalid-start exclusions explicitly.
- Evaluate the frozen policy with deterministic action selection. Seed the random baseline separately and record its RNG seed. Report successes, deaths, timeouts, and median simulated time to success; do not use training reward alone as the score.

If the scripted controller cannot solve valid starts, fix the environment/task definition before spending training compute. Do not quietly lower the target or select evaluation seeds based on model performance.

## Proposed observations

Use structured numbers from the game, not pixels. Screenshots add visual learning and rendering costs before we know whether action/reward/reset works. This first agent is explicitly privileged: internal tile information need not match what a human can see.

- A centered 9×9 tile patch: encode traversable, diggable ground, mineral, rock/indestructible, lava, gas, and out-of-bounds as separate categories. Include mineral value/weight where relevant. Use `WorldData.getBlockData` plus diggability checks, not raw map IDs alone.
- Position within the current tile, velocity, facing direction, grounded/flying/digging flags, and dig progress or target-relative displacement. These avoid treating two different movement/mining states as identical.
- Fuel/max fuel, HP/max HP, cargo weight/capacity, and mineral counts. Normalize continuous values to documented ranges; keep categorical information categorical.
- Menu, transmission, and pause state for environment control. Do not let an invisible modal consume the episode while the agent appears unresponsive.

Define one coordinate convention at the boundary: tile x increases right, tile y increases downward; player world coordinates use upward-positive y. `PortPlayer.position_unity` and `velocity_unity` perform the physics conversion; `_try_start_dig` maps tile coordinates to world coordinates in `godot/scripts/port_player.gd`. Test boundary and halfway-dug cases before training.

## Proposed actions

Use five discrete actions: idle, left, right, up, down. Each selects horizontal/vertical axes in {-1, 0, 1}; all unselected axes must be zeroed to avoid accidentally latched input. No diagonals, mouse aiming, inventory, or item-use actions initially.

Initial action duration: **0.1 simulated seconds**, corresponding to five physics ticks at the configured 50 Hz. This is a proposal; movement and digging may need a shorter or longer duration after scripted-control experiments. It is not equivalent to five replay/render frames. Advance animation/render-dependent gameplay logic on a defined schedule as well as physics.

The environment may start the game and dismiss non-choice informational transmissions consistently before returning control. It must never mine, move, refuel, or award cargo for the policy. If a modal interrupts gameplay, handle it under a documented fixed rule without charging hidden action time.

## Proposed rewards

For the first task, keep reward tied to the actual completion condition:

- +1 on successful collection, awarded once as the episode terminates.
- -1 on death/resource failure or leaving gameplay unexpectedly.
- -0.001 per decision to mildly prefer shorter solutions; no additional timeout bonus or penalty.
- No reward for raw depth, map cells becoming empty, attempted digging, or entering a shop.

A random agent may rarely discover ore. Begin with nearby solvable ore starts, then increase the starting distance only after validation success. This progression is a curriculum: the task becomes harder after learning the easy version. Do not add depth rewards to hide a broken reset or action interface.

## Proposed reset and episode interface

Use the following Python-facing interface, matching Gymnasium's return convention:

- `reset(seed=...) -> (observation, info)` starts an isolated, reproducible episode.
- `step(action) -> (observation, reward, terminated, truncated, info)` advances a fixed amount of simulated time and returns the resulting state.
- `close()` releases the worker process.

The Python environment now implements the Gymnasium contract and normalized spaces on top of local TCP requests to the game worker. It reuses existing movement/state boundaries instead of duplicating the game in Python. Keep engine state authoritative.

The current worker restarts per episode to avoid incomplete in-process resets. It sets temporary save/settings paths before startup, skips persistent co-op initialization, completes arrival, and specifies resources/cargo/upgrades and the deterministic start before exposing the first observation. Never use a personal save directory for future training integrations.

Later optimize resets only after same-seed initial observations and repeated action trajectories agree on the supported engine/platform. A seed option is evidence of controllable randomness, not proof of cross-platform deterministic physics.

## Minimal training approach and prerequisites

1. **Environment proof.** Completed: real reset/step, scripted collection, resource failure, timeout, repeatability, and action-space compatibility.
2. **Runtime benchmark.** Completed: step, reset, and whole-episode timings are recorded above. These IDLE timings are not neural-network training throughput.
3. **First PPO baseline.** Completed: one CPU `MlpPolicy` run over 20,480 decisions, saved and reloaded, with actual optimizer-update and finite-parameter evidence.
4. **Bounded validation.** Completed: deterministic PPO and independently seeded uniform random actions each ran all 50 validation seeds. Success rates tied; PPO collected sooner. The 100 test seeds remain unused. No hyperparameter search or further run is authorized by these results.
5. **Task progression.** Choose a harder gameplay task before more training. Normal surface starts, navigation, safe returns, selling/refueling, and upgrades are not covered by this checkpoint.

The first CPU run completed within its approved limits without installs or runtime changes. Other hardware, worker counts, larger training budgets, and a different curriculum require separate decisions; these measurements do not establish full-game capability.

## Risks and decision gates

| Risk | Gate before training |
| --- | --- |
| Render/physics clock mismatch | Repeated scripted actions advance the same simulated duration and yield consistent mining completion; do not equate replay frames with physics steps. |
| Partial terrain updates mistaken for collection | Score cargo gain, not zeroed map cells; inspect halfway-dug state. |
| Reset leaks | Fresh isolated workers yield identical initial observations for the same seed/start rules; ordinary menu restart is insufficient evidence. |
| Modal UI blocks action | Observe and consistently handle transmissions/pause before benchmarking action effects. |
| Headless/native dependency differences | Verify the configured Box2D extension loads and mining completes on the actual worker runtime. No fallback physics backend. |
| Reward exploits | No post-start checkpoints, free refills, policy-triggered resets, or repeated terminal rewards. |
| Easy task overstated as full gameplay | Publish controlled-start rules and held-out results; do not claim surface-to-sale capability. |
| Training is too slow | Measure throughput without full-map per-frame diagnostic serialization before selecting compute. |

## Initial planning verification (before implementation)

The original planning investigation was read-only apart from this report. The runnable environment and its later runtime verification are documented at the top; the command results below record the initial tooling inspection.

Commands executed:

```sh
command -v godot godot4 Godot
# Exited 1: none found on PATH.
verification/tools/Godot.app/Contents/MacOS/Godot --version
# Exited 0: 4.7.2.stable.official.ed1daf0bf
```

The installed version matches the project's declared Godot 4.7 feature family. The original planning pass did not launch the game; the later smoke now proves that the baked resources and Box2D extension load on this machine.

The initial report check covered citation file/line ranges, source symbols, required sections, and numeric proposal targets in one planning verification cycle. References above now use symbols instead of shifting line numbers. The original runtime milestone used two smoke attempts; Gymnasium/SB3 integration passed its first combined check. Later frozen-runtime revalidation, throughput measurement, and the first CPU training/validation run are documented above with their actual artifacts and limits.
