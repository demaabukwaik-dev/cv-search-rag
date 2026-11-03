import hashlib
from pathlib import Path
import pymupdf
from config import EXTRACTED_DIR
from llama_cloud import LlamaCloud  


MAX_PDF_BYTES = 20 * 1024 * 1024  
PAGE_MARK = "===== Page "


def check_pdf(pdf_path: Path):
    if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
        raise ValueError("Provide an existing .pdf file")
    if pdf_path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the 20 MB size limit")
    with pymupdf.open(pdf_path) as pdf:
        if pdf.needs_pass:
            raise ValueError("Password-protected PDF is not supported")


def read_pdf_pymupdf(pdf_path: Path):
    pages = []
    with pymupdf.open(pdf_path) as pdf:
        for i, page in enumerate(pdf):
            blocks = page.get_text("blocks", sort=True)
            paragraphs = []
            for b in blocks:
                if len(b) > 6 and b[6] == 0 and b[4].strip():   
                    paragraphs.append(b[4].strip())             
            text = "\n\n".join(paragraphs)
            if text:
                pages.append({"page_number": i + 1, "text": text})
    return pages


def read_pdf_llamaparse(pdf_path: Path):

    client = LlamaCloud()
    file = client.files.create(file=str(pdf_path), purpose="parse")
    result = client.parsing.parse(file_id=file.id, tier="agentic",
                                  version="latest", expand=["markdown"])
    pages = []
    for page in result.markdown.pages:
        if not page.success:
            continue
        text = "\n\n".join(part for part in (page.header, page.markdown) if part).strip()
        if text:
            pages.append({"page_number": page.page_number, "text": text})
    return pages


def extract_pdf(pdf_path: Path, extractor: str):
    """Return the pages, from the text cache when this exact file was already extracted."""
    pdf_path = Path(pdf_path)
    check_pdf(pdf_path)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    cache = EXTRACTED_DIR / extractor / f"{pdf_path.stem}-{digest}.txt"

    if cache.exists():
        pages = []
        for part in cache.read_text(encoding="utf-8").split(PAGE_MARK)[1:]:
            number, text = part.split(" =====\n", 1)
            pages.append({"page_number": int(number), "text": text.strip()})
        return pages

    pages = read_pdf_pymupdf(pdf_path) if extractor == "pymupdf" else read_pdf_llamaparse(pdf_path)
    if not pages:
        raise ValueError("No extractable text. This PDF may require OCR")

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n\n".join(f"{PAGE_MARK}{p['page_number']} =====\n{p['text']}" for p in pages),
                     encoding="utf-8")
    return pages

