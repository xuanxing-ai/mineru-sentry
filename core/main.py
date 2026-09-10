"""Application factory and root entry point for the MinerU-Sentry gateway."""
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.init import postgres_init
from core.init.log import setup_logging
from core.api.system_api import router as system_router
from core.service.docker_service import docker_service


def create_app() -> FastAPI:
	"""Initialize shared infrastructure, register business routes, and start monitoring."""
	setup_logging()
	app = FastAPI(
		title="MinerU-Sentry Gateway",
		version="1.0.0",
		description="Lightweight Zero-VRAM Standby Gateway & Orchestrator for MinerU on RTX 5090.",
	)
	app.add_middleware(
		CORSMiddleware,
		allow_origins=["*"],
		allow_credentials=True,
		allow_methods=["*"],
		allow_headers=["*"],
	)

	postgres_init.init_postgres(app)
	if app.postgresSession is not None:
		# Import ORM-backed services only after optional database initialization.
		from core.api.parse_api import router as parse_router

		try:
			postgres_init.Base.metadata.create_all(bind=postgres_init.engine)
			logging.info("Database tables initialized successfully in create_app.")
		except Exception as exc:
			logging.warning("Database table verification deferred: %s", exc)
		app.include_router(parse_router)

	app.include_router(system_router)
	docker_service.start_idle_monitor()
	app.add_event_handler("shutdown", docker_service.stop_idle_monitor)
	return app


app = create_app()

if __name__ == "__main__":
	listen_host = settings.SENTRY_HOST or "0.0.0.0"
	raw_port = settings.SERVICE_PORT
	listen_port = int(raw_port) if raw_port else 8080
	config = uvicorn.Config(
		app, host=listen_host, port=listen_port, log_config=None, access_log=True,
	)
	server = uvicorn.Server(config)
	server.run()
