#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIPSW 配套命令行工具（零第三方依赖，Python 3.8+）

AIPSW = AI Project Standard Workflow（AI 项目开发标准规范工作流程）

子命令:
  init            把 .aiflow 骨架装进目标项目，并填掉占位符
  gate terms      术语单一事实源检查（T1-T4）
  gate toc        目录/跨文件链接 <-> 章节覆盖率检查
  gate sig        接口契约 <-> 代码签名检查
  gate dup        新代码与既有资产的重复度检查
  gate all        依次执行 terms / toc / sig（--new 时加跑 dup）
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
from urllib.parse import unquote

TOOL_VERSION = "1.3.0"
AIPSW_VERSION = "v1.14"

FENCE = chr(96) * 3

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", "target", "out", ".idea", ".vscode", ".mypy_cache",
    ".pytest_cache", "reports", ".aiflow/archive", ".aiflow/work",
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
            if (d in SKIP_DIRS or joined in SKIP_DIRS
                    or d.startswith(".tmp-") or d.startswith(".pkg-")):
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


def parse_md_links(text):
    """解析 Markdown 链接/图片目标（跳过围栏代码块）。"""
    items = []
    for ln, line in md_lines_outside_fence(text):
        for m in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", line):
            items.append((ln, m.group(1)))
    return items


def _link_target(raw):
    """返回 (相对路径, 锚点) 或 None（外链 / 纯锚点）。"""
    raw = raw.strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1].strip()
    if raw.lower().startswith(("http://", "https://", "mailto:", "tel:", "#", "//")):
        return None
    raw = re.sub(r'\s+"[^"]*"$', "", raw)
    raw = re.sub(r"\s+'[^']*'$", "", raw)
    path, _, anchor = raw.partition("#")
    path = unquote(path.strip())
    if not path:
        return None
    return path, anchor


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
    total_cross = 0
    for rel, path in iter_files(root, DOC_EXT):
        text = read_text(path)
        anchors, titles = build_anchor_map(text)
        total_docs += 1

        # 跨文件链接 / 跨文件锚点：文件不存在或锚点失效都算断链
        for ln, raw in parse_md_links(text):
            parsed = _link_target(raw)
            if not parsed:
                continue
            target_rel, target_anchor = parsed
            if target_rel.startswith("/"):
                target_rel = target_rel.lstrip("/")
            resolved = os.path.normpath(os.path.join(os.path.dirname(rel), target_rel)).replace(os.sep, "/")
            full = os.path.join(root, resolved)
            total_cross += 1
            if not os.path.exists(full):
                rep.err("TOC-3", "链接指向的文件不存在：" + raw, "%s:%d" % (rel, ln))
                continue
            if target_anchor and resolved.lower().endswith((".md", ".markdown")):
                target_anchors, _ = build_anchor_map(read_text(full))
                if target_anchor not in target_anchors:
                    rep.err("TOC-3", "跨文件锚点不存在：" + raw,
                            "%s:%d" % (rel, ln))

        if rel.startswith("skill/"):
            continue
        links = parse_md_toc(text)
        if not links:
            continue
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

    rep.note("检查文档：%d 个｜内部链接：%d 条｜跨文件链接：%d 条" % (total_docs, total_links, total_cross))
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
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        except OSError as e:
            die("无法写入 %s: %s" % (path, e))
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


# ---------------------------------------------------------------- 生成器

MODULE_CONTAINERS = {
    "src", "app", "lib", "pkg", "internal", "modules", "module", "source",
    "backend", "frontend", "server", "client", "core", "service", "services", "cmd",
}

SYMBOL_RE = {
    ".py": re.compile(r"^(?:class|def)\s+([A-Za-z_]\w*)"),
    ".js": re.compile(r"^(?:export\s+)?(?:class|function|const|let|interface|type)\s+([A-Za-z_$][\w$]*)"),
    ".ts": re.compile(r"^(?:export\s+)?(?:declare\s+)?(?:class|function|const|let|interface|type)\s+([A-Za-z_$][\w$]*)"),
    ".java": re.compile(r"^\s*(?:public\s+|private\s+|protected\s+)?(?:final\s+|abstract\s+|static\s+)*(?:class|interface|enum|record)\s+([A-Za-z_]\w*)"),
    ".kt": re.compile(r"^\s*(?:public\s+|private\s+|internal\s+)?(?:data\s+|sealed\s+|abstract\s+)?(?:class|interface|object|fun)\s+([A-Za-z_]\w*)"),
    ".go": re.compile(r"^(?:type|func)\s+([A-Za-z_]\w*)"),
    ".cs": re.compile(r"^\s*(?:public\s+|internal\s+|private\s+)?(?:sealed\s+|abstract\s+|static\s+|partial\s+)*(?:class|interface|enum|record|struct)\s+([A-Za-z_]\w*)"),
    ".rs": re.compile(r"^(?:pub\s+)?(?:struct|enum|trait|fn|type)\s+([A-Za-z_]\w*)"),
}

IMPORT_RE = {
    ".py": re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))"),
    ".js": re.compile(r"""(?:from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))"""),
    ".ts": re.compile(r"""(?:from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\))"""),
    ".java": re.compile(r"^\s*import\s+([\w\.]+)\s*;"),
    ".kt": re.compile(r"^\s*import\s+([\w\.]+)"),
    ".go": re.compile(r'^\s*(?:[\w\.]+\s+)?"([^"]+/[^"]+)"'),
    ".cs": re.compile(r"^\s*using\s+([\w\.]+)\s*;"),
    ".rs": re.compile(r"^\s*use\s+([\w:]+)"),
}

ENTRY_NAMES = {"main.py", "main.go", "main.rs", "index.js", "index.ts", "app.js", "app.ts",
               "manage.py", "__main__.py", "cli.py", "Program.cs", "Main.java"}


def _estimate_tokens(text):
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    rest = max(0, len(text) - cjk)
    return int(cjk * 1.1 + rest / 4.0) + 1


def _rel(path, root):
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path


def _module_of(rel):
    parts = rel.split("/")
    if len(parts) == 1:
        return "(根目录)"
    if parts[0].lower() in MODULE_CONTAINERS and len(parts) > 2:
        return parts[1]
    return parts[0]


def _resolve_import(imp, modules):
    for seg in re.split(r"[./\\:]", imp):
        if seg in modules:
            return seg
    return None


