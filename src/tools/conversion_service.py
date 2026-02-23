"""Document conversion service — subprocess wrappers for LibreOffice, Pandoc, Calibre, Pillow."""

import asyncio
import io
import logging
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum input file size: 20 MB
MAX_INPUT_SIZE = 20 * 1024 * 1024

# Subprocess timeout: 120 seconds
CONVERSION_TIMEOUT = 120

# Lock for LibreOffice (not thread-safe — single-instance only)
_libreoffice_lock = asyncio.Lock()


class ConversionError(Exception):
    """Raised when document conversion fails."""


# ---------------------------------------------------------------------------
# MIME type → canonical extension
# ---------------------------------------------------------------------------
MIME_TO_EXT: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/plain": "txt",
    "text/csv": "csv",
    "text/html": "html",
    "text/markdown": "md",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
    "application/epub+zip": "epub",
    "application/x-mobipocket-ebook": "mobi",
    "application/x-fictionbook+xml": "fb2",
    "application/x-fictionbook": "fb2",
    "image/vnd.djvu": "djvu",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/tiff": "tiff",
}

# ---------------------------------------------------------------------------
# Supported conversion matrix: source_ext → set of target_exts
# ---------------------------------------------------------------------------
SUPPORTED_CONVERSIONS: dict[str, set[str]] = {
    # Office documents (LibreOffice)
    "pdf": {"docx", "txt", "html", "jpg", "png"},
    "docx": {"pdf", "txt", "html", "odt", "rtf", "md"},
    "doc": {"pdf", "docx", "txt", "html", "odt", "rtf"},
    "txt": {"pdf", "docx", "html", "md"},
    "rtf": {"pdf", "docx", "txt", "html", "odt"},
    "odt": {"pdf", "docx", "txt", "html", "rtf"},
    "html": {"pdf", "docx", "txt", "md"},
    # Spreadsheets (LibreOffice)
    "xlsx": {"pdf", "csv", "ods", "xls"},
    "xls": {"pdf", "csv", "ods", "xlsx"},
    "csv": {"pdf", "xlsx", "ods", "xls"},
    "ods": {"pdf", "csv", "xlsx", "xls"},
    # Presentations (LibreOffice)
    "pptx": {"pdf"},
    # E-books (Calibre)
    "epub": {"pdf", "mobi", "fb2", "txt", "html", "docx"},
    "fb2": {"pdf", "epub", "mobi", "txt", "html", "docx"},
    "mobi": {"pdf", "epub", "fb2", "txt", "html"},
    "djvu": {"pdf", "txt"},
    # Markdown (Pandoc)
    "md": {"pdf", "docx", "html", "txt"},
    # Images (Pillow + pypdfium2)
    "jpg": {"pdf", "png", "tiff"},
    "jpeg": {"pdf", "png", "tiff"},
    "png": {"pdf", "jpg", "tiff"},
    "tiff": {"pdf", "jpg", "png"},
}

