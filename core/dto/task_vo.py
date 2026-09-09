"""View objects (VO) for returning task, segment, and system state."""
import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class TaskSegmentVo(BaseModel):
	"""
	Value object representing an individual parsed segment.
	"""
	model_config = ConfigDict(from_attributes=True)

	# Segment unique identifier
	id: str
	# Execution order index
	segment_order: int
	# Slice start page
	start_page: int
	# Slice end page
	end_page: int
	# Processing status
	status: str
	# MinerU API task identifier
	mineru_task_id: Optional[str] = None
	# Generated markdown path
	md_path: Optional[str] = None
	# Creation timestamp
	create_at: datetime.datetime


class ParseTaskVo(BaseModel):
	"""
	Value object for standard task responses.
	"""
	model_config = ConfigDict(from_attributes=True)

	# Unique task identifier
	id: str
	# Document filename
	file_name: str
	# SHA-256 content checksum
	file_hash: str
	# File size in bytes
	file_size: int
	# Total page count
	total_pages: Optional[int] = None
	# Current lifecycle status
	status: str
	# Execution backend
	backend: str
	# Parsing effort
	effort: str
	# Start page index
	start_page_id: int
	# End page index
	end_page_id: int
	# Highest page index successfully parsed
	last_processed_page: Optional[int] = None
	# Whether this task is resumed from a parent
	is_resumed: bool
	# Parent task ID if resumed
	parent_task_id: Optional[str] = None
	# Error diagnostic message
	error_message: Optional[str] = None
	# Creation timestamp
	create_at: datetime.datetime
	# Last update timestamp
	update_at: Optional[datetime.datetime] = None


class ParseTaskDetailVo(ParseTaskVo):
	"""
	Value object containing task details and all associated segments.
	"""
	# Path to final stitched Markdown
	final_md_path: Optional[str] = None
	# List of all completed segments
	segments: List[TaskSegmentVo] = []


class GpuStatusVo(BaseModel):
	"""
	Value object reporting RTX 5090 worker container status.
	"""
	# Docker container name
	container_name: str
	# Lifecycle status: running, exited, not_found, error
	container_status: str
	# Whether GPU is currently powered on and active
	is_gpu_active: bool
	# Remaining seconds before idle auto-sleep
	idle_countdown_seconds: Optional[int] = None
	# Number of active tasks being parsed
	active_tasks_count: int
	# Whether mineru-api inside worker is healthy
	mineru_api_healthy: bool


class IntermediateResultVo(BaseModel):
	"""
	Value object reporting intermediate results for an ongoing or interrupted task.
	"""
	# Task identifier
	task_id: str
	# Task status
	status: str
	# Original document filename
	file_name: str
	# Last completed page index
	last_processed_page: Optional[int] = None
	# Number of successfully processed segments
	completed_segments_count: int
	# Text snippet from earliest available markdown
	available_md_preview: Optional[str] = None
	# List of generated files relative to task directory
	available_files: List[str] = []
