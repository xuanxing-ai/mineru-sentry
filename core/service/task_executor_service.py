"""Execute recoverable page batches independently of the caller's HTTP connection."""
import base64
import logging
from pathlib import Path
import re
import threading
import time
import uuid
from typing import List, Optional

from core.config import settings
from core.constant.task_constant import ParserDefaultConstant, TaskStatusConstant
from core.entity.parse_task_entity import ParseTaskEntity
from core.entity.task_segment_entity import TaskSegmentEntity
from core.init import postgres_init
from core.repo.parse_task_repo import ParseTaskRepo
from core.repo.task_segment_repo import TaskSegmentRepo
from core.service.docker_service import docker_service
from core.service.mineru_client_service import MineruTaskUnavailableError, mineru_client_service
from core.service.stitcher_service import stitcher_service


class TaskExecutorService:
	"""Keep one executor per task in the supported single gateway process."""

	def __init__(self) -> None:
		"""Initialize execution ownership and bounded batch settings."""
		self._lock = threading.RLock()
		self._running_tasks: set[str] = set()
		self._cancelled_tasks: set[str] = set()
		self.batch_pages = int(settings.PARSE_BATCH_PAGES or ParserDefaultConstant.DEFAULT_BATCH_PAGES)
		self.task_timeout = int(settings.DEFAULT_MINERU_TASK_RESULT_TIMEOUT_SECONDS or ParserDefaultConstant.DEFAULT_TASK_TIMEOUT_SECONDS)
		if self.batch_pages < 1 or self.task_timeout < 1:
			raise ValueError("PARSE_BATCH_PAGES and DEFAULT_MINERU_TASK_RESULT_TIMEOUT_SECONDS must be positive")

	def is_running(self, task_id: str) -> bool:
		"""Report ownership in this process, including tasks waiting for GPU startup."""
		with self._lock:
			return task_id in self._running_tasks and task_id not in self._cancelled_tasks

	def cancel_task(self, task_id: str) -> None:
		"""
		Marks a task as cancelled so that its background thread will terminate promptly.
		:param task_id: Primary key string of task to cancel.
		"""
		with self._lock:
			if task_id in self._running_tasks:
				self._cancelled_tasks.add(task_id)

	def start_task_in_background(self, task_id: str, resume_start_page: Optional[int] = None) -> None:
		"""Join an existing execution or resume persisted work after a process restart."""
		with self._lock:
			if task_id in self._running_tasks:
				return
			session = postgres_init.SessionLocal()
			try:
				task = ParseTaskRepo.get_by_id(session, task_id)
				if task is None:
					raise ValueError("Task not found")
				if task.status == TaskStatusConstant.COMPLETED and task.final_md_path:
					if Path(task.final_md_path).is_file():
						return
				task.status = TaskStatusConstant.PENDING
				task.error_message = None
				ParseTaskRepo.update(session, task)
			finally:
				session.close()
			self._running_tasks.add(task_id)
			thread = threading.Thread(target=self.execute_task, args=(task_id, resume_start_page), daemon=True)
			try:
				thread.start()
			except Exception:
				self._running_tasks.discard(task_id)
				raise

	def restore_checkpoint(self, session, task: ParseTaskEntity) -> List[TaskSegmentEntity]:
		"""Recover the contiguous durable prefix, including disk writes committed before a crash."""
		segments = TaskSegmentRepo.list_by_task_id(session, task.id)
		known_pairs = {(seg.start_page, seg.end_page) for seg in segments}
		checkpoint_dirs = [Path(task.output_dir) / "checkpoints", Path(task.output_dir)]
		for chk_dir in checkpoint_dirs:
			if not chk_dir.is_dir():
				continue
			for file_path in chk_dir.glob("*.md"):
				if file_path.name in ("result.md", "document.md"):
					continue
				match = re.fullmatch(r"(\d+)_(\d+)\.md", file_path.name)
				if match:
					start_p = int(match.group(1))
					end_p = int(match.group(2))
					if start_p < task.start_page_id or end_p < start_p or end_p > task.end_page_id:
						continue
					if (start_p, end_p) not in known_pairs:
						new_seg = TaskSegmentEntity(
							id=uuid.uuid4().hex,
							create_by="system",
							task_id=task.id,
							segment_order=len(segments),
							start_page=start_p,
							end_page=end_p,
							status=TaskStatusConstant.COMPLETED,
							segment_dir=str(file_path.parent),
							md_path=str(file_path),
						)
						TaskSegmentRepo.add(session, new_seg)
						segments.append(new_seg)
						known_pairs.add((start_p, end_p))

		segments.sort(key=lambda segment: (segment.start_page, segment.segment_order))
		next_page = task.start_page_id
		completed: List[TaskSegmentEntity] = []
		for segment in segments:
			if segment.start_page < next_page:
				continue
			if segment.start_page > next_page:
				break
			if segment.end_page < next_page or segment.end_page > task.end_page_id:
				continue
			markdown_path = Path(segment.md_path) if segment.md_path else None
			is_checkpoint = markdown_path and markdown_path.parent == Path(task.output_dir) / "checkpoints"
			if segment.status != TaskStatusConstant.COMPLETED and not is_checkpoint:
				continue
			if not markdown_path or not markdown_path.is_file():
				if segment.status == TaskStatusConstant.COMPLETED:
					raise ValueError(f"Saved result for pages {segment.start_page}-{segment.end_page} is missing")
				continue
			segment.status = TaskStatusConstant.COMPLETED
			segment.error_message = None
			completed.append(segment)
			next_page = segment.end_page + 1
		# The page checkpoint and segment states are committed together.
		task.last_processed_page = next_page - 1 if completed else None
		session.commit()
		return completed

	def execute_task(self, task_id: str, resume_start_page: Optional[int] = None) -> None:
		"""Persist each completed batch before advancing; preserve all prior batches on failure."""
		gpu_counted = False
		session = postgres_init.SessionLocal()
		try:
			task = ParseTaskRepo.get_by_id(session, task_id)
			if task is None:
				return
			completed = self.restore_checkpoint(session, task)
			next_page = completed[-1].end_page + 1 if completed else task.start_page_id
			if resume_start_page is not None and resume_start_page > next_page:
				raise ValueError(f"Cannot skip uncommitted pages: next page is {next_page}")

			if next_page <= task.end_page_id:
				docker_service.increment_active_tasks()
				gpu_counted = True
				task.status = TaskStatusConstant.WAKING_GPU
				ParseTaskRepo.update(session, task)
				if not docker_service.wake_worker():
					raise RuntimeError("GPU worker failed to become healthy")
				task.status = TaskStatusConstant.PROCESSING
				ParseTaskRepo.update(session, task)

			while next_page <= task.end_page_id:
				with self._lock:
					if task_id in self._cancelled_tasks:
						logging.info("Task %s was cancelled by user request, aborting execution.", task_id)
						return
				batch_end = min(next_page + self.batch_pages - 1, task.end_page_id)
				if task.total_pages is None:
					# Non-PDF inputs have no reliable page count: checkpoint the whole document.
					batch_end = task.end_page_id
				segments = TaskSegmentRepo.list_by_task_id(session, task_id)
				segment = next((item for item in segments if item.start_page == next_page and item.end_page == batch_end), None)
				if segment is None:
					checkpoint_path = Path(task.output_dir) / "checkpoints" / f"{next_page}_{batch_end}.md"
					segment = TaskSegmentEntity(
						id=uuid.uuid4().hex, create_by="system", task_id=task_id,
						segment_order=len(segments), start_page=next_page, end_page=batch_end,
						status=TaskStatusConstant.PENDING, segment_dir=str(checkpoint_path.parent),
						md_path=str(checkpoint_path),
					)
					TaskSegmentRepo.add(session, segment)
				self.execute_segment(session, task, segment)
				completed.append(segment)
				next_page = segment.end_page + 1

			# A successful response must cover the requested range without gaps or missing files.
			expected_page = task.start_page_id
			markdown_paths: List[Path] = []
			for segment in completed:
				if segment.start_page != expected_page or not segment.md_path:
					raise ValueError("Cannot finalize a result with missing pages")
				markdown_path = Path(segment.md_path)
				if not markdown_path.is_file():
					raise ValueError("Cannot finalize a result with a missing checkpoint")
				markdown_paths.append(markdown_path)
				expected_page = segment.end_page + 1
			if expected_page != task.end_page_id + 1:
				raise ValueError("Cannot finalize an incomplete page range")
			final_path = Path(task.output_dir) / "result.md"
			stitcher_service.stitch_segments(markdown_paths, final_path)
			task.final_md_path = str(final_path)
			task.status = TaskStatusConstant.COMPLETED
			task.error_message = None
			ParseTaskRepo.update(session, task)
			logging.info("Task %s completed through page %s. Output stitched to %s", task_id, task.last_processed_page, final_path)
		except Exception as exc:
			logging.exception("Task %s interrupted; durable checkpoints retained", task_id)
			session.rollback()
			task = ParseTaskRepo.get_by_id(session, task_id)
			if task is not None:
				task.status = TaskStatusConstant.FAILED
				task.error_message = str(exc)
				ParseTaskRepo.update(session, task)
		finally:
			session.close()
			if gpu_counted:
				docker_service.decrement_active_tasks()
			with self._lock:
				self._running_tasks.discard(task_id)
				self._cancelled_tasks.discard(task_id)

	def execute_segment(self, session, task: ParseTaskEntity, segment: TaskSegmentEntity) -> None:
		"""Retry a batch, reconnect to its worker task, and atomically commit its text and page range."""
		for attempt in range(ParserDefaultConstant.DEFAULT_BATCH_ATTEMPTS):
			try:
				segment.status = TaskStatusConstant.PROCESSING
				segment.error_message = None
				TaskSegmentRepo.update(session, segment)
				if not segment.mineru_task_id:
					file_path = Path(task.file_path)
					logging.info("Parsing %s pages %s-%s (attempt %s)", task.file_name, segment.start_page, segment.end_page, attempt + 1)
					return_images_enabled = bool(getattr(task, "return_images", False))
					worker_task_id = mineru_client_service.submit_parse_task(
						file_path=file_path, file_name=task.file_name, backend=task.backend,
						effort=task.effort, parse_method=task.parse_method,
						formula_enable=task.formula_enable, table_enable=task.table_enable,
						return_images=return_images_enabled,
						start_page_id=segment.start_page, end_page_id=segment.end_page,
					)
					segment.mineru_task_id = worker_task_id
					TaskSegmentRepo.update(session, segment)
				self._poll_mineru_status(segment.mineru_task_id)
				markdown, images_dict = mineru_client_service.get_task_result(segment.mineru_task_id)
				# Every response replays this exact durable text, including batch separators.
				content = markdown.strip() + "\n\n" if markdown.strip() else ""
				checkpoint_path = Path(segment.md_path)
				stitcher_service.write_checkpoint(checkpoint_path, content)
				if getattr(task, "return_images", False) and images_dict:
					self._save_images(task, images_dict)
				segment.status = TaskStatusConstant.COMPLETED
				segment.error_message = None
				task.last_processed_page = segment.end_page
				session.commit()
				logging.info("Checkpoint saved: %s through page %s", task.file_name, segment.end_page)
				return
			except Exception as exc:
				session.rollback()
				segment.status = TaskStatusConstant.FAILED
				segment.error_message = str(exc)
				# Preserve unknown jobs for reconnection; resubmit only definitive failures.
				if isinstance(exc, MineruTaskUnavailableError):
					segment.mineru_task_id = None
				TaskSegmentRepo.update(session, segment)
				if attempt + 1 == ParserDefaultConstant.DEFAULT_BATCH_ATTEMPTS:
					raise
				logging.warning("Retrying batch %s after error: %s", segment.id, exc)
				time.sleep(2)

	def _poll_mineru_status(self, mineru_task_id: str) -> None:
		"""Wait with a deadline; discard only definitively failed or missing worker jobs."""
		deadline = time.monotonic() + self.task_timeout
		while time.monotonic() < deadline:
			docker_service.touch_activity()
			status = mineru_client_service.get_task_status(mineru_task_id)
			if status == TaskStatusConstant.COMPLETED:
				return
			if status == TaskStatusConstant.FAILED:
				raise MineruTaskUnavailableError("MinerU reported a failed batch")
			time.sleep(2)
		raise TimeoutError("MinerU batch polling timed out; upload the same file to reconnect")

	def _save_images(self, task: ParseTaskEntity, images_dict: dict[str, str]) -> None:
		"""
		Decode base64 Data URIs and save images directly into the task's output image directory.
		:param task: Parent parsing task entity.
		:param images_dict: Mapping of image filename to base64 Data URI string.
		"""
		if not task.output_dir or not images_dict:
			return
		task_images_dir = Path(task.output_dir) / "images"
		task_images_dir.mkdir(parents=True, exist_ok=True)
		saved_count = 0
		for image_name, data_uri in images_dict.items():
			try:
				if "," in data_uri:
					raw_b64 = data_uri.split(",", 1)[1]
				else:
					raw_b64 = data_uri
				image_bytes = base64.b64decode(raw_b64)
				destination = task_images_dir / Path(image_name).name
				destination.write_bytes(image_bytes)
				saved_count += 1
			except Exception as exc:
				logging.warning("Failed to decode and save image %s for task %s: %s", image_name, task.id, exc)
		if saved_count > 0:
			logging.info("Saved %d images for task %s into %s", saved_count, task.id, task_images_dir)


task_executor_service = TaskExecutorService()

