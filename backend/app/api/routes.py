from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.entities import ExecutionConfigUpdate, StrategyConfig
from app.services.bot_engine import engine

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "running": engine.running,
        "last_tick_at": engine.last_tick_at,
        "tick_count": engine.tick_count,
    }


@router.post("/bot/start")
async def start_bot() -> dict:
    await engine.start()
    return {"status": "started"}


@router.post("/bot/stop")
async def stop_bot() -> dict:
    await engine.stop()
    return {"status": "stopped"}


@router.post("/bot/tick")
async def manual_tick() -> dict:
    await engine.tick()
    return {"status": "tick_complete", "tick_count": engine.tick_count}


@router.get("/config")
async def get_config() -> dict:
    return {"config": engine.strategy_config.model_dump()}


@router.post("/config")
async def update_config(config: StrategyConfig) -> dict:
    try:
        updated = engine.update_strategy_config(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "updated", "config": updated.model_dump()}


@router.get("/execution-config")
async def get_execution_config() -> dict:
    return {"execution_config": engine.get_execution_config().model_dump()}


@router.post("/execution-config")
async def update_execution_config(config: ExecutionConfigUpdate) -> dict:
    updated = engine.update_execution_config(config)
    return {"status": "updated", "execution_config": updated.model_dump()}


@router.get("/state")
async def state() -> dict:
    stats = engine.trade_executor.stats
    return {
        "stats": {
            "balance": stats.balance,
            "today_pnl": stats.today_pnl,
            "all_time_pnl": stats.all_time_pnl,
            "trades": stats.trades,
            "win_rate": stats.win_rate,
            "avg_pnl": stats.avg_pnl,
        },
        "config": engine.strategy_config.model_dump(),
        "execution_config": engine.get_execution_config().model_dump(),
        "running": engine.running,
        "tick_count": engine.tick_count,
        "last_tick_at": engine.last_tick_at,
        "last_decision_by_asset": engine.last_decision_by_asset,
        "markets": {k: v.model_dump() for k, v in engine.latest_snapshots.items()},
        "open_trades": [t.model_dump() for t in engine.trade_executor.open_trades.values()],
        "history": [t.model_dump() for t in engine.trade_executor.closed_trades],
    }
