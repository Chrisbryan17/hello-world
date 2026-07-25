from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


class LiveTradingDisabledError(RuntimeError):
    """Raised whenever the process is asked to enable real-money submission."""


@dataclass(frozen=True, slots=True)
class TradingConfig:
    mode: str = "shadow"
    tick_size: Decimal = Decimal("0.01")
    max_book_age_ms: int = 2_000
    max_feed_age_ms: int = 5_000
    max_daily_loss: Decimal = Decimal("25")
    max_orphan_exposure: Decimal = Decimal("0")


def load_config(env: Mapping[str, str] | None = None) -> TradingConfig:
    values = dict(env or {})
    mode = str(values.get("TRADING_MODE", "shadow")).strip().lower()
    if mode not in {"shadow", "live"}:
        raise ValueError("TRADING_MODE must be 'shadow' or 'live'")
    # Deliberately stronger than an arm token: this research checkpoint has no
    # network-capable live implementation. Credentials cannot override it.
    if mode == "live":
        raise LiveTradingDisabledError(
            "live trading is disabled until prospective admission and a separately reviewed release"
        )
    return TradingConfig(
        mode="shadow",
        tick_size=Decimal(str(values.get("TICK_SIZE", "0.01"))),
        max_book_age_ms=int(values.get("MAX_BOOK_AGE_MS", "2000")),
        max_feed_age_ms=int(values.get("MAX_FEED_AGE_MS", "5000")),
        max_daily_loss=Decimal(str(values.get("MAX_DAILY_LOSS", "25"))),
        max_orphan_exposure=Decimal(str(values.get("MAX_ORPHAN_EXPOSURE", "0"))),
    )
