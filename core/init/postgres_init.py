"""Initialize optional PostgreSQL persistence and synchronous session access."""
import logging

from fastapi import FastAPI

from core.config import settings

engine = None
SessionLocal = None
Base = None

if settings.POSTGRES_URL:
	from sqlalchemy.orm import declarative_base

	Base = declarative_base()


def init_postgres(app: FastAPI) -> None:
	"""Bind a synchronous session factory when PostgreSQL configuration is available."""
	global engine, SessionLocal
	app.postgresSession = None
	if not settings.POSTGRES_URL:
		logging.warning("POSTGRES_URL is empty; document parsing routes are disabled.")
		return

	from sqlalchemy import create_engine
	from sqlalchemy.engine import URL
	from sqlalchemy.orm import sessionmaker

	if engine is None:
		database_url = settings.POSTGRES_URL
		if "://" not in database_url:
			postgres_port = int(settings.POSTGRES_PORT) if settings.POSTGRES_PORT else 5432
			database_url = URL.create(
				drivername="postgresql+psycopg2",
				username=settings.POSTGRES_USERNAME,
				password=settings.POSTGRES_PASSWORD,
				host=settings.POSTGRES_URL,
				port=postgres_port,
				database=settings.POSTGRES_DATABASE,
			)
		engine = create_engine(database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
		SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
	app.postgresSession = SessionLocal
	logging.info("Initialized PostgreSQL session factory.")


def get_postgres_session():
	"""Yield a synchronous session and release it after success or rollback."""
	if SessionLocal is None:
		yield None
		return
	postgres_session = SessionLocal()
	try:
		yield postgres_session
	except Exception:
		postgres_session.rollback()
		logging.exception("Database session rolled back.")
		raise
	finally:
		postgres_session.close()
