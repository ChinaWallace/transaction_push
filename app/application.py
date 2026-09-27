"""One ASGI composition root; quant profile shares config without legacy side effects.

uvicorn app.application:create_app --factory
"""
import asyncio
import fcntl
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.runtime_config import get_runtime_settings


def create_app(*, research_only=False):
    settings=get_runtime_settings()
    if settings.app_profile=="legacy":
        if research_only:raise ValueError('Research-only viewer requires quant profile')
        from main import create_app as create_legacy_app
        return create_legacy_app()
    from app.quant.api import router
    from app.quant.runtime import PaperWorker

    @asynccontextmanager
    async def lifespan(app):
        app.state.settings=settings
        if research_only or not settings.quant_worker_enabled:
            yield
            return
        settings.quant_output_dir.mkdir(parents=True,exist_ok=True)
        with (settings.quant_output_dir/"worker.lock").open("a") as handle:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another quant worker owns this account; use one ASGI worker") from None
            worker=PaperWorker(settings.quant_observation_seconds,settings.quant_refresh_seconds,background_collection=True,
                               directory=settings.quant_data_dir,output=settings.quant_output_dir,capital=settings.quant_initial_capital)
            app.state.paper_worker=worker
            worker.save(); task=asyncio.create_task(worker.run())
            try:yield
            finally:
                worker.stop_event.set()
                await task

    app=FastAPI(title="Transaction Push · 合约研究与模拟",version="4.0",lifespan=lifespan)
    app.state.settings=settings
    app.state.research_only=research_only
    if research_only:
        from fastapi.responses import JSONResponse
        @app.middleware("http")
        async def read_only_viewer(request,call_next):
            if request.method not in {"GET","HEAD","OPTIONS"}:
                return JSONResponse({"detail":"Research-only viewer: paper writes are disabled"},status_code=405)
            return await call_next(request)
    app.include_router(router)
    return app
