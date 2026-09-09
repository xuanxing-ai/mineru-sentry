"""Task executor service orchestrating document parsing, polling, error tracking, and resume."""
import datetime
from pathlib import Path
import shutil
import threading
import time
import uuid
from typing import List, Optional, Tuple
import logging

from core.config import settings
from core.init import postgres_init
from core.constant.task_constant import TaskStatusConstant
from core.entity.parse_task_entity import ParseTaskEntity
from core.entity.task_segment_entity import TaskSegmentEntity
from core.repo.parse_task_repo import ParseTaskRepo
from core.repo.task_segment_repo import TaskSegmentRepo
from core.service.docker_service import docker_service
from core.service.mineru_client_service import mineru_client_service
from core.service.stitcher_service import stitcher_service


class TaskExecutorService:
	"""
	Executes and orchestrates document parsing jobs without async/await.
	"""

	def start_task_in_background(self, task_id: str) -> None:
		"""
		Spawns a synchronous daemon thread to execute the task in background.
		:param task_id: Primary key string of the ParseTaskEntity.
		"""
		thread = threading.Thread(target=self.execute_task, args=(task_id,), daemon=True)
		thread.start()

	def execute_task(self, task_id: str) -> None:
		"""
		Coordinates full task lifecycle: waking GPU, submitting to worker, polling, downloading, and stitching.
		:param task_id: Primary key string of the ParseTaskEntity.
		"""
		logging.info(f"Executing parse task: {task_id}")
		session = postgres_init.SessionLocal()
		try:
			task = ParseTaskRepo.get_by_id(session, task_id)
			if not task:
				logging.error(f"Task {task_id} not found in database.")
				return

			task.status = TaskStatusConstant.WAKING_GPU
			ParseTaskRepo.update(session, task)
		finally:
			session.close()

		# Step 1: Wake up GPU worker container
		docker_service.increment_active_tasks()
		try:
			worker_ready = docker_service.wake_worker()
			if not worker_ready:
				self._mark_task_failure(task_id, "GPU worker failed to start or become healthy.")
				return

			# Update status to processing
			session = postgres_init.SessionLocal()
			try:
				task = ParseTaskRepo.get_by_id(session, task_id)
				task.status = TaskStatusConstant.PROCESSING
				ParseTaskRepo.update(session, task)
			finally:
				session.close()

			# Step 2: Register task segment
			task_output_dir = Path(task.output_dir)
			task_output_dir.mkdir(parents=True, exist_ok=True)

			session = postgres_init.SessionLocal()
			try:
				existing_segments = TaskSegmentRepo.list_by_task_id(session, task_id)
				segment_order = len(existing_segments)
				segment_dir = task_output_dir / f"segment_{segment_order}"
				segment_dir.mkdir(parents=True, exist_ok=True)

				# Keep the primary key within VARCHAR(32); task and order have separate fields.
				segment_id = uuid.uuid4().hex
				seg_entity = TaskSegmentEntity(
					id=segment_id,
					create_by="system",
					task_id=task_id,
					segment_order=segment_order,
					start_page=task.start_page_id,
					end_page=task.end_page_id,
					status=TaskStatusConstant.PROCESSING,
					segment_dir=str(segment_dir),
				)
				TaskSegmentRepo.add(session, seg_entity)
				segment_id = seg_entity.id
			finally:
				session.close()

			# Step 3: Submit to mineru-api
			file_path_obj = Path(task.file_path)
			file_name_str = task.file_name
			backend_str = task.backend
			effort_str = task.effort
			method_str = task.parse_method
			formula_val = task.formula_enable
			table_val = task.table_enable
			start_page_val = task.start_page_id
			end_page_val = task.end_page_id

			logging.info(f"Submitting task {task_id} to mineru worker: pages {start_page_val}-{end_page_val}")
			mineru_task_id = mineru_client_service.submit_parse_task(
				file_path=file_path_obj,
				file_name=file_name_str,
				backend=backend_str,
				effort=effort_str,
				parse_method=method_str,
				formula_enable=formula_val,
				table_enable=table_val,
				start_page_id=start_page_val,
				end_page_id=end_page_val,
			)

			session = postgres_init.SessionLocal()
			try:
				seg_entity = TaskSegmentRepo.get_by_id(session, segment_id)
				seg_entity.mineru_task_id = mineru_task_id
				TaskSegmentRepo.update(session, seg_entity)
			finally:
				session.close()

			# Step 4: Poll status synchronously
			terminal_status = self._poll_mineru_status(mineru_task_id)
			if terminal_status != "completed":
				self._mark_task_failure(task_id, f"MinerU API reported failure status: {terminal_status}")
				return

			# Step 5: Download and unpack results
			logging.info(f"Downloading results for task {mineru_task_id} into {segment_dir}")
			mineru_client_service.download_and_extract_zip(mineru_task_id, segment_dir)

			# Step 6: Mark segment completed and stitch
			self._finalize_task_and_stitch(task_id, segment_id, segment_dir)

		except Exception as exc:
			logging.exception(f"Error during execution of task {task_id}: {exc}")
			self._mark_task_failure(task_id, str(exc))
		finally:
			docker_service.decrement_active_tasks()

	def _poll_mineru_status(self, mineru_task_id: str) -> str:
		"""
		Polls mineru-api status synchronously every 2 seconds.
		:param mineru_task_id: Task ID string.
		:return: Terminal status string (completed or failed).
		"""
		while True:
			time.sleep(2.0)
			docker_service.touch_activity()
			try:
				current_status = mineru_client_service.get_task_status(mineru_task_id)
				if current_status in ("completed", "failed"):
					return current_status
			except Exception as exc:
				logging.warning(f"Transient error polling mineru task {mineru_task_id}: {exc}")

	def _finalize_task_and_stitch(self, task_id: str, segment_id: str, segment_dir: Path) -> None:
		"""
		Updates segment record and triggers stitching for all completed segments.
		:param task_id: Primary key string.
		:param segment_id: Segment identifier string.
		:param segment_dir: Path to segment output directory.
		"""
		session = postgres_init.SessionLocal()
		try:
			seg = TaskSegmentRepo.get_by_id(session, segment_id)
			seg.status = TaskStatusConstant.COMPLETED

			md_files = list(segment_dir.glob("**/*.md"))
			if md_files:
				seg.md_path = str(md_files[0])

			middle_files = list(segment_dir.glob("**/*_middle.json"))
			if middle_files:
				seg.middle_json_path = str(middle_files[0])
			TaskSegmentRepo.update(session, seg)

			task = ParseTaskRepo.get_by_id(session, task_id)
			task.status = TaskStatusConstant.COMPLETED
			task.completed_at = datetime.datetime.utcnow()
			task.last_processed_page = task.end_page_id

			all_segments = TaskSegmentRepo.list_by_task_id(session, task_id)
			completed_segments = [s for s in all_segments if s.status == TaskStatusConstant.COMPLETED]

			seg_dirs: List[Path] = [Path(s.segment_dir) for s in completed_segments if s.segment_dir]
			page_ranges: List[Tuple[int, int]] = [(s.start_page, s.end_page) for s in completed_segments]

			base_stem = Path(task.file_name).stem
			output_dir_obj = Path(task.output_dir)
			final_md, _ = stitcher_service.stitch_segments(
				segment_dirs=seg_dirs,
				output_dir=output_dir_obj,
				final_filename=base_stem,
				page_ranges=page_ranges,
			)

			task.final_md_path = str(final_md)
			ParseTaskRepo.update(session, task)
			logging.info(f"Task {task_id} successfully finalized. Output: {final_md}")
		finally:
			session.close()

	def _mark_task_failure(self, task_id: str, error_message: str) -> None:
		"""
		Marks task as failed and logs error message.
		:param task_id: Primary key string.
		:param error_message: Description of failure cause.
		"""
		session = postgres_init.SessionLocal()
		try:
			task = ParseTaskRepo.get_by_id(session, task_id)
			if task:
				task.status = TaskStatusConstant.FAILED
				task.error_message = error_message
				ParseTaskRepo.update(session, task)
				logging.error(f"Task {task_id} marked FAILED: {error_message}")
		finally:
			session.close()

	def create_resume_task(self, original_task_id: str, start_page_id: Optional[int] = None) -> ParseTaskEntity:
		"""
		Creates a new task inheriting earlier completed segments for resumed stitching.
		:param original_task_id: ID of the failed/interrupted task.
		:param start_page_id: Optional explicit starting page offset.
		:return: Created ParseTaskEntity.
		"""
		session = postgres_init.SessionLocal()
		try:
			orig = ParseTaskRepo.get_by_id(session, original_task_id)
			if not orig:
				raise ValueError(f"Task {original_task_id} not found.")

			if start_page_id is not None:
				effective_start = start_page_id
			elif orig.last_processed_page is not None:
				effective_start = orig.last_processed_page + 1
			else:
				effective_start = 0

			storage_root = settings.SHARED_DATA_DIR if settings.SHARED_DATA_DIR else "/usr/model/MinerU/data"
			new_id = f"res_{orig.id[:28]}"
			resumed_output_dir = Path(storage_root) / "tasks" / new_id
			resumed_output_dir.mkdir(parents=True, exist_ok=True)

			resumed_task = ParseTaskEntity(
				id=new_id,
				create_by="system",
				file_name=orig.file_name,
				file_hash=orig.file_hash,
				file_path=orig.file_path,
				file_size=orig.file_size,
				total_pages=orig.total_pages,
				status=TaskStatusConstant.PENDING,
				backend=orig.backend,
				effort=orig.effort,
				parse_method=orig.parse_method,
				formula_enable=orig.formula_enable,
				table_enable=orig.table_enable,
				start_page_id=effective_start,
				end_page_id=orig.end_page_id,
				output_dir=str(resumed_output_dir),
				is_resumed=True,
				parent_task_id=orig.id,
			)
			ParseTaskRepo.add(session, resumed_task)

			# Copy previous completed segments
			orig_segments = TaskSegmentRepo.list_by_task_id(session, orig.id)
			for idx, orig_seg in enumerate(orig_segments):
				if orig_seg.status == TaskStatusConstant.COMPLETED and orig_seg.segment_dir:
					new_seg_dir = resumed_output_dir / f"segment_{idx}"
					if Path(orig_seg.segment_dir).exists():
						shutil.copytree(orig_seg.segment_dir, new_seg_dir, dirs_exist_ok=True)

					# Copied segments need their own primary keys within VARCHAR(32).
					copied_segment_id = uuid.uuid4().hex
					copied_seg = TaskSegmentEntity(
						id=copied_segment_id,
						create_by="system",
						task_id=resumed_task.id,
						segment_order=idx,
						start_page=orig_seg.start_page,
						end_page=orig_seg.end_page,
						status=TaskStatusConstant.COMPLETED,
						mineru_task_id=orig_seg.mineru_task_id,
						segment_dir=str(new_seg_dir),
						md_path=str(new_seg_dir / Path(orig_seg.md_path).name) if orig_seg.md_path else None,
						middle_json_path=str(new_seg_dir / Path(orig_seg.middle_json_path).name) if orig_seg.middle_json_path else None,
					)
					TaskSegmentRepo.add(session, copied_seg)

			self.start_task_in_background(resumed_task.id)
			return resumed_task
		finally:
			session.close()


# Global singleton service
task_executor_service = TaskExecutorService()
