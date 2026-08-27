from quant_engine.screeners.news_events import tag_headline


def test_tags_earnings_beat():
    assert "earnings_beat" in tag_headline("Company beats estimates on strong quarter")


def test_tags_earnings_miss():
    assert "earnings_miss" in tag_headline("Company misses estimates amid weak demand")


def test_tags_guidance_cut():
    assert "guidance_cut" in tag_headline("Company cuts guidance for full year")


def test_tags_ma_activity():
    assert "ma_activity" in tag_headline("Company to buy smaller rival in $2B deal")


def test_tags_legal_regulatory():
    assert "legal_regulatory" in tag_headline("Company faces SEC investigation over accounting")


def test_tags_analyst_action():
    assert "analyst_action" in tag_headline("Analyst upgrades stock with new price target")


def test_untagged_headline_returns_empty_list():
    assert tag_headline("Company opens new office in Auckland") == []


def test_headline_can_match_multiple_tags():
    tags = tag_headline("Company beats estimates and raises guidance for next year")
    assert "earnings_beat" in tags
    assert "guidance_raise" in tags
