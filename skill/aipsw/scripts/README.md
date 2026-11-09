# scripts —— AIPSW 配套命令行

零第三方依赖，只需要 Python 3.8+（Windows 用 `aipsw.cmd` 或 `aipsw.ps1` 包装）。

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
| `aipsw init` | 把 `.aiflow` 骨架装进项目，填占位符，生成第一份问题清单 | 阶段 0 / §3.18 |
| `aipsw gate terms` | 术语单一事实源检查（重复定义、缺字段、废弃词残留） | §3.9 / B2 |
| `aipsw gate toc` | 目录 ↔ 章节覆盖率（锚点失效即 error） | 阶段 4 可机械化项 |
| `aipsw gate sig` | 契约 ↔ 代码签名比对（契约有、代码无 → error） | §3.3 / B3 |
| `aipsw gate dup` | 新代码与既有资产重复度（默认阈值 10%） | 阶段 6 / B5 |
| `aipsw gate all` | 依次跑 terms / toc / sig | 合并前门禁 |
| `aipsw scan impact` | 影响面扫描，产出《影响面清单》骨架 | §3.14.2 M1 |
| `aipsw scan delete` | 引用穷尽扫描，产出《删除专项检查单》骨架 | §3.16 D2 |

## 例子

```bash
# 新项目：先把地基装上
python scripts/aipsw.py init --dest . --project "订单系统" --owner 张三

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
- 退出码：`0` 通过（可能有 warning）、`1` 有 error、`2` 用法错误
- 接 CI 时直接看退出码：

```yaml
- name: AIPSW gates
  run: python scripts/aipsw.py gate all
```

## 边界（重要）

这些脚本**只做能机械判定的部分**，扫不到的东西必须人工补，别把"工具跑过了"当成"检查过了"：

| 工具做不到 | 必须人工 |
| --- | --- |
| 配置驱动的反射 / SPI 动态引用 | 读框架装配逻辑，人工列清单 |
| 外部调用方（其他仓库、网关） | 查对外契约、网关路由 |
| 数据引用（表字段、缓存 key） | 查 schema 与缓存命名 |
| 语义完整性（需求跑偏 / 遗漏） | 换上下文审查（§3.11） |
| 运行时行为（启动期装配、定时任务） | 起服务验证 |
