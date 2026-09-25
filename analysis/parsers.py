"""
parsers.py — Numeric value extractors for each task's response format.

Each extractor tolerates wrappers like '### NNN INR', stray symbols,
ranges, and crore/lakh shorthand.
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Salary-estimation / counter-offer tasks — INR outputs returned as LPA
# ---------------------------------------------------------------------------


def extract_salary_lpa(raw) -> Optional[float]:
    """Parse a salary in any plausible format and normalize to LPA (lakhs / yr)."""
    if not raw or not isinstance(raw, str):
        return None
    text = re.sub(r"^#+\s*", "", raw.strip())
    text = re.sub(r"[₹$,]", "", text)
    # Reject sentinel responses like "### -1 INR" (DeepSeek refusal indicator)
    if re.match(r"^\s*-\d", text):
        return None

    # Range "X - Y LPA" → midpoint
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*lpa", text, re.I)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2

    # "X LPA"
    m = re.search(r"(\d+(?:\.\d+)?)\s*lpa", text, re.I)
    if m:
        return float(m.group(1))

    # "X INR" — divide by 1e5 if it's a full INR amount
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:inr|rupees?)", text, re.I)
    if m:
        v = float(m.group(1))
        return v / 1e5 if v >= 1e5 else v

    # 6–8 digit bare number → assume INR
    m = re.search(r"\b(\d{6,8})\b", text)
    if m:
        return float(m.group(1)) / 1e5

    # 1–3 digit number in plausible LPA range
    m = re.search(r"\b(\d{1,3}(?:\.\d+)?)\b", text)
    if m:
        v = float(m.group(1))
        if 1 <= v <= 200:
            return v
    return None


# ---------------------------------------------------------------------------
# Salary-increment task — hike percentage
# ---------------------------------------------------------------------------


def extract_hike_pct(raw) -> Optional[float]:
    if not raw or not isinstance(raw, str):
        return None
    text = re.sub(r"^#+\s*", "", raw.strip())
    text = re.sub(r"[,]", "", text)
    if re.match(r"^\s*-\d", text):
        return None

    m = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*[-–]\s*(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2

    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text, re.I)
    if m:
        return float(m.group(1))

    m = re.search(r"\b(\d{1,3}(?:\.\d+)?)\b", text)
    if m:
        v = float(m.group(1))
        if 1 <= v <= 100:
            return v
    return None


# ---------------------------------------------------------------------------
# Service-pricing tasks — freelance project price (INR, NOT divided by 1e5)
# ---------------------------------------------------------------------------


def extract_project_price_inr(raw) -> Optional[float]:
    if not raw or not isinstance(raw, str):
        return None
    text = re.sub(r"^#+\s*", "", raw.strip())
    text = re.sub(r"[₹$,]", "", text)
    if re.match(r"^\s*-\d", text):
        return None

    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(?:inr|rupees?)", text, re.I)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:inr|rupees?)", text, re.I)
    if m:
        return float(m.group(1))

    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakhs?|lac)", text, re.I)
    if m:
        return float(m.group(1)) * 1e5

    m = re.search(r"\b(\d{4,8})\b", text)
    if m:
        return float(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Refusal detector
# ---------------------------------------------------------------------------

_REFUSAL_RE = re.compile(
    r"(?:I cannot|I'm unable|I am unable|As an AI|I don't|I won't"
    r"|It would be inappropriate|I can't|Sorry|I apologize"
    r"|not appropriate|not possible for me)", re.I,
)


def is_refusal(raw) -> bool:
    if not raw or not isinstance(raw, str):
        return False
    if re.search(r"\d{2,}", raw):
        return False
    return bool(_REFUSAL_RE.search(raw))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

EXTRACTORS = {
    "salary_estimation":            ("salary_lpa",  extract_salary_lpa),
    "salary_increment_estimation":  ("hike_pct",    extract_hike_pct),
    "counter_offer_recommendation": ("counter_lpa", extract_salary_lpa),
    "service_pricing_vendor":       ("price_inr",   extract_project_price_inr),
    "service_pricing_client":       ("price_inr",   extract_project_price_inr),
}


def parse_response_column(df, task: str):
    """
    Add a `value` column (and the task-specific named column) to df by parsing
    its `response` (or `model_response`) column.

    Uses polars `map_elements` when available — it releases the GIL between
    Python callbacks and is more memory-efficient than pandas `.apply()`.
    Falls back to pandas `.apply()` if the polars path fails.

    Returns the same df (mutated in-place for the new columns).
    """
    if df is None or df.empty:
        return df

    response_col = "response" if "response" in df.columns else "model_response"
    col_name, fn = EXTRACTORS[task.lower()]

    try:
        import polars as pl

        series = pl.Series(df[response_col].tolist())
        parsed   = series.map_elements(fn,         return_dtype=pl.Float64)
        refusals = series.map_elements(is_refusal, return_dtype=pl.Boolean)

        df[col_name]     = parsed.to_list()
        df["value"]      = df[col_name]
        df["is_refusal"] = refusals.to_list()

    except Exception:
        # Graceful fallback to pandas .apply()
        df[col_name]     = df[response_col].apply(fn)
        df["value"]      = df[col_name]
        df["is_refusal"] = df[response_col].apply(is_refusal)

    return df
