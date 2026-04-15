# Candle Terminal Agent Design

## Goal

Build a terminal-only, multi-turn, agentic CLI assistant whose long-term core model runtime is based on `candle` and its native ecosystem, without turning the project into a clone of an existing provider-first CLI harness.

The first implementation target is a usable terminal assistant with:

- interactive REPL,
- one-shot prompt mode,
- multi-turn conversation,
- persistent sessions,
- context management,
- a minimal local tool system,
- a single-agent task loop.

This design explicitly does **not** assume that current `candle` already provides a production-ready LLM serving stack.

## Design Inputs

This design is based on analysis of three repositories:

1. `candle`
2. `mindnlp`
3. `claw-code`

### Candle: What it is today

`candle` is currently a pure-Python deep learning framework with PyTorch-compatible APIs and multiple backends. Its current roadmap places local model loading, quantization, serving, model routing, and self-hosted tool-use runtime in future phases rather than in the current stable scope.

Implications:

- `candle` is aligned with the project's long-term direction.
- `candle` is not yet a complete, off-the-shelf local chat runtime.
- a terminal assistant built around `candle` should treat `candle` as the target execution substrate, not assume the full serving stack already exists.

### MindNLP: What it provides

`mindnlp` already offers a mature HuggingFace-compatible stack including `pipeline("text-generation")`, `AutoTokenizer`, `from_pretrained`, generation APIs, and an internal inference engine with scheduler and model runner abstractions.

Implications:

- `mindnlp` is useful as a reference for generation runtime design.
- `mindnlp` is not the right long-term core because it is built around MindSpore / mindtorch rather than `candle`.
- its main value here is architectural reference, not direct adoption as the base runtime.

### Claw-code: What is worth learning

`claw-code` is valuable primarily at the product and terminal runtime layer:

- clear separation of CLI, commands, runtime, sessions, and tools,
- structured session persistence,
- slash-command control plane,
- tool execution abstraction,
- permissions and diagnostics,
- resume and conversation lifecycle handling.

Implications:

- terminal UX and runtime boundaries should borrow from this style,
- provider routing and remote-model assumptions should not become this project's core,
- the project should not copy the upstream product surface wholesale.

## Core Decision

The implementation should be organized around two different truths:

1. **Product truth**: terminal assistants need stable CLI/runtime/session/tool architecture immediately.
2. **Model truth**: `candle` is the desired long-term core, but its local LLM runtime path is still incomplete.

Therefore the system should be designed with a strict model-runtime abstraction.

The CLI assistant should be real and usable in MVP, while the `candle` runtime evolves behind a dedicated interface instead of being mixed directly into REPL code.

## Non-Goals

The initial design intentionally excludes:

- multi-agent orchestration,
- plugin marketplaces,
- MCP integration,
- multi-model routing,
- autonomous git / PR / issue workflows,
- RAG or vector memory,
- a complete candle-native serving engine in the first milestone.

These can be added later only after the terminal runtime and the first candle-oriented model runtime boundary are stable.

## Feasibility Assessment

### What Candle can own now

`candle` can credibly own:

- tensor and execution substrate,
- backend abstraction,
- future local inference kernels,
- future local-first reasoning runtime,
- long-term model execution core for the assistant.

### What Candle should not be forced to own in MVP

`candle` should not be forced in the first implementation to provide all of the following before any terminal assistant exists:

- tokenizer + chat-template stack,
- full `from_pretrained` loading path,
- stable generation loop,
- kv-cache scheduling,
- tool-calling model protocol,
- serving / router policy.

Doing so would combine two projects into one:

1. a terminal agent assistant,
2. a full local `candle` LLM runtime.

That is not an MVP-friendly path.

### What MindNLP can contribute

`mindnlp` contributes design signals for:

- prompt-to-token flow,
- tokenizer ownership,
- scheduler / prefill / decode separation,
- kv-cache and block scheduling concepts,
- runtime decomposition into engine, scheduler, and runner.

These should be treated as reference patterns only.

### What claw-code contributes

`claw-code` contributes design patterns for:

- session structure,
- CLI command organization,
- control-plane slash commands,
- runtime abstraction boundaries,
- diagnostics and permissions,
- rendering and persisted session lifecycle.

## Reuse Strategy

### Reuse directly

The following ideas can be reused directly at the design level:

- REPL + one-shot dual entry surface,
- slash-command control plane,
- session persistence shape with user / assistant / tool messages,
- explicit permission modes,
- doctor / preflight diagnostics,
- separation of CLI from conversation runtime.

### Reference but rewrite

The following areas should be rewritten for this project:

- the conversation loop internals,
- the model runtime internals,
- tool-call protocol,
- context compaction policy,
- local runtime / generation interface.

### Do not adopt as core

The following should not become the foundation of the project:

- claw-code's provider-centric runtime and remote-first assumptions,
- mindnlp as the long-term model backend,
- a broad automation surface in the first milestone.

## Architecture

