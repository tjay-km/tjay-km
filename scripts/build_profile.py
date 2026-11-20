"""Rebuild the Featured Projects table and the stats card for the profile README.

Uses only public GitHub data, so nothing private ever ends up on the profile.
Runs in GitHub Actions with the built-in GITHUB_TOKEN (read-only use of the API).
"""
import json
import os
import sys
import urllib.request
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CONFIG = ROOT / "projects.json"
STATS_SVG = ROOT / "assets" / "stats.svg"
START, END = "<!-- PROJECTS:START -->", "<!-- PROJECTS:END -->"
API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")


def get(path):
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-builder",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def safe_get(path, default):
    try:
        return get(path)
    except Exception as exc:  # keep the build going if one call fails
        print(f"warning: {path}: {exc}", file=sys.stderr)
        return default


def cell(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def collect(config):
    user = config["username"]
    topic = config.get("topic", "portfolio")
    projects = list(config["projects"])
    listed = {p["repo"].lower() for p in projects}

    owned = safe_get(f"/users/{user}/repos?type=owner&per_page=100&sort=pushed", [])
    for repo in owned:
        if repo.get("private") or repo.get("fork") or repo.get("archived"):
            continue
        if topic not in (repo.get("topics") or []):
            continue
        if repo["full_name"].lower() in listed:
            continue
        stack = ", ".join(t for t in repo.get("topics", []) if t != topic)
        projects.append({
            "repo": repo["full_name"],
            "name": repo["name"],
            "what": repo.get("description") or "",
            "role": "",
            "stack": stack or (repo.get("language") or ""),
        })

    # Only keep repos that are publicly reachable, so a private repo is never linked.
    public = []
    for p in projects:
        info = safe_get(f"/repos/{p['repo']}", None)
        if info and not info.get("private"):
            public.append(p)
        else:
            print(f"skipping non-public or missing repo: {p['repo']}", file=sys.stderr)
    return user, owned, public


def projects_table(projects):
    lines = ["| Project | What it is | My role | Stack |", "|---|---|---|---|"]
    for p in projects:
        link = f"[{cell(p['name'])}](https://github.com/{p['repo']})"
        lines.append(f"| {link} | {cell(p['what'])} | {cell(p['role'])} | {cell(p['stack'])} |")
    return "\n".join(lines)


def language_totals(projects):
    totals = {}
    for p in projects:
        for lang, size in safe_get(f"/repos/{p['repo']}/languages", {}).items():
            totals[lang] = totals.get(lang, 0) + size
    return totals


def stats_svg(user, owned, projects, langs):
    public_repos = sum(1 for r in owned if not r.get("private") and not r.get("fork"))
    commits = safe_get(f"/search/commits?q=author:{user}&per_page=1", {}).get("total_count", 0)
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:6]
    colors = ["#2ea043", "#a371f7", "#3178c6", "#f1e05a", "#e34c26", "#8b949e"]

    rows = [
        ("Featured projects", len(projects)),
        ("Public repositories", public_repos),
        ("Public commits", commits),
    ]
    w, h = 495, 150
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="GitHub stats for {escape(user)}">',
        '<style>.t{font:600 16px Segoe UI,Ubuntu,sans-serif;fill:#2ea043}.l{font:400 13px Segoe UI,Ubuntu,sans-serif;fill:#8b949e}.v{font:600 13px Segoe UI,Ubuntu,sans-serif;fill:#c9d1d9}</style>',
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="8" fill="#0d1117" stroke="#30363d"/>',
        '<text x="20" y="32" class="t">GitHub at a glance</text>',
    ]
    for i, (label, value) in enumerate(rows):
        y = 62 + i * 26
        parts.append(f'<text x="20" y="{y}" class="l">{escape(label)}</text>')
        parts.append(f'<text x="200" y="{y}" class="v" text-anchor="end">{value}</text>')

    parts.append('<text x="240" y="62" class="l">Top languages (featured work)</text>')
    x, bar_w = 240, 235
    for i, (lang, size) in enumerate(top):
        seg = max(2, round(bar_w * size / total))
        parts.append(f'<rect x="{x}" y="72" width="{seg}" height="8" fill="{colors[i % len(colors)]}"/>')
        x += seg
    for i, (lang, size) in enumerate(top):
        col, row = i % 2, i // 2
        lx, ly = 240 + col * 125, 102 + row * 22
        pct = 100 * size / total
        parts.append(f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{colors[i % len(colors)]}"/>')
        parts.append(f'<text x="{lx + 15}" y="{ly}" class="v">{escape(lang)} <tspan class="l">{pct:.1f}%</tspan></text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    user, owned, projects = collect(config)

    readme = README.read_text(encoding="utf-8")
    if START not in readme or END not in readme:
        sys.exit("README is missing the PROJECTS markers")
    head, rest = readme.split(START, 1)
    _, tail = rest.split(END, 1)
    README.write_text(f"{head}{START}\n{projects_table(projects)}\n{END}{tail}", encoding="utf-8")

    STATS_SVG.parent.mkdir(exist_ok=True)
    STATS_SVG.write_text(stats_svg(user, owned, projects, language_totals(projects)), encoding="utf-8")
    print(f"built: {len(projects)} projects")


if __name__ == "__main__":
    main()
