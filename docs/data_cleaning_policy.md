# Data Cleaning and Revenue Calculation Policy
**RSG Research Private Limited – Mini AI Business Intelligence Assistant**

---

## 1. Executive Policy Statement
This document establishes the single, authoritative data-cleaning, transaction-eligibility, and revenue-calculation policy for the Mini AI Business Intelligence Assistant. 

All components—including the backend database models, SQLAlchemy ORM queries, AI intent routing, CSV upload pipelines, executive dashboard KPIs, and automated test suites—must strictly adhere to the standards outlined herein.

---

## 2. Core Financial Definitions and Formulae

### 2.1 Gross Revenue
$$\text{Gross Revenue} = \text{Quantity} \times \text{Unit Price}$$
Gross revenue represents the total nominal sales value of ordered merchandise before any discounts or customer concessions are applied.

### 2.2 Customer Discounts
$$\text{Discount Amount} = \text{Specified Discount in INR}$$
Discounts reflect promotional price reductions granted to the customer. 
- A discount amount cannot be negative ($\text{Discount Amount} \ge 0$).
- A discount amount cannot exceed Gross Revenue ($\text{Discount Amount} \le \text{Gross Revenue}$).

### 2.3 Realized Net Revenue
$$\text{Realized Net Revenue} = \text{Gross Revenue} - \text{Discount Amount}$$
Realized Net Revenue is the actual cash-generative sales figure recognized by the business. All core revenue KPIs, product rankings, regional market shares, and monthly trajectories are computed strictly using **Realized Net Revenue**.

---

## 3. Transaction Eligibility Standards

To ensure financial audit integrity, transactions imported into the system are evaluated against five eligibility rules. Transactions meeting all criteria are marked `is_eligible = True`; any record violating one or more criteria is marked `is_eligible = False` and tagged with an auditable `exclusion_reason`.

| Rule ID | Field Inspected | Condition for Realized Revenue | Business Rationale |
|---|---|---|---|
| **RULE-01** | `Status` | `Status == 'Completed'` (Case-insensitive) | Only completed sales realize revenue. Orders marked `Returned` or `Cancelled` reverse sales and do not represent realized revenue. |
| **RULE-02** | `Quantity` | `Quantity > 0` (Integer) | Transactions with zero or negative quantities are invalid or cancelled line items and cannot realize positive revenue. |
| **RULE-03** | `Unit_price` | `Unit_price > 0` (Numerical, Not Null) | Missing or blank unit prices cannot be calculated without arbitrary fabrication. Such records must be held in audit. |
| **RULE-04** | `Discount_amount` | `0 <= Discount_amount <= Gross_revenue` | Negative discounts or discounts exceeding line-item value indicate data entry corruption. |
| **RULE-05** | `Order_date` | Valid date parseable to `YYYY-MM-DD` | Transactions with missing or unparseable dates cannot be placed in chronological reporting. |

---

## 4. Audit Trail vs. Silent Dropping

### Non-Destructive Ingestion Standard
- **No Silent Dropping:** Corrupted or ineligible records are **never silently discarded** by Pandas or dropped from SQLite.
- **No Synthetic Fillers:** Missing unit prices or invalid quantities are **never filled with fake zeros or statistical means** without audit disclosure.
- **Full Lineage Tracking:** Every transaction is persisted in `sales_transactions` with:
  - `is_eligible` (`BOOLEAN`): Indicates whether the record is included in sales analytics.
  - `exclusion_reason` (`VARCHAR`): Human-readable audit explanation (e.g. `Status is 'Returned'`).

---

## 5. Audit of the Company-Provided Dataset (`sales.csv`)

The baseline dataset provided for the challenge contains **51 total rows**:
- **48 Eligible Completed Transactions** (Realized Net Revenue: **₹1,439,200.00**)
- **3 Audited Excluded Records** (Detailed below):

### Detailed Breakdown of Excluded Records:

| Transaction ID | Order Date | Product | Qty | Unit Price | Discount | Status | Exclusion Reason | Audit Note |
|---|---|---|---|---|---|---|---|---|
| `TXN0033` | 26-04-2026 | Monitor | 2 | ₹9,500.00 | ₹0.00 | **Returned** | `Status is 'Returned'` | Returned order; gross value ₹19,000.00 reversed; not realized sales. |
| `TXN0034` | 28-04-2026 | Keyboard | **0** | ₹900.00 | ₹0.00 | Completed | `Quantity must be positive; found 0` | Zero quantity order; invalid transaction entry. |
| `TXN0051` | 28-06-2026 | Laptop Stand | 5 | **NULL** | ₹0.00 | Completed | `Missing unit price` | Unit price omitted; revenue cannot be determined without assumption. |

---

## 6. Authoritative Benchmark Figures (Golden Truth)

All analytics functions and test assertions must conform to these exact figures:

| Metric | Authoritative Value | Calculation Basis |
|---|---|---|
| **Total Transactions Ingested** | `51` | Total rows in dataset |
| **Eligible Transactions Count** | `48` | Only `is_eligible == True` |
| **Excluded Transactions Count** | `3` | Audited non-eligible rows |
| **Dataset Cleanliness Rate** | `94.12%` | $(48 / 51) \times 100$ |
| **Total Realized Gross Revenue** | **₹1,443,700.00** | $\sum(\text{Quantity} \times \text{Unit Price})$ for eligible rows |
| **Total Customer Discounts** | **₹4,500.00** | $\sum(\text{Discount Amount})$ for eligible rows |
| **Total Realized Net Revenue** | **₹1,439,200.00** | Gross Revenue $-$ Discounts |
| **Total Units Sold** | `633` | $\sum(\text{Quantity})$ for eligible rows |
| **Average Order Value (AOV)** | **₹29,983.33** | $\text{Realized Net Revenue} / 48$ |
| **Highest Revenue Product** | **Monitor** | **₹473,000.00** net revenue (50 units sold) |
| **Highest Volume Product** | **Wireless Mouse** | **228 units** sold (₹148,200.00 net revenue) |
| **Peak Performing Month** | **May 2026** | **₹318,500.00** net revenue |
| **Highest Revenue Region** | **South** | **₹411,200.00** net revenue (173 units) |
| **Omnichannel Revenue Split** | **Online:** ₹746,750 (51.9%)<br>**Retail:** ₹692,450 (48.1%) | Clean ~52/48 omnichannel distribution |

---

## 7. Change Control and Discrepancy Prevention
Any future modifications to data loading or analytics must verify that:
1. `SELECT count(*) FROM sales_transactions WHERE is_eligible = 1` yields exactly `48`.
2. `SELECT sum(net_revenue) FROM sales_transactions WHERE is_eligible = 1` yields exactly `1439200.0`.
3. Automated test `tests/test_data_quality.py` passes 100% on every build.
