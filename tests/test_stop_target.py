import pytest

from risk_management.stop_target import Direction, calculate_stop_target, update_trailing_stop


def test_calculate_stop_target_long():
    result = calculate_stop_target(
        entry_price=100.0, atr=2.0, direction=Direction.LONG, atr_multiplier=2.0, reward_risk_ratio=2.0
    )
    assert result.stop_loss == pytest.approx(96.0)
    assert result.target_price == pytest.approx(108.0)
    assert result.stop_distance == pytest.approx(4.0)


def test_calculate_stop_target_short():
    result = calculate_stop_target(
        entry_price=100.0, atr=2.0, direction=Direction.SHORT, atr_multiplier=2.0, reward_risk_ratio=2.0
    )
    assert result.stop_loss == pytest.approx(104.0)
    assert result.target_price == pytest.approx(92.0)


def test_trailing_stop_long_moves_up_but_never_loosens():
    new_stop = update_trailing_stop(
        current_stop=95.0, current_price=110.0, atr=2.0, direction=Direction.LONG, atr_multiplier=2.0
    )
    assert new_stop == pytest.approx(106.0)

    unchanged = update_trailing_stop(
        current_stop=106.0, current_price=100.0, atr=2.0, direction=Direction.LONG, atr_multiplier=2.0
    )
    assert unchanged == pytest.approx(106.0)  # candidate (96.0) would be worse


def test_trailing_stop_short_moves_down_but_never_loosens():
    new_stop = update_trailing_stop(
        current_stop=105.0, current_price=90.0, atr=2.0, direction=Direction.SHORT, atr_multiplier=2.0
    )
    assert new_stop == pytest.approx(94.0)

    unchanged = update_trailing_stop(
        current_stop=94.0, current_price=100.0, atr=2.0, direction=Direction.SHORT, atr_multiplier=2.0
    )
    assert unchanged == pytest.approx(94.0)  # candidate (104.0) would be worse