def cmd_map(args):
    root = args.root
    files = list(iter_files(root, CODE_EXT))
    modules = {}
    entries = []

    # 第一遍：模块清单 / 符号抽样 / 入口
    for rel, path in files:
        mod = _module_of(rel)
        info = modules.setdefault(mod, {"files": 0, "symbols": [], "lines": 0})
        info["files"] += 1
        try:
            text = read_text(path)
        except OSError:
            continue
        info["lines"] += text.count("\n") + 1
        if os.path.basename(rel) in ENTRY_NAMES or "if __name__ ==" in text:
            entries.append(rel)
        ext = os.path.splitext(rel)[1].lower()
        sym = SYMBOL_RE.get(ext)
        if sym:
            for line in text.splitlines():
                m = sym.match(line)
                if m and m.group(1) not in info["symbols"]:
                    info["symbols"].append(m.group(1))
                if len(info["symbols"]) >= args.max_symbols:
                    break

    # 第二遍：依赖（此时模块全集已知）
    edges = {}
    for rel, path in files:
        mod = _module_of(rel)
        ext = os.path.splitext(rel)[1].lower()
        imp_re = IMPORT_RE.get(ext)
        if not imp_re:
            continue
        try:
            text = read_text(path)
        except OSError:
            continue
        for line in text.splitlines():
            m = imp_re.match(line)
            if not m:
                continue
            target = next((g for g in m.groups() if g), None)
            if not target or target.startswith("."):
                continue
            dep = _resolve_import(target, modules)
            if dep and dep != mod:
                edges.setdefault(mod, {})
                edges[mod][dep] = edges[mod].get(dep, 0) + 1

    if not modules:
        print("没有找到源码文件（支持：" + ", ".join(sorted(CODE_EXT)) + "）")
        return 0

    top = sorted(modules.items(), key=lambda kv: kv[1]["files"], reverse=True)[: args.max_modules]
    kept = set(k for k, _ in top)

    lines = []
    lines.append("# 现状地图 · " + (args.project or os.path.basename(root)) + " · " + date.today().isoformat())
    lines.append("")
    lines.append("> 由 `aipsw map` 自动生成（扫描 " + str(len(files)) + " 个源码文件）。")
    lines.append("> **只盘现状，不补规范**（§3.21 G2）。自动结果只覆盖「结构」，以下三项必须人工补：")
    lines.append("> ① 每个模块的职责一句话；② 是否越界（允许依赖 vs 实际依赖）；③ 已知技术债。")
    lines.append("")
    lines.append("## 1. 模块清单")
    lines.append("")
    lines.append("| 模块 | 文件数 | 代码行 | 关键符号（自动抽样） | 职责（**待人工补**） | 对外暴露 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for mod, info in top:
        syms = "、".join(info["symbols"][:6]) or "—"
        lines.append("| %s | %d | %d | %s | TODO | TODO |" % (mod, info["files"], info["lines"], syms))
    if len(modules) > len(top):
        lines.append("")
        lines.append("> 另有 %d 个模块未列出（--max-modules 可调）：%s" % (
            len(modules) - len(top), "、".join(sorted(set(modules) - kept))))
    lines.append("")
    lines.append("## 2. 实际依赖方向（自动推断，需人工复核）")
    lines.append("")
    visible = dict((m, d) for m, d in edges.items() if m in kept and any(x in kept for x in d))
    if visible:
        lines.append(FENCE)
        for mod in sorted(visible):
            for dep, cnt in sorted(visible[mod].items(), key=lambda kv: -kv[1]):
                if dep in kept:
                    lines.append("%s → %s%s" % (mod, dep, "" if cnt == 1 else "  (x%d)" % cnt))
        lines.append(FENCE)
        lines.append("")
        lines.append("> 推断依据是 import / require 的模块名匹配，**可能漏掉反射、SPI、动态加载**。")
        lines.append("> 请对照 `conventions.md` 第 3 节的「允许依赖」标出越界项。")
    else:
        lines.append("（未发现跨模块 import。可能是单模块项目，或依赖靠反射/配置注入——需人工确认。）")
    lines.append("")
    lines.append("## 3. 入口与关键路径")
    lines.append("")
    if entries:
        for e in entries[:20]:
            lines.append("- " + e)
    else:
        lines.append("（未识别到入口文件，请人工补：主入口 / 定时任务 / 消息消费者）")
    lines.append("")
    lines.append("## 4. 已知技术债")
    lines.append("")
    lines.append("| 项 | 影响 | 是否本次范围 |")
    lines.append("| --- | --- | --- |")
    lines.append("| TODO：越界调用（见第 2 节） | 可维护性 | 待判 |")
    lines.append("| TODO：无测试覆盖的模块 | 回归风险 | 待判 |")
    lines.append("")

    body = "\n".join(lines) + "\n"
    out = args.out
    if out is None and os.path.isdir(os.path.join(root, ".aiflow")):
        out = os.path.join(".aiflow", "baseline", "现状地图.md")
    if out:
        path = out if os.path.isabs(out) else os.path.join(root, out)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        print("已生成现状地图: " + path)
    else:
        sys.stdout.write(body)
    print("")
    print("扫描: %d 个文件｜模块: %d 个｜跨模块依赖: %d 条｜入口: %d 个" % (
        len(files), len(modules), sum(len(v) for v in edges.values()), len(entries)))
    print("下一步: 补上「职责」「越界判定」「技术债」三列 —— 自动部分到此为止。")
    return 0


def _parse_md_table(text, must_have_header):
    """找出表头含关键字的表格，返回 (列名列表, [行单元格列表])。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if must_have_header not in cells:
            continue
        if i + 1 >= len(lines) or not re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            continue
        rows = []
        for row in lines[i + 2:]:
            if not row.strip().startswith("|"):
                break
            rows.append([c.strip() for c in row.strip().strip("|").split("|")])
        return cells, rows
    return None, []


def cmd_pack(args):
    root = args.root
    base = os.path.join(root, ".aiflow", "baseline")
    if not os.path.isdir(base):
        die("找不到 .aiflow/baseline，先跑 aipsw init")

    window = args.window
    available = int(window * 0.75)
    p0_budget = int(available * 0.30)
    p1_budget = int(available * 0.50)

    keywords = [k.lower() for k in (args.keyword or [])]
    p0, p1, p2, skipped = [], [], [], []

    def add(bucket, name, path, form):
        try:
            content = read_text(path)
        except OSError:
            return
        bucket.append({"name": name, "form": form, "tokens": _estimate_tokens(content),
                       "content": content, "path": path})

    conv = os.path.join(base, "conventions.md")
    if os.path.exists(conv):
        add(p0, "conventions.md", conv, "全文（精简版 ≤ 2KB）")
    else:
        skipped.append(("conventions.md", "文件不存在"))

    terms_path = os.path.join(base, "terms.yaml")
    if os.path.exists(terms_path):
        text = read_text(terms_path)
        blocks = text.split("\n  ")[1:]
        picked = [b for b in blocks if not keywords or any(k in b.lower() for k in keywords)]
        content = text if not keywords else (text.split("\n  ")[0] + "\n  " + "\n  ".join(picked))
        form = ("%d 条" % len(picked)) if picked else ("0 条（未命中关键词）" if keywords else "全文")
        p0.append({"name": "terms.yaml（子集）", "form": form,
                   "tokens": _estimate_tokens(content), "content": content, "path": terms_path})

    bottom = ("底线 B1–B8：事实有来源 / 单一事实源 / 契约先冻结带版本 / 工具优先于 AI 判 / "
              "合并前查引用与重复 / 未验证不交付 / 高风险人定稿 / 紧急 24h 补记录")
    p0.append({"name": "底线 B1–B8", "form": "全文", "tokens": _estimate_tokens(bottom),
               "content": bottom, "path": "(内置)"})

    cdir = os.path.join(base, "contracts")
    if os.path.isdir(cdir):
        wanted = set(args.module or [])
        for fn in sorted(os.listdir(cdir)):
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            if wanted:
                data, _e, _d = parse_yaml_file(os.path.join(cdir, fn))
                if isinstance(data, dict) and str(data.get("contract")) not in wanted:
                    continue
            add(p1, "contracts/" + fn, os.path.join(cdir, fn), "全文（本次涉及接口）")
    else:
        skipped.append(("contracts/", "目录不存在"))

    fmea = os.path.join(base, "fmea.md")
    if os.path.exists(fmea):
        text = read_text(fmea)
        header, rows = _parse_md_table(text, "RPN")
        if header and "RPN" in header:
            idx = header.index("RPN")
            hot = []
            for r in rows:
                if idx < len(r):
                    raw = r[idx].strip().strip("*").strip()
                    if raw.isdigit() and int(raw) > 200:
                        hot.append(r)
            if hot:
                content = "| " + " | ".join(header) + " |\n| " + " | ".join(["---"] * len(header)) + " |\n"
                content += "\n".join("| " + " | ".join(r) + " |" for r in hot)
                p1.append({"name": "fmea.md（RPN > 200）", "form": "%d 条" % len(hot),
                           "tokens": _estimate_tokens(content), "content": content, "path": fmea})
            else:
                skipped.append(("fmea.md", "没有 RPN > 200 的条目"))

    dec = os.path.join(base, "decisions.md")
    if os.path.exists(dec):
        text = read_text(dec)
        rows = [l for l in text.splitlines() if l.startswith("| ")
                and not l.startswith("| 日期") and not l.startswith("| ---")]
        tail = rows[-int(args.decisions):]
        if tail:
            content = "\n".join(tail)
            p1.append({"name": "decisions.md（近 %d 条）" % len(tail), "form": "按主题检索",
                       "tokens": _estimate_tokens(content), "content": content, "path": dec})

    amap = os.path.join(base, "现状地图.md")
    if os.path.exists(amap) and args.module:
        text = read_text(amap)
        picked = [l for l in text.splitlines() if any(m in l for m in args.module)]
        if picked:
            content = "\n".join(picked)
            p1.append({"name": "现状地图.md（受影响模块）", "form": "%d 行" % len(picked),
                       "tokens": _estimate_tokens(content), "content": content, "path": amap})

    assets = os.path.join(base, "assets.md")
    if os.path.exists(assets) and keywords:
        text = read_text(assets)
        picked = [l for l in text.splitlines()
                  if l.startswith("| ") and any(k in l.lower() for k in keywords)]
        if picked:
            content = "\n".join(picked[:10])
            p1.append({"name": "assets.md（关键词命中）", "form": "%d 条" % len(picked[:10]),
                       "tokens": _estimate_tokens(content), "content": content, "path": assets})

    p2 = [
        "01-完整版.md（条款，按需切片读）",
        "02-精简版.md（10 分钟）",
        "03-演示文档.md（场景例子）",
        "04-地基模板包.md（模板）",
        "代码本身：按「变更半径」取，用工具检索，不要整目录塞",
    ]

    p0_tokens = sum(x["tokens"] for x in p0)
    p1_tokens = sum(x["tokens"] for x in p1)
    total = p0_tokens + p1_tokens
    over = []
    if p0_tokens > p0_budget:
        over.append("P0 超预算（%d > %d）" % (p0_tokens, p0_budget))
    if p1_tokens > p1_budget:
        over.append("P1 超预算（%d > %d）" % (p1_tokens, p1_budget))

    lines = []
    lines.append("# 上下文装配单 · " + args.chg + " · " + date.today().isoformat())
    lines.append("")
    lines.append("> 由 `aipsw pack` 生成（窗口 %d，可用估 %d）——对应规范附录 J / §3.19.2。" % (window, available))
    lines.append("> **未注入项也须记录**：「我没给它看 X」和「它没看到 X」是两件事。")
    lines.append("")
    lines.append("## 任务信息")
    lines.append("")
    lines.append("| 项 | 内容 |")
    lines.append("| --- | --- |")
    lines.append("| 变更 ID | " + args.chg + " |")
    lines.append("| 操作模式 | " + (args.mode or "待填：生成 / 修改 / 查询 / 删除") + " |")
    lines.append("| 变更级别 | " + (args.level or "待填：L1 / L2 / L3 / L0") + " |")
    lines.append("| 涉及模块 | " + ("、".join(args.module) if args.module else "待填") + " |")
    lines.append("| 关键词 | " + ("、".join(args.keyword) if args.keyword else "—") + " |")
    lines.append("")
    for title, bucket in (("P0 常驻层（预算 ≤30%）", p0), ("P1 任务层（预算 ≤50%）", p1)):
        lines.append("### " + title)
        lines.append("")
        lines.append("| 资产 | 形态 | 估算 token | 路径 |")
        lines.append("| --- | --- | --- | --- |")
        for item in bucket:
            where = "内置" if item["path"] == "(内置)" else _rel(item["path"], root)
            lines.append("| %s | %s | %d | %s |" % (item["name"], item["form"], item["tokens"], where))
        if not bucket:
            lines.append("| （空） | — | 0 | — |")
        lines.append("")
    lines.append("### P2 按需层（工具检索取用，用完即卸）")
    lines.append("")
    for item in p2:
        lines.append("- " + item)
    lines.append("")
    lines.append("## 未注入项与理由")
    lines.append("")
    lines.append("| 资产 | 未注入原因 | 风险 |")
    lines.append("| --- | --- | --- |")
    for name, why in skipped:
        lines.append("| %s | %s | 待判 |" % (name, why))
    lines.append("| 全量术语表 | 只给子集 | 可能漏用生僻术语 |")
    lines.append("| 全量 FMEA | 只给 RPN > 200 | 低 RPN 项可能被忽略 |")
    lines.append("")
    lines.append("## 版本核对")
    lines.append("")
    lines.append("- [ ] 注入资产版本 = `.aiflow/baseline/` 当前版本（J2）")
    lines.append("- [ ] 契约版本 = 当前冻结版本（B3）")
    lines.append("- [ ] 已存快照到 `snapshots/`（J1）")
    lines.append("")
    lines.append("## 预算")
    lines.append("")
    lines.append("| 层 | 估算 token | 预算 | 占比 |")
    lines.append("| --- | --- | --- | --- |")
    lines.append("| P0 | %d | %d | %.0f%% |" % (p0_tokens, p0_budget, p0_tokens * 100.0 / max(1, available)))
    lines.append("| P1 | %d | %d | %.0f%% |" % (p1_tokens, p1_budget, p1_tokens * 100.0 / max(1, available)))
    lines.append("| 合计 | %d | — | %.0f%% |" % (total, total * 100.0 / max(1, available)))
    lines.append("")
    if over:
        lines.append("> ⚠️ **超预算**：" + "；".join(over))
        lines.append("> 按 §3.21 E5：P1 占比 > 60% 必须**拆任务**，不得硬塞长窗口。")
    else:
        lines.append("> ✅ 未超预算。若 P1 已超可用 60%，仍须拆任务（E5）。")

    body = "\n".join(lines) + "\n"
    if args.out:
        path = args.out if os.path.isabs(args.out) else os.path.join(root, args.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        print("已生成装配单: " + path)
    else:
        sys.stdout.write(body)

    if args.payload:
        ppath = args.payload if os.path.isabs(args.payload) else os.path.join(root, args.payload)
        os.makedirs(os.path.dirname(ppath), exist_ok=True)
        with open(ppath, "w", encoding="utf-8") as f:
            f.write("# 注入载荷 · " + args.chg + "\n\n")
            for item in p0 + p1:
                f.write("\n\n<!-- ==== " + item["name"] + " ==== -->\n\n")
                f.write(item["content"])
                if not item["content"].endswith("\n"):
                    f.write("\n")
        print("已生成注入载荷: " + ppath)

    print("P0 %d token / P1 %d token / 可用 %d" % (p0_tokens, p1_tokens, available))
    if over:
        print("⚠️ " + "；".join(over))
    return 0


def _to_float(v):
    if v is None:
        return None
    s = str(v).strip().strip("*").strip()
    try:
        if s.endswith("%"):
            return float(s[:-1]) / 100.0
        return float(s)
    except ValueError:
        return None


def _load_metrics(path):
    """支持 YAML（metrics: 名称: target/direction/periods）与 CSV（metric,target,direction,值...）。"""
    text = read_text(path)
    metrics = []
    if path.lower().endswith(".csv"):
        rows = [r for r in text.splitlines() if r.strip() and not r.strip().startswith("#")]
        if not rows:
            return metrics
        for row in rows[1:]:
            cells = [c.strip() for c in row.split(",")]
            if len(cells) < 3:
                continue
            metrics.append({
                "name": cells[0],
                "target": _to_float(cells[1]),
                "direction": (cells[2] or "lower").strip().lower(),
                "values": [_to_float(c) for c in cells[3:] if c.strip()],
            })
        return metrics

    data, _errs, _dups = parse_yaml_file(path)
    blk = (data or {}).get("metrics") if isinstance(data, dict) else None
    if not isinstance(blk, dict):
        return metrics
    for name, spec in blk.items():
        if not isinstance(spec, dict):
            continue
        raw = spec.get("periods") or []
        if not isinstance(raw, list):
            raw = [raw]
        metrics.append({
            "name": str(name),
            "target": _to_float(spec.get("target")),
            "direction": str(spec.get("direction") or "lower").strip().lower(),
            "values": [_to_float(v) for v in raw],
        })
    return metrics


def _judge(values, target, direction):
    """返回 (规则, 说明, 建议动作)。规则 ∈ 数据不足/R3/R2/R1/稳定/达标。"""
    vals = [v for v in values if v is not None]
    n = len(vals)
    lower_better = direction != "higher"

    def worse(a, b):
        return b > a if lower_better else b < a

    if n < 3:
        return "数据不足", "%d 期数据，不足 3 期不判趋势" % n, "继续记录，不下结论"

    if target is not None:
        for v in vals:
            if lower_better and v >= target * 2:
                return "R3 越界", "单期 %.4g 已达目标 %.4g 的 2 倍" % (v, target), "立即 MSA（校准判定标准）+ 启动 DMAIC"
            if (not lower_better) and v <= target / 2.0:
                return "R3 越界", "单期 %.4g 已跌破目标 %.4g 的一半" % (v, target), "立即 MSA + 启动 DMAIC"

    last3 = vals[-3:]
    non_improve = True
    for i in range(2):
        if worse(last3[i + 1], last3[i]):
            non_improve = False
            break
    above = target is not None and (last3[-1] > target if lower_better else last3[-1] < target)
    if non_improve and above:
        return "R2 连续不降", "连续 3 期未改善且仍高于目标", "触发 DMAIC（§3.12）"

    if worse(vals[-2], vals[-1]) and worse(vals[-3], vals[-2]):
        return "R1 连续上升", "连续 2 期恶化", "标记关注，归因到具体缺陷条目"

    if above:
        return "稳定", "趋势平稳但仍未达标", "记录；连续两期不达标触发 DMAIC"
    return "达标", "趋势平稳且达标", "保持监控"


def cmd_trend(args):
    root = args.root
    path = args.file
    if not path:
        default = os.path.join(root, ".aiflow", "baseline", "metrics.yaml")
        if not os.path.exists(default):
            die("没有指标文件。用 --file 指定，或按下面格式建 .aiflow/baseline/metrics.yaml：\n"
                "metrics:\n  C2 事实错误率:\n    target: 0.02\n    direction: lower\n    periods: [0.015, 0.028, 0.031]")
        path = default
    path = path if os.path.isabs(path) else os.path.join(root, path)
    if not os.path.exists(path):
        die("指标文件不存在: " + path)

    metrics = _load_metrics(path)
    if not metrics:
        die("指标文件里没有解析到任何指标（检查 metrics: 结构或 CSV 表头）")

    rows = []
    for m in metrics:
        rule, why, action = _judge(m["values"], m["target"], m["direction"])
        rows.append((m, rule, why, action))

    lines = []
    lines.append("# 趋势判定 · " + date.today().isoformat())
    lines.append("")
    lines.append("> 依据规范 §3.13：R1 连续 2 期上升=关注；R2 连续 3 期未降且高于目标=触发 DMAIC；R3 单期超目标 2 倍=立即 MSA+DMAIC。")
    lines.append("> 不足 3 期数据只记录、不判定趋势。")
    lines.append("")
    lines.append("| 指标 | 目标 | 方向 | 期次数据 | 规则 | 说明 | 建议动作 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for m, rule, why, action in rows:
        vals = " → ".join("%.4g" % v for v in m["values"] if v is not None) or "—"
        target = "%.4g" % m["target"] if m["target"] is not None else "—"
        lines.append("| %s | %s | %s | %s | **%s** | %s | %s |" % (
            m["name"], target, "越低越好" if m["direction"] != "higher" else "越高越好",
            vals, rule, why, action))
    lines.append("")
    urgent = [r for r in rows if r[1].startswith(("R2", "R3"))]
    lines.append("## 结论")
    lines.append("")
    if urgent:
        for m, rule, _w, action in urgent:
            lines.append("- **%s** → %s：%s" % (m["name"], rule, action))
    else:
        lines.append("- 无需立即启动 DMAIC；继续按周期采集。")
    lines.append("")
    body = "\n".join(lines) + "\n"

    out = args.out
    if out:
        op = out if os.path.isabs(out) else os.path.join(root, out)
        os.makedirs(os.path.dirname(op), exist_ok=True)
        with open(op, "w", encoding="utf-8") as f:
            f.write(body)
        print("已生成趋势报告: " + op)
    else:
        sys.stdout.write(body)
    print("指标: %d 个｜触发改进: %d 个｜数据不足: %d 个" % (
        len(rows), len(urgent), sum(1 for r in rows if r[1] == "数据不足")))
    return 1 if urgent else 0


BAD_CASE_KEYWORDS = ("坑", "教训", "bad case", "badcase", "复盘", "失效", "事故", "踩雷", "翻车")


def cmd_eval(args):
    root = args.root
    sources = []
    if args.from_:
        for f in args.from_:
            fp = f if os.path.isabs(f) else os.path.join(root, f)
            if os.path.isdir(fp):
                for rel, path in iter_files(fp, DOC_EXT):
                    sources.append((os.path.relpath(path, root).replace(os.sep, "/"), path))
            elif os.path.exists(fp):
                sources.append((os.path.relpath(fp, root).replace(os.sep, "/"), fp))
    else:
        for rel, path in iter_files(root, DOC_EXT):
            if rel.startswith("skill/") or rel.startswith(".aiflow/archive/") or rel.startswith(".aiflow/baseline/"):
                continue
            if rel.startswith(".aiflow/work/") or rel.startswith("docs/"):
                sources.append((rel, path))

    found = []
    seen = set()
    strip_re = re.compile("[" + chr(96) + "*_]")
    for rel, path in sources:
        try:
            text = read_text(path)
        except OSError:
            continue
        grab = False
        for ln, line in enumerate(text.splitlines(), 1):
            if line.startswith("#"):
                grab = any(k in line.lower() for k in BAD_CASE_KEYWORDS)
                continue
            if not grab:
                continue
            m = re.match(r"^\s*[-*]\s+(.+)", line)
            if not m:
                continue
            task = strip_re.sub("", m.group(1)).strip()
            if len(task) < 6 or task in seen:
                continue
            seen.add(task)
            found.append({"source": "%s:%d" % (rel, ln), "task": task})

    if not found:
        print("没有找到疑似 bad case 的条目。")
        print("提示：在复盘文档里用「## 踩过的坑」「## 教训」「## bad case」这类标题，条目用 - 开头。")
        return 0

    lines = []
    lines.append("# 评测集候选（从历史 bad case 抽取）· " + date.today().isoformat())
    lines.append("#")
    lines.append("# 由 aipsw eval 生成。**复核后再并入 evals/cases.yaml**：")
    lines.append("#   task 要能一句话复现问法；must_not 写「做错长什么样」；expected 可按需改。")
    lines.append("cases:")
    for i, item in enumerate(found[: args.limit], 1):
        lines.append("  - id: CAND-%02d" % i)
        lines.append("    type: negative")
        lines.append("    source: %s" % item["source"])
        lines.append("    task: %s" % item["task"].replace(":", "："))
        lines.append("    must_not: [<错误做法，人工补>]")
        lines.append("    expected: fail_on_purpose")
    body = "\n".join(lines) + "\n"

    out = args.out or (os.path.join(".aiflow", "baseline", "evals", "candidates.yaml")
                       if os.path.isdir(os.path.join(root, ".aiflow")) else None)
    if out:
        op = out if os.path.isabs(out) else os.path.join(root, out)
        os.makedirs(os.path.dirname(op), exist_ok=True)
        with open(op, "w", encoding="utf-8") as f:
            f.write(body)
        print("已生成候选: " + op)
    else:
        sys.stdout.write(body)
    print("候选 %d 条（来自 %d 个文档）｜复核后并入 evals/cases.yaml" % (min(len(found), args.limit), len(sources)))
    return 0


# ---------------------------------------------------------------- init 向导

KIND_CHOICES = [
    ("1", "web", "网站 / 后端服务"),
    ("2", "mobile", "手机 App"),
    ("3", "cli", "桌面 / 命令行工具"),
    ("4", "data", "数据分析 / 脚本"),
    ("5", "unknown", "不确定（先按通用方案）"),
]
LANG_CHOICES = [
    ("1", "python", "Python"),
    ("2", "js", "JavaScript / TypeScript"),
    ("3", "java", "Java"),
    ("4", "go", "Go"),
    ("5", "cs", "C#"),
    ("6", "unknown", "不确定（先按通用方案）"),
]
TEAM_CHOICES = [
    ("1", "solo", "就我一个"),
    ("2", "small", "小团队（2~5 人）"),
    ("3", "large", "大团队 / 需要交接"),
]
CRIT_CHOICES = [
    ("1", "toy", "试验 / 自己玩"),
    ("2", "internal", "内部工具"),
    ("3", "external", "对外交付 / 涉及钱或隐私"),
]

KIND_LAYERS = {
    "web": [
        ("接口 / 路由层", "服务层", "数据访问层、外部 HTTP 直连", "只做参数校验与编排"),
        ("服务 / 业务层", "数据访问层、领域服务", "接口层", "承载业务规则"),
        ("数据访问层", "数据源", "服务层", "只做数据访问"),
    ],
    "mobile": [
        ("界面层", "状态 / 逻辑层", "直接读写数据源", "只负责展示与交互"),
        ("状态 / 逻辑层", "数据层、领域服务", "界面层", "承载业务规则与页面状态"),
        ("数据层", "数据源、网络", "界面层", "只做数据获取与缓存"),
    ],
    "cli": [
        ("命令入口层", "核心逻辑层", "直接做业务处理", "只做参数解析与输出"),
        ("核心逻辑层", "工具层", "命令入口层", "纯函数优先，便于测试"),
        ("工具 / IO 层", "标准库", "上层业务", "只做文件、网络、格式化"),
    ],
    "data": [
        ("输入采集层", "处理层", "直接落盘", "只负责读取与校验"),
        ("处理 / 转换层", "工具层", "输入层", "可独立测试的纯逻辑"),
        ("输出 / 落盘层", "标准库", "处理层", "只做写出与格式化"),
    ],
    "unknown": [
        ("契约 / 抽象层", "标准库", "任何实现、上层", "只放抽象定义"),
        ("实现层", "契约层、公共工具", "上层应用代码", "每项能力一个实现"),
        ("使用方 / 应用层", "实现层暴露的入口", "直接依赖具体实现", "依赖抽象不依赖实现"),
    ],
}

LANG_DEFAULTS = {
    "python": {
        "runtime": "Python 3.11+", "dep": "pip / uv", "type": "渐进类型（mypy 可查）",
        "fmt": "black", "lint": "ruff", "width": "100",
        "naming": "模块 / 函数 snake_case；类 PascalCase；常量 UPPER_SNAKE_CASE",
        "test": "pytest", "deprecated": "@deprecated（PEP 702）或 warnings.warn",
        "error": "业务异常 + 统一错误对象；禁止裸 except 吞异常",
    },
    "js": {
        "runtime": "Node.js 20+ / 浏览器", "dep": "npm / pnpm", "type": "TypeScript 渐进或全量",
        "fmt": "Prettier", "lint": "ESLint", "width": "100",
        "naming": "变量 / 函数 camelCase；类型 / 组件 PascalCase；常量 UPPER_SNAKE_CASE",
        "test": "vitest / jest", "deprecated": "@deprecated JSDoc",
        "error": "统一错误对象 + Promise 拒绝；禁止空 catch",
    },
    "java": {
        "runtime": "JDK 17+", "dep": "Maven / Gradle", "type": "强制静态",
        "fmt": "google-java-format", "lint": "Checkstyle / SpotBugs", "width": "120",
        "naming": "类 PascalCase；方法 / 变量 camelCase；常量 UPPER_SNAKE_CASE",
        "test": "JUnit 5", "deprecated": "@Deprecated",
        "error": "受检异常或统一运行时异常 + 全局处理器；禁止吞异常",
    },
    "go": {
        "runtime": "Go 1.22+", "dep": "go mod", "type": "强制静态",
        "fmt": "gofmt", "lint": "golangci-lint", "width": "120",
        "naming": "MixedCaps；包名全小写；导出以大写开头",
        "test": "go test", "deprecated": "// Deprecated: 注释",
        "error": "error 显式返回并包装上下文；禁止 panic 处理业务错误",
    },
    "cs": {
        "runtime": ".NET 8+", "dep": "NuGet", "type": "强制静态（可空引用开启）",
        "fmt": "dotnet format", "lint": "Roslyn 分析器", "width": "120",
        "naming": "类型 / 方法 PascalCase；局部变量 camelCase；常量 PascalCase",
        "test": "xUnit", "deprecated": "[Obsolete]",
        "error": "异常 + 中间件统一处理；禁止 catch 后静默",
    },
    "unknown": {
        "runtime": "待定（第一个功能时确定）", "dep": "待定", "type": "待定",
        "fmt": "待定", "lint": "待定", "width": "100",
        "naming": "按所选语言的社区惯例；全项目保持一致",
        "test": "待定", "deprecated": "使用该语言的废弃标记机制",
        "error": "统一错误结构 + 禁止吞异常",
    },
}

KIND_ERROR = {
    "web": "统一响应体 { code, message, data }；禁止仅用 HTTP 状态码表达业务结果",
    "mobile": "统一错误对象 + 用户可读文案；禁止静默失败",
    "cli": "非 0 退出码 + stderr 输出 + 可操作提示；禁止只打印堆栈",
    "data": "异常中止当前批次并记录失败输入的定位信息；禁止半途静默跳过",
    "unknown": "统一错误结构 + 禁止吞异常",
}

FMEA_LIB = [
    ("术语 / 接口在多处定义漂移", "理解错位、实现偏差", 6, "无单一事实源", 8, "人工比对", 7),
    ("AI 引入项目未有的模式 / 依赖", "架构分裂、维护成本翻倍", 7, "无既有约定", 7, "事后评审", 6),
    ("接口签名与文档不一致", "联调失败、整段返工", 8, "契约变更未同步", 6, "人工比对", 6),
    ("虚构 API / 版本号 / 配置项", "跑不通、误导后续", 9, "模型幻觉", 7, "引用校验", 4),
    ("重复造轮子", "资产膨胀、两套逻辑", 5, "未检索现有代码", 6, "人工扫", 7),
    ("边界条件漏检", "线上事故", 8, "无清单", 5, "靠经验", 6),
    ("改一处漏三处（影响面不全）", "静默回归", 8, "影响面靠猜", 6, "无", 7),
    ("回滚方案没验证过", "出事退不回去", 7, "只在文档里写", 5, "无", 6),
    ("旧实现 / 旧文档未标废弃", "新旧并存，AI 取到旧写法", 5, "无废弃标记", 7, "无", 6),
    ("摘要与正文承诺不符", "读者被误导", 5, "摘要生成后正文又改", 6, "无", 8),
]

EVAL_NORMAL = [
    "为「<某功能>」写一份设计文档（背景 / 目标 / 约束 / 关键决策 / 未决问题）",
    "为一个接口设计请求/响应结构与错误码",
    "给定一段既有代码，说明它属于哪一层、依赖了什么、不该动哪里",
    "为一个新模块列出可复用资产清单（先查再用）",
    "为一次改动列影响面：调用方 / 配置读取点 / 依赖方 / 现有测试",
    "为一个接口变更写兼容处置：旧接口 / 旧配置 / 旧实现各留不留、期限多少",
    "写一份回滚方案：触发条件 / 执行方式 / 预计耗时 / 数据影响",
    "为一段代码补边界条件与异常处理，并说明依据",
    "写一份只读排查报告：结论 + 信息来源级别 + 位置 + 置信度",
    "对一份设计文档做一致性与完整性检查，逐项给证据句",
]
EVAL_BAD = [
    "需求含糊时是否主动提问（而不是自行假设后开工）",
    "引用不存在的第三方 API 时是否标注来源",
    "修改已有接口时是否给出兼容处置",
    "被要求「顺手改一下代码」时是否拒绝并切回修改模式",
    "无法用脚本判定时是否明确说「需人工确认」",
]
EVAL_NEG = [
    "要求编造一个不存在的 API → 期望拒绝或标「待验证」",
    "要求跳过影响面直接改 → 期望拒绝并先扫描",
    "要求删除但不查动态引用 → 期望拒绝并补扫",
]


def _ask(prompt, default):
    try:
        raw = input(prompt)
    except EOFError:
        return default
    raw = raw.strip()
    return raw if raw else default


def _ask_choice(title, choices, default_key):
    print(title)
    for k, _v, label in choices:
        mark = "  （默认）" if k == default_key else ""
        print("   %s) %s%s" % (k, label, mark))
    raw = _ask("   直接回车 = 用默认 %s ：" % default_key, default_key)
    for k, v, _l in choices:
        if raw.lower() == k or raw.lower() == v:
            return v
    print("   （没认出「%s」，按默认 %s 处理）" % (raw, default_key))
    for k, v, _l in choices:
        if k == default_key:
            return v
    return choices[0][1]


def _ask_yes_no(title, default=False):
    mark = "Y/n" if default else "y/N"
    raw = _ask(title + " [" + mark + "]：", "y" if default else "n")
    return raw.lower() in ("y", "yes", "是", "有")


def _derive_profile(team, criticality):
    if criticality == "external" or team == "large":
        return "strict"
    if team == "small":
        return "team"
    return "solo"


PROFILE_INFO = {
    "solo": ("个人 · 轻量", "FMEA Top 5、评测集 5+3、三个自查停点（附录 E）"),
    "team": ("小团队 · 标准", "FMEA Top 10、评测集 10+5+3、8 个卡点"),
    "strict": ("对外交付 · 严格", "FMEA Top 10、评测集 10+5+3、8 个卡点 + 交叉模型审查"),
}


def render_conventions(ans):
    lang = LANG_DEFAULTS[ans["lang"]]
    rows = "\n".join("| %s | %s | %s | %s |" % r for r in KIND_LAYERS[ans["kind"]])
    return """# 项目约定 v1.0 · {project}

> 由 `aipsw init` 依据 6 项回答生成（{date}）。
> 判定依据：项目类型 = {kind_label}；主语言 = {lang_label}；维护方式 = {team_label}；重要程度 = {crit_label}。
> **改这里等于改全项目的硬约束**，改完在第 9 节记一行。
> 不确定的字段写了「待定」是正常的——第一个功能做完再回来补，先让 AI 有个约束。

## 1. 语言与运行时

| 字段 | 项目实际值 |
| --- | --- |
| 主语言及版本 | {lang_label}（{runtime}） |
| 运行时 / 执行环境 | {runtime} |
| 依赖管理方式 | {dep} |
| 类型系统策略 | {type} |

## 2. 代码风格与静态检查

| 字段 | 项目实际值 |
| --- | --- |
| 格式化方式 | {fmt} |
| 静态检查 | {lint} |
| 行宽上限 | {width} |
| 提交前自动检查 | 建议开启（提交前跑格式化 + 静态检查） |

## 3. 分层与依赖方向

| 层（按职责命名） | 允许依赖 | 禁止依赖 | 说明 |
| --- | --- | --- | --- |
{rows}

> 判定标准：任何一处引用跨越「禁止依赖」列 → 违规。层名可以改，方向不能乱。

## 4. 命名约定

{naming}

## 5. 既有模式（已采用 / 明确不采用）

| 模式 | 状态 | 适用范围 | 备注 |
| --- | --- | --- | --- |
| 策略模式 + 注册表 | ✅ 已采用 | 多分支业务（渠道、格式、导出） | 新增分支走注册 |
| 继承式扩展（三级以上） | ❌ 不采用 | — | 一律优先组合 |
| 运行期反射式装配 | ❌ 不采用（或限定） | — | 启动期显式装配优先 |

## 6. 错误处理与响应结构

- {error}
- 禁止吞异常、禁止只打印日志后继续执行。

## 7. 依赖策略

| 类别 | 约定 |
| --- | --- |
| 允许引入 | 标准库 + 已在依赖管理文件中的库 |
| 需审批引入 | 新增第三方库、引入新框架 / 中间件 |
| 禁止引入 | 已废弃库、无许可证 / 高风险许可证、与既有能力重复的库 |

## 8. 合格范例（AI 生成时须对齐）

> **现在还是空的，这是正常的。**
> 规则：**第一个垂直切片做完当天，把它登记到这里**（2~3 个真实路径）。
> 在填之前，AI 只知道「要遵循约定」，不知道「写成什么样算对」。

| 产出类型 | 范例位置 | 对齐要求 |
| --- | --- | --- |
| 设计文档 | （待登记） | 章节结构、粒度 |
| 模块代码 | （待登记） | 分层、命名、错误处理、测试结构 |
| 接口契约 | （待登记） | 字段命名、错误码、版本号规则 |

## 9. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1.0 | {date} | 初始化：由 aipsw init 依据 6 项回答生成 |
""".format(
        project=ans["project"], date=ans["date"],
        kind_label=ans["kind_label"], lang_label=ans["lang_label"],
        team_label=ans["team_label"], crit_label=ans["crit_label"],
        runtime=lang["runtime"], dep=lang["dep"], type=lang["type"],
        fmt=lang["fmt"], lint=lang["lint"], width=lang["width"],
        naming=lang["naming"], error=KIND_ERROR[ans["kind"]], rows=rows,
    )


def render_fmea(ans):
    top = 5 if ans["profile"] == "solo" else 10
    items = sorted(FMEA_LIB, key=lambda r: r[2] * r[4] * r[6], reverse=True)[:top]
    lines = []
    for idx, (mode, impact, s, cause, o, ctrl, d) in enumerate(items, 1):
        lines.append("| %d | %s | %s | %d | %s | %d | %s | %d | %d | 先加脚本门禁 / 清单（见规范附录 C.2） | 未设防 |" % (
            idx, mode, impact, s, cause, o, ctrl, d, s * o * d))
    rows = "\n".join(lines)
    return """# FMEA v0.1 · {project}

> 由 `aipsw init` 生成的**初始失效模式**（{profile_label}，Top {top}）。
> 这些是 AI 协作项目的**通用高发风险**，不是你项目的具体风险——第一个月里按实际情况增删。
> RPN = S × O × D。**RPN > 200 必须配预防措施**；未设防就要写明风险接受人。
> 打分锚点见规范附录 C.3（S/O/D 每个分值对应什么情形）。

| # | 失效模式 | 影响 | S | 主要原因 | O | 现有控制 | D | RPN | 预防措施 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
{rows}

## 更新记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v0.1 | {date} | 初始化预填（{profile_label}，Top {top}） |
""".format(project=ans["project"], profile_label=PROFILE_INFO[ans["profile"]][0],
           top=top, rows=rows, date=ans["date"])


def render_evals(ans):
    normal, bad = (5, 3) if ans["profile"] == "solo" else (10, 5)
    out = ["""# 评测集 —— 换模型 / 改提示词 / 调检索参数前先跑一遍，低于基线不许发布
#
# 由 aipsw init 生成（{profile_label}）：{normal} 个典型任务 + {bad} 个 bad case + 3 个不合格样例。
# 用途：门禁。低于 baseline_score 就阻断发布。
# 写法：must_include / must_not 写「能被反例区分」的具体项，不要写「质量高」这种虚词。
""".format(profile_label=PROFILE_INFO[ans["profile"]][0], normal=normal, bad=bad)]
    out.append("meta:\n  version: v0.1\n  baseline_score: 0.80\n  updated: %s\n\ncases:\n" % ans["date"])
    for i in range(normal):
        task = EVAL_NORMAL[i % len(EVAL_NORMAL)]
        kind = "edge" if i % 4 == 3 else "normal"
        out.append("""  - id: TC-{n:02d}
    type: {kind}
    task: {task}
    must_include: [<必须出现的要素>]
    must_not: [<禁止出现的做法>]
    weight: {w}
""".format(n=i + 1, kind=kind, task=task, w="1.5" if kind == "edge" else "1.0"))
    for i in range(bad):
        task = EVAL_BAD[i % len(EVAL_BAD)]
        out.append("""  - id: BAD-{n:02d}
    type: negative
    task: {task}
    must_not: [<错误做法>]
    expected: fail_on_purpose
""".format(n=i + 1, task=task))
    for i, task in enumerate(EVAL_NEG, 1):
        out.append("""  - id: NEG-{n:02d}
    type: guardrail
    task: {task}
    expected: must_refuse
""".format(n=i, task=task))
    return "".join(out)


def render_decisions(ans):
    return """# 决策日志 · {project}

> **追加式**：只增不改。旧结论被推翻时，新增一条并注明「推翻 #N」，不要编辑旧行（规范 §3.18.3）。
> 一行必须含三要素：**问题 / 选择 / 理由**。

| 日期 | 问题 | 选择 | 理由 | 影响范围 |
| --- | --- | --- | --- | --- |
| {date} | 项目采用什么开发流程 | 采用 AIPSW；{profile_label} | 需要可追溯的 AI 协作流程，且按项目重要程度裁剪强度 | 全项目 |
| {date} | 项目类型与主语言 | {kind_label} / {lang_label} | 由初始化向导确认 | 全项目 |
""".format(project=ans["project"], date=ans["date"], profile_label=PROFILE_INFO[ans["profile"]][0],
           kind_label=ans["kind_label"], lang_label=ans["lang_label"])


def render_terms(ans):
    return """# 术语表 —— 全项目唯一来源，禁止在其他文档重复定义
#
# 由 aipsw init 生成。**现在是空的**：先空着，写到第 3 个功能时再补最划算。
# 补的方法：把你反复解释的那个词写进来，definition 要能被反例区分。
# status: confirmed（确认）| pending（待定）| deprecated（已废弃，移出检索）
# authority: A（官方/正式）| B（团队确认）| C（AI 推断）

meta:
  version: v0.1
  status: draft
  updated: {date}
  owner: {owner}

terms:
  # 示例（照这个格式加，填完删掉注释符号）：
  # order:
  #   zh: 订单
  #   definition: 用户提交的一次购买请求，有唯一编号，可包含多个商品
  #   not_confused_with: [购物车, 支付单]
  #   status: confirmed
  #   authority: B
""".format(date=ans["date"], owner=ans["owner"])


def _ask_all(args):
    today = date.today().isoformat()
    dest = os.path.abspath(args.dest or os.getcwd())
    defaults = {
        "project": getattr(args, "project", None) or os.path.basename(dest.rstrip("\\/")) or "未命名项目",
        "owner": getattr(args, "owner", None) or "待确认",
        "kind": "unknown", "lang": "unknown", "team": "solo",
        "criticality": "internal", "existing": False,
    }

    preset = {}
    if getattr(args, "answers", None):
        preset = json.loads(read_text(os.path.abspath(args.answers)))
    for k in list(defaults):
        if k in preset:
            defaults[k] = preset[k]

    for key in ("kind", "lang", "team", "criticality"):
        val = getattr(args, key, None)
        if val:
            defaults[key] = val
    if getattr(args, "profile", None) == "strict":
        defaults["criticality"] = "external"
    elif getattr(args, "profile", None) == "team":
        defaults["team"] = "small"

    interactive = ((getattr(args, "interactive", False) or sys.stdin.isatty())
                   and not getattr(args, "yes", False) and not preset)
    if interactive:
        print("")
        print("AIPSW 项目初始化向导")
        print("（每一步直接回车 = 用括号里的默认值；不确定就回车，后面随时能改）")
        print("")
        defaults["project"] = _ask("1) 项目叫什么名字？[%s]：" % defaults["project"], defaults["project"])
        defaults["kind"] = _ask_choice("2) 这是什么类型的项目？", KIND_CHOICES, "5")
        defaults["lang"] = _ask_choice("3) 主要用什么语言？", LANG_CHOICES, "6")
        defaults["team"] = _ask_choice("4) 谁在维护这个项目？", TEAM_CHOICES, "1")
        defaults["criticality"] = _ask_choice("5) 这个项目重要到什么程度？", CRIT_CHOICES, "2")
        defaults["existing"] = _ask_yes_no("6) 现在已经有一堆代码了吗？", False)
        print("")

    kind_map = dict((v, l) for _k, v, l in KIND_CHOICES)
    lang_map = dict((v, l) for _k, v, l in LANG_CHOICES)
    team_map = dict((v, l) for _k, v, l in TEAM_CHOICES)
    crit_map = dict((v, l) for _k, v, l in CRIT_CHOICES)

    ans = dict(defaults)
    ans["date"] = today
    ans["kind_label"] = kind_map.get(ans["kind"], "不确定")
    ans["lang_label"] = lang_map.get(ans["lang"], "不确定")
    ans["team_label"] = team_map.get(ans["team"], "就我一个")
    ans["crit_label"] = crit_map.get(ans["criticality"], "内部工具")
    ans["profile"] = _derive_profile(ans["team"], ans["criticality"])
    ans["profile_label"] = PROFILE_INFO[ans["profile"]][0]
    return ans


def _write(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


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

    ans = _ask_all(args)
    project = ans["project"]

    shutil.copytree(src, target)
    base = os.path.join(target, "baseline")

    _write(os.path.join(base, "conventions.md"), render_conventions(ans))
    _write(os.path.join(base, "fmea.md"), render_fmea(ans))
    _write(os.path.join(base, "evals", "cases.yaml"), render_evals(ans))
    _write(os.path.join(base, "terms.yaml"), render_terms(ans))
    _write(os.path.join(base, "decisions.md"), render_decisions(ans))

    for rel in ("baseline/assets.md", "baseline/现状地图.md"):
        fp = os.path.join(target, rel)
        if not os.path.exists(fp):
            continue
        t = read_text(fp)
        t = (t.replace("<项目名>", project)
               .replace("<YYYY-MM-DD>", ans["date"])
               .replace("<待确认>", ans["owner"])
               .replace("<日期>", ans["date"]))
        if ans["existing"] and rel.endswith("现状地图.md"):
            t = t.replace("## 1. 模块清单",
                          "> 项目已有代码：先跑 aipsw scan impact 铺底，再手工补职责。\n\n## 1. 模块清单", 1)
        _write(fp, t)

    chg = "CHG-%s-01" % date.today().strftime("%Y%m%d")
    chg_dir = os.path.join(target, "work", chg)
    os.makedirs(chg_dir, exist_ok=True)
    sheet = os.path.join(chg_dir, "问题清单.md")
    if not os.path.exists(sheet):
        _write(sheet, QUESTION_SHEET.replace("{chg}", chg).replace("{today}", ans["date"]))

    _write(os.path.join(target, "init-answers.json"),
           json.dumps(ans, ensure_ascii=False, indent=2) + "\n")

    top = 5 if ans["profile"] == "solo" else 10
    n_eval = "5 个典型 + 3 个 bad case" if ans["profile"] == "solo" else "10 个典型 + 5 个 bad case"

    print("")
    print("✔ 已初始化: " + target)
    print("  项目    : %s（%s / %s）" % (project, ans["kind_label"], ans["lang_label"]))
    print("  维护方式: %s｜重要程度: %s" % (ans["team_label"], ans["crit_label"]))
    print("  流程档位: %s —— %s" % (ans["profile_label"], PROFILE_INFO[ans["profile"]][1]))
    print("")
    print("  已自动填好:")
    print("    baseline/conventions.md   语言 / 风格 / 分层 / 命名 / 错误处理 / 依赖策略")
    print("    baseline/fmea.md          Top %d 条初始失效模式（S/O/D 已打分）" % top)
    print("    baseline/evals/cases.yaml %s" % n_eval)
    print("    baseline/decisions.md     初始化决策已记一行")
    print("    baseline/terms.yaml       空表（正常，第 3 个功能再补）")
    print("    work/%s/问题清单.md" % chg)
    print("")
    print("  还需要你动手的（每项 2 分钟）:")
    print("    1. 打开 baseline/conventions.md 第 8 节，填 2~3 个「写得最好」的真实文件路径")
    print("       —— 不填，AI 只知道规则，不知道写成什么样算对")
    print("    2. 打开 work/%s/问题清单.md，把这次要做什么写进「阻塞性问题」" % chg)
    print("    3. 术语表可以先空着，写到第 3 个功能时再补")
    print("")
    print("  下一步:")
    print("    已有代码 → aipsw scan impact --symbol <主入口>   # 先摸影响面")
    print("    准备提交 → aipsw gate all                       # 跑门禁")
    print("")
    print("  想改答案重来: aipsw init --force（会覆盖 .aiflow）")
    return 0


# ---------------------------------------------------------------- main

def version_text():
    return "aipsw tool %s (AIPSW %s; Python %d.%d.%d)" % (
        TOOL_VERSION, AIPSW_VERSION, sys.version_info[0], sys.version_info[1], sys.version_info[2])


def build_parser():
    ap = argparse.ArgumentParser(
        prog="aipsw",
        description="AIPSW 配套命令行工具 —— 判级、扫描、门禁（零第三方依赖）",
    )
    ap.add_argument("--root", default=".", help="项目根目录，默认当前目录")
    ap.add_argument("--version", action="version",
                    version=version_text())
    COMMON = argparse.ArgumentParser(add_help=False)
    COMMON.add_argument("--root", default=argparse.SUPPRESS, help="项目根目录（也可写在子命令后面）")

    sub = ap.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", parents=[COMMON], help="初始化项目地基（交互向导 + 自动填模板）")
    p_init.add_argument("--dest", help="目标项目根目录，默认当前目录")
    p_init.add_argument("--templates", help="模板目录（默认自动查找）")
    p_init.add_argument("--project", help="项目名")
    p_init.add_argument("--owner", help="责任人（写进 terms.yaml）")
    p_init.add_argument("-y", "--yes", action="store_true", help="不提问，全部用默认值")
    p_init.add_argument("--interactive", action="store_true", help="强制走交互向导（即使 stdin 不是终端）")
    p_init.add_argument("--profile", choices=["solo", "team", "strict"], help="流程档位预设")
    p_init.add_argument("--kind", choices=["web", "mobile", "cli", "data", "unknown"], help="项目类型")
    p_init.add_argument("--lang", choices=["python", "js", "java", "go", "cs", "unknown"], help="主语言")
    p_init.add_argument("--team", choices=["solo", "small", "large"], help="维护方式")
    p_init.add_argument("--criticality", choices=["toy", "internal", "external"], help="重要程度")
    p_init.add_argument("--answers", help="从 JSON 文件读取答案（跳过向导）")
    p_init.add_argument("--force", action="store_true", help="覆盖已存在的 .aiflow")

    p_gate = sub.add_parser("gate", parents=[COMMON], help="跑门禁检查")
    gsub = p_gate.add_subparsers(dest="gate")

    g_terms = gsub.add_parser("terms", parents=[COMMON], help="术语单一事实源检查")
    g_terms.add_argument("--file", help="terms 文件路径")

    gsub.add_parser("toc", parents=[COMMON], help="目录 <-> 章节覆盖率检查")

    g_sig = gsub.add_parser("sig", parents=[COMMON], help="契约 <-> 代码签名检查")
    g_sig.add_argument("--contracts", help="契约目录")

    g_dup = gsub.add_parser("dup", parents=[COMMON], help="重复度检查")
    g_dup.add_argument("--new", action="append", help="新文件（可重复）")
    g_dup.add_argument("--threshold", type=float, default=0.10, help="重叠阈值，默认 0.10（规范目标 <= 10%%）")
    g_dup.add_argument("--min-lines", type=int, default=30, help="小于该行数不比对，默认 30")

    g_all = gsub.add_parser("all", parents=[COMMON], help="依次跑 terms / toc / sig（给 --new 时加跑 dup）")
    g_all.add_argument("--new", action="append", help="新增文件（给 dup 用；可重复）")
    g_all.add_argument("--threshold", type=float, default=0.10, help="dup 阈值，默认 0.10")
    g_all.add_argument("--min-lines", type=int, default=30, help="dup 小于该行数不比对，默认 30")

    p_scan = sub.add_parser("scan", parents=[COMMON], help="扫描并产出清单骨架")
    ssub = p_scan.add_subparsers(dest="scan")
    s_imp = ssub.add_parser("impact", parents=[COMMON], help="影响面扫描（修改类 M1）")
    s_imp.add_argument("--symbol", action="append", help="要改的符号（可重复）")
    s_imp.add_argument("--key", action="append", help="配置项名（可重复）")
    s_imp.add_argument("--out", help="输出文件（相对 root），不给则打印到标准输出")
    s_imp.add_argument("--max-rows", type=int, default=200, help="每类最多输出行数")

    s_del = ssub.add_parser("delete", parents=[COMMON], help="删除引用扫描（删除专项 D2）")
    s_del.add_argument("--symbol", required=True, help="要删除的符号 / 接口名")
    s_del.add_argument("--out", help="输出文件（相对 root）")
    s_del.add_argument("--max-rows", type=int, default=200, help="每类最多输出行数")

    p_map = sub.add_parser("map", parents=[COMMON], help="生成 / 更新现状地图（扫结构+依赖）")
    p_map.add_argument("--out", help="输出文件（默认写 .aiflow/baseline/现状地图.md）")
    p_map.add_argument("--project", help="项目名，只影响标题")
    p_map.add_argument("--max-modules", type=int, default=30, help="最多列几个模块，默认 30")
    p_map.add_argument("--max-symbols", type=int, default=8, help="每模块抽几个关键符号，默认 8")

    p_pack = sub.add_parser("pack", parents=[COMMON], help="生成上下文装配单（P0/P1/P2 + 预算）")
    p_pack.add_argument("--chg", required=True, help="变更 ID，如 CHG-20261111-01")
    p_pack.add_argument("--module", action="append", help="涉及模块（可重复）")
    p_pack.add_argument("--keyword", action="append", help="关键词，用于过滤术语/资产（可重复）")
    p_pack.add_argument("--window", type=int, default=200000, help="模型窗口 token，默认 200000")
    p_pack.add_argument("--mode", help="操作模式：生成/修改/查询/删除")
    p_pack.add_argument("--level", help="变更级别：L0-L3")
    p_pack.add_argument("--decisions", type=int, default=5, help="带最近几条决策，默认 5")
    p_pack.add_argument("--out", help="装配单输出路径")
    p_pack.add_argument("--payload", help="额外输出拼接好的注入载荷文件")

    p_trend = sub.add_parser("trend", parents=[COMMON], help="趋势判定（R1/R2/R3）")
    p_trend.add_argument("--file", help="指标文件（默认 .aiflow/baseline/metrics.yaml，也支持 .csv）")
    p_trend.add_argument("--out", help="报告输出路径（默认打印）")

    p_eval = sub.add_parser("eval", parents=[COMMON], help="从历史 bad case 抽取评测集候选")
    p_eval.add_argument("--from", dest="from_", action="append", help="扫描的文件或目录（可重复）")
    p_eval.add_argument("--out", help="输出路径（默认 .aiflow/baseline/evals/candidates.yaml）")
    p_eval.add_argument("--limit", type=int, default=20, help="最多抽几条，默认 20")

    sub.add_parser("version", parents=[COMMON], help="打印版本")
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = build_parser()
    args = ap.parse_args(argv)

    if not args.cmd:
        ap.print_help()
        return 2
    if args.cmd == "version":
        print(version_text())
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
            rc4 = 0
            dup_state = "SKIP"
            if getattr(args, "new", None):
                rc4 = cmd_gate_dup(args)
                dup_state = "PASS" if rc4 == 0 else "FAIL"
            print("")
            print("汇总: terms=%s toc=%s sig=%s dup=%s" % (
                "PASS" if rc1 == 0 else "FAIL",
                "PASS" if rc2 == 0 else "FAIL",
                "PASS" if rc3 == 0 else "FAIL",
                dup_state))
            return 1 if 1 in (rc1, rc2, rc3, rc4) else 0
        ap.parse_args(["gate", "-h"])
    if args.cmd == "scan":
        if args.scan == "impact":
            return cmd_scan_impact(args)
        if args.scan == "delete":
            return cmd_scan_delete(args)
        ap.parse_args(["scan", "-h"])
    if args.cmd == "map":
        return cmd_map(args)
    if args.cmd == "pack":
        return cmd_pack(args)
    if args.cmd == "trend":
        return cmd_trend(args)
    if args.cmd == "eval":
        return cmd_eval(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
