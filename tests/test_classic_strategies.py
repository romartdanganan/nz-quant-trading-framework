from strategies.breakout.strategy import classic_channel_breakout
from strategies.mean_reversion.strategy import classic_rsi_reversion
from strategies.momentum.strategy import classic_macd_momentum
from strategy_research.strategy_spec import Archetype, Indicator


def test_classic_rsi_reversion_is_valid():
    spec = classic_rsi_reversion()
    spec.validate()
    assert spec.archetype == Archetype.MEAN_REVERSION
    assert spec.entry_conditions[0].indicator == Indicator.RSI


def test_classic_macd_momentum_is_valid():
    spec = classic_macd_momentum()
    spec.validate()
    assert spec.archetype == Archetype.MOMENTUM
    assert spec.entry_conditions[0].indicator == Indicator.MACD


def test_classic_channel_breakout_is_valid_and_has_volume_confirmation():
    spec = classic_channel_breakout()
    spec.validate()
    assert spec.archetype == Archetype.BREAKOUT
    indicators = {c.indicator for c in spec.entry_conditions}
    assert Indicator.CHANNEL_HIGH in indicators
    assert Indicator.VOLUME in indicators
    assert spec.exit_conditions[0].indicator == Indicator.CHANNEL_LOW


def test_classic_strategies_have_stable_internal_source_urls():
    # source_url doubles as the registry dedup key — must not depend on parameters that
    # might vary between calls, or re-seeding would create duplicates.
    assert classic_rsi_reversion(period=21).source_url == classic_rsi_reversion(period=14).source_url
