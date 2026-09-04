from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


W, H = 1080, 1440
OUT = Path("data/output/minato_tower_report/images")
ELEPHANT_LOGO = Path("logoELE.png")
FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/Hiragino Sans GB.ttc"
PUBLISH_MONTH = f"{date.today().year}年{date.today().month}月"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def curve_points(points, steps=24):
    result = []
    for i in range(steps + 1):
        t = i / steps
        x = (
            (1 - t) ** 3 * points[0][0]
            + 3 * (1 - t) ** 2 * t * points[1][0]
            + 3 * (1 - t) * t**2 * points[2][0]
            + t**3 * points[3][0]
        )
        y = (
            (1 - t) ** 3 * points[0][1]
            + 3 * (1 - t) ** 2 * t * points[1][1]
            + 3 * (1 - t) * t**2 * points[2][1]
            + t**3 * points[3][1]
        )
        result.append((round(x), round(y)))
    return result


def base():
    image = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(image)
    return image, draw


def cover():
    image, draw = base()
    logo = Image.open(ELEPHANT_LOGO).convert("RGBA")
    black_pixels = []
    for source_y in range(logo.height):
        for source_x in range(logo.width):
            r, g, b, a = logo.getpixel((source_x, source_y))
            if a and r < 80 and g < 80 and b < 80:
                black_pixels.append((source_x, source_y))
    if black_pixels:
        xs = [point[0] for point in black_pixels]
        ys = [point[1] for point in black_pixels]
        padding = 70
        logo = logo.crop(
            (
                max(min(xs) - padding, 0),
                max(min(ys) - padding, 0),
                min(max(xs) + padding, logo.width),
                min(max(ys) + padding, logo.height),
            )
        )
    max_logo_w, max_logo_h = 360, 260
    scale = min(max_logo_w / logo.width, max_logo_h / logo.height)
    logo_w = round(logo.width * scale)
    logo_h = round(logo.height * scale)
    logo = logo.resize((logo_w, logo_h))
    logo_px = logo.load()
    for logo_y in range(logo.height):
        for logo_x in range(logo.width):
            r, g, b, a = logo_px[logo_x, logo_y]
            if a == 0:
                continue
            if r < 80 and g < 80 and b < 80:
                logo_px[logo_x, logo_y] = (0, 0, 0, a)
            else:
                logo_px[logo_x, logo_y] = (255, 255, 255, 0)
    image.paste(logo, ((W - logo_w) // 2, 80), logo)
    draw.text((72, 555), "东京港区", fill="#111111", font=font(92, True))
    draw.text((72, 675), "塔楼租还是买？", fill="#111111", font=font(72, True))
    draw.text((72, 785), "我替钱包瞄了一眼", fill="#111111", font=font(34))
    draw.text((72, 845), PUBLISH_MONTH, fill="#666666", font=font(32))
    draw.text((72, 905), "吃饱饭，没事干，纯分享。", fill="#111111", font=font(30))
    # Minimal tower skyline drawn only with black lines.
    draw.line((72, 1240, 1008, 1240), fill="#111111", width=3)
    towers = [(110, 1080, 220), (255, 1010, 160), (450, 930, 210), (700, 1040, 145), (870, 970, 115)]
    for x, y, width in towers:
        draw.rectangle((x, y, x + width, 1240), outline="#111111", width=4)
        draw.line((x, y, x + width // 2, y - 35, x + width, y), fill="#111111", width=4, joint="curve")
        for window_y in range(y + 45, 1210, 55):
            draw.line((x + 28, window_y, x + width - 28, window_y), fill="#111111", width=2)
    image.save(OUT / "01-cover-clean.png", quality=95)


def chart(filename, title, subtitle, values, labels, change, note):
    image, draw = base()
    draw.text((72, 210), title, fill="#111111", font=font(66, True))
    draw.text((72, 305), subtitle, fill="#666666", font=font(28))
    draw.line((72, 370, 1008, 370), fill="#111111", width=2)

    xs = [190, 540, 890]
    ys = [900, 710, 530]
    for y in (530, 710, 900):
        draw.line((140, y, 940, y), fill="#DDDDDD", width=2)
    draw.line(list(zip(xs, ys)), fill="#111111", width=9, joint="curve")
    for x, y, value, label in zip(xs, ys, values, labels):
        draw.ellipse((x - 15, y - 15, x + 15, y + 15), fill="white", outline="#111111", width=7)
        box = draw.textbbox((0, 0), value, font=font(44, True))
        draw.text((x - (box[2] - box[0]) / 2, y - 85), value, fill="#111111", font=font(44, True))
        box = draw.textbbox((0, 0), label, font=font(27))
        draw.text((x - (box[2] - box[0]) / 2, 980), label, fill="#111111", font=font(27))

    draw.text((72, 1165), "2023 → 2025", fill="#666666", font=font(30))
    draw.text((72, 1240), change, fill="#111111", font=font(80, True))
    box = draw.textbbox((0, 0), note, font=font(22))
    draw.text((1008 - (box[2] - box[0]), 1365), note, fill="#777777", font=font(22))
    image.save(OUT / filename, quality=95)


def comparison_card():
    image, draw = base()
    draw.text((72, 205), "房型 × 面积 × 租售单价", fill="#111111", font=font(58, True))
    draw.text((72, 292), "2025年最新记录", fill="#666666", font=font(27))
    draw.line((72, 360, 1008, 360), fill="#111111", width=2)

    cols = [72, 390, 675, 1008]
    headers = ["房源分类", "面积", "租赁单价", "买卖单价"]
    for x, label in zip(cols, headers):
        anchor = "ra" if x == 1008 else None
        draw.text((x, 415), label, fill="#555555", font=font(25, True), anchor=anchor)
    draw.line((72, 470, 1008, 470), fill="#BBBBBB", width=2)

    rows = [
        ("1LDK", "54–56㎡", "5,898日元", "暂无样本"),
        ("1LDK", "60–62㎡", "暂无样本", "277万日元"),
    ]
    for i, row in enumerate(rows):
        y = 560 + i * 260
        draw.text((72, y), row[0], fill="#111111", font=font(43, True))
        draw.text((390, y + 4), row[1], fill="#111111", font=font(31))
        draw.text((675, y), row[2], fill="#111111" if "暂无" not in row[2] else "#999999", font=font(31, True), anchor="ma")
        draw.text((1008, y), row[3], fill="#111111" if "暂无" not in row[3] else "#999999", font=font(31, True), anchor="ra")
        if i == 0:
            draw.text((675, y + 58), "每㎡/月", fill="#666666", font=font(22), anchor="ma")
        else:
            draw.text((1008, y + 58), "每㎡", fill="#666666", font=font(22), anchor="ra")
        draw.line((72, y + 145, 1008, y + 145), fill="#DDDDDD", width=2)

    draw.text((72, 1160), "租赁：挂牌单价", fill="#111111", font=font(28))
    draw.text((72, 1220), "买卖：成交单价", fill="#111111", font=font(28))
    image.save(OUT / "02-rent-sale-comparison-clean.png", quality=95)


def unit_history_card():
    image, draw = base()
    draw.text((72, 205), "每平方米单价记录", fill="#111111", font=font(60, True))
    draw.text((72, 292), "2023—2025", fill="#666666", font=font(27))
    draw.line((72, 360, 1008, 360), fill="#111111", width=2)

    draw.text((72, 420), "1LDK · 54–56㎡ · 挂牌租金", fill="#111111", font=font(32, True))
    rental = [("2023.05", "5,258"), ("2024.06", "5,536"), ("2025.08", "5,898")]
    sale = [("2023.09", "241万"), ("2024.10", "262万"), ("2025.11", "277万")]
    for i, (month, value) in enumerate(rental):
        y = 500 + i * 95
        draw.text((90, y), month, fill="#666666", font=font(27))
        draw.text((1000, y), f"{value} 日元/㎡/月", fill="#111111", font=font(30, True), anchor="ra")
    draw.line((72, 805, 1008, 805), fill="#CCCCCC", width=2)
    draw.text((72, 865), "1LDK · 60–62㎡ · 买房子", fill="#111111", font=font(32, True))
    for i, (month, value) in enumerate(sale):
        y = 945 + i * 95
        draw.text((90, y), month, fill="#666666", font=font(27))
        draw.text((1000, y), f"{value} 日元/㎡", fill="#111111", font=font(30, True), anchor="ra")
    image.save(OUT / "03-unit-price-history-clean.png", quality=95)


def multi_layout_chart(filename, title, subtitle, months, series):
    image, draw = base()
    draw.text((72, 205), title, fill="#111111", font=font(62, True))
    draw.text((72, 292), subtitle, fill="#666666", font=font(27))
    draw.line((72, 360, 1008, 360), fill="#111111", width=2)

    left, right, top, bottom = 150, 900, 500, 1080
    xs = [left, (left + right) // 2, right]
    all_values = [v for _, values, _ in series for v in values]
    low, high = min(all_values) * 0.92, max(all_values) * 1.08

    for y in (top, (top + bottom) // 2, bottom):
        draw.line((left, y, right, y), fill="#DDDDDD", width=2)
    for x, month in zip(xs, months):
        box = draw.textbbox((0, 0), month, font=font(25))
        draw.text((x - (box[2] - box[0]) / 2, 1125), month, fill="#555555", font=font(25))

    styles = [("#111111", 10), ("#666666", 8), ("#AAAAAA", 7)]
    for (label, values, suffix), (color, width) in zip(series, styles):
        ys = [bottom - int((value - low) / (high - low) * (bottom - top)) for value in values]
        draw.line(list(zip(xs, ys)), fill=color, width=width, joint="curve")
        for x, y in zip(xs, ys):
            draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill="white", outline=color, width=5)
        draw.text((930, ys[-1] - 18), label, fill=color, font=font(26, True))

    legend_y = 1240
    for i, (label, values, suffix) in enumerate(series):
        color, width = styles[i]
        y = legend_y + i * 55
        draw.line((72, y + 15, 125, y + 15), fill=color, width=width)
        draw.text((145, y), f"{label}  {values[-1]:g}{suffix}", fill="#111111", font=font(25))
    image.save(OUT / filename, quality=95)


def flow_wave_card(filename, title, subtitle, rows, note):
    image, draw = base()
    draw.text((72, 205), title, fill="#111111", font=font(62, True))
    draw.text((72, 292), subtitle, fill="#666666", font=font(27))
    draw.line((72, 360, 1008, 360), fill="#111111", width=2)

    node_xs = [210, 540, 870]
    wave_mid = 555
    wave = []
    for i in range(len(node_xs) - 1):
        x0 = node_xs[i] + 58
        x1 = node_xs[i + 1] - 58
        wave.extend(
            curve_points(
                [
                    (x0, wave_mid),
                    (x0 + 72, wave_mid - 80),
                    (x1 - 72, wave_mid + 80),
                    (x1, wave_mid),
                ],
                34,
            )
        )
    draw.line(wave, fill="#111111", width=7, joint="curve")

    for i, row in enumerate(rows):
        x = node_xs[i]
        draw.ellipse((x - 58, wave_mid - 58, x + 58, wave_mid + 58), fill="white", outline="#111111", width=6)
        label_box = draw.textbbox((0, 0), row["label"], font=font(28, True))
        draw.text((x - (label_box[2] - label_box[0]) / 2, wave_mid - 19), row["label"], fill="#111111", font=font(28, True))

        card_left = 86 + i * 318
        card_right = card_left + 262
        card_top, card_bottom = 760, 1060
        draw.rounded_rectangle((card_left, card_top, card_right, card_bottom), radius=22, outline="#111111", width=4)
        draw.text((card_left + 26, card_top + 32), row["label"], fill="#111111", font=font(38, True))
        draw.text((card_left + 26, card_top + 96), row["area"], fill="#666666", font=font(25))
        draw.line((card_left + 26, card_top + 145, card_right - 26, card_top + 145), fill="#DDDDDD", width=2)
        draw.text((card_left + 26, card_top + 174), row["detail_jpy"], fill="#111111", font=font(28, True))
        draw.text((card_left + 26, card_top + 218), row["detail_cny"], fill="#111111", font=font(24, True))
        draw.text((card_left + 26, card_top + 258), row["unit_jpy"], fill="#666666", font=font(18))
        draw.text((card_left + 26, card_top + 286), row["unit_cny"], fill="#666666", font=font(18))

    draw.text((72, 1196), "1LDK  →  2LDK  →  3LDK", fill="#111111", font=font(36, True))
    draw.text((72, 1268), note, fill="#666666", font=font(24))
    image.save(OUT / filename, quality=95)


OUT.mkdir(parents=True, exist_ok=True)
cover()
flow_wave_card(
    "02-rental-all-layouts-clean.png",
    "租房子",
    "港区公开相场快照 · 2026年8月",
    [
        {
            "label": "1LDK",
            "area": "约40–45㎡",
            "detail_jpy": "27.9万日元/月",
            "detail_cny": "≈1.18万RMB/月",
            "unit_jpy": "约6,083日元/㎡/月",
            "unit_cny": "≈257RMB/㎡/月",
        },
        {
            "label": "2LDK",
            "area": "约65–75㎡",
            "detail_jpy": "47.2万日元/月",
            "detail_cny": "≈1.99万RMB/月",
            "unit_jpy": "约7,520日元/㎡/月",
            "unit_cny": "≈318RMB/㎡/月",
        },
        {
            "label": "3LDK",
            "area": "约95–105㎡",
            "detail_jpy": "90.6万日元/月",
            "detail_cny": "≈3.83万RMB/月",
            "unit_jpy": "约8,135日元/㎡/月",
            "unit_cny": "≈344RMB/㎡/月",
        },
    ],
    "汇率约算：100日元≈4.23RMB。钱包自动进入省电模式。",
)
flow_wave_card(
    "03-sale-all-layouts-clean.png",
    "买房子",
    "中古マンション成交均价 · 2026年1-3月",
    [
        {
            "label": "1LDK",
            "area": "约40–45㎡",
            "detail_jpy": "约1.00亿日元",
            "detail_cny": "≈423万RMB",
            "unit_jpy": "约238万日元/㎡",
            "unit_cny": "≈10.1万RMB/㎡",
        },
        {
            "label": "2LDK",
            "area": "约65–75㎡",
            "detail_jpy": "约2.16亿日元",
            "detail_cny": "≈913万RMB",
            "unit_jpy": "约238万日元/㎡",
            "unit_cny": "≈10.1万RMB/㎡",
        },
        {
            "label": "3LDK",
            "area": "约95–105㎡",
            "detail_jpy": "约3.33亿日元",
            "detail_cny": "≈1,407万RMB",
            "unit_jpy": "约238万日元/㎡",
            "unit_cny": "≈10.1万RMB/㎡",
        },
    ],
    "汇率约算：100日元≈4.23RMB。买完钱包开始修禅。",
)
