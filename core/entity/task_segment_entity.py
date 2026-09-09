"""Entity definition for TaskSegment representing batch slices and resume steps."""
import datetime
from sqlalchemy import (
	Column,
	DateTime,
	Integer,
	String,
	Text,
)
from core.init.postgres_init import Base


class TaskSegmentEntity(Base):
	"""
	SQLAlchemy ORM Entity for task segment slices (no foreign key constraint as per style guide).
	"""
	__tablename__ = "task_segments"

	# Primary key
	id = Column(String(32), primary_key=True, index=True)

	# Mandatory audit fields
	create_by = Column(String(32), default="", nullable=False)
	create_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
	update_by = Column(String(32), nullable=True)
	update_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

	# Logical relationship to parse_tasks (no foreign key)
	task_id = Column(String(32), nullable=False, index=True)
	segment_order = Column(Integer, default=0, nullable=False)

	# Slice range
	start_page = Column(Integer, nullable=False)
	end_page = Column(Integer, nullable=False)
	status = Column(String(32), default="pending", nullable=False)

	# MinerU API task and directory paths
	mineru_task_id = Column(String(128), nullable=True)
	segment_dir = Column(String(1024), nullable=True)
	md_path = Column(String(1024), nullable=True)
	middle_json_path = Column(String(1024), nullable=True)
	error_message = Column(Text, nullable=True)
