---
name: session-fold
description: Fold a Claude Code session (or any Markdown file) into five zoom levels: topic, takeaway, key, brief, full. Use when asked what an agent session did, what failed or was retried, or to skim a long document without paraphrasing it.
---

# session-fold

Fold a Claude Code session transcript (JSONL) or any Markdown file into five zoom levels, using only the author's own words: topic (3 words a step), takeaway (first 14 words), key and brief (first sentence), full (everything). Session totals (tool calls, failures, retries, model requests, tokens, duration) match agentplay's numbers.

## When to use
- The user asks what a coding-agent session did, what it read or edited, what failed, or what was retried.
- You need the gist of a long Markdown file before spending context on all of it.

## Commands (run from the repo root)
- `python session_fold.py --latest --level topic`: newest session under ~/.claude/projects, one line per section
- `python session_fold.py <session.jsonl> --level takeaway`: one line per step
- `python session_fold.py <session.jsonl> --level full --section sec-steps`: every step of one section
- `python session_fold.py notes.md --level key`: fold any Markdown file
- `--json`: the folded document in TextFold's JSON shape

## Notes
- Start at `topic` or `takeaway` and zoom into one section with `--section <id>`; that keeps the output small.
- Sessions can hold secrets and private paths. Read them locally; do not paste them anywhere else without asking.
