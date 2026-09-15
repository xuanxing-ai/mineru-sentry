#!/usr/bin/env python3
"""Batch document parsing test script.

Scans configured directories or files for PDF/Word documents,
sends them to MinerU Sentry parse API via curl, and saves Markdown results
to docs/output/ (overwriting with latest generated results).
"""
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import List, Sequence, Union

# 支持的文件后缀列表
SUPPORTED_EXTENSIONS: List[str] = [".pdf", ".docx", ".doc"]


def collect_target_files(
	input_paths: Sequence[str],
	supported_extensions: Sequence[str] = SUPPORTED_EXTENSIONS,
) -> List[Path]:
	"""Scan directories or files and return deduplicated list of target document paths."""
	collected_files: List[Path] = []
	seen_paths = set()
	normalized_extensions = {ext.lower() for ext in supported_extensions}

	for path_str in input_paths:
		target_path = Path(path_str).expanduser().resolve()
		if not target_path.exists():
			print(f"[WARN] Path does not exist, skipping: {target_path}")
			continue

		if target_path.is_file():
			file_suffix = target_path.suffix.lower()
			if file_suffix in normalized_extensions:
				resolved_str = str(target_path)
				if resolved_str not in seen_paths:
					seen_paths.add(resolved_str)
					collected_files.append(target_path)
			else:
				print(f"[WARN] Unsupported file extension '{file_suffix}', skipping: {target_path}")
		elif target_path.is_dir():
			# Recursively scan directory
			for root, _dirs, files in os.walk(target_path):
				for filename in sorted(files):
					# Skip Mac metadata and temporary office lock files
					if filename.startswith((".", "._", "~$")):
						continue
					file_ext = os.path.splitext(filename)[1].lower()
					if file_ext in normalized_extensions:
						full_file_path = Path(root) / filename
						resolved_file_str = str(full_file_path.resolve())
						if resolved_file_str not in seen_paths:
							seen_paths.add(resolved_file_str)
							collected_files.append(full_file_path)

	return collected_files


def parse_document_via_curl(
	file_path: Path,
	api_url: str,
	output_dir: Path,
	force: bool = False,
	return_images: bool = False,
	timeout_seconds: int = 1800,
) -> bool:
	"""Call parse API via curl command and save markdown response."""
	filename_stem = file_path.stem
	target_md_path = output_dir / f"{filename_stem}.md"
	header_file = output_dir / f".curl_headers_{filename_stem}.txt"

	curl_cmd = [
		"curl",
		"--fail-with-body",
		"-sS",
		"--dump-header",
		str(header_file),
		api_url,
		"-F",
		f"file=@{str(file_path)}",
		"-F",
		f"return_images={'true' if return_images else 'false'}",
	]
	if force:
		curl_cmd.extend(["-F", "force=true"])

	print(f"\n[START] Parsing: {file_path.name} -> {target_md_path.name}")
	start_time = time.time()

	try:
		process = subprocess.run(
			curl_cmd,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			encoding="utf-8",
			errors="replace",
			timeout=timeout_seconds,
		)
	except subprocess.TimeoutExpired:
		print(f"[FAIL] Request timed out after {timeout_seconds}s: {file_path.name}")
		header_file.unlink(missing_ok=True)
		return False
	except Exception as exc:
		print(f"[FAIL] Failed to execute curl: {exc}")
		header_file.unlink(missing_ok=True)
		return False

	duration = time.time() - start_time

	if process.returncode != 0:
		error_output = process.stderr.strip() or process.stdout.strip()
		print(f"[FAIL] Error ({process.returncode}) after {duration:.2f}s: {file_path.name}")
		if error_output:
			print(f"       Details: {error_output[:500]}")
		header_file.unlink(missing_ok=True)
		return False

	# Save markdown content (overwrite with latest)
	markdown_content = process.stdout
	target_md_path.parent.mkdir(parents=True, exist_ok=True)
	target_md_path.write_text(markdown_content, encoding="utf-8")

	content_size = len(markdown_content.encode("utf-8"))
	print(f"[SUCCESS] Completed in {duration:.2f}s, saved {content_size} bytes to {target_md_path}")

	# If return_images is enabled, fetch extracted images using X-Sentry-Task-ID
	if return_images and header_file.is_file():
		task_id = None
		for line in header_file.read_text(encoding="utf-8", errors="ignore").splitlines():
			if line.lower().startswith("x-sentry-task-id:"):
				task_id = line.split(":", 1)[1].strip()
				break
		if task_id:
			base_url = api_url.rsplit("/parse", 1)[0]
			images_api_url = f"{base_url}/tasks/{task_id}/images"
			try:
				import json
				import urllib.request
				req = urllib.request.Request(images_api_url)
				with urllib.request.urlopen(req, timeout=30) as resp:
					img_names = json.loads(resp.read().decode("utf-8"))
				if img_names:
					images_target_dir = output_dir / "images"
					images_target_dir.mkdir(parents=True, exist_ok=True)
					for img_name in img_names:
						img_url = f"{base_url}/tasks/{task_id}/images/{img_name}"
						img_dest = images_target_dir / img_name
						urllib.request.urlretrieve(img_url, str(img_dest))
					print(f"[IMAGES] Downloaded {len(img_names)} images to {images_target_dir}")
			except Exception as exc:
				print(f"[WARN] Failed to download images for task {task_id}: {exc}")

	header_file.unlink(missing_ok=True)
	return True


