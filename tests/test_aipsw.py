#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIPSW CLI 回归测试（零第三方依赖）。

运行（仓库根目录）:
    python -m unittest discover -s tests -v

覆盖:
    init 脚手架
    gate terms / toc / sig / dup 的正例与反例（断言退出码 + 报告错误码）
    scan impact / delete 的产物结构
    --version / --help / gate all
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "aipsw.py"


def run_cli(root, *args, timeout=60):
    """执行 CLI。

    用临时文件而不是 subprocess.PIPE 收集输出：部分 Windows 沙箱会拒绝
    CreatePipe（WinError 5），文件重定向在普通环境与受限环境都能工作。
    """
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.run(
            [sys.executable, str(CLI), "--root", str(root), *args],
            cwd=str(ROOT),
            stdout=out,
            stderr=err,
            timeout=timeout,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(
            proc.args,
            proc.returncode,
            out.read().decode("utf-8", "replace"),
            err.read().decode("utf-8", "replace"),
        )


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_report(root, name):
    path = Path(root) / "reports" / name
    if not path.exists():
        raise AssertionError("报告未落盘: %s" % path)
    return json.loads(path.read_text(encoding="utf-8"))


def error_checks(data):
    return [item["check"] for item in data["errors"]]


TERMS_OK = """meta:
  version: v0.1
terms:
  order:
    zh: 订单
    definition: 交易单据
    status: confirmed
    authority: B
"""

TERMS_WITH_DEPRECATED = """meta:
  version: v0.1
terms:
  order:
    zh: 订单
    definition: 交易单据
    status: confirmed
    authority: B
  legacy_gateway:
    zh: 旧网关
    definition: 已下线的网关
    status: deprecated
    authority: B
"""

CONTRACT_BAD = """contract: order
version: v1.0
status: frozen
endpoints:
  - name: createOrder
    input:
      sku: string
"""

CODE_WITHOUT_IMPL = """class OrderService:
    def create_order(self, sku):
        return sku
"""

CODE_WITH_IMPL = """class OrderService:
    def createOrder(self, sku):
        return sku
"""


def make_code(prefix, offset=0):
    lines = []
    for i in range(40):
        lines.append("def %s_%02d(alpha, beta):" % (prefix, i))
        lines.append("    return alpha + beta + %d" % (i + offset))
    return "\n".join(lines) + "\n"


class TestCliSurface(unittest.TestCase):
    def test_version_flag_reports_runtime(self):
        proc = run_cli(ROOT, "--version")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("aipsw tool 1.2.0", proc.stdout)
        self.assertIn("Python", proc.stdout)

    def test_help_lists_all_subcommands(self):
        top = run_cli(ROOT, "--help")
        self.assertEqual(top.returncode, 0, top.stderr + top.stdout)
        for word in ("init", "gate", "scan", "version"):
            self.assertIn(word, top.stdout)

        gate = run_cli(ROOT, "gate", "--help")
        self.assertEqual(gate.returncode, 0, gate.stderr + gate.stdout)
        for word in ("terms", "toc", "sig", "dup", "all"):
            self.assertIn(word, gate.stdout)

        scan = run_cli(ROOT, "scan", "--help")
        self.assertEqual(scan.returncode, 0, scan.stderr + scan.stdout)
        for word in ("impact", "delete"):
            self.assertIn(word, scan.stdout)

    def test_version_subcommand(self):
        proc = run_cli(ROOT, "version")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("aipsw tool 1.2.0", proc.stdout)


class TestInit(unittest.TestCase):
    def test_init_creates_scaffold_and_question_sheet(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "demo"
            dest.mkdir()
            proc = run_cli(
                ROOT, "init", "--dest", str(dest),
                "--templates", str(ROOT / ".aiflow"),
                "--project", "示例项目", "--owner", "张三",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            terms = dest / ".aiflow" / "baseline" / "terms.yaml"
            self.assertTrue(terms.exists(), "terms.yaml 未生成")
            conventions = (dest / ".aiflow" / "baseline" / "conventions.md").read_text(encoding="utf-8")
            self.assertIn("示例项目", conventions)
            sheets = list((dest / ".aiflow" / "work").glob("CHG-*/问题清单.md"))
            self.assertEqual(len(sheets), 1, "问题清单未生成")

            gate = run_cli(dest, "gate", "all")
            self.assertEqual(gate.returncode, 0, gate.stderr + gate.stdout)
            self.assertTrue((dest / "reports" / "term_check.json").exists())

    def test_init_refuses_existing_aiflow_without_force(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "demo"
            dest.mkdir()
            args = ("init", "--dest", str(dest), "--templates", str(ROOT / ".aiflow"))
            self.assertEqual(run_cli(ROOT, *args).returncode, 0)
            second = run_cli(ROOT, *args)
            self.assertEqual(second.returncode, 2, second.stderr + second.stdout)
            self.assertIn("--force", second.stderr)


class TestTermsGate(unittest.TestCase):
    def test_deprecated_term_in_doc_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / ".aiflow" / "baseline" / "terms.yaml", TERMS_WITH_DEPRECATED)
            write(root / "doc.md", "# 文档\n\n旧网关仍在使用。\n\n订单是核心对象。\n")
            proc = run_cli(root, "gate", "terms")
            self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
            data = read_report(root, "term_check.json")
            self.assertEqual(data["status"], "fail")
            self.assertIn("T3", error_checks(data))

    def test_clean_terms_pass_and_report_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / ".aiflow" / "baseline" / "terms.yaml", TERMS_OK)
            write(root / "doc.md", "# 文档\n\n订单是核心对象。\n")
            proc = run_cli(root, "gate", "terms")
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            data = read_report(root, "term_check.json")
            self.assertEqual(data["status"], "pass")
            self.assertEqual(data["errors"], [])


class TestTocGate(unittest.TestCase):
    def test_broken_anchor_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / "doc.md", """# 文档

## 目录

- [存在](#存在)
- [不存在](#不存在)

## 存在
正文

## 二
x

## 三
x

## 四
x

## 五
x
""")
            proc = run_cli(root, "gate", "toc")
            self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
            data = read_report(root, "toc_check.json")
            self.assertIn("TOC-1", error_checks(data))

    def test_small_doc_skips_coverage_but_checks_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / "doc.md", """# 文档

- [一](#一)

## 一
x
## 二
x
## 三
x
## 四
x
## 五
x
""")
            proc = run_cli(root, "gate", "toc")
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            data = read_report(root, "toc_check.json")
            self.assertEqual(data["status"], "pass")
            self.assertNotIn("TOC-2", [w["check"] for w in data["warnings"]])

    def test_cross_file_missing_target_and_anchor_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / "other.md", "# 另一个\n\n## 存在\n")
            write(root / "doc.md", "# 文档\n\n[other](other.md#不存在)\n[missing](missing.md)\n")
            proc = run_cli(root, "gate", "toc")
            self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
            data = read_report(root, "toc_check.json")
            self.assertGreaterEqual(error_checks(data).count("TOC-3"), 2)

    def test_cross_file_valid_anchor_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / "other.md", "# 另一个\n\n## 存在\n")
            write(root / "doc.md", "# 文档\n\n[other](other.md#存在)\n")
            proc = run_cli(root, "gate", "toc")
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertEqual(read_report(root, "toc_check.json")["status"], "pass")


