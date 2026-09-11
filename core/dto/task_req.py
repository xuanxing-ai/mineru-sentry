"""Request models for parsing and resume endpoints."""
from typing import Optional
from fastapi import Form, HTTPException, Query
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
	# Force re-parse flag: clean previous records and checkpoints, restart from page 0
	force: bool = Field(default=False, description="Force re-parse and clean previous task records and checkpoints")

	@classmethod
	def as_form(
		cls,
		backend: str = Form("hybrid-engine"),
		effort: str = Form("medium"),
		parse_method: str = Form("auto"),
		formula_enable: bool = Form(True),
		table_enable: bool = Form(True),
		start_page_id: int = Form(0, ge=0),
		end_page_id: int = Form(99999, ge=0),
		force: bool = Form(False),
		s: Optional[int] = Form(None, ge=0),
		query_s: Optional[int] = Query(None, alias="s", ge=0),
		query_start_page_id: Optional[int] = Query(None, alias="start_page_id", ge=0),
		query_force: Optional[bool] = Query(None, alias="force"),
	) -> "ParseTaskSubmitReq":
		"""Bind multipart options and accept s as the short spelling of the resume offset from form or query."""
		resolved_s = s if s is not None else query_s
		resolved_start = start_page_id if start_page_id != 0 else (query_start_page_id if query_start_page_id is not None else 0)
		if resolved_s is not None and resolved_start not in (0, resolved_s):
			raise HTTPException(status_code=422, detail="s and start_page_id disagree")
		effective_start = resolved_s if resolved_s is not None else resolved_start
		if effective_start > end_page_id:
			raise HTTPException(status_code=422, detail="Start page exceeds end page")
		resolved_force = bool(force or query_force)
		return cls(
			backend=backend, effort=effort, parse_method=parse_method,
			formula_enable=formula_enable, table_enable=table_enable,
			start_page_id=effective_start, end_page_id=end_page_id,
			force=resolved_force,
		)


class ParseTaskResumeReq(BaseModel):
	"""
	Request model for explicitly resuming an interrupted task with -s offset.
	"""
	# Target task ID to resume
	task_id: str = Field(description="ID of the interrupted task to resume")
	# Starting page offset
	start_page_id: Optional[int] = Field(default=None, ge=0, description="Expected next page (0-indexed); saved pages cannot be skipped")
