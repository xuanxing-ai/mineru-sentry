"""Configure shared console and daily rotating application logs."""
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from core.config import settings


def setup_logging() -> None:
	"""Configure application and Uvicorn output once, retaining fourteen daily logs."""
	logger = logging.getLogger()
	log_level = settings.LOG_LEVEL or "INFO"
	logger.setLevel(log_level.upper())
	if logger.handlers:
		return

	project_root = Path(__file__).resolve().parents[2]
	log_directory = Path(settings.LOG_PATH).expanduser() if settings.LOG_PATH else project_root / "logs"
	if not log_directory.is_absolute():
		log_directory = project_root / log_directory
	log_directory.mkdir(parents=True, exist_ok=True)
	log_name = settings.LOG_NAME or "mineru-sentry"
	log_file = log_directory / f"{log_name}.log"
	formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
	file_handler = TimedRotatingFileHandler(
		filename=log_file, when="midnight", interval=1, backupCount=14, encoding="utf-8",
	)
	file_handler.suffix = "%Y-%m-%d"
	file_handler.setFormatter(formatter)
	console_handler = logging.StreamHandler()
	console_handler.setFormatter(formatter)
	logger.addHandler(file_handler)
	logger.addHandler(console_handler)
