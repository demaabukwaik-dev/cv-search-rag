import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root, for app/ and config
from app.db import get_connection
from app.embedding import embed, BATCH_SIZE

# The average vector of each new CV whose chunks all have a vector (selected combination)
# Each new CV whose chunks all have a vector (selected combination)
NEW_CVS = """
    SELECT d.id, d.title, d.reasons
    FROM documents d
    JOIN document_chunks c ON c.document_id = d.id AND c.level != 'parent'
    JOIN combinations k ON k.id = c.combination_id AND k.selected
    WHERE d.status = 'processing'
    GROUP BY d.id
    HAVING count(*) = count(c.embedding)
"""

SAVE_STATUS = "UPDATE documents SET status = %s, updated_at = now() WHERE id = %s"

with get_connection() as conn:
    # only one run at a time: if another run holds the lock, leave
    if not conn.execute("SELECT pg_try_advisory_lock(hashtext('embed_vectors'))").fetchone()[0]:
        print("Another run is already embedding. Exiting.")
        raise SystemExit

    while True:
        # the next chunks without a vector
        rows = conn.execute("""
            SELECT id, content FROM document_chunks
            WHERE embedding IS NULL AND level != 'parent'
            ORDER BY id
            LIMIT %s
        """, (BATCH_SIZE,)).fetchall()
        if not rows:
            break

        ids = [row[0] for row in rows]
        texts = [row[1] for row in rows]
        vectors = embed(texts)

        with conn.transaction():
            for chunk_id, vector in zip(ids, vectors):
                conn.execute("UPDATE document_chunks SET embedding = %s::vector WHERE id = %s",
                             (str(vector), chunk_id))
        print(f"embedded {len(rows)} chunks")

    # ---------- each new CV: ready, or needs review if it has problems ----------

    for document_id, title, reasons in conn.execute(NEW_CVS).fetchall():
        status = "needs_review" if reasons else "ready"
        conn.execute(SAVE_STATUS, (status, document_id))
        print(f"{title} -> {status} {reasons}")

    print("done")

    