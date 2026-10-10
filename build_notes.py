#!/usr/bin/env python3
"""Build the Field Notes pages from Markdown files.

Usage (from the root of the dristiipatel.github.io repository):
    python3 build_notes.py

Reads   notes_src/*.md      (files starting with "_" are ignored)
Writes  notes/index.html    (list of posts)
        notes/<slug>/index.html
        notes/img/*         (copied from notes_src/img)

The notes/ folder is regenerated on every run, so never edit it by hand.
"""
import html
import re
import shutil
import sys
from datetime import date
from pathlib import Path

try:
    import markdown
except ImportError:
    sys.exit("Missing dependency. Run:  pip install markdown")

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "notes_src"
OUT = ROOT / "notes"

SITE_TITLE = "Field Notes in Physics"
TAGLINE = "Questions, calculations and sketches from learning neutrino physics."
AUTHOR = "Dristii Patel"
HOME_URL = "/"
NOTES_URL = "/notes/"

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b72;--accent:#2f5d8a;--line:#e3e0d8;--code:#f1efe9}
@media (prefers-color-scheme:dark){:root{--bg:#15171a;--fg:#e8e6e1;--muted:#9a9aa3;--accent:#8db6e0;--line:#2c2f34;--code:#1f2227}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:18px/1.7 Georgia,'Times New Roman',serif}
.wrap{max-width:42rem;margin:0 auto;padding:2rem 1.25rem 4rem}
nav{display:flex;gap:1.25rem;font:15px/1 system-ui,sans-serif;margin-bottom:3rem;flex-wrap:wrap}
a{color:var(--accent)}
nav a{text-decoration:none;color:var(--muted)}nav a:hover{color:var(--accent)}
h1{font-size:2rem;line-height:1.25;margin:0 0 .4rem}
h2{font-size:1.35rem;margin:2.2rem 0 .5rem}
h3{font-size:1.1rem;margin:1.6rem 0 .4rem}
.meta{font:14px/1.4 system-ui,sans-serif;color:var(--muted);margin-bottom:2rem}
.tagline{color:var(--muted);margin:0 0 2.5rem}
.entry{padding:1.1rem 0;border-top:1px solid var(--line)}
.entry h2{margin:0 0 .2rem;font-size:1.25rem}
.entry a{text-decoration:none}
.entry p{margin:.3rem 0 0;color:var(--muted);font-size:16px}
img{max-width:100%;height:auto}
figure{margin:1.8rem 0}figcaption{font:14px/1.5 system-ui,sans-serif;color:var(--muted);margin-top:.4rem}
pre,code{background:var(--code);font:14.5px/1.5 ui-monospace,Menlo,Consolas,monospace}
code{padding:.1em .3em;border-radius:3px}
pre{padding:.9rem 1rem;overflow-x:auto;border-radius:4px}pre code{padding:0;background:none}
table{border-collapse:collapse;margin:1.5rem 0;font:15px/1.5 system-ui,sans-serif;display:block;overflow-x:auto}
th,td{border-bottom:1px solid var(--line);padding:.4rem .8rem;text-align:left}
blockquote{margin:1.5rem 0;padding-left:1rem;border-left:3px solid var(--line);color:var(--muted)}
mjx-container[display=true]{overflow-x:auto;overflow-y:hidden}
footer{margin-top:4rem;padding-top:1.2rem;border-top:1px solid var(--line);font:14px/1.5 system-ui,sans-serif;color:var(--muted)}
"""

MATHJAX = """<script>window.MathJax={tex:{inlineMath:[['$','$']],displayMath:[['$$','$$']]}};</script>
<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<style>{css}</style>
{extra_head}
</head>
<body>
<div class="wrap">
<nav><a href="{home}">{author}</a><a href="{notes}">Notes</a></nav>
{body}
<footer>{site_title} &middot; {author}</footer>
</div>
</body>
</html>
"""

# Fenced code and inline code are matched first so that dollar signs inside
# them are left alone. Group 2 is a math expression.
TOKEN = re.compile(
    r"(```.*?```|`[^`\n]+`)|(\$\$.+?\$\$|(?<![\\$])\$(?![\s$])[^$\n]+?(?<!\s)\$)",
    re.S,
)


def protect_math(text):
    store = []

    def sub(m):
        if m.group(1):
            return m.group(0)
        store.append(m.group(2))
        return f"@@MATH{len(store) - 1}@@"

    return TOKEN.sub(sub, text), store


def restore_math(rendered, store):
    for i, expr in enumerate(store):
        rendered = rendered.replace(f"@@MATH{i}@@", html.escape(expr, quote=False))
    return rendered


def parse_post(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing front matter block between --- lines")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"').strip("'")
    for required in ("title", "date"):
        if required not in meta:
            raise ValueError(f"{path.name}: front matter needs '{required}'")
    meta["date"] = date.fromisoformat(meta["date"])
    meta["draft"] = meta.get("draft", "false").lower() == "true"
    meta["tags"] = [t.strip() for t in meta.get("tags", "").strip("[]").split(",") if t.strip()]
    meta["slug"] = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", path.stem)
    return meta, m.group(2)


def render_body(md_text):
    protected, store = protect_math(md_text)
    rendered = markdown.markdown(
        protected,
        extensions=["fenced_code", "tables", "footnotes", "sane_lists"],
    )
    rendered = restore_math(rendered, store)
    # Turn a lone image paragraph into <figure> with the alt text as caption.
    rendered = re.sub(
        r'<p><img alt="([^"]*)" src="([^"]+)" ?/?></p>',
        r'<figure><img src="\2" alt="\1"><figcaption>\1</figcaption></figure>',
        rendered,
    )
    return rendered, bool(store)


def fmt_date(d):
    return f"{d.day} {d.strftime('%B %Y')}"


def build():
    if not SRC.is_dir():
        sys.exit("notes_src/ not found. Run this script from the repository root.")

    posts = []
    for path in sorted(SRC.glob("*.md")):
        if path.name.startswith("_"):
            continue
        meta, body = parse_post(path)
        if meta["draft"]:
            print(f"  skipped draft: {path.name}")
            continue
        meta["html"], meta["has_math"] = render_body(body)
        meta["words"] = len(re.findall(r"\w+", body))
        posts.append(meta)
    posts.sort(key=lambda p: p["date"], reverse=True)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    if (SRC / "img").is_dir():
        shutil.copytree(SRC / "img", OUT / "img")

    for p in posts:
        minutes = max(1, round(p["words"] / 200))
        tags = (" &middot; " + ", ".join(p["tags"])) if p["tags"] else ""
        body = (
            f"<article><h1>{html.escape(p['title'])}</h1>"
            f"<div class='meta'>{fmt_date(p['date'])} &middot; {minutes} min read{tags}</div>"
            f"{p['html']}</article>"
        )
        page = PAGE.format(
            title=f"{html.escape(p['title'])} | {SITE_TITLE}",
            description=html.escape(p.get("summary", TAGLINE)),
            css=CSS,
            extra_head=MATHJAX,
            home=HOME_URL, notes=NOTES_URL, author=AUTHOR,
            body=body, site_title=SITE_TITLE,
        )
        folder = OUT / p["slug"]
        folder.mkdir()
        (folder / "index.html").write_text(page, encoding="utf-8")
        print(f"  built: notes/{p['slug']}/")

    entries = "".join(
        f"<div class='entry'><h2><a href='{NOTES_URL}{p['slug']}/'>{html.escape(p['title'])}</a></h2>"
        f"<div class='meta' style='margin:0'>{fmt_date(p['date'])}</div>"
        f"<p>{html.escape(p.get('summary', ''))}</p></div>"
        for p in posts
    ) or "<p>No posts yet.</p>"
    body = f"<h1>{SITE_TITLE}</h1><p class='tagline'>{TAGLINE}</p>{entries}"
    index = PAGE.format(
        title=SITE_TITLE, description=TAGLINE, css=CSS, extra_head="",
        home=HOME_URL, notes=NOTES_URL, author=AUTHOR,
        body=body, site_title=SITE_TITLE,
    )
    (OUT / "index.html").write_text(index, encoding="utf-8")
    print(f"Done: {len(posts)} post(s) in notes/")


if __name__ == "__main__":
    build()