EBOOK_FORMATS = {"epub", "fb2", "mobi", "djvu"}
IMAGE_FORMATS = {"jpg", "jpeg", "png", "tiff"}
PANDOC_PAIRS: set[tuple[str, str]] = {
    ("md", "docx"),
    ("md", "html"),
    ("md", "pdf"),
    ("md", "txt"),
    ("docx", "md"),
    ("html", "md"),
    ("txt", "md"),
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def detect_source_format(filename: str | None, mime_type: str | None) -> str | None:
    """Infer source extension from filename or MIME type."""
    if filename and "." in filename:
        ext = filename.rsplit(".", maxsplit=1)[-1].lower()
        if ext in SUPPORTED_CONVERSIONS or ext == "jpeg":
            return ext
    if mime_type:
        return MIME_TO_EXT.get(mime_type.split(";")[0].strip().lower())
    return None


def is_supported(source: str, target: str) -> bool:
    """Check if a (source, target) conversion pair is supported."""
    targets = SUPPORTED_CONVERSIONS.get(source, set())
    return target in targets


def get_supported_targets(source: str) -> set[str]:
    """Return the set of supported target formats for a given source."""
    return SUPPORTED_CONVERSIONS.get(source, set())


def _select_tool(source: str, target: str) -> str:
    """Determine which tool handles (source, target) conversion."""
    # Images → Pillow
    if source in IMAGE_FORMATS and target in (IMAGE_FORMATS | {"pdf"}):
        return "pillow"
    # PDF → images
    if source == "pdf" and target in IMAGE_FORMATS:
        return "pypdfium2"
    # E-books → Calibre
    if source in EBOOK_FORMATS or target in EBOOK_FORMATS:
        return "calibre"
    # Markdown pairs → Pandoc
    if (source, target) in PANDOC_PAIRS:
        return "pandoc"
    # Everything else → LibreOffice
    return "libreoffice"


def tool_available(tool: str) -> bool:
    """Check if a conversion tool binary is available on this system."""
    binaries = {
        "libreoffice": "libreoffice",
        "pandoc": "pandoc",
        "calibre": "ebook-convert",
        "pillow": None,  # Always available (Python lib)
        "pypdfium2": None,  # Always available (Python lib)
    }
    binary = binaries.get(tool)
    if binary is None:
        return True
    return shutil.which(binary) is not None


# ---------------------------------------------------------------------------
# Main conversion entry point
# ---------------------------------------------------------------------------
async def convert_document(
    input_bytes: bytes,
    source_ext: str,
    target_ext: str,
    filename: str,
) -> tuple[bytes, str]:
    """Convert document bytes from source format to target format.

    Returns (output_bytes, output_filename).
    Raises ConversionError on failure.
    """
    if not is_supported(source_ext, target_ext):
        raise ConversionError(f"Unsupported conversion: {source_ext} -> {target_ext}")

    tool = _select_tool(source_ext, target_ext)

    if not tool_available(tool):
        raise ConversionError(f"Conversion tool '{tool}' is not installed on this server")

    # Compute output filename
    base_name = filename.rsplit(".", maxsplit=1)[0] if "." in filename else filename
    output_filename = f"{base_name}.{target_ext}"

    # Pure-Python converters (no temp files needed)
    if tool == "pillow":
        out_bytes = await _convert_images(input_bytes, source_ext, target_ext)
        return out_bytes, output_filename

    if tool == "pypdfium2":
        out_bytes = await _pdf_to_images(input_bytes, target_ext)
        return out_bytes, output_filename

    # Subprocess-based converters (need temp files)
    tmp_dir = Path(tempfile.mkdtemp(prefix="conv_"))
    try:
        input_path = tmp_dir / f"input.{source_ext}"
        input_path.write_bytes(input_bytes)

        if tool == "libreoffice":
            out_path = await _convert_libreoffice(input_path, target_ext, tmp_dir)
        elif tool == "pandoc":
            out_path = tmp_dir / f"output.{target_ext}"
            out_path = await _convert_pandoc(input_path, target_ext, out_path)
        elif tool == "calibre":
            out_path = tmp_dir / f"output.{target_ext}"
            out_path = await _convert_calibre(input_path, target_ext, out_path)
        else:
            raise ConversionError(f"Unknown tool: {tool}")

        if not out_path.exists():
            raise ConversionError(f"Conversion produced no output file ({tool})")

        out_bytes = out_path.read_bytes()
        if not out_bytes:
            raise ConversionError("Conversion produced an empty file")

        return out_bytes, output_filename
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# LibreOffice headless
# ---------------------------------------------------------------------------
async def _convert_libreoffice(input_path: Path, target_ext: str, output_dir: Path) -> Path:
    """Convert via LibreOffice headless. Returns path to output file."""
    # LibreOffice filter map for specific conversions
    filter_map: dict[str, str] = {
        "csv": "Text - txt - csv (StarCalc)",
    }
    convert_arg = target_ext
    lo_filter = filter_map.get(target_ext)
    if lo_filter:
        convert_arg = f"{target_ext}:{lo_filter}"

    cmd = [
        "libreoffice",
        "--headless",
        "--norestore",
        "--convert-to",
        convert_arg,
        "--outdir",
        str(output_dir),
        str(input_path),
    ]

    async with _libreoffice_lock:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"HOME": str(output_dir)},  # Isolate user profile
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=CONVERSION_TIMEOUT
            )
        except TimeoutError:
            proc.kill()
            raise ConversionError("LibreOffice conversion timed out")

    if proc.returncode != 0:
        err_msg = stderr.decode(errors="replace")[:500] if stderr else "unknown error"
        raise ConversionError(f"LibreOffice error: {err_msg}")

    # LibreOffice names output as input_basename.target_ext
    expected = output_dir / f"{input_path.stem}.{target_ext}"
    if expected.exists():
        return expected

    # Fallback: find any file with target extension
    candidates = list(output_dir.glob(f"*.{target_ext}"))
    if candidates:
        return candidates[0]

    raise ConversionError(f"LibreOffice produced no .{target_ext} file")