class TestSigGate(unittest.TestCase):
    def test_contract_endpoint_without_implementation_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / ".aiflow" / "baseline" / "contracts" / "order.yaml", CONTRACT_BAD)
            write(root / "src" / "order.py", CODE_WITHOUT_IMPL)
            proc = run_cli(root, "gate", "sig")
            self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
            data = read_report(root, "sig_check.json")
            self.assertIn("S3", error_checks(data))

    def test_contract_and_implementation_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / ".aiflow" / "baseline" / "contracts" / "order.yaml", CONTRACT_BAD)
            write(root / "src" / "order.py", CODE_WITH_IMPL)
            proc = run_cli(root, "gate", "sig")
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            data = read_report(root, "sig_check.json")
            self.assertEqual(data["status"], "pass")
            self.assertEqual(data["errors"], [])


class TestDupGate(unittest.TestCase):
    def test_copied_file_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / "src" / "base.py", make_code("base"))
            write(root / "src" / "copy.py", make_code("base"))
            proc = run_cli(root, "gate", "dup", "--new", "src/copy.py")
            self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
            data = read_report(root, "dup_check.json")
            self.assertIn("D-OVERLAP", error_checks(data))

    def test_unique_file_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / "src" / "base.py", make_code("base"))
            write(root / "src" / "fresh.py", make_code("fresh", 1000))
            proc = run_cli(root, "gate", "dup", "--new", "src/fresh.py")
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertEqual(read_report(root, "dup_check.json")["status"], "pass")

    def test_missing_new_argument_is_usage_error(self):
        with tempfile.TemporaryDirectory() as td:
            proc = run_cli(Path(td), "gate", "dup")
            self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
            self.assertIn("D0", error_checks(read_report(Path(td), "dup_check.json")))


