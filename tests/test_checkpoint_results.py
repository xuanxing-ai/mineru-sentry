"""Exercise result replay and crash recovery with real PostgreSQL and disk checkpoints.

Run only against a disposable database:
SENTRY_TEST_DATABASE_URL=postgresql+psycopg2://... python -m unittest discover -s tests -v
No MinerU inference or Docker lifecycle is simulated by this suite.
"""
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
import uuid

TEST_DATABASE_URL = os.getenv("SENTRY_TEST_DATABASE_URL")
if TEST_DATABASE_URL:
	os.environ["POSTGRES_URL"] = TEST_DATABASE_URL
	os.environ["CONFIG_FILE_PATH"] = "/tmp/mineru-sentry-test-no-env"
	_test_storage = tempfile.TemporaryDirectory(prefix="mineru-sentry-checkpoints-")
	os.environ["SHARED_DATA_DIR"] = _test_storage.name
	os.environ["LOG_PATH"] = str(Path(_test_storage.name) / "logs")
	from fastapi.testclient import TestClient
	from pypdf import PdfWriter
	from main import app
	from core.entity.parse_task_entity import ParseTaskEntity
	from core.entity.task_segment_entity import TaskSegmentEntity
	from core.init import postgres_init
	from core.repo.parse_task_repo import ParseTaskRepo
	from core.repo.task_segment_repo import TaskSegmentRepo
	from core.service.parse_service import parse_service
	from core.service.stitcher_service import stitcher_service
	from core.service.task_executor_service import TaskExecutorService, task_executor_service


