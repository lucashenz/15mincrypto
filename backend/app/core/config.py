from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    poll_interval_seconds: int = 1
    confidence_threshold: float = 0.9
    entry_threshold: float = 0.9
    entry_window_seconds: int = 180
    trade_duration_seconds: int = 900
    switch_to_gamma_seconds: int = 60
    markets_btc: str = "btc-updown-15m"
    markets_eth: str = "eth-updown-15m"
    markets_sol: str = "sol-updown-15m"
    market_resolution_ttl_seconds: int = 3
    backtest_mode: bool = True

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
