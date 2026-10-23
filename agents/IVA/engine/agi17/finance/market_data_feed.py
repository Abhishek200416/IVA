"""AGI 1.7 BANK NIFTY Market Data Feed & Multi-Regime Candle Ingestion Engine.

Provides:
1. Resampling of 1-minute market bars to 5-minute bars.
2. Intraday indicators: Volume Weighted Average Price (VWAP) and 20-period Exponential Moving Average (EMA).
3. Deterministic synthetic fixture generation for Indian market regimes:
   - BULLISH_TRENDING (+500 to +700 points rally)
   - SIDEWAYS_RANGING (tight 120-point oscillating band, high theta decay)
   - VOLATILE_BREAKDOWN (-600 to -800 points drop, IV expansion)
4. Synchronized option chain generation with analytical Black-Scholes Greeks.
5. Strict temporal validation and JSON persistence in runtime storage.
"""

from __future__ import annotations

import datetime
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bank_nifty_backtest import MarketBar, MarketSnapshot, OptionChainQuote
from .bank_nifty_market import BankNiftyContractSpec, BankNiftyMarketCalendar
from .options_math import OptionsMath


def resample_1min_to_5min(bars_1min: Sequence[MarketBar]) -> List[MarketBar]:
    """Resamples a sequential series of 1-minute bars into 5-minute bars."""
    if not bars_1min:
        return []

    bars_5min: List[MarketBar] = []
    chunk: List[MarketBar] = []

    for bar in bars_1min:
        chunk.append(bar)
        if len(chunk) == 5:
            open_p = chunk[0].open
            high_p = max(b.high for b in chunk)
            low_p = min(b.low for b in chunk)
            close_p = chunk[-1].close
            vol = sum(b.volume for b in chunk)
            ts = chunk[0].timestamp_ist  # Bar timestamp anchored to start of interval
            bars_5min.append(MarketBar(ts, open_p, high_p, low_p, close_p, vol))
            chunk = []

    # Residual bars if any
    if chunk:
        open_p = chunk[0].open
        high_p = max(b.high for b in chunk)
        low_p = min(b.low for b in chunk)
        close_p = chunk[-1].close
        vol = sum(b.volume for b in chunk)
        ts = chunk[0].timestamp_ist
        bars_5min.append(MarketBar(ts, open_p, high_p, low_p, close_p, vol))

    return bars_5min


def calculate_intraday_vwap(bars: Sequence[MarketBar]) -> List[float]:
    """Calculates cumulative Volume Weighted Average Price (VWAP) for each bar.
    
    Resets at day boundaries based on the timestamp date.
    """
    vwap_series: List[float] = []
    cum_vol = 0.0
    cum_tp_vol = 0.0
    last_date: Optional[str] = None

    for b in bars:
        cur_date = b.timestamp_ist.split(" ")[0]
        if last_date != cur_date:
            cum_vol = 0.0
            cum_tp_vol = 0.0
            last_date = cur_date

        typical_price = (b.high + b.low + b.close) / 3.0
        v = float(b.volume) if b.volume > 0 else 1.0
        cum_vol += v
        cum_tp_vol += typical_price * v

        vwap_series.append(round(cum_tp_vol / cum_vol, 2))

    return vwap_series


def calculate_ema(prices: Sequence[float], period: int = 20) -> List[float]:
    """Calculates Exponential Moving Average (EMA) over a price series."""
    if not prices:
        return []
    if len(prices) < period:
        # Fallback to cumulative average if fewer than period bars
        res: List[float] = []
        c = 0.0
        for i, p in enumerate(prices):
            c += p
            res.append(round(c / (i + 1), 2))
        return res

    multiplier = 2.0 / (period + 1.0)
    ema_series: List[float] = []

    # First value is Simple Moving Average (SMA) of the initial window
    sma = sum(prices[:period]) / period
    for i in range(period - 1):
        # Fill warm-up with progressive mean
        sub_sma = sum(prices[: i + 1]) / (i + 1)
        ema_series.append(round(sub_sma, 2))

    ema_series.append(round(sma, 2))
    current_ema = sma

    for p in prices[period:]:
        current_ema = (p - current_ema) * multiplier + current_ema
        ema_series.append(round(current_ema, 2))

    return ema_series


