#!/usr/bin/env python3
"""Replay real terminal tool outputs from a Hermes state.db through each truncation
method and report tokens + whether the key error line survived.
Usage: bench.py ~/.hermes/state.db [days] [budget]   -> prints JSON summary
"""
import json, os, re, sqlite3, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from squeeze import squeeze, ERRLINE, strip_progress, collapse

try:
    import tiktoken
    ENC = tiktoken.get_encoding("o200k_base")
    tok = lambda s: len(ENC.encode(s, disallowed_special=()))
    TOK = "o200k_base"
except Exception:
    tok = lambda s: (len(s) + 3) // 4
    TOK = "chars/4"

db, days = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 7
KEYRE = re.compile(os.environ.get("KEYRE", r"(Error|Exception|Traceback|FAILED|fatal:|No such file|command not found|Permission denied|timed out)"))
B = int(sys.argv[3]) if len(sys.argv) > 3 else 8000
con = sqlite3.connect(f"file:{os.path.expanduser(db)}?mode=ro", uri=True)
rows = con.execute("select content from messages where role='tool' and tool_name='terminal' "
                   "and timestamp > ?", (time.time() - days * 86400,)).fetchall()

def head(s): return s[:B]
def headtail(s):
    if len(s) <= B: return s
    return s[:B // 2] + "\n[... truncated ...]\n" + s[-B // 2:]
def headtail_n(s, n):
    if len(s) <= n: return s
    return s[:n // 2] + "\n[... truncated ...]\n" + s[-n // 2:]
def rtk(s):
    try:
        r = subprocess.run(["rtk", "log"], input=s.encode(), capture_output=True, timeout=20)
        o = r.stdout.decode("utf-8", "replace")
        return headtail(o)  # rtk output still has to fit the same budget
    except Exception:
        return headtail(s)

methods = {"raw": lambda s: s, "head": head, "head+tail": headtail,
           "rtk log": rtk, "head+tail@same-size": None, "squeeze": lambda s: squeeze(s, B, None)}
agg = {m: {"tok": 0, "tok_big": 0, "err_kept": 0} for m in methods}
n = big = errs = 0
lossless_tok = 0
for (c,) in rows:
    try:
        d = json.loads(c); out = d.get("output") or ""; ec = d.get("exit_code")
    except Exception:
        continue
    if not out.strip():
        continue
    n += 1
    is_big = len(out) > B
    big += is_big
    lossless_tok += tok("\n".join(collapse(strip_progress(out))))
    key = None
    if is_big and ec not in (0, None):
        cands = [l.strip() for l in out.split("\n") if KEYRE.search(l) and l.strip()]
        if cands: key = cands[-1][:200]; errs += 1
    allerr = list(dict.fromkeys(l.strip()[:120] for l in out.split("\n") if is_big and KEYRE.search(l) and l.strip()))
    sq = squeeze(out, B, None)
    for m, f in methods.items():
        if m == "rtk log" and not is_big:
            o = out  # only bother running rtk on big outputs; small ones pass through
        elif m == "head+tail@same-size":
            o = headtail_n(out, len(sq))
        elif m == "squeeze":
            o = sq
        else:
            o = f(out)
        if allerr:
            agg[m]["errlines_total"] = agg[m].get("errlines_total", 0) + len(allerr)
            agg[m]["errlines_kept"] = agg[m].get("errlines_kept", 0) + sum(1 for e in allerr if e in o)
        t = tok(o)
        agg[m]["tok"] += t
        if is_big: agg[m]["tok_big"] += t
        if key and key[:120] in o: agg[m]["err_kept"] += 1
res = {"tokenizer": TOK, "budget_chars": B, "days": days, "outputs": n, "big_outputs": big,
       "big_failed_with_error_line": errs, "collapse_only_tokens": lossless_tok, "methods": agg}
print(json.dumps(res, indent=1))
