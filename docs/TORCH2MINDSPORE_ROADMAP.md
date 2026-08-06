# Torch2MindSpore Agent 完整执行路线图

## 1. 产品定位

将 `candle-cli` 从通用 Agent CLI 逐步重构为面向 PyTorch→MindSpore
工程迁移的智能诊断与修复 Agent。

目标工作流为：

```text
扫描 → 分类 → 转换 → 执行 → 对齐 → 诊断 → 修复 → 验证
```

第一个达到生产质量的目标不是“完全自动转换所有代码”，而是建立可信的
诊断闭环：能够定位 PyTorch 与 MindSpore 执行过程中出现的第一个语义偏差，
并给出支撑该结论的源码位置、运行数据和官方资料证据。

## 2. 核心设计原则

1. 优先使用确定性分析，规则无法覆盖时再调用大模型。
2. 每条诊断结论必须包含源码位置和运行时证据。
3. 每条结果都必须记录 PyTorch、MindSpore 和映射知识库版本。
4. 修复结果必须通过差分验证后才能标记为成功。
5. 优先集成 MindSpore 官方迁移工具，不重复实现已有底层能力。
6. 大模型和 API 的失败必须显式暴露，不能伪装成成功结果。
7. 功能、评测和可观测性同步开发，避免最后才补数据。

## 3. 目标架构

### Rust 控制平面

- CLI 与配置管理
- Agent Loop 与任务状态机
- 权限策略与沙箱调度
- 执行轨迹规范化和对齐
- 差异分类与首个偏差定位
- Benchmark 编排
- 结构化事件和报告生成

### Python 执行平面

- Python AST/CST 代码分析和改写
- PyTorch 与 MindSpore 运行时集成
- Troubleshooter/API Dump 集成
- 正向和反向数据探针
- 大模型 Provider Bridge

### 版本化知识平面

- PyTorch API 名称与版本
- MindSpore API 名称与版本
- 参数、默认值、dtype、输出结构差异
- 缺失算子及组合实现方案
- 官方来源 URL 和采集时间
- 已通过本地验证的修复规则

## 4. 计划中的仓库结构

```text
src/
  migration/
    mod.rs
    schema.rs
    classify.rs
    align.rs
    diagnose.rs
    report.rs
  cli/
    migrate.rs
python/
  migration/
    scanner.py
    schema.py
    trace_normalizer.py
    runner_torch.py
    runner_mindspore.py
    repair.py
knowledge/
  mappings/
  rules/
benchmarks/
  api_cases/
  component_cases/
  injected_faults/
  manifests/
```

该结构将按里程碑逐步引入。在替代功能通过验证前，保留现有模块并保持兼容。

## 5. 统一诊断数据协议

所有静态分析和运行时观测数据统一转换为以下结构：

```json
{
  "schema_version": "1.0",
  "run_id": "uuid",
  "framework": "pytorch",
  "framework_version": "2.1.0",
  "mode": "eager",
  "file": "model.py",
  "line": 42,
  "column": 8,
  "api": "torch.sum",
  "call_index": 3,
  "inputs": [{"shape": [32, 128], "dtype": "float32"}],
  "output": {
    "shape": [32],
    "dtype": "float32",
    "min": -1.0,
    "max": 1.0,
    "nan_count": 0,
    "inf_count": 0
  }
}
```

诊断结果采用稳定的错误分类：

- `missing_operator`：缺失算子
- `unmapped_api`：API 未映射
- `parameter_mismatch`：参数不一致
- `default_value_mismatch`：默认值不一致
- `dtype_mismatch`：数据类型不一致
- `shape_mismatch`：形状不一致
- `return_structure_mismatch`：返回结构不一致
- `value_mismatch`：数值不一致
- `gradient_mismatch`：梯度不一致
- `randomness_mismatch`：随机性不一致
- `layout_mismatch`：HWC/CHW 等布局不一致
- `normalization_mismatch`：归一化范围或缩放不一致
- `label_dtype_mismatch`：标签类型不一致
- `mask_dtype_mismatch`：布尔掩码类型不一致
- `batching_mismatch`：批大小、尾批次或 drop-last 语义不一致
- `transform_mismatch`：Transform 类型或参数不一致
- `reproducibility_mismatch`：固定种子重复执行不可复现
- `random_distribution_mismatch`：随机统计分布超出冻结阈值
- `graph_compile_failure`：图模式编译失败
- `optimizer_state_mismatch`：优化器超参数、状态槽或更新轨迹不一致
- `checkpoint_mismatch`：Checkpoint 参数结构或恢复输出不一致
- `device_unsupported`：设备不支持
- `runtime_error`：运行时错误
- `needs_manual_review`：需要人工确认

