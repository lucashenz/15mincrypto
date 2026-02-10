# 15mincrypto

Projeto com backend + frontend para bot de operações da Polymarket (paper trading), mercado UP/DOWN de cripto.

## Estrutura
- `backend/` — FastAPI com arquitetura em classes, estratégia configurável (ativos + indicadores), modo híbrido CLOB/Gamma e suporte BTC/ETH/SOL.
- `frontend/` — Interface React/Vite minimalista, com painel para selecionar indicadores e ativos a operar.

## Rodar localmente
### 1) Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2) Frontend
```bash
cd frontend
npm install
npm run dev
```

Frontend: `http://localhost:5173` (proxy para backend em `:8000`).
