#!/usr/bin/env python3
"""Batch document parsing test script.

Scans configured directories or files for PDF/Word documents,
sends them to MinerU Sentry parse API via requests, and saves Markdown results
to docs/output/ (overwriting with latest generated results).
"""
import os
from pathlib import Path
import sys
import time
from typing import List, Sequence, Union

import requests

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
		target_md_path = resolved_output_dir / f"{doc_file.stem}.md"
		print(f"\n[START] Parsing: {doc_file.name} -> {target_md_path.name}")
		start_time = time.time()

		form_data = {
			"force": "true" if force else "false",
			"return_images": "true" if return_images else "false",
		}

		try:
			with open(doc_file, "rb") as fp:
				files_payload = {"file": (doc_file.name, fp, "application/octet-stream")}
				resp = requests.post(
					api_url,
					files=files_payload,
					data=form_data,
					timeout=timeout_seconds,
				)
		except requests.exceptions.Timeout:
			print(f"[FAIL] Request timed out after {timeout_seconds}s: {doc_file.name}")
			failed_count += 1
			continue
		except Exception as exc:
			print(f"[FAIL] Failed to send request: {exc}")
			failed_count += 1
			continue

		duration = time.time() - start_time

		if resp.status_code != 200:
			print(f"[FAIL] Error ({resp.status_code}) after {duration:.2f}s: {doc_file.name}")
			error_details = resp.text.strip()
			if error_details:
				print(f"       Details: {error_details[:500]}")
			failed_count += 1
			continue

		markdown_content = resp.text
		target_md_path.parent.mkdir(parents=True, exist_ok=True)
		target_md_path.write_text(markdown_content, encoding="utf-8")

		content_size = len(markdown_content.encode("utf-8"))
		print(f"[SUCCESS] Completed in {duration:.2f}s, saved {content_size} bytes to {target_md_path}")
		success_count += 1

		# 若开启图片提取，通过 X-Sentry-Task-ID 下载提取的图片
		if return_images:
			task_id = resp.headers.get("X-Sentry-Task-ID")
			if task_id:
				base_url = api_url.rsplit("/parse", 1)[0]
				images_api_url = f"{base_url}/tasks/{task_id}/images"
				try:
					images_resp = requests.get(images_api_url, timeout=30)
					if images_resp.status_code == 200:
						img_names = images_resp.json()
						if img_names:
							images_target_dir = resolved_output_dir / "images"
							images_target_dir.mkdir(parents=True, exist_ok=True)
							for img_name in img_names:
								img_url = f"{base_url}/tasks/{task_id}/images/{img_name}"
								img_data_resp = requests.get(img_url, timeout=60)
								if img_data_resp.status_code == 200:
									(images_target_dir / img_name).write_bytes(img_data_resp.content)
							print(f"[IMAGES] Downloaded {len(img_names)} images to {images_target_dir}")
				except Exception as exc:
					print(f"[WARN] Failed to download images for task {task_id}: {exc}")

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
