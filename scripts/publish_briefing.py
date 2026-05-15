#!/usr/bin/env python3
"""
Publish a weekly briefing draft:
  1. Read the edited draft JSON from drafts/{date}.json
  2. Build the trimmed Slack payload (same rules as the live workflow)
  3. Send to Slack via webhook
  4. Push final HTML to briefings/{date}.html
  5. Update data/weekly-data.json for the archive

Usage:
  python publish_briefing.py <date> [--repo owner/repo] [--dry-run]

Env vars:
  GITHUB_TOKEN — GitHub PAT with repo scope
  SLACK_WEBHOOK_URL_WEEKLY — Slack webhook for the main channel
"""

import argparse
import base64
import json
import os
import sys
import urllib.request


def gh_request(method, path, body=None, repo=None):
    token = os.environ.get("GITHUB_TOKEN", "")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return None
        raise


def read_gh_file(path, repo):
    result = gh_request("GET", path, repo=repo)
    if not result:
        return None, None
    content = base64.b64decode(result["content"]).decode("utf-8")
    return content, result["sha"]


def write_gh_file(path, content, sha, message, repo):
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    body = {"message": message, "content": encoded, "branch": "main"}
    if sha:
        body["sha"] = sha
    gh_request("PUT", path, body=body, repo=repo)


def build_slack_blocks(data, briefing_url, archive_url):
    """Build trimmed Slack blocks from draft data — same rules as the live workflow."""
    mentions = data.get("mentions", [])
    narratives = data.get("narratives", [])
    competitors = data.get("competitors", [])
    persistent = [n for n in narratives if n.get("cadence") in ("persistent", "recurring")]
    emerging = [n for n in narratives if n.get("cadence") in ("new", "sporadic")]
    total_comp = sum(c.get("count", 0) for c in competitors)

    date_display = data.get("date_display", data.get("date", ""))

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"\U0001f4ca Weekly Briefing — {date_display}", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            "_Weekly strategic overview of our media presence, competitive positioning, and emerging industry narratives across crypto and mainstream outlets._"}},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"*{data.get('mentions_count', 0)}* our mentions · "
            f"*{data.get('narrative_count', 0)}* narrative · "
            f"*{total_comp}* competitor articles"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"*\U0001f4cb Strategic Summary*\n{data.get('executive_summary', '')}"}},
    ]

    # Our Mentions (up to 15)
    if mentions:
        blocks.append({"type": "divider"})
        text = f"*\U0001f4f0 Our Mentions* ({len(mentions)} total)\n"
        for a in mentions[:15]:
            text += f"\u2022 <{a['url']}|{a['title'][:90]}> — _{a['source']}_\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    # Competitor Watch
    if total_comp > 0:
        blocks.append({"type": "divider"})
        text = f"*\U0001f3e2 Competitor Watch* ({total_comp} total)\n"
        for c in competitors:
            if c.get("count", 0) > 0:
                text += f"\u2022 *{c['name']}* ({c['count']}): <{c.get('top_url', '#')}|{c.get('top_title', '')[:70]}>\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    # Key Narratives
    if narratives:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*\U0001f50d Key Narratives*"}})

        if persistent:
            for n in persistent:
                ce = {
                    "persistent": "\U0001f525", "recurring": "\U0001f501"
                }.get(n.get("cadence", ""), "\U0001f4cc")
                me = {
                    "rising": "\U0001f4c8", "stable": "\u27a1\ufe0f", "fading": "\U0001f4c9"
                }.get(n.get("momentum", ""), "")
                text = f"{ce} *{n['title']}* · `{n.get('appearances', 1)}x` {me}\n{n.get('description', '')}\n"
                if n.get("relevance"):
                    text += f"> \U0001f3e2 _{n['relevance']}_\n"
                for a in n.get("articles", [])[:2]:
                    text += f"\U0001f4ce _{a['source']}:_ <{a['url']}|{a['title'][:90]}>\n"
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

        if emerging:
            text = "*\u2728 Emerging*\n"
            for n in emerging:
                text += f"\u2022 *{n['title']}* — {n.get('description', '')[:100]}\n"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    # Seizure Scorecard
    if data.get("seizure_value"):
        blocks.append({"type": "divider"})
        text = "*\U0001f4ca Seize & Freeze Scorecard*\n"
        text += f"\U0001f517 *{data['seizure_value']}* seized & frozen with Chainalysis involvement — *{data.get('seizure_cases', 'N/A')} cases*\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    # NO Market Landscape
    # NO Competitor Spotlight

    # Footer + buttons
    blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
        f"_Chainalysis Weekly Briefing · {date_display} · {data.get('articles_analysed', 0)} articles analysed_"}]})
    blocks.append({"type": "actions", "elements": [
        {"type": "button", "text": {"type": "plain_text", "text": "\U0001f4ca View Full Briefing", "emoji": True},
         "url": briefing_url, "style": "primary"},
        {"type": "button", "text": {"type": "plain_text", "text": "\U0001f4cb Browse Archive", "emoji": True},
         "url": archive_url},
    ]})

    fallback = (f"Weekly Briefing ({date_display}): "
                f"{data.get('mentions_count', 0)} our mentions, "
                f"{data.get('narrative_count', 0)} narrative, {total_comp} competitor")

    return {"text": fallback, "blocks": blocks}


