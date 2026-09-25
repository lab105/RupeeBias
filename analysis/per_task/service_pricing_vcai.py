"""service_pricing_vcai — Vendor-Client Asymmetry Index across the two sides."""

from __future__ import annotations

import pandas as pd

from analysis.io import load_concat
from analysis.metrics.vcai import compute_vcai
from analysis.parsers import parse_response_column


def run(models: list[str], lang: str = "en") -> dict[str, pd.DataFrame]:
    """Bridge between the two service_pricing_* tasks: VCAI."""
    df_v = load_concat(models, "service_pricing_vendor", lang=lang)
    df_c = load_concat(models, "service_pricing_client", lang=lang)
    if df_v.empty or df_c.empty:
        return {}
    df_v = parse_response_column(df_v, "service_pricing_vendor")
    df_c = parse_response_column(df_c, "service_pricing_client")
    return {"service_pricing_vcai": compute_vcai(df_v, df_c, value_col="value")}
