"""
Tool Registry Module
--------------------
Provides a centralized, extensible registry of approved analytical tools.
Each tool defines:
- Unique identifier and business description
- Parameter specifications and validation rules
- Deterministic SQL/ORM backend execution handler
- Descriptive metadata for LLM prompt grounding
- Example natural-language phrasings.

This guarantees AI safety: the LLM never executes arbitrary raw SQL;
it selects approved tools whose execution is strictly controlled by the backend.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy.orm import Session
from backend.exceptions import ToolExecutionError
import backend.analytics as analytics


@dataclass
class ToolDefinition:
    name: str
    description: str
    handler: Callable[..., Dict[str, Any]]
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    sql_summary: str = ""
    default_chart_type: str = "bar"
    example_questions: List[str] = field(default_factory=list)


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a new analytical tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Retrieve tool definition by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_tool_catalog_prompt(self) -> str:
        """
        Generates a concise JSON/Markdown catalog of approved tools for LLM intent routing.
        """
        lines = []
        for t in self._tools.values():
            params = t.parameters_schema.get("properties", {})
            param_desc = ", ".join(f"{k} ({v.get('type')})" for k, v in params.items()) or "none"
            ex_str = ", ".join(f'"{q}"' for q in t.example_questions[:2])
            lines.append(
                f"- Tool: `{t.name}`\n"
                f"  Description: {t.description}\n"
                f"  Parameters: {param_desc}\n"
                f"  Examples: {ex_str}"
            )
        return "\n".join(lines)

    def execute(self, tool_name: str, db: Session, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes the registered tool safely with given parameters and database session.
        """
        tool = self.get(tool_name)
        if not tool:
            raise ToolExecutionError(f"Tool '{tool_name}' is not in the approved tool registry.")

        clean_params = params or {}
        try:
            return tool.handler(db, **clean_params)
        except TypeError as e:
            raise ToolExecutionError(
                f"Parameter mismatch while invoking tool '{tool_name}': {e}",
                details={"provided_params": clean_params}
            )
        except Exception as e:
            raise ToolExecutionError(
                f"Error during execution of tool '{tool_name}': {e}",
                details={"provided_params": clean_params}
            )


# Global tool registry instance
registry = ToolRegistry()

# ----------------------------------------------------------------------
# Mandatory Five Tools Registration
# ----------------------------------------------------------------------

registry.register(
    ToolDefinition(
        name="total_revenue",
        description="Calculates total gross revenue, realized net revenue, total discounts given, total units sold, and eligible order count.",
        handler=lambda db, **kwargs: analytics.get_total_revenue(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT SUM(gross_revenue), SUM(net_revenue), SUM(discount_amount) FROM sales_transactions WHERE is_eligible = 1",
        default_chart_type="metric",
        example_questions=[
            "What is the total revenue?",
            "How much money did we earn?",
            "Calculate our total net sales.",
            "Give me the overall sales revenue.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="top_revenue_product",
        description="Identifies the product that generated the highest realized net revenue, including rank, quantity sold, and revenue breakdown.",
        handler=lambda db, limit=1, **kwargs: analytics.get_highest_revenue_product(db, limit=limit),
        parameters_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of top products (default 1)."}
            },
        },
        sql_summary="SELECT product, SUM(net_revenue) AS total_net FROM sales_transactions WHERE is_eligible = 1 GROUP BY product ORDER BY total_net DESC LIMIT :limit",
        default_chart_type="bar",
        example_questions=[
            "Which product generated the highest revenue?",
            "Which product made the most money?",
            "What is our best-selling product by sales revenue?",
            "Rank products by revenue.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="monthly_revenue_trend",
        description="Shows chronological month-by-month revenue, quantity sold, transaction volume, and growth rates across all recorded months, with optional region or product filters.",
        handler=lambda db, region=None, product=None, **kwargs: analytics.get_monthly_revenue_trend(db, region=region, product=product),
        parameters_schema={
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "Optional region name filter (e.g. 'South', 'North')."},
                "product": {"type": "string", "description": "Optional product name filter (e.g. 'Monitor')."},
            },
        },
        sql_summary="SELECT strftime('%Y-%m', order_date) as month, SUM(net_revenue) FROM sales_transactions WHERE is_eligible = 1 GROUP BY month ORDER BY month ASC",
        default_chart_type="line",
        example_questions=[
            "What is the monthly revenue trend?",
            "Show its monthly trend.",
            "Monthly sales trend for South region.",
            "Which month performed best?",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="top_revenue_region",
        description="Identifies the region generating the highest net sales revenue, along with sales volume, transaction count, and regional revenue share.",
        handler=lambda db, limit=1, **kwargs: analytics.get_highest_revenue_region(db, limit=limit),
        parameters_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of top regions (default 1)."}
            },
        },
        sql_summary="SELECT region, SUM(net_revenue) AS net_revenue FROM sales_transactions WHERE is_eligible = 1 GROUP BY region ORDER BY net_revenue DESC LIMIT :limit",
        default_chart_type="bar",
        example_questions=[
            "Which region generated the highest revenue?",
            "Compare sales across regions.",
            "Which region performs best in sales?",
            "Rank regions by revenue.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="monthly_comparison",
        description="Compares revenue, order count, and percentage change between two specified months (e.g., '2026-01' and '2026-02'). Requires both month_1 and month_2.",
        handler=lambda db, month_1, month_2, **kwargs: analytics.compare_two_months(db, month_1=month_1, month_2=month_2),
        parameters_schema={
            "type": "object",
            "properties": {
                "month_1": {"type": "string", "description": "First month in YYYY-MM or month name format (e.g., '2026-01' or 'January')."},
                "month_2": {"type": "string", "description": "Second month in YYYY-MM or month name format (e.g., '2026-02' or 'February')."},
            },
            "required": ["month_1", "month_2"],
        },
        sql_summary="SELECT strftime('%Y-%m', order_date) as month, SUM(net_revenue) FROM sales_transactions WHERE is_eligible = 1 AND month IN (:m1, :m2) GROUP BY month",
        default_chart_type="bar",
        example_questions=[
            "Compare January and February.",
            "How did revenue change between March and May?",
            "Did sales increase in June compared with May?",
            "Compare revenue between 2026-01 and 2026-03.",
        ],
    )
)