def run_batch_parse(
	target_paths: Sequence[str],
	api_url: str = "http://localhost:8080/api/v1/parse",
	output_dir: Union[str, Path] = "docs/output",
	force: bool = False,
	return_images: bool = False,
	timeout_seconds: int = 1800,
) -> None:
	"""Execute batch scanning, API calls, and result persistence."""
	resolved_output_dir = Path(output_dir).expanduser().resolve()
	resolved_output_dir.mkdir(parents=True, exist_ok=True)

	# 若 TARGET_PATHS 为空，则尝试读取命令行传参，方便临时执行
	effective_paths = list(target_paths) if target_paths else sys.argv[1:]

	if not effective_paths:
		print("[INFO] TARGET_PATHS 数组为空。请直接在 tests/test_batch_parse.py 的 TARGET_PATHS 数组中添加待扫描的目录或文件，例如：")
		print("       TARGET_PATHS = [")
		print('           "/path/to/documents_dir",')
		print('           "/path/to/sample.pdf",')
		print("       ]")
		sys.exit(0)

	target_files = collect_target_files(effective_paths, SUPPORTED_EXTENSIONS)

	if not target_files:
		print(f"[INFO] 未在指定路径中找到任何匹配的文件（支持格式: {SUPPORTED_EXTENSIONS}）。")
		sys.exit(0)

	print(f"=== 共扫描到 {len(target_files)} 个待解析文件 ===")
	for idx, doc_path in enumerate(target_files, start=1):
		print(f"  [{idx}] {doc_path}")
	print(f"接口地址 : {api_url}")
	print(f"输出目录 : {resolved_output_dir}")
	print(f"提取图片 : {return_images}")
	print("=" * 50)

	success_count = 0
	failed_count = 0

	for doc_file in target_files:
		ok = parse_document_via_curl(
			file_path=doc_file,
			api_url=api_url,
			output_dir=resolved_output_dir,
			force=force,
			return_images=return_images,
			timeout_seconds=timeout_seconds,
		)
		if ok:
			success_count += 1
		else:
			failed_count += 1

	print("\n" + "=" * 50)
	print(f"批量处理完成: 总数={len(target_files)}, 成功={success_count}, 失败={failed_count}")
	print("=" * 50)

	if failed_count > 0:
		sys.exit(1)


if __name__ == "__main__":

	# 接口地址配置
	# see@SERVICE_PORT
	API_URL: str = "http://localhost:8080/api/v1/parse"

	# 待测试的目录或文件列表（数组形式，支持配置多个目录或具体文件路径）
	TARGET_PATHS: List[str] = [
		# 可以在此数组中直接添加需要测试的目录或文件路径，例如：

		# "docs",
		# "/path/to/document.pdf",
		# "/path/to/document.docx",
	]



	# 是否强制全量重新解析（默认 False，不清理旧任务与分片缓存）
	FORCE: bool = False

	# 是否提取并保存图片（默认 False，设为 True 时请求提取图片并下载到 docs/output/images）
	RETURN_IMAGES: bool = False

	# 请求超时时间（秒）
	TIMEOUT_SECONDS: int = 1800

	# 结果输出目录（自动在 docs/output 下生成同名.md，已在 .gitignore 中忽略）
	OUTPUT_DIR: str = str(Path(__file__).resolve().parent.parent / "docs" / "output")

	run_batch_parse(
		target_paths=TARGET_PATHS,
		api_url=API_URL,
		output_dir=OUTPUT_DIR,
		force=FORCE,
		return_images=RETURN_IMAGES,
		timeout_seconds=TIMEOUT_SECONDS,
	)

