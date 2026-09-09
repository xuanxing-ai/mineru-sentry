"""Durable checkpoint writes and ordered Markdown assembly."""
import os
from pathlib import Path
from typing import List
import uuid


class StitcherService:
	"""Publish complete text atomically so readers never consume a partial checkpoint."""

	@staticmethod
	def write_checkpoint(output_path: Path, content: str) -> None:
		"""Flush a complete batch before atomically publishing its checkpoint path."""
		output_path.parent.mkdir(parents=True, exist_ok=True)
		temporary_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
		try:
			with temporary_path.open("w", encoding="utf-8") as output:
				output.write(content)
				output.flush()
				os.fsync(output.fileno())
			os.replace(temporary_path, output_path)
			directory_fd = os.open(output_path.parent, os.O_RDONLY)
			try:
				os.fsync(directory_fd)
			finally:
				os.close(directory_fd)
		finally:
			temporary_path.unlink(missing_ok=True)

	@staticmethod
	def stitch_segments(markdown_paths: List[Path], output_path: Path) -> None:
		"""Concatenate committed batches without loading the whole document into memory."""
		output_path.parent.mkdir(parents=True, exist_ok=True)
		temporary_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
		try:
			with temporary_path.open("wb") as output:
				for markdown_path in markdown_paths:
					with markdown_path.open("rb") as source:
						while chunk := source.read(65536):
							output.write(chunk)
				output.flush()
				os.fsync(output.fileno())
			os.replace(temporary_path, output_path)
			directory_fd = os.open(output_path.parent, os.O_RDONLY)
			try:
				os.fsync(directory_fd)
			finally:
				os.close(directory_fd)
		finally:
			temporary_path.unlink(missing_ok=True)


stitcher_service = StitcherService()
