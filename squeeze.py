#!/usr/bin/env python3
"""squeeze: shrink noisy command output before it reaches an LLM agent's context.

Usage:  some_command 2>&1 | squeeze [--budget CHARS] [--keep DIR]
        squeeze -- some command args...        (runs it, appends exit code)

What it does, in order (each step is cheap and deterministic, no LLM):
  1. strips ANSI colour codes and carriage-return progress redraws
  2. collapses runs of near-identical lines (same text once digits are masked)
     into one line plus "[... N similar lines]"
  3. if the result is still over budget: keeps the head and the tail, plus
     every line in the cut middle that looks like an error/warning, and saves
     the FULL raw output to a file whose path is printed, so nothing is lost.

Plain head/tail truncation (what most agent harnesses do) drops errors that sit
in the middle of the output and keeps 200 identical progress lines. This keeps
the errors and drops the repeats.
"""
import argparse, hashlib, os, re, subprocess, sys, time

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
DIGITS = re.compile(r"\d+")
ERRLINE = re.compile(
    r"(error|exception|traceback|fatal|failed|failure|panic|denied|not found|"
    r"refused|timed? ?out|warning|warn\b|assert|errno|exit code|status [45]\d\d|\b[45]\d\d\b)",
    re.I)


def strip_progress(text):
    text = ANSI.sub("", text)
    out = []
    for line in text.split("\n"):
        if "\r" in line:  # progress bars redraw with \r: keep the final state
            parts = [p for p in line.split("\r") if p.strip()]
            line = parts[-1] if parts else ""
        out.append(line.rstrip())
    return out


def collapse(lines, min_run=3):
    out, i, n = [], 0, len(lines)
    while i < n:
        key = DIGITS.sub("#", lines[i]).strip()
        j = i + 1
        while j < n and DIGITS.sub("#", lines[j]).strip() == key:
            j += 1
        run = j - i
        if run >= min_run:
            out.append(lines[i])
            out.append(f"[... {run - 2} similar lines]")
            out.append(lines[j - 1])
        else:
            out.extend(lines[i:j])
        i = j
    # collapse runs of blank lines
    res = []
    for l in out:
        if l == "" and res and res[-1] == "":
            continue
        res.append(l)
    return res


def fit(lines, budget, keep_dir, raw):
    text = "\n".join(lines)
    if len(text) <= budget:
        return text
    head_b, tail_b = int(budget * 0.35), int(budget * 0.45)
    err_b = budget - head_b - tail_b
    head, size = [], 0
    for idx, l in enumerate(lines):
        if size + len(l) + 1 > head_b:
            break
        head.append(l); size += len(l) + 1
    h_end = len(head)
    tail, size = [], 0
    for l in reversed(lines[h_end:]):
        if size + len(l) + 1 > tail_b:
            break
        tail.append(l); size += len(l) + 1
    tail.reverse()
    t_start = len(lines) - len(tail)
    middle = lines[h_end:t_start]
    errs, size, seen = [], 0, set()
    for l in middle:
        if ERRLINE.search(l):
            k = DIGITS.sub("#", l)
            if k in seen:
                continue
            seen.add(k)
            l2 = l if len(l) <= 300 else l[:300] + "…"
            if size + len(l2) + 1 > err_b:
                break
            errs.append(l2); size += len(l2) + 1
    path = ""
    if keep_dir:
        os.makedirs(keep_dir, exist_ok=True)
        path = os.path.join(keep_dir, "out-%d-%s.txt" % (
            int(time.time()), hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:8]))
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(raw)
    note = f"[... {len(middle)} lines cut"
    note += f"; {len(errs)} error/warning lines kept below" if errs else ""
    note += f"; full output: {path}]" if path else "]"
    return "\n".join(head + [note] + errs + (["[... end of kept lines]"] if errs else []) + tail)


def squeeze(raw, budget=8000, keep_dir=None):
    return fit(collapse(strip_progress(raw)), budget, keep_dir, raw)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=int(os.environ.get("SQUEEZE_BUDGET", 8000)),
                    help="max output chars (default 8000)")
    ap.add_argument("--keep", default=os.environ.get("SQUEEZE_KEEP", os.path.expanduser("~/.cache/squeeze")),
                    help="dir for full raw output when cut ('' to disable)")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if cmd:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        raw = p.stdout.decode("utf-8", "replace")
        sys.stdout.write(squeeze(raw, a.budget, a.keep or None) + f"\n[exit {p.returncode}]\n")
        sys.exit(p.returncode)
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    sys.stdout.write(squeeze(raw, a.budget, a.keep or None) + "\n")


if __name__ == "__main__":
    main()
