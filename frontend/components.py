"""
Frontend UI Components Module
------------------------------
Encapsulates modular, reusable Streamlit HTML/CSS presentation components:
- Executive KPI summary cards with subtext metrics
- Intent and AI Mode status pills
- Audit quality status indicators
- Structured conversational response cards with grounded insights.
"""

import streamlit as st
from typing import Any, Dict, List, Optional


def inject_custom_css():
    """Injects modern, polished CSS styling into the Streamlit application."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

        html, body, [class*="css"] {
            font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
        }

        /* Metric Card Container */
        .metric-card {
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.95), rgba(248, 250, 252, 0.95));
            border: 1px solid #E2E8F0;
            border-radius: 14px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            margin-bottom: 15px;
        }
        .metric-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(79, 70, 229, 0.08);
            border-color: #CBD5E1;
        }
        .metric-title {
            font-size: 0.85rem;
            font-weight: 600;
            color: #64748B;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 6px;
        }
        .metric-value {
            font-size: 1.85rem;
            font-weight: 800;
            color: #0F172A;
            line-height: 1.2;
            margin-bottom: 6px;
        }
        .metric-sub {
            font-size: 0.8rem;
            color: #10B981;
            font-weight: 500;
        }

        /* Pill Badges */
        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            margin-right: 6px;
        }
        .badge-indigo { background-color: #EEF2FF; color: #4F46E5; border: 1px solid #C7D2FE; }
        .badge-green { background-color: #ECFDF5; color: #059669; border: 1px solid #A7F3D0; }
        .badge-amber { background-color: #FFFBEB; color: #D97706; border: 1px solid #FDE68A; }
        .badge-rose { background-color: #FFF1F2; color: #E11D48; border: 1px solid #FECDD3; }
        .badge-purple { background-color: #F5F3FF; color: #7C3AED; border: 1px solid #DDD6FE; }

        /* Assistant Response Card */
        .assistant-box {
            background-color: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-left: 5px solid #4F46E5;
            border-radius: 12px;
            padding: 22px;
            margin-top: 14px;
            margin-bottom: 20px;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.03);
        }
        .assistant-headline {
            font-size: 1.25rem;
            font-weight: 700;
            color: #1E293B;
            margin-bottom: 10px;
        }
        .assistant-grounded-text {
            font-size: 0.98rem;
            color: #334155;
            line-height: 1.6;
            margin-bottom: 14px;
            background: #F8FAFC;
            padding: 12px 16px;
            border-radius: 8px;
            border: 1px solid #F1F5F9;
        }

        /* Header Gradient Banner */
        .main-header {
            background: linear-gradient(135deg, #1E1B4B 0%, #312E81 50%, #4338CA 100%);
            border-radius: 16px;
            padding: 26px 32px;
            color: white;
            margin-bottom: 24px;
            box-shadow: 0 10px 25px -5px rgba(49, 46, 129, 0.2);
        }
        .main-header h1 {
            color: #FFFFFF;
            font-size: 1.9rem;
            font-weight: 800;
            margin: 0 0 6px 0;
        }
        .main-header p {
            color: #C7D2FE;
            font-size: 0.95rem;
            margin: 0;
        }

        /* Question chips */
        .chip-button {
            background-color: #F1F5F9;
            color: #334155;
            border: 1px solid #CBD5E1;
            border-radius: 20px;
            padding: 6px 14px;
            font-size: 0.85rem;
            cursor: pointer;
            margin: 4px;
            display: inline-block;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str, badge: str = "RSG GET Assessment"):
    """Renders the executive header gradient banner."""
    st.markdown(
        f"""
        <div class="main-header">
            <span class="badge badge-purple" style="background:#4338CA; color:#E0E7FF; border:none; margin-bottom:8px;">{badge}</span>
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(title: str, value: str, subtext: str = "", badge: Optional[str] = None):
    """Renders a responsive KPI card with visual hierarchy."""
    badge_html = f'<span class="badge badge-indigo">{badge}</span>' if badge else ""
    st.markdown(
        f"""
        <div class="metric-card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div class="metric-title">{title}</div>
                {badge_html}
            </div>
            <div class="metric-value">{value}</div>
            <div class="metric-sub">{subtext}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_query_result_box(response: Dict[str, Any]):
    """Renders a structured, formatted AI Assistant answer box."""
    answer = response.get("answer", "")
    explanation = response.get("explanation", "")
    intent = response.get("intent", "general_query")
    category_name = response.get("category_name", "Supported")
    ai_mode = response.get("ai_mode", "fallback_rule")
    exec_time = response.get("execution_time_ms", 0)

    # Determine badge colors
    mode_badge = (
        '<span class="badge badge-green">🤖 Gemini LLM</span>'
        if ai_mode == "gemini"
        else (
            '<span class="badge badge-indigo">🤖 OpenAI LLM</span>'
            if ai_mode == "openai"
            else '<span class="badge badge-amber">⚡ Deterministic Rule Engine</span>'
        )
    )

    category_badge = (
        '<span class="badge badge-green">Category 1: Supported</span>'
        if response.get("category") == 1
        else (
            '<span class="badge badge-amber">Category 2: Unsupported Metric</span>'
            if response.get("category") == 2
            else (
                '<span class="badge badge-purple">Category 3: Ambiguous</span>'
                if response.get("category") == 3
                else '<span class="badge badge-rose">Category 4: Unrelated</span>'
            )
        )
    )

    st.markdown(
        f"""
        <div class="assistant-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <div>
                    {category_badge}
                    {mode_badge}
                    <span class="badge badge-indigo">Tool: <code>{intent}</code></span>
                </div>
                <span style="font-size:0.75rem; color:#64748B; font-weight:600;">⚡ {exec_time:.1f}ms</span>
            </div>
            <div class="assistant-headline">{answer}</div>
            <div class="assistant-grounded-text">
                <strong>💡 Business Insight & Grounded Analysis:</strong><br>
                {explanation}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
