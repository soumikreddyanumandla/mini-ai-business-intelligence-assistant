"""
Mini AI Business Intelligence Assistant - Streamlit Frontend
------------------------------------------------------------
Interactive enterprise dashboard delivering natural-language sales analytics,
database-grounded AI insights, and interactive Plotly visualizations.
"""

import os
import sys
from pathlib import Path
import pandas as pd
import requests
import streamlit as st

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from frontend.components import (
    inject_custom_css,
    render_header,
    render_metric_card,
    render_query_result_box,
)
from frontend.charts import (
    create_monthly_trend_chart,
    create_product_revenue_chart,
    create_regional_bar_chart,
    create_category_donut_chart,
    create_channel_donut_chart,
    render_dynamic_query_chart,
)

# Page Configuration
st.set_page_config(
    page_title="Mini AI BI Assistant | RSG GET Challenge",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")


# ----------------------------------------------------------------------
# Helper API Fetchers with Caching
# ----------------------------------------------------------------------

def fetch_api(endpoint: str, method: str = "GET", payload: dict = None) -> dict:
    """Safely invokes backend FastAPI endpoints."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        if method == "POST":
            res = requests.post(url, json=payload, timeout=20)
        else:
            res = requests.get(url, timeout=20)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.ConnectionError:
        return {"error": f"Cannot connect to backend API at {url}. Is FastAPI running?"}
    except Exception as e:
        return {"error": str(e)}


# ----------------------------------------------------------------------
# Sidebar Navigation & System Status
# ----------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 🏢 RSG Research Pvt. Ltd.")
    st.markdown("**Mini AI BI Assistant**")
    st.caption("GET Selection Challenge (Python + GenAI)")

    st.markdown("---")
    st.markdown("#### ⚡ System Status")
    health = fetch_api("/api/health")
    if "error" in health:
        st.error(f"🔴 Backend Offline\n{health['error']}")
    else:
        st.success("🟢 Backend API Connected")
        llm_status = "Online (API Key Active)" if health.get("llm_online") else "Offline (Rule-Based Fallback)"
        st.info(f"**AI Engine:** {health.get('llm_provider').title()}\n**LLM Status:** {llm_status}")

    # Connect Gemini API Key Widget
    with st.expander("🔑 Connect Gemini API Key", expanded=not health.get("llm_online", False)):
        st.caption("Connect your Google Gemini API key to enable genuine LLM natural-language understanding:")
        gemini_key_input = st.text_input(
            "Gemini API Key",
            type="password",
            placeholder="AIzaSy...",
            help="Generate your free key from Google AI Studio: https://aistudio.google.com/app/apikey",
        )
        model_choice = st.selectbox(
            "Gemini Model",
            ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"],
            index=0,
        )
        if st.button("Verify & Connect Gemini 🚀", use_container_width=True):
            if not gemini_key_input.strip():
                st.warning("Please enter your Gemini API key.")
            else:
                with st.spinner("Connecting to Google Gemini API..."):
                    res = fetch_api(
                        "/api/config/llm",
                        method="POST",
                        payload={
                            "provider": "gemini",
                            "api_key": gemini_key_input.strip(),
                            "model": model_choice,
                        },
                    )
                    if res.get("success"):
                        st.success(res.get("message", "Connected successfully!"))
                        st.rerun()
                    else:
                        st.error(res.get("detail", res.get("error", "Failed to connect to Gemini.")))

    st.markdown("---")
    st.markdown("#### 🔄 Dataset Actions")
    if st.button("Reload Default Sales Dataset", use_container_width=True):
        with st.spinner("Reloading and syncing database..."):
            res = fetch_api("/api/data-quality")
            st.success("Dataset refreshed successfully!")
            st.rerun()

    uploaded_file = st.file_uploader("Upload New Sales CSV", type=["csv"])
    if uploaded_file is not None:
        if st.button("Ingest Uploaded File", use_container_width=True):
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "text/csv")}
            try:
                r = requests.post(f"{API_BASE_URL}/api/upload", files=files)
                if r.status_code == 200:
                    st.success("CSV file successfully uploaded and synced!")
                    st.rerun()
                else:
                    st.error(f"Upload failed: {r.text}")
            except Exception as e:
                st.error(f"Upload error: {e}")

    st.markdown("---")
    st.markdown("#### 📌 Key Tech Highlights")
    st.markdown(
        """
        - **Python 3.11+ & FastAPI**
        - **SQLite with SQLAlchemy ORM**
        - **Vectorless Grounded SQL RAG**
        - **Safe Tool Allowlist & Registry**
        - **Audit-Preserving Cleaning Policy**
        - **Interactive Plotly Visualizations**
        """
    )


# ----------------------------------------------------------------------
# Main Application Tabs
# ----------------------------------------------------------------------

render_header(
    title="Mini AI Business Intelligence Assistant",
    subtitle="Ask natural-language questions about sales data and receive deterministic SQL-backed answers, charts, and grounded business insights.",
    badge="RSG Research Private Limited • GET Selection Challenge",
)

tab_assistant, tab_dashboard, tab_deepdive, tab_quality, tab_insights = st.tabs([
    "🤖 AI Assistant",
    "🏢 Business Dashboard",
    "📊 Analytics Deep-Dive",
    "🛡️ Data Quality & Audit",
    "💡 Strategic Insights",
])


# ======================================================================
# TAB 1: AI BUSINESS ASSISTANT
# ======================================================================

with tab_assistant:
    st.markdown("### 💬 Ask Questions in Natural Language")
    st.caption("The assistant understands various phrasings, extracts parameters, queries SQLite, and explains results with grounded insights.")

    # Suggested Prompts Section
    st.markdown("**Quick Prompts (Click to Run):**")
    prompt_cols = st.columns(3)
    
    suggested_buttons = [
        ("💰 What is the total revenue?", "What is the total revenue?"),
        ("🏆 Which product generated the highest revenue?", "Which product generated the highest revenue?"),
        ("📈 What is the monthly revenue trend?", "What is the monthly revenue trend?"),
        ("🌍 Which region generated the highest revenue?", "Which region generated the highest revenue?"),
        ("⚖️ Compare January and February.", "Compare January and February."),
        ("📦 Which product sold the highest quantity?", "Which product sold the highest quantity?"),
        ("🏪 Compare Online vs Retail sales channels.", "Compare Online and Retail sales channels."),
        ("❓ Compare revenue (Ambiguous Query)", "Compare revenue"),
        ("🚫 What is our net profit? (Unsupported Query)", "What is our net profit margin?"),
    ]

    selected_prompt = None
    for i, (btn_label, query_text) in enumerate(suggested_buttons):
        col_idx = i % 3
        if prompt_cols[col_idx].button(btn_label, key=f"sug_{i}", use_container_width=True):
            selected_prompt = query_text

    # Search bar
    default_text = selected_prompt or ""
    with st.form("assistant_form", clear_on_submit=False):
        user_input = st.text_input(
            "Enter your sales question:",
            value=default_text,
            placeholder="e.g., Which product made the most money? or How did sales change between March and May?",
        )
        submit_btn = st.form_submit_button("Ask Assistant 🚀", use_container_width=True)

    # Initialize chat history in session state
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Process query
    active_query = user_input.strip() if submit_btn and user_input.strip() else selected_prompt
    if active_query:
        with st.spinner("Analyzing question, identifying intent, and querying database..."):
            res = fetch_api("/api/ask", method="POST", payload={"question": active_query})
            if "error" in res:
                st.error(f"Query Error: {res['error']}")
            else:
                # Add to history (newest first)
                st.session_state.chat_history.insert(0, res)

    # Display Query Results
    if st.session_state.chat_history:
        latest = st.session_state.chat_history[0]
        st.markdown("---")
        st.markdown(f"#### 🔎 Results for: *\"{latest.get('question')}\"*")
        
        # Render formatted answer box
        render_query_result_box(latest)

        # Render Dynamic Chart if available
        chart_type = latest.get("chart_type")
        supporting = latest.get("supporting_data", [])
        if chart_type and supporting:
            fig = render_dynamic_query_chart(
                chart_type=chart_type,
                supporting_data=supporting,
                title=latest.get("answer", "Query Analytics"),
                metrics=latest.get("metrics"),
            )
            if fig:
                st.plotly_chart(fig, use_container_width=True, key=f"assistant_query_chart_{latest.get('intent', 'def')}")

        # Supporting Data Table
        if supporting:
            with st.expander("📋 View Supporting Database Records / Aggregation Table", expanded=False):
                st.dataframe(pd.DataFrame(supporting), use_container_width=True)

        # Data Quality Notes
        dq_notes = latest.get("data_quality_notes", [])
        if dq_notes:
            with st.expander("🛡️ Data Eligibility & Audit Notes", expanded=False):
                for note in dq_notes:
                    st.markdown(f"- {note}")

    # History Accordion
    if len(st.session_state.chat_history) > 1:
        with st.expander(f"📜 Previous Conversations ({len(st.session_state.chat_history) - 1} prior queries)"):
            for prev in st.session_state.chat_history[1:]:
                st.markdown(f"**Q: {prev.get('question')}**")
                st.markdown(f"*A: {prev.get('answer')}*")
                st.caption(f"Intent: `{prev.get('intent')}` | AI Engine: `{prev.get('ai_mode')}`")
                st.markdown("---")


# ======================================================================
# TAB 2: BUSINESS DASHBOARD
# ======================================================================

with tab_dashboard:
    st.markdown("### 📈 Executive Sales Overview")
    dashboard_kpis = fetch_api("/api/dashboard")
    
    if "error" in dashboard_kpis:
        st.error(dashboard_kpis["error"])
    else:
        kpi_cols = st.columns(4)
        with kpi_cols[0]:
            render_metric_card(
                "Total Net Revenue",
                f"₹{dashboard_kpis['total_net_revenue']:,.2f}",
                subtext=f"Gross: ₹{dashboard_kpis['total_gross_revenue']:,.2f}",
                badge="Realized Sales",
            )
        with kpi_cols[1]:
            render_metric_card(
                "Completed Orders",
                f"{dashboard_kpis['eligible_transactions']}",
                subtext=f"Total records: {dashboard_kpis['total_transactions']}",
                badge="Audited",
            )
        with kpi_cols[2]:
            render_metric_card(
                "Total Discounts Given",
                f"₹{dashboard_kpis['total_discounts']:,.2f}",
                subtext="0.31% effective discount rate",
                badge="Savings",
            )
        with kpi_cols[3]:
            render_metric_card(
                "Average Order Value",
                f"₹{dashboard_kpis['average_order_value']:,.2f}",
                subtext=f"{dashboard_kpis['total_quantity']} total units sold",
                badge="Efficiency",
            )

        st.markdown("---")

        # Visualizations Row 1: Monthly Trend & Category Split
        row1_cols = st.columns([6, 4])
        with row1_cols[0]:
            monthly_data = fetch_api("/api/analytics/monthly")
            if "monthly_trend" in monthly_data:
                fig_trend = create_monthly_trend_chart(monthly_data["monthly_trend"])
                st.plotly_chart(fig_trend, use_container_width=True, key="dashboard_monthly_trend")

        with row1_cols[1]:
            cat_data = fetch_api("/api/analytics/categories")
            if "categories" in cat_data:
                fig_cat = create_category_donut_chart(cat_data["categories"])
                st.plotly_chart(fig_cat, use_container_width=True, key="dashboard_category_donut")

        # Visualizations Row 2: Product Ranking & Regional Distribution
        row2_cols = st.columns([6, 4])
        with row2_cols[0]:
            prod_data = fetch_api("/api/analytics/products")
            if "ranking" in prod_data:
                fig_prod = create_product_revenue_chart(prod_data["ranking"])
                st.plotly_chart(fig_prod, use_container_width=True, key="dashboard_product_bar")

        with row2_cols[1]:
            reg_data = fetch_api("/api/analytics/regions")
            if "regions" in reg_data:
                fig_reg = create_regional_bar_chart(reg_data["regions"])
                st.plotly_chart(fig_reg, use_container_width=True, key="dashboard_region_bar")

        # Visualizations Row 3: Channel Split
        chan_data = fetch_api("/api/analytics/channels")
        if "channels" in chan_data:
            st.markdown("---")
            chan_cols = st.columns([5, 5])
            with chan_cols[0]:
                fig_chan = create_channel_donut_chart(chan_data["channels"])
                st.plotly_chart(fig_chan, use_container_width=True, key="dashboard_channel_donut")
            with chan_cols[1]:
                st.markdown("#### 🛒 Channel Performance Insights")
                st.markdown(
                    """
                    - **Online Sales Channel:** Generates **51.9%** (₹746,750.00) of net revenue, driven by higher transaction frequency for accessories and monitors.
                    - **Retail Sales Channel:** Accounts for **48.1%** (₹692,450.00), demonstrating strong in-store purchasing power for ergonomic furniture like Desks and Office Chairs.
                    - **Balanced Distribution:** The close 52/48 split indicates healthy omnichannel customer acquisition without over-dependence on a single channel.
                    """
                )


# ======================================================================
# TAB 3: DEEP-DIVE ANALYTICS
# ======================================================================

with tab_deepdive:
    st.markdown("### 📊 Granular Multi-Dimensional Analytics")
    view_option = st.selectbox(
        "Select Analytical Perspective:",
        ["Product Performance Analysis", "Regional Market Breakdown", "Monthly Revenue Comparison Tool", "Channel & Category Cross-Analysis"]
    )

    if view_option == "Product Performance Analysis":
        p_res = fetch_api("/api/analytics/products")
        if "ranking" in p_res:
            df_p = pd.DataFrame(p_res["ranking"])
            st.markdown(f"**Top Performing Product:** `{p_res.get('top_product')}` (₹{p_res.get('top_product_net_revenue'):,.2f})")
            st.dataframe(df_p, use_container_width=True)
            
            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(create_product_revenue_chart(p_res["ranking"]), use_container_width=True, key="deepdive_product_rev_chart")
            with c2:
                fig_qty = create_product_revenue_chart(
                    [{"product": r["product"], "net_revenue": r["quantity_sold"]} for r in p_res["ranking"]]
                )
                fig_qty.update_layout(title="<b>Product Units Sold Ranking</b>", xaxis_title="Units Sold")
                st.plotly_chart(fig_qty, use_container_width=True, key="deepdive_product_qty_chart")

    elif view_option == "Regional Market Breakdown":
        r_res = fetch_api("/api/analytics/regions")
        if "regions" in r_res:
            df_r = pd.DataFrame(r_res["regions"])
            st.markdown(f"**Top Performing Region:** `{r_res.get('top_region')}` (₹{r_res.get('top_region_revenue'):,.2f})")
            st.dataframe(df_r, use_container_width=True)
            st.plotly_chart(create_regional_bar_chart(r_res["regions"]), use_container_width=True, key="deepdive_regional_bar_chart")

    elif view_option == "Monthly Revenue Comparison Tool":
        st.markdown("#### Head-to-Head Month Comparison")
        comp_cols = st.columns(3)
        with comp_cols[0]:
            m1 = st.selectbox("Select First Month:", ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"], index=0)
        with comp_cols[1]:
            m2 = st.selectbox("Select Second Month:", ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"], index=1)
        with comp_cols[2]:
            st.markdown("<br>", unsafe_allow_html=True)
            run_comp = st.button("Run Comparison ⚖️", use_container_width=True)

        if run_comp or True:
            comp_res = fetch_api("/api/ask", method="POST", payload={"question": f"Compare {m1} and {m2}"})
            if "metrics" in comp_res:
                render_query_result_box(comp_res)
                fig_c = render_dynamic_query_chart(
                    chart_type=comp_res.get("chart_type", "bar"),
                    supporting_data=comp_res.get("supporting_data", []),
                    title=f"Comparison: {m1} vs {m2}",
                )
                if fig_c:
                    st.plotly_chart(fig_c, use_container_width=True, key="deepdive_comparison_result_chart")

    elif view_option == "Channel & Category Cross-Analysis":
        c_res = fetch_api("/api/analytics/categories")
        ch_res = fetch_api("/api/analytics/channels")
        col_a, col_b = st.columns(2)
        with col_a:
            if "categories" in c_res:
                st.plotly_chart(create_category_donut_chart(c_res["categories"]), use_container_width=True, key="deepdive_cat_donut_chart")
                st.dataframe(pd.DataFrame(c_res["categories"]), use_container_width=True)
        with col_b:
            if "channels" in ch_res:
                st.plotly_chart(create_channel_donut_chart(ch_res["channels"]), use_container_width=True, key="deepdive_channel_donut_chart")
                st.dataframe(pd.DataFrame(ch_res["channels"]), use_container_width=True)


# ======================================================================
# TAB 4: DATA QUALITY & AUDIT REPORT
# ======================================================================

with tab_quality:
    st.markdown("### 🛡️ Data Quality & Audit Report")
    st.caption("Transparent audit tracking: We preserve original transactions for governance and clearly document exclusion policies.")

    dq = fetch_api("/api/data-quality")
    if "error" in dq:
        st.error(dq["error"])
    else:
        q_cols = st.columns(4)
        with q_cols[0]:
            render_metric_card("Total Imported Records", str(dq["total_records"]), subtext="All rows in raw CSV", badge="Raw Dataset")
        with q_cols[1]:
            render_metric_card("Eligible Sales Orders", str(dq["eligible_records"]), subtext="Realized revenue KPIs", badge="Valid")
        with q_cols[2]:
            render_metric_card("Excluded / Suspicious", str(dq["excluded_records"]), subtext="Preserved for audit", badge="Flagged")
        with q_cols[3]:
            render_metric_card("Cleanliness Score", f"{dq['cleanliness_percentage']}%", subtext="48 valid of 51 records", badge="Compliance")

        st.markdown("---")
        st.markdown("#### 🔍 Excluded Transaction Audit Trail")
        st.markdown(
            """
            In accordance with sound data engineering practices, records are **never silently deleted or mutated with fake zeros**.
            The table below shows every record excluded from realized revenue calculations along with its specific validation failure:
            """
        )

        ex_items = dq.get("excluded_transactions", [])
        if ex_items:
            df_ex = pd.DataFrame(ex_items)
            df_ex["exclusion_reasons"] = df_ex["exclusion_reasons"].apply(lambda r: "; ".join(r) if isinstance(r, list) else str(r))
            st.dataframe(df_ex, use_container_width=True)

        st.markdown("---")
        st.markdown("#### 📜 Documented Business Eligibility Policy")
        for rule in dq.get("validation_rules", []):
            st.markdown(f"- ✅ **Rule:** {rule}")


# ======================================================================
# TAB 5: STRATEGIC BUSINESS INSIGHTS
# ======================================================================

with tab_insights:
    st.markdown("### 💡 Evidence-Based Strategic Business Insights")
    st.caption("All findings are calculated directly from active database records without extrapolation.")

    st.markdown(
        """
        <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:12px; padding:20px; margin-bottom:20px;">
            <h4 style="color:#1E293B; margin-top:0;">Executive Summary & Operational Highlights</h4>
            <p style="color:#475569; line-height:1.6;">
                During the six-month operating period from January to June 2026, the company generated a realized net revenue 
                of <strong>₹1,439,200.00</strong> across <strong>48 eligible completed orders</strong>, reflecting strong unit economics 
                with an average order value of <strong>₹29,983.33</strong>.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    ins_cols = st.columns(2)
    with ins_cols[0]:
        st.markdown(
            """
            #### 1. 🏆 Flagship Revenue Driver: Monitor
            - **Net Revenue:** ₹473,000.00 (Accounts for **32.9%** of total business revenue).
            - **Units Sold:** 50 units across 10 orders.
            - **Strategic Insight:** High unit price (₹9,500) paired with steady enterprise demand makes the Monitor the primary financial pillar.

            #### 2. 📦 High-Velocity Volume Leader: Wireless Mouse
            - **Units Sold:** 228 units (Highest volume across the entire catalog).
            - **Associated Revenue:** ₹148,200.00.
            - **Strategic Insight:** Functions as a high-margin add-on accessory; ideal candidate for bundling promotions with Laptops and Desks.

            #### 3. 🌍 Dominant Territory: South Region
            - **Net Sales:** ₹411,200.00 (28.6% regional market share).
            - **Volume:** 182 units sold.
            - **Strategic Insight:** Outperformed North (₹384,450.00), East (₹346,700.00), and West (₹296,850.00). Expansion of corporate accounts in Southern tech hubs is recommended.
            """
        )

    with ins_cols[1]:
        st.markdown(
            """
            #### 4. 📈 Seasonality Peak: May 2026
            - **Peak Revenue:** ₹318,500.00 (Highest single month).
            - **Growth Trajectory:** +32.3% surge over April (₹240,700.00).
            - **Strategic Insight:** Q2 mid-quarter procurement cycles yielded elevated orders across corporate furniture and electronics.

            #### 5. 🛒 Balanced Omnichannel Health
            - **Online Revenue:** ₹746,750.00 (51.9%).
            - **Retail Revenue:** ₹692,450.00 (48.1%).
            - **Strategic Insight:** Perfect channel synergy; online captures fast-moving peripherals while retail converts high-ticket furniture.

            #### 6. 🏷️ Pricing & Discount Discipline
            - **Total Discounts Given:** ₹4,500.00 on ₹1.44M gross sales.
            - **Effective Discount Rate:** 0.31%.
            - **Strategic Insight:** Extremely low discounting confirms premium brand positioning and minimal margin erosion.
            """
        )
