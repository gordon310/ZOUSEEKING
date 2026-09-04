#!/usr/bin/env python3
"""Create a reviewable PDF sample for the ZOUBEACON property report.

The report is deliberately synthetic. It mirrors the 11-section completed
report shown in web/project.html and must not be used as a market conclusion.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfgen import canvas as canvas_module


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "zoubeacon-property-analysis-sample-v2.pdf"
LOGO = ROOT / "web" / "assets" / "logoELE.png"

PAGE_W, PAGE_H = A4
NAVY = colors.HexColor("#10284d")
NAVY_SOFT = colors.HexColor("#60718a")
MUTED = colors.HexColor("#71809a")
INK_SOFT = colors.HexColor("#31425f")
LINE = colors.HexColor("#d8e0ec")
LINE_STRONG = colors.HexColor("#b5c2d5")
SURFACE = colors.HexColor("#f4f7fb")
SURFACE_WARM = colors.HexColor("#fff8f3")
ORANGE = colors.HexColor("#ff5a0a")
ORANGE_DARK = colors.HexColor("#e84e05")
GREEN = colors.HexColor("#22ad83")
YELLOW = colors.HexColor("#e09b25")
RED = colors.HexColor("#c4372e")
WHITE = colors.white


def register_cjk_font() -> str:
    """Register a macOS CJK font, keeping a readable fallback for CI."""

    candidates = [
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("ReportCN", str(candidate), subfontIndex=0))
            pdfmetrics.registerFontFamily(
                "ReportCN", normal="ReportCN", bold="ReportCN", italic="ReportCN", boldItalic="ReportCN"
            )
            return "ReportCN"
        except Exception:
            continue
    return "Helvetica"


FONT = register_cjk_font()


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle(
            "cover_kicker",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=9,
            leading=12,
            textColor=ORANGE_DARK,
            tracking=1.5,
            spaceAfter=9,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontName=FONT,
            fontSize=27,
            leading=34,
            textColor=NAVY,
            spaceAfter=8,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=12,
            leading=18,
            textColor=NAVY_SOFT,
            spaceAfter=18,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=15,
            textColor=INK_SOFT,
        ),
        "cover_note": ParagraphStyle(
            "cover_note",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=9,
            leading=14,
            textColor=NAVY_SOFT,
        ),
        "header_brand": ParagraphStyle(
            "header_brand",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8.5,
            leading=11,
            textColor=NAVY,
        ),
        "eyebrow": ParagraphStyle(
            "eyebrow",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8,
            leading=10,
            textColor=MUTED,
            spaceAfter=4,
        ),
        "section_title": ParagraphStyle(
            "section_title",
            parent=base["Heading2"],
            fontName=FONT,
            fontSize=18,
            leading=23,
            textColor=NAVY,
            spaceAfter=6,
        ),
        "section_intro": ParagraphStyle(
            "section_intro",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=9.2,
            leading=15,
            textColor=NAVY_SOFT,
            spaceAfter=12,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9.2,
            leading=15,
            textColor=INK_SOFT,
            spaceAfter=6,
            wordWrap="CJK",
        ),
        "body_small": ParagraphStyle(
            "body_small",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8,
            leading=12,
            textColor=NAVY_SOFT,
            wordWrap="CJK",
        ),
        "body_white": ParagraphStyle(
            "body_white",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9,
            leading=14,
            textColor=WHITE,
            wordWrap="CJK",
        ),
        "card_title": ParagraphStyle(
            "card_title",
            parent=base["Heading3"],
            fontName=FONT,
            fontSize=10,
            leading=14,
            textColor=NAVY,
            spaceAfter=4,
        ),
        "card_title_white": ParagraphStyle(
            "card_title_white",
            parent=base["Heading3"],
            fontName=FONT,
            fontSize=10,
            leading=14,
            textColor=WHITE,
            spaceAfter=4,
        ),
        "card_body": ParagraphStyle(
            "card_body",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.5,
            leading=13,
            textColor=INK_SOFT,
            wordWrap="CJK",
        ),
        "label": ParagraphStyle(
            "label",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8,
            leading=11,
            textColor=MUTED,
        ),
        "value": ParagraphStyle(
            "value",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=9,
            leading=13,
            textColor=NAVY,
            wordWrap="CJK",
        ),
        "value_strong": ParagraphStyle(
            "value_strong",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=11,
            leading=15,
            textColor=NAVY,
            wordWrap="CJK",
        ),
        "table_head": ParagraphStyle(
            "table_head",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8,
            leading=11,
            textColor=WHITE,
        ),
        "table_cell": ParagraphStyle(
            "table_cell",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8.3,
            leading=12,
            textColor=INK_SOFT,
            wordWrap="CJK",
        ),
        "table_cell_strong": ParagraphStyle(
            "table_cell_strong",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8.3,
            leading=12,
            textColor=NAVY,
            wordWrap="CJK",
        ),
        "badge": ParagraphStyle(
            "badge",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8,
            leading=11,
            textColor=ORANGE_DARK,
            alignment=TA_CENTER,
        ),
        "toc_num": ParagraphStyle(
            "toc_num",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=13,
            textColor=ORANGE,
            alignment=TA_CENTER,
        ),
        "toc_title": ParagraphStyle(
            "toc_title",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=14,
            textColor=NAVY,
        ),
        "toc_desc": ParagraphStyle(
            "toc_desc",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8,
            leading=12,
            textColor=NAVY_SOFT,
        ),
        "footer": ParagraphStyle(
            "footer",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
        ),
    }


STYLES = build_styles()


def para(text: str, style: str = "body") -> Paragraph:
    safe = escape(str(text)).replace("\n", "<br/>")
    return Paragraph(safe, STYLES[style])


def rich(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, STYLES[style])


def tag(text: str, background: colors.Color = SURFACE_WARM, foreground: colors.Color = ORANGE_DARK) -> Table:
    style = ParagraphStyle(
        "tag_runtime",
        parent=STYLES["badge"],
        textColor=foreground,
    )
    table = Table([[Paragraph(escape(text), style)]], colWidths=[92], rowHeights=[20])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.6, foreground),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def section_header(number: str, english: str, title: str, intro: str | None = None) -> list:
    flow = [
        para(f"{number} · {english}", "eyebrow"),
        para(title, "section_title"),
    ]
    if intro:
        flow.append(para(intro, "section_intro"))
    return flow


def line() -> Table:
    table = Table([[""]], colWidths=[PAGE_W - 84], rowHeights=[1])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LINE)]))
    return table


def detail_table(rows: list[tuple[str, str]], widths: tuple[float, float] = (112, 360)) -> Table:
    data = [[para(label, "label"), para(value, "value")] for label, value in rows]
    table = Table(data, colWidths=list(widths), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.45, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def panel(content: list, background: colors.Color = SURFACE, border: colors.Color = LINE, width: float = 472) -> Table:
    table = Table([[content]], colWidths=[width], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.7, border),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 15),
                ("RIGHTPADDING", (0, 0), (-1, -1), 15),
                ("TOPPADDING", (0, 0), (-1, -1), 13),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
            ]
        )
    )
    return table


def two_cards(left: list, right: list, left_bg: colors.Color = WHITE, right_bg: colors.Color = WHITE) -> Table:
    table = Table([[left, right]], colWidths=[230, 230], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), left_bg),
                ("BACKGROUND", (1, 0), (1, 0), right_bg),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 13),
                ("RIGHTPADDING", (0, 0), (-1, -1), 13),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return table


def conclusion_card(mark: str, title: str, body: str, bg: colors.Color = WHITE) -> list:
    return [
        rich(f'<font color="#ff5a0a"><b>{escape(mark)}</b></font>', "card_title"),
        para(title, "card_title"),
        para(body, "card_body"),
    ]


def status_table(headers: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    data = [[para(item, "table_head") for item in headers]]
    for row in rows:
        data.append([para(item, "table_cell_strong" if index == 0 else "table_cell") for index, item in enumerate(row)])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]
    for row_index in range(1, len(data)):
        style.append(("BACKGROUND", (0, row_index), (-1, row_index), WHITE if row_index % 2 else SURFACE))
    table.setStyle(TableStyle(style))
    return table


def checklist(items: list[tuple[str, str]], width: float = 472) -> Table:
    rows = []
    for label, status in items:
        rows.append([para("?", "toc_num"), para(label, "table_cell"), para(status, "table_cell_strong")])
    table = Table(rows, colWidths=[28, width - 135, 107], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def draw_brand(canvas: canvas_module.Canvas, x: float, y: float, compact: bool = False) -> None:
    canvas.saveState()
    if LOGO.exists():
        try:
            canvas.drawImage(str(LOGO), x, y - (15 if compact else 20), width=(18 if compact else 28), height=(18 if compact else 28), mask="auto", preserveAspectRatio=True)
        except Exception:
            pass
    canvas.setFillColor(NAVY)
    canvas.setFont(FONT, 9 if compact else 12)
    canvas.drawString(x + (24 if compact else 36), y, "小象避坑")
    canvas.setFillColor(NAVY_SOFT)
    canvas.setFont(FONT, 6.5 if compact else 7.5)
    canvas.drawString(x + (24 if compact else 36), y - (9 if compact else 12), "ZOUBEACON")
    canvas.restoreState()


def first_page(canvas: canvas_module.Canvas, doc: BaseDocTemplate) -> None:
    canvas.saveState()
    canvas.setFillColor(SURFACE)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(ORANGE)
    canvas.rect(0, PAGE_H - 7 * mm, PAGE_W, 7 * mm, fill=1, stroke=0)
    draw_brand(canvas, 46, PAGE_H - 35, compact=False)
    canvas.setFillColor(ORANGE_DARK)
    canvas.setFont(FONT, 8)
    canvas.drawRightString(PAGE_W - 46, PAGE_H - 30, "REPORT SAMPLE / V2")
    canvas.setFillColor(MUTED)
    canvas.setFont(FONT, 7.5)
    canvas.drawString(46, 26, "样稿仅供界面与报告结构确认 · 所有数字均为 synthetic_fixture")
    canvas.drawRightString(PAGE_W - 46, 26, "1")
    canvas.restoreState()


def later_pages(canvas: canvas_module.Canvas, doc: BaseDocTemplate) -> None:
    canvas.saveState()
    draw_brand(canvas, 46, PAGE_H - 34, compact=True)
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.6)
    canvas.line(46, PAGE_H - 51, PAGE_W - 46, PAGE_H - 51)
    canvas.setFillColor(MUTED)
    canvas.setFont(FONT, 7.5)
    canvas.drawString(46, 25, "小象避坑 ZOUBEACON · 标准风险筛查报告样稿")
    canvas.drawRightString(PAGE_W - 46, 25, str(canvas.getPageNumber()))
    canvas.restoreState()


def draw_page(canvas: canvas_module.Canvas, doc: BaseDocTemplate) -> None:
    if canvas.getPageNumber() == 1:
        first_page(canvas, doc)
    else:
        later_pages(canvas, doc)


class ReportDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        self.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=draw_page)])


def make_story() -> list:
    story: list = []

    # Cover
    story.extend(
        [
            Spacer(1, 92),
            para("PROPERTY ANALYSIS REPORT", "cover_kicker"),
            para("物件分析报告", "cover_title"),
            para("标准风险筛查样稿 · 收费完整版 V2", "cover_subtitle"),
            tag("界面确认版 · synthetic_fixture"),
            Spacer(1, 24),
        ]
    )
    cover_details = [
        [para("分析物件", "label"), para("大阪市北区 · 塔楼演示项目", "value_strong")],
        [para("物件类型", "label"), para("二手公寓 / 塔楼", "value")],
        [para("分析用途", "label"), para("自住购买", "value")],
        [para("报告版本", "label"), para("V2 · 输入版本 I1", "value")],
        [para("数据快照", "label"), para("2026-08-27 · 仅合成演示数据", "value")],
    ]
    cover_table = Table(cover_details, colWidths=[90, 350], hAlign="LEFT")
    cover_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                ("BOX", (0, 0), (-1, -1), 0.8, LINE),
                ("LINEBELOW", (0, 0), (-1, -1), 0.45, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 13),
                ("RIGHTPADDING", (0, 0), (-1, -1), 13),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(cover_table)
    story.append(Spacer(1, 28))
    story.append(
        panel(
            [
                rich('<font color="#ff5a0a"><b>当前建议：谨慎推进</b></font>', "card_title"),
                para("在补齐长期修缮计划、管理费用和登记资料前，不建议把本项目推进到签约判断。", "body"),
                para("本页是样稿中的演示结论，不替代宅地建物取引士、律师、税务师或金融机构意见。", "cover_note"),
            ],
            background=SURFACE_WARM,
            border=ORANGE,
        )
    )
    story.append(PageBreak())

    # Contents and reading guide
    story.extend(section_header("REPORT MAP", "READING GUIDE", "报告结构", "这份样稿沿用当前网页完整报告的 11 个章节，用于先确认输出物的阅读节奏、信息密度和结论边界。"))
    toc_rows = [
        ("01", "项目结论摘要", "先给出行动结论、证据缺口和不能判断的事项。"),
        ("02", "项目基本信息", "记录物件身份、用途、价格和面积等输入资料。"),
        ("03", "数据来源与可信度", "区分用户提交、市场样本、法规资料和数据类别。"),
        ("04", "市场价格比较", "样本不足时不输出价格区间，挂牌价与成交价分开。"),
        ("05", "购入成本与持有成本", "只列待确认项目，不把未验证金额估成事实。"),
        ("06", "自住专项分析", "按通勤、现场条件、灾害和转售等维度提示缺口。"),
        ("07", "投资收益分析", "资料不足时不生成收益率、现金流或保本租金。"),
        ("08", "法律与重要事项", "列出登记、管理规约、用途和灾害资料检查项。"),
        ("09", "深度避坑分析", "把资料不足、待检查和可能风险分别呈现。"),
        ("10", "资料缺口与下一步行动", "给出可执行的补资料顺序，不直接代替专业判断。"),
        ("11", "方法、版本信息和免责声明", "固定数据类别、计算规则、口径和结论边界。"),
    ]
    toc_data = []
    for number, title, desc in toc_rows:
        toc_data.append([para(number, "toc_num"), [para(title, "toc_title"), para(desc, "toc_desc")]])
    toc = Table(toc_data, colWidths=[42, 430], hAlign="LEFT")
    toc.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(toc)
    story.append(Spacer(1, 17))
    story.append(
        panel(
            [
                para("本样稿的阅读提示", "card_title"),
                para("所有价格、面积、日期、状态和结论均为 synthetic_fixture。正式报告必须绑定来源 URL、取得时间、来源期间、数据类别、样本量、聚合方法、限制和规则版本。", "body"),
                para("如果资料不足，报告会明确保留“资料不足 / 待检查 / 样本不足”，不会把模型估算写成收集到的市场事实。", "body"),
            ],
            background=SURFACE,
        )
    )
    story.append(PageBreak())

    # 01 decision brief
    story.extend(section_header("01", "DECISION BRIEF", "项目结论摘要", "把最重要的判断放在报告前面，同时把证据不足的地方直接标出来。"))
    story.append(
        panel(
            [
                rich('<font color="#ff5a0a"><b>行动结论 · 谨慎推进</b></font>', "card_title"),
                para("在补齐长期修缮计划、管理费用和登记资料前，不建议把本物件推进到签约判断。", "body"),
                para("当前结论只基于演示输入；正式版需要把每个判断连接到已验证证据。", "body_small"),
            ],
            background=SURFACE_WARM,
            border=ORANGE,
        )
    )
    story.append(Spacer(1, 14))
    story.append(
        two_cards(
            conclusion_card("!", "价格暂时不能独立判断", "可比样本不足，不能用单个挂牌价推断合理成交区间。"),
            conclusion_card("×", "资料不足不是没有风险", "产权、合同、建筑合规和灾害资料未完成核对，结论置信度受限。", SURFACE_WARM),
            WHITE,
            SURFACE_WARM,
        )
    )
    story.append(Spacer(1, 14))
    story.append(
        panel(
            [
                para("当前最关键的三个问题", "card_title"),
                checklist(
                    [
                        ("长期修缮计划与修缮记录是否完整？", "资料不足"),
                        ("管理费、修缮积立金和特别征收是多少？", "待确认"),
                        ("登记簿、重要事项说明书和合同草案是否一致？", "待补充"),
                    ],
                    width=442,
                ),
            ],
            background=WHITE,
        )
    )
    story.append(PageBreak())

    # 02 / 03 facts and provenance
    story.extend(section_header("02 - 03", "PROPERTY FACTS / PROVENANCE", "物件信息与数据可信度", "先固定输入和来源状态，再决定哪些分析可以继续。"))
    story.append(para("02 · 项目基本信息", "eyebrow"))
    story.append(
        detail_table(
            [
                ("分析用途", "自住购买"),
                ("所在地", "大阪市北区"),
                ("售价", "35,000,000 JPY"),
                ("专有面积", "45.2㎡"),
                ("物件类型", "二手公寓 / 塔楼"),
                ("资料更新时间", "2026-08-27"),
            ]
        )
    )
    story.append(Spacer(1, 18))
    story.append(para("03 · 数据来源与可信度", "eyebrow"))
    story.append(
        detail_table(
            [
                ("用户提交资料", "待人工确认"),
                ("市场可比数据", "样本不足"),
                ("法规资料", "未加载"),
                ("数据类别", "synthetic_fixture"),
                ("来源授权", "本样稿不连接真实来源"),
                ("快照时间", "2026-08-27"),
            ]
        )
    )
    story.append(Spacer(1, 17))
    story.append(
        panel(
            [
                para("正式报告需要显示的 provenance", "card_title"),
                para("来源 URL、取得 / 核验时间、来源期间、数据类别、使用权状态、转换版本、样本量、聚合方法、缺失值政策和限制。", "body"),
            ],
            background=SURFACE,
        )
    )
    story.append(PageBreak())

    # 04 market
    story.extend(section_header("04", "MARKET COMPARISON", "市场价格比较", "比较必须保持地区、物件类型、面积、期间、交易状态和数据类别一致。"))
    story.append(
        panel(
            [
                rich('<font color="#e09b25"><b>可比样本不足</b></font>', "card_title"),
                para("当前不输出价格区间，也不把挂牌价与成交价混在一起。正式报告会在样本满足口径后，再显示中位数、分布区间和样本量。", "body"),
            ],
            background=SURFACE_WARM,
            border=YELLOW,
        )
    )
    story.append(Spacer(1, 15))
    story.append(
        status_table(
            ["比较维度", "当前状态", "正式报告要求"],
            [
                ["地区", "大阪市北区", "与目标物件相同"],
                ["物件类型", "二手公寓 / 塔楼", "定义保持一致"],
                ["面积段", "45.2㎡", "相近面积段"],
                ["交易状态", "未加载", "挂牌价、成交价分开"],
                ["期间", "未加载", "多个可比期间"],
                ["数据类别", "synthetic_fixture", "不得混用"],
            ],
            [122, 126, 224],
        )
    )
    story.append(Spacer(1, 17))
    story.append(
        panel(
            [
                para("比较口径", "card_title"),
                para("不会因为同一月份有记录，就把不同地区或不同交易状态的记录简单平均。趋势视图也需要多个可比期间，而不是单月变化。", "body"),
            ],
            background=WHITE,
        )
    )
    story.append(PageBreak())

    # 05 cost
    story.extend(section_header("05", "COST MODEL", "购入成本与持有成本", "演示报告只列出状态；未验证金额不会被估算。"))
    story.append(
        status_table(
            ["项目", "状态", "说明"],
            [
                ["中介手续费", "待资料", "需要合同或费用说明"],
                ["管理费与修缮积立金", "资料不足", "需要管理资料与长期修缮计划"],
                ["不动产取得税", "待规则", "需要评估额与适用条件"],
                ["登记与司法书士费用", "资料不足", "需要交易资料和登记信息"],
                ["特别征收 / 临时修缮", "未确认", "需要管理组合会资料"],
            ],
            [154, 92, 226],
        )
    )
    story.append(Spacer(1, 20))
    story.append(
        two_cards(
            [para("不输出的内容", "card_title"), para("未验证的总取得成本、月度持有成本和现金流。", "card_body")],
            [para("需要补齐", "card_title"), para("费用说明、管理规约、长期修缮计划、评估额和交易资料。", "card_body")],
            SURFACE,
            SURFACE_WARM,
        )
    )
    story.append(Spacer(1, 15))
    story.append(para("金额字段在正式数据结构中应保存为数值和单位，报告只负责展示，不从“约 3,500 万日元”这类展示字符串反向计算。", "body_small"))
    story.append(PageBreak())

    # 06 / 07 self use and investment
    story.extend(section_header("06 - 07", "SELF USE / INVESTMENT", "自住与投资视角", "同一个物件在自住和投资场景下的判断维度不同，报告不把两种用途混成一个分数。"))
    story.append(para("06 · 自住专项分析", "eyebrow"))
    story.append(
        checklist(
            [
                ("通勤与生活便利", "待确认"),
                ("采光与噪音", "待现场"),
                ("灾害与转售难度", "资料不足"),
                ("楼层、朝向与实际动线", "待现场"),
            ]
        )
    )
    story.append(Spacer(1, 18))
    story.append(para("07 · 投资收益分析", "eyebrow"))
    story.append(
        status_table(
            ["情景", "结果", "当前限制"],
            [
                ["保守", "待租金", "空置与费用未确认"],
                ["基准", "待租金", "需要可比租金样本"],
                ["乐观", "待租金", "不提前假设增长"],
            ],
            [116, 100, 256],
        )
    )
    story.append(Spacer(1, 15))
    story.append(
        panel(
            [
                para("当前不生成", "card_title"),
                para("毛收益率、净收益率、现金流、保本租金或收益保证。正式计算必须明确租金来源、空置政策、持有成本、融资假设和模型版本。", "body"),
            ],
            background=SURFACE_WARM,
            border=LINE,
        )
    )
    story.append(PageBreak())

    # 08 / 09 legal and risk
    story.extend(section_header("08 - 09", "LEGAL CHECK / RISK REVIEW", "法律与深度避坑分析", "把“待检查”和“资料不足”分开，避免用户把没有核验误读成没有问题。"))
    story.append(para("08 · 法律与重要事项", "eyebrow"))
    story.append(
        checklist(
            [
                ("所有权与登记簿", "资料不足"),
                ("管理规约与修缮计划", "资料不足"),
                ("用途、接道与再建", "待检查"),
                ("灾害地图与避难条件", "待检查"),
                ("重要事项说明书与合同草案", "待补充"),
            ]
        )
    )
    story.append(Spacer(1, 18))
    story.append(para("09 · 深度避坑分析", "eyebrow"))
    risk_rows = [
        ["资料不足", "管理与修缮负担", "长期修缮计划、积立金和特别征收未核对，不能判断未来持有压力。"],
        ["资料不足", "交易与产权核查", "登记簿、重要事项说明书和合同草案未提供，不能确认关键权利义务。"],
        ["待检查", "市场价格偏离", "可比样本不足，当前不把售价与市场合理区间直接比较。"],
    ]
    story.append(status_table(["等级", "风险主题", "当前判断"], risk_rows, [92, 135, 245]))
    story.append(Spacer(1, 15))
    story.append(para("风险等级不是法律结论，也不是投资建议。它只表示当前资料状态与需要优先补齐的证据。", "body_small"))
    story.append(PageBreak())

    # 10 / 11 action and method
    story.extend(section_header("10 - 11", "NEXT ACTION / METHOD & LIMITS", "下一步行动与报告边界", "最后一页让用户知道下一步应该补什么，也知道这份报告不能替他承担什么。"))
    story.append(para("10 · 资料缺口与下一步行动", "eyebrow"))
    story.append(
        panel(
            [
                para("建议补资料顺序", "card_title"),
                para("1. 向中介索取长期修缮计划与修缮记录。", "body"),
                para("2. 确认管理费、修缮积立金和特别征收。", "body"),
                para("3. 补充登记簿、重要事项说明书和合同草案。", "body"),
                para("4. 如需继续，再补充现场采光、噪音、通勤和灾害条件。", "body"),
            ],
            background=SURFACE,
        )
    )
    story.append(Spacer(1, 18))
    story.append(para("11 · 方法、版本信息和免责声明", "eyebrow"))
    story.append(
        detail_table(
            [
                ("数据类别", "synthetic_fixture"),
                ("计算规则", "free-preview-v1 · 演示"),
                ("市场口径", "未生成估算"),
                ("报告版本", "V2 · 输入版本 I1"),
                ("数据快照", "2026-08-27"),
            ]
        )
    )
    story.append(Spacer(1, 14))
    story.append(
        panel(
            [
                para("结论边界", "card_title"),
                para("缺少证据时保持“资料不足”，不把模型估算或示例数据当作收集到的市场事实。", "body"),
                para("本报告不替代宅地建物取引士、律师、税务师或金融机构意见，也不构成签约、贷款或收益承诺。", "body"),
                para("正式交付版本还应显示来源 URL、取得时间、来源期间、使用权状态、样本量、聚合方法、缺失值政策、模型版本和限制。", "body"),
            ],
            background=SURFACE_WARM,
            border=ORANGE,
        )
    )
    story.append(Spacer(1, 21))
    story.append(line())
    story.append(Spacer(1, 9))
    story.append(para("样稿制作目的：确认 PDF 的报告结构、信息密度、结论位置、状态表达和品牌视觉。真实数据、会员权益、支付、报告生成和人工服务均未在本文件中执行。", "body_small"))
    return story


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = ReportDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=72,
        bottomMargin=43,
        title="小象避坑物件分析报告样稿",
        author="ZOUBEACON",
        subject="synthetic_fixture PDF report sample",
    )
    doc.build(make_story())
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
