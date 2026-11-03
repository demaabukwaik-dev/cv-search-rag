import json
import re
import time
from google.genai import errors
from google.genai.local_tokenizer import LocalTokenizer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.embedding import client, MODEL_NAME
from config import BASE_DIR, SECTIONS

SETTINGS = {
    "fixed":        {"size_chars": 500, "overlap_chars": 75},
    "token":        {"size_tokens": 180, "overlap_tokens": 30},
    "recursive":    {"size_chars": 500, "overlap_chars": 75},
    "sentence":     {"max_tokens": 180},
    "section":      {"max_tokens": 180},
    "semantic":     {"threshold": 0.75, "max_tokens": 180},
    "hierarchical": {"child_tokens": 100},
    "layout":       {"max_tokens": 180},
}

NOISE = ["Synthetic CV for training/demo purposes"]

# The local tokenizer cuts the text, the API measures each piece.
tokenizer = LocalTokenizer(model_name="gemini-2.5-flash")._tokenizer

# Saved counts, so the same text is never sent twice.
COUNTS_FILE = BASE_DIR / "data" / f"token_counts_{MODEL_NAME}.json"
counts = json.loads(COUNTS_FILE.read_text()) if COUNTS_FILE.exists() else {}


def count_tokens(text):
    """Tokens as the embedding model counts them."""
    if text not in counts:
        for attempt in range(5):
            try:
                counts[text] = client.models.count_tokens(model=MODEL_NAME, contents=text).total_tokens
                break
            except errors.ClientError as e:
                if e.code != 429 or attempt == 4:
                    raise
                print("Gemini limit reached, waiting 60 seconds...")
                time.sleep(60)
    return counts[text]


def fit(text, max_tokens, head=""):
    """Cut a text into pieces of at most max_tokens with head on top: the local tokenizer cuts, the API checks."""
    ids = tokenizer.encode(text)
    out, start = [], 0
    while start < len(ids):
        end = min(start + max_tokens, len(ids))
        while count_tokens(head + tokenizer.decode(ids[start:end]).strip()) > max_tokens:
            end -= 1                                        # one token shorter until it fits
        out.append(tokenizer.decode(ids[start:end]).strip())
        start = end
    return out


def standard(line):
    """The standard section name if the line is a heading, else None. "## Skills" and "Skills:" work too."""
    line = line.strip("#: ").lower()
    for name, headings in SECTIONS.items():
        if line in headings:
            return name
    return None


def clean(text):
    for noise in NOISE:
        text = text.replace(noise, "")
    text = re.sub(r"</?u>|\*\*", "", text)          # LlamaParse markup
    return re.sub(r"[ \t]+", " ", text).strip()


def chunk(content, page, section=None, level="chunk", parent=None):
    return {"content": content, "page": page, "section": section, "level": level, "parent": parent}


def sentences(text):
    text = " ".join(text.split())                       # join lines: a sentence may span lines
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s]   # split only at . ! ?


def pack(units, max_tokens, sep="\n", head=""):
    """Join small units (sentences / lines / paragraphs) into chunks of up to max_tokens,
    counted with head (the section name) on top, as the chunk will be stored."""
    groups = []                                             # each item: one chunk's text
    for unit in units:
        if groups and count_tokens(head + groups[-1] + sep + unit) <= max_tokens:
            groups[-1] += sep + unit                        # still fits: add to the last chunk
        else:
            groups.append(unit)                             # first unit, or too big: start a new chunk

    # a single unit longer than max_tokens is cut into max_tokens pieces
    return [piece for group in groups
            for piece in (fit(group, max_tokens, head) if count_tokens(head + group) > max_tokens else [group])]

def sections(pages, extractor):
    """Split the CV into sections: [(page_number, section_name, text), ...]."""
    out = []                                            # each item: [page, name, lines]
    for page in pages:
        p = page["page_number"]
        lines = clean(page["text"]).splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            name = standard(line)
            if out and name:                            # a heading (the CV's first line never is)
                out.append([p, name, []])
            else:
                if not out or out[-1][0] != p:          # first line, or a new page: same section continues
                    out.append([p, out[-1][1] if out else "PROFILE", []])
                out[-1][2].append(line)
    return [(p, name, "\n".join(lines)) for p, name, lines in out if lines]


def titled(name, text):
    """Put the section name on top of the chunk, except for the CV's first section (Profile)."""
    return text if name == "PROFILE" else f"{name}\n{text}"


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))

