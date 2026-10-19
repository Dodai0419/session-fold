<div align="center">

# session-fold

**Read what your coding agent did at five zoom levels, from a one-line map to every step.**

agentplay replays Claude Code sessions; TextFold folds documents from a one-screen map to every word. session-fold does both in one stdlib Python file, small enough for an agent to call on itself.

Works with **Claude Code** and **Codex**.

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg) ![Status: prototype](https://img.shields.io/badge/status-prototype-orange.svg)

</div>

## Quick start
```bash
git clone https://github.com/Dodai0419/session-fold && cd session-fold
python session_fold.py fixtures/session.jsonl --level takeaway --section sec-steps
```
```
## Steps  `[sec-steps]`

- Searched for rateLimit in src
- Read src/middleware/rate_limit.ts
- Edited src/middleware/rate_limit.ts
- FAILED: Checked with npm test: parseDuration is not defined
- Checked with npm test again: Tests: 42 passed, 42 total
```
Your own newest Claude Code session: `python session_fold.py --latest --level topic`. Any Markdown file: `python session_fold.py notes.md --level key`.

## The problem
- A long agent session is thousands of JSONL lines; scrolling the terminal does not tell you what it read, edited or broke.
- Replay viewers are web apps; an agent (or you, over SSH) wants plain text it can read in a few hundred tokens.
- Summaries written by a model can be wrong; you want the agent's own words, cut shorter, never rewritten.

## The solution
| Idea | Fixes |
|------|-------|
| **agentplay's counts** (calls, failures, retries, model requests, tokens) from the raw transcript | Same totals as `agentplay export` on the same session |
| **Each step becomes one line** ("FAILED: Checked with npm test: parseDuration is not defined") | The failure and the retry are visible at a glance |
| **TextFold's no-model ladder** (topic, takeaway, key, brief, full) | Zoom out to one line per section or in to every word; nothing is paraphrased |
| **One file, standard library** | 358 lines instead of 21,242 + 9,177; no model call, no venv |

Levels: `topic` (3 words per step), `takeaway` (first 14 words), `key` / `brief` (first sentence), `full` (everything). `--section <id>` narrows to one section, `--json` prints the TextFold document shape.

## Use with Claude Code
```bash
/plugin marketplace add Dodai0419/session-fold
/plugin install session-fold@session-fold
```

## Use with Codex (ChatGPT)
```bash
git clone https://github.com/Dodai0419/session-fold && cp -r session-fold/skills/* ~/.codex/skills/
```
Or copy `AGENTS.md` into your project root.

## Benchmarks
| | original | this repo |
|-|-|-|
| session totals on `fixtures/session.jsonl` (calls, errors, retries, requests, tokens, output tokens, duration, user turns) | agentplay 0.2.1: 8, 1, 1, 9, 311,408, 2,820, 75 s, 1 | same 8 values (unit test) |
| the same totals on 14 finished real Claude Code sessions on the test machine | agentplay 0.2.1 `export` | calls, errors, requests, tokens, output tokens, user turns: 14/14 identical; retries: 9/14 (off by 1 to 3) |
| folded levels vs TextFold 0.10.7 `get --no-generate`, 6 Markdown files (`fixtures/sample.md`, 4 real READMEs/SKILL.md files from the upstream repos, a 15-word test) | reference | identical lines: takeaway 221/230, key 229/232, topic 92/101 |
| CLI wall time, fold new-term-radar's README.md at `takeaway` | 4.22 s (`python -m textfold get README.md --no-generate`; runs: 4.37, 4.28, 4.01) | 1.24 s (runs: 1.38, 1.18, 1.17) |
| CLI wall time, one session | 2.24 s (`agentplay build --rebuild`; runs: 2.39, 2.23, 2.11; builds the full map) | 1.12 s (parse + fold + print; runs: 1.17, 1.02, 1.17) |
| lines of Python | agentplay 21,242 + TextFold 9,177 | 358 |
| dependencies | agentplay: stdlib; TextFold: 10 packages (34 installed) | stdlib |

Windows 11, Python 3.11.1; the three tools were run in turn, three rounds. Bare `python -c pass` takes about 0.7 s on this machine, so most of this repo's wall time is interpreter start; fold + render of that README in-process is 57 ms. One more real session was still being written during the check and is left out. Retries use a simpler shell-verb parser than agentplay's quote-aware one.

Where the folds differ: TextFold parses Markdown with markdown-it, so nested lists, some link-only lines and wide tables come out differently. Two-column tables become units; wider ones are skipped. agentplay does much more than counting (cost in USD, file map, subagents, PRs, a web viewer); session-fold keeps only what a text replay needs. Sidechain (subagent) lines are skipped.

## Inspired by
- [Entelligence-AI/agentplay](https://github.com/Entelligence-AI/agentplay) — what to count in a Claude Code session and how (Apache-2.0).
- [chenxiachan/textfold](https://github.com/chenxiachan/textfold) — the five-level ladder, its tokenizer and sentence rules (Apache-2.0).

## Roadmap
- [ ] Codex session files (`~/.codex/sessions`)
- [ ] Subagent steps as nested sections
- [ ] `--since 1d` to fold every session of the day into one page

## License
MIT. Portions follow Apache-2.0 code; see LICENSE.

## Related tools
- [agent-board](https://github.com/Dodai0419/agent-board): see every Claude Code and Codex session at once
- [session-panel](https://github.com/Dodai0419/session-panel): replay a Claude Code session as an animated panel
- All tools, one install pattern: [github.com/Dodai0419](https://github.com/Dodai0419)
