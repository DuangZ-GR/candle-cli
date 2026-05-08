# Repository Sync and Hygiene Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the local checkout up to GitHub `main`, fill repository hygiene gaps, verify the project, and publish a `v0.2.0` milestone.

**Architecture:** This plan changes repository metadata and documentation only, plus CI/dependency declaration files. It does not change runtime behavior, agent behavior, or model bridge code. The existing Rust/Python test suites remain the authority for validation.

**Tech Stack:** Git/GitHub CLI, Rust Cargo, GitHub Actions, Python pytest, pip requirements.

---

## File Structure Map

- `.github/workflows/ci.yml` — GitHub Actions workflow for Rust fmt/clippy/tests and Python bridge tests.
- `requirements.txt` — Python runtime/test dependencies for the bridge worker and examples.
- `README.md` — badges, Python dependency setup, and examples references.
- `CHANGELOG.md` — milestone history and `v0.2.0` release notes.
- `docs/superpowers/specs/2026-05-07-repository-hygiene-design.md` — design rationale for this repository hygiene pass.
- `docs/superpowers/plans/2026-05-07-repository-sync-and-hygiene.md` — this implementation plan.
- `docs/superpowers/specs/2026-04-29-real-inference-design.md` — historical design note for real inference/API bridge work.
- `docs/superpowers/specs/2026-04-30-repl-session-design.md` — historical design note for REPL multi-turn/session work.
- GitHub repository metadata — description field.
- Git tag `v0.2.0` — release milestone marker.

---

### Task 1: Synchronize Local Main

**Files:**
- Modify local git refs only.

- [ ] **Step 1: Inspect local status**

Run:

```bash
git -C /home/mseco/candle-cli status --short --branch
git -C /home/mseco/candle-cli log --oneline -5
```

Expected: local `main` is behind GitHub, and `.superpowers/` is untracked.

- [ ] **Step 2: Fetch remote main**

Run:

```bash
git -C /home/mseco/candle-cli fetch origin main
```

Expected: `origin/main` updates to the latest GitHub commit. If HTTPS fetch fails with a transient TLS termination error, retry once after confirming `git ls-remote origin main` succeeds.

- [ ] **Step 3: Fast-forward local main**

Run:

```bash
git -C /home/mseco/candle-cli merge --ff-only origin/main
```

Expected: local `main` advances without merge conflicts.

- [ ] **Step 4: Verify sync**

Run:

```bash
git -C /home/mseco/candle-cli status --short --branch
git -C /home/mseco/candle-cli log -1 --oneline
```

Expected: local latest commit matches remote `main`; `.superpowers/` may remain untracked.

---

### Task 2: Add Repository Hygiene Design and Plan Docs

**Files:**
- Create: `docs/superpowers/specs/2026-05-07-repository-hygiene-design.md`
- Create: `docs/superpowers/plans/2026-05-07-repository-sync-and-hygiene.md`

- [ ] **Step 1: Write the design spec**

Create `docs/superpowers/specs/2026-05-07-repository-hygiene-design.md` with:

```markdown
# Repository Hygiene Completion Design

**Date:** 2026-05-07

## Goal

Bring `candle-cli` into a shareable milestone state without changing runtime behavior. The repository should clearly explain how to install dependencies, run examples, validate changes, and understand the current `v0.2.0` capability set.

## Scope

This pass covers documentation, CI, dependency declaration, changelog, GitHub metadata, and a version tag. It does not implement streaming, tool-aware generation, line editing, or candle-native inference.

## Repository Updates

- Add CI for Rust formatting, Rust linting, Rust tests, and Python bridge tests.
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
```

- [ ] **Step 2: Save this implementation plan**

Ensure this file exists at `docs/superpowers/plans/2026-05-07-repository-sync-and-hygiene.md`.

---

### Task 3: Add CI and Python Dependencies

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `requirements.txt`

- [ ] **Step 1: Create GitHub Actions workflow**

