from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    poll_interval_seconds: int = 3
    confidence_threshold: float = 0.9
    trade_duration_seconds: int = 900
    switch_to_gamma_seconds: int = 60
    markets_btc: str = "btc-up-down-15m"
    markets_eth: str = "eth-up-down-15m"
    markets_sol: str = "sol-up-down-15m"
    backtest_mode: bool = True

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
