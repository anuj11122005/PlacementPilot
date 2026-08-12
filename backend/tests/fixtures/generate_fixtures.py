"""
Fixture generator for PlacementPilot Phase 1 tests.

Run this script once to produce test fixture files in the same directory:

    cd backend
    python tests/fixtures/generate_fixtures.py

Why a script instead of committed binaries?
- Binary fixtures can silently corrupt during git operations (line ending
  conversions, etc.).
- A script is self-documenting: it is obvious exactly what each fixture
  contains, which makes the tests easier to understand and maintain.
- Fixtures can be regenerated after dependency updates without needing to
  re-export files manually.

Generated files (all written to the same directory as this script):
    empty.pdf          — 0-page PDF (pdfplumber opens it, yields no text)
    image_only.pdf     — Single-page PDF whose only content is an embedded
                         JPEG image (no text layer)
    malformed.docx     — Deliberately truncated/invalid DOCX (not a valid
                         ZIP file) to trigger python-docx PackageNotFoundError
    valid_resume.pdf   — Single-page PDF with realistic resume text
    valid_resume.docx  — DOCX with realistic resume paragraphs
"""

from __future__ import annotations

import struct
import textwrap
import zlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers: minimal PDF construction
# ---------------------------------------------------------------------------
# We build PDFs by hand using the PDF specification's object/xref format.
# This avoids a dependency on reportlab/fpdf2 (not in Phase 1 requirements)
# and makes it clear exactly what each fixture contains.


