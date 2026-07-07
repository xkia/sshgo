# Codebase Size Reduction

## Metadata

- slug: codebase-size-reduction
- status: approved
- owner: Engineer
- related_specs:
  - docs/specs/host-port-schema-split.md
  - docs/specs/internal-refactors-and-tests.md
  - docs/specs/review-compatibility-hardening.md

## Assessment

Current project size is about 20.7k lines across Python, Expect, tests, shell,
and Markdown. The largest maintenance hotspots are:

- `tui.py`: curses rendering, form loops, navigation, Recent, and CRUD flows in
  one 1.7k-line class.
- `host_manager.py`: config lifecycle, encryption, CRUD, validation facade,
  runtime wrappers, and compatibility exports in one 1.3k-line facade.
- `tests/test_tui.py` and `tests/test_connection_auth_audit.py`: large integration
  style test modules with repeated config fixtures.
- Historical specs: several accepted behavior specs remain useful but contain
  older schema language after the host/port split.

The high-level module split remains reasonable: config storage, validation,
connection planning, runtime handoff, host-tree helpers, TUI forms/text helpers,
and terminal title handling are already separated. The main issue is not a bad
architecture, but accumulated compatibility wrappers, historical documentation,
and two still-large facade/UI modules.

## Scope

- Define a staged decomposition plan with explicit evidence, expected benefit,
  cost, risk, and exit criteria.
- Remove low-risk code made obsolete by the host/port schema split.
- Update stale documentation that still presents old combined endpoint behavior
  as current accepted behavior.
- Keep active compatibility exports that are explicitly required by
  `internal-refactors-and-tests.md`.
- Do not rewrite the Expect handoff model, curses UI model, or config store.

## Product And Engineering Goals

From a product perspective, the refactor should protect the workflows users care
about most: selecting a host quickly, connecting reliably, transferring files,
and editing config without surprises. It should not consume delivery capacity on
cosmetic module reshuffling.

From an engineering perspective, the refactor should reduce the cost of future
changes by making the likely edit areas smaller and safer:

- TUI display and interaction changes should not require reading all CRUD and
  Recent logic.
- Config schema changes should touch one fixture layer in tests instead of many
  repeated JSON snippets.
- Host lifecycle code should stay behind `HostManager`, but implementation
  details should stop accumulating in that facade.
- Historical docs should not contradict current accepted behavior.

## Current Size Evidence

Measured after the host/port schema split:

| Area | Size | Assessment |
| --- | ---: | --- |
| `tui.py` | 1717 lines / 63 methods | Highest-value split candidate. Too many UI responsibilities in one class. |
| `host_manager.py` | 1311 lines / 129 methods | Worth slimming, but public facade stability matters. |
| `tests/test_tui.py` | 1471 lines | Large repeated setup. Good fixture extraction candidate. |
| `tests/test_connection_auth_audit.py` | 1019 lines | Large repeated connection config setup. Good fixture extraction candidate. |
| `config_validation.py` | 609 lines | Large but cohesive enough; do not split first. |
| `connection_planner.py` | 542 lines | Large but cohesive by domain; avoid splitting until transfer/SSH builders need separate ownership. |
| `docs/specs/*.md` | about 3.4k lines | Manageable, but stale superseded language must be clearly marked. |

Total repository size across Python, Expect, Markdown, and shell is about 20.8k
lines. This is not alarming for the feature set, but the concentration in a few
files is now a maintenance risk.

## Split Decision Matrix

Scores use 1 low / 5 high.

| Candidate | User Value | Engineering Benefit | Risk | Recommendation |
| --- | ---: | ---: | ---: | --- |
| Extract shared test fixtures | 3 | 5 | 1 | Do first. It reduces future schema-change cost immediately. |
| Extract `tui_recent.py` | 3 | 4 | 2 | Do second. Recent has clear inputs/outputs and isolated behavior. |
| Extract `tui_render.py` | 4 | 4 | 3 | Do third. Useful, but curses state makes careful boundaries important. |
| Extract `tui_flows.py` | 4 | 4 | 3 | Do after render/recent, once helper boundaries are stable. |
| Extract `host_crud.py` | 3 | 4 | 3 | Worth doing, but keep `HostManager` public methods unchanged. |
| Split `connection_planner.py` | 2 | 2 | 3 | Defer. Current cohesion is acceptable. |
| Split `config_validation.py` | 2 | 2 | 2 | Defer. It is long but mostly pure and centralized. |
| Split Expect scripts | 2 | 2 | 4 | Defer. Runtime behavior risk is high relative to maintainability gain. |
| Delete old accepted specs | 1 | 2 | 3 | Do not broadly delete. Mark superseded parts instead. |

## Staged Plan

### Stage 1: Test Fixture Consolidation

Create `tests/fixtures.py` with small stdlib-only helpers:

- `host(name, host, port=None, **overrides)`
- `jump_with_target(...)`
- `write_hosts_config(temp_dir, config=None, hosts=None)`
- `manager_for_config(temp_dir, hosts, config=None)`

Update large tests gradually, starting with `test_command_plan.py`,
`test_connection_auth_audit.py`, `test_audit.py`, and `test_tui.py`.

Initial implementation:

- Added `tests/fixtures.py`.
- Migrated common jump/target setup in `test_command_plan.py`,
  `test_connection_auth_audit.py`, and `test_audit.py`.

Expected benefit:

- Future schema changes touch fixture helpers instead of dozens of JSON snippets.
- Test intent becomes easier to read.
- Lowest refactor risk because product/runtime code is not touched.

Exit criteria:

