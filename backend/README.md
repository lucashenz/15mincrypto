# Polymarket Sniper - Backend

Backend em FastAPI para rodar localmente o bot (modo paper/backtest), com arquitetura de classes e suporte para BTC/ETH/SOL.

## Features
- Estratégia configurável por API (ativos + indicadores)
- Indicadores disponíveis: `MACD`, `TREND`, `POLY_PRICE`
- Entrada por consenso de indicadores (com trace de decisão por ativo)
- Warmup de histórico para MACD/TREND começarem a sinalizar mais rápido
- Sistema híbrido de API:
  - `CLOB` quando faltam mais de 60s
  - `GAMMA_API` quando faltam 60s ou menos
- Mostra no estado se odd é `live` e qual `source` (`CLOB`, `GAMMA_API`, `LAST_KNOWN`)
- Resolve automaticamente o mercado ativo de 15 minutos via Gamma API usando busca com timestamp (janela atual)

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
Use `MARKETS_BTC`, `MARKETS_ETH`, `MARKETS_SOL` com slug base de 15m (ex.: `btc-updown-15m`).
O backend faz query na Gamma API com termos de timestamp da janela atual para encontrar o mercado ativo e atualizar automaticamente a cada 15 minutos.
Se quiser fixar manualmente, também pode usar market ID direto.
