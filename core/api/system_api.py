"""API router for system health and RTX 5090 GPU worker lifecycle control."""
from fastapi import APIRouter, HTTPException, Query
from core.dto.task_vo import GpuStatusVo
from core.service.docker_service import docker_service

router = APIRouter(tags=["System & GPU Control"])


@router.get("/health", response_model=GpuStatusVo, summary="Gateway health check and GPU status")
def health_check() -> GpuStatusVo:
	"""
	Checks gateway status and returns GPU worker state.
	:return: GpuStatusVo object.
	"""
	return docker_service.get_worker_status_vo()


@router.get("/api/v1/system/gpu/status", response_model=GpuStatusVo, summary="Get RTX 5090 Worker Status")
def get_gpu_status() -> GpuStatusVo:
	"""
	Retrieves current container and GPU scheduler status.
	:return: GpuStatusVo object.
	"""
	return docker_service.get_worker_status_vo()


@router.post("/api/v1/system/gpu/wake", response_model=GpuStatusVo, summary="Manually wake GPU worker")
def wake_gpu() -> GpuStatusVo:
	"""
	Wakes up the GPU worker container on RTX 5090.
	:return: GpuStatusVo object.
	"""
	is_success = docker_service.wake_worker()
	if not is_success:
		raise HTTPException(status_code=500, detail="Failed to wake GPU worker container.")
	return docker_service.get_worker_status_vo()


@router.post("/api/v1/system/gpu/sleep", response_model=GpuStatusVo, summary="Manually sleep GPU worker")
def sleep_gpu(force: bool = Query(default=False, description="Force sleep even if tasks are active")) -> GpuStatusVo:
	"""
	Stops the GPU worker container immediately, releasing RTX 5090 VRAM.
	:param force: Force stop boolean flag.
	:return: GpuStatusVo object.
	"""
	is_success = docker_service.sleep_worker(force=force)
	if not is_success:
		raise HTTPException(
			status_code=400,
			detail="Cannot sleep GPU: active tasks are currently running. Pass force=true to override.",
		)
	return docker_service.get_worker_status_vo()
