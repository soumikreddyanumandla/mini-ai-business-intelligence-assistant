"""
Frontend Charts Module
----------------------
Builds rich, interactive Plotly visualizations for the Streamlit dashboard:
- Monthly revenue trend line charts with area fills and annotations
- Product revenue and quantity bar charts
- Regional sales distribution charts
- Category and sales channel donut charts
- Dynamic response chart renderer for user queries.
"""

from typing import Any, Dict, List, Optional
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Executive Color Palette
COLOR_PRIMARY = "#4F46E5"    # Indigo
COLOR_SECONDARY = "#06B6D4"  # Cyan
COLOR_SUCCESS = "#10B981"    # Emerald
COLOR_WARNING = "#F59E0B"    # Amber
COLOR_DANGER = "#EF4444"     # Rose/Red
COLOR_ACCENT = "#8B5CF6"     # Purple

THEME_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, -apple-system, sans-serif", size=12, color="#374151"),
    margin=dict(l=20, r=20, t=40, b=20),
    hoverlabel=dict(bgcolor="#1E293B", font_size=12, font_color="#FFFFFF"),
)


def create_monthly_trend_chart(monthly_data: List[Dict[str, Any]]) -> go.Figure:
    """Creates a smooth area/line chart of monthly revenue with peak annotation."""
    df = pd.DataFrame(monthly_data)
    if df.empty or "month" not in df.columns or "net_revenue" not in df.columns:
        fig = go.Figure()
        fig.add_annotation(text="No monthly data available", showarrow=False)
        return fig

    fig = go.Figure()
    
    # Area fill
    fig.add_trace(
        go.Scatter(
            x=df["month"],
            y=df["net_revenue"],
            mode="lines+markers",
            name="Net Revenue",
            line=dict(color=COLOR_PRIMARY, width=3, shape="spline"),
            marker=dict(size=8, color=COLOR_PRIMARY, line=dict(width=2, color="#FFFFFF")),
            fill="tozeroy",
            fillcolor="rgba(79, 70, 229, 0.12)",
            hovertemplate="<b>%{x}</b><br>Net Revenue: ₹%{y:,.2f}<extra></extra>",
        )
    )

    # Highlight peak month
    max_row = df.loc[df["net_revenue"].idxmax()]
    fig.add_annotation(
        x=max_row["month"],
        y=max_row["net_revenue"],
        text=f"Peak: ₹{max_row['net_revenue']:,.0f}",
        showarrow=True,
        arrowhead=2,
        arrowcolor=COLOR_SUCCESS,
        arrowsize=1,
        arrowwidth=2,
        ax=0,
        ay=-35,
        font=dict(size=11, color=COLOR_SUCCESS),
        bgcolor="rgba(16, 185, 129, 0.1)",
        bordercolor=COLOR_SUCCESS,
        borderwidth=1,
        borderpad=4,
    )

    fig.update_layout(
        title="<b>Monthly Realized Revenue Trajectory (2026)</b>",
        xaxis=dict(title="", showgrid=True, gridcolor="rgba(209, 213, 219, 0.4)"),
        yaxis=dict(title="Net Revenue (₹)", showgrid=True, gridcolor="rgba(209, 213, 219, 0.4)", tickformat="₹,"),
        **THEME_LAYOUT,
    )
    return fig


def create_product_revenue_chart(product_data: List[Dict[str, Any]]) -> go.Figure:
    """Creates a horizontal bar chart ranking products by net revenue."""
    df = pd.DataFrame(product_data)
    if df.empty or "product" not in df.columns or "net_revenue" not in df.columns:
        fig = go.Figure()
        fig.add_annotation(text="No product data available", showarrow=False)
        return fig

    df_sorted = df.sort_values(by="net_revenue", ascending=True)

    fig = go.Figure(
        go.Bar(
            x=df_sorted["net_revenue"],
            y=df_sorted["product"],
            orientation="h",
            marker=dict(
                color=df_sorted["net_revenue"],
                colorscale="Purples",
                line=dict(color="rgba(255,255,255,0.6)", width=1),
            ),
            text=df_sorted["net_revenue"].apply(lambda v: f"₹{v:,.0f}"),
            textposition="auto",
            hovertemplate="<b>%{y}</b><br>Net Revenue: ₹%{x:,.2f}<br>Units Sold: %{customdata}<extra></extra>",
            customdata=df_sorted.get("quantity_sold", [0] * len(df_sorted)),
        )
    )

    fig.update_layout(
        title="<b>Product Revenue Contribution Ranking</b>",
        xaxis=dict(title="Net Sales (₹)", showgrid=True, gridcolor="rgba(209, 213, 219, 0.4)", tickformat="₹,"),
        yaxis=dict(title=""),
        **THEME_LAYOUT,
    )
    return fig


