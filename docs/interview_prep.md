# RSG Research Private Limited – GET Technical Interview Guide & Preparation Masterclass

**Target Role:** Graduate Engineer Trainee (Python with Generative AI)  
**Project:** Mini AI Business Intelligence Assistant  
**Audience:** B.Tech Computer Science Candidate preparing for RSG Evaluation Panel  

---

## TABLE OF CONTENTS
1. [Core Component Deep-Dives (The "What, Why, How, Alternatives" Framework)](#1-core-component-deep-dives)
2. [Demonstration Script for Technical Evaluation](#2-demonstration-script-for-technical-evaluation)
3. [40+ Project-Specific Technical Interview Questions & Answers](#3-40-project-specific-technical-interview-questions--answers)
   - Python Core & OOP Questions
   - Database & SQL Aggregation Questions
   - Generative AI, LLMs & Structured Output Questions
   - Agentic AI & Tool-Calling Architecture Questions
   - RAG vs. Vectorless RAG Questions
   - FastAPI & Backend Engineering Questions
   - Data Engineering & Cleaning Questions
   - AWS Cloud & Deployment Questions
   - Debugging & Problem-Solving Scenarios
4. [Practical Live-Coding Modifications an Interviewer May Request](#4-practical-live-coding-modifications-an-interviewer-may-request)

---

# 1. CORE COMPONENT DEEP-DIVES

Every major architectural component is analyzed using the **6-Point Engineering Defense Matrix**:
- **What it does**
- **Why it is required**
- **How it works**
- **How the code implements it**
- **What alternatives exist**
- **Why our approach is appropriate**

---

### Component 1: Ingestion & Business Eligibility Pipeline (`backend/data_cleaning.py` & `data_loader.py`)
- **What it does:** Reads raw CSV records, validates types, normalizes dates to ISO format (`YYYY-MM-DD`), calculates gross and net revenue, and tags records as eligible or excluded without silently dropping data.
- **Why it is required:** Real-world datasets contain anomalies (e.g., `TXN0033` is Returned, `TXN0034` has Quantity 0, `TXN0051` has missing unit price). Silently replacing values with zero or dropping rows distorts sales KPIs and violates audit compliance.
- **How it works:** Iterates through records, parses dates using flexible format matchers, validates positive quantities and positive prices, checks transaction status, and computes $\text{Net Revenue} = \text{Quantity} \times \text{Unit Price} - \text{Discount Amount}$.
- **How the code implements it:** In `clean_and_validate_record()`, an array of `reasons` accumulates any rule violations. If `len(reasons) > 0`, `is_eligible = False`. Both valid and invalid rows are saved to SQLite, preserving complete audit lineage.
- **Alternatives:** 
  1. *Pandas `df.dropna()`*: Silently drops data, losing visibility into data quality failures.
  2. *Default zero-fill (`df.fillna(0)`)*: Distorts averages and masks broken upstream logging.
- **Why our approach is appropriate:** It satisfies strict corporate financial audit standards. Management can see exactly why 3 records were excluded while computing realized revenue from the 48 valid orders.

---

### Component 2: Vectorless Structured RAG & SQLite Engine (`backend/analytics.py` & `models.py`)
- **What it does:** Performs exact, deterministic numerical aggregations (`SUM`, `COUNT`, `AVG`, `GROUP BY`) directly on indexed SQLite database tables.
- **Why it is required:** LLMs are notorious for mathematical hallucinations when performing multi-row arithmetic. Real-world BI requires 100% precision to the penny.
- **How it works:** SQLAlchemy ORM compiles high-level Python queries into parameterized SQL. Aggregations filter strictly on `is_eligible == True`.
- **How the code implements it:** Functions like `get_total_revenue()`, `get_highest_revenue_product()`, and `compare_two_months()` execute SQL queries and return typed Python dictionaries with numerical results and supporting tables.
- **Alternatives:**
  1. *Traditional Vector RAG (Chroma/FAISS)*: Chunks CSV rows into text, embeds them, and asks the LLM to sum retrieved chunks. Fails completely because vector similarity cannot compute mathematical sums.
  2. *Unrestricted Text-to-SQL*: Prompting an LLM to generate raw SQL strings. Highly vulnerable to SQL injection, syntax errors, and hallucinated table names.
- **Why our approach is appropriate:** Vectorless RAG treats SQLite as the deterministic retrieval engine. The LLM receives pre-computed, verified numbers and generates grounded narrative explanations.

---

### Component 3: Approved Tool Registry & Safe AI Execution (`backend/tool_registry.py`)
- **What it does:** Maintains an allowlist registry of 19 approved analytical tools with metadata, parameter definitions, and execution handlers.
- **Why it is required:** Decouples AI reasoning from database execution. The LLM acts as an intent selector; the backend controls execution.
- **How it works:** Each tool registers its canonical name, parameter schema, SQL query description, and callable function. When the AI router returns an intent, the registry looks up the tool, validates parameters, and executes the handler.
- **How the code implements it:** The `ToolRegistry` class stores `ToolDefinition` dataclasses. The `.execute(tool_name, db, params)` method safely invokes the handler and catches runtime exceptions.
- **Alternatives:**
  1. *Hardcoded `if/elif` statements*: Inflexible and difficult to extend.
  2. *Autonomous Agent Multi-Step Loop (AutoGPT style)*: Overengineered for tabular reporting, slow, and non-deterministic.
- **Why our approach is appropriate:** Adding a new BI feature takes 5 lines of code: register a new tool definition without touching the API, router, or frontend.

---

### Component 4: Four-Category Intent Router & Fallback (`backend/intent_router.py` & `ai_service.py`)
- **What it does:** Classifies natural-language user queries into:
  - *Category 1 (Supported)*
  - *Category 2 (Related Unsupported: profit, churn, inventory)*
  - *Category 3 (Ambiguous: comparison without months)*
  - *Category 4 (Unrelated: trivia, politics)*
- **Why it is required:** Business users ask a wide variety of questions. An intelligent assistant must handle out-of-scope, missing-parameter, and unsupported queries gracefully rather than crashing or inventing data.
- **How it works:** When API credentials exist, an LLM evaluates the query against the tool catalog and outputs structured JSON. If credentials are missing or the API times out, a deterministic regex/pattern fallback classifier takes over seamlessly.
- **How the code implements it:** `fallback_classify_intent()` inspects query tokens, handles comparison ambiguity, checks out-of-domain patterns, extracts parameters (like normalized month strings), and returns a Pydantic `IntentInterpretation`.
- **Alternatives:**
  1. *Pure Keyword Matching*: Fails on complex phrasing like *"How much money did we make in Q1?"*
  2. *LLM-Only without Fallback*: Crashes during network failure or quota exhaustion.
- **Why our approach is appropriate:** Ensures production-grade high availability. Automated tests and offline evaluations run at zero cost without paid API keys, while genuine LLM intelligence activates when configured.

---

### Component 5: Grounded Business Insight Synthesizer (`backend/ai_service.py`)
- **What it does:** Takes verified database numbers and produces a 2-to-3 sentence executive business summary.
- **Why it is required:** Raw numbers alone do not provide actionable business context. Executives need both the numbers and what they mean.
- **How it works:** Injects exact database metrics into the prompt with a strict system constraint: *"Never invent numbers. State the primary figure in the first sentence and provide business context in the second."*
- **How the code implements it:** `generate_grounded_explanation()` passes metrics to Gemini/OpenAI. If offline, `_build_deterministic_explanation()` uses templated narrative rules so the user always receives professional business commentary.
- **Alternatives:** Allowing the LLM to calculate numbers directly in the prompt (guaranteed arithmetic hallucinations).
- **Why our approach is appropriate:** Guarantees zero arithmetic hallucinations while providing rich natural language answers.

---

### Component 6: Modern Google GenAI SDK Migration & Structured Outputs (`backend/ai_service.py`)
- **What it does:** Migrated from the deprecated legacy `google.generativeai` library to Google's official modern `google-genai` SDK (`genai.Client`). Enforces strict JSON schemas using `response_schema=IntentInterpretation`.
- **Why it is required:** The legacy SDK is deprecated by Google. Modern `google-genai` supports native structured output enforcement at the token decoding level, eliminating regex JSON extraction failures and syntax hallucination.
- **How it works:** Instantiates `genai.Client(api_key=..., http_options=types.HttpOptions(timeout=15000))`. The model directly samples tokens constrained to the Pydantic schema of `IntentInterpretation`.
- **Alternatives:**
  1. *Unconstrained markdown JSON prompting*: Prone to markdown ticks (```json), conversational chatter, and malformed trailing commas.
  2. *Legacy SDK `genai.GenerativeModel`*: Deprecated, throws warnings, and lacks native typing integration.
- **Why our approach is appropriate:** Production-grade compliance with Google's active SDK guidelines, eliminating deprecation warnings and guaranteeing schema conformity.

---

### Component 7: Multi-Turn Conversational Memory & Antecedent Resolution (`backend/conversation.py`)
- **What it does:** Tracks session state across multi-turn user dialogs. Resolves ambiguous pronoun antecedents (e.g., *"What about its monthly trend?"* or *"Compare it with North"*).
- **Why it is required:** Real executives converse iteratively. Single-turn stateless assistants force users to repeat full entity names on every question.
- **How it works:** Maintains an in-memory session registry (`ConversationManager`). When a query contains demonstrative pronouns ("it", "its", "that product", "this region"), `resolve_context()` extracts the entity from the previous turn (`last_product`, `last_region`, `last_tool`) and rewires parameters before intent routing.
- **How the code implements it:** `ConversationSession` logs query turns, extracted parameters, and executed tools. `resolve_context(query, session_id)` checks patterns and returns an enriched query and injected parameters.
- **Alternatives:** Full chat history injection into every LLM prompt (wastes tokens, increases latency, and causes the model to drift from the current question).
- **Why our approach is appropriate:** Targeted antecedent resolution is fast, deterministic, uses zero extra tokens, and guarantees precise entity continuity.

---

### Component 8: Classical Machine Learning Sales Forecasting (`backend/forecasting.py`)
- **What it does:** Produces forward-looking monthly net revenue projections (3-6 months ahead) using Ordinary Least Squares (OLS) Linear Regression and Holt's Linear Exponential Smoothing.
- **Why it is required:** Business stakeholders need forward projections to plan inventory and corporate procurement cycles.
- **How it works:** Aggregates monthly net revenue chronologically. Evaluates models using an out-of-sample chronological split (Jan–Apr train, May–Jun test). Calculates MAE, RMSE, and MAPE. Dynamically selects the model with lower test RMSE. Computes 80% and 95% statistical confidence bounds based on residual standard deviation.
- **Scientific Honesty & Epistemic Limitations:** The dataset contains only 6 monthly aggregates (January to June 2026). Standard time series (e.g., seasonal ARIMA) requires 24-36 months to capture annual seasonality. This module is explicitly framed as an algorithmic proof-of-concept for technical evaluation.
- **Alternatives:** Deep learning (LSTM / Transformers) or complex Prophet models (severely overfit on N=6 points).
- **Why our approach is appropriate:** Demonstrates rigorous ML fundamentals, strict train/test discipline, metric quantification, and epistemic humility.

---

### Component 9: Executive PDF & Audit CSV Exporter (`backend/report_exporter.py`)
- **What it does:** Generates executive-grade PDF reports (ReportLab) and downloadable CSV files directly from the database.
- **Why it is required:** Enterprise BI users need downloadable artifacts for executive presentations and compliance audits.
- **How it works:** Compiles high-resolution PDF documents with corporate typography, executive KPI matrices, product revenue rankings, regional breakdowns, monthly trends, and an explicit data-quality exclusions audit trail.
- **Alternatives:** Client-side HTML print / `window.print()` (inconsistent across browsers, lacks automated formatting).
- **Why our approach is appropriate:** Generates binary-level PDF artifacts server-side with zero external headless browser dependencies.

---

### Component 10: Role-Based Access Control & Security (`backend/auth.py`)
- **What it does:** Restricts sensitive operations using a 3-tier RBAC security model:
  - `Admin`: Full permissions (CSV upload, dataset reset, LLM key configuration, querying, exports).
  - `Analyst`: Analytical permissions (Querying, deep-dive, PDF/CSV exports).
  - `Viewer`: Read-only access (Dashboard KPIs and charts only).
- **Why it is required:** Enterprise datasets require least-privilege security. Unauthenticated users must not upload corrupted CSVs or alter system credentials.
- **How it works:** Uses standard-library PBKDF2-HMAC-SHA256 password hashing with static salts. Fast HTTP header resolution (`X-User-Role` or `Authorization: Bearer <token>`). Guarded via FastAPI dependencies (`require_admin`, `require_analyst_or_admin`).
- **Alternatives:** Plaintext passwords or external auth SaaS (Auth0/Firebase) which adds network latency and external account requirements.
- **Why our approach is appropriate:** Clean, self-contained, cryptographically sound, and verifiable live via the Streamlit sidebar role switcher.

---

# 2. DEMONSTRATION SCRIPT FOR TECHNICAL EVALUATION

Use this step-by-step presentation script during your interview demonstration:

### Step 1: Project Introduction (1 Minute)
> *"Good morning / afternoon members of the evaluation panel. My name is [Your Name], and I am presenting the Mini AI Business Intelligence Assistant developed for the RSG GET selection challenge.*
>
> *The objective of this application is to bridge the gap between non-technical business users and complex relational databases. Instead of writing SQL queries, users ask questions in natural language and receive mathematically accurate, database-backed answers, interactive charts, and grounded business insights.*
>
> *I designed this application around a three-tier decoupled architecture: a FastAPI backend, an SQLite relational database utilizing Vectorless Structured RAG, a safe tool-calling orchestration engine, and an executive Streamlit dashboard."*

### Step 2: Data Quality & Governance Demonstration (1.5 Minutes)
> *"Before writing analytics, I performed data profiling on the company-supplied sales dataset. In Tab 4 (Data Quality & Audit), you can see the results of our documented eligibility policy:*
> - *Total imported rows: 51*
> - *Eligible completed transactions: 48*
> - *Excluded rows: 3 (Cleanliness score: 94.12%)*
>
> *Rather than silently dropping rows with Pandas or filling missing values with fake zeros, our pipeline preserves complete data lineage. TXN0033 was excluded because its status is 'Returned'. TXN0034 was flagged for zero quantity. TXN0051 had a blank unit price. Realized net revenue is calculated strictly from the 48 eligible completed transactions: Gross Revenue minus Discounts."*

### Step 3: Demonstrating the 5 Mandatory Business Questions (2 Minutes)
> *"Now I will demonstrate the five mandatory core business questions:*
> 1. **Total Revenue:** Clicking 'What is the total revenue?' returns ₹1,439,200.00 realized net revenue across 48 orders, with ₹4,500 in discounts.
> 2. **Highest-Revenue Product:** Asking 'Which product generated the highest revenue?' identifies Monitor at ₹473,000.00 (50 units sold), accompanied by an interactive Plotly ranking chart.
> 3. **Monthly Trend:** 'What is the monthly revenue trend?' displays our 6-month trajectory, automatically annotating May 2026 as the peak revenue month at ₹318,500.00.
> 4. **Highest-Revenue Region:** 'Which region generated the highest revenue?' identifies the South region at ₹411,200.00 (28.6% market share).
> 5. **Month-to-Month Comparison:** Asking 'Compare January and February' triggers our comparative analytical tool, calculating an absolute growth of +₹24,350.00 (+11.58%) with a head-to-head bar chart."*

### Step 4: AI Extensibility & 4-Category Handling (2 Minutes)
> *"A key requirement was extensibility beyond five exact sentences. The assistant supports a 4-category taxonomy:*
> - **Extensible Phrasings:** Asking 'How much money did we make?' or 'Calculate our total net sales' maps to the exact same analytical tool without requiring rigid keywords.
> - **Category 2 (Unsupported Metric):** Asking 'What is our net profit margin?' triggers a polite explanation that the dataset contains sales and discount data but lacks product cost or COGS information, while suggesting related available analyses.
> - **Category 3 (Ambiguous Query):** Entering 'Compare revenue' prompts the AI to ask: 'Which two months would you like me to compare?'
> - **Category 4 (Unrelated Query):** Asking 'Who is the Prime Minister of India?' triggers an immediate polite redirection explaining that the assistant specializes in sales business intelligence."*

### Step 5: Architecture, Testing & Code Quality (1.5 Minutes)
> *"Under the hood:
> - **Safe Tool Calling:** The LLM never writes raw SQL. It requests tools from our registry; our backend validates parameters and executes parameterized SQL.
> - **Grounded Generation:** The numbers come directly from SQLite; the LLM only generates narrative explanations grounded on those figures.
> - **Automated Testing:** We have implemented 39 automated Pytest tests covering analytics, data quality, API security, SQL injection defense, and LLM fallbacks. All 39 tests pass with 100% success.*
>
> *I am ready to walk through the source code or make any live modifications you would like to see."*

---

# 3. 40+ PROJECT-SPECIFIC TECHNICAL INTERVIEW QUESTIONS & ANSWERS

### Python Core & OOP Questions

#### Q1: Why did you structure the application using modular Python packages instead of a single script?
**Answer:** Modular programming enforces separation of concerns. `config.py` manages environment settings, `models.py` defines the database schema, `data_cleaning.py` encapsulates validation rules, `analytics.py` executes SQL calculations, `tool_registry.py` handles execution safety, and `main.py` serves API endpoints. This modularity allows individual components to be unit-tested in isolation, reused across different interfaces (FastAPI, Streamlit, CLI), and easily maintained by a team.

#### Q2: What is the difference between a shallow copy and a deep copy in Python, and where might that matter in analytics?
**Answer:** A shallow copy (`copy.copy()`) creates a new container object but inserts references to the objects found in the original. A deep copy (`copy.deepcopy()`) recursively copies all objects found within the original. In our analytics pipeline, when modifying nested dictionaries of query parameters or supporting data rows, a deep copy ensures that mutating intermediate metrics does not inadvertently alter the raw cached dataset.

#### Q3: How do Python type hints and Pydantic validation improve code reliability?
**Answer:** Type hints document expected data types for static analyzers (`mypy`) and IDE autocompletion. Pydantic takes this further by performing runtime validation and coercion. When user input arrives at `/api/ask`, Pydantic validates that `question` is a non-empty string under 500 characters, automatically raising an HTTP 422 error if invalid, protecting backend functions from `TypeError` or `NoneType` attribute crashes.

#### Q4: How does Python's Global Interpreter Lock (GIL) affect FastAPI and background workers?
**Answer:** The GIL ensures only one native thread executes Python bytecode at a time. However, FastAPI utilizes asynchronous I/O (`async def`) powered by `uvloop`. For I/O-bound tasks (database queries, network requests to Gemini/OpenAI), threads release the GIL while waiting for socket responses. For CPU-bound tasks, Python 3.12+ subinterpreters or `ProcessPoolExecutor` can be used.

#### Q5: Explain the difference between `@classmethod`, `@staticmethod`, and instance methods in Python.
**Answer:** Instance methods take `self` as their first argument and can access/modify instance state. `@classmethod` takes `cls` as its first argument and can access/modify class-level state (used in Pydantic for `@field_validator`). `@staticmethod` takes neither `self` nor `cls`; it behaves like an ordinary function namespaced inside a class for logical grouping.

---

### Database & SQL Aggregation Questions

#### Q6: Explain the difference between `WHERE` and `HAVING` in SQL.
**Answer:** `WHERE` filters individual rows **before** any aggregations are calculated. `HAVING` filters aggregated group records **after** the `GROUP BY` clause has been evaluated. For example:
```sql
SELECT product, SUM(net_revenue) AS total_rev
FROM sales_transactions
WHERE is_eligible = 1
GROUP BY product
HAVING total_rev > 100000;
```

#### Q7: Why did you create indexes on `order_date`, `product`, and `region` in SQLite?
**Answer:** Without an index, SQLite must perform a full table scan ($O(N)$ complexity) across all rows to group or filter by product or region. Creating B-tree indexes reduces search and grouping complexity to $O(\log N)$, ensuring sub-millisecond query execution even if the dataset grows to millions of transactions.

#### Q8: How did you implement month-to-month comparison in SQL, and how do you handle a zero baseline?
**Answer:** In SQLite, we extract the year and month using `strftime('%Y-%m', order_date)`. We aggregate `SUM(net_revenue)` filtered by `WHERE month IN (:m1, :m2)`. In Python, the percentage difference is:
$$\text{Percentage Difference} = \frac{\text{Rev}_2 - \text{Rev}_1}{\text{Rev}_1} \times 100$$
If $\text{Rev}_1 = 0$, dividing by zero raises a `ZeroDivisionError`. The code checks `if rev_1 > 0: pct = ...` and safely assigns `100.0%` if $\text{Rev}_2 > 0$ or `0.0%` if both are zero.

#### Q9: What is the difference between `gross_revenue` and `net_revenue` in your schema?
**Answer:**
- $\text{Gross Revenue} = \text{Quantity} \times \text{Unit Price}$
- $\text{Net Revenue} = \text{Gross Revenue} - \text{Discount Amount}$
Realized revenue reflects actual cash inflow after discounts. In our dataset, Gross Revenue is ₹1,443,700.00, customer discounts total ₹4,500.00, resulting in ₹1,439,200.00 realized net revenue.

#### Q10: Why did you choose SQLite over PostgreSQL for this challenge?
**Answer:** SQLite is a serverless, self-contained, zero-configuration relational database stored in a single disk file. For a dataset of 51 rows (or up to hundreds of thousands of transactions), SQLite provides sub-millisecond local execution without requiring the evaluator to configure external database servers, credentials, or network ports. The SQLAlchemy ORM abstraction ensures that switching to PostgreSQL or Amazon Aurora requires only changing `DATABASE_URL` in `.env`.

---

### Generative AI & Structured Output Questions

#### Q11: What is a Large Language Model (LLM) and how does tokenization work?
**Answer:** An LLM is a deep autoregressive neural network based on the Transformer architecture (specifically the self-attention mechanism). Tokenization is the preprocessing step that breaks raw text into numerical sub-word tokens (using algorithms like Byte-Pair Encoding). The model predicts the probability distribution of the next token given preceding context tokens: $P(w_t \mid w_1, w_2, \dots, w_{t-1})$.

#### Q12: What is "Structured Output" in modern LLMs and why is it crucial for tool calling?
**Answer:** By default, LLMs generate free-form conversational text. Structured Output forces the model's token decoding process to adhere strictly to a JSON schema (via JSON Mode or grammar-constrained sampling). This ensures the output can be parsed directly into a Pydantic model (`IntentInterpretation`) without regex parsing errors or missing keys.

#### Q13: What causes LLM hallucinations, and how does your architecture prevent them?
**Answer:** Hallucinations occur because LLMs are statistical pattern matchers, not mathematical engines. If asked to sum 50 numbers, the model outputs tokens that look like a plausible sum based on training data correlations, rather than computing the actual arithmetic. 
Our architecture prevents hallucinations through **Vectorless SQL RAG**: the LLM is never asked to calculate business numbers. SQLite computes the exact metrics, and the LLM only generates narrative explanations strictly grounded in those retrieved numbers.

#### Q14: What is temperature in LLM sampling, and what value did you use?
**Answer:** Temperature controls the randomness of next-token selection by scaling the logits before the softmax activation:
$$p_i = \frac{e^{z_i / T}}{\sum_j e^{z_j / T}}$$
A high temperature ($T > 0.7$) encourages creative text, while $T = 0.0$ produces greedy, deterministic token selection. For our intent classification, we use temperature $0.0$ to ensure maximum determinism and consistency.

#### Q15: How does your application behave if the Gemini or OpenAI API key is missing or invalid?
**Answer:** The system checks credentials at startup. If no key is configured or if an API call throws an exception (network timeout, rate limit, authentication failure), the `AIService` catches the error, logs a warning, and routes the query to `fallback_classify_intent()`. The application never crashes and clearly identifies the AI mode as `fallback_rule` in the response metadata.

---

### Agentic AI & Tool-Calling Architecture Questions

#### Q16: What is Agentic AI and how does it differ from traditional prompt engineering?
**Answer:** Traditional prompt engineering is a single-shot input-to-output interaction. Agentic AI involves an autonomous system capable of reasoning, planning, selecting tools, evaluating environmental feedback, and taking multi-step actions to achieve a business goal. In our application, the assistant reasons about user intent, selects an approved analytical tool, and executes it in a controlled environment.

#### Q17: What is the difference between an Agent and a Workflow?
**Answer:** A workflow follows a fixed, deterministic sequence of programmatic steps. An agent dynamically determines its execution path at runtime based on the inputs and intermediate tool outputs. Our assistant uses a **router workflow** (intent classification $\rightarrow$ tool selection $\rightarrow$ grounded synthesis), which provides the perfect balance between agentic reasoning and deterministic reliability.

#### Q18: What is the Model Context Protocol (MCP)?
**Answer:** MCP is an open standard introduced by Anthropic that standardizes how AI applications provide context and tools to LLMs. Instead of custom API integrations for each data source, MCP provides a unified client-server interface where tools and data resources are exposed over standard JSON-RPC protocols.

#### Q19: Why is unrestricted Text-to-SQL dangerous in production?
**Answer:** Unrestricted Text-to-SQL allows the LLM to write arbitrary SQL strings executed directly by the database. Major risks include:
1. **SQL Injection:** Malicious users embedding commands in prompts.
2. **Destructive Operations:** The model generating `DROP TABLE`, `DELETE`, or `UPDATE`.
3. **Resource Exhaustion:** Accidental cartesian joins (`CROSS JOIN`) locking the database.
4. **Incorrect Joins & Schema Hallucinations:** Hallucinating nonexistent column names.
Our Tool Registry eliminates all four risks by allowing the LLM only to select pre-approved, parameterized queries.

#### Q20: How would you extend this architecture into an autonomous multi-agent system using LangChain, LangGraph, or Google ADK?
**Answer:** We would introduce specialized agent roles:
1. *Router Agent:* Decomposes complex compound questions (e.g., *"Compare the top product in North with the top product in South"*).
2. *SQL Analytics Specialist:* Executes individual analytical tools.
3. *Data Auditor Agent:* Inspects data quality logs and adds cautionary notes.
4. *Synthesis & Visualization Agent:* Formats the executive summary and configures Plotly charts.
Frameworks like **LangGraph** or **Google ADK** would coordinate these agents using state graphs with human-in-the-loop checkpoints.

---

### RAG vs. Vectorless RAG Questions

#### Q21: What are embeddings and vector databases?
**Answer:** An embedding is a dense vector representation of text in high-dimensional semantic space (e.g., 1536 dimensions in OpenAI `text-embedding-3-small`). Words or sentences with similar meanings have smaller cosine distances. A vector database (Pinecone, Milvus, Chroma) indexes these vectors for fast Approximate Nearest Neighbor (ANN) search.

#### Q22: Why is Vectorless RAG superior for structured numerical sales data?
**Answer:** Vector search finds semantic similarity, not numerical truth. If you ask *"What is the total revenue?"*, vector search returns sentences containing words like "revenue" or "sales", but it cannot perform arithmetic operations across 48 transactions. Vectorless RAG queries relational databases directly using SQL, providing exact arithmetic calculations with zero token costs and zero hallucinations.

#### Q23: When *would* a vector database be appropriate in this application?
**Answer:** A vector database would add genuine value if the dataset included **unstructured textual data**, such as:
- Customer product reviews and feedback.
- Support ticket logs and transcripts.
- Free-form sales notes explaining why an order was returned.
In that scenario, a **Hybrid RAG** architecture would be used: SQLite for numerical revenue metrics, and a Vector DB for customer sentiment analysis.

---

### FastAPI & Backend Engineering Questions

#### Q24: What makes FastAPI faster than Flask or Django?
**Answer:** FastAPI is built on **Starlette** (for high-performance async web routing) and **Pydantic** (for ultra-fast Rust-powered data parsing via `pydantic-core`). It runs on ASGI servers like **Uvicorn** and supports non-blocking asynchronous requests (`async/await`), achieving throughput comparable to NodeJS and Go.

#### Q25: How does dependency injection work in FastAPI and why is it beneficial?
**Answer:** FastAPI's `Depends()` declares shared dependencies (such as database sessions, authentication handlers, or configuration objects). When a route handler executes, FastAPI resolves the dependency, provides the session, and executes cleanup code (e.g., closing `db.close()` in `finally:`) upon request completion. In tests, `app.dependency_overrides` allows swapping production databases with in-memory test databases seamlessly.

#### Q26: What are CORS headers and why are they needed in this project?
**Answer:** Cross-Origin Resource Sharing (CORS) is a browser security mechanism that restricts web pages running on one origin (e.g., Streamlit on `localhost:8501`) from requesting resources from a different origin (e.g., FastAPI on `localhost:8000`). We configure `CORSMiddleware` in FastAPI with `allow_origins=["*"]` so the Streamlit frontend can communicate with the API without browser blockages.

#### Q27: How does your API prevent SQL injection?
**Answer:** 
1. The assistant never accepts raw SQL from the user or the LLM.
2. All database queries in `backend/analytics.py` are written using SQLAlchemy ORM constructs or parameterized bindings (e.g., `:m1, :m2`). User parameters are treated strictly as data literals, never as executable SQL code.
3. Automated test `test_sql_injection_defense` explicitly verifies that payloads like `'; DROP TABLE sales_transactions; --` are neutralized.

---

### Data Engineering & Cleaning Questions

#### Q28: Walk me through the 3 excluded transactions in the dataset and why each was disqualified.
**Answer:**
1. **TXN0033 (Monitor, ₹9,500, Qty 2):** Status is `'Returned'`. Realized revenue measures earned income; returned merchandise represents canceled sales and must be excluded.
2. **TXN0034 (Keyboard, ₹900, Qty 0):** Quantity is `0`. A transaction with 0 quantity cannot generate revenue and indicates a system logging anomaly.
3. **TXN0051 (Laptop Stand, Qty 5, Unit Price blank):** Missing unit price. Without price data, revenue cannot be calculated without inventing numbers.

#### Q29: What is the difference between Data Imputation and Data Exclusion?
**Answer:** Data imputation fills missing values with statistical estimates (mean, median, mode, or zero). While useful in machine learning feature engineering, imputation is dangerous in financial accounting because it invents revenue figures. Data exclusion with audit preservation records the failure in an audit log and excludes the record from realization KPIs, preserving financial integrity.

#### Q30: How did you handle date normalization across different date formats?
**Answer:** In `parse_flexible_date()`, we test multiple formats (`%d-%m-%Y`, `%Y-%m-%d`, `%d/%m/%Y`, `%Y/%m/%d`). When raw dates like `"03-01-2026"` arrive, they are converted into Python `datetime.date` objects and stored in SQLite as standard ISO-8601 strings (`2026-01-03`). This enables chronological sorting and date functions like `strftime('%Y-%m', order_date)`.

---

### AWS Cloud & Deployment Questions

#### Q31: How would you deploy this application on AWS using serverless technologies?
**Answer:**
1. **Frontend:** Containerize Streamlit and run on **AWS ECS Fargate** or host a static React/Next.js frontend on **AWS S3 + CloudFront**.
2. **Backend:** Package FastAPI into an **AWS Lambda** container using the **Mangum** ASGI adapter, exposed via **Amazon API Gateway HTTP APIs**.
3. **Database:** Migrate SQLite to **Amazon Aurora Serverless v2 (PostgreSQL)**, providing auto-scaling database capacity with zero maintenance.
4. **Data Ingestion:** Store sales CSV files in **Amazon S3**, triggering an S3 Event Notification to invoke a Lambda data-loading function on file upload.

#### Q32: What is AWS Lambda and what is a "cold start"?
**Answer:** AWS Lambda is an event-driven serverless compute service that executes code in response to events and automatically scales. A "cold start" occurs when Lambda initializes a new execution environment (downloading container images, starting Python runtime, importing libraries like SQLAlchemy/Pydantic) for an incoming request after a period of inactivity. Cold starts can be mitigated using Provisioned Concurrency.

#### Q33: How does Amazon Lex compare to our custom Intent Router?
**Answer:** Amazon Lex is AWS's fully managed conversational AI service for building conversational interfaces (the technology behind Alexa). Lex natively handles Automated Speech Recognition (ASR) and Natural Language Understanding (NLU). Our custom intent router performs a similar function locally: extracting user intent and slots/parameters, which are then passed to backend fulfillment functions.

#### Q34: What is Amazon SageMaker and when would you use it in this project?
**Answer:** Amazon SageMaker is a fully managed machine learning platform for building, training, tuning, and deploying ML models. In our current application, simple SQL analytics suffice for historical reporting. However, if the business wanted **predictive intelligence**—such as forecasting next quarter's sales or predicting which products have high return probabilities—we would train and deploy a forecasting model using SageMaker.

---

### Debugging & Problem-Solving Scenarios

#### Q35: If the Streamlit frontend displays "🔴 Backend Offline", how do you debug it?
**Answer:**
1. Check if the FastAPI process is running: `curl http://127.0.0.1:8000/api/health`.
2. Inspect backend terminal logs for uncaught exceptions or database lock errors.
3. Check port conflicts: `lsof -i :8000` to see if another process is occupying the port.
4. Check CORS headers and verify `API_BASE_URL` in the frontend configuration.

#### Q36: If the user says "Sales figures don't match our accounting spreadsheet", how do you trace the discrepancy?
**Answer:**
1. Check the data quality report at `/api/data-quality` to see which records were excluded.
2. In our dataset, the 3 excluded transactions account for unearned revenue. If the accounting team included Returned transaction `TXN0033` (₹19,000), their total would be ₹1,458,200 instead of our realized net revenue of ₹1,439,200.
3. Provide the full audit table showing transaction IDs, dates, and exclusion reasons to reconcile the figures.

#### Q37: What would happen if two users upload new CSV files simultaneously?
**Answer:** SQLite uses file-level locking during write transactions (`BEGIN EXCLUSIVE`). If two uploads occur concurrently, one will acquire the lock while the second waits (up to the configured `timeout`). In production with high concurrent writes, we would migrate from SQLite to PostgreSQL with row-level locking and connection pooling via PgBouncer.

#### Q38: How did you ensure automated tests don't pollute the production database?
**Answer:** In `tests/conftest.py`, we created an isolated in-memory SQLite database using `sqlite://` with `StaticPool`. Pytest drops and recreates schema tables in memory before each test function. Production database `./data/bi_assistant.db` is never modified during test runs.

#### Q39: Why did you migrate from `google.generativeai` to `google-genai`?
**Answer:**
Google deprecated the legacy `google.generativeai` SDK. The new `google-genai` package is Google's unified modern SDK supporting:
1. Native Structured Outputs via `types.GenerateContentConfig(response_schema=IntentInterpretation, response_mime_type="application/json")`.
2. First-class request timeout controls via `types.HttpOptions(timeout=15000)`.
3. Direct Pydantic model serialization, eliminating regex JSON post-parsing hacks.
Our system maintains a dual-mode initialization: it uses `google-genai` as primary and falls back gracefully to deterministic rule routing if the external API is unreachable or quota is exhausted.

#### Q40: How does your conversational memory resolve pronoun antecedents like "its monthly trend"?
**Answer:**
We built a stateful `ConversationManager` in `backend/conversation.py`. When a user asks:
- Turn 1: *"Which product generated the highest revenue?"* -> Result: Monitor (₹473,000.00).
- Session logs `last_product = "Monitor"`.
- Turn 2: *"What is its monthly trend?"*
The antecedent resolution engine detects the pronoun `"its"` accompanied by trend/revenue keywords. Before routing to the LLM, `resolve_context()` resolves the antecedent to *"Monitor"*, rewriting the query intent to `monthly_revenue_trend(product='Monitor')`. This delivers conversational continuity without polluting LLM prompts with multi-thousand-token chat transcripts.

#### Q41: How do you handle duplicate transaction IDs during CSV ingestion without crashing SQLite?
**Answer:**
In relational databases, primary key columns (`transaction_id`) enforce uniqueness. In naive ingestion pipelines, a duplicate ID triggers an unhandled `sqlite3.IntegrityError` or crashes the batch.
In our `data_loader.py`:
1. We detect whether `Transaction_Id` was already encountered in the current batch or database.
2. If duplicate, we assign a deterministic audit key `f"{tid}_DUP_{duplicate_count}"` and set `is_eligible = False` with `exclusion_reason = "Duplicate Transaction_Id within dataset"`.
3. This allows the duplicate row to be stored safely in SQLite for audit lineage, displays in the Data Quality report, and excludes it from revenue calculations without throwing database exceptions.

#### Q42: What mathematical models did you use for sales forecasting, and how are they evaluated?
**Answer:**
We implemented two classical econometric time-series models in `backend/forecasting.py`:
1. **Ordinary Least Squares (OLS) Linear Trend:**
   $$y = m \cdot t + c$$
2. **Holt's Linear Exponential Smoothing (Additive Level + Trend):**
   $$L_t = \alpha y_t + (1-\alpha)(L_{t-1} + T_{t-1})$$
   $$T_t = \beta(L_t - L_{t-1}) + (1-\beta)T_{t-1}$$
   $$\hat{y}_{t+m} = L_t + m \cdot T_t$$
**Evaluation Protocol:** We split the 6 months chronologically into Train (Months 1–4: Jan–Apr) and Test (Months 5–6: May–Jun). We compute out-of-sample MAE, RMSE, and MAPE, and dynamically select the model with lower out-of-sample RMSE for forward projections.

#### Q43: Why didn't you use deep learning (LSTM/Transformers) or Facebook Prophet for forecasting?
**Answer:**
The available dataset contains only 6 monthly aggregates (January to June 2026). Deep learning architectures and complex Bayesian libraries like Prophet require dozens or hundreds of time points to avoid extreme overfitting and parameter indeterminacy.
Using OLS regression and Holt's smoothing demonstrates mathematical maturity: matching model complexity to sample size ($N=6$) while reporting out-of-sample error honestly.

#### Q44: How are statistical confidence intervals calculated in the forecasting module?
**Answer:**
Confidence bounds are derived from the sample standard error of regression residuals:
$$s_e = \sqrt{\frac{\sum (y_i - \hat{y}_i)^2}{N - 2}}$$
For future step $m$, uncertainty expands by $\sqrt{1 + m \cdot 0.25}$. We calculate:
- 80% Confidence Interval: $\hat{y} \pm 1.28 \cdot s_e(m)$
- 95% Confidence Interval: $\hat{y} \pm 1.96 \cdot s_e(m)$
Negative bounds are floored at zero since revenue cannot be negative.

#### Q45: How is your Role-Based Access Control (RBAC) implemented and secured?
**Answer:**
In `backend/auth.py`, we implement a 3-tier security model:
- `Admin`: Full permissions (upload CSV, reset database, update API keys, query AI, export reports).
- `Analyst`: Analytical permissions (query AI, view deep-dives, export PDF/CSV).
- `Viewer`: Read-only permissions (dashboard KPI cards and charts only).
Passwords are authenticated using standard library `hashlib.pbkdf2_hmac("sha256", password, salt, 100_000)`. Endpoints are guarded via FastAPI dependencies (`require_admin`, `require_analyst_or_admin`). In Streamlit, users can switch simulated roles in the sidebar to test security enforcement live.

#### Q46: Why did you choose ReportLab for executive PDF exports instead of browser printing or HTML-to-PDF?
**Answer:**
Browser-based printing (`window.print()`) depends on client browser rendering, margins, and paper sizes, producing inconsistent layouts. Headless browser HTML-to-PDF tools (like Puppeteer or WeasyPrint) require heavy external binaries (Chromium, Cairo, Pango) that bloat docker containers and slow down CI pipelines.
ReportLab compiles native PDF byte streams in memory using pure Python in ~40ms, producing pixel-perfect corporate tables, headers, and audit logs with zero external OS dependencies.

#### Q47: Why did you choose Modular Function Calling over Multi-Agent Orchestration (CrewAI/AutoGen)?
**Answer:**
For structured enterprise Business Intelligence, Multi-Agent frameworks introduce three major production hazards:
1. High Latency: 8–18 seconds per query due to multi-agent dialogue loops.
2. Compounding Errors: A hallucination in the planner corrupts the SQL agent, which traps the critic agent in an infinite correction loop.
3. High Token Costs: Verbose agent roleplay prompts consume 10x–30x more tokens.
Our Modular Tool-Calling architecture performs single-pass intent routing via Gemini Structured Outputs, then executes pre-compiled, parameter-safe SQLAlchemy queries in under 200ms with zero mathematical hallucination.

#### Q48: How do you defend the data-cleaning discrepancy between 51 raw rows and 48 eligible rows?
**Answer:**
The raw dataset contains 51 transactions totaling ₹1,462,700 gross. However:
1. `TXN0033` has `Status == 'Returned'` (₹19,000 gross).
2. `TXN0034` has `Quantity == 0` (₹0 gross, operational anomaly).
3. `TXN0051` has a blank `Unit_price` (unverifiable financial value).
Per our documented Single-Source-of-Truth policy (`docs/data_cleaning_policy.md`), realized net revenue is earned from completed transactions only:
$$\text{Realized Net Revenue} = \text{Gross Completed} (₹1,443,700) - \text{Discounts} (₹4,500) = ₹1,439,200.00$$
All 51 records are preserved in SQLite with `is_eligible` flags and exclusion reasons for full governance and accounting reconciliation.

---

# 4. PRACTICAL LIVE-CODING MODIFICATIONS AN INTERVIEWER MAY REQUEST

Be prepared to implement these common requests during your technical interview:

### Modification 1: "Add a new analytical question: Which sales channel had the highest return rate?"
**How to answer & code:**
1. Explain: *"I will add an analytics function in `backend/analytics.py` and register it in `backend/tool_registry.py`."*
2. Code to write:
```python
# In backend/analytics.py:
def get_channel_return_rates(db: Session) -> Dict[str, Any]:
    rows = (
        db.query(
            SalesTransaction.sales_channel,
            func.count(SalesTransaction.transaction_id).label("total_orders"),
            func.count(case((SalesTransaction.status == "Returned", 1))).label("returned_orders"),
        )
        .group_by(SalesTransaction.sales_channel)
        .all()
    )
    results = []
    for r in rows:
        tot = int(r.total_orders)
        ret = int(r.returned_orders)
        rate = round((ret / tot) * 100, 2) if tot > 0 else 0.0
        results.append({"sales_channel": r.sales_channel, "total_orders": tot, "returns": ret, "return_rate_pct": rate})
    return {"title": "Sales Channel Return Rates", "supporting_data": results, "chart_type": "bar"}
```
3. Register the tool in `backend/tool_registry.py` under `registry.register(...)`.

### Modification 2: "Can you filter revenue by a specific region (e.g., 'What was total revenue in North?')"
**How to answer & code:**
1. Update `total_revenue` in `backend/analytics.py` to accept an optional `region: Optional[str] = None`:
```python
def get_total_revenue(db: Session, region: Optional[str] = None) -> Dict[str, Any]:
    query = db.query(...).filter(SalesTransaction.is_eligible == True)
    if region:
        query = query.filter(func.lower(SalesTransaction.region) == region.strip().lower())
    # ... return results
```
2. Update the parameter schema in `tool_registry.py`.

### Modification 3: "Add CSV export for chat history in Streamlit"
**How to code:**
In `frontend/app.py`:
```python
if st.session_state.chat_history:
    df_history = pd.DataFrame(st.session_state.chat_history)[["question", "answer", "intent", "ai_mode"]]
    st.download_button(
        label="Download Conversation History (CSV)",
        data=df_history.to_csv(index=False),
        file_name="assistant_chat_history.csv",
        mime="text/csv",
    )
```
