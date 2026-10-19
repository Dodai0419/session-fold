"""session-fold: read a Claude Code session at five zoom levels, from a one-line map to every step.

Session parsing follows agentplay's Claude Code numbers (calls, errors, retries, requests, tokens);
folding follows TextFold's no-model ladder (topic < takeaway < key < brief < full). Standard library only.

  python session_fold.py fixtures/session.jsonl --level takeaway
  python session_fold.py --latest --level topic          # newest session under ~/.claude/projects
  python session_fold.py notes.md --level key            # fold any Markdown file
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

LEVELS = ["topic", "takeaway", "key", "brief", "full"]  # coarsest first
BUDGET = {"takeaway": 14, "topic": 3}  # words, as in TextFold's ladder.py

# --- session: Claude Code JSONL -> steps and totals ------------------------------------

KIND = {"Read": "read", "Grep": "search", "Glob": "search", "LS": "search", "Edit": "edit", "Write": "edit",
        "MultiEdit": "edit", "NotebookEdit": "edit", "WebFetch": "web", "WebSearch": "web", "Task": "subagent",
        "Agent": "subagent", "TodoWrite": "plan"}
# Counting rules follow agentplay's builder.py (Apache-2.0): what is a verify step, a user turn, an error, a retry.
VERIFY = re.compile(r"\b(pytest|go test|go vet|npm (?:run )?(?:test|build|lint)|pnpm (?:run )?(?:test|check|lint)"
                    r"|yarn (?:test|build)|tsc\b|ruff|mypy|make (?:test|check)|cargo (?:test|clippy|check)"
                    r"|vitest|jest|just test)")
MULTI = {"git", "gh", "aws", "npm", "pnpm", "yarn", "make", "cargo", "go", "uv", "just", "docker", "kubectl"}
PREFIX = {"cd", "export", "set", "unset", "source", "pushd", "popd"}
RETRY_WINDOW = 8


def kind_of(name, inp):
    if name == "Bash":
        return "verify" if VERIFY.search(inp.get("command", "")) else "run"
    return "mcp" if name.startswith("mcp__") else KIND.get(name, "tool")


def verb(cmd):
    """First command word(s) of a shell line: 'cd x && npm test -- -u' -> 'npm test'.
    shortcut: no quote-aware tokenizing, unlike agentplay's _shell_verb; upgrade if retries look off."""
    for seg in re.split(r"&&|\|\||;|\n", cmd):
        words = [w for w in seg.split() if not re.match(r"[A-Za-z_]\w*=", w)]
        while words and words[0] in {"sudo", "time", "timeout", "nohup", "env"}:
            words = [w for w in words[1:] if not re.fullmatch(r"-?\d+[smh]?|-\w+", w)] if len(words) > 1 else words[:1]
        if words and words[0] not in PREFIX:
            first = words[0].strip("()").replace("\\", "/").rsplit("/", 1)[-1][:32] or "sh"
            sub = next((w for w in words[1:] if not w.startswith("-") and "/" not in w), "")
            return f"{first} {sub}" if first in MULTI and re.fullmatch(r"[a-z][a-z0-9-]{0,24}", sub) else first
    return "sh"


def user_turn(r, text):
    """agentplay's rule: not meta, not a compact summary, not harness text."""
    t = (text or "").lstrip()
    return bool(t) and not (r.get("isMeta") or r.get("isCompactSummary") or t.startswith(("<", "[Request interrupted"))
                            or "[SYSTEM NOTIFICATION" in t)


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _text(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if b.get("type") == "text")


