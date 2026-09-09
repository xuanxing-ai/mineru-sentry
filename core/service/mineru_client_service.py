"""HTTP Client service for synchronous communication with mineru-api."""
import os
from pathlib import Path
from typing import Optional
import zipfile
import logging
import requests

from core.config import settings


class MineruClientError(Exception):
	"""Exception for communication failures with mineru-api."""
	pass


class MineruClientService:
	"""
	Synchronous client communicating with the containerized mineru-api service.
	"""

	def __init__(self, base_url: Optional[str] = None) -> None:
		raw_url = settings.MINERU_API_URL
		self.base_url: str = base_url if base_url else (raw_url if raw_url else "http://mineru_worker:8000")

	def submit_parse_task(
		self,
		file_path: Path,
		file_name: str,
		backend: str = "hybrid-engine",
		effort: str = "medium",
		parse_method: str = "auto",
		formula_enable: bool = True,
		table_enable: bool = True,
		start_page_id: int = 0,
		end_page_id: int = 99999,
	) -> str:
		"""
		Submits an asynchronous document parsing task to mineru-api POST /tasks.
		:param file_path: Path object pointing to input document.
		:param file_name: Original document filename.
		:param backend: Parsing backend name.
		:param effort: Hybrid parsing effort.
		:param parse_method: auto, txt, or ocr.
		:param formula_enable: Formula detection boolean.
		:param table_enable: Table extraction boolean.
		:param start_page_id: Starting page offset.
		:param end_page_id: Ending page offset.
		:return: Created MinerU task ID string.
		"""
		endpoint = f"{self.base_url}/tasks"
		if not file_path.exists():
			raise MineruClientError(f"Target document not found at: {file_path}")

		req_data = {
			"backend": backend,
			"effort": effort,
			"parse_method": parse_method,
			"formula_enable": str(formula_enable).lower(),
			"table_enable": str(table_enable).lower(),
			"start_page_id": str(start_page_id),
			"end_page_id": str(end_page_id),
			"return_md": "true",
			"return_middle_json": "true",
			"return_images": "true",
			"response_format_zip": "true",
		}

		with open(file_path, "rb") as file_stream:
			files_payload = {"files": (file_name, file_stream, "application/octet-stream")}
			try:
				res = requests.post(endpoint, files=files_payload, data=req_data, timeout=60.0)
				res.raise_for_status()
				json_res = res.json()
				task_id = json_res.get("task_id")
				if not task_id:
					raise MineruClientError(f"Missing task_id in mineru response: {json_res}")
				return str(task_id)
			except Exception as exc:
				logging.error(f"Error submitting task to {endpoint}: {exc}")
				raise MineruClientError(f"Failed to submit task: {exc}") from exc

	def get_task_status(self, mineru_task_id: str) -> str:
		"""
		Queries the current status of a MinerU task from GET /tasks/{task_id}.
		:param mineru_task_id: Task ID string.
		:return: Status string (pending, processing, completed, failed).
		"""
		endpoint = f"{self.base_url}/tasks/{mineru_task_id}"
		try:
			res = requests.get(endpoint, timeout=15.0)
			res.raise_for_status()
			json_res = res.json()
			status = json_res.get("status", "unknown")
			return str(status)
		except Exception as exc:
			logging.warning(f"Error polling mineru task {mineru_task_id}: {exc}")
			raise MineruClientError(f"Polling error: {exc}") from exc

	def download_and_extract_zip(self, mineru_task_id: str, target_dir: Path) -> Path:
		"""
		Downloads result zip archive from GET /tasks/{task_id}/result and extracts into target_dir.
		:param mineru_task_id: Task ID string.
		:param target_dir: Path directory to extract results into.
		:return: Target directory path.
		"""
		endpoint = f"{self.base_url}/tasks/{mineru_task_id}/result"
		target_dir.mkdir(parents=True, exist_ok=True)
		zip_path = target_dir / f"{mineru_task_id}.zip"

		try:
			with requests.get(endpoint, stream=True, timeout=300.0) as res:
				res.raise_for_status()
				with open(zip_path, "wb") as f_out:
					for chunk in res.iter_content(chunk_size=65536):
						if chunk:
							f_out.write(chunk)

			with zipfile.ZipFile(zip_path, "r") as zip_archive:
				zip_archive.extractall(target_dir)

			if zip_path.exists():
				os.remove(zip_path)

			logging.info(f"Successfully extracted mineru result to {target_dir}")
			return target_dir
		except Exception as exc:
			logging.error(f"Failed to download/extract zip for task {mineru_task_id}: {exc}")
			raise MineruClientError(f"Extraction error: {exc}") from exc


# Global singleton service
mineru_client_service = MineruClientService()
