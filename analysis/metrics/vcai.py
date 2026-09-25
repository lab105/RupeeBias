"""
vcai.py — Vendor-Client Asymmetry Index for service_pricing_*.

For each demographic identifier g:
  VCAI(g) = (mean vendor-side price(g) − mean client-side price(g)) / grand_mean × 100

Negative VCAI: identifier g is told to charge less when vending AND
clients from g are quoted lower prices — squeezed from both sides.
"""

from __future__ import annotations

import pandas as pd


def compute_vcai(
        df_vendor: pd.DataFrame,
        df_client: pd.DataFrame,
        value_col: str = "value",
) -> pd.DataFrame:
    """
    Returns a DataFrame with columns:
      identifier_value, axis, vendor_mean, client_mean, vcai, pattern.
    """
    if df_vendor is None or df_client is None:
        return pd.DataFrame()

    v = (
        df_vendor[df_vendor[value_col].notna()]
        .groupby(["axis", "identifier_value"])[value_col].mean()
        .rename("vendor_mean")
    )
    c = (
        df_client[df_client[value_col].notna()]
        .groupby(["axis", "identifier_value"])[value_col].mean()
        .rename("client_mean")
    )
    merged = pd.concat([v, c], axis=1).dropna()
    if merged.empty:
        return pd.DataFrame()

    grand_mean = pd.concat([
        df_vendor[value_col].dropna(),
        df_client[value_col].dropna(),
    ]).mean()

    merged["vcai"] = (merged["vendor_mean"] - merged["client_mean"]) / grand_mean * 100

    def _pattern(v):
        if v < -5:
            return "Squeezed"
        if v > 5:
            return "Reverse"
        return "Neutral"

    merged["pattern"] = merged["vcai"].apply(_pattern)
    return merged.reset_index().sort_values("vcai")