class TestScanCommands(unittest.TestCase):
    def test_impact_scan_writes_required_sections(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / "src" / "order.py", "class OrderService:\n    pass\n")
            write(root / "config" / "app.yml", "page_size: 20\n")
            write(root / "tests" / "test_order.py", "OrderService = None\n")
            write(root / "doc.md", "# 说明\n\nOrderService 在这里。\n")
            proc = run_cli(
                root, "scan", "impact", "--symbol", "OrderService",
                "--key", "page_size", "--out", ".aiflow/work/CHG-1/impact.md",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            out = (root / ".aiflow" / "work" / "CHG-1" / "impact.md").read_text(encoding="utf-8")
            self.assertIn("## 1. 调用方", out)
            self.assertIn("src/order.py:1", out)
            self.assertIn("## 2. 配置读取点", out)
            self.assertIn("config/app.yml:1", out)
            self.assertIn("## 3. 现有测试", out)
            self.assertIn("tests/test_order.py:1", out)

    def test_delete_scan_finds_static_and_dynamic_refs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / "src" / "legacy.py", "def legacyThing():\n    return 1\n")
            write(root / "src" / "registry.py", 'name = "legacyThing"\nClass.forName(name)\n')
            write(root / "tests" / "test_legacy.py", "legacyThing\n")
            write(root / "config" / "app.yml", "legacyThing: true\n")
            write(root / "doc.md", "# 文档\n\nlegacyThing\n")
            proc = run_cli(
                root, "scan", "delete", "--symbol", "legacyThing",
                "--out", ".aiflow/work/CHG-1/delete.md",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            out = (root / ".aiflow" / "work" / "CHG-1" / "delete.md").read_text(encoding="utf-8")
            for section in ("## ① 静态引用", "## ② 动态引用", "## ③ 配置文件", "## ④ 文档 / 示例"):
                self.assertIn(section, out)
            self.assertIn("src/registry.py:1", out)
            self.assertIn("动态候选：1 处", out)


class TestGateAll(unittest.TestCase):
    def test_all_runs_three_gates_and_skips_dup_without_new(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / ".aiflow" / "baseline" / "terms.yaml", TERMS_OK)
            proc = run_cli(root, "gate", "all")
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn("dup=SKIP", proc.stdout)
            for name in ("term_check.json", "toc_check.json", "sig_check.json"):
                self.assertTrue((root / "reports" / name).exists())

    def test_all_runs_dup_when_new_is_given(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / ".aiflow" / "baseline" / "terms.yaml", TERMS_OK)
            write(root / "src" / "base.py", make_code("base"))
            write(root / "src" / "fresh.py", make_code("fresh", 1000))
            proc = run_cli(root, "gate", "all", "--new", "src/fresh.py")
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn("dup=PASS", proc.stdout)
            self.assertTrue((root / "reports" / "dup_check.json").exists())



class TestInitWizard(unittest.TestCase):
    """init 的交互向导 / 预置答案 / 档位推导（v1.14）。"""

    def _run_init(self, td, *args):
        dest = Path(td) / "demo"
        dest.mkdir()
        proc = run_cli(ROOT, "init", "--dest", str(dest),
                       "--templates", str(ROOT / ".aiflow"), *args)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return dest

    @staticmethod
    def _fmea_rows(dest):
        text = (dest / ".aiflow" / "baseline" / "fmea.md").read_text(encoding="utf-8")
        return [l for l in text.splitlines() if l.startswith("| ") and l.split("|")[1].strip().isdigit()]

    def test_answers_file_uses_language_and_kind(self):
        with tempfile.TemporaryDirectory() as td:
            answers = Path(td) / "a.json"
            answers.write_text(json.dumps({
                "kind": "web", "lang": "java", "team": "small",
                "criticality": "internal", "project": "订单系统",
            }, ensure_ascii=False), encoding="utf-8")
            dest = self._run_init(td, "--answers", str(answers))
            conv = (dest / ".aiflow" / "baseline" / "conventions.md").read_text(encoding="utf-8")
            self.assertIn("google-java-format", conv)
            self.assertIn("接口 / 路由层", conv)
            self.assertIn("订单系统", conv)
            # 小团队 -> Top 10
            self.assertEqual(len(self._fmea_rows(dest)), 10)

    def test_default_profile_is_solo_top5(self):
        with tempfile.TemporaryDirectory() as td:
            dest = self._run_init(td, "-y", "--project", "默认项目")
            self.assertEqual(len(self._fmea_rows(dest)), 5)
            evals = (dest / ".aiflow" / "baseline" / "evals" / "cases.yaml").read_text(encoding="utf-8")
            self.assertEqual(evals.count("  - id: TC-"), 5)
            self.assertEqual(evals.count("  - id: BAD-"), 3)

    def test_strict_profile_has_ten_and_five(self):
        with tempfile.TemporaryDirectory() as td:
            dest = self._run_init(td, "--profile", "strict", "--project", "对外项目")
            self.assertEqual(len(self._fmea_rows(dest)), 10)
            evals = (dest / ".aiflow" / "baseline" / "evals" / "cases.yaml").read_text(encoding="utf-8")
            self.assertEqual(evals.count("  - id: TC-"), 10)
            self.assertEqual(evals.count("  - id: BAD-"), 5)
            decisions = (dest / ".aiflow" / "baseline" / "decisions.md").read_text(encoding="utf-8")
            self.assertIn("严格", decisions)

    def test_answers_json_is_written_and_reusable(self):
        with tempfile.TemporaryDirectory() as td:
            dest = self._run_init(td, "--kind", "cli", "--lang", "python", "-y")
            saved = dest / ".aiflow" / "init-answers.json"
            self.assertTrue(saved.exists(), "init-answers.json 未生成")
            data = json.loads(saved.read_text(encoding="utf-8"))
            self.assertEqual(data["kind"], "cli")
            self.assertEqual(data["lang"], "python")
            self.assertIn("profile", data)

    def test_wizard_prompts_accept_enter_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "demo"
            dest.mkdir()
            # 六个问题全部回车 = 默认值
            proc = subprocess.run(
                [sys.executable, str(CLI), "--root", str(ROOT), "init",
                 "--dest", str(dest), "--templates", str(ROOT / ".aiflow"), "--interactive"],
                cwd=str(ROOT), input="\n\n\n\n\n\n",
                capture_output=True, encoding="utf-8", errors="replace", timeout=60,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn("初始化向导", proc.stdout)
            self.assertTrue((dest / ".aiflow" / "baseline" / "conventions.md").exists())
            self.assertTrue((dest / ".aiflow" / "init-answers.json").exists())


if __name__ == "__main__":
    unittest.main()
