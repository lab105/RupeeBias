"""
config.py — Static configuration for the analysis pipeline.

  - MODELS         : canonical list of model slugs included in tables/figures.
  - LICENSE        : closed/open classification for color schemes.
  - CANONICAL_PAIRS: pre-specified privileged vs marginalized identifier per axis.
  - REAL_WORLD_GAPS: PLFS reference gaps for context (kept for future use).
  - Paths          : where runs live, where outputs go.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT          = Path(__file__).resolve().parent.parent
RUNS_DIR      = ROOT / "runs"
MISC_DIR      = ROOT / "misc"
OUT_DIR       = ROOT / "paper_analysis"
TABLES_DIR    = OUT_DIR / "tables"
FIGURES_DIR   = OUT_DIR / "figures"

# ---------------------------------------------------------------------------
# Models — order = leaderboard display order
# ---------------------------------------------------------------------------

MODELS: list[str] = [
    # Closed-source
    "claude-opus-4.7",
    "claude-haiku-4.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gemini-3-flash",
    # Open-source
    "kimi-k2.5",
    "deepseek-v3.2",
    "glm-5.1",
    "sarvam-105b",
]

LICENSE: dict[str, str] = {
    "claude-opus-4.7":  "closed",
    "claude-haiku-4.5": "closed",
    "gpt-5.4":          "closed",
    "gpt-5.4-mini":     "closed",
    "gemini-3-flash":   "closed",
    "kimi-k2.5":        "open",
    "deepseek-v3.2":    "open",
    "glm-5.1":          "open",
    "sarvam-105b":      "open",
}

# Display palettes — red shades for closed, blue shades for open.
# Indices align with MODELS order within each license group.
CLOSED_PALETTE = ["#7B1212", "#A82020", "#C94040", "#D86D6D", "#E89B9B"]
OPEN_PALETTE   = ["#0F2F66", "#1E4D8C", "#3A6FA8", "#6090C2"]


def color_for(model: str) -> str:
    """Pick a palette color for a model based on license + position."""
    license_ = LICENSE.get(model, "open")
    palette = CLOSED_PALETTE if license_ == "closed" else OPEN_PALETTE
    same_license = [m for m in MODELS if LICENSE.get(m) == license_]
    idx = same_license.index(model) if model in same_license else 0
    return palette[idx % len(palette)]


# ---------------------------------------------------------------------------
# Canonical pairs (privileged, marginalized)
# ---------------------------------------------------------------------------

CANONICAL_PAIRS: dict[str, tuple[str, str]] = {
    "Religion":    ("Hindu",         "Muslim"),
    "Caste":       ("Brahmin",       "Dalit"),
    "Region":      ("Gujarati",      "Santhali"),
    "Gender":      ("Male",          "Female"),
    "Disability":  ("No disability", "Intellectual disability"),
    "Urban/Rural": ("Tier 1 city",   "Village"),
}

AXES: list[str] = list(CANONICAL_PAIRS)

# PLFS reference (real-world wage gaps, %) — used for context/abstract framing.
REAL_WORLD_GAPS: dict[str, float] = {
    "Religion": 32.8,
    "Caste":    24.7,
    "Gender":   25.8,
}

# ---------------------------------------------------------------------------
# Bootstrap / CI defaults
# ---------------------------------------------------------------------------

N_BOOT = 2000
ALPHA  = 0.05
