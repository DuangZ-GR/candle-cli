# Candle Terminal Agent MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first usable terminal-only CLI assistant skeleton for `candle-cli`, including REPL and one-shot entrypoints, persistent sessions, a bounded single-agent loop, a minimal tool system, and a model runtime abstraction oriented toward a future `CandleRuntime`.

**Architecture:** The implementation is split into five layers: `cli`, `runtime`, `agent`, `tools`, and `model`. The CLI is responsible only for user interaction and command routing. Session persistence, context assembly, permissions, and turn orchestration live in dedicated runtime modules. The agent loop depends on a model runtime interface and a tool registry. `CandleRuntime` exists as a first-class target implementation boundary, while a `MockRuntime` enables early end-to-end progress without pretending candle already ships a complete local LLM serving engine.

**Tech Stack:** Python 3.11+, standard library, `pytest`, `rich` for terminal rendering, `pydantic` for structured configuration and message schemas, editable package layout under `src/`

---

### Task 1: Bootstrap the Python package and test harness

**Files:**
- Create: `pyproject.toml`
- Create: `src/candle_cli/__init__.py`
- Create: `tests/conftest.py`
- Modify: `README.md`

**Step 1: Write the failing packaging smoke test**

```python
from importlib import import_module


def test_package_imports():
    module = import_module("candle_cli")
    assert hasattr(module, "__version__")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests -k package_imports -v`
Expected: FAIL because `candle_cli` package does not exist

**Step 3: Write minimal package scaffolding**

Create `pyproject.toml` with an editable setuptools package pointing at `src/` and test dependencies.

Create `src/candle_cli/__init__.py`:

```python
__all__ = ["__version__"]

__version__ = "0.1.0"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests -k package_imports -v`
Expected: PASS

**Step 5: Commit**

```bash
git add pyproject.toml README.md src/candle_cli/__init__.py tests/conftest.py
git commit -m "build: bootstrap candle-cli python package"
```

### Task 2: Define session and message persistence models

**Files:**
- Create: `src/candle_cli/runtime/session.py`
- Create: `tests/test_session.py`

**Step 1: Write the failing session round-trip test**

```python
from candle_cli.runtime.session import SessionStore, UserMessage


def test_session_round_trip(tmp_path):
    store = SessionStore(tmp_path / ".candle-cli" / "sessions")
    session = store.create_session(workspace_root=tmp_path)
    session.append(UserMessage(text="hello"))
    store.save(session)

    loaded = store.load(session.session_id)
    assert loaded.messages[0].role == "user"
    assert loaded.messages[0].text == "hello"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_session.py -v`
Expected: FAIL because runtime session types do not exist

**Step 3: Write minimal session model and store**

Implement:

- `BaseMessage`
- `SystemMessage`
- `UserMessage`
- `AssistantMessage`
- `ToolMessage`
- `Session`
- `SessionStore`

Persist JSON under `.candle-cli/sessions/<session-id>.json`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_session.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/candle_cli/runtime/session.py tests/test_session.py
git commit -m "feat: add persistent session model"
```

### Task 3: Add CLI entrypoints and command routing

**Files:**
- Create: `src/candle_cli/cli/main.py`
- Create: `src/candle_cli/cli/repl.py`
- Create: `src/candle_cli/cli/commands.py`
- Create: `tests/test_cli_commands.py`

**Step 1: Write the failing command routing tests**

```python
from candle_cli.cli.commands import parse_cli_args


def test_parse_prompt_mode():
    parsed = parse_cli_args(["prompt", "hello"])
    assert parsed.mode == "prompt"
    assert parsed.prompt == "hello"


