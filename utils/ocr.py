# utils/ocr.py
# Extracts raw text from electricity bill images and PDFs.
# Strategy:
#   1. For PDFs → Try digital extraction using pdfminer.six first.
#   2. If digital extraction fails or text is too short → fallback to OCR.
#   3. For images → Use Tesseract OCR directly.
#
# FIX (alongside extractor.py fix):
#   _clean_text() now preserves blank lines between sections so that the
#   extractor's MULTILINE anchors (^, $) correctly scope each line and avoid
#   cross-line false-positive matches (e.g. a table header "units" on one line
#   bleeding into the number on the next line).

import os
import logging
import io

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tesseract Setup
# ---------------------------------------------------------------------------
try:
    import pytesseract
    from PIL import Image

    tesseract_cmd = os.environ.get(
        "TESSERACT_CMD",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract / Pillow not installed — OCR unavailable.")

# ---------------------------------------------------------------------------
# PDF2IMAGE Setup (OCR fallback for PDFs)
# ---------------------------------------------------------------------------
try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not installed — PDF OCR fallback unavailable.")

# ---------------------------------------------------------------------------
# PDFMINER Setup (Digital PDF extraction)
# ---------------------------------------------------------------------------
try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
    PDFMINER_AVAILABLE = True
except ImportError:
    PDFMINER_AVAILABLE = False
    logger.warning("pdfminer.six not installed — digital PDF extraction unavailable.")


# ---------------------------------------------------------------------------
# IMAGE OCR
# ---------------------------------------------------------------------------

def extract_text_from_image(file_bytes: bytes) -> str:
    """
    Run Tesseract OCR on a raw image file and return cleaned text.

    Args:
        file_bytes: Raw bytes of the image file.

    Returns:
        Cleaned, lowercased OCR text.

    Raises:
        RuntimeError: If pytesseract/Pillow is not installed or OCR fails.
    """
    if not TESSERACT_AVAILABLE:
        raise RuntimeError("pytesseract / Pillow not installed.")

    try:
        image = Image.open(io.BytesIO(file_bytes))
        image = image.convert("RGB")
        raw_text = pytesseract.image_to_string(image, lang="eng")
        return _clean_text(raw_text)
    except Exception as exc:
        raise RuntimeError(f"OCR failed on image: {exc}") from exc


# ---------------------------------------------------------------------------
# DIGITAL PDF EXTRACTION (Primary)
# ---------------------------------------------------------------------------

def extract_text_from_pdf_digital(file_bytes: bytes) -> str | None:
    """
    Try extracting embedded text from a PDF using pdfminer.

    Returns cleaned text, or None if extraction fails or the text is too short
    (indicating a scanned / image-only PDF that needs OCR instead).

    Args:
        file_bytes: Raw bytes of the PDF file.

    Returns:
        Cleaned text string, or None.
    """
    if not PDFMINER_AVAILABLE:
        return None

    try:
        text = pdfminer_extract_text(io.BytesIO(file_bytes))
        cleaned = _clean_text(text)

        # If text is too short, likely a scanned PDF → fallback to OCR
        if len(cleaned) < 30:
            logger.info("Digital PDF text too short (%d chars) — will try OCR.", len(cleaned))
            return None

        logger.info("Digital PDF text extraction successful (%d chars).", len(cleaned))
        return cleaned

    except Exception as exc:
        logger.warning("Digital PDF extraction failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# OCR FALLBACK FOR PDF
# ---------------------------------------------------------------------------

def extract_text_from_pdf_ocr(file_bytes: bytes) -> str:
    """
    Convert a PDF to images page-by-page and run Tesseract OCR on each page.
    Used as a fallback when digital text extraction fails (scanned PDFs).

    Args:
        file_bytes: Raw bytes of the PDF file.

    Returns:
        Cleaned, lowercased OCR text concatenated from all pages.

    Raises:
        RuntimeError: If pdf2image or pytesseract is not installed, or if
                      conversion/OCR fails on all pages.
    """
    if not PDF2IMAGE_AVAILABLE:
        raise RuntimeError(
            "pdf2image not installed. Run: pip install pdf2image (and install Poppler)."
        )
    if not TESSERACT_AVAILABLE:
        raise RuntimeError("pytesseract / Pillow not installed.")

    try:
        pages = convert_from_bytes(file_bytes, dpi=200)
    except Exception as exc:
        raise RuntimeError(f"PDF to image conversion failed: {exc}") from exc

    all_text = []

    for page_number, page_image in enumerate(pages, start=1):
        try:
            page_text = pytesseract.image_to_string(page_image, lang="eng")
            all_text.append(page_text)
        except Exception as exc:
            logger.warning("OCR failed on page %d: %s", page_number, exc)

    if not all_text:
        raise RuntimeError("OCR produced no text from any page of the PDF.")

    logger.info("PDF OCR fallback used (%d pages processed).", len(all_text))
    return _clean_text("\n".join(all_text))


# ---------------------------------------------------------------------------
# MAIN DISPATCH FUNCTION
# ---------------------------------------------------------------------------

def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = os.path.splitext(filename.lower())[1]

    if ext == ".pdf":
        digital_text = extract_text_from_pdf_digital(file_bytes)
        if digital_text:
            return digital_text

        raise RuntimeError(
            "Scanned PDFs are not supported in cloud deployment. "
            "Please upload a digital electricity bill PDF."
        )

    elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"):
        return extract_text_from_image(file_bytes)

    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            "Supported types: PDF, JPG, JPEG, PNG, BMP, TIFF, WEBP"
        )
    
# ---------------------------------------------------------------------------
# TEXT CLEANING
# ---------------------------------------------------------------------------

def _clean_text(raw: str) -> str:
    """
    Normalize OCR/pdfminer output for reliable regex matching in extractor.py.

    Processing steps:
      1. Split into lines.
      2. Strip leading/trailing whitespace from each line.
      3. Collapse internal runs of whitespace (tabs, multiple spaces) to a
         single space — preserves single-line readability without merging
         distinct fields that were on separate lines.
      4. Lowercase everything for case-insensitive matching.
      5. Drop completely empty lines to avoid spurious blank matches,
         BUT preserve single blank lines that separate bill sections
         (important for MULTILINE regex anchors in the extractor).

    NOTE: We deliberately do NOT join all lines into one string, because
    many extractor patterns use ^ and $ anchors (re.MULTILINE) to scope
    matches to individual lines, preventing cross-line false positives such
    as a "units" header on one line matching a number on the next line.
    """
    lines = []
    prev_blank = False

    for line in raw.splitlines():
        cleaned = " ".join(line.split()).lower()  # collapse whitespace + lowercase

        if cleaned:
            lines.append(cleaned)
            prev_blank = False
        else:
            # Allow at most one consecutive blank line (section separator)
            if not prev_blank:
                lines.append("")
            prev_blank = True

    # Strip leading/trailing blank lines from the whole output
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)