# AIPSW · AI 项目开发标准规范工作流程

> **一句话**：让 AI 参与软件交付时，**知道该问什么、该停几次、该查什么、该拿什么证明自己没做错**。
>
> **项目缩写：AIPSW**，全称 **A**I **P**roject **S**tandard **W**orkflow。仓库名、目录名、文档标题、版本记录一律写 `AIPSW`，必要时带版本（如 `AIPSW v1.14`），不另造写法。

---

## 目录

- [这是什么](#这是什么)
- [我该从哪开始](#我该从哪开始)
- [Skill 怎么用（最重要的一节）](#skill-怎么用最重要的一节)
- [命令行怎么用](#命令行怎么用)
- [核心概念（30 秒版）](#核心概念30-秒版)
- [仓库结构](#仓库结构)
- [常见问题](#常见问题)
- [版本](#版本)

---

## 这是什么

一套**能直接用的** AI 协作开发规范：**1 份操作手册 + 4 份文档 + 1 个可执行 CLI + 1 套项目地基模板**。

它要解决的问题很具体——AI 写代码很快，但它会：

- 不问清需求就开工，写完才发现方向错了；
- 改一个地方漏三个地方（**改漏**比写错致命）；
- 删东西时只查静态引用，反射调用漏掉；
- 上下文给错了，它"认真地把事做错"；
- 编造 API、版本号、配置项，而且说得很自信。

AIPSW 把这些拆成**可判定、可留痕、可跑脚本**的动作。核心就三句话：

1. **先判级**——不是所有改动都要走全流程（L0 紧急 / L1 轻量 / L2 标准 / L3 重型）。
2. **按模式做**——生成 / 修改 / 查询 / 删除，四类操作的风险完全不同。
3. **能跑脚本的，别让 AI 判**——术语、契约、重复度、目录覆盖率都有门禁。

---

## 我该从哪开始

| 你是…… | 从这里开始 | 花多久 |
| --- | --- | --- |
| 想先弄懂这套东西 | 读 [02-精简版](02-精简版-v1.4.md) | 10 分钟 |
| **想让 AI 直接按这套规范干活** | 装 [skill](#skill-怎么用最重要的一节) | 3 分钟 |
| 想给自己的项目建地基 | `python scripts/aipsw.py init --dest .` | 1 分钟 |
| 想看完整例子 | [03-演示文档](03-演示文档-v1.3.md)（11 个场景） | 30 分钟 |
| 要查条款 / 判合规 | [01-完整版](01-完整版-v1.14.md)（约 2100 行，**按需切片读**） | 按需 |
| 只想拷模板 | [04-地基模板包](04-地基模板包-v1.4.md) | 按需 |

---

## Skill 怎么用（最重要的一节）

### 它是什么

[skill/aipsw/](skill/aipsw/SKILL.md) 是一份**标准 Agent Skills 封装**——把 2100 行规范压成 agent 能直接执行的 237 行操作手册，后面挂着全套参考资料。

装上之后，你不用再手动翻文档：只要你说的话和"做项目 / 改代码 / 删功能 / 查代码 / 排故障"沾边，agent 会自动加载它，并按规范动作执行。

### 装到 DeepSeek Harness

已经打好包：`dist/aipsw.skill`（zip，22 个文件，含 `scripts/`、`references/` 与地基模板，入口脚本带执行位）。两种装法任选：

```powershell
# 方式 A：装打包产物（给外部使用者）
Expand-Archive .\dist\aipsw.skill -DestinationPath "$env:USERPROFILE\.dsh\skills" -Force

# 方式 B：从源码目录拷
Copy-Item -Recurse -Force ".\skill\aipsw" "$env:USERPROFILE\.dsh\skills\aipsw"
```

Linux / macOS 用 `unzip dist/aipsw.skill -d ~/.dsh/skills`（zip 里已写 0755，解压后 `scripts/aipsw.py` 可直接执行）。

装完先自检入口脚本（应打印 `aipsw tool 1.2.0 (AIPSW v1.14; Python 3.x)`）：

```powershell
python "$env:USERPROFILE\.dsh\skills\aipsw\scripts\aipsw.py" version
```

装完**重启 `dsh web`**（或重新加载宿主）。技能列表里应该出现 `aipsw`。

> 如果你的 `DSH_HOME` 不在 `%USERPROFILE%\.dsh`，把路径换成实际位置。

### 装到其他 Agent Skills 宿主

把 `skill/aipsw/` 整个目录复制到宿主的 skills 目录即可，要求三条：

1. 目录名与 `SKILL.md` 里的 `name: aipsw` 一致；
2. `SKILL.md` 以 YAML frontmatter（`name` + `description`）开头；
3. `references/` 与 `scripts/` 和 `SKILL.md` 同目录，保持相对路径。

### 装好后怎么用

**不需要记命令**，直接说人话。它会按规范走：

| 你说 | 它会做什么 |
| --- | --- |
| 「帮我给订单模块加个导出功能」 | 判级（L2/L3）→ **先建问题清单问阻塞项** → 要你确认主干方案 → 走停点 → 输出影响面与门禁结果 |
| 「把优惠券功能删掉」 | 判为删除专项 → 让你逐条过 D1–D6 → 扫引用（含动态引用）→ 提醒功能级残留（路由/菜单/权限点/数据字段） |
| 「订单模块现在是怎么调支付网关的？」 | 判为只读查询 → 按 S1–S7 分级 → 结论带「级别 + 位置 + 置信」→ 不乱改文件 |
| 「上线后导出超时了」 | 走 §3.12：先 MSA 校准判定标准 → 判趋势 R1/R2/R3 → 5 Whys 挖到可改对象 → 措施优先防错 → 回填 FMEA |
| 「帮我搭个新项目地基」 | 跑 `aipsw init` → 带你填 conventions / terms / fmea / 评测集 |
| 「这次改动算 L 几？要停几次？」 | 按 §1.5 + 停点映射回答 |
| 「拆成几个子 agent 一起做」 | 按 §3.20 派单：权限边界、统一注入、契约版本回报、横向去重、失败收敛 |

**它会主动问你**：需求不清楚时，先出**问题清单**（阻塞 / 可后置 / 建议 三级），只追问阻塞项，其余标"最迟回答节点"。**没有这张表 = 没做过需求确认。**

### 它不会做什么

- ❌ 不替你写业务代码（它是流程约束，不是代码生成器）
- ❌ 不替你做定稿决策（B6 / B7：对外交付与高风险场景必须人定稿）
- ❌ 不假装检查过——脚本扫不到的部分（反射、外部调用方、数据引用、语义完整性），它会明确说"必须人工补"

### Skill 里有什么

```
skill/aipsw/
├── SKILL.md              # 入口：何时用 → 问题清单 → 判级选模式 → 8 条底线
│                         #      → 四类动作 → 注入预算 → DMAIC → 脚本 → 路由表 → 反模式 → 自检
├── scripts/aipsw.py      # 配套 CLI（零依赖 Python 3.8+）
└── references/
    ├── 01-完整版.md       # 权威条款（13 组代号，附录 A–L）—— 按需切片读
    ├── 02-精简版.md       # 300 行日常版
    ├── 03-演示文档.md      # 11 个场景
    ├── 04-地基模板包.md    # 生成/修改/查询/删除 + 问题清单 + 功能级删除清单
    └── templates/aiflow/   # 可直接复制的项目地基骨架
```

---

## 命令行怎么用

只有 Python 3.8+，**没有任何第三方依赖**。Windows 可以用 `scripts/aipsw.cmd` 或 `aipsw.ps1` 包装。

```bash
# 0. 确认运行时版本
python scripts/aipsw.py --version

# 1. 新项目：先跑初始化向导（6 个问题，每题都能直接回车）
python scripts/aipsw.py init --dest D:\my-project

#    不想被问：
#    python scripts/aipsw.py init -y                      # 全默认
#    python scripts/aipsw.py init --lang java --kind web  # 只指定几项

# 2. 改已有代码：先扫影响面（M1），别靠猜
python scripts/aipsw.py scan impact --symbol OrderService --key "order.page.size" \
    --out .aiflow/work/CHG-20261109-01/影响面清单.md

# 3. 删接口 / 删功能：先扫引用（D2）
python scripts/aipsw.py scan delete --symbol legacyGetConnection \
    --out .aiflow/work/CHG-20261109-01/删除专项检查单.md

# 4. 合并前：跑门禁（B4/B5）；给 --new 时 gate all 会加跑 dup
python scripts/aipsw.py gate all
python scripts/aipsw.py gate all --new src/main/java/order/OrderExportService.java
python scripts/aipsw.py gate dup --new src/main/java/order/OrderExportService.java
```

| 命令 | 检查什么 | 对应条款 |
| --- | --- | --- |
| `init` | 交互向导 → 自动填 conventions / fmea / 评测集 / 决策 / 问题清单 | 阶段 0 / §3.18 |
| `gate terms` | 术语重复定义、缺字段、废弃词残留 | §3.9 / B2 |
| `gate toc` | 目录 ↔ 章节锚点/跨文件链接失效、覆盖率 < 90% | 阶段 4 |
| `gate sig` | 契约里声明的接口在代码里找不到 | §3.3 / B3 |
| `gate dup` | 新代码与既有资产重叠 > 10% | 阶段 6 / B5 |
| `gate all --new` | terms / toc / sig 串跑，并加跑 dup | 合并前一次性门禁 |
| `scan impact` | 产出《影响面清单》骨架（调用方/配置/测试） | §3.14.2 M1 |
| `scan delete` | 产出《删除专项检查单》骨架（含动态引用候选） | §3.16 D2 |

门禁结果写到 `reports/*.json`；**退出码 0 = 通过，1 = 有 error**，可直接接 CI：

```yaml
- name: AIPSW gates
  run: python scripts/aipsw.py gate all
```

**测试**（证明门禁真能拦住问题，`tests/` 下正反 fixture）：

```bash
python -m unittest discover -s tests -v
```

详细用法见 [scripts/README.md](scripts/README.md)，测试说明见 [tests/README.md](tests/README.md)。


### 初始化向导（不懂技术也能用）

`init` 默认会问 **6 个问题**，每题都能**直接回车用默认值**：

`@
1) 项目叫什么名字？         [当前目录名]
2) 这是什么类型的项目？     1 网站/后端  2 手机 App  3 桌面/命令行  4 数据/脚本  5 不确定
3) 主要用什么语言？         1 Python  2 JS/TS  3 Java  4 Go  5 C#  6 不确定
4) 谁在维护？               1 就我一个  2 小团队  3 大团队
5) 重要到什么程度？         1 试验  2 内部工具  3 对外交付/涉钱
6) 已经有一堆代码了吗？     y/N
`@

回答完会自动填好这些文件（不用你手写）：

| 文件 | 自动填什么 |
| --- | --- |
| `baseline/conventions.md` | 语言/运行时、格式化与静态检查工具、分层方向、命名约定、错误处理、依赖策略 |
| `baseline/fmea.md` | 按档位生成 Top 5 / Top 10 初始失效模式，S/O/D 已打分 |
| `baseline/evals/cases.yaml` | 5+3 或 10+5+3 条评测用例骨架 |
| `baseline/decisions.md` | 记下「采用什么流程」「什么类型/语言」两条决策 |
| `baseline/terms.yaml` | 空表 + 填写说明（第 3 个功能再补最划算） |
| `work/CHG-…/问题清单.md` | 阶段 2 的问题清单骨架 |

**档位自动推导**（第 4、5 题决定）：

| 维护方式 | 重要程度 | 档位 | 影响 |
| --- | --- | --- | --- |
| 就我一个 | 任意 | 个人 · 轻量 | FMEA Top 5、评测集 5+3、三个自查停点 |
| 小团队 | 试验 / 内部 | 小团队 · 标准 | FMEA Top 10、10+5+3、8 个卡点 |
| 任意 | 对外交付 / 涉钱 | 对外交付 · 严格 | Top 10、10+5+3、8 卡点 + 交叉模型审查 |

三种跳过提问的方式：

`@bash
python scripts/aipsw.py init -y                      # 全默认，适合 CI / 脚本
python scripts/aipsw.py init --lang java --kind web  # 只指定关心的几项
python scripts/aipsw.py init --profile strict        # 直接选严格档
`@

> 答案存在 `.aiflow/init-answers.json`，想改重新跑 `init --force`。

---

## 核心概念（30 秒版）

**四个级别**（§1.5）——决定走多少流程：

| 级别 | 判定 | 停点 |
| --- | --- | --- |
| L1 轻量 | 单文件 / ≤50 行 / 不动接口 | 合并前自查 + 24h 补录 |
| L2 标准 | 多文件单模块 / 内部接口变更 | 停点 1、3（并行或需回滚加 2） |
| L3 重型 | 跨模块 / 对外接口 / **引入新依赖** / 合规 | 停点 1、2、3 |
| L0 紧急 | 生产故障 / 安全事件 | 先修后补，24h 内记录 |

**四类操作**（§3.15）——决定做什么动作：

```
要改变系统状态吗？
├─ 否 → 查询（只读，S1–S7 分级）
└─ 是 → 要移除对象吗？
    ├─ 是 → 删除专项（修改 + D1–D6）
    └─ 否 → 对象已存在吗？
        ├─ 是 → 修改（M1–M7 变更安全）
        └─ 否 → 生成（预设约定 + 范例锚定）
```

**三个停点** = 卡点的合并视图：停点 1（设计定稿前）= 卡点 1+4；停点 2（写代码前）= 卡点 5；停点 3（合并前）= 卡点 6。

**八条底线**（§1.7，任何情况都不能砍）：B1 事实有来源 · B2 单一事实源 · B3 契约先冻结带版本 · B4 工具优先于 AI 判 · B5 合并前查引用与重复 · B6 未验证不交付 · B7 高风险人定稿 · B8 紧急 24h 补记录。

---

## 仓库结构

| 路径 | 是什么 | 什么时候看 |
| --- | --- | --- |
| [01-完整版-v1.14.md](01-完整版-v1.14.md) | 权威条款（约 2100 行，附录 A–L） | 查条款、判合规、追溯 |
| [02-精简版-v1.4.md](02-精简版-v1.4.md) | 300 行日常版 | 开工前、执行中 |
| [03-演示文档-v1.3.md](03-演示文档-v1.3.md) | 11 个场景的完整例子 | 上手、培训 |
| [04-地基模板包-v1.4.md](04-地基模板包-v1.4.md) | 四套模板 + 问题清单 + 功能级删除清单 | 建地基、开工填表 |
| [.aiflow/](.aiflow/README.md) | 可直接复制到项目根的工作流空间骨架 | 长期 |
| [skill/aipsw/](skill/aipsw/SKILL.md) | 标准 Agent Skills 封装 | 装给 agent 用 |
| [scripts/](scripts/README.md) | 配套 CLI | 跑门禁与扫描 |
| [tests/](tests/README.md) | CLI 正反例回归测试 | 改 CLI 后先跑 |
| [docs/可执行度评估.md](docs/可执行度评估.md) | 规范条款 → CLI 能力对照与缺口分级 | 评审落地范围 |

四份文档的关系：**完整版**面向 AI（追求可判定，示例集中在附录 L）→ **精简版**面向人（不得与完整版偏差）→ **演示文档**是条款↔场景对照 → **模板包**是可直接抄的骨架。

---

## 常见问题

**Q：我没有 `.aiflow`，能用这套东西吗？**
能，但效果打折。规范假设有地基（约定/术语/契约/FMEA）；没有地基时，AI 只能按自己的默认风格写。先跑一句 `aipsw init` 补最简版即可。

**Q：一定要用 Python 吗？**
只有脚本需要。纯文档 / skill 用法不需要装任何东西。

**Q：单人项目也要走这么多流程？**
不用。附录 E 有个人模式：8 个卡点压成 3 个自查停点、FMEA Top 5、评测集 5+3——**但 8 条底线不减免**。

**Q：和我们公司现有流程冲突怎么办？**
底线（§1.7）强制，其余可设过渡期；外部法规/制度优先并记录覆盖关系（MR1 / MR4）。

**Q：为什么有些条款写得这么"硬"？**
因为软约束会被绕过。每条硬要求都配了"最小执行方式"，做不到时要求**书面声明「本规范不适用」**——不允许沉默跳过。

---

## 版本

- **AIPSW 资料包 v1.14**：完整版 v1.14 ｜ 精简版 v1.4 ｜ 演示 v1.3 ｜ 模板包 v1.4 ｜ CLI 1.2.0
- 逐版变更见完整版[附录 F（版本简史）](01-完整版-v1.14.md#附录-f版本简史)
- v1.13：配套 CLI（init / 4 门禁 / 2 扫描）、问题清单与功能级删除清单模板、20 条正反例测试；README 重写
- v1.14：**init 交互向导 + 模板自动填充**（6 个问题、档位推导、默认方案）；规范补 §3.22 需求变更、附录 C.3 FMEA 打分锚点、§3.19.2 预算分母；CLI 1.2.0
