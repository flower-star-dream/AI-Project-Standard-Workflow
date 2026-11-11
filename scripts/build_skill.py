#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包 skill/aipsw -> dist/aipsw.skill（zip，含 scripts/ 与 references/）。

Windows 上普通 zip 会丢掉执行位，别人解压到 Linux/macOS 后
scripts/aipsw.py 变成 644，入口脚本就跑不起来，所以这里显式写 0755。

用法:
    python scripts/build_skill.py            # 只打包
    python scripts/build_skill.py --check    # 打包 + 解压到临时目录跑冒烟测试
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SKILL_DIR = os.path.join(REPO, "skill", "aipsw")
DIST_DIR = os.path.join(REPO, "dist")
OUT = os.path.join(DIST_DIR, "aipsw.skill")
EXEC_NAMES = {"aipsw.py", "aipsw.ps1"}


def iter_entries():
    base = os.path.dirname(SKILL_DIR)
    for dirpath, dirnames, filenames in os.walk(SKILL_DIR):
        dirnames[:] = sorted(d for d in dirnames if d not in {"__pycache__", ".git"})
        for fn in sorted(filenames):
            if fn.endswith(".pyc") or fn == ".DS_Store":
                continue
            full = os.path.join(dirpath, fn)
            yield full, os.path.relpath(full, base).replace(os.sep, "/")


def build():
    os.makedirs(DIST_DIR, exist_ok=True)
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in iter_entries():
            info = zipfile.ZipInfo(rel, time.localtime(os.path.getmtime(full))[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if os.path.basename(rel) in EXEC_NAMES else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.create_system = 3
            with open(full, "rb") as f:
                z.writestr(info, f.read())
            count += 1
    return count


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check():
    """解压到 dist/.check，模拟别人装好后的第一次运行（不走管道，避开沙箱限制）。"""
    tmp = os.path.join(DIST_DIR, ".check")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    ok = True
    try:
        with zipfile.ZipFile(OUT) as z:
            modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
            z.extractall(tmp)
        for name in ("aipsw/scripts/aipsw.py", "aipsw/scripts/aipsw.ps1"):
            if modes.get(name) != 0o755:
                print("  [FAIL] 执行位丢失: %s -> %o" % (name, modes.get(name, 0)))
                ok = False
        root = os.path.join(tmp, "aipsw")
        script = os.path.join(root, "scripts", "aipsw.py")
        proj = os.path.join(tmp, "proj")
        steps = [
            ("version", [sys.executable, script, "version"], tmp),
            ("init", [sys.executable, script, "init", "--dest", proj], tmp),
            ("gate all", [sys.executable, script, "gate", "all"], proj),
        ]
        if sys.platform == "win32":
            steps.append(("aipsw.cmd", ["cmd", "/c", os.path.join(root, "scripts", "aipsw.cmd"), "version"], tmp))
            steps.append(("aipsw.ps1", ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                        "-File", os.path.join(root, "scripts", "aipsw.ps1"), "version"], tmp))
        for label, cmd, cwd in steps:
            try:
                code = subprocess.call(cmd, cwd=cwd)
            except OSError:
                print("  [SKIP] %s（宿主上没有这个解释器）" % label)
                continue
            print("  [%s] %-9s exit=%s" % ("OK" if code == 0 else "FAIL", label, code))
            ok = ok and code == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def main():
    n = build()
    print("已打包: %s" % OUT)
    print("  条目 %d 个，%.1f KB" % (n, os.path.getsize(OUT) / 1024.0))
    print("  sha256: %s" % sha256(OUT))
    if "--check" in sys.argv:
        print("冒烟测试（解压后从零跑一遍）:")
        if not check():
            print("打包结果不可用")
            return 1
        print("冒烟测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
