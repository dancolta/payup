"""Escalation tiering. Pure, deterministic, config-driven.

Given how overdue an invoice is, how many times we already chased it, and how
long since the last chase, decide which reminder tier to send next (or hold).
This is the heart of "polite but escalating, and never double-nag".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["Tier", "EscalationConfig", "select_tier"]


class Tier(str, Enum):
    GENTLE = "gentle"
    FIRM = "firm"
    FINAL = "final"


@dataclass(frozen=True)
class EscalationConfig:
    """Thresholds for tier selection. Defaults are the shipped policy."""

    min_gap_days: int = 7          # never chase the same invoice twice inside this window
    gentle_max_days: int = 14      # 1..gentle_max overdue, no prior -> gentle
    firm_max_days: int = 30        # gentle_max+1..firm_max overdue -> firm
    final_min_priors: int = 2      # this many prior reminders forces final

    @classmethod
    def load(cls, path: str | None = None) -> EscalationConfig:
        """Load from a YAML file if pyyaml + path are available, else defaults."""
        if not path:
            return cls()
        try:
            import yaml  # optional; only present in the bot/dev extras
        except Exception:
            return cls()
        try:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except FileNotFoundError:
            return cls()
        return cls(
            min_gap_days=int(data.get("min_gap_days", cls.min_gap_days)),
            gentle_max_days=int(data.get("gentle_max_days", cls.gentle_max_days)),
            firm_max_days=int(data.get("firm_max_days", cls.firm_max_days)),
            final_min_priors=int(data.get("final_min_priors", cls.final_min_priors)),
        )


def select_tier(
    days_overdue: int,
    prior_count: int,
    days_since_last: int | None,
    cfg: EscalationConfig,
) -> Tier | None:
    """Return the tier to send, or None to hold.

    Rules:
      * not overdue (days_overdue < 1)            -> None
      * chased within min_gap_days                -> None (hold)
      * 31+ days overdue OR >= final_min_priors   -> FINAL
      * 15-30 days overdue OR >= 1 prior          -> FIRM
      * 1-14 days overdue, 0 prior                -> GENTLE
    """
    if days_overdue < 1:
        return None
    if days_since_last is not None and days_since_last < cfg.min_gap_days:
        return None
    if prior_count >= cfg.final_min_priors or days_overdue > cfg.firm_max_days:
        return Tier.FINAL
    if prior_count >= 1 or days_overdue > cfg.gentle_max_days:
        return Tier.FIRM
    return Tier.GENTLE
