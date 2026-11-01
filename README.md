# Mini AI Business Intelligence Assistant
### RSG Research Private Limited – Graduate Engineer Trainee (Python with Generative AI) Selection Challenge

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Google GenAI](https://img.shields.io/badge/Google%20GenAI-SDK%202.0%2B-4285F4.svg)](https://cloud.google.com/vertex-ai/generative-ai/docs)
[![SQLite](https://img.shields.io/badge/Database-SQLite%203-003B57.svg)](https://www.sqlite.org/)
[![Streamlit](https://img.shields.io/badge/Frontend-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![Plotly](https://img.shields.io/badge/Charts-Plotly-3F4F75.svg)](https://plotly.com/)
[![ReportLab](https://img.shields.io/badge/Reports-ReportLab%20PDF-E11D48.svg)](https://www.reportlab.com/)
[![Pytest](https://img.shields.io/badge/Tests-66%20Passed-brightgreen.svg)](https://docs.pytest.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 1. Project Overview & Business Problem

In enterprise environments, business executives and operational managers frequently need immediate answers to critical sales performance questions:
- *"What is our total net sales revenue?"*
- *"Which product generated the highest revenue?"*
- *"What is our monthly sales trajectory?"*
- *"How did sales change between March and May?"*
- *"Compare it with North region."* (Multi-turn conversational follow-up)

Traditionally, answering these questions requires either writing complex SQL queries or waiting days for business intelligence teams to build custom reports.

The **Mini AI Business Intelligence Assistant** bridges this gap by enabling non-technical stakeholders to ask questions in natural language and receive **100% mathematically accurate, database-backed answers**, interactive Plotly charts, executive PDF/CSV exports, ML-driven forward projections, and evidence-grounded business insights.

### Key Architectural Principle: Vectorless Structured RAG
Unlike traditional document-based RAG that relies on approximate vector embeddings and frequently suffers from LLM arithmetic hallucinations, this system employs **Vectorless SQL RAG with Decoupled Tool Calling**:
1. Google's modern `google-genai` SDK performs **Intent Classification & Parameter Extraction** via **Native Structured Outputs**.
2. Aggregations (`SUM`, `COUNT`, `AVG`, `GROUP BY`) execute directly on an **indexed SQLite database** using pre-compiled SQLAlchemy ORM queries.
3. Verified numerical results are passed back to the LLM to generate **evidence-grounded business commentary**.
4. The system operates with **zero arithmetic hallucinations**, eliminates SQL injection vectors, and provides a deterministic fallback router for 100% offline availability.

---

## 2. Technology Stack

| Layer | Technology | Version | Engineering Rationale |
|---|---|---|---|
| **Language** | Python | 3.11+ | Modern typing, high performance, robust ecosystem |
| **Backend API** | FastAPI | 0.110+ | Ultra-fast async execution, automatic OpenAPI Swagger docs, dependency injection |
| **Data Validation** | Pydantic v2 | 2.6+ | High-speed Rust-backed validation and typed request/response contracts |
| **Database** | SQLite 3 | Embedded | Serverless, zero-config relational storage, portable across evaluation environments |
| **ORM & SQL** | SQLAlchemy | 2.0+ | Parameterized SQL compilation, indexing, schema safety, SQL injection prevention |
| **Data Processing**| Pandas & NumPy | 2.2+ | Tabular manipulation, flexible date normalization, and quality audits |
| **Generative AI** | Google Gemini / OpenAI | Configurable | Natural language understanding, slot filling, and grounded insight synthesis |
| **AI Fallback** | Custom Regex Router | Built-in | 100% deterministic offline execution without requiring paid API keys |
| **Frontend** | Streamlit | 1.32+ | Interactive executive dashboard, chat conversation, and responsive layout |
| **Visualizations** | Plotly | 5.20+ | Interactive area, bar, and donut charts with custom tooltips |
| **Automated Tests**| Pytest | 8.1+ | Hermetic test suite running across in-memory SQLite instances (39 tests) |

---

## 3. Ground Truth Analytics & The 5 Mandatory Questions

All figures are calculated directly from active database records using the company-supplied dataset (`sales.csv`):

### Realized Revenue Policy:
$$\text{Gross Revenue} = \text{Quantity} \times \text{Unit Price}$$
$$\text{Net Revenue} = \text{Gross Revenue} - \text{Discount Amount}$$
Realized revenue KPIs are calculated strictly from **Eligible Completed** transactions. Excluded records are preserved in the database for auditing and tracking.

### Ground Truth Verified Results:
| # | Mandatory Question | Canonical Intent | Ground Truth Result | Supporting Context |
|---|---|---|---|---|
| **A** | **Total Revenue** | `total_revenue` | **₹1,439,200.00** Net Sales | Gross: ₹1,443,700.00; Discounts: ₹4,500.00; 48 eligible orders; 3 excluded records |
| **B** | **Highest-Revenue Product** | `top_revenue_product` | **Monitor** (₹473,000.00) | 50 units sold across 10 orders; 2nd: Desk (₹222,500.00) |
| **C** | **Monthly Revenue Trend** | `monthly_revenue_trend` | **May 2026 Peak** (₹318,500.00) | Jan: ₹210,250 \| Feb: ₹234,600 \| Mar: ₹223,900 \| Apr: ₹240,700 \| May: ₹318,500 \| Jun: ₹211,250 |
| **D** | **Highest-Revenue Region** | `top_revenue_region` | **South Region** (₹411,200.00) | 182 units sold; 28.6% market share; 2nd: North (₹384,450.00) |
| **E** | **Comparison Between Two Months** | `monthly_comparison` | **+₹24,350.00 (+11.58%)** | Jan (₹210,250) vs Feb (₹234,600); Growth direction: Increased |

---

## 4. Dataset Inspection & Data Cleaning Policy

The dataset contains 51 transaction records spanning January to June 2026. A strict, documented data cleaning and eligibility policy was implemented:

### Excluded Transactions Audit Trail
| Transaction ID | Date | Product | Qty | Unit Price | Status | Reason for Exclusion |
|---|---|---|---|---|---|---|
| `TXN0033` | 2026-04-26 | Monitor | 2 | 9,500 | Returned | Status is `'Returned'`. Excluded from realized net sales revenue. |
| `TXN0034` | 2026-04-28 | Keyboard | 0 | 900 | Completed | Quantity is `0`. Flagged as invalid/suspicious order volume. |
| `TXN0051` | 2026-06-28 | Laptop Stand | 5 | *blank* | Completed | Missing unit price. Excluded to prevent inventing numerical data. |

- **Total Imported Rows:** 51
- **Eligible Completed Orders:** 48
- **Ineligible / Suspicious Records:** 3
- **Data Cleanliness Score:** 94.12%
- **Audit Preservation:** Ineligible records are **never silently deleted or mutated with fake zeros**. They are preserved in SQLite with `is_eligible = False` and explicit `exclusion_reason` strings for complete governance transparency.

---

## 5. Four-Category AI Question Taxonomy

To prevent hallucinations, out-of-domain answers, and execution errors, every query is classified into one of 4 categories:

```
User Natural Language Question
              |
              v
     Intent Classification
              |
    +---------+---------+-------------------+
    |                   |                   |
    v                   v                   v
Category 1          Category 2          Category 3          Category 4
Supported           Related             Ambiguous           Unrelated
Analytical Tool     Unsupported         Missing Params      Out-of-Domain
    |                   |                   |                   |
    v                   v                   v                   v
Execute Tool        Explain Data        Ask User for        Polite
on SQLite DB        Limitations         Clarification       Redirection
```

1. **Category 1 – Supported Questions:** Mapped to one of 19 approved tools in the registry (e.g., Total Revenue, Top Product, Monthly Trend, Top Region, Channel Split, Category Share).
2. **Category 2 – Related Unsupported Questions:** Questions on metrics not in the dataset (e.g., *"What is our net profit margin?"*). The assistant explains that cost/COGS data is absent and suggests available analyses.
3. **Category 3 – Ambiguous Questions:** Queries lacking required parameters (e.g., *"Compare revenue"*). The assistant halts execution and asks: *"Which two months would you like me to compare?"*
4. **Category 4 – Unrelated Questions:** General trivia or out-of-domain questions (e.g., *"Who is the Prime Minister of India?"*). The assistant politely redirects the user to sales intelligence.

---

## 6. Approved Analytical Tools Registry (Extensibility)

The application implements a decoupled `ToolRegistry` containing 19 pre-approved analytical functions:

1. `total_revenue`: Gross revenue, net revenue, discounts, order counts.
2. `top_revenue_product`: Highest net revenue product ranking.
3. `monthly_revenue_trend`: Chronological 6-month trajectory and peak month.
4. `top_revenue_region`: Regional revenue distribution and market share.
5. `monthly_comparison`: Head-to-head two-month variance and percentage growth.
6. `top_quantity_product`: Best-selling product by units sold (Wireless Mouse: 228 units).
7. `lowest_quantity_product`: Lowest volume product (Desk: 18 units).
8. `category_revenue`: Category breakdown (Accessories ₹533K, Electronics ₹473K, Furniture ₹433K).
9. `channel_comparison`: Online (51.9%) vs Retail (48.1%) sales split.
10. `average_transaction_value`: Average order value across completed orders (₹29,983.33).
11. `regional_transaction_counts`: Order frequency by region.
12. `status_breakdown`: Total orders by status (Completed vs Returned).
13. `discount_analysis`: Total discounts (₹4,500) and discount rate (0.31%).
14. `top_5_products`: Top 5 products ranked by net revenue.
15. `product_comparison`: Head-to-head comparison of two specific products.

---

## 7. Project Structure

```text
mini-bi-assistant/
├── backend/
│   ├── __init__.py           # Backend package initialization
│   ├── config.py             # Strongly-typed Pydantic settings & env loading
│   ├── database.py           # SQLite connection, session factory & health check
│   ├── models.py             # SQLAlchemy ORM models (SalesTransaction, DataQualityLog)
│   ├── schemas.py            # Pydantic request/response schemas & taxonomy enums
│   ├── data_cleaning.py      # Business eligibility rules & date normalization
│   ├── data_loader.py        # CSV ingestion pipeline & database synchronization
│   ├── analytics.py          # Deterministic SQL analytical aggregation functions
│   ├── tool_registry.py      # Centralized allowlist registry of approved tools
│   ├── intent_router.py      # 4-category deterministic rule router & fallback
│   ├── ai_service.py         # Multi-provider LLM service & grounded synthesis
│   ├── exceptions.py         # Custom domain-specific exception classes
│   └── main.py               # FastAPI application, CORS & RESTful endpoints
├── frontend/
│   ├── __init__.py           # Frontend package initialization
│   ├── app.py                # Main Streamlit dashboard application
│   ├── components.py         # Styled HTML/CSS metric cards & answer boxes
│   └── charts.py             # Interactive Plotly chart builders
├── data/
│   ├── sales.csv             # Working copy of company sales dataset
│   └── bi_assistant.db       # Generated SQLite database file
├── tests/
│   ├── __init__.py           # Tests package initialization
│   ├── conftest.py           # In-memory SQLite fixtures & TestClient configuration
│   ├── test_analytics.py     # Unit tests for all mathematical calculations
│   ├── test_data_quality.py  # Tests for eligibility, exclusions & audit counts
│   ├── test_ai_service.py    # Tests for 4-category routing & LLM fallbacks
│   └── test_api.py           # Integration tests for FastAPI endpoints & security
├── docs/
│   ├── architecture.md       # Comprehensive system architecture & Mermaid diagrams
│   ├── ai_development_report.md # AI usage, debugging steps & engineering report
│   └── interview_prep.md     # 40+ technical Q&As, presentation script & defense
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules for Python, SQLite & venv
├── requirements.txt          # Python package dependencies
├── run.sh                    # Unified startup and test execution script
└── README.md                 # Primary project documentation
```

---

## 8. Installation & Execution Guide

### Prerequisites
- macOS, Linux, or Windows with WSL
- Python 3.11 or higher
- Git

### Quick Setup

```bash
# 1. Clone or navigate to the project directory
cd mini-bi-assistant

# 2. Run the automated runner script (creates venv and installs dependencies)
./run.sh all
```

### Manual Step-by-Step Setup

```bash
# 1. Create a Python 3.11 virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables (optional)
cp .env.example .env
# Edit .env to add your GEMINI_API_KEY or OPENAI_API_KEY if desired.
# Note: The application runs 100% locally in demonstration mode without any paid API key!

# 4. Start the FastAPI backend server
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# 5. In a second terminal, start the Streamlit frontend
streamlit run frontend/app.py --server.port 8501
```

- **Frontend Dashboard:** [http://127.0.0.1:8501](http://127.0.0.1:8501)
- **Backend API & Swagger Docs:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 9. Automated Testing & Verification

The test suite contains **66 comprehensive automated tests** with zero external network dependencies, verifying analytics correctness, API contracts, data quality governance, multi-turn memory, ML forecasting, and RBAC:

```bash
# Run the complete test suite
./run.sh test

# Or using pytest directly
venv/bin/pytest -v
```

### Verified Test Breakdown (66 Tests Passing):
- **AI Service & Conversational Memory (`tests/test_ai_service.py`):** 15 tests (Phrasings, multi-turn follow-ups, antecedent resolution, fallback router, edge cases).
- **Core Analytics Engine (`tests/test_analytics.py`):** 11 tests (Total revenue, product rankings, monthly trends, regional comparisons, discounts, channels).
- **REST API Endpoints (`tests/test_api.py`):** 13 tests (Health checks, asking questions, validation errors, duplicate detection, dataset reset).
- **Data Quality & Audit Policy (`tests/test_data_quality.py`):** 7 tests (Status exclusions, zero quantity, negative values, missing prices, date formats).
- **Report & Data Exporters (`tests/test_exports.py`):** 6 tests (ReportLab PDF generation, transactions CSV, eligible-only CSV, summary CSVs).
- **Machine Learning Forecasting (`tests/test_forecasting.py`):** 5 tests (OLS linear regression, Holt's smoothing, out-of-sample MAE/RMSE/MAPE, confidence interval consistency, scientific disclosures).
- **Role-Based Access Control (`tests/test_rbac.py`):** 9 tests (Password hashing, login tokens, permission enforcement, 403 Forbidden checks, backward compatibility).

```text
======================== 66 passed, 1 warning in 0.62s =========================
```

---

## 10. Sample Demonstration Questions

Try these sample natural-language queries in the assistant:

### Five Core Mandatory Questions
1. *"What is the total revenue?"* (or *"How much money did we make?"*)
2. *"Which product generated the highest revenue?"* (or *"Which product made the most money?"*)
3. *"What is the monthly revenue trend?"* (or *"Show revenue month by month"*)
4. *"Which region generated the highest revenue?"* (or *"Compare sales across regions"*)
5. *"Compare January and February."* (or *"How did sales change between March and May?"*)

### Additional Analytical Capabilities
6. *"Which product sold the highest quantity?"*
7. *"Compare Online and Retail sales channels."*
8. *"What is the revenue breakdown by category?"*
9. *"How much discount did we give to customers?"*
10. *"What is our average transaction value?"*

### Category Handling & Safety Demonstrations
11. **Ambiguous Query:** *"Compare revenue"* $\rightarrow$ AI asks: *"Which two months would you like me to compare?"*
12. **Unsupported Business Metric:** *"What is our net profit margin?"* $\rightarrow$ AI explains that cost/COGS data is absent and suggests available analyses.
13. **Unrelated Trivia:** *"Who is the Prime Minister of India?"* $\rightarrow$ AI politely explains its specialization in sales intelligence.
14. **SQL Injection Defense:** *"What is total revenue'; DROP TABLE sales_transactions; --"* $\rightarrow$ Safely executed without table corruption.

---

## 11. Security Considerations

- **Parameterized Queries:** All SQL queries are executed using SQLAlchemy parameterized bindings. Direct string concatenation into SQL statements is prohibited.
- **Controlled Tool Registry:** The LLM selects canonical tool names; the backend executes pre-compiled handlers. Raw SQL generation by the LLM is prohibited.
- **Read-Only Analytics:** Analytical handlers execute `SELECT` queries only. Destructive database operations (`DROP`, `DELETE`, `UPDATE`) are impossible through the conversational interface.
- **Secure File Ingestion:** CSV upload validates `.csv` extensions, enforces a 10MB maximum file size, and parses contents safely before database writes.
- **Sensitive Credentials Protection:** API keys and database connection secrets are loaded via environment variables and excluded from Git commits via `.gitignore`.

---

## 12. Interview Preparation & Architectural Deliverables

For complete technical interview preparation, consult the companion documents in `docs/`:
- **[System Architecture](docs/architecture.md):** Deep-dive architectural explanations, Mermaid diagrams, Vectorless RAG concepts, and AWS deployment readiness.
- **[Architectural Evaluation: Multi-Agent vs. Tool Calling](docs/architecture_evaluation.md):** In-depth technical comparison of Single-Agent Tool Calling vs. Multi-Agent Orchestration (CrewAI/AutoGen).
- **[Data Cleaning & Audit Policy](docs/data_cleaning_policy.md):** Authoritative single-source-of-truth reconciliation of 51 raw vs. 48 eligible records (realized revenue: ₹1,439,200.00).
- **[AI Development Report](docs/ai_development_report.md):** AI tools utilized, engineering decisions, problems encountered, and debugging steps.
- **[Interview Masterclass](docs/interview_prep.md):** 50+ technical interview Q&As, candidate demonstration script, and live-coding modification walkthroughs.
