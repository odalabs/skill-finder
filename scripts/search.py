#!/usr/bin/env python
"""skill-finder/scripts/search.py — find Claude Code skills on GitHub.

Usage:
    python search.py "<query>" [--limit 5] [--json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Force UTF-8 on stdout — Windows console defaults to cp866/cp1251 and
# mangles Cyrillic/Markdown unless we ask for UTF-8 explicitly.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

GITHUB_API = "https://api.github.com"
UA = "skill-finder/0.1"
DEBUG = False

GH_FALLBACK_PATHS = [
    r"C:\Program Files\GitHub CLI\gh.exe",
    r"C:\Program Files (x86)\GitHub CLI\gh.exe",
    os.path.expanduser(r"~\AppData\Local\GitHubCLI\gh.exe"),
]


def find_gh() -> str | None:
    for name in ("gh", "gh.exe"):
        p = shutil.which(name)
        if p:
            return p
    for p in GH_FALLBACK_PATHS:
        if os.path.isfile(p):
            return p
    return None


def get_token() -> str | None:
    gh = find_gh()
    if gh:
        try:
            r = subprocess.run(
                [gh, "auth", "token"], capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def gh_request(url: str, token: str | None, accept_json: bool = True):
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json" if accept_json else "*/*",
            "User-Agent": UA,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if accept_json else raw.decode("utf-8", errors="replace")
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        sys.stderr.write(f"[skill-finder] HTTP {e.code} on {url}\n  {body}\n")
        if e.code == 422:
            return {"items": []} if accept_json else ""
        return None
    except URLError as e:
        sys.stderr.write(f"[skill-finder] network error on {url}: {e}\n")
        return None


def search_code(query: str, token: str) -> list[dict]:
    # GitHub Code Search REST API uses legacy syntax: `filename:` (exact name match),
    # not `path:` — the latter is web-UI only and silently returns 0 here.
    q = f"{query} filename:SKILL.md"
    url = f"{GITHUB_API}/search/code?" + urlencode({"q": q, "per_page": 30})
    res = gh_request(url, token)
    if not res:
        return []
    return res.get("items", [])


def parse_frontmatter(text: str) -> dict:
    if not text or not text.lstrip().startswith("---"):
        return {}
    text = text.lstrip()
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    block = text[4:end]
    out: dict = {}
    cur = None
    for line in block.splitlines():
        m = re.match(r"^([\w-]+)\s*:\s*(.*)$", line)
        if m:
            cur = m.group(1)
            val = m.group(2).strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            out[cur] = val
        elif cur and (line.startswith(" ") or line.startswith("\t")):
            out[cur] = (out.get(cur, "") + " " + line.strip()).strip()
    return out


def fetch_raw(repo_full: str, ref: str | None, path: str, token: str | None) -> str:
    # raw.githubusercontent.com requires a real branch (HEAD doesn't resolve).
    # Try the provided ref first (if any), then main, then master.
    candidates = [r for r in (ref, "main", "master") if r and r != "HEAD"]
    seen: set[str] = set()
    safe_repo = quote(repo_full, safe="/")
    safe_path = quote(path, safe="/")
    for r in candidates:
        if r in seen:
            continue
        seen.add(r)
        safe_ref = quote(r, safe="/")
        url = f"https://raw.githubusercontent.com/{safe_repo}/{safe_ref}/{safe_path}"
        req = Request(url, headers={"User-Agent": UA})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError):
            continue
    return ""


def score(query: str, fm: dict, repo: dict, source_bonus: int) -> float:
    q_terms = set(re.findall(r"\w+", query.lower()))
    if not q_terms:
        return 0.0
    name = (fm.get("name") or "").lower()
    desc = (fm.get("description") or "").lower()
    name_hits = sum(1 for t in q_terms if t in name)
    desc_hits = sum(1 for t in q_terms if t in desc)
    match = min((name_hits * 3 + desc_hits) / len(q_terms), 1.0) * 50

    stars = repo.get("stargazers_count", 0) or 0
    star_score = min(math.log10(stars + 1) / 4, 1.0) * 20

    pushed = repo.get("pushed_at") or repo.get("updated_at") or ""
    recency = 0.0
    if pushed:
        try:
            dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - dt).days
            recency = max(0.0, 1 - days / 365) * 15
        except ValueError:
            pass

    return round(match + star_score + recency + source_bonus, 2)


def search(query: str, limit: int, token: str | None) -> list[dict]:
    items = search_code(query, token) if token else []
    if DEBUG:
        sys.stderr.write(f"[skill-finder] code-search returned {len(items)} items\n")
    seen: dict[str, dict] = {}
    for it in items[:30]:
        repo = it.get("repository") or {}
        full = repo.get("full_name")
        path = it.get("path")
        if not full or not path:
            continue
        key = f"{full}:{path}"
        seen[key] = {
            "repo_full": full,
            "path": path,
            "default_branch": repo.get("default_branch"),
            "html_url": it.get("html_url", ""),
        }

    repo_cache: dict[str, dict] = {}
    out: list[dict] = []
    skipped = 0
    for h in seen.values():
        md = fetch_raw(h["repo_full"], h["default_branch"], h["path"], token)
        fm = parse_frontmatter(md)
        if not fm.get("name") and not fm.get("description"):
            skipped += 1
            if DEBUG:
                sys.stderr.write(
                    f"[skill-finder] skip (no frontmatter): {h['repo_full']}/{h['path']}\n"
                )
            continue

        if h["repo_full"] not in repo_cache:
            time.sleep(0.05)
            repo_cache[h["repo_full"]] = (
                gh_request(f"{GITHUB_API}/repos/{h['repo_full']}", token) or {}
            )
        repo_meta = repo_cache[h["repo_full"]]

        bonus = 0
        rfl = h["repo_full"].lower()
        if rfl.startswith("anthropics/"):
            bonus = 15
        elif "awesome" in rfl or "claude-skill" in rfl:
            bonus = 7

        out.append(
            {
                "name": fm.get("name") or h["path"].rsplit("/", 1)[-1],
                "description": (fm.get("description") or "").strip(),
                "repo": h["repo_full"],
                "path": h["path"],
                "html_url": h["html_url"],
                "stars": repo_meta.get("stargazers_count", 0) or 0,
                "pushed_at": repo_meta.get("pushed_at") or "",
                "default_branch": repo_meta.get("default_branch") or h["default_branch"],
                "score": score(query, fm, repo_meta, bonus),
            }
        )

    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:limit]


def install_cmd(r: dict) -> str:
    path = r["path"]
    repo_url = f"https://github.com/{r['repo']}.git"
    if path == "SKILL.md":
        skill_name = r["repo"].split("/")[-1]
        return f"git clone --depth 1 {repo_url} ~/.claude/skills/{skill_name}"
    sub = "/".join(path.split("/")[:-1])
    skill_name = sub.rsplit("/", 1)[-1] if "/" in sub else sub
    tmp = f"/tmp/{skill_name}-src"
    return (
        f"git clone --depth 1 {repo_url} {tmp} && "
        f"cp -r {tmp}/{sub} ~/.claude/skills/{skill_name} && rm -rf {tmp}"
    )


def render_md(query: str, results: list[dict]) -> str:
    if not results:
        return (
            f"# skill-finder: «{query}»\n\n"
            "Ничего не нашёл. Попробуй другие EN-ключевые слова "
            "(GitHub Code Search ищет по содержимому SKILL.md, "
            "а они почти всегда на английском).\n"
        )
    lines = [f"# skill-finder: «{query}»", "", f"Топ {len(results)} (по убыванию score):", ""]
    for i, r in enumerate(results, 1):
        pushed = (r.get("pushed_at") or "")[:10]
        lines.append(f"## {i}. **{r['name']}** — score {r['score']}")
        lines.append(
            f"- repo: [{r['repo']}](https://github.com/{r['repo']}) · "
            f"★{r['stars']} · last push {pushed}"
        )
        if r["path"] != "SKILL.md":
            lines.append(f"- path: `{r['path']}`")
        desc = r["description"][:280] + ("…" if len(r["description"]) > 280 else "")
        lines.append(f"- {desc}")
        lines.append("- install:")
        lines.append(f"  ```bash\n  {install_cmd(r)}\n  ```")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Search GitHub for Claude Code skills.")
    ap.add_argument("query", help="Search query (English keywords work best)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--debug", action="store_true", help="Verbose progress to stderr")
    args = ap.parse_args()

    global DEBUG
    DEBUG = args.debug

    token = get_token()
    if not token:
        sys.stderr.write(
            "[skill-finder] WARNING: no GitHub token found. "
            "Code Search requires auth. Run `gh auth login` first.\n"
        )
    elif DEBUG:
        sys.stderr.write(f"[skill-finder] token loaded ({len(token)} chars)\n")

    results = search(args.query, args.limit, token)
    if args.json:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_md(args.query, results) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