The assistant should use a layered architecture.

```text
CLI / REPL
  -> Command Router
  -> Conversation Runtime
  -> Agent Loop
  -> Tool Registry + Context Manager + Session Store
  -> Model Runtime Interface
      -> Candle Runtime (target)
      -> Mock Runtime (tests)
      -> Transitional Adapter Runtime (optional, temporary)
```

### Layer responsibilities

#### 1. CLI Layer

Responsibilities:

- terminal input loop,
- prompt submission,
- slash command dispatch,
- output rendering,
- interactive help,
- doctor / status display.

This layer must not own the model loop.

#### 2. Runtime Layer

Responsibilities:

- session persistence,
- message schema,
- prompt history,
- context truncation,
- simple compaction,
- permissions,
- runtime status reporting.

This layer must not know how the underlying model works.

#### 3. Agent Layer

Responsibilities:

- single-agent turn loop,
- decide whether to answer directly or call a tool,
- consume tool results,
- maintain turn state,
- bound the number of internal iterations.

This layer depends on the model interface and the tool registry.

#### 4. Tool Layer

Responsibilities:

- tool definitions,
- tool registry,
- argument validation,
- execution,
- permission checks,
- normalized tool result objects.

The first version should keep the tool set intentionally small.

#### 5. Model Layer

Responsibilities:

- define the generation interface,
- normalize model input/output,
- expose runtime diagnostics,
- own tokenizer and sampling policy once candle-native support exists,
- host the eventual `CandleRuntime`.

This is where `candle` should become the long-term core.

## Data Model

The session model should be explicit and tool-aware.

### Message roles

- `system`
- `user`
- `assistant`
- `tool`

### Content block types

- `text`
- `tool_use`
- `tool_result`

### Session metadata

- session id,
- timestamps,
- workspace root,
- active model id,
- prompt history,
- optional compaction summary,
- optional runtime diagnostics snapshot.

This mirrors the shape needed for a true agent loop and is consistent with what works well in terminal agent harnesses.

## CLI Surface

The initial CLI should stay small.

### Entry points

- `candle-agent`
- `candle-agent prompt "..."`
- `candle-agent doctor`

### Initial slash commands

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

### Permission modes

- `read-only`
- `workspace-write`
- `danger-full-access`

The initial assistant should also support a minimal allowed-tools restriction.

## Agent Loop

The first agent loop should be intentionally conservative.

One turn should follow this pattern:

1. receive user message,
2. persist it to session,
3. build context window,
4. call model runtime,
5. inspect output,
6. if model requests a tool, execute the tool,
7. append tool result to session,
8. continue loop until a final assistant answer is produced or iteration limit is reached,
9. render final answer and persist turn artifacts.

This should be a **single-agent**, bounded-iteration loop in MVP.

## Model Runtime Interface

The most important architectural protection is the model runtime abstraction.

Suggested responsibilities for the base interface:

- health check,
- capability report,
- generate turn,
- optional streaming interface,
- tokenizer ownership,
- model identity,
- structured response format.

### Planned runtime implementations

#### MockRuntime

Used for tests and CLI/runtime development before the real model backend is ready.

#### CandleRuntime

The long-term target.

Planned evolution:

1. stub + capability report,
2. tokenizer and prompt normalization ownership,
3. model loading,
4. generation loop,
5. kv-cache and scheduling,
6. tool-call aware structured output.

#### Transitional Adapter Runtime

Optional and temporary only.

This may exist solely to verify the terminal architecture while candle-native generation is immature. It must be isolated behind the same interface and must not become the project's permanent center of gravity.

## MVP Definition

MVP is complete when the repository contains a working terminal assistant with:

- REPL mode,
- one-shot prompt mode,
- persisted sessions,
- resumed sessions,
- context assembly,
- bounded single-agent loop,
- at least three useful tools,
- permission checks,
- doctor command,
- model runtime abstraction with a real `CandleRuntime` placeholder.

MVP does **not** require a complete candle-native local generation engine.

## Risks

### Risk 1: Candle-native generation path is incomplete

This is the main technical risk. It should be isolated behind the model runtime boundary so that terminal product work can proceed without corrupting the architecture.

### Risk 2: Project scope expands into a clone of a full coding-agent product

The first version must stay focused on terminal chat, local tool use, and session/runtime foundations.

### Risk 3: Transitional adapters become permanent

Any temporary runtime used before `CandleRuntime` matures must remain a replaceable implementation, never the conceptual core.

### Risk 4: Context and tool loop complexity overwhelms early implementation

The first loop should use a hard iteration limit, a tiny tool set, and simple compaction rules.

## Recommendation

Proceed in two major phases:

1. build the terminal assistant architecture and MVP runtime surface,
2. incrementally grow the candle-native model runtime behind a stable interface.

This satisfies the requirement that the project is fundamentally oriented around `candle`, while avoiding the unrealistic assumption that current `candle` already ships a full local agent runtime.
