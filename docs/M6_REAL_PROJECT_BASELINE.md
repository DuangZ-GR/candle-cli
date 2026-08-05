# M6 真实项目静态评测基线

## 为什么需要这组数据

仓库此前的 scanner、trace 和 rewrite 评测均为公开合成开发集，适合做确定性回归，但不能代表真实 PyTorch 工程。MindSpore 官方迁移指南建议先扫描项目 API 并查询映射表，但目前没有找到可直接复用的标准化 PyTorch→MindSpore Agent benchmark。因此本阶段建立 `real-projects-v1`，用于测量真实源码上的解析稳定性、映射覆盖率和安全 Patch 机会。

这不是人工标注的迁移正确率测试。评测器不执行第三方代码，也不把“Patch 后语法有效”解释为 MindSpore 运行等价。

## 数据集冻结方式

第三方源码不进入本仓库，只在用户指定的外部缓存目录准备。清单固定 HTTPS 仓库地址、完整 40 位 commit、许可证文件和选取路径；评测前会拒绝 commit 不一致、tracked worktree 不干净、许可证缺失、路径逃逸和符号链接。

| 项目 | 固定 commit | 许可证 | 选取内容 |
|---|---|---|---|
| `pytorch/examples` | `acc295dc7b90714f1bf47f06004fc19a7fe235c4` | BSD-3-Clause | MNIST、DCGAN、VAE、word language model |
| `karpathy/nanoGPT` | `3adf61e154c3fe3fca428ad6bc3818b27a3b8291` | MIT | 根目录 Python 训练、模型、采样代码 |
| `facebookresearch/detr` | `29901c51d7fe8712168b8d0d64351170bc0f83e0` | Apache-2.0 | main、engine、models、util |

准备与执行：

```bash
python -m migration.real_corpus /external/cache/real-projects-v1 --pretty
python -m migration.real_project_benchmark /external/cache/real-projects-v1 --pretty
```

源码准备使用参数数组和 `shell=False` 调用 Git。重复运行时不会更新到分支最新版本，而是严格校验清单中的 commit。

## 冻结基线结果

本次结果绑定知识库快照 `ms2.9.0-pt2.1-2026-08-05.1` 及 SHA-256 `bd6560e4...fbc765`。完整逐项目 JSON 位于 `benchmarks/results/real_projects_v1_baseline.json`。

| 指标 | 结果 |
|---|---:|
| 项目 / 文件 / 物理行 | 3 / 25 / 4,436 |
| 成功扫描文件 | 25/25，100% |
| 静态发现 / 唯一 API | 545 / 162 |
| 已映射调用发现 | 132/545，24.22% |
| 已映射唯一 API | 21/162，12.96% |
| exact / difference / unknown | 102 / 30 / 413 |
| exact-only 调用重写机会 | 71 |
| 带 Patch 文件 | 18 |
| Patch 语法有效 | 18/18，100% |

这里的 100% 只表示所有生成预览都能被 Python AST 再次解析，不代表其能通过 MindSpore 运行时验证。24.22% 的映射覆盖率是当前小型知识库在真实代码上的诚实基线，说明知识库扩充是下一步最高收益项。

## 真实缺口

按调用频次排序的主要 unknown 包括：

- `torch.nn.Conv2d`：17 次；
- `torch.no_grad`：17 次；
- `torch.nn.Dropout`：16 次；
- `torch.load`、`torch.manual_seed`：各 9 次；
- `torch.Tensor.to`、`torchvision.transforms.ToTensor`：各 8 次；
- `torch.Tensor.size`、`torch.device`、`torch.nn.BatchNorm2d`：各 7 次。

这些 API 不能统一按“名称相似”自动替换。例如官方文档指出 `torch.Tensor.size()` 对应的是 MindSpore `Tensor.shape` 属性；BatchNorm 和 Dropout 还涉及默认训练/推理模式。因此后续规则必须区分：可直接加入 exact 映射、只能标记 difference、需要结构性重写、以及没有安全自动替代的上下文 API。

## 可复现性与限制

- 基线结果保存知识库快照版本和文件哈希，后续扩充不会冒充同一次评测。
- 选取项目在规则扩充前冻结，但该语料没有人工标注所有调用位置，因此不能计算 scanner precision/recall。
- 评测只做 AST 扫描和 Patch 预览，不下载数据集、权重，也不导入 PyTorch/MindSpore。
- 后续应把这三个项目作为开发/覆盖审计集；规则冻结后另选未查看的新项目做最终 held-out 测试。

## 来源

- MindSpore 迁移准备指南：<https://www.mindspore.cn/docs/en/r2.3.0/migration_guide/analysis_and_preparation.html>
- MindSpore PyTorch API 映射表：<https://www.mindspore.cn/docs/en/r2.7.2/note/api_mapping/pytorch_api_mapping.html>
- PyTorch Examples 许可证：<https://github.com/pytorch/examples/blob/main/LICENSE>
- nanoGPT：<https://github.com/karpathy/nanoGPT>
- DETR：<https://github.com/facebookresearch/detr>
