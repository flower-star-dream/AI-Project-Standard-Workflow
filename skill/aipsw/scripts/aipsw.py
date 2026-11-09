#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIPSW 配套命令行工具（零第三方依赖，Python 3.8+）

AIPSW = AI Project Standard Workflow（AI 项目开发标准规范工作流程）

子命令:
  init            把 .aiflow 骨架装进目标项目，并填掉占位符
  gate terms      术语单一事实源检查（T1-T4）
  gate toc        目录 <-> 章节覆盖率检查
  gate sig        接口契约 <-> 代码签名检查
  gate dup        新代码与既有资产的重复度检查
  gate all        依次执行 terms / toc / sig
  scan impact     修改类 M1：影响面扫描，产出《影响面清单》骨架
  scan delete     删除专项 D2：引用穷尽扫描，产出《删除专项检查单》骨架
  version

约定:
  - 报告写到 <root>/reports/*.json
  - .aiflow/archive 属于"物理隔离区"，任何扫描都会跳过它（规范 3.18.2）
  - 退出码: 0 = 通过（可能带 warning）；1 = 有 error；2 = 用法错误
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date

TOOL_VERSION = "1.0.0"
AIPSW_VERSION = "v1.13"

FENCE = chr(96) * 3

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", "out", ".idea", ".vscode", ".mypy_cache",
    ".pytest_cache", "reports", ".aiflow/archive",
}
CODE_EXT = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".kt", ".kts",
    ".go", ".rs", ".cs", ".cpp", ".cc", ".c", ".h", ".hpp", ".rb", ".php",
    ".swift", ".scala", ".lua", ".sh", ".bash", ".ps1", ".sql", ".vue", ".svelte",
}
CONFIG_EXT = {
    ".yml", ".yaml", ".json", ".toml", ".ini", ".properties", ".conf", ".cfg",
    ".env", ".envrc", ".xml", ".gradle",
}
DOC_EXT = {".md", ".markdown", ".rst", ".txt", ".adoc"}
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec)(/|$)|(_test|\.test|\.spec|Test)\.", re.I)

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SCAN_FILES = 20000


def die(msg, code=2):
    print("错误: " + msg, file=sys.stderr)
    sys.exit(code)


def iter_files(root, exts=None, skip_archive=True):
    """遍历文件，跳过 SKIP_DIRS 与 .aiflow/archive。"""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""
        keep = []
        for d in dirnames:
            joined = (rel_dir + "/" + d) if rel_dir else d
            if d in SKIP_DIRS or joined in SKIP_DIRS:
                continue
            if skip_archive and d == "archive" and ".aiflow" in joined:
                continue
            keep.append(d)
        dirnames[:] = sorted(keep)
        for fn in sorted(filenames):
            if exts is not None:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in exts:
                    continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if skip_archive and rel.startswith(".aiflow/archive/"):
                continue
            try:
                if os.path.getsize(p) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            n += 1
            if n > MAX_SCAN_FILES:
                return
            yield rel, p


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


class Report:
    def __init__(self, name):
        self.name = name
        self.errors = []
        self.warnings = []
        self.info = []

    def err(self, check, msg, loc=""):
        self.errors.append({"check": check, "message": msg, "location": loc})

    def warn(self, check, msg, loc=""):
        self.warnings.append({"check": check, "message": msg, "location": loc})

    def note(self, msg):
        self.info.append(msg)

    @property
    def ok(self):
        return not self.errors

    def as_dict(self):
        return {
            "tool": "aipsw",
            "tool_version": TOOL_VERSION,
            "aipsw_version": AIPSW_VERSION,
            "check": self.name,
            "status": "pass" if self.ok else "fail",
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
        }

    def print_summary(self, json_path=None):
        tag = "通过" if self.ok else "不通过"
        print("[%s] %s — error %d / warning %d" % (
            tag, self.name, len(self.errors), len(self.warnings)))
        for e in self.errors:
            loc = (" @ " + e["location"]) if e["location"] else ""
            print("  ERROR   [%s] %s%s" % (e["check"], e["message"], loc))
        for w in self.warnings:
            loc = (" @ " + w["location"]) if w["location"] else ""
            print("  WARN    [%s] %s%s" % (w["check"], w["message"], loc))
        for i in self.info:
            print("  · " + i)
        if json_path:
            print("  报告: " + json_path)


def md_lines_outside_fence(text):
    """产出 (行号, 行内容)，跳过围栏代码块内的行。"""
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(FENCE):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield i, line


def gh_slug(title):
    """GitHub 风格锚点：小写、去标点、空格转连字符（CJK 保留）。"""
    s = title.strip().lower()
    s = "".join(ch for ch in s if ch.isalnum() or ch.isspace() or ch in "_-")
    return re.sub(r"\s", "-", s)


def build_anchor_map(text):
    titles = []
    for _, line in md_lines_outside_fence(text):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            titles.append((m.group(2), len(m.group(1))))
    seen = {}
    anchors = set()
    for t, _lvl in titles:
        s = gh_slug(t)
        n = seen.get(s, 0)
        seen[s] = n + 1
        anchors.add(s if n == 0 else "%s-%d" % (s, n))
    return anchors, titles


def parse_md_toc(text):
    items = []
    for ln, line in md_lines_outside_fence(text):
        for m in re.finditer(r"\]\(#([^)]+)\)", line):
            items.append((ln, m.group(1)))
    return items


# ---------------------------------------------------------------- 极简 YAML

def _strip_comment(s):
    res = []
    quote = None
    for i, ch in enumerate(s):
        if quote:
            res.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            res.append(ch)
        elif ch == "#" and (i == 0 or s[i - 1].isspace()):
            break
        else:
            res.append(ch)
    return "".join(res).rstrip()


def _scalar(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [] if not inner else [_scalar(x) for x in inner.split(",")]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v.lower() in ("null", "~", ""):
        return None
    return v


class YamlMini:
    """够用于 .aiflow 模板的 YAML 子集：嵌套映射、列表、行内列表、块标量。"""

    def __init__(self, text):
        self.sig = []
        self.errors = []
        self.dups = []
        for ln, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            body = _strip_comment(raw)
            if not body.strip():
                continue
            indent = len(body) - len(body.lstrip(" "))
            self.sig.append((indent, body.strip(), ln))

    def parse(self):
        if not self.sig:
            return {}
        val, idx = self._parse_block(0, self.sig[0][0])
        if idx < len(self.sig):
            self.errors.append("第 %d 行缩进异常，无法解析" % self.sig[idx][2])
        return val if val is not None else {}

    def _parse_block(self, idx, indent):
        if self.sig[idx][1].startswith("- "):
            return self._parse_seq(idx, indent)
        return self._parse_map(idx, indent)

    def _parse_map(self, idx, indent):
        d = {}
        while idx < len(self.sig):
            ind, txt, ln = self.sig[idx]
            if ind < indent:
                break
            if ind > indent:
                self.errors.append("第 %d 行多余缩进" % ln)
                idx += 1
                continue
            if txt.startswith("- "):
                break
            if ":" not in txt:
                self.errors.append("第 %d 行不是 key: value 形式 -> %s" % (ln, txt[:40]))
                idx += 1
                continue
            key, _, val = txt.partition(":")
            key = key.strip()
            if key in d:
                self.dups.append("%s（第 %d 行）" % (key, ln))
            val = _strip_comment(val).strip()
            idx += 1
            if val == "":
                if idx < len(self.sig) and self.sig[idx][0] > ind:
                    d[key], idx = self._parse_block(idx, self.sig[idx][0])
                elif idx < len(self.sig) and self.sig[idx][0] == ind and self.sig[idx][1].startswith("- "):
                    d[key], idx = self._parse_seq(idx, ind)
                else:
                    d[key] = None
            elif val in ("|", ">", "|-", ">-", "|+", ">+"):
                block = []
                while idx < len(self.sig) and self.sig[idx][0] > ind:
                    block.append(self.sig[idx][1])
                    idx += 1
                d[key] = "\n".join(block)
            else:
                d[key] = _scalar(val)
        return d, idx

    def _parse_seq(self, idx, indent):
        arr = []
        while idx < len(self.sig):
            ind, txt, ln = self.sig[idx]
            if ind != indent or not txt.startswith("- "):
                break
            rest = txt[2:].strip()
            idx += 1
            if rest == "":
                if idx < len(self.sig) and self.sig[idx][0] > ind:
                    v, idx = self._parse_block(idx, self.sig[idx][0])
                    arr.append(v)
                else:
                    arr.append(None)
            elif ":" in rest and not rest.startswith("["):
                key, _, val = rest.partition(":")
                item = {}
                key = key.strip()
                val = _strip_comment(val).strip()
                if val == "":
                    if idx < len(self.sig) and self.sig[idx][0] > ind:
                        item[key], idx = self._parse_block(idx, self.sig[idx][0])
                    else:
                        item[key] = None
                else:
                    item[key] = _scalar(val)
                while idx < len(self.sig) and self.sig[idx][0] > ind and not self.sig[idx][1].startswith("- "):
                    more, idx = self._parse_map(idx, self.sig[idx][0])
                    if isinstance(more, dict):
                        item.update(more)
                    else:
                        break
                arr.append(item)
            else:
                arr.append(_scalar(rest))
        return arr, idx


def parse_yaml_file(path):
    mini = YamlMini(read_text(path))
    data = mini.parse()
    return data, mini.errors, mini.dups


def is_placeholder(v):
    if v is None:
        return True
    s = str(v).strip()
    if not s:
        return True
    if s.startswith("<") or s.startswith("（") or s.startswith("("):
        return True
    return False


def finish(rep, root, json_name, args, quiet=False):
    json_path = os.path.join(root, "reports", json_name)
    try:
        write_json(json_path, rep.as_dict())
    except OSError:
        json_path = None
    if not quiet:
        rep.print_summary(json_path)
    return 0 if rep.ok else 1


# ---------------------------------------------------------------- gate terms

def cmd_gate_terms(args):
    root = args.root
    rep = Report("terms")
    tpath = getattr(args, "file", None) or os.path.join(root, ".aiflow", "baseline", "terms.yaml")
    if not os.path.exists(tpath):
        rep.err("T0", "找不到术语表（先跑 aipsw init，或用 --file 指定）", tpath)
        return finish(rep, root, "term_check.json", args)

    data, errs, dups = parse_yaml_file(tpath)
    for e in errs:
        rep.err("T1", e, os.path.relpath(tpath, root))
    for d in dups:
        rep.err("T1", "术语重复定义：" + d, os.path.relpath(tpath, root))
    if errs or dups:
        return finish(rep, root, "term_check.json", args)

    terms = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(terms, dict) or not terms:
        rep.warn("T1", "术语表没有 terms 条目（模板未填写？）", os.path.relpath(tpath, root))
        return finish(rep, root, "term_check.json", args)

    zh_to_key = {}
    real_terms = {}
    for key, spec in terms.items():
        if not isinstance(spec, dict):
            continue
        if is_placeholder(key) or is_placeholder(spec.get("zh")):
            continue
        zh = str(spec.get("zh")).strip()
        real_terms[key] = spec
        if not is_placeholder(spec.get("definition")):
            pass
        else:
            rep.err("T2", "术语「%s」缺少 definition（或仍是占位符）" % zh, key)
        status = str(spec.get("status") or "").strip()
        if status not in ("confirmed", "pending", "deprecated"):
            rep.err("T2", "术语「%s」status 非法：%r（应为 confirmed / pending / deprecated）" % (zh, status), key)
        if zh in zh_to_key and zh_to_key[zh] != key:
            rep.err("T2", "中文名「%s」被两个术语重复占用：%s / %s" % (zh, zh_to_key[zh], key), key)
        zh_to_key[zh] = key

    if not real_terms:
        rep.warn("T1", "术语表只有占位符，尚无真实术语")
        return finish(rep, root, "term_check.json", args)

    docs = [(rel, path) for rel, path in iter_files(root, DOC_EXT)
            if not rel.startswith("skill/") and not rel.startswith(".aiflow/")]

    defined_in = {}
    for key, spec in real_terms.items():
        zh = str(spec.get("zh")).strip()
        status = str(spec.get("status") or "").strip()
        pat_def = re.compile(r"\*\*" + re.escape(zh) + r"\*\*[（(：:]")
        for rel, path in docs:
            text = read_text(path)
            if pat_def.search(text):
                defined_in.setdefault(zh, []).append(rel)
            if status == "deprecated" and zh in text and not pat_def.search(text):
                for ln, line in md_lines_outside_fence(text):
                    if zh in line:
                        rep.err("T3", "已废弃术语「%s」仍出现在正文（应移出或改写）" % zh,
                                "%s:%d" % (rel, ln))
                        break

    for zh, files in defined_in.items():
        if len(files) > 1:
            rep.warn("T4", "术语「%s」被加粗定义在 %d 个文件里，应只在术语表定义" % (zh, len(files)),
                     ", ".join(files))

    rep.note("术语数：%d｜扫描文档：%d 个" % (len(real_terms), len(docs)))
    return finish(rep, root, "term_check.json", args)


# ---------------------------------------------------------------- gate toc

def cmd_gate_toc(args):
    root = args.root
    rep = Report("toc")
    total_docs = 0
    total_links = 0
    for rel, path in iter_files(root, DOC_EXT):
        if rel.startswith("skill/"):
            continue
        text = read_text(path)
        anchors, titles = build_anchor_map(text)
        links = parse_md_toc(text)
        if not links:
            continue
        total_docs += 1
        total_links += len(links)
        for ln, target in links:
            if target not in anchors:
                rep.err("TOC-1", "目录指向不存在的标题：#" + target, "%s:%d" % (rel, ln))

        SKIP_TITLE = {"目录", "contents", "toc", "table of contents"}
        has_toc_heading = any(t.strip().lower() in ("目录", "contents", "toc") for t, _l in titles)
        h2 = [t for t, lvl in titles if t and lvl == 2 and t.strip().lower() not in SKIP_TITLE]
        if len(h2) >= 5 and (has_toc_heading or len(links) >= 5):
            linked = set()
            for _, target in links:
                linked.add(target)
            covered = 0
            for t in h2:
                if gh_slug(t) in linked or any(gh_slug(t) == x.split("-", 1)[0] for x in linked):
                    covered += 1
            rate = covered / float(len(h2))
            if rate < 0.9:
                rep.warn("TOC-2", "二级标题覆盖率 %.0f%%（< 90%%）：%d/%d 个二级标题未进目录" % (
                    rate * 100, len(h2) - covered, len(h2)), rel)

    rep.note("检查文档：%d 个｜内部链接：%d 条" % (total_docs, total_links))
    return finish(rep, root, "toc_check.json", args)


# ---------------------------------------------------------------- gate sig

IDENT_RE = re.compile(r"[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]*")


def cmd_gate_sig(args):
    root = args.root
    rep = Report("sig")
    cdir = getattr(args, "contracts", None) or os.path.join(root, ".aiflow", "baseline", "contracts")
    if not os.path.isdir(cdir):
        rep.warn("S0", "没有契约目录，跳过签名比对（并行前才需要冻结契约）", cdir)
        return finish(rep, root, "sig_check.json", args)

    contracts = [f for f in sorted(os.listdir(cdir))
                 if f.endswith((".yaml", ".yml")) and not f.startswith("_")]
    if not contracts:
        rep.warn("S0", "契约目录里没有 <module>.yaml，跳过")
        return finish(rep, root, "sig_check.json", args)

    code_text = None
    seen_names = {}
    checked = 0
    for fn in contracts:
        path = os.path.join(cdir, fn)
        data, errs, dups = parse_yaml_file(path)
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        for e in errs:
            rep.err("S1", e, rel)
        for d in dups:
            rep.err("S1", "契约字段重复：" + d, rel)
        if errs:
            continue
        if not isinstance(data, dict):
            rep.err("S1", "契约文件结构不是映射", rel)
            continue
        ver = str(data.get("version") or "")
        if not re.match(r"^v\d+(\.\d+)*$", ver):
            rep.err("S1", "契约版本号缺失或非法：%r（应为 vX.Y）" % ver, rel)
        ep = data.get("endpoints") or []
        if not isinstance(ep, list):
            rep.err("S1", "endpoints 不是列表", rel)
            continue
        names = []
        for item in ep:
            if isinstance(item, dict) and item.get("name") and not is_placeholder(item.get("name")):
                names.append(str(item["name"]).strip())
        if not names:
            rep.warn("S1", "契约里没有可校验的 endpoint（仍是占位符？）", rel)
            continue
        for n in names:
            if n in seen_names and seen_names[n] != rel:
                rep.err("S2", "接口「%s」在多个契约中重复声明：%s / %s" % (n, seen_names[n], rel), rel)
            seen_names[n] = rel

        if code_text is None:
            chunks = []
            for crel, cpath in iter_files(root, CODE_EXT):
                chunks.append(read_text(cpath))
            code_text = "\n".join(chunks)
        for n in names:
            checked += 1
            if not re.search(r"\b" + re.escape(n) + r"\b", code_text):
                rep.err("S3", "契约接口「%s」在代码里找不到同名实现" % n, rel)

    rep.note("契约文件：%d 个｜校验接口：%d 个" % (len(contracts), checked))
    return finish(rep, root, "sig_check.json", args)


# ---------------------------------------------------------------- gate dup

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _tokens(text):
    return [t.lower() for t in TOKEN_RE.findall(text)]


def _shingles(tokens, n=5):
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def cmd_gate_dup(args):
    root = args.root
    rep = Report("dup")
    if not getattr(args, "new", None):
        rep.err("D0", "需要指定新文件：--new <file> [--new <file> ...]")
        return finish(rep, root, "dup_check.json", args)

    new_files = [n.replace("\\", "/") for n in getattr(args, "new", [])]
    pool = []
    for rel, path in iter_files(root, CODE_EXT):
        if rel in new_files:
            continue
        try:
            if os.path.getsize(path) < getattr(args, "min_lines", 30) * 8:
                continue
        except OSError:
            continue
        pool.append((rel, path))

    rep.note("基线资产：%d 个文件｜阈值：%.0f%%" % (len(pool), getattr(args, "threshold", 0.10) * 100))
    compared = 0
    for nrel in new_files:
        npath = os.path.join(root, nrel)
        if not os.path.exists(npath):
            rep.err("D1", "新文件不存在", nrel)
            continue
        ntext = read_text(npath)
        nlines = ntext.count("\n") + 1
        if nlines < getattr(args, "min_lines", 30):
            rep.note("跳过（行数 < %d）：%s" % (getattr(args, "min_lines", 30), nrel))
            continue
        ns = _shingles(_tokens(ntext))
        if not ns:
            rep.note("跳过（无可比对标识符）：" + nrel)
            continue
        ext = os.path.splitext(nrel)[1].lower()
        best = None
        for rel, path in pool:
            if os.path.splitext(rel)[1].lower() != ext:
                continue
            compared += 1
            es = _shingles(_tokens(read_text(path)))
            if not es:
                continue
            inter = len(ns & es)
            if not inter:
                continue
            ratio = inter / float(len(ns))
            if best is None or ratio > best[1]:
                best = (rel, ratio)
        if best and best[1] >= getattr(args, "threshold", 0.10):
            rep.err("D-OVERLAP",
                    "%s 与 %s 的重叠度 %.0f%%（目标 <= 10%%，阈值 %.0f%%）" % (
                        nrel, best[0], best[1] * 100, getattr(args, "threshold", 0.10) * 100),
                    nrel)
        elif best:
            rep.note("最高相似：%s -> %s（%.0f%%）" % (nrel, best[0], best[1] * 100))
        else:
            rep.note("未发现相似资产：" + nrel)

    if not compared:
        rep.warn("D2", "没有同类型基线文件可比对")
    return finish(rep, root, "dup_check.json", args)


# ---------------------------------------------------------------- scan

BT = chr(96)


def _classify(rel, ext):
    if TEST_RE.search("/" + rel):
        return "test"
    if ext in CONFIG_EXT:
        return "config"
    if ext in CODE_EXT:
        return "code"
    if ext in DOC_EXT:
        return "doc"
    return "other"


def _hits(root, patterns, exts):
    seen = set()
    for rel, path in iter_files(root, exts):
        try:
            text = read_text(path)
        except OSError:
            continue
        if not any(p.search(text) for p in patterns):
            continue
        ext = os.path.splitext(rel)[1].lower()
        kind = _classify(rel, ext)
        for ln, line in enumerate(text.splitlines(), 1):
            for p in patterns:
                if p.search(line):
                    key = (rel, ln)
                    if key in seen:
                        break
                    seen.add(key)
                    yield rel, ln, kind, line.strip()[:160]
                    break


def _md_table(rows, headers):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in r) + " |")
    return "\n".join(lines)


def cmd_scan_impact(args):
    root = args.root
    symbols = args.symbol or []
    keys = args.key or []
    if not symbols and not keys:
        die("至少给一个 --symbol 或 --key")

    today = date.today().isoformat()
    exts = CODE_EXT | CONFIG_EXT | DOC_EXT
    sym_rows, cfg_rows, test_rows = [], [], []
    idx = 0

    for sym in symbols:
        pat = re.compile(r"\b" + re.escape(sym) + r"\b")
        for rel, ln, kind, text in _hits(root, [pat], exts):
            idx += 1
            if kind == "test":
                test_rows.append([idx, "测试引用", "%s:%d" % (rel, ln), text, "待判", "待定"])
            elif kind == "config":
                cfg_rows.append([idx, "配置读取", "%s:%d" % (rel, ln), text, "是", "待定"])
            else:
                sym_rows.append([idx, kind, "%s:%d" % (rel, ln), text, "待判", "待定"])

    for k in keys:
        pat = re.compile(re.escape(k))
        for rel, ln, kind, text in _hits(root, [pat], exts):
            if kind not in ("config", "code"):
                continue
            idx += 1
            cfg_rows.append([idx, "配置读取", "%s:%d" % (rel, ln), text, "是", "待定"])

    md = []
    md.append("# 影响面清单（M1）· " + (" ".join(symbols + keys) or "未命名") + " · " + today)
    md.append("")
    md.append("> 由 " + BT + "aipsw scan impact" + BT + " 生成。**扫描结果只是起点**：")
    md.append("> 工具扫不到的部分（动态引用、外部调用方、运行时行为）必须人工补；")
    md.append("> 清单为空或未覆盖「配置读取点」时，按规范 §3.14.2 不得进入阶段 6。")
    md.append("")
    md.append("## 扫描命令")
    md.append("")
    cmd = "aipsw scan impact"
    if symbols:
        cmd += " " + " ".join(["--symbol " + s for s in symbols])
    if keys:
        cmd += " " + " ".join(["--key " + k for k in keys])
    md.append(BT + cmd + BT)
    md.append("")
    md.append("## 1. 调用方 / 引用点（code）")
    md.append("")
    md.append(_md_table(sym_rows[: getattr(args, "max_rows", 200)], ["#", "类型", "位置（文件:行）", "命中内容", "受影响", "处置"]))
    md.append("")
    md.append("## 2. 配置读取点")
    md.append("")
    md.append(_md_table(cfg_rows[: getattr(args, "max_rows", 200)], ["#", "类型", "位置（文件:行）", "命中内容", "受影响", "处置"]))
    md.append("")
    md.append("## 3. 现有测试")
    md.append("")
    md.append(_md_table(test_rows[: getattr(args, "max_rows", 200)], ["#", "类型", "位置（文件:行）", "命中内容", "受影响", "处置"]))
    md.append("")
    md.append("## 4. 必须人工确认的项")
    md.append("")
    md.append("- [ ] 动态引用：反射 / SPI 注册 / 字符串类名 / 插件扫描")
    md.append("- [ ] 外部调用方：对外契约、网关路由、其他仓库")
    md.append("- [ ] 数据引用：表字段、缓存 key、日志字段")
    md.append("- [ ] 运行时行为：启动期装配、健康检查、定时任务")
    md.append("")
    md.append("## 统计")
    md.append("")
    md.append("- 代码引用：%d 处" % len(sym_rows))
    md.append("- 配置读取：%d 处" % len(cfg_rows))
    md.append("- 测试引用：%d 处" % len(test_rows))
    if idx > getattr(args, "max_rows", 200):
        md.append("- 已截断：仅显示前 %d 条，完整结果请缩小扫描范围" % args.max_rows)

    body = "\n".join(md) + "\n"
    return _emit(body, args, root)


def cmd_scan_delete(args):
    root = args.root
    sym = args.symbol
    if not sym:
        die("需要 --symbol <要删除的符号或接口名>")

    today = date.today().isoformat()
    exts = CODE_EXT | CONFIG_EXT | DOC_EXT
    static_rows, dyn_rows, cfg_rows, doc_rows = [], [], [], []
    i = 0

    ident = re.compile(r"\b" + re.escape(sym) + r"\b")
    counters = {"doc": 0, "config": 0, "test": 0, "code": 0}
    for rel, ln, kind, text in _hits(root, [ident], exts):
        k = kind if kind in counters else "code"
        counters[k] += 1
        n = counters[k]
        if kind == "doc":
            doc_rows.append([n, "文档/示例", "%s:%d" % (rel, ln), text, "待处置"])
        elif kind == "config":
            cfg_rows.append([n, "配置文件", "%s:%d" % (rel, ln), text, "待处置"])
        elif kind == "test":
            static_rows.append([n, "静态引用(测试)", "%s:%d" % (rel, ln), text, "改造用例"])
        else:
            static_rows.append([n, "静态引用", "%s:%d" % (rel, ln), text, "待处置"])

    quoted = re.compile(r"""["']\s*""" + re.escape(sym) + r"""\s*["']""")
    reflect = re.compile(r"(Class\.forName|getattr|importlib|ServiceLoader|Assembly\.Load|ClassLoader|反射|加载类|SPI)", re.I)
    for rel, ln, kind, text in _hits(root, [quoted, reflect], CODE_EXT):
        if not ident.search(text) and not quoted.search(text):
            continue
        dyn_rows.append([len(dyn_rows) + 1, "动态引用", "%s:%d" % (rel, ln), text, "重点核对"])

    md = []
    md.append("# 删除专项检查单 · " + sym + " · " + today)
    md.append("")
    md.append("> 由 " + BT + "aipsw scan delete" + BT + " 生成。**代码删除看引用，数据删除看合规。**")
    md.append("> ⑤ 外部调用方、⑥ 数据引用工具扫不到，必须人工确认；任一类未扫不得执行删除（§3.16 D2）。")
    md.append("")
    md.append("## D1 必要性确认")
    md.append("")
    md.append("| 选项 | 评估 |")
    md.append("| --- | --- |")
    md.append("| 改为废弃标记长期保留 | 可行 / 不可行（原因：） |")
    md.append("| 直接移除 | 结论： |")
    md.append("")
    md.append("> 多数「删除」其实是「不想让人再用」——先确认废弃是否已足够。")
    md.append("")
    md.append("## ① 静态引用")
    md.append("")
    md.append(_md_table(static_rows[: getattr(args, "max_rows", 200)], ["#", "类型", "位置（文件:行）", "命中内容", "处置"]) or "（无）")
    md.append("")
    md.append("## ② 动态引用（反射 / SPI / 字符串类名）")
    md.append("")
    if dyn_rows:
        md.append(_md_table(dyn_rows[: getattr(args, "max_rows", 200)], ["#", "类型", "位置（文件:行）", "命中内容", "处置"]))
    else:
        md.append("（工具未命中。**这不等于没有**——配置驱动的反射查不到，需人工确认。）")
    md.append("")
    md.append("## ③ 配置文件")
    md.append("")
    md.append(_md_table(cfg_rows[: args.max_rows], ["#", "类型", "位置（文件:行）", "命中内容", "处置"]) or "（无）")
    md.append("")
    md.append("## ④ 文档 / 示例")
    md.append("")
    md.append(_md_table(doc_rows[: getattr(args, "max_rows", 200)], ["#", "类型", "位置（文件:行）", "命中内容", "处置"]) or "（无）")
    md.append("")
    md.append("## ⑤ 外部调用方（人工）")
    md.append("")
    md.append("- [ ] 对外契约 / OpenAPI 里是否还有该端点")
    md.append("- [ ] 网关路由 / 白名单是否有记录")
    md.append("- [ ] 其他仓库 / 调用方是否在用")
    md.append("")
    md.append("## ⑥ 数据引用（人工）")
    md.append("")
    md.append("- [ ] 是否有表字段 / 索引依赖它")
    md.append("- [ ] 是否有缓存 key / 日志字段依赖它")
    md.append("- [ ] 涉及个人数据时：审计日志 + 不可恢复确认 + 必要时法务（D5）")
    md.append("")
    md.append("## 统计")
    md.append("")
    md.append("- 静态引用：%d 处" % len(static_rows))
    md.append("- 动态候选：%d 处（需人工复核）" % len(dyn_rows))
    md.append("- 配置：%d 处｜文档：%d 处" % (len(cfg_rows), len(doc_rows)))

    body = "\n".join(md) + "\n"
    return _emit(body, args, root)


def _emit(body, args, root):
    if getattr(args, "out", None):
        path = args.out if os.path.isabs(args.out) else os.path.join(root, args.out)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        print("已写入: " + path)
        return 0
    sys.stdout.write(body)
    return 0


# ---------------------------------------------------------------- init

def _find_templates(hint):
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if hint:
        candidates.append(hint)
    candidates.append(os.path.join(here, "..", ".aiflow"))
    candidates.append(os.path.join(here, "..", "references", "templates", "aiflow"))
    candidates.append(os.path.join(here, "templates", "aiflow"))
    for c in candidates:
        c = os.path.abspath(c)
        if os.path.isdir(c) and os.path.exists(os.path.join(c, "baseline", "conventions.md")):
            return c
    return None


QUESTION_SHEET = """# 问题清单 · {chg} · {today}

> 阶段 2 的产物。**没有这张表 = 没有做过需求确认。**
> 1. 只回答「不回答就写不下去」的阻塞级问题；其余记为待办，不进常驻上下文。
> 2. 每条待办必须写「最迟回答节点」，到期未答自动升级为阻塞项。
> 3. 确认的结论同步进 decisions.md；待定假设不得作为设计依据。

## 一、阻塞性问题（不回答就写不下去）
| # | 问题 | 为什么阻塞 | 首次提问 | 用户回答 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 |  |  |  |  | 待答 |

## 二、重要但可后置
| # | 问题 | 最迟回答节点 | 首次提问 | 回答 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 |  | 卡点 3 前 |  |  | 待答 |

## 三、建议性（可随复盘归档）
| # | 问题 | 记录日期 | 处理 |
| --- | --- | --- | --- |
| 1 |  |  |  |

## 四、人工补充的盲区
| # | 问题 | 谁补充 | 补充日期 |
| --- | --- | --- | --- |
| 1 |  |  |  |

## 五、本轮确认结论（→ decisions.md）
| 问题 | 结论 | 取舍理由 | 影响的文档章节 |
| --- | --- | --- | --- |
|  |  |  |  |

## 六、仍待定的假设（不得作为设计依据）
| 假设 | 若错了会怎样 | 最迟验证节点 |
| --- | --- | --- |
|  |  |  |

## 核对
- [ ] 每条阻塞项都已回答
- [ ] 每条待办都有「最迟回答节点」
- [ ] 结论已同步到 decisions.md
"""


def cmd_init(args):
    dest = os.path.abspath(args.dest or os.getcwd())
    src = _find_templates(args.templates)
    if not src:
        die("找不到 .aiflow 模板；请用 --templates 指定模板目录")
    target = os.path.join(dest, ".aiflow")
    if os.path.exists(target) and not args.force:
        die("目标已存在 .aiflow（用 --force 覆盖骨架，或先备份）")

    if os.path.exists(target) and args.force:
        shutil.rmtree(target)
    shutil.copytree(src, target)

    project = args.project or os.path.basename(dest.rstrip("\\/")) or "未命名项目"
    owner = args.owner or "待确认"
    today = date.today().isoformat()
    replaced = 0
    for rel in ("baseline/conventions.md", "baseline/terms.yaml", "baseline/fmea.md",
                "baseline/assets.md", "baseline/decisions.md", "baseline/现状地图.md",
                "baseline/evals/cases.yaml"):
        fp = os.path.join(target, rel)
        if not os.path.exists(fp):
            continue
        t = read_text(fp)
        t2 = (t.replace("<项目名>", project)
                .replace("<YYYY-MM-DD>", today)
                .replace("<待确认>", owner)
                .replace("<日期>", today))
        if t2 != t:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(t2)
            replaced += 1

    chg = "CHG-%s-01" % date.today().strftime("%Y%m%d")
    chg_dir = os.path.join(target, "work", chg)
    os.makedirs(chg_dir, exist_ok=True)
    sheet_path = os.path.join(chg_dir, "问题清单.md")
    if not os.path.exists(sheet_path):
        with open(sheet_path, "w", encoding="utf-8") as f:
            f.write(QUESTION_SHEET.replace("{chg}", chg).replace("{today}", today))

    print("已初始化: " + target)
    print("项目名  : " + project)
    print("日期    : " + today)
    print("已填占位符: %d 个文件" % replaced)
    print("已生成    : .aiflow/work/" + chg + "/问题清单.md")
    print("")
    print("下一步（按顺序）:")
    print("  1. 填 baseline/conventions.md —— 尤其第 8 节「合格范例」，写 2~3 个真实路径")
    print("  2. 填 baseline/terms.yaml —— 10~20 个核心术语")
    print("  3. 填 baseline/fmea.md —— Top 10（个人模式 Top 5），RPN > 200 必须配措施")
    print("  4. 填 baseline/evals/cases.yaml —— 团队 >=10+5+3，个人 5+3")
    print("  5. 开工：.aiflow/work/" + chg + "/问题清单.md （先填这张表）")
    print("  6. 提交前跑门禁：python scripts/aipsw.py gate all")
    return 0


# ---------------------------------------------------------------- main

def build_parser():
    ap = argparse.ArgumentParser(
        prog="aipsw",
        description="AIPSW 配套命令行工具 —— 判级、扫描、门禁（零第三方依赖）",
    )
    ap.add_argument("--root", default=".", help="项目根目录，默认当前目录")
    sub = ap.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="把 .aiflow 骨架装进目标项目")
    p_init.add_argument("--dest", help="目标项目根目录，默认当前目录")
    p_init.add_argument("--templates", help="模板目录（默认自动查找）")
    p_init.add_argument("--project", help="项目名，用于替换 <项目名>")
    p_init.add_argument("--owner", help="责任人，用于替换 <待确认>")
    p_init.add_argument("--force", action="store_true", help="覆盖已存在的 .aiflow")

    p_gate = sub.add_parser("gate", help="跑门禁检查")
    gsub = p_gate.add_subparsers(dest="gate")

    g_terms = gsub.add_parser("terms", help="术语单一事实源检查")
    g_terms.add_argument("--file", help="terms 文件路径")

    gsub.add_parser("toc", help="目录 <-> 章节覆盖率检查")

    g_sig = gsub.add_parser("sig", help="契约 <-> 代码签名检查")
    g_sig.add_argument("--contracts", help="契约目录")

    g_dup = gsub.add_parser("dup", help="重复度检查")
    g_dup.add_argument("--new", action="append", help="新文件（可重复）")
    g_dup.add_argument("--threshold", type=float, default=0.10, help="重叠阈值，默认 0.10（规范目标 <= 10%%）")
    g_dup.add_argument("--min-lines", type=int, default=30, help="小于该行数不比对，默认 30")

    gsub.add_parser("all", help="依次跑 terms / toc / sig")

    p_scan = sub.add_parser("scan", help="扫描并产出清单骨架")
    ssub = p_scan.add_subparsers(dest="scan")
    s_imp = ssub.add_parser("impact", help="影响面扫描（修改类 M1）")
    s_imp.add_argument("--symbol", action="append", help="要改的符号（可重复）")
    s_imp.add_argument("--key", action="append", help="配置项名（可重复）")
    s_imp.add_argument("--out", help="输出文件（相对 root），不给则打印到标准输出")
    s_imp.add_argument("--max-rows", type=int, default=200, help="每类最多输出行数")

    s_del = ssub.add_parser("delete", help="删除引用扫描（删除专项 D2）")
    s_del.add_argument("--symbol", required=True, help="要删除的符号 / 接口名")
    s_del.add_argument("--out", help="输出文件（相对 root）")
    s_del.add_argument("--max-rows", type=int, default=200, help="每类最多输出行数")

    sub.add_parser("version", help="打印版本")
    return ap


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = build_parser()
    args = ap.parse_args(argv)

    if not args.cmd:
        ap.print_help()
        return 2
    if args.cmd == "version":
        print("aipsw tool %s (AIPSW %s)" % (TOOL_VERSION, AIPSW_VERSION))
        return 0
    args.root = os.path.abspath(args.root)
    if not os.path.isdir(args.root):
        die("root 不是目录: " + args.root)

    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "gate":
        if args.gate == "terms":
            return cmd_gate_terms(args)
        if args.gate == "toc":
            return cmd_gate_toc(args)
        if args.gate == "sig":
            return cmd_gate_sig(args)
        if args.gate == "dup":
            return cmd_gate_dup(args)
        if args.gate == "all":
            rc1 = cmd_gate_terms(args)
            rc2 = cmd_gate_toc(args)
            rc3 = cmd_gate_sig(args)
            print("")
            print("汇总: terms=%s toc=%s sig=%s" % (
                "PASS" if rc1 == 0 else "FAIL",
                "PASS" if rc2 == 0 else "FAIL",
                "PASS" if rc3 == 0 else "FAIL"))
            return 1 if 1 in (rc1, rc2, rc3) else 0
        ap.parse_args(["gate", "-h"])
    if args.cmd == "scan":
        if args.scan == "impact":
            return cmd_scan_impact(args)
        if args.scan == "delete":
            return cmd_scan_delete(args)
        ap.parse_args(["scan", "-h"])
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
