"""Service for combining and stitching multi-segment Markdown and Middle JSON documents."""
import json
from pathlib import Path
import shutil
from typing import List, Optional, Tuple
import logging


class StitcherService:
	"""
	Combines sequential Markdown segments and JSON files generated from resumed tasks.
	"""

	@staticmethod
	def stitch_segments(
		segment_dirs: List[Path],
		output_dir: Path,
		final_filename: str,
		page_ranges: List[Tuple[int, int]],
	) -> Tuple[Path, Optional[Path]]:
		"""
		Merges sequential segment folders into a single unified Markdown and Middle JSON output.
		:param segment_dirs: Chronologically ordered list of segment directories.
		:param output_dir: Directory to place the final unified files.
		:param final_filename: Base stem name for the output markdown file.
		:param page_ranges: List of (start_page, end_page) tuples matching segments.
		:return: Tuple of (final_markdown_path, final_middle_json_path).
		"""
		output_dir.mkdir(parents=True, exist_ok=True)
		unified_images_dir = output_dir / "images"
		unified_images_dir.mkdir(parents=True, exist_ok=True)

		combined_md_lines: List[str] = []
		collected_pages: List[object] = []
		base_meta_obj = {}

		total_segments = len(segment_dirs)
		for idx, seg_dir in enumerate(segment_dirs):
			page_tuple = page_ranges[idx] if idx < len(page_ranges) else (0, 0)
			start_p = page_tuple[0]
			end_p = page_tuple[1]
			logging.info(f"Stitching segment {idx + 1}/{total_segments}: pages {start_p}-{end_p} from {seg_dir}")

			# 1. Locate markdown file
			md_file_list = list(seg_dir.glob("**/*.md"))
			if md_file_list:
				first_md = md_file_list[0]
				with open(first_md, "r", encoding="utf-8") as f_in:
					md_text = f_in.read().strip()

				if idx > 0:
					divider_line = f"\n\n<!-- ==================== Page Break (Pages {start_p} - {end_p}) ==================== -->\n\n"
					combined_md_lines.append(divider_line)
				combined_md_lines.append(md_text)

			# 2. Consolidate image files
			images_folders = list(seg_dir.glob("**/images"))
			for img_folder in images_folders:
				if img_folder.is_dir():
					for img_file in img_folder.glob("*.*"):
						dest_file = unified_images_dir / img_file.name
						if not dest_file.exists():
							shutil.copy2(img_file, dest_file)

			# 3. Consolidate middle JSON structure
			middle_files = list(seg_dir.glob("**/*_middle.json"))
			if middle_files:
				first_middle = middle_files[0]
				try:
					with open(first_middle, "r", encoding="utf-8") as f_mid:
						raw_data = json.load(f_mid)
						pdf_info_list = raw_data.get("pdf_info")
						if isinstance(pdf_info_list, list):
							collected_pages.extend(pdf_info_list)
						for k, v in raw_data.items():
							if k != "pdf_info":
								base_meta_obj[k] = v
				except Exception as exc:
					logging.warning(f"Failed to parse middle json at {first_middle}: {exc}")

		# 4. Write final stitched Markdown
		final_md_path = output_dir / f"{final_filename}.md"
		with open(final_md_path, "w", encoding="utf-8") as f_out:
			f_out.write("".join(combined_md_lines))
		logging.info(f"Final stitched markdown created at: {final_md_path}")

		# 5. Write final stitched middle JSON
		final_middle_path: Optional[Path] = None
		if collected_pages:
			final_middle_path = output_dir / f"{final_filename}_middle.json"
			base_meta_obj["pdf_info"] = collected_pages
			with open(final_middle_path, "w", encoding="utf-8") as f_json:
				json.dump(base_meta_obj, f_json, ensure_ascii=False, indent=2)
			logging.info(f"Final stitched middle json created at: {final_middle_path}")

		return final_md_path, final_middle_path


# Global singleton service
stitcher_service = StitcherService()
