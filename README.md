# squeeze

Shrinks noisy command output before it reaches an AI agent's context and keeps the error lines. It is one Python file, uses only the standard library and makes no LLM calls.

```
some_command 2>&1 | python3 squeeze.py            # default budget 8000 chars
python3 squeeze.py --budget 4000 -- pytest -q      # wrap a command; exit code kept
```

Agent harnesses cap long output by position. Hermes `browser_exec` keeps the head. Hermes `terminal` and Codex keep the head and the tail. Claude Code keeps a preview and spills the rest to a file. A cut by position drops errors from the middle and still spends the budget on repeated progress or log lines. squeeze works in three steps:

1. It strips ANSI codes and `\r` progress redraws.
2. It collapses runs of near-identical lines (lines that match once digits are masked) into `first / [... N similar lines] / last`.
3. If the output is still over budget, it keeps the head (35%) and the tail (45%), plus every distinct error or warning line from the cut middle. It writes the full raw output to `~/.cache/squeeze/` and prints that path, so nothing is lost.

## Numbers (our machine, real data)
I replayed all 12,250 non-empty `terminal` tool results from 7 days of our Hermes agents (`~/.hermes/state.db`) through each method at the same 8,000-char budget. 1,175 of the results were over budget, and those carried 56% of all output tokens.

| method | tokens on the 1,175 big outputs | error lines kept (of 544) |
|---|---|---|
| no cap | 4,794,215 | 100% |
| head only | 2,350,000 | 44% |
| head+tail (common default) | 2,357,050 | 74% |
| head+tail cut to the same size as squeeze | 1,954,560 | 70% |
| `rtk log` (rtk 1.1.0) | 91,950 | 13% |
| **squeeze** | **1,948,388 (−17%)** | **91%** |

An error line is any line matching `Error|Exception|Traceback|FAILED|fatal:|No such file|command not found|Permission denied|timed out`. This regex is independent of squeeze's own pattern, which is broader (that overlap is a caveat). When the final error line of a failed run is the only thing counted, head+tail and squeeze both keep 62 of 62, and head-only keeps 1 of 62. Tokens are chars/4. The 4k and 16k budget runs are in `results/`, and you can reproduce them on your own Hermes with `python3 bench.py ~/.hermes/state.db 7 8000`.

What this does not show: whether agents finish more tasks with it. That needs an A/B on live runs. `rtk` is built for specific commands and for log files, so treat that row as rtk used outside its intended use, not as a verdict on rtk.

## Complaints this targets
- https://github.com/NousResearch/hermes-agent/issues/137332 (head-only stderr cut drops the traceback's exception line)
- https://github.com/NousResearch/hermes-agent/issues/131786
- https://github.com/openai/codex/issues/49907 (save full output where the model can read it)
- https://github.com/openai/codex/issues/7906
- https://github.com/anthropics/claude-code/issues/93905 (models pipe through head/tail and rerun)
- https://github.com/anthropics/claude-code/issues/94337 (spilled output must be re-read, cost paid twice)
- https://github.com/anthropics/claude-code/issues/41810, https://github.com/anthropics/claude-code/issues/32105

MIT. Built in one day in public by [@DLife_hacker](https://x.com/DLife_hacker).
