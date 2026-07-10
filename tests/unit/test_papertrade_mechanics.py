"""Golden tests for :mod:`investment_assistant.papertrade.mechanics`.

Every table-driven rule (tick size, price-limit band, slippage, lot
rounding, commission, tax) is exercised at its documented boundary values
against the design doc's tables (``docs/papertrade-design.md``).
"""

from __future__ import annotations

import pytest

from investment_assistant.papertrade.mechanics import (
    CommissionModel,
    TaxLedger,
    apply_slippage,
    clamp_to_limit,
    commission,
    fill_price,
    price_limit_band,
    round_lot,
    round_to_tick,
    round_yen,
)

# --- tick rounding -----------------------------------------------------


@pytest.mark.parametrize(
    ("price", "expected_buy", "expected_sell"),
    [
        # <=3,000 band: tick=1
        (100.4, 101.0, 100.0),
        (2999.5, 3000.0, 2999.0),
        # boundary: 3000 is also a valid 5-yen tick, so behavior is identical.
        (3000.0, 3000.0, 3000.0),
        (3002.0, 3005.0, 3000.0),
        # >3,000 and <=5,000 band: tick=5.
        (4998.0, 5000.0, 4995.0),
        # boundary: 5000 is also a valid 10-yen tick.
        (5000.0, 5000.0, 5000.0),
        (5003.0, 5010.0, 5000.0),
        # >5,000 and <=30,000 band: tick=10.
        (29995.0, 30000.0, 29990.0),
        # boundary: 30000 is also a valid 50-yen tick.
        (30000.0, 30000.0, 30000.0),
        (30011.0, 30050.0, 30000.0),
        # >30,000 and <=50,000 band: tick=50.
        (49970.0, 50000.0, 49950.0),
        # boundary: 50000 is also a valid 100-yen tick.
        (50000.0, 50000.0, 50000.0),
        (50001.0, 50100.0, 50000.0),
        # >50,000 and <=300,000 band: tick=100.
        (299950.0, 300000.0, 299900.0),
        # boundary: 300000 is also a valid 500-yen tick.
        (300000.0, 300000.0, 300000.0),
        (300001.0, 300500.0, 300000.0),
        # >300,000 and <=500,000 band: tick=500.
        (499800.0, 500000.0, 499500.0),
        # boundary: 500000 is also a valid 1,000-yen tick.
        (500000.0, 500000.0, 500000.0),
        (500001.0, 501000.0, 500000.0),
        # catch-all above 500,000: tick=1000
        (600400.0, 601000.0, 600000.0),
    ],
)
def test_round_to_tick_buy_up_sell_down(
    price: float, expected_buy: float, expected_sell: float
) -> None:
    assert round_to_tick(price, side="buy") == expected_buy
    assert round_to_tick(price, side="sell") == expected_sell


def test_round_to_tick_exact_tick_multiple_is_unchanged() -> None:
    assert round_to_tick(120.0, side="buy") == 120.0
    assert round_to_tick(120.0, side="sell") == 120.0


# --- price-limit band ----------------------------------------------------
# Price-limit bands use strictly-less boundaries; this is correct and must
# stay even though the quotation-unit tick table uses less-or-equal bands.


def test_price_limit_band_boundary_999_vs_1000() -> None:
    # ref < 1000 -> band (.., 150); ref == 1000 is NOT < 1000 -> next band (.., 300)
    assert price_limit_band(999.0) == (849.0, 1149.0)
    assert price_limit_band(1000.0) == (700.0, 1300.0)


@pytest.mark.parametrize(
    ("reference_price", "expected_low", "expected_high"),
    [
        (100.0, 50.0, 150.0),  # ref==100 is not <100 -> next band (<200: width 50)
        (99.0, 69.0, 129.0),  # ref < 100 band (width 30)
        (500.0, 400.0, 600.0),  # ref==500 -> next band (<700: width 100)
        (499.0, 419.0, 579.0),  # ref < 500 band (width 80)
        (150000.0, 120000.0, 180000.0),  # last enumerated band boundary -> fallback (+/-20%)
        (149999.0, 119999.0, 179999.0),  # just under last bound -> <150,000 band (width 30,000)
    ],
)
def test_price_limit_band_table(
    reference_price: float, expected_low: float, expected_high: float
) -> None:
    assert price_limit_band(reference_price) == (expected_low, expected_high)


def test_price_limit_band_above_last_bound_uses_20pct_fallback() -> None:
    low, high = price_limit_band(1_000_000.0)
    assert low == pytest.approx(800_000.0)
    assert high == pytest.approx(1_200_000.0)


def test_clamp_to_limit_within_band_is_unchanged() -> None:
    price, clamped = clamp_to_limit(1000.0, reference_price=999.0)
    assert clamped is False
    assert price == 1000.0


def test_clamp_to_limit_clamps_high_and_low() -> None:
    high_price, high_clamped = clamp_to_limit(2000.0, reference_price=999.0)
    assert high_clamped is True
    assert high_price == 1149.0  # upper bound of the 999-reference band

    low_price, low_clamped = clamp_to_limit(100.0, reference_price=999.0)
    assert low_clamped is True
    assert low_price == 849.0


def test_clamp_to_limit_snaps_upper_bound_down_to_valid_tick() -> None:
    # prev_close=2999 -> limit band high is 3499, but 3499 is not a valid
    # 5-yen tick because quotation-unit bands are <=3,000 then >3,000.
    high_price, high_clamped = clamp_to_limit(3500.0, reference_price=2999.0)
    assert high_clamped is True
    assert high_price == 3495.0