class MarketDataFeed:
    """Manages generation, ingestion, and validation of Indian market data fixtures."""

    def __init__(self, storage_dir: Optional[Path | str] = None) -> None:
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            self.storage_dir = Path("agents/AGI_1_7/runtime_storage/finance/data")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.calendar = BankNiftyMarketCalendar()

    def generate_regime_day(
        self,
        date_str: str = "2026-10-14",  # Wednesday expiry date
        regime: str = "BULLISH_TRENDING",
        base_spot: float = 52000.0,
        step_minutes: int = 5,
        seed: int = 42,
    ) -> List[MarketSnapshot]:
        """Generates a reproducible 1-day session of 5-min bars and option chains.
        
        Regimes:
        - BULLISH_TRENDING: Strong morning drive (+600 pts total)
        - SIDEWAYS_RANGING: Low volatility oscillating between +/- 90 pts
        - VOLATILE_BREAKDOWN: Gap down followed by heavy selling (-700 pts)
        """
        rng = random.Random(seed)
        start_time = datetime.datetime.fromisoformat(f"{date_str}T09:15:00")
        end_time = datetime.datetime.fromisoformat(f"{date_str}T15:30:00")

        total_steps = int((end_time - start_time).total_seconds() / (step_minutes * 60)) + 1
        ref_date = start_time.date()
        expiry_date = self.calendar.get_nearest_expiry(ref_date)
        expiry_str = expiry_date.isoformat()

        # Days to expiry in years
        days_to_exp = max(0.5, (expiry_date - ref_date).days + 0.5)
        t_years = days_to_exp / 365.0

        current_spot = base_spot
        if regime == "VOLATILE_BREAKDOWN":
            current_spot -= 150.0  # Gap down open

        snapshots: List[MarketSnapshot] = []

        for step in range(total_steps):
            bar_time = start_time + datetime.timedelta(minutes=step * step_minutes)
            ts_str = bar_time.strftime("%Y-%m-%d %H:%M:%S")

            # Intraday drift and noise according to regime
            if regime == "BULLISH_TRENDING":
                drift = 9.0 if step < 25 else (4.0 if step < 50 else 1.0)
                noise = rng.uniform(-15.0, 20.0)
                volatility = 0.16
            elif regime == "SIDEWAYS_RANGING":
                # Mean reverting toward base_spot
                deviation = current_spot - base_spot
                drift = -0.15 * deviation
                noise = rng.uniform(-18.0, 18.0)
                volatility = 0.13
            elif regime == "VOLATILE_BREAKDOWN":
                drift = -12.0 if step < 30 else -4.0
                noise = rng.uniform(-25.0, 15.0)
                volatility = 0.24
            else:
                drift = 0.0
                noise = rng.uniform(-10.0, 10.0)
                volatility = 0.15

            open_p = current_spot
            close_p = open_p + drift + noise
            high_p = max(open_p, close_p) + abs(rng.uniform(5.0, 25.0))
            low_p = min(open_p, close_p) - abs(rng.uniform(5.0, 25.0))

            # Realistic U-shaped volume curve (higher at open & close)
            time_norm = step / max(1, total_steps - 1)
            vol_multiplier = 2.5 if (time_norm < 0.15 or time_norm > 0.85) else 1.0
            volume = int(rng.uniform(2000, 8000) * vol_multiplier)

            bar = MarketBar(
                timestamp_ist=ts_str,
                open=round(open_p, 2),
                high=round(high_p, 2),
                low=round(low_p, 2),
                close=round(close_p, 2),
                volume=volume,
            )
            current_spot = close_p

            # Synchronized Option Chain (ATM and +/- 4 strikes: 9 strikes * 2 types = 18 contracts)
            atm_strike = BankNiftyContractSpec.get_atm_strike(close_p)
            strikes = [atm_strike + (offset * 100.0) for offset in range(-4, 5)]

            options: Dict[str, OptionChainQuote] = {}
            for strike in strikes:
                # Call option
                ce_greeks = OptionsMath.calculate_greeks(
                    spot=close_p,
                    strike=strike,
                    time_to_expiry_years=t_years,
                    volatility=volatility,
                    is_call=True,
                )
                ce_sym = f"BANKNIFTY{ref_date.strftime('%y%b').upper()}{int(strike)}CE"
                options[ce_sym] = OptionChainQuote(
                    symbol=ce_sym,
                    strike=strike,
                    option_type="CE",
                    expiry=expiry_str,
                    ltp=BankNiftyContractSpec.round_to_tick(max(1.0, ce_greeks["price"])),
                    iv=volatility,
                    delta=round(ce_greeks["delta"], 4),
                    gamma=round(ce_greeks["gamma"], 6),
                    theta=round(ce_greeks["theta"], 2),
                    vega=round(ce_greeks["vega"], 2),
                    volume=int(volume * max(0.1, 1.0 - abs(strike - atm_strike) / 1000.0)),
                )

                # Put option
                pe_greeks = OptionsMath.calculate_greeks(
                    spot=close_p,
                    strike=strike,
                    time_to_expiry_years=t_years,
                    volatility=volatility,
                    is_call=False,
                )
                pe_sym = f"BANKNIFTY{ref_date.strftime('%y%b').upper()}{int(strike)}PE"
                options[pe_sym] = OptionChainQuote(
                    symbol=pe_sym,
                    strike=strike,
                    option_type="PE",
                    expiry=expiry_str,
                    ltp=BankNiftyContractSpec.round_to_tick(max(1.0, pe_greeks["price"])),
                    iv=volatility,
                    delta=round(pe_greeks["delta"], 4),
                    gamma=round(pe_greeks["gamma"], 6),
                    theta=round(pe_greeks["theta"], 2),
                    vega=round(pe_greeks["vega"], 2),
                    volume=int(volume * max(0.1, 1.0 - abs(strike - atm_strike) / 1000.0)),
                )

            snapshots.append(MarketSnapshot(timestamp_ist=ts_str, spot_bar=bar, options=options))

        return snapshots

    def generate_multi_day_dataset(
        self,
        start_date: str = "2026-10-12",
        days: int = 3,
        step_minutes: int = 5,
    ) -> List[MarketSnapshot]:
        """Generates a cohesive multi-day sequence spanning multiple market regimes."""
        regimes = ["BULLISH_TRENDING", "SIDEWAYS_RANGING", "VOLATILE_BREAKDOWN"]
        base = 52000.0
        cur_dt = datetime.datetime.fromisoformat(f"{start_date}T09:15:00")
        all_snapshots: List[MarketSnapshot] = []

        for d_idx in range(days):
            # Skip non-trading days
            while not self.calendar.is_trading_day(cur_dt.date()):
                cur_dt += datetime.timedelta(days=1)

            regime = regimes[d_idx % len(regimes)]
            day_str = cur_dt.strftime("%Y-%m-%d")
            day_snaps = self.generate_regime_day(
                date_str=day_str,
                regime=regime,
                base_spot=base,
                step_minutes=step_minutes,
                seed=100 + d_idx,
            )
            all_snapshots.extend(day_snaps)
            # Update base for next day from last close
            base = day_snaps[-1].spot_bar.close
            cur_dt += datetime.timedelta(days=1)

        return all_snapshots

    def save_fixture(
        self,
        snapshots: Sequence[MarketSnapshot],
        filename: str = "bank_nifty_multi_regime_fixture.json",
    ) -> Path:
        """Serializes snapshots to disk as a JSON fixture."""
        filepath = self.storage_dir / filename
        data = []
        for s in snapshots:
            bar_dict = {
                "timestamp_ist": s.spot_bar.timestamp_ist,
                "open": s.spot_bar.open,
                "high": s.spot_bar.high,
                "low": s.spot_bar.low,
                "close": s.spot_bar.close,
                "volume": s.spot_bar.volume,
            }
            opts_dict = {}
            for sym, q in s.options.items():
                opts_dict[sym] = {
                    "symbol": q.symbol,
                    "strike": q.strike,
                    "option_type": q.option_type,
                    "expiry": q.expiry,
                    "ltp": q.ltp,
                    "iv": q.iv,
                    "delta": q.delta,
                    "gamma": q.gamma,
                    "theta": q.theta,
                    "vega": q.vega,
                    "volume": q.volume,
                }
            data.append({
                "timestamp_ist": s.timestamp_ist,
                "spot_bar": bar_dict,
                "options": opts_dict,
            })

        filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return filepath

    def load_fixture(self, filepath: Path | str) -> List[MarketSnapshot]:
        """Loads and deserializes a JSON fixture of market snapshots."""
        path = Path(filepath)
        if not path.exists():
            path = self.storage_dir / filepath

        raw = json.loads(path.read_text(encoding="utf-8"))
        snapshots: List[MarketSnapshot] = []

        for item in raw:
            b_raw = item["spot_bar"]
            bar = MarketBar(
                timestamp_ist=b_raw["timestamp_ist"],
                open=float(b_raw["open"]),
                high=float(b_raw["high"]),
                low=float(b_raw["low"]),
                close=float(b_raw["close"]),
                volume=int(b_raw.get("volume", 0)),
            )

            options: Dict[str, OptionChainQuote] = {}
            for sym, o_raw in item.get("options", {}).items():
                options[sym] = OptionChainQuote(
                    symbol=o_raw["symbol"],
                    strike=float(o_raw["strike"]),
                    option_type=o_raw["option_type"],
                    expiry=o_raw["expiry"],
                    ltp=float(o_raw["ltp"]),
                    iv=float(o_raw.get("iv", 0.15)),
                    delta=float(o_raw.get("delta", 0.5)),
                    gamma=float(o_raw.get("gamma", 0.001)),
                    theta=float(o_raw.get("theta", -10.0)),
                    vega=float(o_raw.get("vega", 10.0)),
                    volume=int(o_raw.get("volume", 1000)),
                )

            snapshots.append(MarketSnapshot(
                timestamp_ist=item["timestamp_ist"],
                spot_bar=bar,
                options=options,
            ))

        return snapshots

    def validate_fixture(self, snapshots: Sequence[MarketSnapshot]) -> Tuple[bool, str]:
        """Strictly validates chronological sequence, OHLC validity, and quote sanity."""
        if not snapshots:
            return False, "Fixture contains 0 snapshots"

        prev_ts: Optional[str] = None
        for idx, snap in enumerate(snapshots):
            ts = snap.timestamp_ist
            if prev_ts is not None and ts <= prev_ts:
                return False, f"Temporal anomaly at index {idx}: {ts} <= {prev_ts} (lookahead violation)"
            prev_ts = ts

            b = snap.spot_bar
            if not (b.low <= b.open <= b.high and b.low <= b.close <= b.high):
                return False, f"Invalid OHLC on spot at {ts}: O={b.open}, H={b.high}, L={b.low}, C={b.close}"

            for sym, q in snap.options.items():
                if q.ltp <= 0:
                    return False, f"Non-positive option LTP on {sym} at {ts}: {q.ltp}"
                if abs(q.delta) > 1.05:
                    return False, f"Unphysical option delta on {sym} at {ts}: {q.delta}"

        return True, "FIXTURE_VALID"
