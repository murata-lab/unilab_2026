from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PAGE_W = 1240
PAGE_H = 1754
MARGIN = 78

NAVY = "#13263D"
BLUE = "#2474C6"
CYAN = "#22B8CF"
GOLD = "#F5B940"
RED = "#D6534D"
INK = "#213042"
MUTED = "#607086"
PAPER = "#F4F7FA"
WHITE = "#FFFFFF"
LINE = "#D8E1EA"
PALE_BLUE = "#EAF4FF"
PALE_CYAN = "#E9FAFC"
PALE_GOLD = "#FFF7DF"
PALE_RED = "#FFF0EE"
CODE_BG = "#172A42"

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "ヒューマンタワーバトル_操作マニュアル.pdf"
FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")

_FONT_CACHE = {}


def font(size):
    key = int(size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(str(FONT_PATH), key)
    return _FONT_CACHE[key]


def line_height(size, gap=10):
    f = font(size)
    box = f.getbbox("国Ag")
    return box[3] - box[1] + gap


def wrap_lines(draw, value, fnt, max_width):
    lines = []
    for paragraph in str(value).split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            trial = current + char
            if current and draw.textlength(trial, font=fnt) > max_width:
                lines.append(current.rstrip())
                current = char.lstrip()
            else:
                current = trial
        if current:
            lines.append(current.rstrip())
    return lines


def draw_text(draw, value, x, y, width, size=28, color=INK, gap=10, bold=False):
    fnt = font(size)
    step = line_height(size, gap)
    stroke = 1 if bold else 0
    for line in wrap_lines(draw, value, fnt, width):
        if line:
            draw.text(
                (x, y),
                line,
                font=fnt,
                fill=color,
                stroke_width=stroke,
                stroke_fill=color,
            )
        y += step
    return y


def centered_text(draw, value, center_x, y, width, size=28, color=INK, gap=8, bold=False):
    fnt = font(size)
    step = line_height(size, gap)
    stroke = 1 if bold else 0
    for line in wrap_lines(draw, value, fnt, width):
        line_width = draw.textlength(line, font=fnt)
        draw.text(
            (center_x - line_width / 2, y),
            line,
            font=fnt,
            fill=color,
            stroke_width=stroke,
            stroke_fill=color,
        )
        y += step
    return y


def rounded_card(draw, box, fill=WHITE, outline=LINE, radius=22, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def section_title(draw, number, title, y, accent=BLUE):
    draw.rounded_rectangle(
        (MARGIN, y, MARGIN + 54, y + 54), radius=14, fill=accent
    )
    centered_text(draw, str(number), MARGIN + 27, y + 7, 50, 27, WHITE, bold=True)
    draw_text(draw, title, MARGIN + 73, y + 4, PAGE_W - MARGIN * 2 - 73, 34, NAVY, bold=True)
    return y + 72


def bullet_list(draw, items, x, y, width, size=27, accent=CYAN, gap_after=12):
    for item in items:
        draw.ellipse((x, y + 13, x + 12, y + 25), fill=accent)
        y = draw_text(draw, item, x + 28, y, width - 28, size, INK, gap=8)
        y += gap_after
    return y


def code_box(draw, lines, x, y, width, size=22):
    if isinstance(lines, str):
        lines = [lines]
    wrapped = []
    fnt = font(size)
    for line in lines:
        wrapped.extend(wrap_lines(draw, line, fnt, width - 52))
    height = 32 + len(wrapped) * line_height(size, 9)
    draw.rounded_rectangle((x, y, x + width, y + height), radius=18, fill=CODE_BG)
    cursor = y + 17
    for line in wrapped:
        draw.text((x + 26, cursor), line, font=fnt, fill="#E8F3FF")
        cursor += line_height(size, 9)
    return y + height


def page_base(page_number, title, subtitle):
    image = Image.new("RGB", (PAGE_W, PAGE_H), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, PAGE_W, 188), fill=NAVY)
    draw.rectangle((0, 180, PAGE_W, 188), fill=CYAN)
    draw_text(draw, "HUMAN TOWER BATTLE 2026", MARGIN, 36, 720, 21, CYAN, bold=True)
    draw_text(draw, title, MARGIN, 73, PAGE_W - MARGIN * 2, 47, WHITE, bold=True)
    draw_text(draw, subtitle, MARGIN, 138, PAGE_W - MARGIN * 2, 22, "#D8E5F1")
    footer_y = PAGE_H - 62
    draw.line((MARGIN, footer_y, PAGE_W - MARGIN, footer_y), fill=LINE, width=2)
    draw_text(draw, "ヒューマンタワーバトル 2026 操作マニュアル", MARGIN, footer_y + 16, 700, 18, MUTED)
    draw_text(draw, f"{page_number} / 3", PAGE_W - MARGIN - 80, footer_y + 16, 80, 18, MUTED)
    return image, draw


def draw_numbered_steps(draw, items, x, y, width, accent=BLUE, size=25):
    for number, text in enumerate(items, start=1):
        draw.ellipse((x, y + 1, x + 42, y + 43), fill=accent)
        centered_text(draw, str(number), x + 21, y + 7, 38, 22, WHITE, bold=True)
        next_y = draw_text(draw, text, x + 60, y, width - 60, size, INK, gap=8)
        y = max(next_y, y + 50) + 9
    return y


def page_one():
    image, draw = page_base(1, "起動とカメラの準備", "完全版を起動し、ゲーム開始画面まで進む")
    y = 224

    rounded_card(draw, (MARGIN, y, PAGE_W - MARGIN, y + 185), fill=PALE_CYAN, outline="#BCEAF0")
    draw_text(draw, "このゲームについて", MARGIN + 28, y + 22, 430, 30, NAVY, bold=True)
    draw_text(
        draw,
        "カメラで撮影した人物をSAM2で切り抜き、物理演算で積み上げるタワーゲームです。人物が床まで落ちないよう、左右・中央を選んで高く積みます。",
        MARGIN + 28,
        y + 70,
        PAGE_W - MARGIN * 2 - 56,
        26,
        INK,
        gap=9,
    )
    y += 215

    y = section_title(draw, 1, "macOSのカメラ権限を確認", y)
    rounded_card(draw, (MARGIN, y, PAGE_W - MARGIN, y + 176))
    bullet_list(
        draw,
        [
            "「システム設定 > プライバシーとセキュリティ > カメラ」を開く。",
            "使用するターミナルを許可する。設定を変えたらターミナルを終了して開き直す。",
        ],
        MARGIN + 28,
        y + 22,
        PAGE_W - MARGIN * 2 - 56,
        25,
    )
    y += 206

    y = section_title(draw, 2, "カメラ番号を確認", y)
    y = code_box(
        draw,
        [
            "cd human_tower_battle_2026",
            "~/.venvs/human_tower_battle_2026/bin/python games/camera_check.py",
            "open camera_check_output/contact_sheet.jpg",
        ],
        MARGIN,
        y,
        PAGE_W - MARGIN * 2,
        21,
    )
    y += 16
    y = draw_text(
        draw,
        "比較画像の Camera 0、Camera 1 などから、使いたいカメラ番号を選びます。",
        MARGIN + 10,
        y,
        PAGE_W - MARGIN * 2 - 20,
        24,
        MUTED,
    )
    y += 18

    y = section_title(draw, 3, "完全版を起動", y)
    y = code_box(
        draw,
        [
            "cd human_tower_battle_2026",
            "HTB_CAMERA_INDEX=0 ~/.venvs/human_tower_battle_2026/bin/python games/main.py",
        ],
        MARGIN,
        y,
        PAGE_W - MARGIN * 2,
        21,
    )
    y += 22
    rounded_card(draw, (MARGIN, y, PAGE_W - MARGIN, y + 116), fill=PALE_GOLD, outline="#F0D58A")
    draw_text(draw, "起動時のポイント", MARGIN + 28, y + 18, 300, 27, NAVY, bold=True)
    draw_text(
        draw,
        "カメラ番号は確認結果に合わせて変更します。SAM2 largeモデルをCPUで読み込むため、画面が開くまで30秒前後待ちます。",
        MARGIN + 28,
        y + 57,
        PAGE_W - MARGIN * 2 - 56,
        23,
        INK,
        gap=7,
    )
    return image


def page_two():
    image, draw = page_base(2, "ゲームの遊び方", "撮影 → 配置 → 落下を繰り返してタワーを作る")
    y = 224

    y = section_title(draw, 1, "基本の流れ", y, CYAN)
    labels = [
        ("1", "ゲーム開始を\nクリック"),
        ("2", "人物をクリック\nまたはドラッグ"),
        ("3", "Enterで撮影\n・切り抜き"),
        ("4", "1・2・3で\n落下位置を選ぶ"),
    ]
    flow_y = y
    gap = 18
    box_w = (PAGE_W - MARGIN * 2 - gap * 3) // 4
    for index, (number, label) in enumerate(labels):
        x = MARGIN + index * (box_w + gap)
        rounded_card(draw, (x, flow_y, x + box_w, flow_y + 178), fill=WHITE, outline="#BCD6ED")
        draw.ellipse((x + box_w / 2 - 25, flow_y + 18, x + box_w / 2 + 25, flow_y + 68), fill=BLUE)
        centered_text(draw, number, x + box_w / 2, flow_y + 27, 48, 24, WHITE, bold=True)
        centered_text(draw, label, x + box_w / 2, flow_y + 84, box_w - 28, 23, INK, gap=7, bold=True)
    y += 208

    y = section_title(draw, 2, "キーとボタン", y)
    rows = [
        ("クリック", "プレビュー上で切り抜く人物の胴体を指定する", GOLD),
        ("ドラッグ", "複数人が映るとき、対象の全身を枠で囲む", GOLD),
        ("右クリック", "クリックまたは枠の指定を解除する", RED),
        ("Enter", "人物を撮影し、切り抜いた次のピースを作る", BLUE),
        ("1", "台の左側へ配置して落とす", CYAN),
        ("2", "台の中央へ配置して落とす", CYAN),
        ("3", "台の右側へ配置して落とす", CYAN),
        ("D", "まだ落としていない人物を破棄する", RED),
    ]
    table_x = MARGIN
    table_w = PAGE_W - MARGIN * 2
    key_w = 230
    row_h = 72
    rounded_card(draw, (table_x, y, table_x + table_w, y + row_h * len(rows)), fill=WHITE)
    for i, (key, description, accent) in enumerate(rows):
        row_y = y + i * row_h
        if i:
            draw.line((table_x, row_y, table_x + table_w, row_y), fill=LINE, width=2)
        draw.rounded_rectangle((table_x + 24, row_y + 12, table_x + key_w - 20, row_y + 60), radius=14, fill=accent)
        centered_text(draw, key, table_x + key_w / 2, row_y + 20, key_w - 60, 22, WHITE, bold=True)
        draw_text(draw, description, table_x + key_w + 18, row_y + 20, table_w - key_w - 42, 23, INK, gap=5)
    y += row_h * len(rows) + 30

    rounded_card(draw, (MARGIN, y, PAGE_W - MARGIN, y + 150), fill=PALE_BLUE, outline="#B9D8F4")
    draw_text(draw, "操作のコツ", MARGIN + 28, y + 19, 260, 29, NAVY, bold=True)
    draw_text(
        draw,
        "胴体を1回クリックするのが基本です。複数人が近い場合は対象の全身をドラッグで囲みます。指定を直すときは再選択、消すときはプレビュー上で右クリックします。",
        MARGIN + 28,
        y + 63,
        PAGE_W - MARGIN * 2 - 56,
        24,
        INK,
        gap=7,
    )
    y += 180

    rounded_card(draw, (MARGIN, y, PAGE_W - MARGIN, y + 172), fill=PALE_RED, outline="#F0C4BF")
    draw_text(draw, "ゲームオーバー", MARGIN + 28, y + 20, 300, 29, RED, bold=True)
    draw_text(
        draw,
        "人物が画面下部の床まで落ちると終了です。結果画面に積み上げ人数と当日のランキングが表示されます。",
        MARGIN + 28,
        y + 63,
        PAGE_W - MARGIN * 2 - 56,
        24,
        INK,
        gap=7,
    )
    draw_text(draw, "もう一度プレイ＝再開　　終了＝ゲームを閉じる", MARGIN + 28, y + 120, PAGE_W - MARGIN * 2 - 56, 23, NAVY, bold=True)
    return image


def option_card(draw, title, command, y, accent=BLUE):
    rounded_card(draw, (MARGIN, y, PAGE_W - MARGIN, y + 172), fill=WHITE)
    draw.rounded_rectangle((MARGIN, y, MARGIN + 16, y + 172), radius=8, fill=accent)
    draw_text(draw, title, MARGIN + 38, y + 18, PAGE_W - MARGIN * 2 - 70, 28, NAVY, bold=True)
    code_box(draw, command, MARGIN + 38, y + 64, PAGE_W - MARGIN * 2 - 68, 20)
    return y + 194


def trouble_row(draw, title, details, y, accent=RED):
    rounded_card(draw, (MARGIN, y, PAGE_W - MARGIN, y + 148), fill=WHITE)
    draw.ellipse((MARGIN + 25, y + 28, MARGIN + 67, y + 70), fill=accent)
    centered_text(draw, "!", MARGIN + 46, y + 34, 38, 22, WHITE, bold=True)
    draw_text(draw, title, MARGIN + 84, y + 20, PAGE_W - MARGIN * 2 - 110, 27, NAVY, bold=True)
    draw_text(draw, details, MARGIN + 84, y + 62, PAGE_W - MARGIN * 2 - 110, 22, INK, gap=7)
    return y + 166


def page_three():
    image, draw = page_base(3, "表示設定とトラブル対処", "設置環境に合わせた起動オプションと確認事項")
    y = 224

    y = section_title(draw, 1, "便利な起動オプション", y, GOLD)
    y = option_card(
        draw,
        "デモモード（カメラ・SAM2なしで動作確認）",
        "HTB_DEMO_MODE=1 ~/.venvs/human_tower_battle_2026/bin/python games/main.py",
        y,
        CYAN,
    )
    y = option_card(
        draw,
        "左側の外部縦モニターへ表示",
        "HTB_USE_EXTERNAL_MONITOR=1 ~/.venvs/human_tower_battle_2026/bin/python games/main.py",
        y,
        BLUE,
    )
    y = option_card(
        draw,
        "ウィンドウサイズを720 × 1245に固定",
        "HTB_WINDOW_WIDTH=720 HTB_WINDOW_HEIGHT=1245 ~/.venvs/human_tower_battle_2026/bin/python games/main.py",
        y,
        GOLD,
    )
    y += 8

    y = section_title(draw, 2, "困ったとき", y, RED)
    y = trouble_row(
        draw,
        "カメラが開かない",
        "macOSのカメラ設定でターミナルを許可し、ターミナルを再起動します。その後 camera_check.py で番号を再確認します。",
        y,
    )
    y = trouble_row(
        draw,
        "人物を切り抜けない",
        "頭から足までを画面内に入れ、胴体をクリックします。複数人が映る場合は対象の全身だけをドラッグで囲みます。別の人が選ばれる場合は枠を少し狭めます。",
        y,
        GOLD,
    )
    y = trouble_row(
        draw,
        "起動が遅い／SDL警告が出る",
        "SAM2 largeモデルのCPU読み込みには約30秒かかります。objc・SDL警告は、ゲーム画面が開けばそのまま利用できます。",
        y,
        BLUE,
    )

    rounded_card(draw, (MARGIN, y, PAGE_W - MARGIN, y + 130), fill=PALE_CYAN, outline="#BCEAF0")
    draw_text(draw, "ローカル保存場所", MARGIN + 28, y + 17, 320, 27, NAVY, bold=True)
    draw_text(
        draw,
        "仮想環境: ~/.venvs/human_tower_battle_2026\n診断起動: HTB_SAVE_SEGMENT_DEBUG=1 HTB_CAMERA_INDEX=0 ... games/main.py\n診断画像: segmentation_debug/　　ランキング: games/ranking.json",
        MARGIN + 28,
        y + 57,
        PAGE_W - MARGIN * 2 - 56,
        21,
        INK,
        gap=7,
    )
    return image


def main():
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"Japanese font not found: {FONT_PATH}")
    pages = [page_one(), page_two(), page_three()]
    pages[0].save(
        OUTPUT,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=pages[1:],
        title="ヒューマンタワーバトル 2026 操作マニュアル",
        author="Human Tower Battle 2026",
        subject="ゲームの起動・操作・トラブル対処",
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