def test_parse_doctor_mode():
    parsed = parse_cli_args(["doctor"])
    assert parsed.mode == "doctor"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_commands.py -v`
Expected: FAIL because CLI modules do not exist

**Step 3: Implement minimal parser and entrypoint**

Support these forms:

- `candle-agent`
- `candle-agent prompt "..."`
- `candle-agent doctor`

Add command metadata for future slash commands:

- `/help`
- `/doctor`
- `/status`
- `/session`
- `/resume`
- `/history`
- `/model`
- `/tools`
- `/clear`
- `/exit`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_commands.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/candle_cli/cli/main.py src/candle_cli/cli/repl.py src/candle_cli/cli/commands.py tests/test_cli_commands.py
git commit -m "feat: add cli entrypoints and command router"
```

### Task 4: Add model runtime interface and mock runtime

**Files:**
- Create: `src/candle_cli/model/base.py`
- Create: `src/candle_cli/model/mock_runtime.py`
- Create: `src/candle_cli/model/candle_runtime.py`
- Create: `tests/test_model_runtime.py`

**Step 1: Write the failing runtime contract test**

```python
from candle_cli.model.mock_runtime import MockRuntime


def test_mock_runtime_returns_text_reply():
    runtime = MockRuntime()
    result = runtime.generate_turn(system_prompt="sys", messages=[{"role": "user", "text": "hello"}])
    assert result.output_kind == "final"
    assert result.text
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_model_runtime.py -v`
Expected: FAIL because model runtime modules do not exist

**Step 3: Implement runtime contract**

Define:

- `ModelTurnResult`
- `ToolCallIntent`
- `BaseModelRuntime`
- `MockRuntime`
- `CandleRuntime`

`CandleRuntime` should initially expose:

- `name()`
- `healthcheck()`
- `capabilities()`
- `generate_turn()` raising `NotImplementedError`

This makes candle the explicit target runtime without faking maturity.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_model_runtime.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/candle_cli/model/base.py src/candle_cli/model/mock_runtime.py src/candle_cli/model/candle_runtime.py tests/test_model_runtime.py
git commit -m "feat: add model runtime abstraction"
```

### Task 5: Build the tool registry and minimal tool set

**Files:**
- Create: `src/candle_cli/tools/registry.py`
- Create: `src/candle_cli/tools/pwd.py`
- Create: `src/candle_cli/tools/read_file.py`
- Create: `src/candle_cli/tools/grep.py`
- Create: `src/candle_cli/tools/shell.py`
- Create: `src/candle_cli/runtime/permissions.py`
- Create: `tests/test_tools.py`

**Step 1: Write the failing tool execution tests**

```python
from candle_cli.tools.registry import build_default_registry


def test_pwd_tool_executes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = build_default_registry(permission_mode="read-only")
    result = registry.execute("pwd", {})
    assert str(tmp_path) in result.output
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools.py -v`
Expected: FAIL because tools do not exist

**Step 3: Implement registry and tools**

Support:

- `pwd`
- `read_file`
- `grep`
- `shell`

Permission policy:

- `pwd`, `read_file`, `grep` allowed in `read-only`
- `shell` blocked in `read-only`
- `shell` allowed in `workspace-write` and `danger-full-access`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/candle_cli/tools src/candle_cli/runtime/permissions.py tests/test_tools.py
git commit -m "feat: add minimal tool registry"
```

### Task 6: Implement conversation runtime and bounded single-agent loop

**Files:**
- Create: `src/candle_cli/runtime/context.py`
- Create: `src/candle_cli/runtime/conversation.py`
- Create: `src/candle_cli/agent/loop.py`
- Create: `src/candle_cli/agent/state.py`
- Create: `tests/test_agent_loop.py`

**Step 1: Write the failing final-answer loop test**

```python
from candle_cli.agent.loop import AgentLoop
from candle_cli.model.mock_runtime import MockRuntime
from candle_cli.tools.registry import build_default_registry


def test_agent_loop_returns_final_answer(tmp_path):
    loop = AgentLoop(
        runtime=MockRuntime(),
        tool_registry=build_default_registry(permission_mode="read-only"),
        max_iterations=3,
    )
    result = loop.run_turn("hello", workspace_root=tmp_path)
    assert result.final_text
    assert result.iterations >= 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_loop.py -v`
