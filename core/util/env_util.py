"""Load project configuration independently of the current working directory."""
import os
from pathlib import Path

from dotenv import dotenv_values


def load_env(filepath: str):
	"""Load a file under core/config while letting process variables take precedence."""
	config_path = Path(filepath).expanduser()
	if not config_path.is_absolute():
		config_directory = Path(__file__).resolve().parents[1] / "config"
		config_path = config_directory / config_path
	print(f"Loading environment file: {config_path}")
	if config_path.is_file():
		file_values = dotenv_values(config_path)
		for key, value in file_values.items():
			if value is not None:
				# Docker SDK also reads configuration directly from the process environment.
				os.environ.setdefault(key, value)
	return os.environ