def parse(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if not r.get("isSidechain")]
    cwd = next((r["cwd"] for r in rows if r.get("cwd")), "")
    times = [t for t in (_ts(r.get("timestamp")) for r in rows if r.get("type") in ("user", "assistant")) if t]
    usage, prompts, events, by_id, notes, last_text, signals = {}, [], [], {}, [], "", 0
    for r in rows:
        msg = r.get("message") or {}
        content = msg.get("content")
        if r.get("type") == "system":  # API errors and refusal fallbacks are errors too
            sub = str(r.get("subtype") or "")
            signals += sub == "model_refusal_fallback" or "error" in sub
        elif r.get("type") == "attachment":
            signals += (r.get("attachment") or {}).get("type") in ("hook_blocking_error", "hook_non_blocking_error")
        elif r.get("type") == "assistant":
            if r.get("isApiErrorMessage"):
                signals += 1
                continue
            if msg.get("id") and msg.get("usage"):
                usage[msg["id"]] = msg["usage"]  # one message is split over several lines: count it once
            for b in content if isinstance(content, list) else []:
                if b.get("type") == "text" and b.get("text", "").strip():
                    last_text = b["text"].strip()
                    notes.append((len(events), last_text))
                elif b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    ev = {"seq": len(events), "tool": b["name"], "kind": kind_of(b["name"], inp), "input": inp,
                          "err": None, "out": ""}
                    by_id[b.get("id")] = ev
                    events.append(ev)
        elif r.get("type") == "user":
            blocks = content if isinstance(content, list) else []
            if any(b.get("type") == "tool_result" for b in blocks):
                for b in blocks:
                    ev = by_id.get(b.get("tool_use_id"))
                    if b.get("type") == "tool_result" and ev:
                        ev["err"] = bool(b.get("is_error"))
                        ev["out"] = b["content"] if isinstance(b.get("content"), str) else _text(b.get("content"))
                        status = str((r.get("toolUseResult") or {}).get("status") or "") \
                            if isinstance(r.get("toolUseResult"), dict) else ""
                        ev["err"] |= ev["kind"] == "subagent" and status in ("failed", "error", "killed", "cancelled")
                continue
            text = content if isinstance(content, str) else " ".join(b["text"] for b in blocks if b.get("type") == "text")
            if text.lstrip().startswith("[Request interrupted") and not r.get("isMeta"):
                signals += 1
            elif user_turn(r, text):
                prompts.append(text.strip())
    for ev in events:  # a call that never got a result was killed or interrupted
        ev["err"] = True if ev["err"] is None else ev["err"]
    window = []
    for ev in events:  # a retry repeats a recent call (same tool, verb and target) that failed
        i = ev["input"]
        ev["key"] = (ev["tool"], verb(i.get("command", "")) if ev["tool"] == "Bash" else None,
                     i.get("file_path") or i.get("path") or i.get("notebook_path") or i.get("url"))
        prev = next((p for p in reversed(window) if p["key"] == ev["key"]), None)
        if prev and prev["err"]:
            ev["retryOf"] = prev["seq"]
        window = (window + [ev])[-RETRY_WINDOW:]
    tok = lambda u: sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                 "cache_read_input_tokens", "output_tokens"))
    totals = {"calls": len(events), "errors": sum(e["err"] for e in events) + signals,
              "retries": sum("retryOf" in e for e in events), "requests": len(usage),
              "tokens": sum(map(tok, usage.values())), "outputTokens": sum(u.get("output_tokens") or 0 for u in usage.values()),
              "durationMs": int((max(times) - min(times)).total_seconds() * 1000) if times else 0,
              "userTurns": len(prompts)}
    return {"cwd": cwd, "start": min(times).strftime("%H:%M:%S") if times else "00:00:00", "prompts": prompts,
            "events": events, "notes": notes, "result": last_text, "totals": totals}


def _rel(p, cwd):
    return p[len(cwd):].lstrip("/\\") if cwd and p.startswith(cwd) else p


def step_line(ev, cwd):
    i, out = ev["input"], (ev["out"] or "").strip().splitlines()
    target = i.get("file_path") or i.get("path") or i.get("notebook_path") or ""
    what = {"read": f"Read `{_rel(target, cwd)}`", "edit": f"Edited `{_rel(target, cwd)}`",
            "search": f"Searched for `{i.get('pattern', '')}` in `{_rel(target, cwd) or '.'}`",
            "verify": f"Checked with `{i.get('command', '')}`", "run": f"Ran `{i.get('command', '')}`",
            "web": f"Fetched {i.get('url') or i.get('query', '')}", "subagent": f"Asked a subagent: {i.get('description', '')}"
            }.get(ev["kind"], f"Called {ev['tool']}")
    if "retryOf" in ev:
        what += " again"
    if ev["err"]:
        detail = next((x for pat in (r"error|not defined|exception|denied", r"fail") for x in out if re.search(pat, x, re.I)),
                      out[0] if out else "")
        return f"FAILED: {what}: {detail.strip()}."
    return f"{what}{(': ' + out[-1].strip()) if ev['kind'] in ('verify', 'run') and out else ''}."