Expected: FAIL because agent loop modules do not exist

**Step 3: Implement bounded loop**

Responsibilities:

- build current context from session,
- call runtime,
- execute one or more tool requests,
- append tool results,
- stop after `max_iterations`,
- produce final assistant text.

Use a simple context strategy first:

- keep system prompt,
- keep latest N messages,
- no summarization yet.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_loop.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/candle_cli/runtime/context.py src/candle_cli/runtime/conversation.py src/candle_cli/agent/loop.py src/candle_cli/agent/state.py tests/test_agent_loop.py
git commit -m "feat: add bounded single-agent conversation loop"
```

### Task 7: Add REPL integration, doctor command, and status surfaces

**Files:**
- Create: `src/candle_cli/cli/doctor.py`
- Create: `src/candle_cli/cli/render.py`
- Create: `tests/test_doctor.py`
- Modify: `src/candle_cli/cli/repl.py`
- Modify: `README.md`

**Step 1: Write the failing doctor health-check test**

```python
from candle_cli.cli.doctor import build_doctor_report


def test_doctor_report_mentions_runtime_and_sessions(tmp_path):
    report = build_doctor_report(workspace_root=tmp_path)
    assert "workspace" in report.lower()
    assert "runtime" in report.lower()
    assert "session" in report.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_doctor.py -v`
Expected: FAIL because doctor module does not exist

**Step 3: Implement doctor and REPL command dispatch**

`/doctor` should report:

- current workspace,
- session directory,
- configured permission mode,
- selected runtime,
- `CandleRuntime` healthcheck status,
- available tools.

Also add basic rendering helpers for:

- assistant text,
- tool results,
- status blocks.

**Step 4: Run targeted tests and smoke command**

Run:

```bash
pytest tests/test_doctor.py -v
pytest tests -v
python -m candle_cli.cli.main doctor
```

Expected: PASS and printable doctor output

**Step 5: Commit**

```bash
git add src/candle_cli/cli/doctor.py src/candle_cli/cli/render.py src/candle_cli/cli/repl.py tests/test_doctor.py README.md
git commit -m "feat: add doctor and repl runtime surfaces"
```

### Task 8: Add context truncation and session resume support

**Files:**
- Modify: `src/candle_cli/runtime/session.py`
- Modify: `src/candle_cli/runtime/context.py`
- Modify: `src/candle_cli/cli/commands.py`
- Modify: `src/candle_cli/cli/repl.py`
- Create: `tests/test_resume.py`

**Step 1: Write the failing resume test**

```python
from candle_cli.runtime.session import SessionStore


def test_resume_latest_session(tmp_path):
    store = SessionStore(tmp_path / ".candle-cli" / "sessions")
    created = store.create_session(workspace_root=tmp_path)
    store.save(created)

    latest = store.load_latest()
    assert latest.session_id == created.session_id
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_resume.py -v`
Expected: FAIL because `load_latest()` does not exist

**Step 3: Implement session resume and context truncation**

Add:

- `SessionStore.load_latest()`
- `/resume <session-id|latest>` handling
- simple context truncation by message count or char budget

This keeps context management explicit before adding summarization.

**Step 4: Run full suite**

Run: `pytest tests -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/candle_cli/runtime/session.py src/candle_cli/runtime/context.py src/candle_cli/cli/commands.py src/candle_cli/cli/repl.py tests/test_resume.py
git commit -m "feat: add session resume and context truncation"
```

## Exit Criteria

This plan is complete when:

- the repository contains a working package,
- `candle-agent` REPL and `prompt` mode both run,
- sessions persist and resume,
- a minimal tool-aware loop works with `MockRuntime`,
- the project has a first-class `CandleRuntime` boundary,
- `doctor` exposes runtime readiness and current configuration,
- the test suite passes.
