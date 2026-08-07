# Changelog

## Unreleased

### Added

- Frozen M18 security heldout suite with explicit applicable/not-applicable accounting.
- Structured `doctor --json` checks for Rust, Python, PyTorch, MindSpore, Docker, Bridge, Provider, and dual-runtime environments.
- Linux/Windows install and offline demo scripts.
- Linux/Windows GitHub Actions CI plus a manual artifact-only release dry run.
- Traceable final benchmark JSON/Markdown aggregation with source SHA-256 digests.

### Security

- Prevent recursive grep/glob from following workspace symlinks to external paths.
- Pass web-search queries as opaque Python arguments instead of interpolating them into executable source.
- Require confirmation for network search in prompt and workspace-write modes.
- Bound read-tool file size and retained shell stdout/stderr bytes.

### Changed

- Native Shell uses `cmd.exe` on Windows and `sh` on Unix.
- Strict Clippy checks are clean on the M18 candidate.

## v0.4.0 - 2026-06-06

### Added

- rustyline-based REPL with line editing, history, and readline shortcuts.
- grep-RAG pre-search: automatically injects relevant code snippets into context.
- session naming: `/name <label>` for human-readable session labels.
- thinking spinner with elapsed time display during model calls.
- web_search tool via DuckDuckGo Lite.

### Changed

- Permission prompt (`prompt` mode) now requests interactive confirmation for dangerous tools.
- Tool call parser supports fallback function-style calls: `read({...})`.
- Shell tool reports exit code in structured output format.

## v0.3.0 - 2026-05-09

### Added

- Agentic tool loop: model can request tools via `<tool_call>` text JSON protocol.
- Real read, glob, and grep tool implementations (were stubs returning empty strings).
- Edit tool with exact-once match semantics (fails on 0 or multiple matches).
- Permission system integrated into agent loop with workspace path boundary enforcement.
- Execution trace (`/trace`) showing step-by-step agent execution chain.
- Runtime status display (`/status`) with session, model, and permission info.
- Tool listing (`/tools`) for system capability inspection.
- Shell timeout via `CANDLE_CLI_SHELL_TIMEOUT_SECS`.
- Tool call / tool result blocks persisted in session messages.
- `CandleRuntime` placeholder for future local inference backend.

## v0.2.0 - 2026-05-07

### Added

- Real Python bridge generation path using transformers.
- OpenAI-compatible API mode for Ollama, vLLM, and OpenAI-style endpoints.
- Multi-turn REPL with slash commands.
- Persistent session save/list/resume/clear support.
- Configurable system prompt and context turn limit via environment variables.
- Verbose bridge diagnostics for API calls, token usage, latency, and GPU memory.
- Example scripts for API inference and local transformers inference.
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
