# AI-Assisted Development Challenge – Engineering & AI Report

**Candidate:** Graduate Engineer Trainee (Python with Generative AI)  
**Company:** RSG Research Private Limited  
**Project:** Mini AI Business Intelligence Assistant  
**Date:** November 2026  

---

## 1. Executive Summary

This report documents the design, implementation, debugging, and verification process for the **Mini AI Business Intelligence Assistant**, developed for the RSG Research Private Limited Graduate Engineer Trainee evaluation. 

The application was built using a hybrid AI architecture combining:
- **Vectorless SQL RAG:** Grounded, deterministic analytical retrieval directly over SQLite.
- **Controlled Tool Registry & Safe Intent Routing:** Allowing LLMs to interpret intent while keeping execution strictly constrained to pre-approved, parameterized queries.
- **Multi-Provider AI Service:** Seamlessly supporting Google Gemini, OpenAI, and an offline deterministic fallback interpreter that guarantees 100% functionality without paid API keys.
- **Automated Verification:** 39 comprehensive Pytest tests covering calculations, data quality rules, edge cases, and API security.

---

## 2. AI Tools Utilized During Development

During this engineering challenge, AI development tools were leveraged across each phase:

1. **Google Antigravity Agentic IDE:**
   - **Role:** Autonomous pair programmer and architect.
   - **Contribution:** Orchestrated multi-file project scaffolding, environment setup, rapid iterative test-driven development, and automated test execution.
2. **Google Gemini API (`gemini-1.5-flash` / `gemini-2.0-flash`):**
   - **Role:** Runtime conversational understanding and grounded insight synthesizer.
   - **Contribution:** Interprets ambiguous business user questions, maps natural language expressions to structured JSON intents, and synthesizes 2-3 sentence executive business commentary.
3. **OpenAI API (`gpt-4o-mini`):**
   - **Role:** Alternative runtime LLM provider.
   - **Contribution:** Verified multi-provider adaptability via standard JSON-mode completions.

---

## 3. Key Architectural Decisions & Engineering Rationale

### A. Vectorless SQL RAG vs. Traditional Vector Embeddings
- **Decision:** Implemented relational SQL aggregation instead of vector database retrieval (e.g., Chroma, FAISS, Pinecone).
- **Rationale:** Sales data is structured and quantitative. Vector embeddings measure textual similarity; they cannot compute sums, multiply unit prices by quantities, or filter date ranges. Vector retrieval over numerical tables leads to catastrophic LLM arithmetic hallucinations. SQL guarantees 100% mathematical precision.

### B. Controlled Tool Registry vs. Unrestricted Text-to-SQL
- **Decision:** Constructed a registry of 19 approved analytical tools with parameterized handlers rather than letting the LLM generate arbitrary SQL strings.
- **Rationale:** Unrestricted Text-to-SQL introduces massive vulnerability vectors (SQL injection, accidental `DROP`/`UPDATE`, inefficient table scans) and high hallucination risk with complex schemas. A tool registry guarantees that only safe, read-only, audited aggregations run against SQLite.

### C. Audit-Preserving Data Cleaning Policy
- **Decision:** Retained all 51 rows in the SQLite database, marking ineligible records with `is_eligible = False` and explicit `exclusion_reason` strings.
- **Rationale:** Financial auditing and compliance require complete data lineage. Silently deleting records or replacing missing prices with 0 distorts operational metrics and conceals supplier/logging errors.

### D. Offline Deterministic Fallback Mechanism
- **Decision:** Built a robust regex-and-pattern based fallback intent classifier.
- **Rationale:** Production AI systems must never fail completely when external APIs experience outages, rate limits, or expired credentials. In demonstration or automated testing environments, the application works with zero configuration.

---

## 4. Problems Encountered, Root Causes & Debugging Steps

