import logging
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.database import init_db
from app.routers import courses, dashboard
from app.routers import bets as bets_router
from app.routers import scoring as scoring_router
from app.routers import auth_router
from app.routers import stats_router
from app.auth import validate_token, get_token_from_request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialisation de la base de données...")
    await init_db()
    logger.info("Base de données prête.")

    # Lancer optimize au démarrage si des courses terminées existent
    try:
        from app.database import AsyncSessionLocal
        from app.models import Course
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Course).where(Course.statut_resultat == "TERMINE").limit(1)
            )
            if result.scalar_one_or_none():
                logger.info("Courses terminées détectées — optimisation des poids au démarrage...")
                from app.routers.scoring import optimize_weights
                await optimize_weights(db)
                logger.info("Poids optimisés.")
                # Auto-calibration au démarrage
                from app.calibration import calibrate_and_store
                async with AsyncSessionLocal() as db2:
                    await calibrate_and_store(db2)
                    logger.info("Auto-calibration des poids effectuée au démarrage.")
    except Exception as e:
        logger.warning("Erreur lors de l'optimisation au démarrage : %s", e)

    yield
    from app.pmu_client import pmu_client
    await pmu_client.close()
    logger.info("Application arrêtée.")


app = FastAPI(
    title="PMU Smart Analyzer",
    description="Analyse intelligente des courses hippiques PMU",
    version="2.0.0",
    lifespan=lifespan,
)

# ---- Auth middleware — protects all /api/* except /api/login ----
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Always allow: login endpoint, static files, manifest, SW, root HTML
    if (
        path == "/api/login"
        or path == "/api/logout"
        or not path.startswith("/api/")
    ):
        return await call_next(request)
    # Protected API route → validate token
    token = get_token_from_request(request)
    try:
        validate_token(token)
    except Exception:
        return JSONResponse(status_code=401, content={"detail": "Non authentifié"})
    return await call_next(request)

# Routers API
app.include_router(auth_router.router)
app.include_router(courses.router)
app.include_router(dashboard.router)
app.include_router(bets_router.router)
app.include_router(scoring_router.router)
app.include_router(stats_router.router)

# Servir les fichiers statiques
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse("static/index.html")


@app.get("/sw.js", include_in_schema=False)
async def serve_sw():
    """Service Worker servi depuis la racine pour avoir scope '/'."""
    return FileResponse(
        "static/sw.js",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        media_type="application/javascript",
    )


@app.get("/manifest.json", include_in_schema=False)
async def serve_manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")


@app.get("/{path_name:path}", include_in_schema=False)
async def serve_spa(path_name: str):
    if path_name.startswith("api/"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return FileResponse("static/index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
