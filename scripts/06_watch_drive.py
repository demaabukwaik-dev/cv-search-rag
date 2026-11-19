import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
STEPS = ["02_store_documents.py", "03_store_chunks.py", "04_embed_store_vectors.py"]

while True:
    for step in STEPS:
        subprocess.run([sys.executable, str(SCRIPTS_DIR / step)], check=True)
    time.sleep(60)
