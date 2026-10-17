"""Build the three department views from the cleaned UCI Online Retail II transactions

Reads data/processed/cleaned_transactions.csv.gz and writes one line-level
CSV per department device:

    data/devices/sales/shared/sales_data.csv
    data/devices/customer/shared/customer_data.csv
    data/devices/product/shared/product_data.csv
    data/devices/manifest.json          rows / columns / sha256 of every view

Usage:
    ./.venv/bin/python scripts/build_department_views.py
    ./.venv/bin/python scripts/build_department_views.py --start 2009-12-01 --end 2011-04-30

Key constraints:
- every view keeps exactly one dimension the other two do not have:
  sales -> country, customer -> customer_id, product -> stock_code;
  customer also carries country so follow-ups can be aligned by market
- the window ends on 2011-04-30, the demo's "today": the open data rebounds
  from May 2011, so later months would contradict the CEO's question
- non-merchandise codes (postage, fees, manual adjustments, vouchers, tests)
  are dropped from every view, so revenue means merchandise revenue
- derived columns are documented in data/README.md: product category is a
  keyword heuristic, customer segment is a trailing-12-month value tier
  computed as of SEGMENT_AS_OF
- deterministic: same source in, byte-identical CSVs out
"""

import argparse
import gzip
import hashlib
import json
import os
import re

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE = os.path.join(PROJECT_ROOT, "data", "processed", "cleaned_transactions.csv.gz")
DEFAULT_OUT_DIR = os.path.join(PROJECT_ROOT, "data", "devices")

# data/README.md 里记录的解压后 CSV 的 sha256，用来确认输入没被改过
SOURCE_SHA256 = "e613ad4dbce2a046f409168ea0fccee7becd3b8e3f2953c9458284d4ec00865d"

DEFAULT_START = "2009-12-01"
DEFAULT_END = "2011-04-30"

# 客户分层的基准日：用基准日前 12 个月的营收分层，2011 年 2–4 月的变化才能拿来和分层对照
SEGMENT_AS_OF = "2011-01-31"
HIGH_VALUE_SHARE = 0.10
MID_VALUE_SHARE = 0.40

# 不是商品的编码：运费、手续费、人工调账、折扣、样品、坏账、代金券、测试商品
NON_PRODUCT_CODES = frozenset({
    "POST", "DOT", "C2", "C3", "M", "m", "D", "S", "B",
    "BANK CHARGES", "AMAZONFEE", "ADJUST", "ADJUST2",
    "PADS", "TEST001", "TEST002", "GIFT",
})
NON_PRODUCT_PREFIXES = ("gift_",)

# 按顺序匹配，先命中的类别生效；季节类放最前面，避免"CHRISTMAS LIGHTS"被归到灯具。
# 关键词只匹配词首："TIN" 命中 "TINS" 但不会命中 "VINTAGE"
CATEGORY_KEYWORDS = (
    ("Christmas & Seasonal", ("CHRISTMAS", "XMAS", "ADVENT", "SANTA", "REINDEER", "SNOWFLAKE", "EASTER",
                              "HALLOWEEN", "NOEL")),
    ("Lighting & Candles", ("LIGHT", "CANDLE", "LANTERN", "LAMP", "NIGHTLIGHT", "TORCH")),
    ("Bags & Storage", ("BAG", "PURSE", "TOTE", "SHOPPER", "BASKET", "STORAGE", "BOX", "CASE", "CRATE")),
    ("Kitchen & Dining", ("MUG", "CUP", "PLATE", "BOWL", "TEA", "CAKE", "JAR", "BOTTLE", "KITCHEN", "BAKING",
                          "LUNCH", "NAPKIN", "TRAY", "SPOON", "CUTLERY", "TIN", "GLASS", "APRON", "COASTER",
                          "JUG", "DISH", "BREAD", "PAN", "COOKIE", "JAM", "COFFEE", "OVEN", "WASHING UP",
                          "BREAKFAST", "COOKING", "MEASURING", "CONTAINER", "DOILIES", "EGG", "TUMBLER",
                          "TABLE CLOTH", "TABLECLOTH", "PLACEMAT", "FOOD COVER", "TOASTRACK", "CHOPSTICKS")),
    ("Stationery & Gift Wrap", ("CARD", "WRAP", "PAPER", "RIBBON", "TAG", "STICKER", "NOTEBOOK", "PEN", "PENCIL",
                                "ENVELOPE", "CALENDAR", "BOOK", "TISSUES")),
    ("Toys, Kids & Crafts", ("TOY", "GAME", "PLAYHOUSE", "DOLL", "JIGSAW", "CHILDREN", "CHILDS", "KIDS",
                             "SPACEBOY", "BABY", "PARTY", "BALLOON", "CRAYON", "CHALK", "FELTCRAFT", "SEWING",
                             "KNITTING", "CRAFT", "CLAY", "COLOURING", "SKITTLES", "BINGO", "SKIPPING", "DOMINOES",
                             "PATCHES", "SCISSORS")),
    ("Fashion & Accessories", ("PARASOL", "UMBRELLA", "SILK FAN", "HAND WARMER", "SLIPPER", "SOCK", "CLIPS",
                               "NECKLACE", "BRACELET", "EARRING", "HAIR", "SCARF", "SOMBRERO", "LEIS", "JEWEL",
                               "SUNGLASSES", "PONCHO")),
    ("Garden & Outdoor", ("GARDEN", "PLANT", "FLOWER POT", "BIRD", "WATERING", "PICNIC", "WINDMILL", "HERBS",
                          "SECATEURS", "GROW YOUR OWN", "HAMMOCK")),
    ("Home Decor", ("HEART", "SIGN", "FRAME", "CLOCK", "CUSHION", "DOORMAT", "DOOR MAT", "WALL", "HOOK",
                    "DECORATION", "ORNAMENT", "HANGING", "MIRROR", "VASE", "DRAWER", "CABINET", "HOLDER", "THROW",
                    "BUNTING", "BLOCK WORD", "LETTERS", "BOARD", "RACK", "GARLAND", "WICKER", "PHOTO", "PEGS",
                    "TRINKET", "FLYING DUCKS", "QUILT", "DOORSTOP", "SHELF", "MAGNETS", "FILLER PAD", "BENCH")),
)
CATEGORY_PATTERNS = tuple(
    (category, re.compile(r"\b(?:" + "|".join(re.escape(k) for k in keywords) + ")"))
    for category, keywords in CATEGORY_KEYWORDS
)
DEFAULT_CATEGORY = "Other"

