# scripts —— AIPSW 配套命令行

零第三方依赖，只需要 Python 3.8+（Windows 用 `aipsw.cmd` 或 `aipsw.ps1` 包装）。

```bash
python scripts/aipsw.py --version   # aipsw tool 1.2.0 (AIPSW v1.14; Python 3.x.y)
```

## 安装到你的项目

```powershell
# 方式一：直接拷脚本过去
Copy-Item -Recurse .\scripts D:\my-project\scripts

# 方式二：把本仓库当工具，项目里只放 .aiflow
python D:\AI-Project-Standard-Workflow\scripts\aipsw.py init --dest D:\my-project
```

## 命令速查

| 命令 | 做什么 | 对应规范 |
| --- | --- | --- |
| `aipsw init` | **交互向导**：问 6 个问题 → 自动填 conventions / fmea / 评测集 / 决策 / 问题清单 | 阶段 0 / §3.18 |
| `aipsw gate terms` | 术语单一事实源检查（重复定义、缺字段、废弃词残留） | §3.9 / B2 |
| `aipsw gate toc` | 目录 ↔ 章节覆盖率（锚点/跨文件链接失效即 error） | 阶段 4 可机械化项 |
| `aipsw gate sig` | 契约 ↔ 代码签名比对（契约有、代码无 → error） | §3.3 / B3 |
| `aipsw gate dup` | 新代码与既有资产重复度（默认阈值 10%） | 阶段 6 / B5 |
| `aipsw gate all` | 依次跑 terms / toc / sig；给 `--new` 时加跑 dup | 合并前门禁 |
| `aipsw scan impact` | 影响面扫描，产出《影响面清单》骨架 | §3.14.2 M1 |
| `aipsw scan delete` | 引用穷尽扫描，产出《删除专项检查单》骨架 | §3.16 D2 |

## 初始化向导（`aipsw init`）

不需要手写任何模板。默认问 **6 个问题**，每题**直接回车 = 用默认值**：

`@
1) 项目叫什么名字？         [当前目录名]
2) 这是什么类型的项目？     1 网站/后端  2 手机 App  3 桌面/命令行  4 数据/脚本  5 不确定
3) 主要用什么语言？         1 Python  2 JS/TS  3 Java  4 Go  5 C#  6 不确定
4) 谁在维护？               1 就我一个  2 小团队  3 大团队
5) 重要到什么程度？         1 试验  2 内部工具  3 对外交付/涉钱
6) 已经有一堆代码了吗？     y/N
`@

### 会自动填什么

| 文件 | 内容 |
| --- | --- |
| `baseline/conventions.md` | 语言/运行时、格式化与静态检查、分层方向（按项目类型）、命名约定（按语言）、错误处理、依赖策略、合格范例占位 |
| `baseline/fmea.md` | Top 5 / Top 10 初始失效模式（取自通用高发风险库），S/O/D 已按附录 C.3 锚点打分，RPN 已算 |
| `baseline/evals/cases.yaml` | 5+3 或 10+5+3 条用例骨架（normal / edge / negative / guardrail 四类） |
| `baseline/decisions.md` | 「采用什么流程」「什么类型/语言」两条初始化决策 |
| `baseline/terms.yaml` | 空表 + 填写说明（刻意留空：第 3 个功能再补最划算） |
| `baseline/assets.md`、`现状地图.md` | 占位符替换；选「已有代码」时给现状地图加扫描提示 |
| `work/CHG-YYYYMMDD-01/问题清单.md` | 阶段 2 问题清单骨架 |
| `init-answers.json` | 本次答案存档，便于复现或改答 |

### 档位自动推导

| 维护方式 | 重要程度 | 档位 | FMEA | 评测集 |
| --- | --- | --- | --- | --- |
| 就我一个 | 任意 | 个人 · 轻量 | Top 5 | 5+3 |
| 小团队 | 试验 / 内部 | 小团队 · 标准 | Top 10 | 10+5+3 |
| 任意 | 对外交付 / 涉钱 | 对外交付 · 严格 | Top 10 | 10+5+3 + 交叉模型审查 |

### 非交互用法

`@bash
aipsw init -y                                   # 全默认（CI / 脚本）
aipsw init --kind web --lang java --team small  # 指定单项
aipsw init --profile strict                     # 直接选严格档
aipsw init --answers answers.json               # 从文件读答案（可复现）
aipsw init --interactive                        # 强制走向导（stdin 不是终端时）
aipsw init --force                              # 覆盖已有 .aiflow，重新问
`@

> 参数优先级：命令行 > `--answers` 文件 > 向导回答 > 内置默认值。
> 非终端环境（被脚本调用）自动用默认值，不会卡在等待输入。

---

## 例子

```bash
# 新项目：先跑初始化向导（直接回车即默认）
python scripts/aipsw.py init --dest . --project "订单系统"

# 全默认（CI 里用）
python scripts/aipsw.py init --dest . -y

# 改一个已有接口：先扫影响面
python scripts/aipsw.py scan impact --symbol OrderService --key "order.page.size" ^
    --out .aiflow/work/CHG-20261109-01/影响面清单.md

# 删一个接口：先扫引用
python scripts/aipsw.py scan delete --symbol legacyGetConnection ^
    --out .aiflow/work/CHG-20261109-01/删除专项检查单.md

# 合并前跑门禁
python scripts/aipsw.py gate all
python scripts/aipsw.py gate dup --new src/main/java/order/OrderExportService.java
```

## 报告

- gate 的结果写到 `<root>/reports/*.json`（默认被 `.gitignore` 忽略）
- 测试用临时目录造正反 fixture，不依赖真实文档：`python -m unittest discover -s tests -v`
- 退出码：`0` 通过（可能有 warning）、`1` 有 error、`2` 用法错误
- 接 CI 时直接看退出码：

```yaml
- name: AIPSW gates
  run: python scripts/aipsw.py gate all
```

## 测试（证明门禁能拦住问题）

```bash
python -m unittest discover -s tests -v
```

- 4 个 gate 都有正例与反例；反例断言退出码为 1 且报告含具体错误码（`T3` / `TOC-1` / `TOC-3` / `S3` / `D-OVERLAP` / `D0`）；
- `init`、`gate all`、`scan impact`、`scan delete` 都有产物断言；
- 测试通过临时目录构造 fixture，跑完不污染仓库。

## 边界（重要）

这些脚本**只做能机械判定的部分**，扫不到的东西必须人工补，别把"工具跑过了"当成"检查过了"：

| 工具做不到 | 必须人工 |
| --- | --- |
| 配置驱动的反射 / SPI 动态引用 | 读框架装配逻辑，人工列清单 |
| 外部调用方（其他仓库、网关） | 查对外契约、网关路由 |
| 数据引用（表字段、缓存 key） | 查 schema 与缓存命名 |
| 语义完整性（需求跑偏 / 遗漏） | 换上下文审查（§3.11） |
| 运行时行为（启动期装配、定时任务） | 起服务验证 |
