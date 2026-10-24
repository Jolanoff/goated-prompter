"""The verdict and the report page (report.html, report.md) of one quality run."""

import html
import json

from .judge import DIMENSIONS, GUARD, leaning

def _wrong_way(row):
    from .checks import CHECKS
    higher = next((up for name, _, _, up in CHECKS if name == row["check"]), True)
    return (row["candidate"] > row["baseline"]) != higher


def verdict(audit_result, check_rows, review):
    """(verdict, reasons_worse, reasons_better, notes)."""
    worse, better, notes = [], [], []
    if audit_result and not audit_result.get("changes") and not audit_result.get("assembled"):
        notes.append("The old and new code give the model the same instructions, so differences in the outputs are "
                     "chance. To test a change you already committed, set baseline to the commit before it "
                     "(for example HEAD~1).")
    if audit_result:
        if audit_result["new"]:
            worse.append(f"{len(audit_result['new'])} new collision(s) between settings")
        if audit_result["fixed"]:
            better.append(f"{len(audit_result['fixed'])} collision(s) fixed")
        if audit_result["errors"]:
            worse.append(f"{len(audit_result['errors'])} setting combination(s) no longer build")
    for row in check_rows or []:
        if row["change"] == "n/a":
            continue
        if row["kind"] in ("info", "hint"):  # reported, never the verdict: time and retries, or a word-pattern pointer
            if row["change"] in ("better", "worse"):
                notes.append(f"{row['check']} ({row['kind']}) went {'down' if row['candidate'] < row['baseline'] else 'up'}"
                             f" ({row['baseline']} -> {row['candidate']})"
                             + (": read the scenes it points at" if row["kind"] == "hint" else ""))
            continue
        if row["change"] in ("better", "worse"):
            (better if row["change"] == "better" else worse).append(
                f"{row['check']} {'improved' if row['change'] == 'better' else 'got worse'} "
                f"({row['baseline']} -> {row['candidate']})")
        elif row["change"] == "same" and row["baseline"] is not None and row["candidate"] is not None \
                and abs(row["candidate"] - row["baseline"]) >= 0.05:
            notes.append(f"{row['check']} may have got {'worse' if _wrong_way(row) else 'better'} "
                         f"({row['baseline']} -> {row['candidate']}), but within noise ({row['noise']}): "
                         "run more seeds to know")
    if review:
        if not review["counts"]:
            notes.append(f"The review by {review['reviewer'] or 'an unnamed reviewer'} ({review['kind'] or 'no kind'}) "
                         "is shown as a hint only: name a reviewer and use kind human or independent for it to count.")
        else:
            for name, tally in review["dimensions"].items():
                lean = leaning(tally)
                if lean == "worse" and name in GUARD:
                    worse.append(f"reviewers prefer the old output on {name}")
                elif lean == "worse":
                    notes.append(f"reviewers prefer the old output on {name}")
                elif lean == "better":
                    better.append(f"reviewers prefer the new output on {name}")
    else:
        notes.append("Not reviewed yet: the verdict comes from the audit and the automatic checks only.")
    result = "Worse" if worse else "Better" if better else "No real difference"
    return result, worse, better, notes


def _table(rows, columns):
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(row.get(key, '') if row.get(key) is not None else '–'))}</td>"
                                    for key, _ in columns) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


