# M6 真实项目评测结果

## 结论

在不执行第三方代码、只进行 AST 扫描与确定性 Patch 预览的前提下，知识库从冻结基线快照 `.1` 扩充至规则快照 `.3` 后：

| 指标 | 基线 `.1` | 扩充后 `.3` | 变化 |
|---|---:|---:|---:|
| 有映射的调用发现 | 132/545（24.22%） | 244/545（44.77%） | +20.55 个百分点 |
| 有映射的唯一 API | 21/162（12.96%） | 37/162（22.84%） | +9.88 个百分点 |
| exact / difference / unknown | 102 / 30 / 413 | 159 / 85 / 301 | unknown 减少 112 |
| exact-only 调用改写机会 | 71 | 115 | +62.0% |
| Patch 文件语法有效 | 18/18 | 18/18 | 保持 100% |

扩充规则来自 MindSpore 官方 PyTorch API 映射资料。带训练/推理默认模式、数据管线、返回结构或数据布局差异的条目保留为 `difference`，默认不会进入自动重写。即使是 `exact` 条目，调用中出现官方列出的通用不兼容参数（例如 `device`、`out`、`requires_grad`）时也会安全跳过。

完整机器可读结果：

- 基线：`benchmarks/results/real_projects_v1_baseline.json`
- 扩充后：`benchmarks/results/real_projects_v1_after.json`

## 规则冻结后的留出测试

知识库 `.3` 冻结后才选取 `facebookresearch/segment-anything`，且不再根据该项目添加规则。固定提交为 `dca509fe793f601edb92606367a655c15ac00fdf`。

| 指标 | 留出结果 |
|---|---:|
| 文件 / 物理行 | 17 / 3,052 |
| 成功扫描 | 17/17（100%） |
| 调用发现 / 唯一 API | 212 / 63 |
| 有映射的调用发现 | 89/212（41.98%） |
| 有映射的唯一 API | 20/63（31.75%） |
| exact / difference / unknown | 68 / 21 / 123 |
| exact-only 调用改写机会 | 45 |
| Patch 文件语法有效 | 9/9（100%） |

留出语料既可通过 Git 固定提交准备，也支持固定 GitHub ZIP。归档模式会校验 ZIP SHA-256、拒绝路径逃逸和符号链接，并逐字节比对许可证与所有参与评测的源码；第三方源码和归档只存放在外部缓存，不进入本仓库。清单位于 `benchmarks/migration/real_projects_heldout_v1.json`，完整结果位于 `benchmarks/results/real_projects_heldout_v1.json`。

```bash
python -m migration.real_corpus /external/cache/real-projects-heldout-v1 \
  --manifest benchmarks/migration/real_projects_heldout_v1.json --pretty
python -m migration.real_project_benchmark /external/cache/real-projects-heldout-v1 \
  --manifest benchmarks/migration/real_projects_heldout_v1.json --pretty
```

## 指标边界

这些数字证明的是静态解析稳定性、知识库覆盖和保守 Patch 的语法有效性，不是端到端迁移准确率：

- 没有人工标注全部调用，所以不能由此计算 scanner precision/recall；
- 没有在此 Windows 环境安装和执行 MindSpore，因此不能把语法有效率称为运行正确率；
- 留出项目只包含一个代码库，结论仍需更多领域和模型结构验证；
- `unknown` 表示当前知识库没有足够证据，不表示 MindSpore 缺失该能力。

下一阶段应在 Linux/MindSpore 环境运行双框架微型用例，测量首个偏差定位 Top-1、dtype/shape/数值差异分类，以及生成修复后的真实运行通过率。

## 官方证据

- MindSpore PyTorch API 映射表：<https://www.mindspore.cn/docs/en/r2.7.2/note/api_mapping/pytorch_api_mapping.html>
- Normalize 差异说明：<https://www.mindspore.cn/docs/en/r2.7.2/note/api_mapping/pytorch_diff/Normalize.html>
- Segment Anything：<https://github.com/facebookresearch/segment-anything>
