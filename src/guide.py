"""guide.py —— 把接入指南渲染成一个独立的网页（D12+）。

为什么单独做一页？
    接入指南是写给「第一次接触的人」的。埋在某份 Markdown 里，
    对方得先找到仓库、再找到文件、再点开原始视图。做成一个公开网址，
    发出去就能看，手机也能读。

用法：
    python src/guide.py                     # 输出 docs/integration.html
    python src/guide.py --out _site/guide.html
"""

from __future__ import annotations

import argparse
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "integration.md"
DEFAULT_OUT = ROOT / "docs" / "integration.html"

TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BehaviorCI · 接入指南</title>
<style>
  :root {{
    --bg:#f7f8fa; --card:#fff; --ink:#1a1d24; --muted:#6b7280;
    --line:#e5e7eb; --accent:#0f766e; --code-bg:#f3f4f6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1115; --card:#171a21; --ink:#e8eaed; --muted:#9aa0a6;
             --line:#2a2e37; --accent:#2dd4bf; --code-bg:#11141a; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font: 16px/1.75 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }}
  .wrap {{ max-width: 820px; margin: 0 auto; padding: 24px 18px 80px; }}
  .top {{ display:flex; justify-content:space-between; align-items:center;
          padding-bottom:16px; border-bottom:1px solid var(--line); margin-bottom:8px; }}
  .top a {{ color: var(--accent); text-decoration: none; font-size: 14px; }}
  .top .brand {{ font-weight: 700; font-size: 15px; color: var(--ink); }}
  h1 {{ font-size: 28px; line-height:1.3; margin: 24px 0 8px; }}
  h2 {{ font-size: 20px; margin: 40px 0 12px; padding-top: 16px;
        border-top: 1px solid var(--line); }}
  h3 {{ font-size: 16px; margin: 24px 0 8px; }}
  p {{ margin: 10px 0; }}
  ul, ol {{ padding-left: 22px; }}
  li {{ margin: 6px 0; }}
  blockquote {{ margin: 16px 0; padding: 12px 16px; border-left: 4px solid var(--accent);
                background: var(--card); color: var(--ink); border-radius: 0 8px 8px 0; }}
  blockquote p {{ margin: 4px 0; color: var(--muted); }}
  code {{ background: var(--code-bg); padding: 2px 6px; border-radius: 5px;
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9em; }}
  pre {{ background: var(--code-bg); padding: 16px; border-radius: 10px;
         overflow-x: auto; border: 1px solid var(--line); }}
  pre code {{ background: none; padding: 0; font-size: 13px; line-height: 1.6; }}
  table {{ width:100%; border-collapse: collapse; margin: 16px 0; font-size: 14px;
           background: var(--card); border-radius: 10px; overflow: hidden; }}
  th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left;
            vertical-align: top; }}
  th {{ color: var(--muted); font-weight: 600; font-size: 13px; }}
  hr {{ border: none; border-top: 1px solid var(--line); margin: 32px 0; }}
  a {{ color: var(--accent); }}
  .footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--line);
             color: var(--muted); font-size: 13px; text-align: center; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <span class="brand">BehaviorCI</span>
    <span><a href="./">最新巡检报告</a> · <a href="https://github.com/tudou718/behaviorci">GitHub</a></span>
  </div>
  {body}
  <div class="footer">
    BehaviorCI · 接入指南 · 有问题请在 GitHub 提 Issue
  </div>
</div>
</body>
</html>
"""


def build(source: Path = SOURCE, out: Path = DEFAULT_OUT) -> Path:
    body = markdown.markdown(
        source.read_text(encoding="utf-8"),
        extensions=["fenced_code", "tables", "sane_lists", "toc"],
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.format(body=body), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="渲染接入指南网页")
    parser.add_argument("--source", default=str(SOURCE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    path = build(Path(args.source), Path(args.out))
    print(f"✓ 指南网页已生成：{path}")


if __name__ == "__main__":
    main()