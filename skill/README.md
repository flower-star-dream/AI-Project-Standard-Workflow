# skill —— AIPSW 的标准 Agent Skills 封装

> 安装与使用说明已合并到主 README 的 [「Skill 怎么用」](../README.md#skill-怎么用最重要的一节)，这里只留维护信息。

## 结构

```
skill/aipsw/
├── SKILL.md              入口：何时用 → 问题清单 → 判级选模式 → 8 条底线
│                         → 四类动作 → 注入预算 → DMAIC → 脚本 → 路由表 → 反模式 → 自检
├── scripts/aipsw.py      配套 CLI（+ aipsw.cmd / aipsw.ps1 包装）
└── references/
    ├── 01-完整版.md       快照
    ├── 02-精简版.md       快照
    ├── 03-演示文档.md     快照
    ├── 04-地基模板包.md   快照
    └── templates/aiflow/  项目地基骨架
```

## 维护约定

- 四份文档升版后：重新拷贝到 `references/`（文件名保持不带版本号），并更新 `SKILL.md` 末尾版本行；
- `scripts/` 与仓库根目录的 `scripts/` 保持同步；
- `references/templates/aiflow/` 与仓库根目录的 `.aiflow/` 保持同步；
- 版本一致性可用脚本检查：`python scripts/aipsw.py gate toc`（覆盖 README 与文档的链接完整性）。
