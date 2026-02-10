from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.services.bot_engine import engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await engine.shutdown()


app = FastAPI(title="Polymarket Sniper Backend", version="1.0.0", lifespan=lifespan)
app.include_router(router)
