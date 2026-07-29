from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from jose.api.routes import admin, dashboard, health, imports, job_merge, jobs, sources, tasks
from jose.config import get_settings
from jose.db.session import SessionLocal
from jose.services.users import get_or_create_default_user


@asynccontextmanager
async def lifespan(_: FastAPI):
    with SessionLocal() as session:
        get_or_create_default_user(session)
    yield


app = FastAPI(
    title="JOSE API",
    version="0.1.0",
    description="Job Opportunity Search Engine",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(dashboard.router)
app.include_router(sources.router)
app.include_router(imports.router)
app.include_router(jobs.router)
app.include_router(job_merge.router)
app.include_router(tasks.router)
app.include_router(admin.router)
