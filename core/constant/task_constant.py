"""Task and system status constants for MinerU-Sentry."""


class TaskStatusConstant:
	"""
	Defines execution lifecycle states for parsing tasks.
	"""
	PENDING: str = "pending"
	WAKING_GPU: str = "waking_gpu"
	PROCESSING: str = "processing"
	COMPLETED: str = "completed"
	FAILED: str = "failed"
	INTERRUPTED: str = "interrupted"


class WorkerStatusConstant:
	"""
	Defines container and health statuses for the GPU worker.
	"""
	RUNNING: str = "running"
	EXITED: str = "exited"
	NOT_FOUND: str = "not_found"
	ERROR: str = "error"


class ParserDefaultConstant:
	"""
	Defines default parser parameter constants.
	"""
	DEFAULT_BACKEND: str = "hybrid-engine"
	DEFAULT_EFFORT: str = "medium"
	DEFAULT_PARSE_METHOD: str = "auto"
	DEFAULT_START_PAGE: int = 0
	DEFAULT_END_PAGE: int = 99999
	DEFAULT_BATCH_PAGES: int = 64
	DEFAULT_TASK_TIMEOUT_SECONDS: int = 3600
	DEFAULT_BATCH_ATTEMPTS: int = 3
