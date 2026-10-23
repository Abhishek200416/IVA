import pytest
from agi17.finance.candlestick_momentum_detector import CandlestickMomentumDetector, Candle

def test_boom_up_bullish_engulfing():
    detector = CandlestickMomentumDetector()
    candles = [
        Candle(time="09:15", o=22880, h=22885, l=22850, c=22855, v=10000),  # Red candle
        Candle(time="09:20", o=22850, h=22920, l=22845, c=22915, v=25000),  # Big Green engulfing
    ]
    signal = detector.analyze_candles(candles)
    assert signal.direction == "BOOM_UP"
    assert signal.pattern == "BULLISH_ENGULFING"
    assert signal.confidence >= 0.85
    assert "SUPERCHARGED" in signal.action_directive

def test_boom_up_hammer_bottom_absorption():
    detector = CandlestickMomentumDetector()
    candles = [
        Candle(time="09:15", o=22900, h=22905, l=22870, c=22875, v=12000),
        # Hammer: Open 22880, High 22885, Low 22820 (deep lower wick), Close 22882
        Candle(time="09:20", o=22880, h=22885, l=22820, c=22882, v=30000),
    ]
    signal = detector.analyze_candles(candles)
    assert signal.direction == "BOOM_UP"
    assert signal.pattern == "HAMMER_BOTTOM_ABSORPTION"

def test_boom_down_shooting_star_rejection():
    detector = CandlestickMomentumDetector()
    candles = [
        Candle(time="09:25", o=22960, h=22990, l=22955, c=22985, v=15000),
        # Shooting Star at 23,000 resistance: Open 22985, High 23045 (long upper wick), Low 22980, Close 22982
        Candle(time="09:30", o=22985, h=23045, l=22980, c=22982, v=28000),
    ]
    signal = detector.analyze_candles(candles)
    assert signal.direction == "BOOM_DOWN"
    assert signal.pattern == "SHOOTING_STAR_CEILING_REJECTION"
    assert "RATCHET_SL" in signal.action_directive

def test_boom_down_bearish_engulfing():
    detector = CandlestickMomentumDetector()
    candles = [
        Candle(time="09:35", o=22980, h=23010, l=22975, c=23005, v=14000),  # Green
        Candle(time="09:40", o=23010, h=23015, l=22940, c=22945, v=32000),  # Big Red engulfing
    ]
    signal = detector.analyze_candles(candles)
    assert signal.direction == "BOOM_DOWN"
    assert signal.pattern == "BEARISH_ENGULFING"
    assert "TIGHTEN_SL" in signal.action_directive
