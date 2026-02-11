from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    poll_interval_seconds: int = 3
    confidence_threshold: float = 0.85
    trade_duration_seconds: int = 900
    switch_to_gamma_seconds: int = 60
    markets_btc: str = "btc-updown-15m"
    markets_eth: str = "eth-updown-15m"
    markets_sol: str = "sol-updown-15m"
    market_resolution_ttl_seconds: int = 30
    backtest_mode: bool = True
    entry_probability_threshold: float = 0.85
    late_entry_seconds: int = 180
    stop_loss_pct: float = 0.2

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
