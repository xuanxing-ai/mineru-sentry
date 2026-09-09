"""Service handling business assembly and data conversion for parse API endpoints."""
import hashlib
from pathlib import Path
from typing import List, Optional
import uuid
from fastapi import HTTPException
import logging

from core.config import settings
from core.init import postgres_init
from core.constant.task_constant import TaskStatusConstant
from core.entity.parse_task_entity import ParseTaskEntity
from core.repo.parse_task_repo import ParseTaskRepo
from core.repo.task_segment_repo import TaskSegmentRepo
from core.dto.task_req import ParseTaskResumeReq, ParseTaskSubmitReq
from core.dto.task_vo import (
	IntermediateResultVo,
	ParseTaskDetailVo,
	ParseTaskVo,
	TaskSegmentVo,
)
from core.service.task_executor_service import task_executor_service


class ParseService:
	"""
	Business logic layer for parsing operations.
	"""

	@staticmethod
	def handle_submit_parse(file_content: bytes, original_filename: str, req: ParseTaskSubmitReq) -> ParseTaskVo:
		"""
		Validates file, checks deduplication/auto-resume, persists task entity, and triggers executor.
		:param file_content: Binary file content bytes.
		:param original_filename: Name of the uploaded file.
		:param req: ParseTaskSubmitReq instance.
		:return: ParseTaskVo containing task details.
		"""
		safe_name = Path(original_filename).name
		file_hash = hashlib.sha256(file_content).hexdigest()
		file_size = len(file_content)

		storage_root = settings.SHARED_DATA_DIR if settings.SHARED_DATA_DIR else "/usr/model/MinerU/data"
		uploads_dir = Path(storage_root) / "uploads"
		uploads_dir.mkdir(parents=True, exist_ok=True)

		saved_file_path = uploads_dir / f"{file_hash}_{safe_name}"
		with open(saved_file_path, "wb") as f_out:
			f_out.write(file_content)

		session = postgres_init.SessionLocal()
		try:
			# Check for auto-resume if enabled
			auto_resume_flag = req.auto_resume
			start_p = req.start_page_id
			if auto_resume_flag and start_p == 0:
				past_records = ParseTaskRepo.list_by_file_hash(session, file_hash)
				for past in past_records:
					if past.status in (TaskStatusConstant.FAILED, TaskStatusConstant.INTERRUPTED):
						if past.last_processed_page is not None:
							logging.info(f"Found failed previous task {past.id}, auto-resuming...")
							next_start_page = past.last_processed_page + 1
							resumed_entity = task_executor_service.create_resume_task(past.id, next_start_page)
							return ParseTaskVo.model_validate(resumed_entity)

			# Create new task
			task_uuid = str(uuid.uuid4()).replace("-", "")[:32]
			tasks_dir = Path(storage_root) / "tasks" / task_uuid
			tasks_dir.mkdir(parents=True, exist_ok=True)

			backend_val = req.backend
			effort_val = req.effort
			method_val = req.parse_method
			formula_val = req.formula_enable
			table_val = req.table_enable
			end_p = req.end_page_id

			entity = ParseTaskEntity(
				id=task_uuid,
				create_by="system",
				file_name=safe_name,
				file_hash=file_hash,
				file_path=str(saved_file_path),
				file_size=file_size,
				status=TaskStatusConstant.PENDING,
				backend=backend_val,
				effort=effort_val,
				parse_method=method_val,
				formula_enable=formula_val,
				table_enable=table_val,
				start_page_id=start_p,
				end_page_id=end_p,
				output_dir=str(tasks_dir),
			)
			created_entity = ParseTaskRepo.add(session, entity)
			task_executor_service.start_task_in_background(created_entity.id)
			return ParseTaskVo.model_validate(created_entity)
		finally:
			session.close()

	@staticmethod
	def handle_resume_parse(req: ParseTaskResumeReq) -> ParseTaskVo:
		"""
		Processes explicit resume request by delegating to task executor.
		:param req: ParseTaskResumeReq instance.
		:return: ParseTaskVo of the created resume task.
		"""
		task_id_val = req.task_id
		start_page_val = req.start_page_id
		try:
			resumed_entity = task_executor_service.create_resume_task(task_id_val, start_page_val)
			return ParseTaskVo.model_validate(resumed_entity)
		except ValueError as exc:
			raise HTTPException(status_code=404, detail=str(exc)) from exc

	@staticmethod
	def handle_get_task(task_id: str) -> ParseTaskDetailVo:
		"""
		Retrieves task details and its executed segments.
		:param task_id: Primary key string.
		:return: ParseTaskDetailVo instance.
		"""
		session = postgres_init.SessionLocal()
		try:
			entity = ParseTaskRepo.get_by_id(session, task_id)
			if not entity:
				raise HTTPException(status_code=404, detail="Task not found")

			segments = TaskSegmentRepo.list_by_task_id(session, task_id)
			segment_vos = [TaskSegmentVo.model_validate(s) for s in segments]

			base_vo = ParseTaskVo.model_validate(entity)
			return ParseTaskDetailVo(
				**base_vo.model_dump(),
				final_md_path=entity.final_md_path,
				segments=segment_vos,
			)
		finally:
			session.close()

	@staticmethod
	def handle_get_result_path(task_id: str) -> Path:
		"""
		Validates completion status and returns path to final stitched Markdown.
		:param task_id: Primary key string.
		:return: Path object to Markdown file.
		"""
		session = postgres_init.SessionLocal()
		try:
			entity = ParseTaskRepo.get_by_id(session, task_id)
			if not entity:
				raise HTTPException(status_code=404, detail="Task not found")

			if entity.status != TaskStatusConstant.COMPLETED or not entity.final_md_path:
				raise HTTPException(status_code=400, detail=f"Task is not completed (status: {entity.status})")

			md_path = Path(entity.final_md_path)
			if not md_path.exists():
				raise HTTPException(status_code=404, detail="Result file not found on disk")
			return md_path
		finally:
			session.close()

	@staticmethod
	def handle_get_intermediate(task_id: str) -> IntermediateResultVo:
		"""
		Collects available intermediate files and markdown snippet from task directory.
		:param task_id: Primary key string.
		:return: IntermediateResultVo instance.
		"""
		session = postgres_init.SessionLocal()
		try:
			entity = ParseTaskRepo.get_by_id(session, task_id)
			if not entity:
				raise HTTPException(status_code=404, detail="Task not found")

			task_dir = Path(entity.output_dir)
			files_list: List[str] = []
			preview_text: Optional[str] = None

			if task_dir.exists():
				files_list = [str(p.relative_to(task_dir)) for p in task_dir.glob("**/*") if p.is_file()]
				md_files = list(task_dir.glob("**/*.md"))
				if md_files:
					try:
						with open(md_files[0], "r", encoding="utf-8") as f:
							preview_text = f.read(2000)
					except Exception:
						pass

			segments = TaskSegmentRepo.list_by_task_id(session, task_id)
			completed_segs = [s for s in segments if s.status == TaskStatusConstant.COMPLETED]

			return IntermediateResultVo(
				task_id=entity.id,
				status=entity.status,
				file_name=entity.file_name,
				last_processed_page=entity.last_processed_page,
				completed_segments_count=len(completed_segs),
				available_md_preview=preview_text,
				available_files=files_list,
			)
		finally:
			session.close()

	@staticmethod
	def handle_list_by_filename(filename: str) -> List[ParseTaskVo]:
		"""
		Lists tasks matching a specific filename.
		:param filename: Filename string.
		:return: List of ParseTaskVo.
		"""
		session = postgres_init.SessionLocal()
		try:
			entities = ParseTaskRepo.list_by_file_name(session, filename)
			return [ParseTaskVo.model_validate(e) for e in entities]
		finally:
			session.close()

	@staticmethod
	def handle_list_by_hash(file_hash: str) -> List[ParseTaskVo]:
		"""
		Lists tasks matching a specific SHA-256 hash.
		:param file_hash: Hash string.
		:return: List of ParseTaskVo.
		"""
		session = postgres_init.SessionLocal()
		try:
			entities = ParseTaskRepo.list_by_file_hash(session, file_hash)
			return [ParseTaskVo.model_validate(e) for e in entities]
		finally:
			session.close()


# Global singleton service
parse_service = ParseService()
