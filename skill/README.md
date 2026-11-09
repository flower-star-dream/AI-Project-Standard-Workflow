# skill —— 把 AIPSW 装成可调用的 Skill

本目录是 AIPSW 的**标准 Agent Skills 封装**（`SKILL.md` + `references/`），可直接被支持 Agent Skills 的宿主加载。

```
skill/aipsw/
├── SKILL.md               # 入口：路由说明 + 60 秒流程 + 8 条底线 + 反模式 + 自检
└── references/
    ├── README.md          # 快照版本与读取建议
    ├── 01-完整版.md        # 完整条款（按需切片读，不要通读）
    ├── 02-精简版.md        # 10 分钟上手
    ├── 03-演示文档.md      # 11 个场景
    ├── 04-地基模板包.md    # 四套模板
    └── templates/
        └── aiflow/        # 可直接复制到项目根的 .aiflow 骨架
```

## 安装（DeepSeek Harness）

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.dsh\skills" | Out-Null
Copy-Item -Recurse -Force ".\skill\aipsw" "$env:USERPROFILE\.dsh\skills\aipsw"
```

然后重启 `dsh web`（或重新加载宿主），技能列表里应出现 `aipsw`。

> 若你的 `DSH_HOME` 不在 `%USERPROFILE%\.dsh`，把上面的路径换成实际的 `<DSH_HOME>\skills`。

## 安装（其他 Agent Skills 宿主）

把 `skill/aipsw/` 整个目录复制到宿主的 skills 目录即可。要求：

- 目录名与 `SKILL.md` 里的 `name: aipsw` 一致；
- `SKILL.md` 以 YAML frontmatter（`name` + `description`）开头；
- `references/` 与 `SKILL.md` 同目录，保持相对路径。

## 触发方式

`description` 已包含中英双语触发词。典型触发：

- 「按 AIPSW 规范做」「这次改动算 L 几」「要停几次」
- 「变更安全 / 影响面 / 回归基线」「删除专项」「只读审计」
- 「上下文怎么给」「FMEA / DMAIC / 复盘」「帮我把项目地基搭起来」

## 维护

- 四份文档升版后，重新拷贝 `references/01–04` 并更新 `SKILL.md` 末尾的版本行；
- `references/templates/aiflow/` 与仓库根目录的 `.aiflow/` 保持同步。
