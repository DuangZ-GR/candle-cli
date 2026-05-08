# Repository Hygiene Completion Design

**Date:** 2026-05-07

## Goal

Bring `candle-cli` into a shareable milestone state without changing runtime behavior. The repository should clearly explain how to install dependencies, run examples, validate changes, and understand the current `v0.2.0` capability set.

## Scope

This pass covers documentation, dependency declaration, changelog, GitHub metadata, and a version tag. It does not implement streaming, tool-aware generation, line editing, or candle-native inference. A GitHub Actions workflow is intentionally deferred until a token with the `workflow` scope is available.

## Repository Updates

- Add Python requirements for bridge/runtime development.
- Update README with badges, Python dependency setup, and examples references.
- Add a changelog entry for `v0.2.0`.
- Add historical specs documenting the recently completed inference/API/session work.
- Update the GitHub repository description.
- Create tag `v0.2.0` after validation.

## Validation

Before publishing, run:

- `cargo fmt --check`
- `cargo clippy --all-targets --all-features -- -D warnings`
- `cargo test`
- `python3 -m pytest python/test_bridge_runtime.py -q`

## Non-goals

- No runtime behavior changes.
- No streaming protocol changes.
- No tool execution loop changes.
- No new Rust dependencies.
- No GitHub release body unless requested separately.
