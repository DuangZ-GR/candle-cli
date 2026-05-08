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
