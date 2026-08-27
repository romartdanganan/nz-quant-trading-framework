import pytest

from strategy_research.strategy_spec import (
    Archetype,
    Condition,
    Indicator,
    Operator,
    StrategySpec,
    StrategySpecError,
)


def make_spec(**overrides) -> StrategySpec:
    defaults = dict(
        name="test strategy",
        archetype=Archetype.MEAN_REVERSION,
        entry_conditions=[Condition(Indicator.RSI, Operator.LT, 30)],
        exit_conditions=[Condition(Indicator.RSI, Operator.GT, 70)],
        timeframe="1d",
        source_url="https://example.com",
        extraction_method="rule",
        confidence=0.8,
    )
    defaults.update(overrides)
    return StrategySpec(**defaults)


def test_valid_spec_passes():
    make_spec().validate()


def test_empty_name_rejected():
    with pytest.raises(StrategySpecError):
        make_spec(name="   ").validate()


def test_no_entry_conditions_rejected():
    with pytest.raises(StrategySpecError):
        make_spec(entry_conditions=[]).validate()


def test_no_exit_conditions_rejected():
    with pytest.raises(StrategySpecError):
        make_spec(exit_conditions=[]).validate()


def test_confidence_out_of_range_rejected():
    with pytest.raises(StrategySpecError):
        make_spec(confidence=1.5).validate()


def test_unknown_extraction_method_rejected():
    with pytest.raises(StrategySpecError):
        make_spec(extraction_method="vibes").validate()


def test_rsi_threshold_out_of_range_rejected():
    with pytest.raises(StrategySpecError):
        make_spec(entry_conditions=[Condition(Indicator.RSI, Operator.LT, 150)]).validate()


def test_crossover_condition_not_range_checked():
    make_spec(
        entry_conditions=[Condition(Indicator.MACD, Operator.CROSSES_ABOVE, 0.0)],
        exit_conditions=[Condition(Indicator.MACD, Operator.CROSSES_BELOW, 0.0)],
    ).validate()


def test_round_trip_dict():
    spec = make_spec()
    restored = StrategySpec.from_dict(spec.to_dict())
    assert restored.archetype == spec.archetype
    assert restored.entry_conditions == spec.entry_conditions
    assert restored.exit_conditions == spec.exit_conditions
    assert restored.source_url == spec.source_url


def test_to_dict_tags_kind_single():
    assert make_spec().to_dict()["kind"] == "single"


def test_condition_period_round_trips():
    spec = make_spec(entry_conditions=[Condition(Indicator.RSI, Operator.LT, 30, period=21)])
    restored = StrategySpec.from_dict(spec.to_dict())
    assert restored.entry_conditions[0].period == 21


def test_condition_period_defaults_to_none():
    assert Condition(Indicator.RSI, Operator.LT, 30).period is None


def test_channel_high_condition_not_range_checked():
    make_spec(
        entry_conditions=[Condition(Indicator.CHANNEL_HIGH, Operator.CROSSES_ABOVE, 0.0, period=20)],
        exit_conditions=[Condition(Indicator.CHANNEL_LOW, Operator.CROSSES_BELOW, 0.0, period=10)],
    ).validate()
