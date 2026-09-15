"""Independent native extraction endpoints, available without a task database."""
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from core.service.fidelity_service import fidelity_service

router = APIRouter(prefix="/api/v1/parse/faithful", tags=["Faithful Extraction"])


@router.post("", response_class=PlainTextResponse, summary="Extract original text and retain page evidence")
def parse_faithful(file: Annotated[UploadFile, File()], ocr: Annotated[bool, Form()] = True):
	"""Return Markdown with an artifact ID for downloading images and the coverage report."""
	return fidelity_service.handle_parse(file, ocr)


@router.get("/{artifact_id}/zip", response_class=FileResponse, summary="Download Markdown, images and coverage report")
def get_faithful_artifact(artifact_id: str):
	"""Download all assets referenced by one completed independent extraction."""
	return fidelity_service.handle_artifact(artifact_id)