STYLE = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e2e2dc;--good:#1f7a3a;--bad:#b3261e;--mid:#8a6d00}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ececea;--muted:#a3a39c;--card:#20201e;--line:#34342f;--good:#5fc27e;--bad:#ff8a80;--mid:#e0c060}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px}h3{font-size:15px;margin:16px 0 6px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0}
.verdict{font-size:22px;font-weight:700}.Better{color:var(--good)}.Worse{color:var(--bad)}.No{color:var(--mid)}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.better{color:var(--good)}.worse{color:var(--bad)}pre{white-space:pre-wrap;margin:0;font:13px/1.45 ui-monospace,monospace}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media (max-width:760px){.pair{grid-template-columns:1fr}}
.added{color:var(--good)}.removed{color:var(--bad);text-decoration:line-through}
.dims{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:6px 16px;margin-top:10px}
label{margin-right:10px}button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
input,select{font:inherit;padding:6px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
"""


def _case_table(case_checks):
    """Old -> new per request (seeds averaged), for the checks that apply to it."""
    from .checks import CHECKS
    rows = []
    for case, sides in case_checks.items():
        cells = [f"{name}: {sides['baseline'][name]} -> {sides['candidate'][name]}" for name, *_ in CHECKS
                 if sides["baseline"].get(name) is not None or sides["candidate"].get(name) is not None]
        rows.append({"case": case, "values": " · ".join(cells)})
    return "<h3>Per request</h3>" + _table(rows, (("case", "Request"), ("values", "Old -> new")))


def _stage_table(stages):
    """Model calls, failed calls and tokens per stage, old -> new, over all runs."""
    rows = []
    for stage in sorted(set(stages.get("baseline") or {}) | set(stages.get("candidate") or {})):
        old, new = (stages.get(side, {}).get(stage, {}) for side in ("baseline", "candidate"))
        rows.append({"stage": stage, **{key: f"{old.get(key, 0)} -> {new.get(key, 0)}"
                                        for key in ("calls", "failed", "tokens")}})
    return "<h3>Model calls by stage</h3>" + _table(rows, (("stage", "Stage"), ("calls", "Calls"),
                                                         ("failed", "Failed"), ("tokens", "Tokens")))


def _changes_html(changes):
    if not changes:
        return "<p class='muted'>No guide text changed.</p>"
    blocks = []
    for row in changes:
        lines = [f"<div class='removed'>− {html.escape(text)}</div>" for text in row["removed"]]
        lines += [f"<div class='added'>+ {html.escape(text)}</div>" for text in row["added"]]
        blocks.append(f"<div class='card'><b>{html.escape(row['where'])}</b>{''.join(lines)}</div>")
    return "".join(blocks)


def _review_form(packet):
    if not packet or not packet["pairs"]:
        return "<p class='muted'>No pairs to review (the live run is off or failed).</p>"
    out = ["<div class='card'><p>Pick the better output for each point, without knowing which one is new. Then click "
           "<b>Download review</b>, save <code>review.json</code> into this run's folder and run "
           "<code>quality.bat report</code>.</p><p>Reviewer <input id='reviewer' placeholder='your name'> Kind "
           "<select id='kind'><option>human</option><option>independent</option><option>exploratory</option></select> "
           "<button onclick='save()'>Download review</button></p></div>"]
    for index, pair in enumerate(packet["pairs"]):
        dims = "".join(
            f"<div><b>{html.escape(name)}</b><br>" + "".join(
                f"<label><input type='radio' name='p{index}-{name}' value='{value}'> {value}</label>"
                for value in ("A", "B", "tie")) + "</div>" for name in DIMENSIONS)
        out.append(f"<div class='card' data-pair='{html.escape(pair['pair'], quote=True)}' data-index='{index}'>"
                   f"<h3>{html.escape(pair['pair'])}</h3><p><b>Request:</b> {html.escape(pair['request'])}<br>"
                   f"<span class='muted'>{html.escape(pair['settings'])}</span></p><div class='pair'>"
                   f"<div><h3>A</h3><pre>{html.escape(pair['a'])}</pre></div>"
                   f"<div><h3>B</h3><pre>{html.escape(pair['b'])}</pre></div></div><div class='dims'>{dims}</div></div>")
    dims = json.dumps(list(DIMENSIONS))
    out.append("<script>const DIMS=" + dims + ";function save(){const pairs={};document.querySelectorAll('[data-pair]')"
               ".forEach(card=>{const i=card.dataset.index,a={};DIMS.forEach(d=>{const c=card.querySelector(`input[name=\"p${i}-${d}\"]:checked`);"
               "a[d]=c?c.value:''});pairs[card.dataset.pair]=a});const review={reviewer:document.getElementById('reviewer').value,"
               "review_kind:document.getElementById('kind').value,pairs};const blob=new Blob([JSON.stringify(review,null,1)],"
               "{type:'application/json'});const link=document.createElement('a');link.href=URL.createObjectURL(blob);"
               "link.download='review.json';link.click()}</script>")
    return "".join(out)


def render(run):
    """(html, markdown) for a finished run dictionary."""
    result, worse, better, notes = run["verdict"]
    audit_result, check_rows, review = run.get("audit"), run.get("checks"), run.get("review")
    css = result.split()[0]
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
             f"initial-scale=1'><title>Quality report</title><style>{STYLE}</style></head><body><main>",
             f"<h1>Quality report</h1><p class='muted'>{html.escape(run['label'])}</p>",
             f"<div class='card'><div class='verdict {css}'>{html.escape(result)}</div>"
             + "".join(f"<div class='worse'>▼ {html.escape(item)}</div>" for item in worse)
             + "".join(f"<div class='better'>▲ {html.escape(item)}</div>" for item in better)
             + "".join(f"<div class='muted'>• {html.escape(item)}</div>" for item in notes) + "</div>"]
    if audit_result:
        parts.append("<h2>1. Collisions between settings</h2>")
        for title, key in (("New", "new"), ("Fixed", "fixed"), ("Still there", "remaining")):
            rows = audit_result[key]
            parts.append(f"<h3>{title} ({len(rows)})</h3>" + (_table(rows, (("owner", "Guide"), ("name", "Part"),
                         ("decision", "Belongs to"), ("sentence", "Sentence"))) if rows else "<p class='muted'>None.</p>"))
        if audit_result["duplicates"]:
            parts.append("<h3>Same rule written twice</h3>" + _table(audit_result["duplicates"], (
                ("a", "Here"), ("b", "And here"), ("sentence_a", "Sentence"))))
        if audit_result["errors"]:
            parts.append("<h3>Settings that no longer build</h3>" + _table(
                [{"settings": name, "error": text} for name, text in audit_result["errors"].items()],
                (("settings", "Settings"), ("error", "Error"))))
        parts.append("<h2>2. What changed in the guides</h2>" + _changes_html(audit_result["changes"]))
        if audit_result["assembled"]:
            parts.append(f"<p class='muted'>The instructions the model receives changed for {len(audit_result['assembled'])} "
                         f"setting combination(s): {html.escape(', '.join(audit_result['assembled'][:40]))}"
                         + (" …" if len(audit_result["assembled"]) > 40 else "") + "</p>")
    if check_rows:
        parts.append("<h2>3. Automatic checks (old -> new)</h2>" + _table(check_rows, (
            ("check", "Check"), ("about", "What it measures"), ("kind", "Kind"), ("baseline", "Old"),
            ("candidate", "New"), ("noise", "Seed noise"), ("change", "Change"))))
        parts.append("<p class='muted'>guard: must never get worse · aim: should improve · hint: a word-pattern "
                     "pointer, never the verdict · info: reported · noise: how much the number moves between the "
                     "paired runs of old and new; a smaller difference is chance · per-case numbers are below and "
                     "in checks.json</p>")
        if run.get("case_checks"):
            parts.append(_case_table(run["case_checks"]))
        if any((run.get("stages") or {}).values()):
            parts.append(_stage_table(run["stages"]))
    if review:
        rows = [{"dimension": name, **tally, "leaning": leaning(tally)} for name, tally in review["dimensions"].items()]
        parts.append(f"<h2>4. Blind review by {html.escape(review['reviewer'] or 'unnamed')} ({html.escape(review['kind'])})</h2>"
                     + _table(rows, (("dimension", "Point"), ("wins", "New better"), ("losses", "Old better"),
                                     ("ties", "Tie"), ("leaning", "Result"))))
    parts.append("<h2>Review the outputs</h2>" + _review_form(run.get("packet")))
    parts.append("</main></body></html>")
    md = [f"# Quality report — {result}", "", run["label"], ""] + [f"- worse: {item}" for item in worse] \
        + [f"- better: {item}" for item in better] + [f"- note: {item}" for item in notes]
    if audit_result:
        md += ["", f"Collisions: {len(audit_result['new'])} new, {len(audit_result['fixed'])} fixed, "
                   f"{len(audit_result['remaining'])} still there; {len(audit_result['changes'])} guide part(s) changed."]
    if check_rows:
        md += ["", "| Check | Old | New | Change |", "| --- | --- | --- | --- |"] + [
            f"| {row['check']} | {row['baseline']} | {row['candidate']} | {row['change']} |" for row in check_rows]
    if any((stages := run.get("stages") or {}).values()):
        md += ["", "| Stage | Calls | Failed | Tokens |", "| --- | --- | --- | --- |"]
        for stage in sorted(set(stages.get("baseline") or {}) | set(stages.get("candidate") or {})):
            old, new = (stages.get(side, {}).get(stage, {}) for side in ("baseline", "candidate"))
            md.append(f"| {stage} | " + " | ".join(f"{old.get(key, 0)} -> {new.get(key, 0)}"
                                                   for key in ("calls", "failed", "tokens")) + " |")
    return "".join(parts), "\n".join(md) + "\n"
