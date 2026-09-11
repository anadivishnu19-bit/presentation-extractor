"""
Generates a stand-in finance-presentation PDF to develop/test the extraction
pipeline against, since no real sample file was provided. It deliberately
mimics how a PPT/Excel-exported PDF actually looks: a title, a data table
page, a bar-chart page with real overlaid text data labels (positioned to
match the bars pixel-for-pixel, not just captioned nearby), and a pie-chart
page with a real text legend -- i.e. numbers that live as PDF text objects,
not just pixels in a picture. This is exactly the scenario the parser's
"nearby text extraction" targets.
"""
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

OUT = Path(__file__).resolve().parent.parent / "samples" / "Sample_Finance_Presentation.pdf"
PAGE_W, PAGE_H = landscape(A4)  # 842 x 595 pt roughly


def make_bar_chart_png(categories, values, path, figsize=(6.4, 3.4), dpi=150):
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    bars = ax.bar(categories, values, color="#2563eb", width=0.55)
    ax.set_yticks([])
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.set_xticks(range(len(categories)))
    ax.set_xticklabels(categories, fontsize=11)
    ax.set_ylim(0, max(values) * 1.25)
    fig.tight_layout(pad=1.2)

    # compute label anchor points (figure-fraction coords) BEFORE saving
    label_fracs = []
    for bar, v in zip(bars, values):
        x_center = bar.get_x() + bar.get_width() / 2
        y_top = bar.get_height()
        disp = ax.transData.transform((x_center, y_top))
        frac = fig.transFigure.inverted().transform(disp)
        label_fracs.append((frac[0], frac[1]))

    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return label_fracs, figsize, dpi


def make_pie_chart_png(labels, values, path, figsize=(4.6, 3.4), dpi=150):
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    colors_list = ["#2563eb", "#60a5fa", "#93c5fd", "#1d4ed8", "#bfdbfe"]
    ax.pie(values, labels=None, colors=colors_list[: len(values)], startangle=90,
           wedgeprops={"linewidth": 1, "edgecolor": "white"})
    ax.axis("equal")
    fig.tight_layout(pad=0.5)
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def draw_wrapped_title(c, text, x, y, size=22):
    c.setFont("Helvetica-Bold", size)
    c.setFillColor(colors.HexColor("#0f172a"))
    c.drawString(x, y, text)