@unittest.skipUnless(TEST_DATABASE_URL, "Set SENTRY_TEST_DATABASE_URL to a disposable PostgreSQL database")
class CheckpointResultTest(unittest.TestCase):
	"""Use actual records and files to verify the public result contract without a GPU."""

	def setUp(self):
		"""Create a two-page PDF and an interrupted task owned by this test."""
		self.task_id = uuid.uuid4().hex
		self.filename = f"{self.task_id}.pdf"
		writer = PdfWriter()
		writer.add_blank_page(width=100, height=100)
		writer.add_blank_page(width=100, height=100)
		buffer = io.BytesIO()
		writer.write(buffer)
		self.pdf = buffer.getvalue()
		self.output_dir = Path(_test_storage.name) / "tasks" / self.task_id
		self.output_dir.mkdir(parents=True)
		self.source_path = self.output_dir / self.filename
		self.source_path.write_bytes(self.pdf)
		session = postgres_init.SessionLocal()
		try:
			task = ParseTaskEntity(
				id=self.task_id, file_name=self.filename, file_hash=hashlib.sha256(self.pdf).hexdigest(),
				file_path=str(self.source_path), file_size=len(self.pdf), total_pages=2,
				status="failed", backend="hybrid-engine", effort="medium", parse_method="auto",
				formula_enable=True, table_enable=True, start_page_id=0, end_page_id=1,
				output_dir=str(self.output_dir), error_message="Previous process stopped",
			)
			ParseTaskRepo.add(session, task)
		finally:
			session.close()
		self.client = TestClient(app)

	def tearDown(self):
		"""Delete only this test's records after any background finalization has ended."""
		import time
		deadline = time.monotonic() + 5
		while task_executor_service.is_running(self.task_id) and time.monotonic() < deadline:
			time.sleep(0.01)
		self.assertFalse(task_executor_service.is_running(self.task_id))
		session = postgres_init.SessionLocal()
		try:
			segments = TaskSegmentRepo.list_by_task_id(session, self.task_id)
			for segment in segments:
				TaskSegmentRepo.delete(session, segment.id)
			ParseTaskRepo.delete(session, self.task_id)
		finally:
			session.close()
		self.client.close()

	def save_batch(self, start, end, text, status="completed"):
		"""Publish a real text checkpoint and optionally leave its database commit incomplete."""
		path = self.output_dir / "checkpoints" / f"{start}_{end}.md"
		stitcher_service.write_checkpoint(path, text)
		session = postgres_init.SessionLocal()
		try:
			segment = TaskSegmentEntity(
				id=uuid.uuid4().hex, task_id=self.task_id, segment_order=start,
				start_page=start, end_page=end, status=status, segment_dir=str(path.parent), md_path=str(path),
			)
			TaskSegmentRepo.add(session, segment)
		finally:
			session.close()
		return path

	def mark_complete(self, text):
		"""Persist a complete result for cache-hit requests."""
		path = self.output_dir / "result.md"
		stitcher_service.write_checkpoint(path, text)
		session = postgres_init.SessionLocal()
		try:
			task = ParseTaskRepo.get_by_id(session, self.task_id)
			task.status = "completed"
			task.final_md_path = str(path)
			task.last_processed_page = 1
			ParseTaskRepo.update(session, task)
		finally:
			session.close()

	def test_completed_upload_returns_text_without_download(self):
		"""A repeated completed upload returns its exact body and the same task identity."""
		self.mark_complete("# 已完成\n\n正文 Ω\n")
		response = self.client.post("/api/v1/parse", files={"file": (self.filename, self.pdf)})
		self.assertEqual(response.status_code, 200, response.text)
		self.assertEqual(response.text, "# 已完成\n\n正文 Ω\n")
		self.assertEqual(response.headers["x-sentry-task-id"], self.task_id)
		self.assertTrue(response.headers["content-type"].startswith("text/markdown"))
		self.assertNotIn("content-disposition", response.headers)
		self.assertFalse(task_executor_service.is_running(self.task_id))

	def test_cached_stream_and_filename_result(self):
		"""Streaming and filename-only requests return the same complete text."""
		self.mark_complete("Already parsed\n")
		response = self.client.post("/api/v1/parse/stream", files={"file": (self.filename, self.pdf)})
		self.assertEqual(response.text, "Already parsed\n")
		response = self.client.post(f"/api/v1/parse/by-filename/{self.filename}")
		self.assertEqual(response.text, "Already parsed\n")

	def test_recover_disk_write_before_database_commit(self):
		"""Re-upload restores the last atomic batch and finalizes without another inference run."""
		self.save_batch(0, 0, "第一页\n\n")
		self.save_batch(1, 1, "Second page\n\n", status="processing")
		response = self.client.post("/api/v1/parse", files={"file": (self.filename, self.pdf)}, data={"s": "1"})
		self.assertEqual(response.status_code, 200, response.text)
		self.assertEqual(response.text, "第一页\n\nSecond page\n\n")
		detail = self.client.get(f"/api/v1/tasks/{self.task_id}").json()
		self.assertEqual(detail["last_processed_page"], 1)
		self.assertEqual(detail["status"], "completed")
		self.assertEqual(len(detail["segments"]), 2)

	def test_recover_orphan_checkpoint_and_ignore_temporary_file(self):
		"""Recovery imports complete named files and ignores unfinished atomic-write files."""
		checkpoint = self.output_dir / "checkpoints" / "0_0.md"
		stitcher_service.write_checkpoint(checkpoint, "Saved page\n\n")
		(checkpoint.parent / ".1_1.md.partial.tmp").write_text("unfinished", encoding="utf-8")
		session = postgres_init.SessionLocal()
		try:
			task = ParseTaskRepo.get_by_id(session, self.task_id)
			executor = TaskExecutorService()
			segments = executor.restore_checkpoint(session, task)
			self.assertEqual(len(segments), 1)
			self.assertEqual(task.last_processed_page, 0)
		finally:
			session.close()

	def test_page_210_resume_returns_the_entire_prefix_and_remainder(self):
		"""The s=209 case retains pages 0-208 when recovering the final saved page."""
		writer = PdfWriter()
		for _ in range(210):
			writer.add_blank_page(width=100, height=100)
		buffer = io.BytesIO()
		writer.write(buffer)
		self.pdf = buffer.getvalue()
		self.source_path.write_bytes(self.pdf)
		session = postgres_init.SessionLocal()
		try:
			task = ParseTaskRepo.get_by_id(session, self.task_id)
			task.file_hash = hashlib.sha256(self.pdf).hexdigest()
			task.file_size = len(self.pdf)
			task.total_pages = 210
			task.end_page_id = 209
			ParseTaskRepo.update(session, task)
		finally:
			session.close()
		prefix = "".join(f"Page {page + 1}\n\n" for page in range(209))
		self.save_batch(0, 208, prefix)
		self.save_batch(209, 209, "Page 210\n\n", status="processing")
		response = self.client.post("/api/v1/parse?s=209", files={"file": (self.filename, self.pdf)})
		self.assertEqual(response.status_code, 200, response.text)
		self.assertEqual(response.text, prefix + "Page 210\n\n")

	def test_explicit_offset_cannot_skip_missing_prefix(self):
		"""A resume hint cannot turn missing earlier pages into a successful result."""
		response = self.client.post("/api/v1/parse", files={"file": (self.filename, self.pdf)}, data={"s": "1"})
		self.assertEqual(response.status_code, 409)
		self.assertIn("before 0", response.text)

	def test_new_upload_cannot_start_without_saved_prefix(self):
		"""The first request cannot claim that prior pages have already been saved."""
		response = self.client.post("/api/v1/parse", files={"file": (f"new-{self.filename}", self.pdf)}, data={"s": "1"})
		self.assertEqual(response.status_code, 409)
		self.assertIn("No saved prefix", response.text)

	def test_same_name_changed_content_is_rejected(self):
		"""A same-name revision must not receive a stale result from another document."""
		self.mark_complete("Old result")
		response = self.client.post("/api/v1/parse", files={"file": (self.filename, self.pdf + b"\n%revision")})
		self.assertEqual(response.status_code, 409)
		self.assertIn("different content", response.text)

	def test_changed_options_and_range_are_rejected(self):
		"""Cached text is not reused under incompatible parsing options or page ranges."""
		self.mark_complete("Old result")
		for options in ({"effort": "high"}, {"end_page_id": "0"}):
			response = self.client.post("/api/v1/parse", files={"file": (self.filename, self.pdf)}, data=options)
			self.assertEqual(response.status_code, 409)

	def test_intermediate_body_and_failed_stream(self):
		"""Saved text is available after failure, but a failed stream cannot end as complete."""
		self.save_batch(0, 0, "Saved prefix\n\n")
		response = self.client.get(f"/api/v1/tasks/{self.task_id}/intermediate")
		self.assertEqual(response.text, "Saved prefix\n\n")
		chunks = parse_service.iter_result(self.task_id)
		self.assertEqual(next(chunks), "Saved prefix\n\n")
		with self.assertRaisesRegex(RuntimeError, "interrupted"):
			next(chunks)

	def test_missing_checkpoint_cannot_be_silently_skipped(self):
		"""A completed record with lost text blocks finalization instead of dropping its pages."""
		path = self.save_batch(0, 0, "Saved prefix\n\n")
		path.unlink()
		response = self.client.post("/api/v1/parse", files={"file": (self.filename, self.pdf)})
		self.assertEqual(response.status_code, 409)
		self.assertIn("missing", response.text)

	def test_openapi_includes_both_result_modes(self):
		"""The running router publishes the direct and streamed result endpoints."""
		response = self.client.get("/openapi.json")
		self.assertEqual(response.status_code, 200)
		paths = response.json()["paths"]
		self.assertIn("/api/v1/parse/stream", paths)
		self.assertIn("/api/v1/parse/by-filename/{filename}", paths)


if __name__ == "__main__":
	unittest.main()