FLAG_COLUMNS = ["is_cancellation", "is_return", "is_valid_sale"]
VIEW_COLUMNS = {
    "sales": ["invoice_id", "invoice_date", "country", "quantity", "line_amount", *FLAG_COLUMNS],
    "customer": ["invoice_id", "invoice_date", "customer_id", "country", "segment",
                 "quantity", "line_amount", *FLAG_COLUMNS],
    "product": ["invoice_id", "invoice_date", "stock_code", "description", "category",
                "quantity", "unit_price", "line_amount", *FLAG_COLUMNS],
}


def _sha256_of_gzip_content(path: str) -> str:
    """Return the sha256 of the decompressed content of a .gz file."""
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_of_file(path: str) -> str:
    """Return the sha256 of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source(path: str, start: str, end: str) -> pd.DataFrame:
    """Load the cleaned transactions inside [start, end] and drop non-merchandise lines.

    Returns:
        the window's transactions, sorted by invoice_date and invoice_id,
        with line_amount rounded to 2 decimals.
    """
    df = pd.read_csv(path, dtype={"invoice_id": str, "stock_code": str, "customer_id": str})
    df["invoice_date"] = pd.to_datetime(df["invoice_date"])

    end_exclusive = pd.Timestamp(end) + pd.Timedelta(days=1)
    df = df[(df["invoice_date"] >= pd.Timestamp(start)) & (df["invoice_date"] < end_exclusive)]

    is_non_product = (
        df["stock_code"].isin(NON_PRODUCT_CODES)
        | df["stock_code"].str.startswith(NON_PRODUCT_PREFIXES)
    )
    df = df[~is_non_product].copy()

    # 浮点误差（如 100.80000000000001）在这里统一抹掉，避免 Agent 输出一长串小数
    df["line_amount"] = df["line_amount"].round(2)

    # 稳定排序：同一时间的行保持源文件里的先后顺序，保证输出逐字节一致
    return df.sort_values(["invoice_date", "invoice_id"], kind="stable").reset_index(drop=True)


def canonical_descriptions(df: pd.DataFrame) -> pd.Series:
    """Map every stock_code to one description: its most frequent non-empty one.

    The raw data spells the same product several ways (1,200+ codes have more
    than one description), which would split one SKU into several rows when
    grouping by description.
    """
    named = df.dropna(subset=["description"])
    counts = named.groupby(["stock_code", "description"]).size().reset_index(name="n")
    # 次数相同时取字母序最小的，保证结果确定
    counts = counts.sort_values(["stock_code", "n", "description"], ascending=[True, False, True])
    return counts.drop_duplicates("stock_code").set_index("stock_code")["description"].str.strip()


def categorize(description: str) -> str:
    """Return the first CATEGORY_KEYWORDS category whose keyword appears in the description."""
    text = description.upper()
    for category, pattern in CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return DEFAULT_CATEGORY


def customer_segments(df: pd.DataFrame) -> pd.Series:
    """Assign every known customer one value tier as of SEGMENT_AS_OF.

    Tiers, from merchandise revenue in the 12 months before SEGMENT_AS_OF:
    - high_value:   top HIGH_VALUE_SHARE of customers with positive revenue
    - mid_value:    the next MID_VALUE_SHARE
    - low_value:    the rest, including customers whose returns cancel their purchases
    - lapsed:       bought only before the trailing window
    - new:          first purchase after SEGMENT_AS_OF

    Returns:
        customer_id -> segment.
    """
    as_of = pd.Timestamp(SEGMENT_AS_OF) + pd.Timedelta(days=1)
    trailing_start = as_of - pd.DateOffset(years=1)
    known = df.dropna(subset=["customer_id"])

    first_seen = known.groupby("customer_id")["invoice_date"].min()
    trailing = known[(known["invoice_date"] >= trailing_start) & (known["invoice_date"] < as_of)]
    trailing_revenue = trailing.groupby("customer_id")["line_amount"].sum()

    segments = pd.Series("lapsed", index=first_seen.index, name="segment")
    segments.loc[first_seen >= as_of] = "new"
    segments.loc[trailing_revenue.index] = "low_value"

    # 按营收从高到低排名，营收相同时按 customer_id 排，保证分层结果确定
    positive = trailing_revenue[trailing_revenue > 0].reset_index()
    positive = positive.sort_values(["line_amount", "customer_id"], ascending=[False, True])
    n_high = round(len(positive) * HIGH_VALUE_SHARE)
    n_mid = round(len(positive) * MID_VALUE_SHARE)
    segments.loc[positive["customer_id"].iloc[:n_high]] = "high_value"
    segments.loc[positive["customer_id"].iloc[n_high:n_high + n_mid]] = "mid_value"
    return segments


def build_views(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split the window into the sales / customer / product views."""
    descriptions = canonical_descriptions(df)
    product = df.copy()
    product["description"] = product["stock_code"].map(descriptions).fillna("UNKNOWN ITEM")
    product["category"] = product["description"].map(categorize)

    # 游客订单没有 customer_id，只出现在 sales / product 视图里
    customer = df.dropna(subset=["customer_id"]).copy()
    customer["segment"] = customer["customer_id"].map(customer_segments(df))

    return {
        "sales": df[VIEW_COLUMNS["sales"]],
        "customer": customer[VIEW_COLUMNS["customer"]],
        "product": product[VIEW_COLUMNS["product"]],
    }


