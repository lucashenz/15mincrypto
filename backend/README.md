# Polymarket Sniper - Backend

Backend em FastAPI para rodar localmente o bot (modo paper/backtest), com arquitetura de classes e suporte para BTC/ETH/SOL.

## Features
- Estratégia configurável por API (ativos + indicadores)
- Indicadores disponíveis: `MACD`, `TREND`, `POLY_PRICE`
- Entrada somente quando `confidence >= threshold`
- Sistema híbrido de API:
  - `CLOB` quando faltam mais de 60s
  - `GAMMA_API` quando faltam 60s ou menos
- Mostra no estado se odd é `live` e qual `source` (CLOB/GAMMA/LAST_KNOWN)

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
- `GET /api/config`
- `POST /api/config`

## Nota importante sobre preços da Poly
Para odds reais consistentes, preencha `MARKETS_BTC`, `MARKETS_ETH`, `MARKETS_SOL` com ID/slug corretos dos mercados ativos de 15min na Polymarket.
