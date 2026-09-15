#!/usr/bin/env python3
"""Xem phiên Codex đang chạy như trong TUI. Ctrl-C để thoát."""
import json, sys, time, os, glob

sid = sys.argv[1] if len(sys.argv) > 1 else None
pat = os.path.expanduser("~/.codex/sessions/**/rollout-*.jsonl")
if sid:
    files = [p for p in glob.glob(pat, recursive=True) if sid in p]
else:
    files = sorted(glob.glob(pat, recursive=True), key=os.path.getmtime)[-1:]
if not files:
    sys.exit("không thấy phiên nào")
path = files[0]
print(f"\033[2m— {os.path.basename(path)} —\033[0m\n")

C = {"user": "\033[96m", "assistant": "\033[93m", "cmd": "\033[92m", "out": "\033[90m"}
R = "\033[0m"

def show(rec):
    p = rec.get("payload") or rec
    t = p.get("type") or rec.get("type") or ""
    if t == "message":
        role = p.get("role", "")
        if role in ("developer", "system"):
            return
        txt = "".join(c.get("text", "") for c in p.get("content", []) if isinstance(c, dict))
        if txt.strip():
            if len(txt) > 4000:
                txt = txt[:4000] + " …"
            print(f"{C.get(role, '')}[{role}]{R} {txt.strip()}\n")
    elif t in ("function_call", "local_shell_call"):
        args = p.get("arguments") or json.dumps(p.get("action", ""))
        try:
            cmd = json.loads(args).get("command", args)
        except Exception:
            cmd = args
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        print(f"{C['cmd']}$ {str(cmd)[:400]}{R}")
    elif t == "function_call_output":
        out = str(p.get("output", ""))[:600]
        if out.strip():
            print(f"{C['out']}{out.rstrip()}{R}\n")
    elif t == "reasoning":
        for s in p.get("summary", []):
            txt = s.get("text", "") if isinstance(s, dict) else str(s)
            if txt.strip():
                print(f"\033[95m· {txt.strip()[:400]}{R}")

with open(path, "r", encoding="utf-8", errors="replace") as f:
    while True:
        line = f.readline()
        if not line:
            time.sleep(0.4)
            continue
        try:
            show(json.loads(line))
        except Exception:
            pass