# ---------------------------------------------------------------------------
# Pandoc
# ---------------------------------------------------------------------------
async def _convert_pandoc(input_path: Path, target_ext: str, output_path: Path) -> Path:
    """Convert via Pandoc. Returns path to output file."""
    cmd = ["pandoc", str(input_path), "-o", str(output_path)]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=CONVERSION_TIMEOUT
        )
    except TimeoutError:
        proc.kill()
        raise ConversionError("Pandoc conversion timed out")

    if proc.returncode != 0:
        err_msg = stderr.decode(errors="replace")[:500] if stderr else "unknown error"
        raise ConversionError(f"Pandoc error: {err_msg}")

    return output_path


# ---------------------------------------------------------------------------
# Calibre ebook-convert
# ---------------------------------------------------------------------------
async def _convert_calibre(input_path: Path, target_ext: str, output_path: Path) -> Path:
    """Convert via Calibre ebook-convert. Returns path to output file."""
    cmd = ["ebook-convert", str(input_path), str(output_path)]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=CONVERSION_TIMEOUT
        )
    except TimeoutError:
        proc.kill()
        raise ConversionError("Calibre conversion timed out")

    if proc.returncode != 0:
        err_msg = stderr.decode(errors="replace")[:500] if stderr else "unknown error"
        raise ConversionError(f"Calibre error: {err_msg}")

    return output_path


# ---------------------------------------------------------------------------
# Pillow: image ↔ image, image → PDF
# ---------------------------------------------------------------------------
async def _convert_images(
    input_bytes: bytes, source_ext: str, target_ext: str
) -> bytes:
    """Convert between image formats or image → PDF using Pillow."""
    from PIL import Image

    def _do_convert() -> bytes:
        img = Image.open(io.BytesIO(input_bytes))

        # Convert to RGB if saving as JPEG/PDF (no alpha channel)
        if target_ext in ("jpg", "jpeg", "pdf") and img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        buf = io.BytesIO()
        save_format = {
            "jpg": "JPEG",
            "jpeg": "JPEG",
            "png": "PNG",
            "tiff": "TIFF",
            "pdf": "PDF",
        }.get(target_ext, target_ext.upper())

        img.save(buf, format=save_format)
        return buf.getvalue()

    return await asyncio.to_thread(_do_convert)


# ---------------------------------------------------------------------------
# pypdfium2: PDF → image
# ---------------------------------------------------------------------------
async def _pdf_to_images(input_bytes: bytes, target_ext: str) -> bytes:
    """Render first page of PDF as an image using pypdfium2."""
    import pypdfium2 as pdfium

    def _do_render() -> bytes:
        pdf = pdfium.PdfDocument(input_bytes)
        page = pdf[0]
        # Render at 2x scale for good quality
        bitmap = page.render(scale=2)
        pil_image = bitmap.to_pil()

        if target_ext in ("jpg", "jpeg") and pil_image.mode in ("RGBA", "P", "LA"):
            pil_image = pil_image.convert("RGB")

        buf = io.BytesIO()
        save_format = {
            "jpg": "JPEG",
            "jpeg": "JPEG",
            "png": "PNG",
            "tiff": "TIFF",
        }.get(target_ext, "PNG")

        pil_image.save(buf, format=save_format)
        return buf.getvalue()

    return await asyncio.to_thread(_do_render)
