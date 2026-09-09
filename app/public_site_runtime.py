"""Lifecycle wiring for the optional-looking but always local public site."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import backup_runtime
from app.public_site import PublicSiteBuilder, PublicSiteWorker


def install(app: FastAPI) -> None:
    """Create the public builder without starting background work in tests."""

    builder = PublicSiteBuilder(app.state.settings, app.state.content)
    worker = PublicSiteWorker(builder)
    app.state.public_site_builder = builder
    app.state.public_site_worker = worker
    app.state.content.git.add_commit_listener(worker.request_build)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    worker: PublicSiteWorker = app.state.public_site_worker
    async with backup_runtime.lifespan(app):
        worker.start()
        try:
            yield
        finally:
            app.state.content.git.remove_commit_listener(worker.request_build)
            worker.stop()
