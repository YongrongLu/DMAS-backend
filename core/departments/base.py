"""Department definitions -- the single source of truth for each department

Classes provided:
- Metric:               one named metric computed from a department view
- DepartmentSpec:       one department: data file, dimensions, metrics, privacy policy

Constants provided:
- TIME_DIMENSIONS:      date / week / month, derived from the date column of every view
- FLAG_COLUMNS:         row flags every view carries
- REVENUE / ORDERS / LINES / UNITS / AOV:    metrics shared by several departments

Key constraints:
- every metric is computed on one row set, valid sales or return lines;
  ratio metrics are always a ratio of sums, never a mean of per-row ratios
- dimensions are the only columns a skill may group or filter by;
  restricted columns (personal data, row-level identifiers) are denied
  outright instead of reported as unknown
- a decomposition (metric -> (volume, rate)) must satisfy metric = volume x rate,
  e.g. revenue = orders x aov
"""

from dataclasses import dataclass, field
from typing import Literal, Mapping


TIME_DIMENSIONS = {
    "date": "calendar day, YYYY-MM-DD",
    "week": "week starting on Monday, YYYY-MM-DD",
    "month": "calendar month, YYYY-MM",
}
FLAG_COLUMNS = ("is_cancellation", "is_return", "is_valid_sale")


@dataclass(frozen=True)
class Metric:
    """One named metric of a department view.

    Attributes:
        name:           the name skills accept, e.g. "revenue".
        kind:           sum / nunique / count (number of lines) / median / ratio.
        column:         source column for sum, nunique and median.
        rows:           "valid" for valid sales, "returns" for return lines.
        negate:         flip the sign; return quantities are negative in the data.
        numerator:      ratio only, name of the numerator metric.
        denominator:    ratio only, name of the denominator metric.
        description:    one line shown to the agent.
    """
    name: str
    kind: Literal["sum", "nunique", "count", "median", "ratio"]
    column: str | None = None
    rows: Literal["valid", "returns"] = "valid"
    negate: bool = False
    numerator: str | None = None
    denominator: str | None = None
    description: str = ""

    @property
    def additive(self) -> bool:
        """Whether group values add up to the total, so shares of a change make sense."""
        return self.kind in ("sum", "count")


@dataclass(frozen=True)
class DepartmentSpec:
    """Everything the data layer and the skills need to know about one department.

    Attributes:
        name:               "sales" / "customer" / "product"; also the agent role
                            and the subagent_id prefix.
        display_name:       e.g. "Sales Department".
        csv_name:           file name of the department view.
        dimensions:         column -> description; the columns skills may group or filter by.
        metrics:            metric name -> Metric.
        label_columns:      group column -> display column added to results,
                            e.g. stock_code -> description.
        restricted_columns: column -> why it never leaves the device.
        entity_column:      the column identifying a person, used for
                            k-anonymity and retention; None when the view has none.
        k_anon_min:         groups with fewer distinct entities are suppressed.
        decompositions:     metric -> (volume metric, rate metric) with metric = volume x rate.
        record_label:       what a raw row is, used in the denial message, e.g. "customer-level".
        capability:         the capability card sent to the orchestrator.
        example_questions:  questions this department answers well.
        date_column:        the timestamp column of the view.
    """
    name: str
    display_name: str
    csv_name: str
    dimensions: Mapping[str, str]
    metrics: Mapping[str, Metric]
    label_columns: Mapping[str, str] = field(default_factory=dict)
    restricted_columns: Mapping[str, str] = field(default_factory=dict)
    entity_column: str | None = None
    k_anon_min: int = 5
    decompositions: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    record_label: str = "transaction-level"
    capability: str = ""
    example_questions: tuple[str, ...] = ()
    date_column: str = "invoice_date"

    @property
    def group_columns(self) -> dict[str, str]:
        """Every column skills may group by: the dimensions plus the time dimensions."""
        return {**self.dimensions, **TIME_DIMENSIONS}

    @property
    def required_columns(self) -> list[str]:
        """Every column the view must contain."""
        columns = {self.date_column, *FLAG_COLUMNS, *self.dimensions, *self.label_columns.values(),
                   *self.restricted_columns}
        columns.update(m.column for m in self.metrics.values() if m.column)
        return sorted(columns)


REVENUE = Metric("revenue", "sum", column="line_amount", description="merchandise revenue of valid sales (GBP)")
ORDERS = Metric("orders", "nunique", column="invoice_id", description="number of distinct invoices with a valid sale")
LINES = Metric("lines", "count", description="number of valid order lines")
UNITS = Metric("units", "sum", column="quantity", description="units sold in valid sales")
AOV = Metric("aov", "ratio", numerator="revenue", denominator="orders", description="average order value = revenue / orders")