def session_markdown(s):
    title = (s["prompts"][0] if s["prompts"] else "Session").splitlines()[0][:80]
    t = s["totals"]
    md = [f"# {title}", "", "## Prompt", ""] + [p + "\n" for p in s["prompts"]] + ["## Steps", ""]
    notes = dict(s["notes"])
    for ev in s["events"]:
        if ev["seq"] in notes:
            md += ["", notes.pop(ev["seq"]), ""]
        md.append("- " + step_line(ev, s["cwd"]))
    md += ["", "## Result", "", s["result"] or "No final message.", "", "## Totals", "",
           f"{t['calls']} tool calls, {t['errors']} failed, {t['retries']} retried. {t['requests']} model requests, "
           f"{t['tokens']:,} tokens ({t['outputTokens']:,} output), {t['durationMs'] / 1000:.0f} s."]
    return "\n".join(md) + "\n"


# --- fold: Markdown -> five levels (TextFold's no-model ladder) -------------------------
# Tokenizer, sentence split and word heads follow TextFold's textfold/tokens.py and ladder.py (Apache-2.0).

CJK = "\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f"
TOKEN = re.compile(rf"\s+|`[^`]+`|[{CJK}]|\d+(?:[.,]\d+)+%?|[^\W_{CJK}]+(?:['’\-][^\W_{CJK}]+)*|\S")
ABBREV = {"e", "g", "i", "al", "etc", "vs", "cf", "fig", "figs", "eq", "eqs", "sec", "secs", "tab", "ref", "refs", "no",
          "approx", "resp", "ca", "viz", "dr", "mr", "ms", "prof", "st", "jr", "inc", "ltd", "co", "appx", "app", "thm",
          "def", "lem", "prop", "cor", "ch"}
INLINE = [(r"!\[[^\]]*\]\([^)]*\)", ""), (r"\[([^\]]*)\]\([^)]*\)", r"\1"),
          (r"(\*\*|__)(.+?)\1", r"\2"), (r"(?<!\w)[*_](?!\s)(.+?)(?<!\s)[*_](?!\w)", r"\1"), (r"<[^>]+>", "")]


def tokens(text):
    out = []  # [text, space_after]
    for m in TOKEN.finditer(text):
        if m.group(0).isspace():
            if out:
                out[-1][1] = True
        else:
            out.append([m.group(0), False])
    return out


def join(toks):  # a code span is one token (an atom in TextFold); its backticks go on output
    return "".join(t.strip("`") + (" " if sp else "") for t, sp in toks).strip()


def sentences(toks):
    bounds, start, n = [], 0, len(toks)
    for i, (t, sp) in enumerate(toks):
        if t not in (".", "?", "!") or i + 1 >= n:
            continue
        end = i
        if not sp and toks[i + 1][0] in (")", "]", "\u201d", '"', "\u2019") and toks[i + 1][1]:
            end = i + 1  # a closing bracket or quote glued to the stop belongs to this sentence
        elif not sp:
            continue
        if end + 1 >= n:
            continue
        prev = toks[i - 1][0] if i else ""
        if t == "." and (prev.lower() in ABBREV or re.fullmatch(r"[A-Z]", prev)):
            continue
        if re.match(r"[A-Z0-9(\[\u201c\"\u2018`]", toks[end + 1][0]):  # a code span starts a sentence too
            bounds.append(toks[start:end + 1])
            start = end + 1
    return bounds + ([toks[start:]] if start < n else [])


def head(toks, n):
    """The first n words, punctuation between them kept, none at the end."""
    is_word = lambda t: len(t) > 1 and t[0] == "`" or bool(re.search(r"\w", t))
    out, w = [], 0
    for tk in toks:
        word = is_word(tk[0])
        if word and w == n:
            break
        out.append(tk)
        w += word
    while out and not is_word(out[-1][0]):
        out.pop()
    return out


def inline(text):
    for pat, rep in INLINE:
        text = re.sub(pat, rep, text)
    return text


def unit(text, kind, uid):
    text = inline(text)
    sents = sentences(tokens(text)) or [[]]
    take = head(sents[0], BUDGET["takeaway"])
    texts = [join(x) for x in sents]
    return {"id": uid, "kind": kind, "full": " ".join(texts), "sentences": texts, "brief": texts[:1], "evidence": [0],
            "key": texts[0], "takeaway": join(take), "topic": join(head(take, BUDGET["topic"]))}