def _pdf_bytes(pages: list[str]) -> bytes:
    """
    Build a minimal valid PDF with the given list of page content streams.

    Each item in `pages` is a raw PDF content-stream string (e.g. BT ... ET).
    An empty list produces a 0-page PDF.
    """
    objects: list[bytes] = []
    offsets: list[int] = []

    def add_object(obj_bytes: bytes) -> int:
        """Append an object and return its 1-based object number."""
        obj_num = len(objects) + 1
        objects.append(obj_bytes)
        return obj_num

    # We'll fill in cross-reference offsets after assembling all objects.
    # First pass: build objects, track them.

    page_object_nums: list[int] = []
    content_object_nums: list[int] = []

    for content_stream in pages:
        stream_bytes = content_stream.encode("latin-1")
        content_obj_num = add_object(b"")  # placeholder
        content_object_nums.append(content_obj_num)
        page_obj_num = add_object(b"")  # placeholder
        page_object_nums.append(page_obj_num)

    pages_obj_num = add_object(b"")  # placeholder for Pages dict
    catalog_obj_num = add_object(b"")  # placeholder for Catalog

    # Rebuild with real object numbers
    objects.clear()
    content_object_nums.clear()
    page_object_nums.clear()

    counter = [1]  # mutable counter for object numbers

    def make_obj(body: bytes) -> tuple[int, bytes]:
        n = counter[0]
        counter[0] += 1
        full = f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
        return n, full

    rendered: list[bytes] = []

    page_refs: list[str] = []

    content_nums_local: list[int] = []
    page_nums_local: list[int] = []

    for content_stream in pages:
        stream_bytes = content_stream.encode("latin-1")
        stream_len = len(stream_bytes)
        content_body = (
            f"<< /Length {stream_len} >>\nstream\n".encode()
            + stream_bytes
            + b"\nendstream"
        )
        cn, content_rendered = make_obj(content_body)
        content_nums_local.append(cn)
        rendered.append(content_rendered)

        page_body = (
            f"<< /Type /Page /Parent 0 0 R /Contents {cn} 0 R "
            f"/MediaBox [0 0 612 792] >>".encode()
        )
        pn, page_rendered = make_obj(page_body)
        page_nums_local.append(pn)
        page_refs.append(f"{pn} 0 R")
        rendered.append(page_rendered)

    kids_str = " ".join(page_refs)
    pages_body = (
        f"<< /Type /Pages /Kids [{kids_str}] /Count {len(pages)} >>".encode()
    )
    pages_num, pages_rendered = make_obj(pages_body)
    rendered.append(pages_rendered)

    # Patch page objects to reference the real Pages parent
    for i, pn in enumerate(page_nums_local):
        old = rendered[2 * i + 1]
        new = old.replace(b"0 0 R", f"{pages_num} 0 R".encode(), 1)
        rendered[2 * i + 1] = new

    catalog_body = f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode()
    catalog_num, catalog_rendered = make_obj(catalog_body)
    rendered.append(catalog_rendered)

    # Assemble the file and compute xref offsets
    header = b"%PDF-1.4\n"
    body_parts = [header]
    offsets_map: dict[int, int] = {}
    pos = len(header)

    for obj_bytes in rendered:
        obj_num = int(obj_bytes.split(b" ")[0])
        offsets_map[obj_num] = pos
        body_parts.append(obj_bytes)
        pos += len(obj_bytes)

    total_objects = counter[0] - 1
    xref_offset = pos
    xref_lines = [f"xref\n0 {total_objects + 1}\n".encode()]
    xref_lines.append(b"0000000000 65535 f \n")
    for n in range(1, total_objects + 1):
        off = offsets_map.get(n, 0)
        xref_lines.append(f"{off:010d} 00000 n \n".encode())

    trailer = (
        f"\ntrailer\n<< /Size {total_objects + 1} /Root {catalog_num} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()

    return b"".join(body_parts) + b"".join(xref_lines) + trailer


def _make_empty_pdf() -> bytes:
    """Produce a valid PDF with 0 pages (pdfplumber can open it, but yields no text)."""
    return _pdf_bytes([])


def _make_text_pdf(text: str) -> bytes:
    """Produce a single-page PDF with the given text rendered via PDF BT...ET operator."""
    # Encode text as a simple Tf / Tj sequence.
    # We use Helvetica (a standard PDF font) so no font embedding is needed.
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = (
        "BT\n"
        "/F1 12 Tf\n"
        "50 750 Td\n"
        f"({escaped}) Tj\n"
        "ET"
    )
    page_resources = "<< /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>"
    return _pdf_bytes_with_resources([content], page_resources)


def _pdf_bytes_with_resources(pages: list[str], resources: str) -> bytes:
    """Like _pdf_bytes but injects a /Resources dict into each page object."""
    raw = _pdf_bytes(pages)
    # Patch every page dict to include resources
    raw = raw.replace(
        b"/Type /Page /Parent",
        f"/Type /Page /Resources {resources} /Parent".encode(),
    )
    return raw


def _make_image_only_pdf() -> bytes:
    """
    Produce a single-page PDF whose only content is an embedded image
    (a tiny 2×2 white JPEG). No text operators are present so pdfplumber
    will extract zero text from it.
    """
    # Minimal JFIF JPEG: 2x2 white pixels
    jpeg_bytes = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00,
        0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
        0xFF, 0xDB, 0x00, 0x43, 0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05,
        0x08, 0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D,
        0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12, 0x13, 0x0F, 0x14, 0x1D, 0x1A,
        0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20,
        0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29, 0x2C, 0x30, 0x31,
        0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E,
        0x33, 0x34, 0x32,
        0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x02, 0x00, 0x02, 0x01, 0x01,
        0x11, 0x00,
        0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01, 0x01,
        0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B,
        0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03, 0x03, 0x02,
        0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D, 0x01,
        0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1,
        0x08, 0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33,
        0x62, 0x72, 0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25,
        0x26, 0x27, 0x28, 0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39,
        0x3A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54,
        0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x63, 0x64, 0x65, 0x66, 0x67,
        0x68, 0x69, 0x6A, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7A,
        0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x92, 0x93, 0x94,
        0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6,
        0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8,
        0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA,
        0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
        0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3,
        0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA,
        0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00,
        0xFB, 0xD2, 0x8A, 0x28, 0x03, 0xFF, 0xD9,
    ])

    jpeg_len = len(jpeg_bytes)
    # Build a PDF with an XObject image and a Do operator (no BT/ET text)
    # This is a simplified hand-rolled structure.
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100]"
        b" /Resources << /XObject << /Im1 4 0 R >> >>"
        b" /Contents 5 0 R >>\nendobj\n"
        + b"4 0 obj\n<< /Type /XObject /Subtype /Image /Width 2 /Height 2"
        + f" /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode /Length {jpeg_len} >>\nstream\n".encode()
        + jpeg_bytes
        + b"\nendstream\nendobj\n"
        b"5 0 obj\n<< /Length 32 >>\nstream\nq 100 0 0 100 0 0 cm /Im1 Do Q\nendstream\nendobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000266 00000 n \n"
        b"0000000000 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
    )
    return pdf


