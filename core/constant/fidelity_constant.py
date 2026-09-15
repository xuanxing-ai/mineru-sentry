"""Format identifiers shared by native document extraction."""


class FidelityConstant:
	"""Keep document namespace and rendering settings separate from business logic."""
	WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
	REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
	PAGE_DPI = 144
	SCHEMA_VERSION = 1
