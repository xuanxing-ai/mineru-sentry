"""HTTP routes for resumable document parsing and direct Markdown results."""
from typing import Annotated, List
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse

from core.dto.task_req import ParseTaskResumeReq, ParseTaskSubmitReq
from core.dto.task_vo import ParseTaskDetailVo, ParseTaskVo
from core.service.parse_service import parse_service

router = APIRouter(prefix="/api/v1", tags=["Document Parsing"])


@router.post("/parse", response_class=PlainTextResponse, summary="Upload, resume or reuse a document and return complete Markdown")
def submit_parse(
	file: Annotated[UploadFile, File(description="Same filename and content reconnect to the saved task")],
	req: Annotated[ParseTaskSubmitReq, Depends(ParseTaskSubmitReq.as_form)],
):
	"""Return the complete parsing result in the response body."""
	upload_file = file
	submit_req = req
	response = parse_service.handle_submit_parse(upload_file, submit_req)
	return response


@router.post("/parse/stream", response_class=StreamingResponse, summary="Replay saved Markdown and stream newly completed batches")
def stream_parse(
	file: Annotated[UploadFile, File(description="Document to parse or reconnect")],
	req: Annotated[ParseTaskSubmitReq, Depends(ParseTaskSubmitReq.as_form)],
):
	"""Stream the full document from its saved prefix through completion."""
	upload_file = file
	submit_req = req
	response = parse_service.handle_submit_parse(upload_file, submit_req, stream=True)
	return response


@router.post("/parse/resume", response_class=PlainTextResponse, summary="Resume a saved task and return complete Markdown")
def resume_parse(req: ParseTaskResumeReq):
	"""Use a task ID instead of uploading the same document again."""
	resume_req = req
	response = parse_service.handle_resume_parse(resume_req)
	return response


@router.get("/tasks/{task_id}", response_model=ParseTaskDetailVo, summary="Get task details and checkpoints")
def get_task(task_id: str) -> ParseTaskDetailVo:
	"""Return diagnostic task status without triggering execution."""
	target_id = task_id
	detail_vo = parse_service.handle_get_task(target_id)
	return detail_vo


@router.get("/tasks/{task_id}/result", response_class=PlainTextResponse, summary="Return completed Markdown text")
def get_result(task_id: str):
	"""Return the result body, without a file download response."""
	target_id = task_id
	response = parse_service.handle_get_result(target_id)
	return response


@router.get("/tasks/{task_id}/intermediate", response_class=PlainTextResponse, summary="Return saved Markdown text so far")
def get_intermediate_results(task_id: str):
	"""Return the durable partial result without file listings or paths."""
	target_id = task_id
	response = parse_service.handle_get_intermediate(target_id)
	return response


@router.get("/tasks/{task_id}/images", response_model=List[str], summary="List extracted image filenames for a task")
def list_task_images(task_id: str) -> List[str]:
	"""Return the list of image filenames associated with the task."""
	target_id = task_id
	images_list = parse_service.handle_list_task_images(target_id)
	return images_list


@router.get("/tasks/{task_id}/images/{filename}", summary="Get an extracted image by filename")
def get_task_image(task_id: str, filename: str):
	"""Return the binary image content directly."""
	target_id = task_id
	target_filename = filename
	response = parse_service.handle_get_task_image(target_id, target_filename)
	return response


@router.get("/tasks/{task_id}/zip", summary="Download Markdown and extracted images as a ZIP archive")
def get_task_zip(task_id: str):
	"""Package result.md and images directory into a downloadable ZIP archive."""
	target_id = task_id
	response = parse_service.handle_get_task_zip(target_id)
	return response


@router.post("/parse/by-filename/{filename}", response_class=PlainTextResponse, summary="Resume or return a saved document by filename")
def get_filename_result(filename: str):
	"""Resolve a saved filename and return its complete parsing result."""
	target_name = filename
	response = parse_service.handle_filename_result(target_name)
	return response


@router.get("/tasks/by-filename/{filename}", response_model=List[ParseTaskVo], summary="Find task records by filename")
def find_tasks_by_filename(filename: str) -> List[ParseTaskVo]:
	"""Return diagnostic records matching an exact filename."""
	target_name = filename
	records = parse_service.handle_list_by_filename(target_name)
	return records


@router.get("/tasks/by-hash/{file_hash}", response_model=List[ParseTaskVo], summary="Find task records by SHA-256")
def find_tasks_by_hash(file_hash: str) -> List[ParseTaskVo]:
	"""Return diagnostic records matching a content hash."""
	target_hash = file_hash
	records = parse_service.handle_list_by_hash(target_hash)
	return records
