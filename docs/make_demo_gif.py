"""把一次真实运行的终端输出渲染成演示 GIF（D12）。

为什么不用录屏软件？
    Kap / QuickTime 需要人手操作，而且录出来会带上本机的窗口、字体、缩放。
    这里直接把「真实命令输出」逐行画成终端画面——内容一模一样，可复现，
    改一次 README 就能重新生成。

字体为什么要两套？
    等宽英文字体（Menlo）没有中文字形，直接画会变成豆腐块。
    所以 ASCII 用 Menlo、中文回退到 Hiragino Sans GB，按字符分段绘制。

用法：
    python docs/make_demo_gif.py
输入：docs/demo-session.txt（真实命令 + 输出，原样保存）
输出：docs/demo.gif
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SESSION = ROOT / "docs" / "demo-session.txt"
OUT = ROOT / "docs" / "demo.gif"

WIDTH, HEIGHT = 980, 640
PAD_X, PAD_Y = 22, 16
TITLE_H = 36
LINE_H = 19
FONT_SIZE = 13

BG = (15, 17, 21)
TITLE_BG = (24, 27, 33)
INK = (215, 218, 224)
DIM = (139, 148, 158)
GREEN = (52, 211, 153)
RED = (248, 113, 113)
CYAN = (125, 211, 252)
YELLOW = (253, 224, 71)
PROMPT = (110, 231, 183)

ASCII_FONTS = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
]
CJK_FONTS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Songti.ttc",
]
# ✓ / ✗ 这类符号不在等宽英文字体里，也不在中文字体里，单独找一个符号字体
SYMBOL_FONTS = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Apple Symbols.ttf",
    "/System/Library/Fonts/Symbol.ttf",
]
SYMBOLS = set("✓✗✔✘→←↑↓")


def _load(paths: list[str]) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in paths:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, FONT_SIZE, index=0)
            except OSError:
                continue
    return ImageFont.load_default()


def color_for(line: str) -> tuple[int, int, int]:
    """按行内容上色，模拟终端里的高亮。"""
    stripped = line.strip()
    if stripped.startswith("$"):
        return PROMPT
    if "✓" in stripped:
        return GREEN
    if "✗" in stripped:
        return RED
    if stripped.startswith(("结论：", "理由：")):
        return YELLOW
    if stripped.startswith(("裁判（", "对比：", "任务：")):
        return CYAN
    if stripped and set(stripped) <= {"="} or stripped and set(stripped) <= {"-"}:
        return DIM
    return INK


def _font_kind(ch: str) -> str:
    if ch in SYMBOLS:
        return "symbol"
    return "ascii" if ord(ch) < 128 else "cjk"


def text_width(
    text: str, ascii_font, cjk_font, symbol_font, draw: ImageDraw.ImageDraw
) -> float:
    width = 0.0
    for ch in text:
        font = {"ascii": ascii_font, "cjk": cjk_font, "symbol": symbol_font}[
            _font_kind(ch)
        ]
        width += draw.textlength(ch, font=font)
    return width


def draw_mixed(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    text: str,
    fill,
    ascii_font,
    cjk_font,
    symbol_font,
) -> float:
    """逐段绘制：ASCII / 中文 / 符号各用各的字体，避免豆腐块。"""
    fonts = {"ascii": ascii_font, "cjk": cjk_font, "symbol": symbol_font}
    run: list[str] = []
    current_kind = None

    def flush(buffer: list[str]) -> None:
        nonlocal x
        if not buffer:
            return
        font = fonts[current_kind]
        chunk = "".join(buffer)
        draw.text((x, y), chunk, font=font, fill=fill)
        x += draw.textlength(chunk, font=font)

    for ch in text:
        kind = _font_kind(ch)
        if current_kind is None or kind == current_kind:
            run.append(ch)
            current_kind = kind
        else:
            flush(run)
            run = [ch]
            current_kind = kind
    flush(run)
    return x


def fit_line(text: str, max_w: float, draw, ascii_font, cjk_font, symbol_font) -> str:
    """超宽的行截断加省略号。"""
    if text_width(text, ascii_font, cjk_font, symbol_font, draw) <= max_w:
        return text
    out = []
    width = 0.0
    for ch in text:
        font = {
            "ascii": ascii_font,
            "cjk": cjk_font,
            "symbol": symbol_font,
        }[_font_kind(ch)]
        w = draw.textlength(ch, font=font)
        if width + w > max_w - 14:
            break
        out.append(ch)
        width += w
    return "".join(out) + "…"


def draw_frame(
    lines: list[str],
    shown: int,
    cursor_on: bool,
    ascii_font,
    cjk_font,
    symbol_font,
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, WIDTH, TITLE_H], fill=TITLE_BG)
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 18 + i * 18
        draw.ellipse([cx - 5, TITLE_H // 2 - 5, cx + 5, TITLE_H // 2 + 5], fill=color)
    draw.text((82, 10), "behaviorci — python main.py compare", font=ascii_font, fill=DIM)

    y = TITLE_H + PAD_Y
    for line in lines[:shown]:
        draw_mixed(
            draw, PAD_X, y, line, color_for(line), ascii_font, cjk_font, symbol_font
        )
        y += LINE_H

    if cursor_on and 0 < shown <= len(lines):
        last = lines[shown - 1]
        cursor_x = (
            PAD_X + text_width(last, ascii_font, cjk_font, symbol_font, draw) + 3
        )
        draw.rectangle([cursor_x, y - LINE_H + 4, cursor_x + 7, y - 4], fill=INK)
    return img


def main() -> None:
    ascii_font = _load(ASCII_FONTS)
    cjk_font = _load(CJK_FONTS)
    symbol_font = _load(SYMBOL_FONTS)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    raw_lines = SESSION.read_text(encoding="utf-8").rstrip("\n").split("\n")
    max_w = WIDTH - PAD_X * 2
    lines = [
        fit_line(line, max_w, probe, ascii_font, cjk_font, symbol_font)
        for line in raw_lines
    ]

    frames: list[Image.Image] = []
    durations: list[int] = []

    frames.append(draw_frame(lines, 0, True, ascii_font, cjk_font, symbol_font))
    durations.append(800)

    for shown in range(1, len(lines) + 1):
        frames.append(
            draw_frame(lines, shown, True, ascii_font, cjk_font, symbol_font)
        )
        durations.append(260 if shown > 3 else 150)

    for i in range(6):
        frames.append(
            draw_frame(
                lines, len(lines), i % 2 == 0, ascii_font, cjk_font, symbol_font
            )
        )
        durations.append(350)
    durations[-1] = 2500

    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(
        f"✓ {OUT} | {len(frames)} 帧 | {sum(durations) / 1000:.1f}s | "
        f"{OUT.stat().st_size / 1024:.0f} KB"
    )


if __name__ == "__main__":
    main()