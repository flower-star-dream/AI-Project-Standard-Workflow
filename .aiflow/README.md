# `.aiflow` —— AIPSW 工作流空间

本目录是 AIPSW（AI 项目开发标准规范工作流程）的工作流空间，放在仓库根目录。四个区各司其职（规范 §3.18）：

| 区 | 生命周期 | 能不能改 | 检索可见 |
| --- | --- | --- | --- |
| `baseline/` | 长期 | 可改，但须留变更理由与影响范围 | ✅ |
| `work/` | 单次变更 | 执行中可自由改 | ✅ 仅当前变更 |
| `snapshots/` | 永久只读 | 创建后不可改 | ⚠️ 仅供追溯 |
| `archive/` | 永久 | 只增不删 | ❌ 物理隔离 |

## 从哪开始

1. `baseline/conventions.md` —— **先填这个**（尤其「合格范例」一节点 2~3 个真实路径，它决定 AI 生成时的风格对齐）；
2. `baseline/terms.yaml` —— 先定 10~20 个核心术语；
3. `baseline/contracts/` —— 有并行前才需要冻结；
4. `baseline/fmea.md` —— Top 10（个人模式 Top 5）；
5. `baseline/evals/cases.yaml` —— 评测集基线；
6. `baseline/assets.md` —— 可复用资产清单；
7. `baseline/现状地图.md` / `decisions.md` —— 改存量、做决策时补。

## 三条硬规矩

- `baseline/` 里**同一事实只留一处**（术语、契约、约束不得多份手写）——B2；
- 一次性产物（影响面、回归基线、查询报告）写进 `work/CHG-YYYYMMDD-NN/`，**不要写进 baseline**；
- 废弃内容移进 `archive/`，否则下次检索会把旧方案当现行用。
