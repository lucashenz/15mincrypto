# Polymarket Sniper - Backend

Backend em FastAPI para rodar localmente o bot (modo paper/backtest), com arquitetura de classes e suporte para BTC/ETH/SOL.

## Features
- Estratégia MACD + tendência
- Entrada apenas quando confiança >= 90%
- Mercado de janela curta (configurável, padrão 15 min)
- Sistema híbrido de API:
  - `CLOB` quando faltam mais de 60s
  - `GAMMA_API` quando faltam 60s ou menos
- Entradas e saídas fictícias (paper trading)
- Estado e métricas zeradas no boot

## Executar em localhost
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Endpoints
- `GET /api/health`
- `POST /api/bot/start`
- `POST /api/bot/stop`
- `POST /api/bot/tick`
- `GET /api/state`

## Observação
Para odds reais em produção, ajuste os `market_id` no `.env` e adapte parsing dos endpoints CLOB/Gamma conforme o formato exato do mercado alvo.
