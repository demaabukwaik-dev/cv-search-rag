import shutil
from app.db import get_connection
from config import BASE_DIR

OUT_DIR = BASE_DIR / "data" / "chunks_review"
shutil.rmtree(OUT_DIR, ignore_errors=True)        # remove the old files first
OUT_DIR.mkdir(parents=True, exist_ok=True)

with get_connection() as conn:
    rows = conn.execute("""
        SELECT cb.id, cb.extractor, cb.strategy, d.title, c.chunk_index, c.level,
               c.metadata->>'section', c.token_count, c.content
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        JOIN combinations cb ON cb.id = c.combination_id
        ORDER BY cb.id, d.filename, c.chunk_index
    """).fetchall()

files = {}
for combo_id, extractor, strategy, title, index, level, section, tokens, content in rows:
    name = f"{combo_id:02d}_{extractor}_{strategy}.txt"
    files.setdefault(name, []).append(f"--- {title} | chunk {index} | {level} | {section} | {tokens} tokens ---\n{content}\n")

for name, chunks in files.items():
    (OUT_DIR / name).write_text("\n".join(chunks), encoding="utf-8")
    print(f"{name}: {len(chunks)} chunks")