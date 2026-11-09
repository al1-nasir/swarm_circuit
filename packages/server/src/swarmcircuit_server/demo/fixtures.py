"""Small disclosed fixtures. These are not customer data or model-generated analysis."""

import csv
import io
from decimal import Decimal

DATASET = """quarter,revenue,customers
Q1,120000,400
Q2,138000,440
Q3,151800,460
Q4,166980,500
"""
PUBLIC_FINDINGS = """# Reading the sales brief

These notes use no restricted data and can be prepared independently of dataset access.

- Revenue measures sales before expenses. Growing revenue does not establish profit.
- Quarter-over-quarter growth compares one quarter with the preceding quarter.
- Four quarterly values alone cannot establish seasonality or forecast future sales.
- Adding quarterly customer counts gives customer-quarters, not unique customers.

## Further reading

- SEC, Beginner's Guide to Financial Statements:
  https://www.sec.gov/investor/pubs/begfinstmtguide.htm
- Census Bureau, Quarterly Financial Report:
  https://www.census.gov/programs-surveys/qfr.html

Bundled explanatory notes; links were not fetched during this run.
"""


def analyze() -> dict[str, str | int]:
    rows = list(csv.DictReader(io.StringIO(DATASET)))
    first, last = Decimal(rows[0]["revenue"]), Decimal(rows[-1]["revenue"])
    growth = ((last / first - 1) * 100).quantize(Decimal("0.01"))
    customers = sum(int(row["customers"]) for row in rows)
    return {
        "first_quarter_revenue": str(first),
        "last_quarter_revenue": str(last),
        "revenue_growth_percent": str(growth),
        "customer_quarters": customers,
        "quarters": len(rows),
    }


def analysis_text(result: dict[str, str | int]) -> str:
    return (
        "# Quarterly dataset summary\n\n"
        f"- First-quarter revenue: {result['first_quarter_revenue']} sample units\n"
        f"- Last-quarter revenue: {result['last_quarter_revenue']} sample units\n"
        f"- Revenue growth from first to last quarter: {result['revenue_growth_percent']}%\n"
        f"- Customer-quarters observed: {result['customer_quarters']}\n\n"
        "Customer-quarters add the four quarterly counts; they are not unique customers.\n\n"
        "Local sample data; no live company data or model-generated analysis.\n"
    )


def final_text(result: dict[str, str | int]) -> str:
    return (
        "# Quarterly sales brief\n\n"
        "## Main finding\n\n"
        f"Revenue grew {result['revenue_growth_percent']}% between the first and last "
        f"quarters, from {result['first_quarter_revenue']} to "
        f"{result['last_quarter_revenue']} sample units. All four quarters "
        "showed higher revenue than the preceding quarter where a comparison exists.\n\n"
        "## Supporting numbers\n\n"
        f"The dataset contains {result['quarters']} quarters and "
        f"{result['customer_quarters']} customer-quarters. The latter sums quarterly "
        "customer counts; it does not count unique people or businesses.\n\n"
        "## Interpretation\n\n"
        "Revenue growth describes sales, not profit. Costs are absent from the sample. "
        "Four quarterly observations do not establish seasonality or support a forecast. "
        "The calculations were checked before this brief was written.\n\n"
        "Local sample data; no live company data or model-generated analysis.\n"
    )
