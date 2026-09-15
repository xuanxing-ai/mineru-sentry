"""Check native extraction against actual documents supplied outside Git.

Set SENTRY_FIDELITY_TEST_INPUT to a directory containing PDF/DOCX originals.
The suite does not send originals to an external service or simulate OCR responses.
"""
from collections import Counter
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pymupdf

from core.constant.fidelity_constant import FidelityConstant
from core.dto.fidelity_vo import FidelityPartVo
from core.service.fidelity_service import fidelity_service, VisibleTextParser


@unittest.skipUnless(os.getenv("SENTRY_FIDELITY_TEST_INPUT"), "Set SENTRY_FIDELITY_TEST_INPUT to actual original documents")
class FidelityTest(unittest.TestCase):
	"""Compare independent source reads, output text, assets and public HTTP responses."""

	@classmethod
	def setUpClass(cls):
		"""Extract real native documents once into a disposable output directory."""
		cls.storage = tempfile.TemporaryDirectory(prefix="sentry-fidelity-")
		cls.root = Path(cls.storage.name)
		cls.results = []
		cls.scans = []
		for source in sorted(Path(os.environ["SENTRY_FIDELITY_TEST_INPUT"]).rglob("*")):
			if source.suffix.lower() not in (".pdf", ".docx") or not source.is_file():
				continue
			if source.suffix.lower() == ".pdf":
				with pymupdf.open(source) as document:
					if any(not page.get_text().strip() and page.get_images() for page in document):
						cls.scans.append(source)
						continue
			output = cls.root / str(len(cls.results))
			report = fidelity_service.parse_file(source, output, ocr=False)
			cls.results.append((source, output, report))

	@classmethod
	def tearDownClass(cls):
		"""Remove only the disposable extraction artifacts created by this suite."""
		cls.storage.cleanup()

	def test_word_text_sequence_and_tables(self):
		"""All native Word text, including repeated content, survives in original part order."""
		found = False
		for source, output, report in self.results:
			if source.suffix.lower() != ".docx":
				continue
			found = True
			markdown = (output / "result.md").read_text(encoding="utf-8")
			with ZipFile(source) as archive:
				for part in report.parts:
					root = ET.fromstring(archive.read(part.part))
					texts = [node.text or "" for node in root.iter() if node.tag == "{" + FidelityConstant.WORD_NS + "}t"]
					expected = re.sub(r"\s", "", "".join(texts))
					content = markdown.split(f"<!-- source: {part.part} -->", 1)[1].split("<!-- source:", 1)[0] if expected else ""
					parser = VisibleTextParser()
					parser.feed(content)
					actual = re.sub(r"\s", "", "".join(parser.text))
					self.assertEqual(actual, expected, part.part)
					self.assertEqual(part.tables, len(root.findall(".//{" + FidelityConstant.WORD_NS + "}tbl")))
				for image in (output / "images").iterdir():
					self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), image.stem)
		self.assertTrue(found, "Supply at least one real DOCX")

	def test_pdf_native_characters_and_page_count(self):
		"""Each PDF page keeps exactly its native characters, including page numbers."""
		found = False
		for source, output, report in self.results:
			if source.suffix.lower() != ".pdf":
				continue
			found = True
			markdown = (output / "result.md").read_text(encoding="utf-8")
			with pymupdf.open(source) as document:
				self.assertEqual(len(report.parts), len(document))
				for page, part in zip(document, report.parts):
					content = markdown.split(f"<!-- page: {page.number + 1};", 1)[1].split("-->", 1)[1].split("<details>", 1)[0]
					parser = VisibleTextParser()
					parser.feed(content)
					expected = Counter(re.sub(r"\s", "", page.get_text()))
					actual = Counter(re.sub(r"\s", "", "".join(parser.text)))
					self.assertEqual(actual, expected, f"Page {page.number + 1}")
					self.assertEqual(part.source_characters, expected.total())
		self.assertTrue(found, "Supply at least one real text PDF")

	def test_assets_and_archive_are_complete(self):
		"""All Markdown image references resolve inside the downloadable ZIP."""
		self.assertTrue(self.results)
		for source, output, report in self.results:
			markdown = (output / "result.md").read_text(encoding="utf-8")
			paths = re.findall(r'(?:src="|\]\()(images/[^"\s)]+)', markdown)
			with ZipFile(output / "result.zip") as archive:
				self.assertEqual(archive.read("result.md").decode("utf-8"), markdown)
				self.assertIn("report.json", archive.namelist())
				for name in paths:
					self.assertEqual(archive.read(name), (output / name).read_bytes())
			self.assertTrue(report.requires_review)

	def test_native_loss_and_duplication_are_rejected(self):
		"""A missing or repeated original character must fail the coverage gate."""
		source, output, report = self.results[0]
		parser = VisibleTextParser()
		parser.feed((output / "result.md").read_text(encoding="utf-8"))
		text = re.sub(r"\s", "", "".join(parser.text))[:100]
		self.assertTrue(text)
		part = FidelityPartVo(part="coverage", method="native")
		with self.assertRaisesRegex(ValueError, "coverage mismatch"):
			fidelity_service.check_text(text, text[1:], part)
		with self.assertRaisesRegex(ValueError, "coverage mismatch"):
			fidelity_service.check_text(text, text + text[0], part)

	def test_scan_is_not_misreported_as_empty_native_text(self):
		"""A real image-only page requires OCR instead of yielding an empty success."""
		self.assertTrue(self.scans, "Supply at least one real scanned PDF")
		for index, source in enumerate(self.scans):
			with self.assertRaisesRegex(ValueError, "requires OCR"):
				fidelity_service.parse_file(source, self.root / f"scan-{index}", ocr=False)

	def test_http_body_and_artifact_contract_without_database(self):
		"""The independent route returns matching text and assets without task ORM state."""
		from fastapi import FastAPI
		from fastapi.testclient import TestClient
		from core.api.fidelity_api import router
		from core.config import settings
		original_storage = settings.SHARED_DATA_DIR
		settings.SHARED_DATA_DIR = str(self.root / "http")
		try:
			app = FastAPI()
			app.include_router(router)
			with TestClient(app) as client:
				for source, output, report in self.results:
					with source.open("rb") as file:
						response = client.post("/api/v1/parse/faithful", files={"file": ("document" + source.suffix, file)}, data={"ocr": "false"})
					self.assertEqual(response.status_code, 200, response.text[:100])
					artifact_id = response.headers["x-sentry-artifact-id"]
					artifact = client.get(f"/api/v1/parse/faithful/{artifact_id}/zip")
					self.assertEqual(artifact.status_code, 200)
					with ZipFile(io.BytesIO(artifact.content)) as archive:
						self.assertEqual(archive.read("result.md").decode("utf-8"), response.text)
				self.assertEqual(client.get("/api/v1/parse/faithful/invalid/zip").status_code, 404)
		finally:
			settings.SHARED_DATA_DIR = original_storage


if __name__ == "__main__":
	unittest.main()
