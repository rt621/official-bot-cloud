"""应用入口：FastAPI + 运行时 supervisor 同进程。"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, features, group_admin, instances, payment
from app.database import init_db
from app.runtime.supervisor import Supervisor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("websockets").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    supervisor = Supervisor()
    app.state.supervisor = supervisor
    bootstrap_task = asyncio.create_task(supervisor.bootstrap())
    async def expiry_loop() -> None:
        while True:
            try:
                await supervisor.enforce_expirations()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger("app").exception("用户有效期巡检失败")
            await asyncio.sleep(60)

    expiry_task = asyncio.create_task(expiry_loop(), name="user-expiration-monitor")
    yield
    bootstrap_task.cancel()
    expiry_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await bootstrap_task
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await expiry_task
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await supervisor.shutdown()


app = FastAPI(title="官机云平台", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin.public)
app.include_router(instances.router)
app.include_router(features.router)
app.include_router(group_admin.router)
app.include_router(payment.router)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


# 生产模式：托管前端构建产物（frontend/dist）
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        file = _dist / full_path
        if full_path and file.is_file():
            # 带 hash 的静态资源可长缓存；入口文件禁缓存，保证更新即时可见
            return FileResponse(file, headers={"Cache-Control": "public, max-age=31536000, immutable"})
        return FileResponse(
            _dist / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
