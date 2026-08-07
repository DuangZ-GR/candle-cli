# candle-cli

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust Edition](https://img.shields.io/badge/Rust-2021-orange.svg)
[![CI](https://github.com/DuangZ-GR/candle-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/DuangZ-GR/candle-cli/actions/workflows/ci.yml)

[English](README.md) | [中文](README_CN.md)

`candle-cli` is a Rust-first diagnostic CLI for PyTorch-to-MindSpore migration. It combines deterministic AST scanning, official mappings, cross-framework runtime evidence, and transactional patches to locate the first semantic divergence and produce verifiable, reversible migration results.

It was built for a concrete migration failure mode: direct API replacement can make a PyTorch example run under MindSpore while silently changing dtype, shape, return structure, default training semantics, random data flow, or optimizer state. `candle-cli` turns that process into an auditable workflow: scan APIs without executing the project, apply evidence-backed rewrites, run both frameworks when configured, compare traces, identify the first observable divergence, and roll back unsafe edits.

## Current evidence status

| Area | Current checked-in evidence | Boundary |
|------|-----------------------------|----------|
| Static scan and mapping | 25/25 real-project files scanned; mapped-call coverage improved from 24.22% to 44.77% on PyTorch Examples/nanoGPT/DETR; 41.98% on the frozen Segment Anything holdout | Static coverage, not runtime migration accuracy |
| Runtime parity | PyTorch 2.6.0+cu124 and MindSpore 2.9.0 runs cover API chains, components, training steps, data pipeline/randomness, graph mode, optimizer state, and checkpoint recovery | Fixed small benchmarks, not unseen-project success rate |
| End-to-end workflow | `migrate run` composes scan, rewrite, validation, trace comparison, and rollback; the MNIST classifier-head slice passes 3/3 frozen dual-runtime scenarios with 2/2 byte-level rollbacks | 25-line executable slice, not full MNIST migration |
| Safety and context | M18 Linux heldout blocks or gates 12/12 applicable attacks with 0/8 benign false blocks; context retention keeps 20/20 frozen facts while reducing estimated tokens by 81.76% | Deterministic suites; provider cache hit rate remains unclaimed |
| CI and release readiness | Rust, Python, schema/evidence, Ubuntu Rust, and Windows Rust checks passed on PR #7 | Pending repository merge/release decision |

Full reproducibility notes and résumé-safe wording are maintained in [`docs/RESUME_PROJECT_SUMMARY_CN.md`](docs/RESUME_PROJECT_SUMMARY_CN.md), [`docs/MILESTONE_EXECUTION_PLAN_CN.md`](docs/MILESTONE_EXECUTION_PLAN_CN.md), and `benchmarks/results/`.

## Highlights

- **Migration scanner** — discovers aliased PyTorch calls, inferred Tensor methods, source spans, and arguments without importing either framework
- **Verified migration rewrites** — previews minimal API/dtype edits, applies them transactionally, runs an explicit validator, and supports checksum-protected rollback
- **End-to-end migration workflow** — one command composes scan, preview, apply, program validation, trace comparison, and failure rollback into a JSON/Markdown report
- **Cross-framework diagnostics** — captures PyTorch/MindSpore forward, gradient, data pipeline, graph-mode, optimizer, and checkpoint traces, then scores equivalence, defect class, and first-divergence Top-1
- **Rust core + Python bridge** — Rust owns CLI, agent loop, tools, permissions, and structured protocols; Python bridges OpenAI-compatible APIs, Ollama native mode, local models, and migration analysis
- **Agentic tool loop** — bounded multi-step execution with read-only sub-agent task delegation and shared budgets
- **Safety controls** — path-boundary enforcement, confirmation gates, bounded read/shell output, optional Docker shell isolation, and frozen security regression/heldout suites
- **Context and observability** — layered memory, deterministic context compaction, `/tools`, `/status`, `/trace`, millisecond timing, JSON export, and provider usage collection hooks
- **Fault tolerance** — API retry with exponential backoff (4xx not retried), persistent Python worker reuse, shell timeout, and process cleanup

## Quickstart

Requirements: Rust stable and Python 3.10 or newer. Install Python bridge
dependencies with `python -m pip install -r requirements.txt` when using the
bridge runtime.

```bash
git clone https://github.com/DuangZ-GR/candle-cli.git
cd candle-cli
cargo build
```

Repository helpers install the Rust CLI without downloading framework dependencies by default:

```bash
sh scripts/install.sh                # Linux/macOS
.\scripts\install.ps1               # Windows PowerShell
```

Use `--with-python` on Linux or `-InstallPythonDependencies` on Windows only when Bridge/framework dependencies are needed. `sh scripts/demo.sh` and `scripts/demo.ps1` run an offline doctor, mapping, scan, patch preview, and frozen-security walkthrough without modifying the example source.

### Recommended: DeepSeek API

```bash
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_DEEPSEEK_API_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

cargo run -- prompt "Read README.md and summarize this project"
cargo run --
```

### Local fallback: Ollama

```bash
ollama pull qwen2:0.5b

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_STYLE="ollama-native"
export CANDLE_CLI_API_BASE_URL="http://localhost:11434"
export CANDLE_CLI_API_KEY="ollama"
export CANDLE_CLI_MODEL_ID="qwen2:0.5b"

cargo run -- prompt "Hello, introduce yourself"
```

> Small models (0.5B–3B) may not reliably follow the tool-call protocol. Use 7B+ or API models for agentic tasks.

## Usage

| Command | Purpose |
|---------|---------|
| `cargo run -- prompt "..."` | One-shot prompt and exit |
| `cargo run --` | Interactive REPL with readline editing |
| `cargo run -- harness` | Run automated scenario benchmark |
| `cargo run -- security-harness` | Run deterministic path/permission security regression benchmark |
| `cargo run -- security-heldout` | Run the independently frozen M18 security heldout suite |
| `cargo run -- context-harness` | Measure deterministic turn-compaction reduction and integrity |
| `cargo run -- doctor [--json]` | Check Rust, Python, frameworks, Docker, Bridge, Provider, and dual-runtime configuration |
| `cargo run -- migrate scan <path>` | Scan PyTorch APIs and emit a versioned JSON report |
| `cargo run -- migrate run <path>` | Run the scan, rewrite, validation, trace comparison, and rollback workflow |
| `cargo run -- migrate map <api>` | Query a versioned MindSpore mapping with official evidence |
| `cargo run -- migrate import-msprobe ...` | Normalize an msprobe `dump.json` into canonical JSONL |
| `cargo run -- migrate compare <pt.jsonl> <ms.jsonl>` | Align traces and locate the first observable divergence |
| `cargo run -- migrate rewrite <path>` | Preview deterministic API and dtype rewrites without modifying source |
| `cargo run -- migrate rollback <manifest>` | Restore files from a rewrite transaction |

### PyTorch-to-MindSpore migration scan

```bash
# JSON on stdout
cargo run -- migrate scan ./project --pretty

# Markdown report; existing files are not overwritten by default
cargo run -- migrate scan ./project --format markdown --output scan-report.md

# Explicitly replace an existing report
cargo run -- migrate scan ./project --format markdown --output scan-report.md --force

# Query one API directly
cargo run -- migrate map torch.arange --pretty

# Import API-level msprobe statistics from both framework runs
cargo run -- migrate import-msprobe torch_dump/dump.json torch.jsonl \
  --framework pytorch --framework-version 2.1 --run-id experiment-001
cargo run -- migrate import-msprobe ms_dump/dump.json mindspore.jsonl \
  --framework mindspore --framework-version 2.9.0 --run-id experiment-001

# Compare the saved artifacts; a valid divergence is reported as JSON, not a process failure
cargo run -- migrate compare torch.jsonl mindspore.jsonl --pretty

# Preview a minimal patch; source files are not changed
cargo run -- migrate rewrite ./project --pretty

# Run the unified preview workflow and write Markdown
cargo run -- migrate run ./project \
  --format markdown --output migration-report.md

# Apply the patch and require validation in a MindSpore environment
cargo run -- migrate run ./project --apply \
  --validate-program /path/to/mindspore/python \
  --validate-arg=-m --validate-arg=pytest

# Let a versioned manifest collect both traces, compare them, and roll back on failure
export CANDLE_CLI_PYTORCH_PYTHON=/path/to/pytorch/python
export CANDLE_CLI_MINDSPORE_PYTHON=/path/to/mindspore/python
cargo run -- migrate run ./project/model.py --apply \
  --runtime-manifest ./project/runtime_manifest.json

# Apply only exact mappings and run a validator without a shell
cargo run -- migrate rewrite ./project --apply \
  --validate-program python --validate-arg=-m --validate-arg=pytest

# Restore a transaction after a successful apply
cargo run -- migrate rollback \
  ./project/.candle-cli/backups/<transaction-id>/manifest.json --pretty
```

The scanner uses only Python's standard-library AST and never imports or executes the target project. It resolves common import aliases, records source spans and arguments, infers statically identifiable Tensor methods, and flags dynamic `getattr` calls. Each finding includes the target API, framework versions, knowledge snapshot, difference categories, and official evidence when known. The default per-file limit is 2 MiB and can be changed with `--max-file-bytes`.

The current snapshot is grounded in the official PyTorch 2.1 to MindSpore 2.9.0 mapping table and contains 53 validated records. It covers 27 of 36 unique APIs (75%) in the fixed scanner suite: 25 exact, 2 different, and 9 unknown. An absent entry means the snapshot does not know; it does not claim that MindSpore lacks the API.

The checked-in `torch2ms-scanner-v1` syntax suite contains 50 tasks. This version exactly matches 50/50 cases with 100% precision and recall on that public development suite. These numbers demonstrate coverage of the included syntax patterns only; they are not an estimate for unseen real-world projects. A separate held-out project suite is planned.

Runtime comparison accepts canonical traces produced by the lightweight `TraceRecorder` or imported from current msprobe API-level `dump.json` statistics. Calls are aligned through the versioned mapping snapshot and compared in order by runtime error, return structure, dtype, shape, NaN/Inf counts, and numerical summaries. The fixed `trace-defects-v1` suite contains 10 synthetic cases and currently reaches 100% classification accuracy and 100% Top-1 localization on its 8 injected defects. This is a reproducible development-set result, not a real-world generalization claim; see `docs/M4_VERIFICATION.md` for scope and limitations.

Rewriting is preview-only by default. The rewriter resolves import aliases and changes only mapped call names plus supported `dtype=` constants inside accepted calls; comments and surrounding formatting remain untouched. Mappings marked `difference` require `--include-differences`. Apply verifies preview hashes, writes same-filesystem backups and a transaction manifest, and automatically restores all changed sources if the validator fails or times out. An apply without `--validate-program` is deliberately reported as `verified: false`. The fixed `rewrite-cases-v1` synthetic development set contains 15 cases and currently has 100% exact-patch, safe-skip, and syntax-valid rates; it includes a mixed-migration case to ensure a still-used PyTorch import is preserved. This is not a held-out or real-project benchmark.

The pinned `real-projects-v1` corpus adds an out-of-sample coverage audit over 25 files and 4,436 lines from PyTorch Examples, nanoGPT, and DETR. With knowledge snapshot `ms2.9.0-pt2.1-2026-08-05.1`, all 25 files scan without issues, while only 132/545 findings (24.22%) and 21/162 unique APIs (12.96%) are mapped. Exact-only rewriting finds 71 call edits across 18 files and all 18 previews remain syntactically valid. These are static coverage and syntax metrics, not runtime migration accuracy; see `docs/M6_REAL_PROJECT_BASELINE.md`.

After evidence-backed expansion to snapshot `.3`, mapped call coverage reaches 244/545 (44.77%), exact-only rewrite opportunities rise from 71 to 115, and all 18 preview files remain syntax-valid. A rule-frozen held-out audit on Segment Anything scans 17/17 files and maps 89/212 calls (41.98%), with 9/9 generated preview files syntax-valid. See `docs/M6_REAL_PROJECT_RESULTS.md`; these remain static metrics rather than MindSpore runtime accuracy.

The version-gated runtime parity microbenchmark captures five deterministic API chains in separate PyTorch and MindSpore environments, then evaluates return structure, dtype, shape, NaN/Inf and numeric summaries through the common trace comparator. A pinned Linux run of `runtime-parity-v2` on PyTorch 2.6.0+cu124 and MindSpore 2.9.0 captured 5/5 cases and 10/10 calls on each side; all 5 cases were equivalent, for 100% parity and classification accuracy with both version gates satisfied. This is a basic forward-API microbenchmark, not whole-project migration accuracy. See `docs/M7_RUNTIME_PARITY.md`.

`runtime-components-v1` extends the same evidence path to an MLP, a CNN block, input/weight gradients, BatchNorm inference, and three frozen dtype/default-mode/missing-operator defects. A pinned Linux run captured 7/7 cases and 12/12 call records per framework: all 4 equivalent components passed, all 3 held-out defects had the correct class and first-divergence Top-1, and the gradient case was equivalent. This remains a small deterministic component/fault-injection suite, not end-to-end project migration accuracy. See `docs/M11_COMPONENT_PARITY.md`.

`runtime-training-v1` extends validation to a minimal training step: forward output, MSE loss, parameter gradients, and parameter snapshots after one SGD update. A pinned Linux run on PyTorch 2.6.0+cu124 and MindSpore 2.9.0 captured 3/3 cases and 12/12 call records on each side: both equivalent training cases passed, and the frozen learning-rate fault was localized Top-1 at the optimizer update stage. This remains a small deterministic training-step benchmark, not evidence for multi-step convergence, Adam, mixed precision, distributed training, or whole-project migration accuracy. See `docs/M12_TRAINING_PARITY.md`.

`workflow-e2e-v1` exercises the unified `migrate run` state machine across scanning, rewriting, program execution, trace comparison, and rollback. On PyTorch 2.6.0+cu124 and MindSpore 2.9.0, all 4 frozen scenarios matched expectations: the real cross-framework apply passed, both injected failures restored the original bytes, and the dtype fault was localized Top-1 before rollback. The suite contains one executable two-operator fixture and two labelled faults, so it demonstrates workflow control and recovery rather than whole-project migration accuracy. See `docs/M13_END_TO_END_WORKFLOW.md`.

`real-model-dual-runtime-v1` pins the 141-line PyTorch Examples MNIST source and builds a 25-line offline executable slice from its classifier head. The workflow launches PyTorch 2.6.0+cu124 and MindSpore 2.9.0, captures both traces, applies six automatic edits, and reports one manual functional adaptation separately. All 3 frozen scenarios passed: the normal migration was equivalent and both injected failures restored the original bytes, for a 6/7 (85.7143%) automatic-patch adoption rate. The slice maps all 5 runtime findings, but this is not a success-rate claim for the full upstream program or unseen projects. See `docs/M14_REAL_MODEL_DUAL_RUNTIME.md`.

`data-pipeline-randomness-v1` runs 18 frozen data-input cases through PyTorch 2.6.0+cu124/torchvision 0.21.0+cu124 and MindSpore 2.9.0. It covers TensorDataset/DataLoader, Normalize, Resize, ToTensor, layout, dtype, labels, masks, tail batches, fixed seeds, Dropout, sampling, and initialization. All 7 deterministic-equivalence cases and 3 statistical-equivalence cases passed; all 8 injected faults were classified and localized Top-1 correctly. The four random cases report sample size, statistics, and thresholds and explicitly avoid elementwise equality. These are fixed small-array and fault-injection results, not unseen-project accuracy or proof that framework RNG algorithms are identical. See `docs/M15_DATA_PIPELINE_RANDOMNESS.md`.

`advanced-training-v1` runs 13 frozen cases across PyTorch Eager and MindSpore PYNATIVE/GRAPH on CPU. All four forward components match across the three runtimes; two of three 3-5-step optimizer cases match, while the AdamW + learning-rate sequence exposes a reproducible cross-framework optimizer-state divergence instead of hiding it behind tolerance. All three fresh-process checkpoint round trips succeed, and all five injected compile/runtime/gradient/optimizer/shape faults are classified Top-1 correctly. These are tiny deterministic trajectories, not convergence, accelerator, mixed-precision, or distributed-training results. See `docs/M16_GRAPH_ADVANCED_TRAINING.md`.

The checked-in `security-regression-v1` suite exercises 12 local path/permission attacks and 10 benign controls without running dangerous shell commands. All 12 attacks were intercepted (10 hard blocks and 2 confirmation gates), while 10/10 benign cases were allowed. These figures apply only to this deterministic regression set, not unknown attacks, container escape, prompt injection, or network exfiltration; see `docs/M8_SECURITY_BENCHMARK.md`.

M18 adds a separately frozen `security-heldout-v1` suite. On Linux, 12/15 attack cases were applicable and all 12 were blocked or confirmation-gated; 8/8 benign controls were allowed or intentionally gated, for a 0% false-block rate. Archive traversal (no extractor exists), race-free symlink swapping, and Windows junctions remain explicitly `not_applicable` and are excluded from the rate. M18 also prevents recursive search from following external symlinks, passes web queries as opaque arguments, requires confirmation for network access, and bounds file/shell output memory. See `docs/M18_RELEASE_SECURITY_CI.md` and `docs/FINAL_BENCHMARK_REPORT_CN.md`.

The `context-fact-retention-v2` suite uses recent verbatim turns plus structured task state and verifiable source digests across 20 frozen migration conversations. Estimated tokens fall from 23,146 to 4,221 (81.76%); required file, command, error, pending-action, and decision facts are retained 20/20, historical-fact tasks remain answerable 20/20, and source digests verify 20/20. This is still a deterministic heuristic, not provider billing data. The Bridge collects provider-reported token/cache usage, and Agent ablation now has a `--smoke` capability gate whose output is ineligible for formal claims. The available `qwen2:0.5b` did not pass the tool-use smoke, so the formal provider ablation has not run and cache hit rate remains `null`. See `docs/M17_CONTEXT_AGENT_ABLATION.md`.

### REPL commands

| Command | Alias | Purpose |
|---------|-------|---------|
| `/help` | `/h` | Show available commands |
| `/exit` | `/quit`, `/q` | Exit and save session |
| `/session` | `/info` | Show session metadata |
| `/status` | | Show runtime, model, permission status |
| `/tools` | | List registered tools |
| `/trace` | | Show execution trace with timing; `--json` for structured export |
| `/system` | | Show active system prompt |
| `/name <label>` | | Name current session |
| `/memory` | | Manage project memory (file/cmd/note subcommands) |
| `/clear` | | Clear current session |
| `/list` | `/ls` | List saved sessions |
| `/resume <id>` | | Resume a saved session |
| `/save` | | Save current session |

## Agentic system

### Tool call protocol

Models request tools via text JSON blocks:

```text
<tool_call>{"id":"call-1","name":"read","input":{"file_path":"README.md"}}</tool_call>
```

Rust parses the block, executes the tool, records the result in session, and feeds it back to the model. The loop continues until the model produces a final answer or reaches the maximum step count (8). A fallback parser also accepts function-style calls: `read({"file_path":"README.md"})`.

### Available tools

| Tool | Input | Purpose | Mutates |
|------|-------|---------|---------|
| `pwd` | `{}` | Show workspace directory | No |
| `read` | `{"file_path":"README.md"}` | Read a UTF-8 file (path boundary enforced) | No |
| `glob` | `{"pattern":"src/**/*.rs"}` | Find files by pattern | No |
| `grep` | `{"pattern":"fn main","path":"src"}` | Search file contents recursively | No |
| `web_search` | `{"query":"today weather"}` | Web search via DuckDuckGo/Sogou fallback | No |
| `task` | `{"description":"analyze this code"}` | Delegate to read-only sub-agent (3-step loop) | No |
| `write` | `{"file_path":"report.txt","content":"..."}` | Write a UTF-8 file inside the workspace | **Yes** |
| `edit` | `{"file_path":"Cargo.toml","old_string":"0.1.0","new_string":"0.3.0"}` | Replace exactly one text occurrence | **Yes** |
| `shell` | `{"command":"cargo test"}` | Run shell command with timeout | **Possible** |

### Permission modes

| Mode | Behavior |
|------|----------|
| `read-only` | Allow `pwd`, `read`, `glob`, `grep` only |
| `read-only-with-task` | Allow read tools plus `task`, without shell or mutation |
| `workspace-write` (default) | Allow workspace file edits; require confirmation for host shell commands |
| `prompt` | Auto-allow read tools; confirm `edit`, `write`, `shell` interactively |
| `danger-full-access` | Allow all tools, including host shell commands, without confirmation |

### Multi-agent coordination

The `task` tool spawns a sub-agent with read-only permission and a 3-step bounded loop. Parent and sub-agent share model-request and tool-step budgets, and the sub-agent inherits the parent's workspace root. This keeps single/delegated ablations budget-comparable and prevents reads from an unrelated process directory.

### Layered memory

- **Session memory**: dialogue history persisted as JSON, supports list/resume/clear
- **Project memory**: `.candle-cli/memory.json` stores key files, common commands, and free-form notes; automatically injected into system prompt

```bash
/memory file src/main.rs
/memory cmd cargo test
/memory note build=takes ~5s on 4090
```

### Sandboxed execution

Set `CANDLE_CLI_SANDBOX=docker` to run shell commands in an isolated Alpine container with read-only workspace mount and network disabled.

### Fault tolerance

- API retry with exponential backoff (3 attempts, 1s/2s/4s, 4xx not retried)
- Shell timeout with SIGKILL (configurable via `CANDLE_CLI_SHELL_TIMEOUT_SECS`)

### RAG pre-search

Before each turn, the context builder extracts keywords from the user message, runs grep against `src/`, and injects matching code snippets into the prompt. Greetings and chat messages are automatically detected and skipped.

### Observability

- `/tools` — system capability boundary
- `/status` — runtime snapshot (session, model, permission, configuration)
- `/trace` — execution chain with per-step millisecond timing; `--json` for structured analysis

### Harness

```bash
cargo run -- harness
```

Runs four predefined scenarios (read, glob, grep, shell) and produces a pass/fail report with timing, tool step counts, and a `harness_report.json` output.

## Model backends

Set `CANDLE_CLI_RUNTIME=bridge` for real model calls (default `mock` for testing).

| Backend | `CANDLE_CLI_API_BASE_URL` | `CANDLE_CLI_API_KEY` | `CANDLE_CLI_MODEL_ID` |
|---------|---------------------------|----------------------|-----------------------|
| DeepSeek | `https://api.deepseek.com/v1` | `YOUR_DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
| Ollama native | `http://localhost:11434` | `ollama` | `qwen2:0.5b` |
| vLLM | `http://localhost:8000/v1` | `not-needed` | `Qwen/Qwen2-0.5B-Instruct` |
| OpenAI | `https://api.openai.com/v1` | `sk-xxx` | `gpt-4o-mini` |

### Local transformers model

```bash
python3 -m pip install -r requirements.txt

export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_MODEL_ID="Qwen/Qwen2-0.5B-Instruct"
export CANDLE_CLI_MODEL_DEVICE="cpu"
export CANDLE_CLI_LOCAL_FILES_ONLY="false"

cargo run -- prompt "Hello"
```

### Verbose diagnostics

Set `CANDLE_CLI_VERBOSE=1` for API request details, token usage, timing, and GPU memory diagnostics on stderr.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `CANDLE_CLI_RUNTIME` | `mock` | `mock` or `bridge` |
| `CANDLE_CLI_MODEL_ID` | `Qwen/Qwen2-0.5B-Instruct` | Model ID or local path |
| `CANDLE_CLI_MODEL_DEVICE` | auto | `cpu`, `cuda`, or `auto` |
| `CANDLE_CLI_LOCAL_FILES_ONLY` | `true` | Use only local files (no download) |
| `CANDLE_CLI_API_BASE_URL` | (empty) | OpenAI-compatible API base URL |
| `CANDLE_CLI_API_KEY` | (empty) | API key |
| `CANDLE_CLI_API_STYLE` | `openai` | `openai` or `ollama-native`; native mode supports Ollama `think=false` |
| `CANDLE_CLI_MAX_NEW_TOKENS` | `512` | Max generated tokens per turn |
| `CANDLE_CLI_TEMPERATURE` | `0.7` | Sampling temperature |
| `CANDLE_CLI_TOP_P` | `0.9` | Top-p sampling |
| `CANDLE_CLI_SYSTEM_PROMPT` | built-in | Override system prompt |
| `CANDLE_CLI_MAX_TURNS` | `20` | Max retained conversation turns |
| `CANDLE_CLI_PERMISSION` | `workspace-write` | Permission mode |
| `CANDLE_CLI_PERMISSION_RESPONSE` | (empty) | Pre-set prompt responses (`y`/`allow`/`deny`) |
| `CANDLE_CLI_SHELL_TIMEOUT_SECS` | `30` | Shell command timeout (seconds) |
| `CANDLE_CLI_MAX_SHELL_OUTPUT_BYTES` | `1048576` | Maximum retained bytes for each shell stdout/stderr stream |
| `CANDLE_CLI_MAX_READ_BYTES` | `2097152` | Maximum UTF-8 file size accepted by the read tool |
| `CANDLE_CLI_MAX_TOOL_OUTPUT_CHARS` | `65536` | Maximum tool-result characters retained in model/session context |
| `CANDLE_CLI_ALLOW_STUB_FALLBACK` | `false` | Enable echo-only bridge stub for demos/tests; never enable for real agent tasks |
| `CANDLE_CLI_INCLUDE_USAGE` | `true` | Request usage in streaming API responses; disable for incompatible local backends |
| `CANDLE_CLI_SANDBOX` | (empty) | Set to `docker` for container isolation |
| `CANDLE_CLI_VERBOSE` | `false` | Print diagnostics to stderr |
| `CANDLE_CLI_MODEL_CONFIG` | (empty) | Optional JSON config file path |
| `CANDLE_CLI_SESSION_DIR` | system temp dir | Session storage directory |

## Examples

```bash
# Standalone inference tests
python3 examples/api_inference.py
python3 examples/qwen3_local_inference.py

# Multi-step agentic task
export CANDLE_CLI_RUNTIME="bridge"
export CANDLE_CLI_API_BASE_URL="https://api.deepseek.com/v1"
export CANDLE_CLI_API_KEY="YOUR_KEY"
export CANDLE_CLI_MODEL_ID="deepseek-v4-flash"

cargo run -- prompt "Read src/tools/registry.rs and summarize the tool dispatch logic"

# Harness benchmark
cargo run -- harness
```

## Development

```bash
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test
PYTHONPATH=python python3 -m pytest python -q
```

## License

MIT