def test_clamp_to_limit_snaps_lower_bound_up_to_valid_tick() -> None:
    # prev_close=14999 -> limit band low is 11999, but that is not a valid
    # 10-yen tick, so the low-side clamp must round up without leaving the band.
    low_price, low_clamped = clamp_to_limit(1000.0, reference_price=14999.0)
    assert low_clamped is True
    assert low_price == 12000.0


# --- slippage -----------------------------------------------------------


def test_apply_slippage_buy_up_sell_down_default_bps() -> None:
    assert apply_slippage(1000.0, side="buy") == pytest.approx(1001.0)
    assert apply_slippage(1000.0, side="sell") == pytest.approx(999.0)


def test_apply_slippage_custom_bps() -> None:
    assert apply_slippage(1000.0, side="buy", bps=50) == pytest.approx(1005.0)
    assert apply_slippage(1000.0, side="sell", bps=50) == pytest.approx(995.0)


# --- fill_price composition ----------------------------------------------


def test_fill_price_composes_slippage_tick_and_clamp_for_buy() -> None:
    # open=980, prev_close=1000: slippage(+0.1%) -> 980.98, tick round up
    # (<=3,000 band: tick 1) -> 981.0; limit band for ref=1000 is
    # (700, 1300), 981 is inside -> not clamped.
    result = fill_price(980.0, prev_close=1000.0, side="buy")
    assert result.price == 981.0
    assert result.clamped is False


def test_fill_price_composes_slippage_tick_and_clamp_for_sell() -> None:
    # open=1020, prev_close=1000: slippage(-0.1%) -> 1018.98, tick round down (tick 1) -> 1018.0
    # limit band for ref=1000 is (700, 1300), 1018 is inside -> not clamped.
    result = fill_price(1020.0, prev_close=1000.0, side="sell")
    assert result.price == 1018.0
    assert result.clamped is False


def test_fill_price_tick_rounding_at_a_coarser_band() -> None:
    # open=10003, prev_close=10000, no slippage: tick band >5,000 and
    # <=30,000 -> tick=10 -> ceil(10003/10)*10 = 10010. Limit band for
    # ref=10000 is (7000, 13000): inside -> not clamped.
    result = fill_price(10003.0, prev_close=10000.0, side="buy", slippage_bps=0)
    assert result.price == 10010.0
    assert result.clamped is False


def test_fill_price_clamps_when_open_gaps_past_limit_band() -> None:
    # prev_close=100 -> band (50, 150) (ref==100 falls in the <200 band, width 50).
    # open gaps way up to 500 -> ticked price 501 clamped down to the band's high (150).
    result = fill_price(500.0, prev_close=100.0, side="buy")
    assert result.clamped is True
    assert result.price == 150.0


def test_fill_price_custom_slippage_bps() -> None:
    result = fill_price(1000.0, prev_close=1000.0, side="buy", slippage_bps=0)
    # no slippage: 1000 -> tick round up (<=3,000 band tick=1) ->
    # unchanged; limit band for ref=1000 is (700, 1300) -> not clamped.
    assert result.price == 1000.0
    assert result.clamped is False


# --- lot rounding ---------------------------------------------------------


@pytest.mark.parametrize(
    ("shares", "expected"),
    [(0, 0), (99, 0), (100, 100), (250, 200), (399, 300)],
)
def test_round_lot(shares: int, expected: int) -> None:
    assert round_lot(shares) == expected


# --- commission -----------------------------------------------------------


def test_commission_zero_model() -> None:
    assert commission(1_000_000.0, CommissionModel.zero()) == 0.0


def test_commission_bps_model() -> None:
    model = CommissionModel.bps(5)  # 5 bps = 0.05%
    assert commission(1_000_000.0, model) == pytest.approx(500.0)


# --- round_yen --------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(100.4, 100), (100.5, 101), (100.49999, 100), (0.5, 1)],
)
def test_round_yen_half_up(value: float, expected: int) -> None:
    assert round_yen(value) == expected


# --- TaxLedger --------------------------------------------------------------


def test_tax_ledger_gain_withholds_tax() -> None:
    ledger = TaxLedger()
    delta = ledger.record_realized_pnl(100_000.0)
    assert delta == round_yen(100_000.0 * 0.20315)
    assert delta == 20315
    assert ledger.cumulative_tax_withheld == 20315


def test_tax_ledger_subsequent_loss_partially_refunds() -> None:
    ledger = TaxLedger()
    ledger.record_realized_pnl(100_000.0)  # withheld 20315
    delta = ledger.record_realized_pnl(-40_000.0)  # cumulative pnl now 60,000
    expected_new_total = round_yen(60_000.0 * 0.20315)
    assert delta == expected_new_total - 20315
    assert delta < 0  # a refund
    assert ledger.cumulative_tax_withheld == expected_new_total


def test_tax_ledger_net_negative_cumulative_means_zero_total_tax() -> None:
    ledger = TaxLedger()
    ledger.record_realized_pnl(100_000.0)  # withheld 20315
    delta = ledger.record_realized_pnl(-150_000.0)  # cumulative pnl now -50,000
    assert ledger.cumulative_tax_withheld == 0
    assert delta == -20315  # full refund of what was withheld


def test_tax_ledger_nisa_always_zero() -> None:
    ledger = TaxLedger(nisa=True)
    assert ledger.record_realized_pnl(1_000_000.0) == 0
    assert ledger.record_realized_pnl(-500_000.0) == 0
    assert ledger.cumulative_tax_withheld == 0
    # cumulative_pnl bookkeeping still tracked even though tax is always zero.
    assert ledger.cumulative_pnl == 500_000.0
