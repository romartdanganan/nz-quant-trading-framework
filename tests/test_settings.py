from config.settings import Settings


def test_settings_loads_config_yaml():
    settings = Settings.load()
    assert settings.base_currency == "NZD"
    assert settings.get("nz_tax.fif_threshold_nzd") == 50000
