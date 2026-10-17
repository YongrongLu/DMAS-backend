"""Test configuration

Provided fixtures:
- source:       a small synthetic cleaned-transactions frame with a known story
- views:        the three department views built from it, department -> CSV path
- context:      factory building a skill Context for one department
- skill:        factory loading a skill script module by skill name

The synthetic data (A = Feb-Apr 2010, B = Feb-Apr 2011):
- 12 UK customers 20001-20012 buy every month in A; only 20001-20006 come back in B
- 2 Iceland customers 20101-20102 buy every month in A and B (a group below k=5)
- 4 new UK customers 20201-20204 buy only in B
- SKU 10001 sells only in A (stopped), 10004 only in B (new), 10002 / 10003 in both
- one guest order per month, one return line per period
- trading stops 2010-12-21 .. 2011-01-04 (a closure)
"""

import importlib.util
import os

import pandas as pd
import pytest

from core.data.cli import Context
from core.data.loader import load_frame
from core.departments import get_department
from core.tools._kernel.constants import PROJECT_ROOT, SKILLS_DIR


SKUS = {
    "10001": ("WHITE CHERRY LIGHTS", 2.0),
    "10002": ("RED HEART DOORMAT", 5.0),
    "10003": ("TEA MUG", 1.5),
    "10004": ("NEW LANTERN", 4.0),
}
UK_RETAINED = [str(20000 + i) for i in range(1, 7)]
UK_CHURNED = [str(20000 + i) for i in range(7, 13)]
ICELAND = ["20101", "20102"]
UK_NEW = [str(20200 + i) for i in range(1, 5)]
MONTHS_A = ["2010-02", "2010-03", "2010-04"]
MONTHS_B = ["2011-02", "2011-03", "2011-04"]


def _line(invoice, sku, qty, when, customer, country, *, cancelled=False):
    """One cleaned transaction line."""
    description, price = SKUS[sku]
    return {
        "invoice_id": invoice, "stock_code": sku, "description": description, "quantity": qty,
        "invoice_date": pd.Timestamp(when), "unit_price": price, "customer_id": customer, "country": country,
        "line_amount": round(qty * price, 2), "is_cancellation": cancelled, "is_return": qty < 0,
        "is_valid_sale": qty > 0 and not cancelled,
    }


def build_source() -> pd.DataFrame:
    """The synthetic transactions described in the module docstring."""
    rows, n = [], 500000
    for month in MONTHS_A + ["2010-12", "2011-01"] + MONTHS_B:
        in_b = month in MONTHS_B
        buyers = [(c, "United Kingdom") for c in (UK_RETAINED + UK_NEW if in_b else UK_RETAINED + UK_CHURNED)]
        buyers += [(c, "Iceland") for c in ICELAND]
        day = "20" if month == "2010-12" else "05"
        for i, (customer, country) in enumerate(buyers):
            n += 1
            when = f"{month}-{day} {8 + i % 10:02d}:{i:02d}:00"
            basket = ["10002", "10003", "10004"] if in_b else ["10001", "10002", "10003"]
            for sku in basket:
                rows.append(_line(str(n), sku, 6 if sku != "10002" else 2, when, customer, country))
        n += 1
        rows.append(_line(str(n), "10003", 12, f"{month}-{day} 18:00:00", None, "United Kingdom"))
        if month in ("2010-03", "2011-03"):
            n += 1
            rows.append(_line(f"C{n}", "10003", -3, f"{month}-07 09:00:00", UK_RETAINED[0], "United Kingdom",
                              cancelled=True))
    return pd.DataFrame(rows).sort_values(["invoice_date", "invoice_id"], kind="stable").reset_index(drop=True)


def _load_module(path: str, name: str):
    """Import a Python file that is not on a package path."""
    module_spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def source() -> pd.DataFrame:
    return build_source()


@pytest.fixture(scope="session")
def views(source, tmp_path_factory) -> dict[str, str]:
    builder = _load_module(os.path.join(PROJECT_ROOT, "scripts", "build_department_views.py"), "build_views")
    out_dir = tmp_path_factory.mktemp("devices")
    manifest = builder.write_views(builder.build_views(source), str(out_dir), {})
    return {dept: str(out_dir / info["path"]) for dept, info in manifest["views"].items()}


@pytest.fixture()
def context(views):
    def make(department: str) -> Context:
        spec = get_department(department)
        return Context(spec=spec, df=load_frame(spec, views[department]), data_path=views[department])
    return make


@pytest.fixture(scope="session")
def skill():
    def load(name: str):
        scripts = os.path.join(SKILLS_DIR, name, "scripts")
        script = next(f for f in sorted(os.listdir(scripts)) if f.endswith(".py"))
        return _load_module(os.path.join(scripts, script), f"skill_{name.replace('-', '_')}")
    return load


def run_skill(module, ctx: Context, argv: list[str]) -> dict:
    """Parse argv with the skill's parser and call its run()."""
    return module.run(ctx, module.build_parser().parse_args(argv))
