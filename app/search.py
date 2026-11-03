"""Search: the request as it is becomes a vector, and one SQL query finds the closest candidates."""
from psycopg.rows import dict_row

from app.db import get_connection
from app.embedding import embed

# each candidate scored by their closest chunk, among the CVs this user may see and the fields they chose
SQL = """
    SELECT d.id AS document_id,
           d.title,
           d.filename,
           d.drive_file_id,
           f.field_name AS field,
           MIN(c.embedding <=> %(vector)s::vector) AS distance

    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id
    JOIN fields f ON f.id = d.field_id

    WHERE c.combination_id = (SELECT id FROM combinations WHERE selected)
      AND c.embedding IS NOT NULL
      AND d.status = 'ready'

      AND ((SELECT role FROM users WHERE id = %(user_id)s) = 'admin'
           OR d.field_id IN (SELECT field_id FROM user_fields WHERE user_id = %(user_id)s))

      AND f.field_name = ANY(%(fields)s)

    GROUP BY d.id, d.title, d.filename, d.drive_file_id, f.field_name
    ORDER BY distance
    LIMIT %(limit)s
"""


def search(question, user_id, fields, limit=5, on_step=lambda text: None):
    """The closest candidates to the request, as it is: no call to read it first."""
    on_step("Searching the CVs by meaning...")
    vector = embed([question], kind="query")[0]
    params = {"vector": str(vector), "user_id": user_id, "fields": list(fields), "limit": limit}
    with get_connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute(SQL, params)
        return cursor.fetchall()
