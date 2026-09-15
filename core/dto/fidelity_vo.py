"""Evidence and limitations accompanying a faithful extraction."""
from typing import List

from pydantic import BaseModel, Field

from core.constant.fidelity_constant import FidelityConstant


class FidelityPartVo(BaseModel):
	"""Describe one page or Word package part without claiming OCR correctness."""
	# One-based PDF page number or Word package part name.
	part: str
	# Native XML, native PDF text, or probabilistic OCR.
	method: str
	# Number of original non-whitespace characters available for comparison.
	source_characters: int = 0
	# Number of original non-whitespace characters emitted.
	emitted_characters: int = 0
	# Count of native tables retained in this part.
	tables: int = 0
	# Reasons why visual or manual verification is still needed.
	warnings: List[str] = Field(default_factory=list)


class FidelityReportVo(BaseModel):
	"""Publish reproducible coverage evidence separately from the document content."""
	# Report format version, independent of the original parser cache.
	schema_version: int = FidelityConstant.SCHEMA_VERSION
	# SHA-256 of the exact uploaded bytes.
	source_sha256: str
	# Original container format.
	format: str
	# Ordered page or package-part results.
	parts: List[FidelityPartVo] = Field(default_factory=list)
	# Native text coverage alone cannot certify visual or OCR correctness.
	requires_review: bool = True