# ---------------------------------------------------------------------------
# Helpers: DOCX construction
# ---------------------------------------------------------------------------


def _make_valid_docx(paragraphs: list[str]) -> bytes:
    """
    Build a minimal valid DOCX (Office Open XML) in memory.
    A DOCX is a ZIP archive containing specific XML files.
    We construct it using the zipfile module — no dependency on python-docx
    here (that's a test subject, not a test tool).
    """
    import io
    import zipfile

    para_xml = ""
    for p in paragraphs:
        escaped = (
            p.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
        )
        para_xml += (
            f'<w:p><w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>\n'
        )

    # NOTE: XML declarations must start at position 0 — no leading whitespace.
    # We build each XML string with the declaration on the very first character.
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document'
        ' xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' mc:Ignorable="w14 wp14">\n'
        '  <w:body>\n'
        f'    {para_xml}'
        '  </w:body>\n'
        '</w:document>\n'
    )

    relationships_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1"\n'
        '    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"\n'
        '    Target="word/document.xml"/>\n'
        '</Relationships>\n'
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels"\n'
        '    ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/word/document.xml"\n'
        '    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        '</Types>\n'
    )

    word_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '</Relationships>\n'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", relationships_xml)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/_rels/document.xml.rels", word_rels_xml)
    return buf.getvalue()


def _make_malformed_docx() -> bytes:
    """
    Produce a file with a .docx extension that is NOT a valid ZIP archive.
    python-docx will raise PackageNotFoundError when it tries to open it.
    """
    return b"This is not a valid DOCX or ZIP file. \x00\x01\x02\xFF"


# ---------------------------------------------------------------------------
# Main — generate all fixtures
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent


def generate_all() -> None:
    fixtures = {
        "empty.pdf": _make_empty_pdf(),
        "image_only.pdf": _make_image_only_pdf(),
        "malformed.docx": _make_malformed_docx(),
        "valid_resume.pdf": _make_text_pdf(
            "John Doe  john.doe@email.com  555-1234\n"
            "Skills: Python, FastAPI, SQL, Docker\n"
            "Experience: Backend Engineer at Acme Corp 2021-2024\n"
            "Education: B.Sc. Computer Science, State University 2021"
        ),
        "valid_resume.docx": _make_valid_docx([
            "Jane Smith | jane@example.com | 555-5678",
            "Skills",
            "Python, Machine Learning, PyTorch, SQL",
            "Experience",
            "ML Engineer at TechCorp, 2022-2024",
            "Developed recommendation models serving 1M users.",
            "Education",
            "M.Sc. Data Science, City University, 2022",
        ]),
    }

    for filename, content in fixtures.items():
        dest = FIXTURE_DIR / filename
        dest.write_bytes(content)
        print(f"  Generated: {dest.name} ({len(content)} bytes)")

    print(f"\nAll fixtures written to: {FIXTURE_DIR}")


if __name__ == "__main__":
    generate_all()
