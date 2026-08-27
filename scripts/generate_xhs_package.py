import argparse
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


W, H = 1080, 1440
ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "logoELE.png"
FONT_REGULAR = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/Hiragino Sans GB.ttc"


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
    return image, ImageDraw.Draw(image)


def cleaned_logo(max_w=360, max_h=260):
    logo = Image.open(LOGO).convert("RGBA")
    black_pixels = []
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, a = logo.getpixel((x, y))
            if a and r < 80 and g < 80 and b < 80:
                black_pixels.append((x, y))
    if black_pixels:
        xs = [p[0] for p in black_pixels]
        ys = [p[1] for p in black_pixels]
        padding = 70
        logo = logo.crop(
            (
                max(min(xs) - padding, 0),
                max(min(ys) - padding, 0),
                min(max(xs) + padding, logo.width),
                min(max(ys) + padding, logo.height),
            )
        )
    scale = min(max_w / logo.width, max_h / logo.height)
    logo = logo.resize((round(logo.width * scale), round(logo.height * scale)))
    px = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if r < 80 and g < 80 and b < 80:
                px[x, y] = (0, 0, 0, a)
            else:
                px[x, y] = (255, 255, 255, 0)
    return logo


def draw_cover(config, image_dir):
    image, draw = base()
    logo = cleaned_logo()
    image.paste(logo, ((W - logo.width) // 2, 80), logo)

    cover = config["cover"]
    draw.text((72, 555), cover["line1"], fill="#111111", font=font(92, True))
    draw.text((72, 675), cover["line2"], fill="#111111", font=font(72, True))
    draw.text((72, 785), cover["tagline"], fill="#111111", font=font(34))
    draw.text((72, 845), config["publish_month"], fill="#666666", font=font(32))
    draw.text((72, 905), cover["note"], fill="#111111", font=font(30))

    draw.line((72, 1240, 1008, 1240), fill="#111111", width=3)
    towers = [(110, 1080, 220), (255, 1010, 160), (450, 930, 210), (700, 1040, 145), (870, 970, 115)]
    for x, y, width in towers:
        draw.rectangle((x, y, x + width, 1240), outline="#111111", width=4)
        draw.line((x, y, x + width // 2, y - 35, x + width, y), fill="#111111", width=4, joint="curve")
        for window_y in range(y + 45, 1210, 55):
            draw.line((x + 28, window_y, x + width - 28, window_y), fill="#111111", width=2)

    image.save(image_dir / "01-cover-clean.png", quality=95)


def draw_flow_card(filename, title, subtitle, rows, note, image_dir):
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
                [(x0, wave_mid), (x0 + 72, wave_mid - 80), (x1 - 72, wave_mid + 80), (x1, wave_mid)],
                34,
            )
        )
    draw.line(wave, fill="#111111", width=7, joint="curve")

    for i, row in enumerate(rows):
        x = node_xs[i]
        draw.ellipse((x - 58, wave_mid - 58, x + 58, wave_mid + 58), fill="white", outline="#111111", width=6)
        label = row["layout"]
        label_box = draw.textbbox((0, 0), label, font=font(28, True))
        draw.text((x - (label_box[2] - label_box[0]) / 2, wave_mid - 19), label, fill="#111111", font=font(28, True))

        card_left = 86 + i * 318
        card_right = card_left + 262
        card_top, card_bottom = 760, 1060
        draw.rounded_rectangle((card_left, card_top, card_right, card_bottom), radius=22, outline="#111111", width=4)
        draw.text((card_left + 26, card_top + 32), row["layout"], fill="#111111", font=font(38, True))
        draw.text((card_left + 26, card_top + 96), row["area"], fill="#666666", font=font(25))
        draw.line((card_left + 26, card_top + 145, card_right - 26, card_top + 145), fill="#DDDDDD", width=2)
        draw.text((card_left + 26, card_top + 174), row["amount_jpy"], fill="#111111", font=font(28, True))
        draw.text((card_left + 26, card_top + 218), row["amount_rmb"], fill="#111111", font=font(24, True))
        draw.text((card_left + 26, card_top + 258), row["unit_jpy"], fill="#666666", font=font(18))
        draw.text((card_left + 26, card_top + 286), row["unit_rmb"], fill="#666666", font=font(18))

    draw.text((72, 1196), "1LDK  →  2LDK  →  3LDK", fill="#111111", font=font(36, True))
    draw.text((72, 1268), note, fill="#666666", font=font(24))
    image.save(image_dir / filename, quality=95)


def render_markdown(config):
    def row_line(row):
        amount = row["amount_jpy"]
        if row.get("amount_rmb"):
            amount = f"{amount}≈{row['amount_rmb'].lstrip('≈')}"
        unit = row["unit_jpy"]
        if row.get("unit_rmb"):
            unit = f"{unit}≈{row['unit_rmb'].lstrip('≈')}"
        return f"{row['layout']}｜{row['area']}｜{amount}｜{unit}"

    lines = [
        f"# {config['title']}｜{config['publish_month']}",
        "",
    ]
    if config.get("intro"):
        lines.extend(["## 区域说明", *config["intro"], ""])
    if config.get("explain"):
        lines.extend(["## 基础说明", *config["explain"], ""])
    if config.get("exchange_rate_note"):
        lines.extend(["## 汇率", config["exchange_rate_note"], ""])

    rental = config["sections"]["rental"]
    lines.append(f"## {rental['title']}")
    for row in rental["rows"]:
        lines.append(row_line(row))

    sale = config["sections"]["sale"]
    lines.extend(["", f"## {sale['title']}"])
    for row in sale["rows"]:
        lines.append(row_line(row))

    summary = config["summary"]
    lines.extend(["", f"## {summary['title']}", summary["line"], summary["note"]])
    return "\n".join(lines) + "\n"


def library_record(config, markdown):
    rental_rows = config["sections"]["rental"]["rows"]
    sale_rows = config["sections"]["sale"]["rows"]
    layouts = sorted({row["layout"] for row in rental_rows + sale_rows})
    regions = []
    for word in ["东京港区", "港区", "中央区", "涩谷区", "新宿区", "大阪", "京都"]:
        haystack = config["title"] + " " + " ".join(config.get("intro", []))
        if word in haystack:
            regions.append(word)
    asset_type = "塔楼" if "塔楼" in config["title"] or "塔楼" in " ".join(config.get("explain", [])) else "房产"
    record = {
        "id": f"{config['slug']}::{config['publish_month']}",
        "slug": config["slug"],
        "template_name": config.get("template_name", "jphouse"),
        "title": config["title"],
        "publish_month": config["publish_month"],
        "generated_at": config.get("generated_at", ""),
        "regions": regions or [config["cover"]["line1"]],
        "asset_type": asset_type,
        "layouts": layouts,
        "status": config.get("status", "generated"),
        "summary": config["summary"],
        "rental": rental_rows,
        "sale": sale_rows,
        "markdown": markdown,
        "hashtags": config.get("hashtags", []),
        "data_sources": config.get("data_sources", []),
        "images": [
            f"library/{config['slug']}/images/01-cover-clean.png",
            f"library/{config['slug']}/images/02-rental-all-layouts-clean.png",
            f"library/{config['slug']}/images/03-sale-all-layouts-clean.png",
        ],
    }
    search_parts = [
        record["title"],
        record["template_name"],
        record["publish_month"],
        record["asset_type"],
        " ".join(record["regions"]),
        " ".join(record["layouts"]),
        markdown,
        " ".join(record.get("hashtags", [])),
    ]
    record["search_text"] = " ".join(search_parts).lower()
    return record


def upsert_library_record(path: Path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        records = json.loads(path.read_text(encoding="utf-8"))
    else:
        records = []
    records = [item for item in records if item.get("id") != record["id"]]
    records.insert(0, record)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def sync_web_library(output_dir: Path, config, records):
    web_dir = ROOT / "web"
    web_dir.mkdir(exist_ok=True)
    web_images = web_dir / "library" / config["slug"] / "images"
    web_images.mkdir(parents=True, exist_ok=True)
    for name in ["01-cover-clean.png", "02-rental-all-layouts-clean.png", "03-sale-all-layouts-clean.png"]:
        shutil.copy2(output_dir / "images" / name, web_images / name)
    (web_dir / "content-library.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def generate(config_path: Path, output_dir: Path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir = output_dir / "images"
    image_dir.mkdir(exist_ok=True)

    draw_cover(config, image_dir)
    rental = config["sections"]["rental"]
    draw_flow_card(
        "02-rental-all-layouts-clean.png",
        rental["title"],
        rental["subtitle"],
        rental["rows"],
        rental["note"],
        image_dir,
    )
    sale = config["sections"]["sale"]
    draw_flow_card(
        "03-sale-all-layouts-clean.png",
        sale["title"],
        sale["subtitle"],
        sale["rows"],
        sale["note"],
        image_dir,
    )

    markdown = render_markdown(config)
    (output_dir / "data_detail.md").write_text(markdown, encoding="utf-8")
    (output_dir / "source_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    record = library_record(config, markdown)
    records = upsert_library_record(ROOT / "data" / "content_library.json", record)
    sync_web_library(output_dir, config, records)


def main():
    parser = argparse.ArgumentParser(description="Generate a jphouse data package from a reusable JSON template.")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    generate(args.config, args.output_dir)


if __name__ == "__main__":
    main()