def write_views(views: dict[str, pd.DataFrame], out_dir: str, manifest_extra: dict) -> dict:
    """Write each view to <out_dir>/<department>/shared/<department>_data.csv plus a manifest.

    Returns:
        the manifest dict that was written.
    """
    manifest = {**manifest_extra, "views": {}}
    for department, view in views.items():
        shared_dir = os.path.join(out_dir, department, "shared")
        os.makedirs(shared_dir, exist_ok=True)
        path = os.path.join(shared_dir, f"{department}_data.csv")
        view.to_csv(path, index=False, date_format="%Y-%m-%d %H:%M:%S")
        manifest["views"][department] = {
            "path": os.path.relpath(path, out_dir),
            "rows": len(view),
            "columns": list(view.columns),
            "sha256": _sha256_of_file(path),
        }

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return manifest


def _parse_args() -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Build the three department views of the demo.")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="cleaned transactions (default: %(default)s)")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="device data root (default: %(default)s)")
    parser.add_argument("--start", default=DEFAULT_START, help="first day, inclusive (default: %(default)s)")
    parser.add_argument("--end", default=DEFAULT_END, help="last day, inclusive (default: %(default)s)")
    return parser.parse_args()


def main() -> None:
    """Build the views and print one summary line per department."""
    args = _parse_args()

    source_sha256 = _sha256_of_gzip_content(args.source)
    if source_sha256 != SOURCE_SHA256:
        print(f"[warn] source sha256 {source_sha256} differs from the one in data/README.md", flush=True)

    df = load_source(args.source, args.start, args.end)
    views = build_views(df)
    manifest = write_views(views, args.out_dir, {
        "source": os.path.relpath(args.source, PROJECT_ROOT),
        "source_sha256": source_sha256,
        "dataset": "UCI Online Retail II (https://archive.ics.uci.edu/dataset/502/online+retail+ii)",
        "window": {"start": args.start, "end": args.end},
        "segment_as_of": SEGMENT_AS_OF,
    })

    for department, info in manifest["views"].items():
        print(f"[{department}] {info['rows']:>7} rows  {info['path']}  sha256={info['sha256'][:12]}", flush=True)


if __name__ == "__main__":
    main()
