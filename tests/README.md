# tests —— CLI 正反例回归测试

零第三方依赖（只用标准库 `unittest`），验证 `scripts/aipsw.py` 的门禁是否真的能拦住问题。

## 运行

```bash
python -m unittest discover -s tests -v
```

预期：25 条测试全部通过，退出码 0。

## 覆盖范围

| 测试组 | 正例 | 反例（断言退出码 1 + 具体错误码） |
| --- | --- | --- |
| init | 生成 `.aiflow/`、占位符替换、问题清单、对脚手架跑 `gate all` | 重复 init 未加 `--force` → 退出码 2 |
| init 向导 | `--answers` 预置答案、`-y` 默认档（Top 5 / 5+3）、`--profile strict`（Top 10 / 10+5+3）、`--interactive` 全回车 | — |
| terms | 干净术语表通过、报告落盘 | 正文出现 `status: deprecated` 术语 → `T3` |
| toc | 小文档不误报覆盖率、跨文件锚点有效 | 锚点失效 → `TOC-1`；文件/跨文件锚点缺失 → `TOC-3` |
| sig | 契约接口在代码中找到同名实现 | 契约有接口、代码无实现 → `S3` |
| dup | 唯一新文件通过 | 复制文件重叠 100% → `D-OVERLAP`；缺 `--new` → `D0` |
| scan | impact 产出调用方/配置/测试三节；delete 产出静态/动态/配置/文档四节 | — |
| gate all | 不给 `--new` 时 `dup=SKIP`；给 `--new` 时四门禁串跑 | — |

## fixture 策略

每个测试用 `tempfile.TemporaryDirectory()` 临时造一个最小仓库（`.aiflow/baseline/`、源码、配置、文档），跑完自动删除；不把测试文档放进真实仓库，避免污染 `gate terms` / `gate toc` 的扫描结果。

Windows 沙箱可能拒绝 `subprocess.PIPE`（WinError 5），测试辅助函数改用临时文件重定向收集 stdout/stderr，普通环境同样适用。

## 相关

- CLI 用法：[scripts/README.md](../scripts/README.md)
- 规范入口：[README.md](../README.md)
