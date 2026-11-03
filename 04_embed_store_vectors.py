import json
from psycopg.types.json import Jsonb
from app.chunking import cosine
from app.db import get_connection
from app.embedding import embed, BATCH_SIZE
from config import MIN_FIELD_GAP, MIN_FIELD_SCORE, OTHER_FIELDS

# The average vector of each new CV whose chunks all have a vector (selected combination)
NEW_CVS = """
    SELECT d.id, d.title, d.reasons, avg(c.embedding)::text
    FROM documents d
    JOIN document_chunks c ON c.document_id = d.id AND c.level != 'parent'
    JOIN combinations k ON k.id = c.combination_id AND k.selected
    WHERE d.status = 'processing'
    GROUP BY d.id
    HAVING count(*) = count(c.embedding)
"""

SAVE_DECISION = """
    UPDATE documents
    SET field_id = (SELECT id FROM fields WHERE field_name = %s),
        status = %s, reasons = %s, metadata = metadata || %s, updated_at = now()
    WHERE id = %s
"""

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

    # ---------- the field of each new CV, then ready or needs review ----------

    new_cvs = conn.execute(NEW_CVS).fetchall()
    if not new_cvs:                # nothing to decide: don't embed the field descriptions for nothing
        print("no new CVs")
        raise SystemExit

    hiring = dict(conn.execute("SELECT field_name, description FROM fields").fetchall())
    descriptions = hiring | OTHER_FIELDS                      # the 5 fields we hire for + the 7 we don't
    field_vectors = dict(zip(descriptions, embed(list(descriptions.values()), kind="query")))

    for document_id, title, reasons, cv_vector in new_cvs:
        cv_vector = json.loads(cv_vector)
        scores = {field: cosine(cv_vector, vector) for field, vector in field_vectors.items()}
        closest, second = sorted(scores, key=scores.get, reverse=True)[:2]
        score = scores[closest]
        gap = score - scores[second]

        if closest in OTHER_FIELDS:
            problem = f"Closest to a field we don't hire for: {closest}"
        elif score < MIN_FIELD_SCORE:
            problem = "Far from all fields"
        elif gap < MIN_FIELD_GAP:
            problem = f"Between two fields: {closest} / {second}"
        else:
            problem = None

        if problem:
            reasons.append(problem)
        field = None if problem else closest
        status = "needs_review" if reasons else "ready"
        guess = {"closest": closest, "score": round(score, 3), "second": second, "gap": round(gap, 3)}

        conn.execute(SAVE_DECISION, (field, status, reasons, Jsonb(guess), document_id))
        print(f"{title} -> {field} | {status} {reasons}")

    print("done")