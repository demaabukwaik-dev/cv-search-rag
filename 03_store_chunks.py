"""Step 3: chunk every CV that has no chunks yet, with the selected combination."""
import os
import yaml
from psycopg.types.json import Jsonb
from app.chunking import SETTINGS, chunk_pages
from app.db import get_connection
from app.extract import extract_pdf
from config import BASE_DIR, cv_file

# The combination chosen in the 16-combination comparison: new CVs are chunked with it only
review = yaml.safe_load((BASE_DIR / "data" / "manual_review.yaml").read_text(encoding="utf-8"))
for entry in review:
    if entry["selected"]:
        selected = entry


def save_combination(conn, entry):
    """Save the combination and its settings. If the settings changed, delete its old chunks."""
    settings = SETTINGS[entry["strategy"]] | {
        "embedding_model": os.environ["EMBEDDING_MODEL"],
        "dimensions": int(os.environ["EMBEDDING_DIMENSIONS"]),
    }

    with conn.transaction():
        old = conn.execute("SELECT settings FROM combinations WHERE extractor = %s AND strategy = %s",
                           (entry["extractor"], entry["strategy"])).fetchone()

        combination_id = conn.execute("""
            INSERT INTO combinations (extractor, strategy, settings, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (extractor, strategy) DO UPDATE
            SET settings = EXCLUDED.settings, notes = EXCLUDED.notes
            RETURNING id
        """, (entry["extractor"], entry["strategy"], Jsonb(settings), entry["notes"])).fetchone()[0]

        if old and old[0] != settings:     # settings changed: old chunks are wrong now
            conn.execute("DELETE FROM document_chunks WHERE combination_id = %s", (combination_id,))

    return combination_id


def already_saved(conn, document_id, combination_id):
    """True if this CV already has chunks for this combination."""
    row = conn.execute("""
        SELECT 1 FROM document_chunks
        WHERE document_id = %s AND combination_id = %s
        LIMIT 1
    """, (document_id, combination_id)).fetchone()
    return row is not None


def save_chunks(conn, document_id, combination_id, chunks):
    """Save all chunks of one CV in one transaction: all of them, or none."""
    with conn.transaction():
        saved_ids = []
        for chunk in chunks:
            # hierarchical: a child points to its parent, which was saved before it
            if chunk["parent"] is None:
                parent_id = None                          # not a child
            else:
                parent_id = saved_ids[chunk["parent"]]    # the parent's id in the database

            new_id = conn.execute("""
                INSERT INTO document_chunks
                    (document_id, combination_id, chunk_index, level, parent_id, content, token_count, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (document_id, combination_id, chunk["chunk_index"], chunk["level"], parent_id,
                  chunk["content"], chunk["token_count"],
                  Jsonb({"page": chunk["page"], "section": chunk["section"]}))).fetchone()[0]
            saved_ids.append(new_id)


with get_connection() as conn:
    extractor, strategy = selected["extractor"], selected["strategy"]
    combination_id = save_combination(conn, selected)

    # Mark it as the selected one: unselect all, then select it, in one step so search never sees none selected
    with conn.transaction():
        conn.execute("UPDATE combinations SET selected = FALSE")
        conn.execute("UPDATE combinations SET selected = TRUE WHERE id = %s", (combination_id,))

    # failed files can't be read, and rejected ones are not needed
    documents = conn.execute("""SELECT id, drive_file_id, filename FROM documents
                                WHERE status NOT IN ('failed', 'rejected')""").fetchall()

    for document_id, drive_file_id, filename in documents:
        if already_saved(conn, document_id, combination_id):
            continue
        pages = extract_pdf(cv_file(drive_file_id, filename), extractor)
        chunks = chunk_pages(pages, strategy, extractor)
        save_chunks(conn, document_id, combination_id, chunks)
        print(f"{filename}: {len(chunks)} chunks")

    print(f"{extractor} / {strategy}: done")