- No behavior changes.
- Full test suite passes.
- At least the common jump/target config is created through fixtures in two large
  test modules.

### Stage 2: Extract Recent Logic

Move Recent group construction from `tui.py` into `tui_recent.py`.

Proposed boundary:

- Input: `host_manager`.
- Output: Recent group node or `None`.
- Keep TUI rendering, navigation, and `_recent_group` caching in `Tui`.

Initial implementation:

- Added `tui_recent.py`.
- Moved audit-history resolution, current-node lookup, de-duplication, and
  history-only fallback construction out of `tui.py`.
- Added focused `tests/test_tui_recent.py` coverage.

Expected benefit:

- Recent behavior can be tested without curses object setup.
- `tui.py` loses one stateful subsection with limited UI coupling.

Exit criteria:

- Existing Recent tests pass.
- New focused tests cover node-id resolution, endpoint fallback, and history-only
  fallback.
- `Tui` still owns `_recent_group` caching, unless moving the cache reduces
  complexity without adding hidden state.

### Stage 3: Extract Render Helpers

Move low-level drawing methods from `Tui` into `tui_render.py` while keeping
screen ownership in `Tui`.

Candidate functions:

- safe addstr / width-aware truncation wrappers
- top/bottom bar drawing
- detail pane formatting
- tree row rendering helpers

Initial implementation:

- Added `tui_render.py`.
- Moved safe screen writes, shell/header/footer rendering, main split layout,
  and detail pane drawing out of `tui.py`.
- Kept `Tui` as the owner of screen lifecycle, keyboard handling, form flow, and
  detail data lookup.
- Added focused `tests/test_tui_render.py` coverage.

Expected benefit:

- Visual changes become localized.
- Existing `tui_text.py` and `tui_forms.py` stay pure helpers.

Risk control:

- Do not change keyboard handling or form flow in this stage.
- Do not introduce a large renderer class unless plain functions become
  awkward.

Exit criteria:

- TUI tests pass.
- Manual smoke remains `./sshgo.sh`, press `q`.
- No curses setup is required for pure formatting tests.

### Stage 4: Extract TUI Flows

Move add/edit/delete flow orchestration into `tui_flows.py` after render and
Recent boundaries are stable.

Initial implementation:

- Added `tui_flows.py`.
- Moved add/edit/delete orchestration and flow-specific messages out of
  `tui.py`.
- Kept `Tui.run()` and keyboard dispatch in `Tui`.
- Kept `Tui` wrapper methods for compatibility with existing tests and call
  sites.
- Added focused `tests/test_tui_flows.py` coverage.

Expected benefit:

- CRUD behavior becomes easier to reason about independently from draw code.
- Future form validation changes are less likely to touch navigation/rendering.

Risk control:

- Keep `Tui.run()` and keyboard dispatch in `Tui`.
- Flow helpers may receive the `Tui` instance initially; only introduce a smaller
  protocol after call sites are clear.

Exit criteria:

- No CLI/TUI behavior changes.
- Add/edit/delete tests continue to assert persistence and validation behavior.

### Stage 5: Slim `HostManager` With CRUD Extraction

Extract internal CRUD implementation to `host_crud.py`, but keep public
`HostManager` methods and compatibility exports stable.

Candidate responsibilities:

- applying update data
- add/update/delete/move tree mutation
- candidate validation host-copy assembly

Expected benefit:

- `HostManager` remains the public facade, but stops being the implementation
  sink for every config mutation.
- Save-conflict and validation flows become easier to test around smaller
  helpers.

Risk control:

- Do not move encryption in this stage.
- Do not remove compatibility exports named in `internal-refactors-and-tests.md`.
- Do not alter `HostManager` method names used by CLI/TUI/tests.

Exit criteria:

- All existing HostManager persistence and validation tests pass.
- No public import path changes.

### Stage 6: Documentation Pruning

After code boundaries stabilize, prune docs in a narrow pass:

- Keep current behavior docs and accepted specs.
- Mark superseded sections clearly instead of deleting useful historical
  decisions.
- Remove duplicated validation command blocks where `AGENTS.md` is the source of
  truth.
- Keep `README.md`, `README.zh.md`, and `AGENTS.md` as current facts only.

Expected benefit:

- Agents and maintainers stop reading conflicting behavior.
- Historical context remains available without becoming current guidance.

Exit criteria:

- `rg` for old schema examples only finds explicit "not accepted" or "display
  only" references.
- `docs/README.md` accurately lists active specs.

## Non-Goals

- Do not split every large file just because it is large.
- Do not create class hierarchies or framework-like abstractions.
- Do not change command-line behavior, Expect runtime handoff, or audit record
  schema as part of decomposition.
- Do not rewrite TUI in another library.
- Do not delete accepted specs unless their decisions are captured elsewhere.

## Recommended Delivery Order

1. Test fixtures.
2. `tui_recent.py`.
3. `tui_render.py`.
4. `tui_flows.py`.
5. `host_crud.py`.
6. Documentation pruning.

This order front-loads low-risk, high-leverage work and delays risky facade/UI
splits until fixture coverage and simpler boundaries are in place.

## Acceptance Criteria

1. No runtime code imports or calls removed helpers.
2. Current documentation no longer describes combined `host:port` config values
   as accepted current behavior.
3. Historical specs that are partly superseded clearly point to the active
   replacement spec.
4. Unit tests, py_compile, and whitespace checks pass.

## Review Status

- status: approved
- verdict: PASS
- notes: Scope is intentionally narrow to reduce size and stale guidance without
  destabilizing TUI or connection handoff behavior.