Create `.github/workflows/ci.yml` with:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  rust:
    name: Rust
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Install Rust toolchain
        uses: dtolnay/rust-toolchain@stable
        with:
          components: rustfmt, clippy

      - name: Check formatting
        run: cargo fmt --check

      - name: Run clippy
        run: cargo clippy --all-targets --all-features -- -D warnings

      - name: Run Rust tests
        run: cargo test

  python:
    name: Python bridge
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install test dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -r requirements.txt

      - name: Run Python bridge tests
        run: python -m pytest python/test_bridge_runtime.py -q
```

- [ ] **Step 2: Create requirements file**

Create `requirements.txt` with:

```text
pytest>=8,<9
transformers>=4.40,<5
torch>=2.2
```

---

### Task 4: Update README and CHANGELOG

**Files:**
- Modify: `README.md`
- Create: `CHANGELOG.md`

- [ ] **Step 1: Update README**

Modify `README.md` to include:

```markdown
[![CI](https://github.com/DuangZ-GR/candle-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/DuangZ-GR/candle-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)
```

Also add a Python dependency setup section:

```markdown
## Python 依赖

Bridge runtime 和示例脚本需要 Python 依赖：

```bash
python3 -m pip install -r requirements.txt
```

如果只使用 API 模式，通常不需要本地 GPU；如果使用本地 transformers 推理，请根据你的 CUDA/CPU 环境安装合适的 PyTorch wheel。
```

Also add an examples section:

```markdown
## 示例脚本

仓库包含两个独立示例，方便在不启动 Rust CLI 的情况下验证模型路径：

```bash
python3 examples/api_inference.py
python3 examples/qwen3_local_inference.py
```

- `examples/api_inference.py`：调用 OpenAI-compatible API，例如 Ollama 或 vLLM。
- `examples/qwen3_local_inference.py`：直接通过 transformers 加载本地模型。
```

- [ ] **Step 2: Create changelog**

Create `CHANGELOG.md` with:

```markdown
# Changelog

## v0.2.0 - 2026-05-07

### Added

- Real Python bridge generation path using transformers.
- OpenAI-compatible API mode for Ollama, vLLM, and OpenAI-style endpoints.
- Multi-turn REPL with slash commands.
- Persistent session save/list/resume/clear support.
- Configurable system prompt and context turn limit via environment variables.
- Verbose bridge diagnostics for API calls, token usage, latency, and GPU memory.
- Example scripts for API inference and local transformers inference.
- CI workflow for Rust and Python validation.
- Python dependency declaration in `requirements.txt`.

### Verified

- Rust formatting, clippy, and test suite.
- Python bridge runtime tests.

## v0.1.0 - 2026-04-16

### Added

- Initial Rust crate structure.
- CLI command parsing, prompt mode, doctor mode, and REPL foundation.
- Session model and persistence.
- Tool registry and built-in read/write/shell tool skeletons.
- Permission policy model.
- Candle-target runtime trait with mock and bridge implementations.
```

---

### Task 5: Add Historical Specs for Completed Work

**Files:**
- Create: `docs/superpowers/specs/2026-04-29-real-inference-design.md`
- Create: `docs/superpowers/specs/2026-04-30-repl-session-design.md`

- [ ] **Step 1: Add real inference design note**

Create `docs/superpowers/specs/2026-04-29-real-inference-design.md` with:

```markdown
# Real Inference and API Mode Design

**Date:** 2026-04-29

## Goal

Move `LocalBridgeRuntime` beyond stub responses by letting the Python bridge perform real generation through either local transformers models or an OpenAI-compatible API.

## Runtime Boundary

Rust continues to own CLI, session, tools, permissions, context building, and agent orchestration. Python owns transitional model execution behind the existing stdio JSON bridge. The upper Rust layers continue to depend only on `CandleTargetRuntime`.

## Python Bridge Modes

### Local transformers mode

The bridge loads `AutoTokenizer` and `AutoModelForCausalLM`, formats chat messages with the tokenizer chat template, and calls `model.generate`. Model ID, device, local-files-only behavior, max tokens, temperature, top-p, and verbosity are controlled by environment variables.

### API mode

When `CANDLE_CLI_API_BASE_URL` is set, the bridge skips local model loading and sends OpenAI-compatible `/chat/completions` requests. This supports Ollama, vLLM, and OpenAI-style endpoints.

## Fallback Behavior

If local model loading or generation fails, the bridge returns a deterministic stub-style response so CLI and Rust integration tests remain runnable in lightweight environments.

## Diagnostics

When `CANDLE_CLI_VERBOSE=1`, diagnostics go to stderr so stdout remains reserved for JSON protocol responses. Diagnostics include model loading, API calls, token usage, latency, and GPU memory where available.

## Deferred Work

- Streaming output.
- Structured tool calling.
- Direct candle-native inference.
```

- [ ] **Step 2: Add REPL/session design note**

Create `docs/superpowers/specs/2026-04-30-repl-session-design.md` with:

```markdown
# REPL Multi-turn and Session Management Design

**Date:** 2026-04-30

## Goal

Make `candle-cli` usable as a multi-turn terminal assistant with persistent sessions and practical slash commands.

## REPL Flow

The REPL creates a session, reads user input line-by-line, appends user messages, runs one model turn through the agent loop, saves the session, and prints the latest assistant message.

## Slash Commands

The REPL supports commands for exiting, help, showing session info, showing the system prompt, clearing the current session, listing saved sessions, resuming a session, and explicitly saving.

## Session Persistence

Sessions are serialized as JSON files under the configured session directory. `CANDLE_CLI_SESSION_DIR` can override the default temp-based location.

## Context Management

Before each turn, the context builder compacts old messages according to `CANDLE_CLI_MAX_TURNS` and serializes messages into the runtime request. The system prompt is resolved from `CANDLE_CLI_SYSTEM_PROMPT` or the built-in default.

## Deferred Work

- Line editing and command history through rustyline or reedline.
- Streaming display.
- Tool-aware recursive agent loop.
- Richer session metadata.
```

---

### Task 6: Verify Locally

**Files:**
- Test only.

- [ ] **Step 1: Format check**

Run:

```bash
cargo fmt --check
```

Expected: exits successfully.

- [ ] **Step 2: Clippy**

Run:

```bash
cargo clippy --all-targets --all-features -- -D warnings
```

Expected: exits successfully with zero warnings.

- [ ] **Step 3: Rust tests**

Run:

```bash
cargo test
```

Expected: all Rust tests pass.

- [ ] **Step 4: Python tests**

Run:

```bash
python3 -m pytest python/test_bridge_runtime.py -q
```

Expected: all Python tests pass.

---

### Task 7: Commit, Push, and Publish Metadata

**Files:**
- Commit changed files only; do not commit `.superpowers/`.

- [ ] **Step 1: Inspect diff**

Run:

```bash
git status --short
git diff -- README.md CHANGELOG.md requirements.txt .github/workflows/ci.yml docs/superpowers/specs docs/superpowers/plans
```

Expected: only intended files are changed or created.

- [ ] **Step 2: Stage intended files**

Run:

```bash
git add README.md CHANGELOG.md requirements.txt .github/workflows/ci.yml docs/superpowers/specs docs/superpowers/plans
```

Expected: intended files are staged; `.superpowers/` remains untracked.

- [ ] **Step 3: Commit**

Run:

```bash
git commit -m "chore: add CI and release documentation"
```

Expected: new commit is created.

- [ ] **Step 4: Push main**

Run:

```bash
git push origin main
```

Expected: GitHub `main` receives the new commit.

- [ ] **Step 5: Update GitHub repository description**

Run:

```bash
gh repo edit DuangZ-GR/candle-cli --description "Rust-first terminal AI assistant with multi-turn conversation, session persistence, and OpenAI-compatible / local backends."
```

Expected: GitHub description is no longer empty.

- [ ] **Step 6: Create and push version tag**

Run:

```bash
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
```

Expected: GitHub has tag `v0.2.0` pointing to the hygiene/release documentation commit.
```
