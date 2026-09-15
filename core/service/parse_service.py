"""Resolve same-name uploads to durable tasks and return Markdown directly."""
import hashlib
import io
import logging
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Iterator, List, Optional
from urllib.parse import quote
import uuid
import zipfile

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from pypdf import PdfReader

from core.config import settings
from core.constant.task_constant import TaskStatusConstant
from core.dto.task_req import ParseTaskResumeReq, ParseTaskSubmitReq
from core.dto.task_vo import ParseTaskDetailVo, ParseTaskVo, TaskSegmentVo
from core.entity.parse_task_entity import ParseTaskEntity
from core.init import postgres_init
from core.repo.parse_task_repo import ParseTaskRepo
from core.repo.task_segment_repo import TaskSegmentRepo
from core.service.task_executor_service import task_executor_service


class ParseService:
	"""Use filename identity, content validation, and immutable batches for reconnectable results."""

	def __init__(self) -> None:
		"""Serialize submission decisions while background tasks continue independently."""
		self._submission_lock = threading.RLock()

	def handle_submit_parse(self, upload: UploadFile, req: ParseTaskSubmitReq, stream: bool = False):
		"""Spool an upload, reuse or resume its task, and return complete or incremental text."""
		task_id = self.prepare_task(upload, req)
		return self.result_response(task_id, stream)

	def prepare_task(self, upload: UploadFile, req: ParseTaskSubmitReq) -> str:
		"""Match a filename safely and reject conflicting contents or missing resume prefixes."""
		original_filename = upload.filename or "document.pdf"
		safe_name = Path(original_filename.replace("\\", "/")).name
		if safe_name in ("", ".", "..") or len(safe_name) > 255:
			raise HTTPException(status_code=422, detail="Invalid filename")
		storage_root = Path(settings.SHARED_DATA_DIR or "/usr/model/MinerU/data").resolve()
		uploads_dir = storage_root / "uploads"
		uploads_dir.mkdir(parents=True, exist_ok=True)
		temporary_path = uploads_dir / f".{uuid.uuid4().hex}.upload"
		digest = hashlib.sha256()
		file_size = 0
		try:
			with temporary_path.open("wb") as output:
				while chunk := upload.file.read(1048576):
					digest.update(chunk)
					file_size += len(chunk)
					output.write(chunk)
				output.flush()
				os.fsync(output.fileno())
			if file_size == 0:
				raise HTTPException(status_code=422, detail="The uploaded file is empty")
			file_hash = digest.hexdigest()
			total_pages = None
			end_page = req.end_page_id
			if safe_name.lower().endswith(".pdf"):
				try:
					with temporary_path.open("rb") as source:
						reader = PdfReader(source)
						total_pages = len(reader.pages)
					if not total_pages:
						raise ValueError("PDF has no pages")
				except Exception as exc:
					raise HTTPException(status_code=422, detail="Cannot read PDF pages") from exc
				end_page = min(end_page, total_pages - 1)
			elif req.start_page_id:
				raise HTTPException(status_code=422, detail="Page offsets require a PDF")

			with self._submission_lock:
				session = postgres_init.SessionLocal()
				try:
					past_records = ParseTaskRepo.list_by_file_name(session, safe_name)
					is_force = req.force
					if is_force and past_records:
						for old_task in past_records:
							old_task_id = old_task.id
							task_executor_service.cancel_task(old_task_id)
							TaskSegmentRepo.delete_by_task_id(session, old_task_id)
							ParseTaskRepo.delete(session, old_task_id)
							old_output_dir = old_task.output_dir
							if old_output_dir:
								shutil.rmtree(old_output_dir, ignore_errors=True)
							old_final_path = old_task.final_md_path
							if old_final_path:
								Path(old_final_path).unlink(missing_ok=True)
						past_records = []

					task = past_records[0] if past_records else None
					if task is not None:
						if task.file_hash != file_hash:
							raise HTTPException(status_code=409, detail="This filename belongs to different content; use a different filename")
						option_names = ("backend", "effort", "parse_method", "formula_enable", "table_enable", "return_images")
						if any(getattr(task, name) != getattr(req, name) for name in option_names):
							raise HTTPException(status_code=409, detail="Parsing options differ from the saved task; use a different filename")
						stored_end = min(task.end_page_id, total_pages - 1) if total_pages else task.end_page_id
						if task.start_page_id != 0 or stored_end != end_page:
							raise HTTPException(status_code=409, detail="Saved task has a different page range; use a different filename")
						if not task_executor_service.is_running(task.id):
							task.total_pages = total_pages
							task.end_page_id = end_page
							ParseTaskRepo.update(session, task)
					else:
						if req.start_page_id and not is_force:
							raise HTTPException(status_code=409, detail="No saved prefix exists; submit this document from page 0 first")
						task_id = uuid.uuid4().hex
						task_dir = storage_root / "tasks" / task_id
						task_dir.mkdir(parents=True, exist_ok=True)
						saved_path = uploads_dir / f"{file_hash}_{safe_name}"
						os.replace(temporary_path, saved_path)
						task = ParseTaskEntity(
							id=task_id, create_by="system", file_name=safe_name, file_hash=file_hash,
							file_path=str(saved_path), file_size=file_size, total_pages=total_pages,
							status=TaskStatusConstant.PENDING, backend=req.backend, effort=req.effort,
							parse_method=req.parse_method, formula_enable=req.formula_enable,
							table_enable=req.table_enable, return_images=req.return_images,
							start_page_id=0, end_page_id=end_page,
							output_dir=str(task_dir),
						)
						ParseTaskRepo.add(session, task)
					task_id = task.id
					# Re-uploading also restores a removed source file for an unfinished task.
					if temporary_path.is_file() and not Path(task.file_path).is_file():
						Path(task.file_path).parent.mkdir(parents=True, exist_ok=True)
						os.replace(temporary_path, task.file_path)
				finally:
					session.close()
				start_offset = 0 if is_force else req.start_page_id
				self.resume_task(task_id, start_offset)
				return task_id
		finally:
			temporary_path.unlink(missing_ok=True)

	def resume_task(self, task_id: str, start_page_id: Optional[int] = None) -> None:
		"""Resume the same task without allowing an offset to skip unsaved pages."""
		resume_offset = None
		with self._submission_lock:
			session = postgres_init.SessionLocal()
			try:
				task = ParseTaskRepo.get_by_id(session, task_id)
				if task is None:
					raise HTTPException(status_code=404, detail="Task not found")
				if task.status == TaskStatusConstant.COMPLETED and task.final_md_path:
					if Path(task.final_md_path).is_file():
						return
				if not task_executor_service.is_running(task_id):
					try:
						task_executor_service.restore_checkpoint(session, task)
					except ValueError as exc:
						raise HTTPException(status_code=409, detail=str(exc)) from exc
				next_page = task.last_processed_page + 1 if task.last_processed_page is not None else task.start_page_id
				if start_page_id and start_page_id > next_page:
					raise HTTPException(status_code=409, detail=f"Only pages before {next_page} are saved; resume from {next_page} or omit s")
				if start_page_id is not None and start_page_id > 0:
					resume_offset = start_page_id
			finally:
				session.close()
			task_executor_service.start_task_in_background(task_id, resume_start_page=resume_offset)

	def result_response(self, task_id: str, stream: bool = False):
		"""Return Markdown in the response body with no download disposition or file metadata."""
		headers = {"X-Sentry-Task-ID": task_id, "Cache-Control": "no-store", "X-Accel-Buffering": "no"}
		chunks = self.iter_result(task_id)
		if stream:
			return StreamingResponse(chunks, media_type="text/markdown; charset=utf-8", headers=headers)
		try:
			content = "".join(chunks)
		except RuntimeError as exc:
			raise HTTPException(status_code=502, detail=str(exc), headers=headers) from exc
		return PlainTextResponse(content, media_type="text/markdown", headers=headers)

	def iter_result(self, task_id: str) -> Iterator[str]:
		"""Replay the durable prefix then follow new batches; abort the stream on a failed task."""
		next_page: Optional[int] = None
		emitted = False
		while True:
			session = postgres_init.SessionLocal()
			try:
				task = ParseTaskRepo.get_by_id(session, task_id)
				if task is None:
					raise RuntimeError("Task no longer exists")
				if next_page is None:
					next_page = task.start_page_id
				status = task.status
				error = task.error_message
				end_page = task.end_page_id
				final_path = task.final_md_path
				segments = TaskSegmentRepo.list_by_task_id(session, task_id)
				ready = sorted(
					[(segment.start_page, segment.end_page, segment.md_path) for segment in segments
					 if segment.status == TaskStatusConstant.COMPLETED],
					key=lambda segment: segment[0],
				)
			finally:
				session.close()
			if not emitted and status == TaskStatusConstant.COMPLETED and final_path:
				with Path(final_path).open("r", encoding="utf-8") as source:
					while chunk := source.read(65536):
						yield chunk
				return
			for start, end, markdown_path in ready:
				if start < next_page:
					continue
				if start != next_page:
					break
				if not markdown_path or not Path(markdown_path).is_file():
					raise RuntimeError("A saved batch is missing; the result is incomplete")
				with Path(markdown_path).open("r", encoding="utf-8") as source:
					while chunk := source.read(65536):
						yield chunk
				emitted = True
				next_page = end + 1
			if status == TaskStatusConstant.COMPLETED:
				if next_page <= end_page:
					raise RuntimeError("Completed result contains a page gap")
				return
			if status in (TaskStatusConstant.FAILED, TaskStatusConstant.INTERRUPTED):
				raise RuntimeError(f"Parsing interrupted; upload the same file to resume. {error or ''}")
			if not task_executor_service.is_running(task_id):
				# Re-read once when an executor terminates between the snapshot and this check.
				session = postgres_init.SessionLocal()
				try:
					current = ParseTaskRepo.get_by_id(session, task_id)
					if current.status not in (TaskStatusConstant.COMPLETED, TaskStatusConstant.FAILED):
						raise RuntimeError("Execution stopped; upload the same file to resume")
				finally:
					session.close()
			time.sleep(0.25)

	def handle_resume_parse(self, req: ParseTaskResumeReq):
		"""Resume an existing task ID and return its full Markdown body."""
		self.resume_task(req.task_id, req.start_page_id)
		return self.result_response(req.task_id)

	def handle_filename_result(self, filename: str):
		"""Return cached text or resume the latest saved task for this exact filename."""
		session = postgres_init.SessionLocal()
		try:
			tasks = ParseTaskRepo.list_by_file_name(session, filename)
			if not tasks:
				raise HTTPException(status_code=404, detail="Filename not found")
			task_id = tasks[0].id
		finally:
			session.close()
		self.resume_task(task_id)
		return self.result_response(task_id)

	def handle_get_result(self, task_id: str):
		"""Return an already completed Markdown body without attachment headers."""
		session = postgres_init.SessionLocal()
		try:
			task = ParseTaskRepo.get_by_id(session, task_id)
			if task is None:
				raise HTTPException(status_code=404, detail="Task not found")
			if task.status != TaskStatusConstant.COMPLETED:
				raise HTTPException(status_code=409, detail="Task is not completed")
		finally:
			session.close()
		return self.result_response(task_id)

	@staticmethod
	def handle_get_intermediate(task_id: str):
		"""Return only the contiguous saved Markdown prefix, without resuming execution."""
		session = postgres_init.SessionLocal()
		try:
			task = ParseTaskRepo.get_by_id(session, task_id)
			if task is None:
				raise HTTPException(status_code=404, detail="Task not found")
			segments = TaskSegmentRepo.list_by_task_id(session, task_id)
			segments.sort(key=lambda segment: segment.start_page)
			next_page = task.start_page_id
			parts: List[str] = []
			for segment in segments:
				if segment.status != TaskStatusConstant.COMPLETED or segment.start_page < next_page:
					continue
				if segment.start_page != next_page:
					break
				if not segment.md_path or not Path(segment.md_path).is_file():
					raise HTTPException(status_code=409, detail="A saved batch is missing")
				parts.append(Path(segment.md_path).read_text(encoding="utf-8"))
				next_page = segment.end_page + 1
			content = "".join(parts)
			return PlainTextResponse(content, media_type="text/markdown")
		finally:
			session.close()

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

			images_list: List[str] = []
			if entity.output_dir:
				images_dir = Path(entity.output_dir) / "images"
				if images_dir.is_dir():
					images_list = sorted([p.name for p in images_dir.iterdir() if p.is_file()])

			base_vo = ParseTaskVo.model_validate(entity)
			return ParseTaskDetailVo(
				**base_vo.model_dump(),
				segments=segment_vos,
				images=images_list,
			)
		finally:
			session.close()

	@staticmethod
	def handle_list_task_images(task_id: str) -> List[str]:
		"""
		Lists extracted image filenames for a specific task.
		:param task_id: Primary key string.
		:return: List of image filename strings.
		"""
		session = postgres_init.SessionLocal()
		try:
			entity = ParseTaskRepo.get_by_id(session, task_id)
			if not entity:
				raise HTTPException(status_code=404, detail="Task not found")
			if not entity.output_dir:
				return []
			images_dir = Path(entity.output_dir) / "images"
			if not images_dir.is_dir():
				return []
			return sorted([p.name for p in images_dir.iterdir() if p.is_file()])
		finally:
			session.close()

	@staticmethod
	def handle_get_task_image(task_id: str, filename: str) -> FileResponse:
		"""
		Returns an extracted image file for a specific task.
		:param task_id: Primary key string.
		:param filename: Filename of the target image.
		:return: FileResponse containing binary image data.
		"""
		safe_filename = Path(filename).name
		if safe_filename != filename or safe_filename in ("", ".", ".."):
			raise HTTPException(status_code=400, detail="Invalid filename")
		session = postgres_init.SessionLocal()
		try:
			entity = ParseTaskRepo.get_by_id(session, task_id)
			if not entity:
				raise HTTPException(status_code=404, detail="Task not found")
			if not entity.output_dir:
				raise HTTPException(status_code=404, detail="Task output directory not found")
			images_dir = (Path(entity.output_dir) / "images").resolve()
			image_path = (images_dir / safe_filename).resolve()
			if not image_path.is_file() or not str(image_path).startswith(str(images_dir)):
				raise HTTPException(status_code=404, detail="Image not found")
			return FileResponse(str(image_path))
		finally:
			session.close()

	@staticmethod
	def handle_get_task_zip(task_id: str) -> Response:
		"""
		Packages result Markdown and images into a zip archive for download.
		:param task_id: Primary key string.
		:return: Response containing zip archive bytes.
		"""
		session = postgres_init.SessionLocal()
		try:
			entity = ParseTaskRepo.get_by_id(session, task_id)
			if not entity:
				raise HTTPException(status_code=404, detail="Task not found")
			if not entity.output_dir:
				raise HTTPException(status_code=404, detail="Task output directory not found")
			task_dir = Path(entity.output_dir)
			if not task_dir.is_dir():
				raise HTTPException(status_code=404, detail="Task output directory not found on disk")
			zip_buffer = io.BytesIO()
			with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
				result_md = task_dir / "result.md"
				if result_md.is_file():
					zf.write(result_md, arcname="result.md")
				images_dir = task_dir / "images"
				if images_dir.is_dir():
					for img_path in sorted(images_dir.iterdir()):
						if img_path.is_file():
							zf.write(img_path, arcname=f"images/{img_path.name}")
			zip_buffer.seek(0)
			stem = Path(entity.file_name).stem if entity.file_name else task_id
			zip_filename = f"{stem}.zip"
			encoded_filename = quote(zip_filename)
			headers = {
				"Content-Disposition": f"attachment; filename=\"{task_id}.zip\"; filename*=utf-8''{encoded_filename}",
			}
			return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers=headers)
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


parse_service = ParseService()