def create_regional_bar_chart(region_data: List[Dict[str, Any]]) -> go.Figure:
    """Creates a stylized bar chart showing sales performance across regions."""
    df = pd.DataFrame(region_data)
    if df.empty or "region" not in df.columns or "net_revenue" not in df.columns:
        fig = go.Figure()
        fig.add_annotation(text="No regional data available", showarrow=False)
        return fig

    colors = [COLOR_PRIMARY, COLOR_SECONDARY, COLOR_ACCENT, COLOR_WARNING]

    fig = go.Figure(
        go.Bar(
            x=df["region"],
            y=df["net_revenue"],
            marker=dict(color=colors[:len(df)], line=dict(width=1, color="#FFFFFF")),
            text=df["net_revenue"].apply(lambda v: f"₹{v:,.0f}"),
            textposition="outside",
            hovertemplate="<b>%{x} Region</b><br>Net Revenue: ₹%{y:,.2f}<br>Units: %{customdata[0]}<br>Orders: %{customdata[1]}<extra></extra>",
            customdata=df[["quantity_sold", "transaction_count"]].values if "transaction_count" in df.columns else None,
        )
    )

    fig.update_layout(
        title="<b>Regional Net Revenue Breakdown</b>",
        xaxis=dict(title=""),
        yaxis=dict(title="Net Revenue (₹)", showgrid=True, gridcolor="rgba(209, 213, 219, 0.4)", tickformat="₹,"),
        **THEME_LAYOUT,
    )
    return fig


def create_category_donut_chart(category_data: List[Dict[str, Any]]) -> go.Figure:
    """Creates an elegant donut chart for category market share."""
    df = pd.DataFrame(category_data)
    if df.empty or "category" not in df.columns or "net_revenue" not in df.columns:
        fig = go.Figure()
        fig.add_annotation(text="No category data available", showarrow=False)
        return fig

    fig = go.Figure(
        go.Pie(
            labels=df["category"],
            values=df["net_revenue"],
            hole=0.55,
            marker=dict(colors=[COLOR_PRIMARY, COLOR_SECONDARY, COLOR_ACCENT, COLOR_WARNING]),
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b><br>Net Revenue: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
        )
    )

    fig.update_layout(
        title="<b>Category Revenue Distribution</b>",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
        **THEME_LAYOUT,
    )
    return fig


def create_channel_donut_chart(channel_data: List[Dict[str, Any]]) -> go.Figure:
    """Creates a donut chart comparing Online vs Retail sales channels."""
    df = pd.DataFrame(channel_data)
    if df.empty or "sales_channel" not in df.columns or "net_revenue" not in df.columns:
        fig = go.Figure()
        fig.add_annotation(text="No channel data available", showarrow=False)
        return fig

    fig = go.Figure(
        go.Pie(
            labels=df["sales_channel"],
            values=df["net_revenue"],
            hole=0.6,
            marker=dict(colors=[COLOR_PRIMARY, COLOR_SUCCESS]),
            textinfo="label+percent",
            hovertemplate="<b>%{label} Channel</b><br>Net Revenue: ₹%{value:,.2f}<br>Share: %{percent}<extra></extra>",
        )
    )

    fig.update_layout(
        title="<b>Sales Channel Split (Online vs Retail)</b>",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
        **THEME_LAYOUT,
    )
    return fig


def render_dynamic_query_chart(
    chart_type: str,
    supporting_data: List[Dict[str, Any]],
    title: str = "Query Visualization",
    metrics: Optional[Dict[str, Any]] = None,
) -> Optional[go.Figure]:
    """
    Renders dynamic interactive Plotly visualization for an AI query response.
    """
    if not supporting_data:
        return None

    df = pd.DataFrame(supporting_data)

    if chart_type == "line":
        x_col = "month" if "month" in df.columns else df.columns[0]
        y_col = "net_revenue" if "net_revenue" in df.columns else df.columns[1]
        fig = px.line(df, x=x_col, y=y_col, markers=True, title=f"<b>{title}</b>")
        fig.update_traces(line_color=COLOR_PRIMARY, line_width=3)
        fig.update_layout(**THEME_LAYOUT)
        return fig

    elif chart_type == "donut":
        label_col = "category" if "category" in df.columns else ("sales_channel" if "sales_channel" in df.columns else ("status" if "status" in df.columns else df.columns[0]))
        val_col = "net_revenue" if "net_revenue" in df.columns else ("record_count" if "record_count" in df.columns else df.columns[1])
        fig = px.pie(df, names=label_col, values=val_col, hole=0.5, title=f"<b>{title}</b>")
        fig.update_layout(**THEME_LAYOUT)
        return fig

    elif chart_type == "bar":
        # Check if period comparison
        if "period" in df.columns and "net_revenue" in df.columns:
            fig = px.bar(
                df.dropna(subset=["period", "net_revenue"]),
                x="period",
                y="net_revenue",
                title=f"<b>{title}</b>",
                color="period",
                color_discrete_sequence=[COLOR_PRIMARY, COLOR_SUCCESS],
                text_auto=".2s",
            )
            fig.update_layout(showlegend=False, **THEME_LAYOUT)
            return fig

        # Standard bar chart
        x_col = "product" if "product" in df.columns else ("region" if "region" in df.columns else df.columns[0])
        y_col = "net_revenue" if "net_revenue" in df.columns else ("quantity_sold" if "quantity_sold" in df.columns else df.columns[1])
        fig = px.bar(df, x=x_col, y=y_col, title=f"<b>{title}</b>", text_auto=".2s")
        fig.update_traces(marker_color=COLOR_PRIMARY)
        fig.update_layout(**THEME_LAYOUT)
        return fig

    return None
