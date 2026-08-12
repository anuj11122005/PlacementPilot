"""
Section-aware chunker — Phase 1 of the PlacementPilot ingestion pipeline.

Splits parsed text (from resume_parser or jd_parser) into section-tagged
chunks with metadata, as specified in ARCHITECTURE.md §3.1:

    Each chunk stored with metadata: {source, section_type, chunk_id}

Design decisions:
- Section detection uses heading-keyword heuristics (regex). This is
  language-model-free, deterministic, and fully testable. A more
  sophisticated classifier can replace this in a later phase without
  changing the chunk schema.
- chunk_id format: "{source}_{section_type}_{index}" (e.g. "resume_skills_0")
  Deterministic and human-readable; good for debugging and unit tests.
- If no known section header is detected, the entire text is tagged as
  section_type="general" — never silently dropped.
- Chunks below min_chunk_chars are discarded (prevents empty/noise chunks).

RULES compliance:
- Rule 14: ChunkingError raised explicitly — never silently swallowed.
- Rule 11: No hidden global state; fully unit-testable in isolation.
"""

import logging
import re

from ingestion.exceptions import ChunkingError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section heading patterns
# ---------------------------------------------------------------------------
# Each pattern is tried (case-insensitive) against lines that look like
# headings (short lines, possibly followed by a colon or newline).
# Order matters: first match wins for a given heading line.

_RESUME_SECTION_PATTERNS: list[tuple[str, str]] = [
    (r"\bsummary\b|\bobjective\b|\bprofile\b|\babout me\b", "summary"),
    (r"\bskills?\b|\btechnical skills?\b|\bcore competenc", "skills"),
    (r"\bexperience\b|\bwork history\b|\bemployment\b|\bwork experience\b", "experience"),
    (r"\beducation\b|\bacademic\b|\bqualification", "education"),
    (r"\bprojects?\b|\bpersonal projects?\b|\bacademic projects?\b", "projects"),
    (r"\bcertification|\blicense", "certifications"),
    (r"\bawards?\b|\bachievement|\bhonors?\b", "awards"),
    (r"\bpublication|\bresearch", "publications"),
    (r"\blanguages?\b", "languages"),
    (r"\bvolunteer|\bextracurricular|\bactivit", "activities"),
    (r"\breferences?\b", "references"),
]

_JD_SECTION_PATTERNS: list[tuple[str, str]] = [
    (r"\babout (the )?(role|job|position|company|us)\b|\boverview\b", "overview"),
    (r"\bresponsibilit|\bduties\b|\byou will\b|\bwhat you.ll do\b", "responsibilities"),
    (r"\brequirements?\b|\bqualification|\bwhat we.re looking\b|\bwhat you need\b", "requirements"),
    (r"\bnice.to.have|\bpreferred\b|\bbonus\b|\bdesirable\b", "nice_to_have"),
    (r"\bskills?\b|\btechnical skills?\b", "skills"),
    (r"\bbenefits?\b|\bperks?\b|\bwhat we offer\b|\bcompensation\b", "benefits"),
    (r"\bequal opportunity|\bdiversity\b|\binclusion\b", "eeo"),
]

# Minimum characters a chunk must have to be kept (filters noise/blank chunks)
DEFAULT_MIN_CHUNK_CHARS = 30

# Valid source identifiers
_VALID_SOURCES = {"resume", "jd"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    source: str,
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
) -> list[dict]:
    """
    Split parsed text into section-tagged chunks with metadata.

    Args:
        text:            Clean text from resume_parser or jd_parser.
        source:          "resume" or "jd" — determines which section patterns
                         are applied and prefixes chunk_ids.
        min_chunk_chars: Chunks shorter than this are discarded. Increase to
                         filter more aggressively; set to 0 to keep everything.

    Returns:
        List of chunk dicts, each with keys:
            - source:       "resume" | "jd"
            - section_type: detected section label or "general"
            - chunk_id:     "{source}_{section_type}_{index}"
            - text:         chunk text content

    Raises:
        ValueError:     If source is not "resume" or "jd".
        ChunkingError:  If text is empty after stripping.
    """
    if source not in _VALID_SOURCES:
        raise ValueError(
            f"Invalid source '{source}'. Must be one of: {sorted(_VALID_SOURCES)}"
        )

    stripped = text.strip() if text else ""
    if not stripped:
        raise ChunkingError(
            f"Cannot chunk empty text for source='{source}'. "
            "Ensure the parser returned non-empty text before calling chunk_text."
        )

    patterns = _RESUME_SECTION_PATTERNS if source == "resume" else _JD_SECTION_PATTERNS
    raw_sections = _split_into_sections(stripped, patterns)

    chunks: list[dict] = []
    section_counters: dict[str, int] = {}

    for section_type, section_text in raw_sections:
        section_text = section_text.strip()
        if len(section_text) < min_chunk_chars:
            logger.debug(
                "Discarding short chunk: source=%s section=%s chars=%d",
                source, section_type, len(section_text),
            )
            continue

        idx = section_counters.get(section_type, 0)
        section_counters[section_type] = idx + 1

        chunk_id = f"{source}_{section_type}_{idx}"
        chunks.append(
            {
                "source": source,
                "section_type": section_type,
                "chunk_id": chunk_id,
                "text": section_text,
            }
        )

    logger.info(
        "Chunking complete: source=%s total_chunks=%d sections=%s",
        source,
        len(chunks),
        sorted(section_counters.keys()),
    )
    return chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_heading_line(line: str) -> bool:
    """
    Heuristic: a line is a potential section heading if it is short (≤ 60 chars),
    does not end mid-sentence (no period at end), and is not empty.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 60:
        return False
    # Headings typically don't end with punctuation that closes a sentence
    if stripped.endswith((".", "!", "?")):
        return False
    return True


def _match_section(line: str, patterns: list[tuple[str, str]]) -> str | None:
    """Return the section_type label for the first pattern that matches line."""
    lower = line.lower()
    for pattern, label in patterns:
        if re.search(pattern, lower):
            return label
    return None


def _split_into_sections(
    text: str,
    patterns: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """
    Walk the text line by line, detect section headings, and collect text
    under each heading.

    Returns a list of (section_type, text) tuples. Text that appears before
    any recognised heading is tagged as "general".
    """
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_section = "general"
    current_lines: list[str] = []

    for line in lines:
        if _is_heading_line(line):
            matched = _match_section(line, patterns)
            if matched:
                # Save accumulated text under current section
                if current_lines:
                    sections.append((current_section, "\n".join(current_lines)))
                    current_lines = []
                current_section = matched
                # Don't add the heading line itself as content — it's metadata
                continue

        current_lines.append(line)

    # Flush remaining lines
    if current_lines:
        sections.append((current_section, "\n".join(current_lines)))

    # If nothing was split (no headings detected), the whole text is "general"
    if not sections:
        sections = [("general", text)]

    return sections
