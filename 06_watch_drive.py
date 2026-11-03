import subprocess
import sys
import time

STEPS = ["02_store_documents.py", "03_store_chunks.py", "04_embed_store_vectors.py"]

while True:
    for step in STEPS:
        subprocess.run([sys.executable, step], check=True)   
    time.sleep(60)