| # | Problem Encountered | Root Cause | Debugging & Resolution Steps |
|---|---|---|---|
| **1** | Host system lacked Python 3.11 and dependencies | macOS default Python was 3.9 without package managers configured | Inspected Homebrew, installed bottled `python@3.11.18`, created dedicated `venv`, and installed FastAPI, Streamlit, Pandas, SQLAlchemy, Plotly, Pytest, and Gemini SDK. |
| **2** | Dataset anomalies identified during raw CSV inspection | TXN0033 was Returned; TXN0034 had Quantity 0; TXN0051 had blank Unit Price | Built `backend/data_cleaning.py` with explicit eligibility rules: only `Completed` realized revenue; flagged quantity $\le 0$; excluded missing unit prices. Result: 48 eligible, 3 excluded. |
| **3** | `SyntaxError: f-string expression part cannot include a backslash` | In `backend/tool_registry.py`, an inline list comprehension with escaped quotes was embedded in an f-string (invalid in Python 3.11) | Extracted the formatted example strings into a local variable (`ex_str = ...`) before passing to the f-string. |
| **4** | `AttributeError: 'Settings' object has no attribute 'LOG_LEVEL'` | Pydantic Settings model was missing the `LOG_LEVEL` field referenced in `main.py` | Added `LOG_LEVEL: str = "INFO"` to `Settings` in `backend/config.py`. |
| **5** | In-memory SQLite failed with `no such table` across test calls | SQLite `:memory:` establishes a distinct blank database per connection by default | Configured `poolclass=StaticPool` in `tests/conftest.py` and monkeypatched the session factory so all connections share the exact same in-memory database. |
| **6** | Month extraction inverted order in comparison queries | `extract_months_from_text` iterated over dictionary sorted by name length (`february` before `january`) | Refactored `extract_months_from_text` using `re.finditer()` to index start positions and sort by character appearance in the sentence. |
| **7** | Query *"Compare sales across regions"* triggered ambiguous comparison | Word `"compare"` triggered the comparison block, which expected two months or products | Added explicit checks for `"region"` and `"channel"` inside the comparison branch to route directly to regional and channel analytical tools. |

---

## 5. Verification & Test Execution Results

The automated Pytest suite was executed and passed with 100% success:

```text
============================= test session starts ==============================
platform darwin -- Python 3.11.18, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/.../mini-bi-assistant
plugins: anyio-4.16.0
collected 39 items

tests/test_ai_service.py ............                                    [ 30%]
tests/test_analytics.py ...........                                      [ 58%]
tests/test_api.py .........                                              [ 82%]
tests/test_data_quality.py .......                                       [100%]

============================== 39 passed in 0.15s ==============================
```

### Coverage Highlights
- **Mandatory 5 Business Questions:** Validated to the penny against ground-truth database calculations.
- **Edge Cases & Data Quality:** Validated rejection of zero quantities, negative quantities, missing unit prices, and returned status.
- **AI 4-Category Taxonomy:** Verified supported tools, parameter extraction, ambiguous clarification, unsupported business limitations, and unrelated trivia redirection.
- **Security & Reliability:** Verified SQL injection defense, Pydantic HTTP 422 input validation, and LLM network timeout fallback.

---

## 6. What Could Be Improved With Another Development Day

If allocated an additional 24 hours of development time, the following production enhancements would be implemented:

1. **Multi-Turn Conversational Memory with Context State (Redis):**
   - Current implementation handles single-turn queries and stores chat history in the frontend.
   - An additional day would introduce a backend session cache enabling progressive drill-downs (e.g., User: *"Which region had the most sales?"* $\rightarrow$ Assistant: *"South"* $\rightarrow$ User: *"What were its top 3 products?"* using conversational anaphora resolution).
2. **Natural Language Chart Customization:**
   - Allow users to modify chart formats conversationally (e.g., *"Switch this to a horizontal bar chart"* or *"Highlight May in emerald green"*).
3. **Automated Anomaly Detection & Scheduled Alerts (Cron / APScheduler):**
   - A background worker computing daily rolling z-scores over transaction velocity, sending proactive Slack or Email notifications when unusual spikes or return rates occur.
4. **AWS Serverless Deployment Infrastructure (Terraform / AWS CDK):**
   - Infrastructure-as-code scripts provisioning an Amazon S3 bucket for CSV uploads, an AWS Lambda container running FastAPI via Mangum, and an Aurora Serverless PostgreSQL instance.
5. **Role-Based Access Control (RBAC & JWT):**
   - User authentication ensuring regional sales managers only see transactions corresponding to their assigned territory (`region == user.region`).
