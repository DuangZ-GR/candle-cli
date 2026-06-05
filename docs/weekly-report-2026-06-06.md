# candle-cli 开发周报（2026.06.06）

## 本周工作总结

本周围绕 candle-cli 的用户体验改进和功能扩展，完成了 6 项代码变更，版本号从 0.1.0 更新至 0.4.0。主要方向：REPL 交互优化、上下文增强、工具扩展。

## 本周工作进展

1. **修复 REPL 输入编辑问题。** 将裸 `std::io::stdin().read_line()` 替换为 rustyline 库，REPL 现已支持退格删除、方向键移动光标、Home/End 跳转和上下键历史翻查。涉及文件：`Cargo.toml`、`src/cli/repl.rs`。

2. **新增 grep 关键词 RAG 预搜索。** 在每轮 agent 调用前自动提取用户问题中的关键词，对 `src/` 目录执行 grep，将前 10 行匹配结果拼入用户消息上下文。包含保护逻辑：纯聊天（"你好""谢谢"）不触发；停用词（的/了/帮我）被过滤；关键词最多取 4 个。涉及文件：`src/context/builder.rs`。

3. **新增 session 自定义命名。** Session 结构体增加 `label` 字段（可选的、serde 兼容），新增 `/name <label>` slash 命令用于命名，`/list` 和 `/session` 命令同步展示标签。涉及文件：`src/session/model.rs`、`src/cli/repl.rs`。

4. **新增模型调用等待动画。** 在 `runtime.generate_turn()` 前后启动/停止独立线程的 spinner，显示旋转字符（`/ - \ |`）和已等待秒数，模型返回后自动清除。涉及文件：`src/ui/spinner.rs`、`src/agent/loop.rs`。

5. **新增 web_search 网络搜索工具。** 模型可通过 `{"query":"..."}` 调用 DuckDuckGo Lite 搜索，失败时自动回退至 Sogou 搜狗。HTML 清洗使用 Python `re.DOTALL` 模式完整删除多行 script/style 块，中文字符经 `urllib.parse.quote` 编码。该工具在 read-only 和 workspace-write 模式均可使用。涉及文件：`src/tools/builtin/web_search.rs`（新建）、`src/tools/builtin/mod.rs`、`src/tools/registry.rs`、`src/agent/loop.rs`、`src/context/builder.rs`。

6. **版本号更新。** `Cargo.toml` 版本号由 0.1.0 更新至 0.4.0，`CHANGELOG.md` 补充 v0.3.0 和 v0.4.0 变更记录。涉及文件：`Cargo.toml`、`CHANGELOG.md`、`Cargo.lock`。

## 当前项目状态

项目当前处于 v0.4.0 版本，81 个 Rust 测试 + 27 个 Python 测试全部通过。现已具备 agent loop（8 步）、7 个工具（pwd/read/glob/grep/web_search/edit/shell）、4 种权限模式、session 持久化、REPL 编辑交互、RAG 预搜索和等待动画等功能。所有改动已推送至 GitHub main 分支。

## 下周计划

- 验证 web_search 工具在真实场景下的搜索质量，必要时优化 HTML 提取逻辑。
- 补充 web_search 和 RAG 相关的单元测试。
- 优化系统提示词，提升模型主动调用 web_search 的比例。
- 继续根据使用反馈优化 REPL 交互体验。
