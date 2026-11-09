import re
import pymupdf
from psycopg.types.json import Jsonb
from app.chunking import clean, sections, standard
from app.db import get_connection
from app.drive import connect, download, list_files
from app.extract import extract_pdf
from config import DRIVE_FOLDER_ID, MAX_FAR_RIGHT_SHARE, REQUIRED_SECTIONS, cv_file

SAVE_DOCUMENT = """
    INSERT INTO documents (drive_file_id, title, filename, content_hash, status, reasons, metadata)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (drive_file_id) DO UPDATE
    SET title = EXCLUDED.title,
        field_id = NULL,
        filename = EXCLUDED.filename,
        content_hash = EXCLUDED.content_hash,
        status = EXCLUDED.status,
        reasons = EXCLUDED.reasons,
        metadata = EXCLUDED.metadata,
        updated_at = now()
    RETURNING id
"""


def candidate_name(pages):
    """The CV's first line, if it looks like a name: 2 to 5 words, letters only."""
    first_line = clean(pages[0]["text"]).splitlines()[0]
    words = first_line.split()
    if 2 <= len(words) <= 5 and all(word.isalpha() for word in words):
        return first_line
    return None


def missing_sections(pages):
    """The required sections the CV doesn't have."""
    found = []
    for page in pages:
        for line in clean(page["text"]).splitlines():
            name = standard(line)        # the standard name if the whole line is a heading, else None
            if name:
                found.append(name)

    missing = []
    for section in REQUIRED_SECTIONS:
        if section not in found:
            missing.append(section)
    return missing


def experience_has_dates(pages):
    """True if the work experience section has a year in it (any date format)."""
    current = None                                   # the section we are in now
    for page in pages:
        for line in clean(page["text"]).splitlines():
            name = standard(line)
            if name:
                current = name                       # a heading: a new section starts here
            elif current == "WORK EXPERIENCE" and re.search(r"\b(19|20)\d{2}\b", line):
                return True                          # a year inside work experience
    return False


def has_table_or_columns(pdf_path):
    """True if a page has a table, or too many of its lines start far from the left margin (two columns)."""
    with pymupdf.open(pdf_path) as pdf:
        for page in pdf:
            if page.find_tables().tables:
                return True
 
            lefts = []                               # where each line starts, from the page's left edge
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    lefts.append(line["bbox"][0])
 
            far_right = 0
            for left in lefts:
                if left > page.rect.width / 3:       # starts after the first third of the page
                    far_right += 1
 
            if lefts and far_right / len(lefts) > MAX_FAR_RIGHT_SHARE:
                return True
    return False


def template_problems(pages, pdf_path):
    """The ATS problems in a readable CV, as reasons for the admin."""
    reasons = []
    if not candidate_name(pages):
        reasons.append("Name not found on the first line")
    missing = missing_sections(pages)
    for section in missing:
        reasons.append(f"Missing section: {section}")
    if "WORK EXPERIENCE" not in missing and not experience_has_dates(pages):
        reasons.append("No dates in the experience section")
    if has_table_or_columns(pdf_path):
        reasons.append("Table or two-column layout")
    return reasons
 
 
# ---------- the steps for one Drive file ----------
  
def unchanged(conn, drive_file_id, content_hash):
    """True if this Drive file is already saved with the same content."""
    row = conn.execute("SELECT content_hash FROM documents WHERE drive_file_id = %s", (drive_file_id,)).fetchone()
    return row is not None and row[0] == content_hash

 
def check_cv(conn, drive, item, content_hash):
    """Download the CV, read it and list its problems. Returns title, status, reasons, page_count."""
    # 1. A duplicate of a CV we already have? -> failed, without downloading it
    duplicate = conn.execute("SELECT filename, title FROM documents WHERE content_hash = %s AND drive_file_id <> %s",
                             (content_hash, item["id"])).fetchone()
    if duplicate:
        return duplicate[1], "failed", [f"Duplicate of {duplicate[0]}"], 0

    # 2. Download it
    file = cv_file(item["id"], item["name"])
    download(drive, item, file)

    # 3. Read it -> failed if it can't be read (not a PDF, password, no text, broken, too big)
    try:
        pages = extract_pdf(file, "pymupdf")
    except Exception as error:
        return file.stem, "failed", [str(error)], 0

    # 4. Check the ATS template -> processing, with the problems found
    title = candidate_name(pages) or file.stem
    return title, "processing", template_problems(pages, file), len(pages)


# ---------- every file in the Drive folder ----------

with get_connection() as conn:
    drive = connect()
    for item in list_files(drive, DRIVE_FOLDER_ID):
        drive_file_id, filename = item["id"], item["name"]
        content_hash = item.get("md5Checksum") or item["modifiedTime"]   # Drive's fingerprint of the content

        if unchanged(conn, drive_file_id, content_hash):
            continue                   # same file, same content

        title, status, reasons, page_count = check_cv(conn, drive, item, content_hash)

        with conn.transaction():
            document_id = conn.execute(SAVE_DOCUMENT, (drive_file_id, title, filename, content_hash, status,
                                                       reasons, Jsonb({"page_count": page_count}))).fetchone()[0]
            conn.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))   # old chunks no longer match

        print(f"{filename} -> {title} | {status} {reasons}")