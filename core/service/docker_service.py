"""Docker service for managing RTX 5090 worker container lifecycle without async/await."""
import threading
import time
from typing import Optional
import docker
from docker.errors import DockerException, NotFound
import logging
import requests

from core.config import settings
from core.constant.task_constant import WorkerStatusConstant
from core.dto.task_vo import GpuStatusVo


class DockerService:
	"""
	Synchronous Docker management service governing the lifecycle of the GPU worker.
	"""

	def __init__(self) -> None:
		raw_name = settings.MINERU_WORKER_CONTAINER_NAME
		self.container_name: str = raw_name if raw_name else "mineru_gpu_worker"

		raw_timeout = settings.IDLE_TIMEOUT_SECONDS
		self.idle_timeout_seconds: int = int(raw_timeout) if raw_timeout else 900

		raw_url = settings.MINERU_API_URL
		self.worker_api_url: str = raw_url if raw_url else "http://mineru_worker:8000"

		raw_startup_timeout = settings.DEFAULT_MINERU_LOCAL_API_STARTUP_TIMEOUT_SECONDS
		self.worker_startup_timeout_seconds: int = int(raw_startup_timeout) if raw_startup_timeout else 300

		self._client: Optional[docker.DockerClient] = None
		self._lock = threading.Lock()
		self._active_task_count: int = 0
		self._last_activity_time: float = time.time()
		self._is_monitoring: bool = False
		self._monitor_thread: Optional[threading.Thread] = None

	def _get_docker_client(self) -> docker.DockerClient:
		"""
		Retrieves or initializes the Docker SDK client.
		:return: Initialized DockerClient.
		"""
		if self._client is None:
			try:
				self._client = docker.from_env()
			except DockerException as exc:
				logging.error(f"Failed to initialize Docker client: {exc}")
				raise
		return self._client

	def _get_worker_container(self):
		"""
		Fetches the GPU worker container object by name.
		:return: Container object or None.
		"""
		client = self._get_docker_client()
		target_name = self.container_name
		try:
			return client.containers.get(target_name)
		except NotFound:
			logging.error(f"Container '{target_name}' not found on host.")
			return None
		except Exception as exc:
			logging.error(f"Error accessing container '{target_name}': {exc}")
			return None

	def start_idle_monitor(self) -> None:
		"""
		Launches the background daemon thread to monitor container idle time.
		"""
		with self._lock:
			if not self._is_monitoring:
				self._is_monitoring = True
				self._monitor_thread = threading.Thread(target=self._idle_monitor_loop, daemon=True)
				self._monitor_thread.start()
				logging.info("DockerService idle monitor thread started.")

	def stop_idle_monitor(self) -> None:
		"""
		Stops the background idle monitor thread.
		"""
		with self._lock:
			self._is_monitoring = False

	def _idle_monitor_loop(self) -> None:
		"""
		Loop checking idle time every 10 seconds. Stops container when threshold is reached.
		"""
		while self._is_monitoring:
			time.sleep(10)
			with self._lock:
				task_count = self._active_task_count
				if task_count == 0:
					current_time = time.time()
					elapsed = current_time - self._last_activity_time
					threshold = self.idle_timeout_seconds
					if elapsed >= threshold:
						container = self._get_worker_container()
						if container and container.status == WorkerStatusConstant.RUNNING:
							name = self.container_name
							logging.info(
								f"No active tasks for {int(elapsed)}s (threshold: {threshold}s). "
								f"Stopping worker '{name}' to release 5090 VRAM..."
							)
							try:
								container.stop(timeout=10)
								logging.info(f"Container '{name}' stopped. GPU VRAM released.")
							except Exception as exc:
								logging.error(f"Failed to stop container '{name}': {exc}")

	def touch_activity(self) -> None:
		"""
		Resets the idle timer timestamp to current time.
		"""
		self._last_activity_time = time.time()

	def increment_active_tasks(self) -> None:
		"""
		Increments active task counter and updates activity timestamp.
		"""
		with self._lock:
			self._active_task_count += 1
			self.touch_activity()

	def decrement_active_tasks(self) -> None:
		"""
		Decrements active task counter and updates activity timestamp.
		"""
		with self._lock:
			self._active_task_count = max(0, self._active_task_count - 1)
			self.touch_activity()

	def check_api_health(self) -> bool:
		"""
		Checks if mineru-api responds with status 200 OK.
		:return: True if healthy, False otherwise.
		"""
		endpoint = f"{self.worker_api_url}/health"
		try:
			res = requests.get(endpoint, timeout=3.0)
			status_code = res.status_code
			return status_code == 200
		except Exception:
			return False

	def wake_worker(self) -> bool:
		"""
		Wakes the worker container if stopped and blocks until healthy or timeout.
		:return: True if worker is healthy, False on failure.
		"""
		with self._lock:
			self.touch_activity()
			container = self._get_worker_container()
			if not container:
				return False

			container.reload()
			current_status = container.status
			if current_status != WorkerStatusConstant.RUNNING:
				settings.generate_mineru_config()
				name = self.container_name
				logging.info(f"Starting GPU worker '{name}' for RTX 5090...")
				container.start()

			# Poll healthcheck synchronously
			start_ts = time.time()
			timeout = self.worker_startup_timeout_seconds
			while time.time() - start_ts < timeout:
				is_healthy = self.check_api_health()
				if is_healthy:
					logging.info("GPU worker is healthy and ready.")
					return True
				time.sleep(2.0)

			logging.error("GPU worker startup timed out.")
			return False

	def sleep_worker(self, force: bool = False) -> bool:
		"""
		Manually stops the GPU worker container.
		:param force: If True, forces container stop even with active tasks.
		:return: True if stopped successfully, False otherwise.
		"""
		with self._lock:
			active_count = self._active_task_count
			if active_count > 0 and not force:
				logging.warning("Active tasks running; use force=True to stop.")
				return False

			container = self._get_worker_container()
			if not container:
				return False

			container.reload()
			current_status = container.status
			if current_status == WorkerStatusConstant.RUNNING:
				container.stop(timeout=10)
				logging.info("GPU worker manually stopped.")
			return True

	def get_worker_status_vo(self) -> GpuStatusVo:
		"""
		Returns a GpuStatusVo reporting container status and countdown.
		:return: GpuStatusVo instance.
		"""
		container = self._get_worker_container()
		status = WorkerStatusConstant.NOT_FOUND
		is_running = False

		if container:
			try:
				container.reload()
				status = container.status
				is_running = status == WorkerStatusConstant.RUNNING
			except Exception:
				status = WorkerStatusConstant.ERROR

		api_healthy = self.check_api_health() if is_running else False

		countdown = None
		if is_running and self._active_task_count == 0:
			elapsed = time.time() - self._last_activity_time
			countdown = max(0, int(self.idle_timeout_seconds - elapsed))

		status_vo = GpuStatusVo(
			container_name=self.container_name,
			container_status=status,
			is_gpu_active=is_running,
			idle_countdown_seconds=countdown,
			active_tasks_count=self._active_task_count,
			mineru_api_healthy=api_healthy,
		)
		return status_vo


# Global singleton service
docker_service = DockerService()
