"""HTTP Client service for synchronous communication with mineru-api."""
from pathlib import Path
from typing import Optional
import logging
import requests

from core.config import settings


class MineruClientError(Exception):
	"""Exception for communication failures with mineru-api."""
	pass


class MineruTaskUnavailableError(MineruClientError):
	"""The worker has definitively lost or failed this task; a new submission is required."""
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
			"return_middle_json": "false",
			"return_images": "false",
			"response_format_zip": "false",
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
			if res.status_code == 404:
				raise MineruTaskUnavailableError("Worker task no longer exists")
			res.raise_for_status()
			json_res = res.json()
			status = json_res.get("status", "unknown")
			return str(status)
		except MineruTaskUnavailableError:
			raise
		except Exception as exc:
			logging.warning(f"Error polling mineru task {mineru_task_id}: {exc}")
			raise MineruClientError(f"Polling error: {exc}") from exc

	def get_task_markdown(self, mineru_task_id: str) -> str:
		"""Read the single uploaded document's Markdown from MinerU's JSON result."""
		endpoint = f"{self.base_url}/tasks/{mineru_task_id}/result"
		try:
			response = requests.get(endpoint, timeout=300.0)
			response.raise_for_status()
			payload = response.json()
			results = payload.get("results")
			if not isinstance(results, dict) or len(results) != 1:
				raise MineruClientError("Expected exactly one document in MinerU results")
			document = next(iter(results.values()))
			markdown = document.get("md_content") if isinstance(document, dict) else None
			# An empty page is valid; missing output is not a completed checkpoint.
			if not isinstance(markdown, str):
				raise MineruClientError("MinerU result is missing md_content")
			return markdown
		except Exception as exc:
			raise MineruClientError(f"Failed to read MinerU result: {exc}") from exc


# Global singleton service
mineru_client_service = MineruClientService()
