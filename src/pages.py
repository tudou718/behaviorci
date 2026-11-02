"""pages.py —— 把 JSON 报告渲染成一个静态网页（D10）。

为什么不用 Markdown 直接发布？
    报告里有判定色彩、并排摘要、票型，Markdown 表达不了。而且 Pages 上的
    读者通常是在手机上打开——需要一套能自适应的样式，所以干脆渲染成
    单文件 HTML（CSS 内联，零依赖）。

输入：reports/*.json（compare 已经写好的结构化报告）
输出：_site/index.html（交给 GitHub Pages 发布）

用法：
    python src/pages.py --latest              # 取最新一份 JSON，输出到 _site/
    python src/pages.py reports/x.json --out _site
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERDICT_STYLE = {
    "等价": ("ok", "行为等价"),
    "变好": ("better", "行为变好"),
    "漂移": ("drift", "行为漂移"),
}


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _fmt_ms(ms) -> str:
    if not ms:
        return "—"
    return f"{ms / 1000:.1f}s"


def _verdict_block(verdict: dict) -> tuple[str, str]:
    """返回 (样式类名, 展示文本)。"""
    if verdict.get("skipped"):
        return "skip", "未裁决"
    if verdict.get("verdict") is None:
        return "error", "裁决失败"
    css, label = VERDICT_STYLE.get(verdict["verdict"], ("skip", verdict["verdict"]))
    return css, f"{verdict['verdict']}（{verdict.get('agreement', '')}）"


def _tape_summary(tape: dict) -> str:
    meta = tape.get("meta", {})
    started = (meta.get("started_at") or "").replace("T", " ")[:19]
    return (
        f"<div class='tape'>"
        f"<div class='tape-name'>{_esc(meta.get('variant') or meta.get('run_id'))}</div>"
        f"<div class='tape-meta'>{_esc(started)} · {_fmt_ms(meta.get('duration_ms'))} · "
        f"{_esc(meta.get('step_count', len(tape.get('steps', []))))} 步</div>"
        f"</div>"
    )


def render_html(payload: dict) -> str:
    report = payload["report"]
    content = report["content"]
    verdict = report["verdict"]
    checks = report["checks"]
    summary = report["summary"]

    css_class, verdict_text = _verdict_block(verdict)
    generated = payload.get("generated_at", "").replace("T", " ")[:19]

    checks_html = "\n".join(
        f"<tr><td>{_esc(c['label'])}</td>"
        f"<td class='{'pass' if c['consistent'] else 'fail'}'>"
        f"{'✓ 一致' if c['consistent'] else '✗ 不同'}</td>"
        f"<td>{_esc(c['detail'])}</td></tr>"
        for c in checks
    )

    if content["changed_steps"]:
        root_names = {r["name"] for r in content["root_steps"]}
        change_items = "\n".join(
            f"<li>第 {item['index']} 步「{_esc(item['label'])}」：输出 "
            f"{item['diff_count']} 处不同"
            f"{'（源头）' if item['name'] in root_names else '（输入来自上游，输出跟着变）'}</li>"
            for item in content["changed_steps"]
        )
        if content["final_output_changed"]:
            change_items += "\n<li>最终交付物（summary）也变了</li>"
        changes_html = f"<ul>{change_items}</ul>"
    else:
        changes_html = "<p>两份磁带内容完全一致。</p>"

    runs_html = ""
    if verdict.get("runs"):
        runs_html = "".join(
            f"<li><span class='vote'>{_esc(r['verdict'])}</span>"
            f"<span class='vote-reason'>{_esc(r['reason'])}</span></li>"
            for r in verdict["runs"]
        )
        runs_html = f"<ol class='votes'>{runs_html}</ol>"

    reason_html = ""
    if verdict.get("verdict") and not verdict.get("skipped"):
        reason_html = f"<p class='reason'>「{_esc(verdict['reason'])}」</p>"
    elif verdict.get("reason"):
        reason_html = f"<p class='reason'>{_esc(verdict['reason'])}</p>"

    base_text = (payload.get("baseline") or {}).get("output", {})
    # compare 的 JSON 里不带完整磁带，摘要从报告里取；这里做个兜底
    base_summary = base_text.get("summary", "") if isinstance(base_text, dict) else ""
    cand_summary = (payload.get("candidate") or {}).get("output", {})
    cand_summary = cand_summary.get("summary", "") if isinstance(cand_summary, dict) else ""

    tape_html = ""
    for label, tape in (("基线", payload.get("baseline")), ("候选", payload.get("candidate"))):
        if tape:
            tape_html += f"<div class='tape-col'><h4>{label}</h4>{_tape_summary(tape)}</div>"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BehaviorCI · {_esc(report['task'])} 巡检报告</title>
<style>
  :root {{
    --bg: #f7f8fa; --card: #ffffff; --ink: #1a1d24; --muted: #6b7280;
    --line: #e5e7eb; --ok: #0f766e; --better: #1d4ed8; --drift: #b91c1c;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1115; --card:#171a21; --ink:#e8eaed; --muted:#9aa0a6;
             --line:#2a2e37; --ok:#2dd4bf; --better:#93c5fd; --drift:#f87171; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font: 15px/1.65 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }}
  main {{ max-width: 860px; margin: 0 auto; padding: 32px 16px 64px; }}
  header h1 {{ font-size: 22px; margin: 0 0 6px; }}
  header p {{ margin: 0; color: var(--muted); font-size: 13px; }}
  .verdict {{ margin: 24px 0; padding: 20px; border-radius: 12px;
              border-left: 5px solid var(--ok); background: var(--card); }}
  .verdict.better {{ border-left-color: var(--better); }}
  .verdict.drift  {{ border-left-color: var(--drift); }}
  .verdict.skip, .verdict.error {{ border-left-color: var(--muted); }}
  .verdict .label {{ font-size: 13px; color: var(--muted); }}
  .verdict .value {{ font-size: 26px; font-weight: 700; margin: 4px 0 8px; }}
  .verdict.drift .value {{ color: var(--drift); }}
  .verdict.ok .value {{ color: var(--ok); }}
  .verdict.better .value {{ color: var(--better); }}
  .reason {{ margin: 0; color: var(--ink); }}
  section {{ background: var(--card); border-radius: 12px; padding: 20px;
             margin: 16px 0; border: 1px solid var(--line); }}
  section h2 {{ font-size: 15px; margin: 0 0 12px; color: var(--muted); font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); }}
  th {{ color: var(--muted); font-weight: 500; font-size: 12px; }}
  .pass {{ color: var(--ok); white-space: nowrap; }}
  .fail {{ color: var(--drift); white-space: nowrap; }}
  .tapes {{ display: flex; gap: 12px; flex-wrap: wrap; }}
  .tape-col {{ flex: 1 1 240px; }}
  .tape-col h4 {{ margin: 0 0 8px; font-size: 13px; color: var(--muted); }}
  .tape {{ border: 1px solid var(--line); border-radius: 10px; padding: 12px; }}
  .tape-name {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }}
  .tape-meta {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
  blockquote {{ margin: 0 0 12px; padding: 10px 14px; border-left: 3px solid var(--line);
                color: var(--ink); background: transparent; }}
  .votes {{ padding-left: 20px; margin: 0; }}
  .votes li {{ margin: 8px 0; }}
  .vote {{ font-weight: 600; margin-right: 8px; }}
  .vote-reason {{ color: var(--muted); }}
  footer {{ color: var(--muted); font-size: 12px; margin-top: 24px; text-align: center; }}
</style>
</head>
<body>
<main>
  <header>
    <h1>BehaviorCI · 行为回归巡检</h1>
    <p>任务 {_esc(report['task'])} · 生成于 {_esc(generated)}</p>
  </header>

  <div class="verdict {css_class}">
    <div class="label">最终判定</div>
    <div class="value">{_esc(verdict_text)}</div>
    {reason_html}
  </div>

  <section>
    <h2>结构对比</h2>
    <table>
      <thead><tr><th>检查项</th><th>结果</th><th>说明</th></tr></thead>
      <tbody>{checks_html}</tbody>
    </table>
    <p style="color:var(--muted);font-size:13px;margin:12px 0 0">
      {summary['total']} 项对比，{summary['consistent']} 项一致，{summary['different']} 项不同
    </p>
  </section>

  <section>
    <h2>磁带概要</h2>
    <div class="tapes">{tape_html}</div>
  </section>

  <section>
    <h2>内容差异</h2>
    {changes_html}
  </section>

  {'<section><h2>最终交付物对比</h2><blockquote><strong>基线</strong><br>' + _esc(base_summary or '（空）') + '</blockquote><blockquote><strong>候选</strong><br>' + _esc(cand_summary or '（空）') + '</blockquote></section>' if (base_summary or cand_summary) else ''}

  <section>
    <h2>裁判</h2>
    {f"<p>投票：{verdict.get('agreement', '—')}</p>" if verdict.get('agreement') else ''}
    {runs_html or '<p>本次未调用裁判。</p>'}
  </section>

  <footer>
    由 BehaviorCI 生成 · 模型 {_esc((verdict or {}).get('model') or '—')}<br>
    基线 {_esc(payload.get('baseline_tape', '—'))} · 候选 {_esc(payload.get('candidate_tape', '—'))}
  </footer>
</main>
</body>
</html>
"""


def build(payload_path: Path, out_dir: Path) -> Path:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"
    index.write_text(render_html(payload), encoding="utf-8")
    return index


def latest_report() -> Path:
    reports = sorted((ROOT / "reports").glob("*.json"))
    if not reports:
        raise SystemExit("reports/ 里没有 JSON 报告，先跑一次 compare")
    return reports[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="把 JSON 报告渲染成静态网页")
    parser.add_argument("report", nargs="?", help="报告 JSON 路径；省略则取最新一份")
    parser.add_argument("--out", default=str(ROOT / "_site"), help="输出目录")
    parser.add_argument("--latest", action="store_true", help="取 reports/ 里最新一份")
    args = parser.parse_args()

    path = latest_report() if (args.latest or not args.report) else Path(args.report)
    index = build(path, Path(args.out))
    print(f"✓ 网页已生成：{index}")


if __name__ == "__main__":
    main()