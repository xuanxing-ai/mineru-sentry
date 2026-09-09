"""Entity definition for ParseTask representing document processing metadata and lifecycle state."""
import datetime
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	DateTime,
	Integer,
	String,
	Text,
)
from core.init.postgres_init import Base


class ParseTaskEntity(Base):
	"""
	SQLAlchemy ORM Entity for document parsing tasks.
	"""
	__tablename__ = "parse_tasks"

	# Primary key
	id = Column(String(32), primary_key=True, index=True)

	# Mandatory audit fields
	create_by = Column(String(32), default="", nullable=False)
	create_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
	update_by = Column(String(32), nullable=True)
	update_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

	# File identification fields
	file_name = Column(String(255), nullable=False)
	file_hash = Column(String(64), nullable=False, index=True)
	file_path = Column(String(1024), nullable=False)
	file_size = Column(BigInteger, default=0, nullable=False)
	total_pages = Column(Integer, nullable=True)

	# Parsing execution configuration
	status = Column(String(32), default="pending", nullable=False, index=True)
	backend = Column(String(64), default="hybrid-engine", nullable=False)
	effort = Column(String(32), default="medium", nullable=False)
	parse_method = Column(String(32), default="auto", nullable=False)
	formula_enable = Column(Boolean, default=True, nullable=False)
	table_enable = Column(Boolean, default=True, nullable=False)

	# Page range boundaries
	start_page_id = Column(Integer, default=0, nullable=False)
	end_page_id = Column(Integer, default=99999, nullable=False)
	last_processed_page = Column(Integer, nullable=True)

	# Output paths and diagnostics
	output_dir = Column(String(1024), nullable=False)
	final_md_path = Column(String(1024), nullable=True)
	error_message = Column(Text, nullable=True)

	# Resume tracking
	is_resumed = Column(Boolean, default=False, nullable=False)
	parent_task_id = Column(String(32), nullable=True)