def draw_bullets(c, bullets, x, y, leading=18, size=11.5):
    c.setFont("Helvetica", size)
    c.setFillColor(colors.HexColor("#334155"))
    for b in bullets:
        c.drawString(x, y, f"•  {b}")
        y -= leading
    return y


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = OUT.parent / "_tmp_chart_imgs"
    tmp_dir.mkdir(exist_ok=True)

    c = canvas.Canvas(str(OUT), pagesize=(PAGE_W, PAGE_H))

    # ---- Page 1: Cover ----
    c.setFillColor(colors.HexColor("#0b1220"))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 34)
    c.drawString(70, PAGE_H - 220, "Sample Finance Corp Ltd")
    c.setFont("Helvetica", 18)
    c.setFillColor(colors.HexColor("#93c5fd"))
    c.drawString(70, PAGE_H - 260, "Q1 FY26 Investor Presentation (Synthetic Sample)")
    c.setFont("Helvetica", 11)
    c.setFillColor(colors.HexColor("#64748b"))
    c.drawString(70, 70, "This document contains fabricated placeholder data generated for software testing only.")
    c.showPage()

    # ---- Page 2: Balance sheet growth (heading + key points + table) ----
    draw_wrapped_title(c, "Balance Sheet Growth", 60, PAGE_H - 80)
    y = draw_bullets(c, [
        "Total assets grew 18% YoY to Rs 4,820 Cr in Q1 FY26.",
        "Net worth increased to Rs 1,340 Cr, up from Rs 1,110 Cr in Q1 FY25.",
        "Gross NPA improved to 1.8% from 2.4% a year ago.",
        "Capital adequacy ratio (CRAR) stood at 22.4%, well above regulatory minimum.",
    ], 60, PAGE_H - 130)

    table_data = [
        ["Particulars (Rs Cr)", "Q1 FY25", "Q4 FY25", "Q1 FY26"],
        ["Total Assets", "4,085", "4,610", "4,820"],
        ["Net Worth", "1,110", "1,275", "1,340"],
        ["Total Borrowings", "2,690", "2,940", "3,050"],
        ["Gross NPA (%)", "2.4", "2.0", "1.8"],
    ]
    tbl = Table(table_data, colWidths=[170, 90, 90, 90])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b1220")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    tw, th = tbl.wrapOn(c, 0, 0)
    tbl.drawOn(c, 60, PAGE_H - 260 - th)
    c.showPage()

    # ---- Page 3: Revenue trend (heading + bar chart with real data labels) ----
    draw_wrapped_title(c, "Quarterly Revenue Trend", 60, PAGE_H - 80)
    y = draw_bullets(c, [
        "Revenue has grown for four consecutive quarters, driven by disbursement growth.",
        "Q1 FY26 revenue of Rs 172 Cr represents 22% YoY growth.",
    ], 60, PAGE_H - 130)

    categories = ["Q2 FY25", "Q3 FY25", "Q4 FY25", "Q1 FY26"]
    values = [128, 141, 158, 172]
    chart_path = tmp_dir / "revenue_bar.png"
    label_fracs, figsize, dpi = make_bar_chart_png(categories, values, chart_path)

    img_w = figsize[0] * 72   # points
    img_h = figsize[1] * 72
    img_x = 70
    img_y = PAGE_H - 200 - img_h
    c.drawImage(str(chart_path), img_x, img_y, width=img_w, height=img_h)

    c.setFont("Helvetica-Bold", 10.5)
    c.setFillColor(colors.HexColor("#0f172a"))
    for (fx, fy), v in zip(label_fracs, values):
        lx = img_x + fx * img_w
        ly = img_y + fy * img_h + 6
        c.drawCentredString(lx, ly, f"Rs {v} Cr")

    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor("#64748b"))
    c.drawString(img_x, img_y - 16, "Figures in Rs Crore, unaudited management estimates")
    c.showPage()

    # ---- Page 4: Loan book mix (heading + pie chart with real legend text) ----
    draw_wrapped_title(c, "Loan Book Composition", 60, PAGE_H - 80)
    y = draw_bullets(c, [
        "Home loans remain the largest segment at 48% of the book.",
        "Loan against property (LAP) has grown share to 22% as of Q1 FY26.",
    ], 60, PAGE_H - 130)

    pie_labels = ["Home Loans", "LAP", "Affordable Housing", "Construction Finance", "Other"]
    pie_values = [48, 22, 18, 8, 4]
    pie_path = tmp_dir / "loanmix_pie.png"
    make_pie_chart_png(pie_labels, pie_values, pie_path)

    pie_w, pie_h = 4.6 * 72, 3.4 * 72
    pie_x, pie_y = 70, PAGE_H - 200 - pie_h
    c.drawImage(str(pie_path), pie_x, pie_y, width=pie_w, height=pie_h)

    legend_x = pie_x + pie_w + 30
    legend_y = pie_y + pie_h - 20
    swatches = ["#2563eb", "#60a5fa", "#93c5fd", "#1d4ed8", "#bfdbfe"]
    c.setFont("Helvetica", 11)
    for lbl, val, sw in zip(pie_labels, pie_values, swatches):
        c.setFillColor(colors.HexColor(sw))
        c.rect(legend_x, legend_y - 3, 10, 10, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#0f172a"))
        c.drawString(legend_x + 16, legend_y, f"{lbl} — {val}%")
        legend_y -= 22
    c.showPage()

    c.save()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
