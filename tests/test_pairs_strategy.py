import numpy as np
import pandas as pd
import pytest

from strategies.pairs_trading.strategy import (
    PairsSpec,
    PairsSpecError,
    align_price_series,
    build_pairs_spec,
    check_cointegration,
    compute_hedge_ratio,
    compute_spread,
    compute_zscore,
)


def test_valid_pairs_spec_passes():
    build_pairs_spec("KO", "PEP").validate()


def test_same_ticker_rejected():
    with pytest.raises(PairsSpecError):
        build_pairs_spec("KO", "KO")


def test_entry_zscore_must_exceed_exit_zscore():
    with pytest.raises(PairsSpecError):
        build_pairs_spec("KO", "PEP", entry_zscore=1.0, exit_zscore=2.0)


def test_negative_exit_zscore_rejected():
    with pytest.raises(PairsSpecError):
        build_pairs_spec("KO", "PEP", exit_zscore=-0.5)


def test_build_pairs_spec_gives_distinct_source_urls_per_pair():
    spec_a = build_pairs_spec("KO", "PEP")
    spec_b = build_pairs_spec("XOM", "CVX")
    assert spec_a.source_url != spec_b.source_url


def test_round_trip_dict():
    spec = build_pairs_spec("KO", "PEP", lookback_period=45, entry_zscore=2.5, exit_zscore=0.3)
    restored = PairsSpec.from_dict(spec.to_dict())
    assert restored.ticker_a == "KO"
    assert restored.ticker_b == "PEP"
    assert restored.lookback_period == 45
    assert restored.entry_zscore == 2.5
    assert restored.exit_zscore == 0.3


def test_to_dict_tags_kind_pairs():
    assert build_pairs_spec("KO", "PEP").to_dict()["kind"] == "pairs"


def test_align_price_series_inner_joins_on_date():
    idx_a = pd.date_range("2024-01-01", periods=5, freq="D")
    idx_b = pd.date_range("2024-01-02", periods=5, freq="D")  # offset by one day
    price_a = pd.Series(range(5), index=idx_a, dtype=float)
    price_b = pd.Series(range(5), index=idx_b, dtype=float)

    aligned_a, aligned_b = align_price_series(price_a, price_b)

    assert list(aligned_a.index) == list(aligned_b.index)
    assert len(aligned_a) == 4  # only the overlapping 4 days


def test_compute_hedge_ratio_recovers_known_slope():
    rng = np.random.default_rng(0)
    price_b = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    price_a = 2.0 * price_b + 10  # exact linear relationship

    hedge_ratio = compute_hedge_ratio(price_a, price_b)

    assert hedge_ratio == pytest.approx(2.0, rel=1e-6)


def test_compute_spread_and_zscore_are_centered_near_zero():
    rng = np.random.default_rng(1)
    price_b = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    price_a = 1.5 * price_b + rng.normal(0, 0.1, 200)

    hedge_ratio = compute_hedge_ratio(price_a, price_b)
    spread = compute_spread(price_a, price_b, hedge_ratio)
    zscore = compute_zscore(spread, lookback=30)

    assert abs(zscore.dropna().mean()) < 1.0  # roughly centered, no huge systematic bias


def test_check_cointegration_detects_cointegrated_pair():
    rng = np.random.default_rng(2)
    price_b = pd.Series(100 + np.cumsum(rng.normal(0, 1, 300)))
    price_a = 0.5 * price_b + 50 + rng.normal(0, 0.5, 300)  # cointegrated by construction

    p_value = check_cointegration(price_a, price_b)

    assert p_value < 0.05


def test_check_cointegration_rejects_independent_series():
    rng = np.random.default_rng(3)
    price_a = pd.Series(100 + np.cumsum(rng.normal(0, 1, 300)))
    price_b = pd.Series(100 + np.cumsum(rng.normal(0, 1, 300)))  # independent random walk

    p_value = check_cointegration(price_a, price_b)

    assert p_value > 0.05
