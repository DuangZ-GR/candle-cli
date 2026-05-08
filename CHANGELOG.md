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