## 6. 里程碑

### M0：基线建立与现有系统稳定化

预计工作量：3～5 个开发日。

交付内容：

- 建立干净的功能分支并记录基线提交
- 修复多步工具调用的上下文裁剪
- RAG 只增强请求上下文，不修改原始会话
- 交互模式复用长驻 Python Worker
- Bridge 错误显式传播
- 统一工具注册、工具说明与权限行为
- 限制工具输出长度并校验 Session ID
- 增加 Python版本和运行环境检查

验收标准：

- 在受支持的 Rust/Python环境中通过现有测试
- 每个修复问题都有对应回归测试
- API 请求失败能够被调用方识别为失败
- 重复 Agent Step 不会递归扩大用户消息

### M1：静态迁移扫描器

预计工作量：5～8 个开发日。

交付内容：

- `migrate scan <path>` 命令
- 支持 import 别名解析的 Python AST 扫描器
- 提取 PyTorch API、源码位置和调用参数
- 稳定的 JSON 扫描报告
- 第一版迁移风险分类器
- Markdown 报告生成

第一版扫描范围：

- `torch.*`
- `torch.nn.*`
- `torch.nn.functional.*`
- `import` 和 `from import` 别名
- 部分常用 Tensor Method

验收标准：

- 至少 50 个扫描器测试样例
- 测试集上的 API 调用召回率不低于 95%
- 每条结果均包含文件、行号、规范化 API 和风险等级

### M2：版本化 API 映射知识库

预计工作量：4～7 个开发日。

交付内容：

- 版本化本地映射格式
- 官方资料来源和证据字段
- 直接一致、存在差异、不支持、未知四类状态
- 参数、默认值、dtype 和返回结构差异
- 确定性逻辑与 Agent 共用的查询接口

验收标准：

- 可以从固定版本的官方来源重复生成映射数据
- 所有“不支持”结论都包含来源证据
- Benchmark 报告记录两个框架的版本

### M3：差分轨迹接入与根因诊断

当前执行批次 M4 已完成本节第一版实现和本地验收，详见 `docs/M4_VERIFICATION.md`。

预计工作量：10～15 个开发日。

交付内容：

- Troubleshooter/API Dump 适配器
- 规范化 PyTorch/MindSpore JSONL 轨迹
- 第一版调用序列对齐算法
- dtype、shape、NaN/Inf 和数值误差比较
- 首个可观测差异定位
- 带证据的诊断报告

验收标准：

- 在第一批缺陷注入集上达到至少 80% 的 Top-1 定位准确率
- 报告能够区分最终报错位置与首个偏差位置
- 可以通过保存的实验产物重复执行比较

### M4：自动修复与验证闭环

预计工作量：10～20 个开发日。

交付内容：

- Level 1 确定性修复：import、API名称和关键字参数
- Level 2 确定性修复：显式 dtype、shape 和默认值适配
- Patch 预览和回滚
- 修复后自动重新执行
- 正向等价性判定
- 对长尾问题生成可选的大模型修复建议

验收标准：

- 未通过验证的修复不能标记为成功
- 确定性修复和大模型修复分别统计成功率
- Patch 失败后保持原始源码不变

### M5：反向、权重、Graph Mode 与组合算子

预计工作量：M4 完成后继续投入 4～8 周。

交付内容：

- 梯度轨迹比较
- PyTorch/MindSpore 权重对齐
- 随机性和状态层控制
- PYNATIVE/GRAPH 模式专项诊断
- 组合算子推荐与验证

验收标准：

- 至少三个有代表性的网络组件通过正向和反向比较
- Graph Mode 错误具有独立、可解释的分类和证据

### M6：评测、文档与发布

该阶段贯穿所有里程碑，M4 后形成第一版可发布结果。

