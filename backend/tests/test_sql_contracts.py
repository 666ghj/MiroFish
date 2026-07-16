import re
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

BASE_27 = [
    "ticker", "name", "sector", "industry", "scale_marketcap", "exchange",
    "is_delisted", "latest_annual_date", "revenue_annual", "net_income_annual",
    "revenue_ttm", "net_income_ttm", "eps_diluted_ttm", "free_cash_flow_ttm",
    "net_margin", "gross_margin", "roe", "market_cap", "pe", "ps", "pb",
    "enterprise_value", "debt", "cash", "equity", "ebitda", "revenue_yoy_pct",
    "earnings_yoy_pct", "pe_percentile_in_sector", "ps_percentile_in_sector",
    "roe_percentile_in_sector", "institutional_total_value",
    "institutional_holder_count", "institutional_top5_concentration_pct",
]


def _final_select(sql: str) -> str:
    m = re.search(r"(?m)^SELECT$", sql)
    assert m, "no top-level SELECT found; file does not parse as a CTE query"
    return sql[m.start():]


def _has_alias(final_select: str, alias: str) -> bool:
    return re.search(rf"\bAS\s+{re.escape(alias)}\b", final_select, re.IGNORECASE) is not None


def test_screen_selects_base_27_and_quarterly_trend():
    sql = (SQL_DIR / "dossier_screen.sql").read_text()
    fs = _final_select(sql)
    for alias in BASE_27:
        assert _has_alias(fs, alias), f"screen missing alias: {alias}"
    assert _has_alias(fs, "quarterly_trend"), "screen missing quarterly_trend"
    assert "{ticker:String}" in sql, "screen must be parameterized by ticker"
    assert "{holding_quarter" not in sql, "screen must not reference holding_quarter"


def test_deepdive_is_strict_superset_of_screen():
    screen_fs = _final_select((SQL_DIR / "dossier_screen.sql").read_text())
    deepdive_fs = _final_select((SQL_DIR / "dossier_deepdive.sql").read_text())
    screen_aliases = set(re.findall(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\b", screen_fs, re.IGNORECASE))
    assert screen_aliases, "no aliases found in screen final SELECT"
    for alias in screen_aliases:
        assert _has_alias(deepdive_fs, alias), f"deepdive missing screen alias: {alias}"
    for extra in ("top_holders", "ownership_trend"):
        assert _has_alias(deepdive_fs, extra), f"deepdive missing extra alias: {extra}"


def test_deepdive_universe_orders_by_market_cap_desc_with_limit():
    sql = (SQL_DIR / "deepdive_universe.sql").read_text()
    assert re.search(r"ORDER\s+BY\s+market_cap\s+DESC", sql, re.IGNORECASE), \
        "deep-dive universe must ORDER BY market_cap DESC"
    assert re.search(r"\bLIMIT\b", sql, re.IGNORECASE), \
        "deep-dive universe must have a LIMIT"
    assert "{limit:UInt32}" in sql, \
        "deep-dive universe must be parameterized by {limit:UInt32}"
    # deterministic secondary sort on ticker (no alphabetical tie-break ambiguity)
    assert re.search(r"ORDER\s+BY\s+market_cap\s+DESC\s*,\s*ticker", sql, re.IGNORECASE), \
        "deep-dive universe needs a deterministic secondary sort on ticker"
    # null-safe: marketcap filtered non-null so market_cap column cannot be null
    assert re.search(r"marketcap\s*>\s*0", sql, re.IGNORECASE), \
        "deep-dive universe must filter marketcap > 0 to avoid nullable-column failures"
    assert re.search(r"isdelisted\s*=\s*'N'", sql, re.IGNORECASE), \
        "deep-dive universe must restrict to non-delisted companies"


def test_param_arity():
    screen = (SQL_DIR / "dossier_screen.sql").read_text()
    deepdive = (SQL_DIR / "dossier_deepdive.sql").read_text()
    assert "{ticker:String}" in screen and "{holding_quarter" not in screen, \
        "screen must use only {ticker:String}"
    assert "{ticker:String}" in deepdive and "{holding_quarter:Date}" in deepdive, \
        "deepdive must use both {ticker:String} and {holding_quarter:Date}"
