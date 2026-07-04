# Host tree extraction

## Metadata

- slug: host-tree-extraction
- status: approved
- owner: Architect/Engineer
- related_roadmap: docs/roadmap.md#2026-07
- related_docs:
  - docs/gap-analysis.md
- related_specs:
  - docs/specs/node-identity-recent-hardening.md
  - docs/specs/common-workflow-polish.md

## Background

`HostManager` still owns a mix of config semantics, credential handling, command planning, audit handoff, and pure host-tree operations. Command planning and config storage have already been isolated. The next low-risk reduction is extracting reusable tree traversal and mutation helpers without changing user-visible behavior.

## Scope

- Add a stdlib-only `host_tree.py` module for pure tree helpers.
- Move traversal, node lookup, parent/index lookup, replacement, descendant host detection, runtime parent-link rebuilding, and node-id assignment helpers out of `HostManager`.
- Keep `HostManager` as the owner of config semantics, validation, saving, encryption, audit, and command planning.
- Preserve existing public `HostManager` methods as compatibility wrappers where they already exist.
- Follow the explicit node ID migration persistence policy documented in `node-identity-recent-hardening`; this extraction does not introduce additional persistence changes.
- Add focused unit tests for the extracted helpers plus existing HostManager/TUI regression coverage.

## Non-goals

- Do not change `hosts.json` format.
- Do not change validation rules, node ID format, or Recent behavior.
- Do not change TUI workflow or display; stable-id helper calls may be used internally to preserve the selected-node semantics.
- Do not change SSH/SFTP/relay command planning or Expect handoff.
- Do not add dependencies.

## Acceptance Criteria

1. `host_tree.py` provides pure helpers for traversal, lookup, replacement, parent/index lookup, descendant host detection, runtime parent-link rebuilding, and node-id assignment.
2. `HostManager` delegates equivalent tree operations to `host_tree.py`.
3. Existing HostManager CRUD, Recent, validation, and TUI tests continue to pass.
4. Focused tests cover host tree helper behavior, including nested parent links and duplicate/blank node ID assignment.
5. No user-visible command output or config format changes.

## Technical Design

Use small functions operating on dict/list nodes:

- `traverse_all(nodes)`
- `find_node(nodes, name=None, node_id=None)`
- `replace_node(nodes, replacement, name=None, node_id=None)`
- `find_node_and_parent(nodes, name=None, node_id=None)`
- `contains_hosts(node)`
- `potential_parents(nodes)`
- `ensure_node_ids(nodes, new_id, seen_ids=None)`
- `rebuild_nest_parents(nodes, host_ancestors=None, direct_parent=None)`

`ensure_node_ids` receives an ID generator callback so `HostManager` continues to own the UUID strategy.

## Review Status

- status: reviewed
- verdict: PASS
- notes: Behavior-preserving extraction is compatible with current design constraints because it reduces HostManager scope without changing validation, config format, or runtime SSH/SFTP behavior. Node ID migration persistence follows the explicit policy in `node-identity-recent-hardening`.
