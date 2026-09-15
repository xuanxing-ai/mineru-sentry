"""Extract original text and retain visual evidence without rewriting document content."""
import base64
from collections import Counter
import hashlib
from html import escape
from html.parser import HTMLParser
import logging
from pathlib import Path
import posixpath
import re
import shutil
import time
import uuid
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import pymupdf

from core.constant.fidelity_constant import FidelityConstant
from core.dto.fidelity_vo import FidelityPartVo, FidelityReportVo
from core.service.stitcher_service import stitcher_service


class VisibleTextParser(HTMLParser):
	"""Read emitted HTML text for independent native-character coverage checks."""

	def __init__(self):
		"""Collect decoded visible text while excluding markup and image attributes."""
		super().__init__(convert_charrefs=True)
		self.text = []

	def handle_data(self, data: str) -> None:
		"""Record literal text for a multiset comparison against the source."""
		self.text.append(data)


class WordRenderer:
	"""Render Word XML in document order, including nested tables and original assets."""

	def __init__(self, archive: ZipFile, output_dir: Path):
		"""Keep archive relationships local to each input document."""
		self.archive = archive
		self.output_dir = output_dir
		self.ns = {"w": FidelityConstant.WORD_NS}
		self.word = "{" + FidelityConstant.WORD_NS + "}"
		self.rel = "{" + FidelityConstant.REL_NS + "}"
		self.relationships = {}
		self.warnings = []
		self.source_text = []

	def render_part(self, part: str) -> str:
		"""Resolve this part's own media references before traversing its XML."""
		self.relationships = {}
		parent, name = posixpath.split(part)
		rels_path = posixpath.join(parent, "_rels", name + ".rels")
		if rels_path in self.archive.namelist():
			for rel in ET.fromstring(self.archive.read(rels_path)):
				if rel.get("TargetMode") != "External":
					target = posixpath.normpath(posixpath.join(parent, rel.get("Target", "")))
					self.relationships[rel.get("Id")] = target
		root = ET.fromstring(self.archive.read(part))
		return self.render(root)

	def render(self, node) -> str:
		"""Preserve visible text rather than inferred headings, corrected wording or summaries."""
		tag = node.tag.rsplit("}", 1)[-1]
		if tag == "AlternateContent":
			# Choice and Fallback describe the same object; emitting both duplicates content.
			choice = next((child for child in node if child.tag.endswith("}Choice")), None)
			if choice is None:
				choice = next(iter(node), None)
			return self.render(choice) if choice is not None else ""
		if tag in ("del", "moveFrom", "instrText", "delText") or tag.endswith("Pr"):
			return ""
		if tag in ("altChunk", "chart", "OLEObject"):
			raise ValueError(f"Word contains an unsupported {tag} object; cannot silently omit it")
		if tag == "t":
			text = node.text or ""
			self.source_text.append(text)
			return escape(text, quote=False)
		if tag in ("tab", "ptab"):
			return "&#9;"
		if tag in ("br", "cr"):
			return "<br>"
		if tag == "noBreakHyphen":
			self.source_text.append("\u2011")
			return "\u2011"
		if tag == "softHyphen":
			self.source_text.append("\u00ad")
			return "\u00ad"
		if tag == "sym":
			self.warnings.append("A symbol uses a font-specific character code; verify it in Word.")
			text = chr(int(node.get(self.word + "char", "FFFD"), 16))
			self.source_text.append(text)
			return escape(text)
		if tag in ("blip", "imagedata"):
			rel_id = node.get(self.rel + "embed") or node.get(self.rel + "id")
			if not rel_id and tag == "imagedata" and list(node.attrib.values()) == [""]:
				# Word can contain empty VML image slots with only an empty title.
				return ""
			target = self.relationships.get(rel_id)
			if not target or target not in self.archive.namelist():
				raise ValueError("A Word image is external or missing; cannot publish a complete result")
			data = self.archive.read(target)
			suffix = Path(target).suffix.lower()
			name = hashlib.sha256(data).hexdigest() + suffix
			(self.output_dir / "images" / name).write_bytes(data)
			if suffix in (".emf", ".wmf"):
				self.warnings.append("A vector Office image is preserved but may need an Office-compatible viewer.")
			return f'<img src="images/{name}" alt="">'
		if tag == "tbl":
			return self.render_table(node)
		content = "".join(self.render(child) for child in node)
		if tag == "r":
			vertical = node.find("w:rPr/w:vertAlign", self.ns)
			if vertical is not None:
				position = vertical.get(self.word + "val")
				if position in ("superscript", "subscript"):
					wrapper = "sup" if position == "superscript" else "sub"
					content = f"<{wrapper}>{content}</{wrapper}>"
		if tag == "p":
			if node.find("w:pPr/w:numPr", self.ns) is not None:
				# A missing generated list label is not an acceptable successful extraction.
				raise ValueError("Automatic Word list numbering is not supported by native extraction yet")
			wrapper = "div" if "<p " in content or "<table>" in content else "p"
			return f'<{wrapper} style="white-space:pre-wrap">{content}</{wrapper}>\n' if content else ""
		if tag in ("oMath", "oMathPara", "object"):
			self.warnings.append("An equation or embedded object requires visual verification in the original Word file.")
		return content

	def render_table(self, table) -> str:
		"""Preserve merged cells without repeating their values in continuation rows."""
		rows = table.findall("w:tr", self.ns)
		cells = []
		active = {}
		for row in rows:
			before = row.find("w:trPr/w:gridBefore", self.ns)
			column = int(before.get(self.word + "val", "0")) if before is not None else 0
			row_cells = []
			next_active = {}
			for cell in row.findall("w:tc", self.ns):
				span_node = cell.find("w:tcPr/w:gridSpan", self.ns)
				span = int(span_node.get(self.word + "val", "1")) if span_node is not None else 1
				merge = cell.find("w:tcPr/w:vMerge", self.ns)
				content = "".join(self.render(child) for child in cell)
				key = (column, span)
				if merge is not None and merge.get(self.word + "val") != "restart" and key in active:
					previous = active[key]
					previous[2] += 1
					previous[3] += content
					next_active[key] = previous
				else:
					entry = [column, span, 1, content]
					row_cells.append(entry)
					if merge is not None:
						next_active[key] = entry
				column += span
			cells.append(row_cells)
			active = next_active
		result = ['<table>']
		for row_cells in cells:
			result.append("<tr>")
			for column, colspan, rowspan, content in row_cells:
				result.append(f'<td colspan="{colspan}" rowspan="{rowspan}">{content}</td>')
			result.append("</tr>")
		result.append("</table>\n")
		return "".join(result)


