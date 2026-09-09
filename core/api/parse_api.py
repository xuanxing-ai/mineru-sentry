"""API router for document parsing and task retrieval (sync functions, no business implementation in router)."""
from pathlib import Path
from typing import Annotated, List
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from core.dto.task_req import ParseTaskResumeReq, ParseTaskSubmitReq
from core.dto.task_vo import (
	IntermediateResultVo,
	ParseTaskDetailVo,
	ParseTaskVo,
)
from core.service.parse_service import parse_service

router = APIRouter(prefix="/api/v1", tags=["Document Parsing"])


@router.post("/parse", response_model=ParseTaskVo, summary="Submit document for parsing")
def submit_parse(
	file: Annotated[UploadFile, File(description="Target document file")],
	backend: Annotated[str, Form(description="Parser backend")] = "hybrid-engine",
	effort: Annotated[str, Form(description="Hybrid effort")] = "medium",
	parse_method: Annotated[str, Form(description="auto, txt, or ocr")] = "auto",
	formula_enable: Annotated[bool, Form(description="Formula parsing")] = True,
	table_enable: Annotated[bool, Form(description="Table parsing")] = True,
	start_page_id: Annotated[int, Form(description="Start page (0-indexed)")] = 0,
	end_page_id: Annotated[int, Form(description="End page (0-indexed)")] = 99999,
	auto_resume: Annotated[bool, Form(description="Auto-resume previously interrupted tasks")] = True,
) -> ParseTaskVo:
	"""
	Receives upload request, constructs ParseTaskSubmitReq, and delegates to parse_service.
	:param file: UploadFile stream.
	:param backend: Backend parameter string.
	:param effort: Effort level string.
	:param parse_method: Parse method string.
	:param formula_enable: Formula flag boolean.
	:param table_enable: Table flag boolean.
	:param start_page_id: Start page int.
	:param end_page_id: End page int.
	:param auto_resume: Auto-resume flag boolean.
	:return: ParseTaskVo containing task status.
	"""
	file_bytes = file.file.read()
	raw_name = file.filename if file.filename else "document.pdf"

	req_obj = ParseTaskSubmitReq(
		backend=backend,
		effort=effort,
		parse_method=parse_method,
		formula_enable=formula_enable,
		table_enable=table_enable,
		start_page_id=start_page_id,
		end_page_id=end_page_id,
		auto_resume=auto_resume,
	)
	return parse_service.handle_submit_parse(file_bytes, raw_name, req_obj)


@router.post("/parse/resume", response_model=ParseTaskVo, summary="Resume an interrupted task with -s offset")
def resume_parse(req: ParseTaskResumeReq) -> ParseTaskVo:
	"""
	Delegates task resume request to parse_service.
	:param req: ParseTaskResumeReq object.
	:return: ParseTaskVo object.
	"""
	validated_req = ParseTaskResumeReq.model_validate(req.model_dump())
	return parse_service.handle_resume_parse(validated_req)


@router.get("/tasks/{task_id}", response_model=ParseTaskDetailVo, summary="Get task details and segments")
def get_task(task_id: str) -> ParseTaskDetailVo:
	"""
	Delegates task retrieval to parse_service.
	:param task_id: Unique task identifier string.
	:return: ParseTaskDetailVo instance.
	"""
	return parse_service.handle_get_task(task_id)


@router.get("/tasks/{task_id}/result", summary="Download final unified Markdown file")
def download_result(task_id: str) -> FileResponse:
	"""
	Delegates result file download to parse_service.
	:param task_id: Unique task identifier string.
	:return: FileResponse streaming the markdown file.
	"""
	result_path = parse_service.handle_get_result_path(task_id)
	return FileResponse(path=str(result_path), media_type="text/markdown", filename=result_path.name)


@router.get("/tasks/{task_id}/intermediate", response_model=IntermediateResultVo, summary="Get intermediate results")
def get_intermediate_results(task_id: str) -> IntermediateResultVo:
	"""
	Delegates intermediate results retrieval to parse_service.
	:param task_id: Unique task identifier string.
	:return: IntermediateResultVo instance.
	"""
	return parse_service.handle_get_intermediate(task_id)


@router.get("/tasks/by-filename/{filename}", response_model=List[ParseTaskVo], summary="Find tasks by filename")
def find_tasks_by_filename(filename: str) -> List[ParseTaskVo]:
	"""
	Delegates query by filename to parse_service.
	:param filename: Filename string.
	:return: List of ParseTaskVo.
	"""
	return parse_service.handle_list_by_filename(filename)


@router.get("/tasks/by-hash/{file_hash}", response_model=List[ParseTaskVo], summary="Find tasks by SHA-256 hash")
def find_tasks_by_hash(file_hash: str) -> List[ParseTaskVo]:
	"""
	Delegates query by file hash to parse_service.
	:param file_hash: SHA-256 hash string.
	:return: List of ParseTaskVo.
	"""
	return parse_service.handle_list_by_hash(file_hash)
