import json
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from config import BASE_DIR
import time
from google.genai import errors

MAX_RETRIES = 5

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

MODEL_NAME = os.environ["EMBEDDING_MODEL"]
DIMENSIONS = int(os.environ["EMBEDDING_DIMENSIONS"])
BATCH_SIZE = 32

# Saved vectors, so the same text is never sent to Gemini twice.
CACHE_FILE = BASE_DIR / "data" / f"embeddings_{MODEL_NAME}_{DIMENSIONS}.json"
cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}


def call_gemini(texts):
    for attempt in range(MAX_RETRIES):
        try:
            result = client.models.embed_content(
                model=MODEL_NAME,
                contents=[types.Content(parts=[types.Part.from_text(text=t)]) for t in texts],
                config=types.EmbedContentConfig(output_dimensionality=DIMENSIONS),
            )
            return [e.values for e in result.embeddings]   
        except errors.ClientError as e:
            if e.code != 429 or attempt == MAX_RETRIES - 1:
                raise
            print("Gemini limit reached, waiting 60 seconds...")
            time.sleep(60)

def embed(texts, kind="document"):
    """kind="document" for CV chunks, kind="query" for questions."""
    if kind == "document":
        texts = ["title: none | text: " + t for t in texts]
    else:
        texts = ["task: search result | query: " + t for t in texts]

    new_texts = [t for t in texts if t not in cache]

    for start in range(0, len(new_texts), BATCH_SIZE):
        batch = new_texts[start:start + BATCH_SIZE]
        vectors = call_gemini(batch)
        for text, vector in zip(batch, vectors):
            cache[text] = vector
        CACHE_FILE.write_text(json.dumps(cache))

    return [cache[t] for t in texts]