def build_final_html(data, date):
    """Build the published HTML from draft data."""
    persistent = [n for n in data.get("narratives", []) if n.get("cadence") in ("persistent", "recurring")]
    emerging = [n for n in data.get("narratives", []) if n.get("cadence") in ("new", "sporadic")]
    total_comp = sum(c.get("count", 0) for c in data.get("competitors", []))

    mention_rows = "".join(
        f'<div class="mention-row"><a href="{m["url"]}" class="mention-title">{m["title"]}</a>'
        f'<div class="mention-meta">{m["source"]}</div></div>'
        for m in data.get("mentions", []))

    def theme_html(n, style_class):
        badge = {"persistent": "🔥 Persistent", "recurring": "🔁 Recurring"}.get(n.get("cadence"), "✨ New")
        badge_cls = {"persistent": "badge-persistent", "recurring": "badge-recurring"}.get(n.get("cadence"), "badge-new")
        me = {"rising": "📈", "stable": "➡️", "fading": "📉"}.get(n.get("momentum", ""), "")
        links = "".join(f'<a href="{a["url"]}">{a["source"]}: {a["title"][:80]}</a>' for a in n.get("articles", [])[:3])
        rel = f'<p class="theme-relevance">🏢 {n["relevance"]}</p>' if n.get("relevance") else ""
        return (f'<div class="theme-card {style_class}"><div><span class="theme-title">{n["title"]}</span>'
                f'<span class="badge {badge_cls}">{badge}</span>'
                f'<span class="trend-meta">{me} {n.get("appearances", 1)}x</span></div>'
                f'<p class="theme-desc">{n.get("description", "")}</p>{rel}'
                f'<div class="theme-links">{links}</div></div>')

    persistent_html = "".join(theme_html(n, "theme-persistent") for n in persistent)
    emerging_html = "".join(theme_html(n, "theme-emerging") for n in emerging)

    top_domains = data.get("top_domains", [])
    max_count = top_domains[0]["count"] if top_domains else 1
    domain_bars = "".join(
        f'<div class="bar-row"><span class="bar-label">{d["name"]}</span>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{d["count"]/max_count*100}%"></div></div>'
        f'<span class="bar-count">{d["count"]}</span></div>'
        for d in top_domains)

    comp_html = ""
    for c in data.get("competitors", []):
        if c.get("count", 0) > 0:
            comp_html += (f'<div class="comp-item"><span class="comp-name">{c["name"]}</span> '
                          f'<span class="comp-count">({c["count"]})</span>'
                          f'<div class="comp-headline"><a href="{c.get("top_url","#")}">{c.get("top_title","")}</a>'
                          f' &mdash; <span style="color:var(--text-muted);font-size:12px">{c.get("top_source","")}</span></div></div><hr>')
        else:
            comp_html += (f'<div class="comp-item"><span class="comp-name" style="color:var(--text-muted)">{c["name"]}</span>'
                          f' <span class="comp-count">(0)</span></div><hr>')

    landscape_html = ""
    if data.get("market_landscape"):
        landscape_html = (f'<div class="card"><div class="card-header"><h2>🌍 Market Landscape</h2></div>'
                          f'<div class="card-body"><p style="font-size:14px;color:var(--text-muted);line-height:1.7">'
                          f'{data["market_landscape"]}</p></div></div>')

    spotlight_html = ""
    if data.get("spotlight_trm") or data.get("spotlight_elliptic"):
        spotlight_html = '<div class="card"><div class="card-header"><h2>🔎 Competitor Spotlight</h2></div><div class="card-body">'
        if data.get("spotlight_trm"):
            spotlight_html += f'<p style="font-size:14px;color:var(--text-muted);margin-bottom:12px"><strong style="color:var(--text)">TRM Labs:</strong> {data["spotlight_trm"]}</p>'
        if data.get("spotlight_elliptic"):
            spotlight_html += f'<p style="font-size:14px;color:var(--text-muted)"><strong style="color:var(--text)">Elliptic:</strong> {data["spotlight_elliptic"]}</p>'
        spotlight_html += '</div></div>'

    seizure_html = ""
    if data.get("seizure_value"):
        seizure_html = (f'<div class="card"><div class="card-header"><h2>📊 Seize & Freeze Scorecard</h2></div>'
                        f'<div class="card-body"><div class="seizure-box">'
                        f'<p>🔗 <strong>{data["seizure_value"]}</strong> seized &amp; frozen — <strong>{data.get("seizure_cases","N/A")} cases</strong></p>'
                        f'</div></div></div>')

    dd = data.get("date_display", date)

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Weekly Briefing — {date}</title>
<style>
:root{{--bg:#f8f9fa;--card:#fff;--text:#1a1a2e;--text-muted:#6b7280;--border:#e5e7eb;--primary:#1a73e8;--success:#16a34a;--warning:#d97706;--info:#2563eb}}
@media(prefers-color-scheme:dark){{:root{{--bg:#111118;--card:#1c1c27;--text:#e4e4e7;--text-muted:#9ca3af;--border:#2e2e3a;--primary:#60a5fa;--success:#4ade80;--warning:#fbbf24;--info:#60a5fa}}}}
*{{margin:0;padding:0;box-sizing:border-box}}body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;line-height:1.6;min-height:100vh}}
.container{{max-width:800px;margin:0 auto;padding:40px 16px}}.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;margin-bottom:24px;overflow:hidden}}
.card-header{{padding:16px 20px 0}}.card-body{{padding:16px 20px 20px}}h1{{font-size:24px;font-weight:700}}h2{{font-size:15px;font-weight:600;margin-bottom:4px}}
.subtitle{{font-size:13px;color:var(--text-muted)}}.text-center{{text-align:center}}a{{color:var(--primary);text-decoration:none}}a:hover{{text-decoration:underline}}hr{{border:none;border-top:1px solid var(--border);margin:12px 0}}
.nav-bar{{display:flex;justify-content:space-between;align-items:center;padding:12px 0;margin-bottom:20px;border-bottom:1px solid var(--border);font-size:13px}}.nav-bar a{{color:var(--primary)}}.nav-bar .disabled{{color:var(--text-muted)}}
.stat-grid{{display:grid;grid-template-columns:repeat(4,1fr)}}.stat-cell{{text-align:center;padding:16px 8px;border-right:1px solid var(--border)}}.stat-cell:last-child{{border-right:none}}
.stat-value{{font-size:24px;font-weight:700}}.stat-label{{font-size:10px;color:var(--text-muted);text-transform:uppercase;margin-top:4px}}
.mention-row{{padding:10px 0;border-bottom:1px solid var(--border)}}.mention-row:last-child{{border-bottom:none}}.mention-title{{font-size:14px;font-weight:500;color:var(--primary)}}.mention-meta{{font-size:12px;color:var(--text-muted);margin-top:2px}}
.theme-card{{border-radius:8px;padding:12px;margin-bottom:10px;border-left:3px solid}}.theme-persistent{{background:rgba(217,119,6,0.08);border-left-color:var(--warning)}}.theme-emerging{{background:rgba(37,99,235,0.08);border-left-color:var(--info)}}
.theme-title{{font-size:14px;font-weight:600}}.theme-desc{{font-size:13px;color:var(--text-muted);margin-top:4px}}.theme-relevance{{font-size:12px;font-style:italic;margin-top:4px}}.theme-links{{margin-top:8px}}.theme-links a{{font-size:12px;display:block;margin-top:3px}}
.badge{{display:inline-block;font-size:10px;font-weight:600;padding:1px 8px;border-radius:99px;margin-left:6px}}.badge-persistent,.badge-recurring{{background:rgba(217,119,6,0.15);color:var(--warning)}}.badge-new{{background:rgba(37,99,235,0.12);color:var(--info)}}.trend-meta{{font-size:11px;color:var(--text-muted);margin-left:6px}}
.bar-row{{display:flex;align-items:center;gap:12px;margin-bottom:6px}}.bar-label{{width:200px;font-size:12px;color:var(--text-muted)}}.bar-track{{flex:1;height:14px;background:var(--border);border-radius:4px;overflow:hidden}}.bar-fill{{height:100%;background:var(--primary);border-radius:4px}}.bar-count{{width:30px;text-align:right;font-size:12px;font-weight:600}}
.comp-item{{margin-bottom:14px}}.comp-name{{font-size:14px;font-weight:600}}.comp-count{{font-size:12px;color:var(--text-muted)}}.comp-headline{{font-size:13px;margin-top:2px}}
.seizure-box{{border-radius:8px;padding:14px;background:rgba(22,163,74,0.08);border-left:3px solid var(--success)}}.footer{{text-align:center;font-size:11px;color:var(--text-muted);padding:12px 0 40px}}
.card-header-row{{display:flex;justify-content:space-between;align-items:baseline}}.count-label{{font-size:12px;color:var(--text-muted)}}
</style></head><body><div class="container">
<div class="nav-bar"><span class="disabled">← Previous week</span><a href="../index.html">📋 Archive</a><span class="disabled">Next week →</span></div>
<div class="text-center" style="margin-bottom:28px"><h1>Weekly Briefing</h1><p class="subtitle">Week ending {dd}</p></div>
<div class="card"><div class="stat-grid">
<div class="stat-cell"><div class="stat-value" style="color:var(--primary)">{data.get('mentions_count',0)}</div><div class="stat-label">Our Mentions</div></div>
<div class="stat-cell"><div class="stat-value" style="color:var(--success)">{data.get('narrative_count',0)}</div><div class="stat-label">Narrative</div></div>
<div class="stat-cell"><div class="stat-value" style="color:var(--warning)">{total_comp}</div><div class="stat-label">Competitor</div></div>
<div class="stat-cell"><div class="stat-value" style="color:var(--info)">{len(persistent)}</div><div class="stat-label">Persistent</div></div>
</div></div>
<div class="card"><div class="card-header"><h2>Strategic Summary</h2></div><div class="card-body"><p style="font-size:14px;color:var(--text-muted)">{data.get('executive_summary','')}</p></div></div>
<div class="card"><div class="card-header"><div class="card-header-row"><h2>📰 Chainalysis in the News</h2><span class="count-label">{data.get('mentions_count',0)} mentions</span></div></div><div class="card-body">{mention_rows or '<p style="color:var(--text-muted)">No mentions.</p>'}</div></div>
{f'<div class="card"><div class="card-header"><h2>🔥 Persistent Themes</h2></div><div class="card-body">{persistent_html}</div></div>' if persistent_html else ''}
{f'<div class="card"><div class="card-header"><h2>✨ Emerging This Week</h2></div><div class="card-body">{emerging_html}</div></div>' if emerging_html else ''}
{f'<div class="card"><div class="card-header"><h2>📊 Topic Coverage</h2></div><div class="card-body">{domain_bars}</div></div>' if domain_bars else ''}
{seizure_html}
{f'<div class="card"><div class="card-header"><h2>🏢 Competitor Watch</h2></div><div class="card-body">{comp_html}</div></div>' if comp_html else ''}
{landscape_html}
{spotlight_html}
<div class="footer">Chainalysis Weekly Briefing · {dd} · {data.get('articles_analysed', '?')} articles analysed</div>
</div></body></html>"""


def main():
    parser = argparse.ArgumentParser(description="Publish a weekly briefing draft")
    parser.add_argument("date", help="Date of the briefing (YYYY-MM-DD)")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="GitHub repo (owner/name)")
    parser.add_argument("--dry-run", action="store_true", help="Print Slack payload without sending")
    args = parser.parse_args()

    if not args.repo:
        print("Error: --repo or GITHUB_REPOSITORY required", file=sys.stderr)
        sys.exit(1)

    repo = args.repo
    date = args.date
    owner = repo.split("/")[0]
    repo_name = repo.split("/")[1]

    # 1. Read draft data
    print(f"Reading draft: drafts/{date}.json")
    draft_content, _ = read_gh_file(f"drafts/{date}.json", repo)
    if not draft_content:
        print(f"Error: drafts/{date}.json not found", file=sys.stderr)
        sys.exit(1)
    data = json.loads(draft_content)

    briefing_url = f"https://{owner}.github.io/{repo_name}/briefings/{date}.html"
    archive_url = f"https://{owner}.github.io/{repo_name}/"

    # 2. Build and send Slack
    print("Building Slack payload...")
    slack_payload = build_slack_blocks(data, briefing_url, archive_url)

    if args.dry_run:
        print(json.dumps(slack_payload, indent=2))
    else:
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL_WEEKLY", "")
        if webhook_url:
            print("Sending to Slack...")
            req = urllib.request.Request(webhook_url,
                data=json.dumps(slack_payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req) as resp:
                print(f"Slack sent: {resp.status}")
        else:
            print("Warning: SLACK_WEBHOOK_URL_WEEKLY not set, skipping Slack")

    # 3. Build and push final HTML
    print("Building final HTML...")
    html = build_final_html(data, date)

    briefing_path = f"briefings/{date}.html"
    _, sha = read_gh_file(briefing_path, repo)
    write_gh_file(briefing_path, html, sha, f"Publish briefing {date}", repo)
    print(f"Published: {briefing_path}")

    # 4. Update archive data
    print("Updating archive...")
    archive_content, archive_sha = read_gh_file("data/weekly-data.json", repo)
    archive = json.loads(archive_content) if archive_content else []

    comp_counts = {c["name"]: c["count"] for c in data.get("competitors", [])}
    archive_entry = {
        "date": date,
        "url": f"briefings/{date}.html",
        "mentions": data.get("mentions_count", 0),
        "narrative": data.get("narrative_count", 0),
        "competitor_total": sum(comp_counts.values()),
        "persistent_count": data.get("persistent_count", 0),
        "emerging_count": len([n for n in data.get("narratives", []) if n.get("cadence") in ("new", "sporadic")]),
        "articles_analysed": data.get("articles_analysed", 0),
        "mention_categories": data.get("mention_categories", {}),
        "sentiment": data.get("sentiment", {}),
        "competitors": comp_counts,
        "top_domains": data.get("top_domains", []),
        "narratives": [n["title"] for n in data.get("narratives", [])],
        "headline": data.get("executive_summary", "")[:200],
    }

    archive = [e for e in archive if e.get("date") != date]
    archive.append(archive_entry)
    archive.sort(key=lambda e: e["date"], reverse=True)

    write_gh_file("data/weekly-data.json", json.dumps(archive, indent=2), archive_sha, f"Update archive {date}", repo)
    print(f"Archive updated")
    print(f"\nDone! Briefing live at: {briefing_url}")


if __name__ == "__main__":
    main()
