"""Request models for parsing and resume endpoints."""
from typing import Optional
from pydantic import BaseModel, Field


class ParseTaskSubmitReq(BaseModel):
	"""
	Request model for document parsing options submitted via API.
	"""
	# Parser backend: hybrid-engine, pipeline, vlm-engine
	backend: str = Field(default="hybrid-engine", description="Parser backend")
	# Hybrid effort: medium or high
	effort: str = Field(default="medium", description="Hybrid effort: medium or high")
	# Method: auto, txt, or ocr
	parse_method: str = Field(default="auto", description="auto, txt, or ocr")
	# Formula parsing switch
	formula_enable: bool = Field(default=True, description="Enable LaTeX formula extraction")
	# Table parsing switch
	table_enable: bool = Field(default=True, description="Enable HTML table extraction")
	# Page range boundaries
	start_page_id: int = Field(default=0, ge=0, description="Start page (0-indexed)")
	end_page_id: int = Field(default=99999, ge=0, description="End page (0-indexed)")
	# Whether to automatically resume previously interrupted task with identical hash
	auto_resume: bool = Field(default=True, description="Auto-resume previously interrupted task")


class ParseTaskResumeReq(BaseModel):
	"""
	Request model for explicitly resuming an interrupted task with -s offset.
	"""
	# Target task ID to resume
	task_id: str = Field(description="ID of the interrupted task to resume")
	# Starting page offset
	start_page_id: Optional[int] = Field(default=None, description="Starting page offset (0-indexed)")