# ----------------------------------------------------------------------
# Additional Analytical Capabilities Registration
# ----------------------------------------------------------------------

registry.register(
    ToolDefinition(
        name="top_quantity_product",
        description="Identifies the product with the highest total unit volume / quantity sold.",
        handler=lambda db, **kwargs: analytics.get_top_quantity_product(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT product, SUM(quantity) AS total_qty FROM sales_transactions WHERE is_eligible = 1 GROUP BY product ORDER BY total_qty DESC",
        default_chart_type="bar",
        example_questions=[
            "Which product sold the highest quantity?",
            "What is our most popular product by volume?",
            "Which item had the most units sold?",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="lowest_quantity_product",
        description="Identifies the product with the lowest total unit volume / quantity sold.",
        handler=lambda db, **kwargs: analytics.get_lowest_quantity_product(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT product, SUM(quantity) AS total_qty FROM sales_transactions WHERE is_eligible = 1 GROUP BY product ORDER BY total_qty ASC",
        default_chart_type="bar",
        example_questions=[
            "Which product sold the lowest quantity?",
            "What is the least sold item by volume?",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="category_revenue",
        description="Provides category-wise revenue aggregation and percentage contribution across product categories.",
        handler=lambda db, **kwargs: analytics.get_category_revenue_breakdown(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT category, SUM(net_revenue) FROM sales_transactions WHERE is_eligible = 1 GROUP BY category ORDER BY net_revenue DESC",
        default_chart_type="donut",
        example_questions=[
            "Show category-wise revenue.",
            "What is the revenue breakdown by category?",
            "Which category contributes the most sales?",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="channel_comparison",
        description="Compares performance between Online and Retail sales channels in revenue and order volume.",
        handler=lambda db, **kwargs: analytics.get_sales_channel_comparison(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT sales_channel, SUM(net_revenue), COUNT(*) FROM sales_transactions WHERE is_eligible = 1 GROUP BY sales_channel",
        default_chart_type="donut",
        example_questions=[
            "Compare sales channels.",
            "Which sales channel generates more revenue?",
            "Online vs Retail sales performance.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="average_transaction_value",
        description="Calculates average net revenue per eligible completed transaction.",
        handler=lambda db, **kwargs: analytics.get_average_transaction_value(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT AVG(net_revenue) FROM sales_transactions WHERE is_eligible = 1",
        default_chart_type="metric",
        example_questions=[
            "What is the average transaction value?",
            "What is our average order value (AOV)?",
            "How much does a customer spend on average per order?",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="regional_transaction_counts",
        description="Analyzes the number of transactions and order frequency across all regions.",
        handler=lambda db, **kwargs: analytics.get_region_transaction_counts(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT region, COUNT(*) AS orders FROM sales_transactions WHERE is_eligible = 1 GROUP BY region",
        default_chart_type="bar",
        example_questions=[
            "Show transaction count by region.",
            "Which region has the most orders?",
            "Order volume across regions.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="status_breakdown",
        description="Displays the distribution of transactions by status (Completed, Returned) for data audit.",
        handler=lambda db, **kwargs: analytics.get_transaction_status_breakdown(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT status, COUNT(*) FROM sales_transactions GROUP BY status",
        default_chart_type="donut",
        example_questions=[
            "Show transaction count by status.",
            "How many orders were completed versus returned?",
            "Status breakdown of sales transactions.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="discount_analysis",
        description="Analyzes total discounts given, average discount rate, and proportion of discounted transactions.",
        handler=lambda db, **kwargs: analytics.get_discount_analysis(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT SUM(discount_amount), SUM(gross_revenue) FROM sales_transactions WHERE is_eligible = 1",
        default_chart_type="metric",
        example_questions=[
            "How much discount did we give?",
            "Analyze sales discounts.",
            "What is our discount percentage on sales?",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="top_5_products",
        description="Ranks the top 5 products by realized net sales revenue.",
        handler=lambda db, **kwargs: analytics.get_top_n_products_by_revenue(db, n=5),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT product, SUM(net_revenue) FROM sales_transactions WHERE is_eligible = 1 GROUP BY product ORDER BY net_revenue DESC LIMIT 5",
        default_chart_type="bar",
        example_questions=[
            "What are the top 5 products by revenue?",
            "Show the top 5 best-performing products.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="product_comparison",
        description="Compares net revenue, volume, and orders between two specific products.",
        handler=lambda db, product_1, product_2, **kwargs: analytics.compare_products(db, product_1=product_1, product_2=product_2),
        parameters_schema={
            "type": "object",
            "properties": {
                "product_1": {"type": "string", "description": "First product name (e.g., 'Monitor')."},
                "product_2": {"type": "string", "description": "Second product name (e.g., 'Desk')."},
            },
            "required": ["product_1", "product_2"],
        },
        sql_summary="SELECT product, SUM(net_revenue), SUM(quantity) FROM sales_transactions WHERE is_eligible = 1 AND LOWER(product) IN (:p1, :p2) GROUP BY product",
        default_chart_type="bar",
        example_questions=[
            "Compare Monitor and Desk.",
            "How does Keyboard compare to Wireless Mouse in sales?",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="compare_regions",
        description="Compares net sales revenue, units sold, and orders between two specific regions (e.g. South vs North).",
        handler=lambda db, region_1, region_2, **kwargs: analytics.compare_regions(db, region_1=region_1, region_2=region_2),
        parameters_schema={
            "type": "object",
            "properties": {
                "region_1": {"type": "string", "description": "First region name (e.g., 'South')."},
                "region_2": {"type": "string", "description": "Second region name (e.g., 'North')."},
            },
            "required": ["region_1", "region_2"],
        },
        sql_summary="SELECT region, SUM(net_revenue), SUM(quantity) FROM sales_transactions WHERE is_eligible = 1 AND LOWER(region) IN (:r1, :r2) GROUP BY region",
        default_chart_type="bar",
        example_questions=[
            "Compare South and North.",
            "Compare it with North.",
            "How do South and West regions compare in sales?",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="lowest_performing_product",
        description="Identifies the product with the lowest net sales revenue.",
        handler=lambda db, **kwargs: analytics.get_lowest_performing_product(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT product, SUM(net_revenue) AS total_net FROM sales_transactions WHERE is_eligible = 1 GROUP BY product ORDER BY total_net ASC LIMIT 1",
        default_chart_type="bar",
        example_questions=[
            "Which product generated the lowest revenue?",
            "What is our worst-performing product by sales?",
            "Lowest revenue product.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="data_quality_audit",
        description="Audits data quality issues, excluded records, invalid quantities, missing prices, returned orders, and dataset cleanliness percentage.",
        handler=lambda db, **kwargs: analytics.get_data_quality_audit(db),
        parameters_schema={"type": "object", "properties": {}},
        sql_summary="SELECT is_eligible, exclusion_reason, count(*) FROM sales_transactions GROUP BY is_eligible, exclusion_reason",
        default_chart_type="table",
        example_questions=[
            "What are the data-quality issues?",
            "Show data quality audit.",
            "How clean is our sales dataset?",
            "What records were excluded and why?",
        ],
    )
)

# ----------------------------------------------------------------------
# Phase 2 – Package B: Advanced Analytics Tools
# ----------------------------------------------------------------------

registry.register(
    ToolDefinition(
        name="anomaly_detection",
        description="Performs IQR and Z-score anomaly detection on sales transactions, distinguishing statistical outliers from confirmed data quality errors.",
        handler=lambda db, **kwargs: analytics.detect_anomalies(db, **kwargs),
        parameters_schema={
            "type": "object",
            "properties": {
                "z_threshold": {"type": "number", "description": "Z-score outlier threshold, default 2.5."}
            },
        },
        sql_summary="SELECT transaction_id, net_revenue, is_eligible FROM sales_transactions",
        default_chart_type="table",
        example_questions=[
            "Detect sales anomalies.",
            "Show revenue outliers and anomalies.",
            "Are there any statistical anomalies in transactions?",
            "Find unusual sales transactions.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="revenue_concentration",
        description="Calculates Pareto 80/20 revenue concentration, identifying the vital few products driving 80% of net revenue with clear denominator.",
        handler=lambda db, **kwargs: analytics.get_pareto_revenue_concentration(db, **kwargs),
        parameters_schema={
            "type": "object",
            "properties": {
                "top_pct_cutoff": {"type": "number", "description": "Cumulative percentage cutoff, default 80.0."}
            },
        },
        sql_summary="SELECT product, SUM(net_revenue) FROM sales_transactions WHERE is_eligible = 1 GROUP BY product ORDER BY SUM(net_revenue) DESC",
        default_chart_type="bar",
        example_questions=[
            "Show Pareto 80/20 analysis.",
            "What is our revenue concentration?",
            "Which products generate 80% of our revenue?",
            "Pareto distribution of sales.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="what_if_simulation",
        description="Simulates revenue what-if scenarios adjusting price, volume, and discount parameters without inventing fictitious costs.",
        handler=lambda db, **kwargs: analytics.simulate_what_if_revenue(db, **kwargs),
        parameters_schema={
            "type": "object",
            "properties": {
                "price_change_pct": {"type": "number", "description": "Percentage change in unit prices (e.g. 10.0 for +10%)."},
                "volume_change_pct": {"type": "number", "description": "Percentage change in sales volume (e.g. -5.0 for -5%)."},
                "discount_adjustment_pct": {"type": "number", "description": "Percentage change in discount rates (e.g. -10.0 for -10%)."},
                "category": {"type": "string", "description": "Optional category filter."},
                "channel": {"type": "string", "description": "Optional sales channel filter."},
            },
        },
        sql_summary="SELECT product, quantity, unit_price, discount_amount, net_revenue FROM sales_transactions WHERE is_eligible = 1",
        default_chart_type="bar",
        example_questions=[
            "What if prices increase by 10%?",
            "Simulate a 5% volume increase and 10% discount cut.",
            "What-if revenue simulation.",
            "Simulate price increase for Electronics.",
        ],
    )
)

registry.register(
    ToolDefinition(
        name="quota_pacing",
        description="Evaluates sales target and quota pacing, comparing configured business targets against empirical realized sales run-rate.",
        handler=lambda db, **kwargs: analytics.get_sales_target_pacing(db, **kwargs),
        parameters_schema={
            "type": "object",
            "properties": {
                "monthly_target": {"type": "number", "description": "Configured monthly sales quota (e.g. 500000)."},
                "target_year": {"type": "integer", "description": "Optional year."},
                "target_month": {"type": "integer", "description": "Optional month (1-12)."},
            },
        },
        sql_summary="SELECT SUM(net_revenue), count(*) FROM sales_transactions WHERE is_eligible = 1 AND order_date BETWEEN :start AND :end",
        default_chart_type="metric",
        example_questions=[
            "What is our sales quota pacing?",
            "Are we on track to hit our sales target?",
            "Sales target pacing analysis.",
            "Quota pacing for 500000 target.",
        ],
    )
)