# ---------- the 8 strategies ----------


def section(pages, s):
    out = []
    for page, name, text in sections(pages, s["extractor"]):   # one CV section at a time
        lines = text.split("\n")
        groups = pack(lines, s["max_tokens"], head=titled(name, ""))   # up to 180 tokens, the name included
        for group in groups:
            content = titled(name, group)                       # put the section name on top
            out.append(chunk(content, page, section=name))
    return out



def fixed(pages, s):
    size = s["size_chars"]                    # 500 characters per chunk
    overlap = s["overlap_chars"]              # 75 characters repeated
    step = size - overlap                     # move forward 425 each time

    out = []
    for page in pages:
        text = clean(page["text"])
        start = 0
        while start < max(len(text) - overlap, 1):
            piece = text[start : start + size]           # take 500 characters
            out.append(chunk(piece.strip(), page["page_number"]))
            start = start + step                         # jump 425 forward
    return out


def token(pages, s):
    size = s["size_tokens"]                   # 180 tokens per chunk
    overlap = s["overlap_tokens"]             # 30 tokens repeated

    out = []
    for page in pages:
        text = clean(page["text"])
        ids = tokenizer.encode(text)                      # text -> list of tokens
        start = 0
        while True:
            end = min(start + size, len(ids))             # take 180 tokens
            piece = tokenizer.decode(ids[start:end]).strip()
            while count_tokens(piece) > size:             # too long for the embedding model: one token shorter
                end -= 1
                piece = tokenizer.decode(ids[start:end]).strip()
            out.append(chunk(piece, page["page_number"]))
            if end == len(ids):                           # reached the end of the page
                break
            start = end - overlap                         # the last 30 tokens are repeated
    return out

def recursive(pages, s):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=s["size_chars"],          # 500 characters per chunk
        chunk_overlap=s["overlap_chars"],    # 75 characters repeated
    )

    out = []
    for page in pages:
        text = clean(page["text"])
        pieces = splitter.split_text(text)   # LangChain does the cutting
        for piece in pieces:
            out.append(chunk(piece, page["page_number"]))
    return out


def sentence(pages, s):
    out = []
    for page in pages:
        text = clean(page["text"])
        sents = sentences(text)                            # split into sentences
        groups = pack(sents, s["max_tokens"], sep="\n")     # join sentences up to 180 tokens
        for group in groups:
            out.append(chunk(group, page["page_number"]))
    return out


def semantic(pages, s):
    from app.embedding import embed
    out = []
    for p in pages:
        sents = sentences(clean(p["text"]))
        if not sents:
            continue
        vecs = embed(sents)
        group = [sents[0]]
        for i in range(1, len(sents)):
            similarity = cosine(vecs[i], vecs[i - 1])
            if similarity < s["threshold"]:   # topic changed: start a new chunk
                out += [chunk(t, p["page_number"]) for t in pack(group, s["max_tokens"], "\n")]
                group = []
            group.append(sents[i])
        out += [chunk(t, p["page_number"]) for t in pack(group, s["max_tokens"], "\n")]
    return out


def hierarchical(pages, s):
    out = []
    for page, name, text in sections(pages, s["extractor"]):
        out.append(chunk(titled(name, text), page, name, level="parent"))
        parent = len(out) - 1
        out += [chunk(titled(name, t), page, name, "child", parent)
                for t in pack(text.split("\n"), s["child_tokens"], head=titled(name, "")) if t]
    return out


def layout(pages, s):
    # Uses the extractor's own paragraph blocks (blank-line separated) as the units.
    return [chunk(t, p["page_number"]) for p in pages
            for t in pack([b for b in clean(p["text"]).split("\n\n") if b.strip()], s["max_tokens"], "\n\n")]


STRATEGIES = {name: fn for name, fn in globals().items() if name in SETTINGS}


def chunk_pages(pages, strategy, extractor):
    """Run one strategy on one extractor's pages; add chunk_index and token_count."""
    params = {**SETTINGS[strategy], "extractor": extractor}
    chunks = [c for c in STRATEGIES[strategy](pages, params) if c["content"]]
    for i, c in enumerate(chunks):
        c["chunk_index"] = i
        c["token_count"] = count_tokens(c["content"])     # the exact size, from the embedding model
    COUNTS_FILE.write_text(json.dumps(counts))
    return chunks