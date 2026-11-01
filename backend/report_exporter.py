"""
Report Exporter Module
----------------------
Generates professional executive PDF reports and audit-grade CSV exports
grounded directly in the SQLite database records.

Features:
- Executive PDF generation via ReportLab with corporate styling, KPI metrics,
  product rankings, regional breakdown, monthly trend, and data-cleaning audit lineage.
- CSV exports for transactions (with audit eligibility flags) and aggregated summaries.
"""

import io
import csv
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)

from backend import analytics
from backend.models import SalesTransaction


def generate_executive_pdf_report(db: Session) -> bytes:
    """
    Generates an executive-grade Business Intelligence PDF report in memory.
    Returns bytes of the compiled PDF document.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()
    
    # Custom Corporate Color Palette
    c_primary = colors.HexColor("#1E293B")      # Slate 800
    c_accent = colors.HexColor("#2563EB")       # Blue 600
    c_muted = colors.HexColor("#64748B")        # Slate 500
    c_bg_light = colors.HexColor("#F8FAFC")     # Slate 50
    c_border = colors.HexColor("#CBD5E1")       # Slate 300
    c_danger = colors.HexColor("#DC2626")       # Red 600

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=c_primary,
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=c_muted,
    )
    h2_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=c_primary,
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "BodyDark",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=c_primary,
    )

    story = []

    # 1. Header Banner
    story.append(Paragraph("MINI AI BUSINESS INTELLIGENCE ASSISTANT", title_style))
    story.append(Paragraph(
        f"Executive Sales Performance & Data Governance Report • Generated on {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}",
        subtitle_style
    ))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.5, color=c_accent, spaceBefore=2, spaceAfter=8))

    # 2. Executive Summary & Audit Governance Callout
    tot_rev = analytics.get_total_revenue(db)
    dq_summary = analytics.get_data_quality_summary(db)

    gov_text = (
        f"<b>Data Governance & Lineage Notice:</b> Grounded strictly in deterministic database records. "
        f"Of <b>{dq_summary['total_records']} raw transactions</b> ingested, <b>{dq_summary['eligible_records']} eligible completed transactions</b> "
        f"form the realized financial base (Cleanliness: {dq_summary['cleanliness_percentage']}%). Exactly <b>{dq_summary['excluded_records']} anomalous records</b> "
        f"were audited and excluded per the Single-Source-of-Truth Data Cleaning Policy."
    )
    gov_table = Table([[Paragraph(gov_text, body_style)]], colWidths=[540])
    gov_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), c_bg_light),
        ('BOX', (0, 0), (-1, -1), 1, c_border),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(gov_table)
    story.append(Spacer(1, 10))

    # 3. High-Level KPI Matrix
    story.append(Paragraph("1. Executive Financial & Operational KPIs", h2_style))
    
    kpi_data = [
        [
            Paragraph("<b>Realized Net Revenue</b>", body_style),
            Paragraph(f"<b>₹{tot_rev['total_net_revenue']:,.2f}</b>", body_style),
            Paragraph("<b>Gross Revenue</b>", body_style),
            Paragraph(f"₹{tot_rev['total_gross_revenue']:,.2f}", body_style),
        ],
        [
            Paragraph("<b>Total Discounts Given</b>", body_style),
            Paragraph(f"₹{tot_rev['total_discounts']:,.2f}", body_style),
            Paragraph("<b>Average Order Value (AOV)</b>", body_style),
            Paragraph(f"₹{tot_rev['average_order_value']:,.2f}", body_style),
        ],
        [
            Paragraph("<b>Eligible Orders Count</b>", body_style),
            Paragraph(f"{tot_rev['eligible_transaction_count']} orders", body_style),
            Paragraph("<b>Total Units Sold</b>", body_style),
            Paragraph(f"{tot_rev['total_quantity_sold']} units", body_style),
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[140, 130, 140, 130])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('BACKGROUND', (0, 0), (0, -1), c_bg_light),
        ('BACKGROUND', (2, 0), (2, -1), c_bg_light),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 10))

    # 4. Product Revenue Rankings Table
    story.append(Paragraph("2. Product Revenue Performance Rankings", h2_style))
    prod_data = analytics.get_highest_revenue_product(db)
    prod_rows = [["Rank", "Product Name", "Units Sold", "Order Count", "Net Revenue (₹)"]]
    for item in prod_data["ranking"]:
        prod_rows.append([
            str(item["rank"]),
            item["product"],
            str(item["quantity_sold"]),
            str(item["order_count"]),
            f"₹{item['net_revenue']:,.2f}",
        ])
    prod_table = Table(prod_rows, colWidths=[40, 210, 80, 80, 130])
    prod_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_primary),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_light]),
    ]))
    story.append(prod_table)
    story.append(Spacer(1, 10))

    # 5. Regional Breakdown Table
    story.append(Paragraph("3. Regional Sales Performance Breakdown", h2_style))
    reg_data = analytics.get_highest_revenue_region(db)
    reg_rows = [["Rank", "Region", "Net Revenue (₹)", "Revenue Share %", "Units Sold", "AOV (₹)"]]
    for r in reg_data["regions"]:
        aov = round(r["net_revenue"] / r["transaction_count"], 2) if r.get("transaction_count") else 0.0
        share = r.get("revenue_share_percentage", 0.0)
        reg_rows.append([
            str(r["rank"]),
            r["region"],
            f"₹{r['net_revenue']:,.2f}",
            f"{share:.1f}%",
            str(r["quantity_sold"]),
            f"₹{aov:,.2f}",
        ])
    reg_table = Table(reg_rows, colWidths=[40, 100, 110, 95, 85, 110])
    reg_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_accent),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_light]),
    ]))
    story.append(reg_table)
    story.append(Spacer(1, 10))

    # 6. Monthly Revenue Trend Table
    story.append(Paragraph("4. Monthly Revenue & Order Velocity Trend", h2_style))
    month_data = analytics.get_monthly_revenue_trend(db)
    month_rows = [["Month", "Net Revenue (₹)", "Units Sold", "Orders", "MoM Growth %", "Avg Order Value (₹)"]]
    for m in month_data["monthly_trend"]:
        try:
            m_name = datetime.strptime(m["month"], "%Y-%m").strftime("%b %Y")
        except Exception:
            m_name = m["month"]
        growth_str = f"{m['growth_percentage']:+.1f}%" if m["growth_percentage"] is not None else "Baseline"
        aov = round(m["net_revenue"] / m["transaction_count"], 2) if m.get("transaction_count") else 0.0
        month_rows.append([
            m_name,
            f"₹{m['net_revenue']:,.2f}",
            str(m["quantity_sold"]),
            str(m["transaction_count"]),
            growth_str,
            f"₹{aov:,.2f}",
        ])
    month_table = Table(month_rows, colWidths=[90, 105, 75, 60, 95, 115])
    month_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_primary),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_light]),
    ]))
    story.append(month_table)
    story.append(Spacer(1, 10))

    # 7. Data Cleaning & Exclusions Audit Log
    story.append(Paragraph("5. Data Quality Exclusions Audit Log (Lineage Preserved)", h2_style))
    excluded_txns = db.query(SalesTransaction).filter(SalesTransaction.is_eligible.is_(False)).all()
    audit_rows = [["Txn ID", "Date", "Product", "Reported Anomaly / Exclusion Reason"]]
    for ex in excluded_txns:
        audit_rows.append([
            ex.transaction_id,
            str(ex.order_date or "Missing/Invalid"),
            ex.product or "N/A",
            ex.exclusion_reason or "Unspecified anomaly",
        ])
    audit_table = Table(audit_rows, colWidths=[80, 75, 115, 270])
    audit_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_danger),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, c_bg_light]),
    ]))
    story.append(audit_table)
    story.append(Spacer(1, 8))

    # Footer note
    footer_text = (
        "<i>CONFIDENTIAL & PROPRIETARY • RSG Research Private Limited Selection Challenge • "
        "Engineered with FastAPI, SQLAlchemy, and Gemini AI.</i>"
    )
    story.append(Paragraph(footer_text, subtitle_style))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_transactions_csv_export(db: Session, filter_eligible: Optional[bool] = None) -> str:
    """
    Exports sales transactions to CSV string format with data governance attributes.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Transaction_Id",
        "Order_Date",
        "Product",
        "Category",
        "Region",
        "Sales_Channel",
        "Quantity",
        "Unit_Price",
        "Discount_Amount",
        "Net_Revenue",
        "Status",
        "Is_Eligible",
        "Exclusion_Reason",
    ])

    query = db.query(SalesTransaction)
    if filter_eligible is not None:
        query = query.filter(SalesTransaction.is_eligible == filter_eligible)
    
    transactions = query.order_by(SalesTransaction.transaction_id.asc()).all()
    for t in transactions:
        net_rev = (t.quantity * t.unit_price - t.discount_amount) if t.is_eligible else 0.0
        writer.writerow([
            t.transaction_id,
            t.order_date.isoformat() if t.order_date else "",
            t.product,
            t.category,
            t.region,
            t.sales_channel,
            t.quantity,
            t.unit_price,
            t.discount_amount,
            f"{net_rev:.2f}",
            t.status,
            "YES" if t.is_eligible else "NO",
            t.exclusion_reason or "",
        ])

    return output.getvalue()