class FidelityService:
	"""Offer an independent extraction path with explicit per-part coverage evidence."""

	def parse_file(self, source: Path, output_dir: Path, ocr: bool = True) -> FidelityReportVo:
		"""Save Markdown, assets and a report; never accept silent native-text loss."""
		output_dir.mkdir(parents=True, exist_ok=True)
		(output_dir / "images").mkdir(exist_ok=True)
		with source.open("rb") as input_file:
			digest = hashlib.file_digest(input_file, "sha256").hexdigest()
		report = FidelityReportVo(source_sha256=digest, format=source.suffix.lower().lstrip("."))
		if source.suffix.lower() == ".docx":
			markdown = self.parse_word(source, output_dir, report)
		elif source.suffix.lower() == ".pdf":
			markdown = self.parse_pdf(source, output_dir, report, ocr)
		else:
			raise ValueError("Native extraction supports PDF and DOCX; save legacy DOC as DOCX first")
		for reference in re.findall(r'(?:src="|\]\()(images/[^"\s)]+)', markdown):
			image_path = (output_dir / reference).resolve()
			if not image_path.is_relative_to(output_dir.resolve()) or not image_path.is_file():
				raise ValueError("An image reference is missing or unsafe; refusing incomplete output")
		stitcher_service.write_checkpoint(output_dir / "result.md", markdown)
		stitcher_service.write_checkpoint(output_dir / "report.json", report.model_dump_json(indent=2))
		with ZipFile(output_dir / "result.zip", "w", ZIP_DEFLATED) as archive:
			archive.write(output_dir / "result.md", "result.md")
			archive.write(output_dir / "report.json", "report.json")
			for image in sorted((output_dir / "images").iterdir()):
				archive.write(image, "images/" + image.name)
		return report

	@staticmethod
	def check_text(source_text: str, html: str, part: FidelityPartVo) -> None:
		"""Require identical native character counts; this does not certify reading order."""
		parser = VisibleTextParser()
		parser.feed(html)
		source_characters = Counter(re.sub(r"\s", "", source_text))
		emitted_characters = Counter(re.sub(r"\s", "", "".join(parser.text)))
		part.source_characters = source_characters.total()
		part.emitted_characters = emitted_characters.total()
		if source_characters != emitted_characters:
			raise ValueError(f"Native text coverage mismatch in {part.part}; refusing incomplete output")

	def parse_word(self, source: Path, output_dir: Path, report: FidelityReportVo) -> str:
		"""Keep body, headers, footers, footnotes and endnotes from the original package."""
		sections = []
		with ZipFile(source) as archive:
			renderer = WordRenderer(archive, output_dir)
			parts = ["word/document.xml"]
			parts.extend(sorted(name for name in archive.namelist() if re.fullmatch(
				r"word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml", name,
			)))
			for name in parts:
				renderer.source_text = []
				renderer.warnings = []
				content = renderer.render_part(name)
				part = FidelityPartVo(part=name, method="native-word", tables=content.count("<table>"))
				self.check_text("".join(renderer.source_text), content, part)
				part.warnings = sorted(set(renderer.warnings))
				if name != "word/document.xml":
					part.warnings.append("Header/footer/note content is retained separately; Word pagination is not reproduced.")
				report.parts.append(part)
				if content:
					sections.append(f"<!-- source: {name} -->\n\n{content}\n")
		return "\n".join(sections)

	def parse_pdf(self, source: Path, output_dir: Path, report: FidelityReportVo, ocr: bool) -> str:
		"""Extract each page independently and preserve its rendered appearance for review."""
		sections = []
		with pymupdf.open(source) as document:
			if document.needs_pass:
				raise ValueError("Encrypted PDF requires an unlocked copy")
			if not len(document):
				raise ValueError("PDF has no pages")
			for page in document:
				page_number = page.number + 1
				image_name = f"page-{page_number:04d}.png"
				image_path = output_dir / "images" / image_name
				page.get_pixmap(dpi=FidelityConstant.PAGE_DPI).save(image_path)
				text = page.get_text()
				part = FidelityPartVo(part=str(page_number), method="native-pdf")
				image_coverage = max((pymupdf.Rect(info["bbox"]).get_area() / page.rect.get_area()
					for info in page.get_image_info()), default=0)
				is_scan_with_header = image_coverage > 0.65 and len(re.sub(r"\s", "", text)) < 200
				if text.strip() and "\ufffd" not in text and not is_scan_with_header:
					content = self.render_pdf_page(page, part, output_dir)
					part.warnings.append("Native character coverage does not verify table geometry, reading order or image text.")
				elif page.get_images() or page.get_drawings() or text.strip():
					if not ocr:
						raise ValueError(f"Page {page_number} requires OCR; enable OCR to extract this page")
					content = self.ocr_page(source, page.number, output_dir)
					part.method = "ocr"
					part.warnings.append("OCR text is unverified. Compare every word, number and symbol with the page image.")
				else:
					content = ""
					part.method = "blank-page"
				report.parts.append(part)
				sections.append(
					f"<!-- page: {page_number}; method: {part.method} -->\n\n{content}\n\n"
					f"<details><summary>原始第 {page_number} 页（核对用）</summary>\n\n"
					f"![原始第 {page_number} 页](images/{image_name})\n\n</details>\n\n"
				)
				logging.info("Faithful extraction: page %s, %s, native characters %s", page_number, part.method, part.source_characters)
		return "".join(sections)

	def render_pdf_page(self, page, part: FidelityPartVo, output_dir: Path) -> str:
		"""Assign every native character once to a detected table cell or an outside line."""
		flags = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
		blocks = page.get_text("rawdict", flags=flags, sort=True)["blocks"]
		# PDF text operators often split formulas and superscripts into separate lines.
		# Group spans by baseline within each source block before assigning characters.
		for block in blocks:
			groups = []
			source_lines = block.get("lines", [])
			for source_line in sorted(source_lines, key=lambda item: -max(span["size"] for span in item["spans"])):
				span = max(source_line["spans"], key=lambda item: item["size"])
				baseline = span["origin"][1]
				matches = [group for group in groups if abs(group["baseline"] - baseline) <= group["size"] * (
					0.8 if span["size"] < group["size"] * 0.85 else 0.45
				)]
				if matches:
					group = min(matches, key=lambda item: abs(item["baseline"] - baseline))
					group["spans"].extend(source_line["spans"])
					group["bbox"] |= pymupdf.Rect(source_line["bbox"])
				else:
					groups.append({"baseline": baseline, "size": span["size"], "spans": list(source_line["spans"]), "bbox": pymupdf.Rect(source_line["bbox"])})
			block["lines"] = sorted(groups, key=lambda item: (item["bbox"].y0, item["bbox"].x0))
			for line in block["lines"]:
				line["spans"].sort(key=lambda span: span["bbox"][0])
		tables = page.find_tables().tables
		part.tables = len(tables)
		# Flat cells retain their geometry; merged rectangles are emitted only once.
		cells = []
		for table_index, table in enumerate(tables):
			for bounds in sorted(set(tuple(cell) for cell in table.cells if cell)):
				cells.append((table_index, pymupdf.Rect(bounds), []))
		outside = []
		outside_bounds = []
		source_text = []
		line_index = 0
		for block in blocks:
			for line in block.get("lines", []):
				fragments = []
				for span in line["spans"]:
					for char in span["chars"]:
						value = char["c"]
						source_text.append(value)
						bounds = pymupdf.Rect(char["bbox"])
						center = (bounds.tl + bounds.br) / 2
						fragment = escape(value, quote=False)
						baseline_offset = span["origin"][1] - line["baseline"]
						is_small = span["size"] < line["size"] * 0.85
						if span["flags"] & 1 or (is_small and baseline_offset < -line["size"] * 0.08):
							fragment = f"<sup>{fragment}</sup>"
						elif is_small and baseline_offset > line["size"] * 0.08:
							fragment = f"<sub>{fragment}</sub>"
						cell = next((cell for cell in cells if center in cell[1]), None)
						if cell is None:
							fragments.append((bounds.x0, fragment))
						else:
							cell[2].append((line_index, fragment))
				if fragments and any(re.sub(r"<[^>]+>", "", fragment).strip() for _, fragment in fragments):
					outside.append((line["bbox"][1], line["bbox"][0], fragments))
					outside_bounds.append(pymupdf.Rect(line["bbox"]))
				line_index += 1
		# Some PDFs encode one formula symbol as dozens of one-pixel image strips.
		# Join touching strips before inserting the visual at its original text position.
		image_regions = []
		for info in page.get_image_info():
			region = pymupdf.Rect(info["bbox"]) & page.rect
			if region.is_empty:
				continue
			pending = True
			while pending:
				pending = False
				for previous in image_regions[:]:
					if (region + (-2, -2, 2, 2)).intersects(previous):
						region |= previous
						image_regions.remove(previous)
						pending = True
			image_regions.append(region)
		image_items = []
		for image_index, region in enumerate(image_regions):
			name = f"page-{page.number + 1:04d}-image-{image_index + 1}.png"
			page.get_pixmap(clip=region, dpi=216).save(output_dir / "images" / name)
			image_html = f'<img src="images/{name}" width="{region.width:.1f}" alt="">'
			center = (region.tl + region.br) / 2
			cell = next((cell for cell in cells if center in cell[1]), None)
			if cell is not None:
				cell[2].append((line_index + image_index, image_html))
				continue
			inline = [index for index, bounds in enumerate(outside_bounds)
				if abs((bounds.y0 + bounds.y1) / 2 - center.y) < bounds.height / 2
				and region.height < bounds.height * 2 and bounds.x0 - 30 < center.x < bounds.x1 + 30]
			if inline:
				outside[inline[0]][2].append((region.x0, image_html))
			else:
				image_items.append((region.y0, region.x0, image_html))
		items = []
		for y, x, fragments in outside:
			text = "".join(fragment for _, fragment in sorted(fragments, key=lambda item: item[0]))
			items.append((y, x, f'<p style="white-space:pre-wrap">{text}</p>'))
		items.extend(image_items)
		for table_index, table in enumerate(tables):
			table_cells = [cell for cell in cells if cell[0] == table_index]
			xs = sorted({round(cell[1].x0, 1) for cell in table_cells} | {round(cell[1].x1, 1) for cell in table_cells})
			ys = sorted({round(cell[1].y0, 1) for cell in table_cells} | {round(cell[1].y1, 1) for cell in table_cells})
			rows = []
			for y in ys[:-1]:
				row = []
				for _, bounds, fragments in sorted(table_cells, key=lambda cell: cell[1].x0):
					if round(bounds.y0, 1) != y:
						continue
					colspan = xs.index(round(bounds.x1, 1)) - xs.index(round(bounds.x0, 1))
					rowspan = ys.index(round(bounds.y1, 1)) - ys.index(round(bounds.y0, 1))
					text = []
					previous_line = None
					for index, fragment in fragments:
						if previous_line is not None and index != previous_line:
							text.append("<br>")
						text.append(fragment)
						previous_line = index
					row.append(f'<td colspan="{colspan}" rowspan="{rowspan}">{"".join(text)}</td>')
				rows.append("<tr>" + "".join(row) + "</tr>")
			items.append((table.bbox[1], table.bbox[0], "<table>" + "".join(rows) + "</table>"))
		# A persistent central gutter separates columns; y-only sorting interleaves them.
		line_bounds = [line["bbox"] for block in blocks for line in block.get("lines", [])]
		body_bounds = [bounds for bounds in line_bounds if page.rect.height * 0.1 < bounds[1] < page.rect.height * 0.9]
		candidates = [page.rect.width * fraction / 100 for fraction in range(40, 61)]
		gutter = min(candidates, key=lambda x: sum(bounds[0] < x < bounds[2] for bounds in body_bounds))
		left_count = sum(bounds[2] <= gutter for bounds in body_bounds)
		right_count = sum(bounds[0] >= gutter for bounds in body_bounds)
		crossing_count = sum(bounds[0] < gutter < bounds[2] for bounds in body_bounds)
		is_two_columns = min(left_count, right_count) >= 5 and crossing_count <= 2
		if is_two_columns:
			items.sort(key=lambda item: (
				0 if item[0] < page.rect.height * 0.1 else
				3 if item[0] > page.rect.height * 0.94 else 1 if item[1] < gutter else 2,
				item[0], item[1],
			))
		else:
			items.sort(key=lambda item: (item[0], item[1]))
		content = "\n\n".join(item[2] for item in items)
		self.check_text("".join(source_text), content, part)
		return content

	@staticmethod
	def ocr_page(source: Path, page_index: int, output_dir: Path) -> str:
		"""Use the existing GPU worker only for pages without usable native text."""
		from core.config import settings
		from core.service.docker_service import docker_service
		from core.service.mineru_client_service import MineruClientError, MineruTaskUnavailableError, mineru_client_service
		docker_service.increment_active_tasks()
		try:
			if not docker_service.wake_worker():
				raise RuntimeError("GPU worker failed to become healthy")
			task_id = None
			submissions = 0
			deadline = time.monotonic() + int(settings.DEFAULT_MINERU_TASK_RESULT_TIMEOUT_SECONDS or 3600)
			while time.monotonic() < deadline:
				docker_service.touch_activity()
				if task_id is None:
					if submissions >= 3:
						raise RuntimeError(f"OCR repeatedly lost page {page_index + 1}")
					task_id = mineru_client_service.submit_parse_task(
						source, source.name, effort="high", parse_method="ocr", return_images=True,
						start_page_id=page_index, end_page_id=page_index,
					)
					submissions += 1
				try:
					status = mineru_client_service.get_task_status(task_id)
				except MineruTaskUnavailableError:
					# Only a definitive missing job permits submitting the same page again.
					task_id = None
					continue
				except MineruClientError:
					logging.warning("Reconnecting to OCR page %s", page_index + 1)
					if not docker_service.check_api_health() and not docker_service.wake_worker():
						raise RuntimeError("GPU worker could not reconnect")
					time.sleep(2)
					continue
				if status == "completed":
					break
				if status == "failed":
					raise RuntimeError(f"OCR failed on page {page_index + 1}")
				time.sleep(2)
			else:
				raise TimeoutError(f"OCR timed out on page {page_index + 1}")
			markdown, images_dict = mineru_client_service.get_task_result(task_id)
			ocr_images_dir = output_dir / "images"
			ocr_images_dir.mkdir(parents=True, exist_ok=True)
			for img_name, data_uri in images_dict.items():
				try:
					raw_b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
					img_bytes = base64.b64decode(raw_b64)
					name = f"ocr-{page_index + 1}-{Path(img_name).name}"
					(ocr_images_dir / name).write_bytes(img_bytes)
					markdown = markdown.replace("images/" + img_name, "images/" + name)
				except Exception as exc:
					logging.warning("Failed to decode OCR image %s: %s", img_name, exc)
			for name in re.findall(r"!?\[[^\]]*\]\(images/([^\s)]+)\)", markdown):
				if not (output_dir / "images" / name).is_file():
					raise RuntimeError("An OCR image was not retained; cannot publish a complete result")
			if not markdown.strip():
				raise RuntimeError(f"OCR returned no content for nonblank page {page_index + 1}")
			return markdown
		finally:
			docker_service.decrement_active_tasks()

	def handle_parse(self, upload, ocr: bool):
		"""Store each independent extraction under a fresh ID to avoid stale MinerU caches."""
		from fastapi import HTTPException
		from fastapi.responses import PlainTextResponse
		from core.config import settings
		root = Path(settings.SHARED_DATA_DIR or "/usr/model/MinerU/data") / "faithful"
		artifact_id = uuid.uuid4().hex
		output_dir = root / artifact_id
		suffix = Path(upload.filename or "").suffix.lower()
		if suffix not in (".pdf", ".docx"):
			raise HTTPException(status_code=422, detail="Supports PDF and DOCX; save legacy DOC as DOCX first")
		output_dir.mkdir(parents=True)
		source = output_dir / ("source" + suffix)
		try:
			with source.open("wb") as output:
				shutil.copyfileobj(upload.file, output)
			self.parse_file(source, output_dir, ocr)
		except ValueError as exc:
			raise HTTPException(status_code=422, detail=str(exc)) from exc
		except Exception as exc:
			logging.exception("Faithful extraction failed: %s", artifact_id)
			raise HTTPException(status_code=502, detail="Extraction failed; no complete result was published") from exc
		finally:
			source.unlink(missing_ok=True)
		content = (output_dir / "result.md").read_text(encoding="utf-8")
		headers = {
			"X-Sentry-Artifact-ID": artifact_id,
			"X-Sentry-Review-Required": "true",
			"Cache-Control": "no-store",
		}
		return PlainTextResponse(content, media_type="text/markdown", headers=headers)

	@staticmethod
	def handle_artifact(artifact_id: str):
		"""Return the Markdown, referenced assets and coverage report as one portable ZIP."""
		from fastapi import HTTPException
		from fastapi.responses import FileResponse
		from core.config import settings
		if not re.fullmatch(r"[0-9a-f]{32}", artifact_id):
			raise HTTPException(status_code=404, detail="Artifact not found")
		root = Path(settings.SHARED_DATA_DIR or "/usr/model/MinerU/data") / "faithful"
		path = root / artifact_id / "result.zip"
		if not path.is_file():
			raise HTTPException(status_code=404, detail="Completed artifact not found")
		return FileResponse(path, media_type="application/zip", filename="result.zip")


fidelity_service = FidelityService()
