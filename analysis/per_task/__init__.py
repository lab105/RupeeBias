"""
per_task — one module per RupeeBias task plus the cross-task VCAI bridge.

Each module exposes a `run(models, lang)` function returning a dict of named
DataFrames suitable for direct CSV export.
"""

from analysis.per_task import (
    counter_offer_recommendation,
    salary_estimation,
    salary_increment_estimation,
    service_pricing_client,
    service_pricing_vcai,
    service_pricing_vendor,
)

__all__ = [
    "salary_estimation",
    "salary_increment_estimation",
    "counter_offer_recommendation",
    "service_pricing_vendor",
    "service_pricing_client",
    "service_pricing_vcai",
]