def fold(md):
    title, sections, buf, kind, fence = "", [], [], None, False
    lines = md.splitlines()
    if lines and lines[0].strip() == "---":  # front matter
        end = next((i for i, x in enumerate(lines[1:], 1) if x.strip() == "---"), 0)
        lines = lines[end + 1:]

    def flush():
        nonlocal buf
        if buf:
            if not sections:
                sections.append({"id": "abstract", "title": "(untitled)", "units": [], "depth": 1})
            sec = sections[-1]
            sec["units"].append(unit(" ".join(buf), kind, f"{sec['id']}.u{len(sec['units']) + 1}"))
        buf = []

    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(("```", "~~~")):
            flush()
            fence = not fence
            continue
        m = re.match(r"(#{1,6})\s+(.*)", s)
        if fence:
            continue
        if s.startswith("|"):  # a table row is a unit "cell: cell"; its header and separator row are not
            flush()
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            cells = [c.strip() for c in s.strip("|").split("|")]
            # shortcut: only two-column tables become units (what TextFold printed in our checks); wider ones are skipped
            if len(cells) == 2 and not re.fullmatch(r"[|:\-\s]+", s) and not re.fullmatch(r"\|?[\s:|-]*-{3,}[\s:|-]*", nxt):
                buf, kind = [": ".join(cells)], "table row"
                flush()
        elif s.startswith(("<", "![")):
            flush()
        elif m:
            flush()
            name = inline(m.group(2)).replace("`", "")
            if len(m.group(1)) == 1 and not title:
                title = name
            else:
                slug = "".join(c for c in name.lower() if c.isalnum() or c in "_- ").strip().replace(" ", "-")
                sections.append({"id": f"sec-{slug or len(sections) + 1}", "title": name, "units": [],
                                 "depth": max(1, len(m.group(1)) - 1)})
        elif re.match(r"([-*+]|\d+[.)])\s+", s):
            flush()
            buf, kind = [re.sub(r"^([-*+]|\d+[.)])\s+", "", s)], "list item"
        elif not s or re.fullmatch(r"[-*_]{3,}", s):
            flush()
        else:
            if not buf:
                kind = "paragraph"
            buf.append(s.lstrip("> "))
    flush()
    return {"format": "textfold/doc", "version": 0, "title": title, "levels": LEVELS,
            "provenance": {"made_with": "session-fold", "ai_generated": False, "local": True},
            "sections": [s for s in sections if s["units"]]}


def render(doc, level="topic", section=None):
    if level not in LEVELS:
        raise ValueError(f"level is one of {', '.join(LEVELS)}")
    out = [f"# {doc['title']}", ""]
    for s in doc["sections"]:
        if section and section not in (s["id"], s["title"]):
            continue
        out += [f"{'#' * (1 + s.get('depth', 1))} {s['title']}  `[{s['id']}]`", ""]
        us = s["units"]
        if level == "topic":
            out += ["; ".join(u["topic"] for u in us), ""]
        elif level == "takeaway":
            out += [f"- {u['takeaway']}" for u in us] + [""]
        else:
            for u in us:
                text = u["full"] if level == "full" else u["key"]
                out += [("- " if u["kind"] == "list item" else "") + text, ""]
    return "\n".join(out)


def latest(home=Path.home() / ".claude" / "projects"):
    files = [p for p in home.glob("*/*.jsonl")]
    if not files:
        sys.exit(f"no sessions under {home}")
    return max(files, key=lambda p: p.stat().st_mtime)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read a Claude Code session (or any Markdown) at five zoom levels.")
    ap.add_argument("file", nargs="?", help="session .jsonl or a .md file")
    ap.add_argument("--latest", action="store_true", help="newest session under ~/.claude/projects")
    ap.add_argument("--level", default="takeaway", choices=LEVELS)
    ap.add_argument("--section", help="only this section (id or title)")
    ap.add_argument("--json", action="store_true", help="the folded document as JSON (TextFold doc shape)")
    a = ap.parse_args(argv)
    path = latest() if a.latest else Path(a.file) if a.file else ap.error("give a file or --latest")
    text = path.read_text(encoding="utf-8")
    doc = fold(session_markdown(parse(path)) if path.suffix == ".jsonl" else text)
    out = json.dumps(doc, indent=1) if a.json else render(doc, a.level, a.section)
    sys.stdout.buffer.write((out + "\n").encode("utf-8"))  # UTF-8 even on cp949/cp1252 consoles


if __name__ == "__main__":
    main()