def generate_analytics_summary_csv(db: Session, summary_type: str = "products") -> str:
    """
    Generates CSV export for specific aggregated analytical summaries.
    Options: 'products', 'regions', 'monthly', 'channels'
    """
    output = io.StringIO()
    writer = csv.writer(output)

    if summary_type == "products":
        writer.writerow(["Rank", "Product", "Units_Sold", "Order_Count", "Net_Revenue", "Gross_Revenue"])
        data = analytics.get_highest_revenue_product(db)
        for p in data["ranking"]:
            writer.writerow([
                p["rank"], p["product"], p["quantity_sold"], p["order_count"],
                f"{p['net_revenue']:.2f}", f"{p['gross_revenue']:.2f}"
            ])

    elif summary_type == "regions":
        writer.writerow(["Rank", "Region", "Net_Revenue", "Revenue_Share_Pct", "Units_Sold", "Order_Count", "AOV"])
        data = analytics.get_highest_revenue_region(db)
        for r in data["regions"]:
            aov = round(r["net_revenue"] / r["transaction_count"], 2) if r.get("transaction_count") else 0.0
            share = r.get("revenue_share_percentage", 0.0)
            writer.writerow([
                r["rank"], r["region"], f"{r['net_revenue']:.2f}", f"{share:.2f}",
                r["quantity_sold"], r["transaction_count"], f"{aov:.2f}"
            ])

    elif summary_type == "monthly":
        writer.writerow(["Month", "Month_Name", "Net_Revenue", "Units_Sold", "Order_Count", "MoM_Growth_Pct", "AOV"])
        data = analytics.get_monthly_revenue_trend(db)
        for m in data["monthly_trend"]:
            try:
                m_name = datetime.strptime(m["month"], "%Y-%m").strftime("%B %Y")
            except Exception:
                m_name = m["month"]
            growth_val = f"{m['growth_percentage']:.2f}" if m["growth_percentage"] is not None else ""
            aov = round(m["net_revenue"] / m["transaction_count"], 2) if m.get("transaction_count") else 0.0
            writer.writerow([
                m["month"], m_name, f"{m['net_revenue']:.2f}",
                m["quantity_sold"], m["transaction_count"], growth_val, f"{aov:.2f}"
            ])

    elif summary_type == "channels":
        writer.writerow(["Rank", "Sales_Channel", "Net_Revenue", "Revenue_Share_Pct", "Units_Sold", "Order_Count", "AOV"])
        data = analytics.get_sales_channel_comparison(db)
        for idx, c in enumerate(data["channels"], start=1):
            aov = round(c["net_revenue"] / c["transaction_count"], 2) if c.get("transaction_count") else 0.0
            share = c.get("revenue_share_percentage", 0.0)
            writer.writerow([
                idx, c["sales_channel"], f"{c['net_revenue']:.2f}", f"{share:.2f}",
                c["quantity_sold"], c["transaction_count"], f"{aov:.2f}"
            ])

    return output.getvalue()
