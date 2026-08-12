"""
Typed exceptions for the ingestion pipeline.

Using specific exception types (rather than bare ValueError / Exception)
ensures callers can handle parsing vs. chunking failures independently,
and that errors are never silently swallowed — per RULES.md Rule 14.
"""


class ParsingError(Exception):
    """
    Raised when a resume or JD cannot be parsed into usable text.

    Examples:
    - PDF with no extractable text (image-only / scanned)
    - Malformed / truncated DOCX
    - Unsupported file extension
    - JD text too short to contain meaningful content
    """


class ChunkingError(Exception):
    """
    Raised when valid parsed text cannot be split into chunks.

    Examples:
    - Empty string passed to chunker after stripping
    - Invalid source identifier (not 'resume' or 'jd')
    """