交付内容：

- `Torch2MSBench` 任务清单和固定任务 ID
- API 微测试、网络组件和缺陷注入用例
- 确定性基线、纯 LLM 基线和完整 Agent 消融实验
- JSON 与 Markdown Benchmark 报告
- CI、安装说明、演示材料和架构文档

## 7. 评测方案

### 数据集分层

1. API 微测试：第一版 50 个，目标 200 个以上
2. 网络组件：第一版 5 个，目标 20 个以上
3. 完整迁移案例：第一版 1 个，目标 5～10 个
4. 缺陷注入：第一版 50 个，目标 100 个以上

### 必须采集的指标

- 静态 API 检测准确率和召回率
- API 映射覆盖率和映射准确率
- 缺失算子召回率
- 差异类型分类准确率
- 首个差异 Top-1 和 Top-3 定位准确率
- 确定性自动修复成功率
- 大模型辅助修复成功率
- 正向等价验证通过率
- 反向等价验证通过率
- PYNATIVE/GRAPH 模式等价率
- 多步优化器轨迹等价率
- 跨进程 Checkpoint 恢复率
- 平均诊断耗时
- 输入、输出、缓存 Token 与估算成本
- 工具调用失败率和重试率
- 沙箱拦截率和正常任务误拦截率

### 消融实验

- 仅 API 映射规则
- 仅使用大模型
- API 映射 + 静态分析
- API 映射 + 差分执行
- 自动修复与验证的完整系统
- 复杂任务下的单 Agent 与专家多 Agent 对比

所有实验报告必须记录：模型 ID、temperature、随机种子、框架版本、硬件、
仓库提交、任务清单哈希和知识库版本。

## 8. 多 Agent 使用范围

只有在确定性诊断达到可靠水平后才扩展多 Agent。

候选专家 Agent：

- Scanner：识别迁移位置和风险
- Debugger：分析对齐后的执行轨迹
- Operator Researcher：查询官方映射和替代方案
- Verifier：审查 Patch 并重新执行验证

简单、确定性的 API 映射不得调用子 Agent。只有可独立拆分的检索、分析和验证
任务才允许并行，并且必须设置 Token、时间和工具调用预算。

## 9. 安全能力范围

近期目标：

- 使用 Docker 隔离 Benchmark 执行
- 源码只读挂载，单独配置输出目录
- 默认禁用网络
- 限制 CPU、内存和运行时间
- 超时时清理完整进程树

长期目标：

- 跨平台宿主机原生沙箱
- 基于域名的网络白名单
- 权限决策和越界操作 Telemetry
- 提示注入与数据外传对抗测试集

在同时获得攻击拦截率和正常任务误拦截率前，不对外发布安全性能数字。

## 10. 暂缓开发内容

在迁移诊断闭环得到验证前，暂不优先开发：

- 训练本地大模型
- 恢复 Candle 作为主要推理后端
- 通用浏览器自动化
- 大型向量数据库
- 复杂 Web UI
- 完全通用的多 Agent 调度平台
- 自研容器运行时
- 完整 SWE-bench 评测

## 11. 达到简历量化标准的发布门槛

满足以下条件后，才使用量化数据编写简历：

- 至少一个完整的扫描→诊断→修复→验证演示
- 至少 100 条版本化 API 映射或已验证规则
- 至少 50 个可复现缺陷注入用例
- 已测量 Top-1 定位率和自动修复成功率
- 至少一个真实模型或网络组件迁移案例
- 已发布固定任务清单、汇总结果和环境元数据
- 现有 Agent 基础不存在已知高严重性正确性问题

达到这些条件前，文档只描述已经实现的能力，不编造性能数字。

## 12. 立即执行顺序

M0–M16 已完成并形成从静态扫描、改写、双运行时验证、回滚到数据流水线和高级训练状态的机器证据。当前顺序为：

1. M17：实现“近期原文 + 结构化任务状态 + 可验证摘要”的上下文策略。
2. 固定 Provider、模型和请求集，采集真实 Token、Cache、延迟与成本。
3. 在相同任务、预算和超时下完成单 Agent/多 Agent 消融。
4. M18：增加 CI Benchmark 门禁、安装包、版本、Changelog 和一键复现实验。
