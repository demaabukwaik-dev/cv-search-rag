"""Evaluation: run every test case through the RAG, compare the answer with the expected one,
and save the results and the traces.

Run:  python 05_evaluate.py A        (A = a name for this run)
"""
import csv
import json
import sys
import time

from app.answer import answer, PRIVATE
import app.answer as rag
from app.db import get_connection
from config import BASE_DIR

RUN = sys.argv[1]
EVAL_DIR = BASE_DIR / "data" / "evaluation"
OUT = EVAL_DIR / "runs" / RUN
OUT.mkdir(parents=True, exist_ok=True)

CASES = json.loads((EVAL_DIR / "eval_cases.json").read_text(encoding="utf-8"))

COLUMNS = ["case", "type", "passed", "expected_full", "full", "partial", "message",
           "recall@5", "precision@5", "completeness", "ranking_ok", "safe", "no_contacts",
           "tokens_in", "tokens_out", "seconds"]


# ---------- the users who ask ----------

def get_user(case):
    """The admin, or a recruiter who may not see the field named in case["user_lacks"].
    Returns (user id, the fields this user may see)."""
    with get_connection() as conn:
        if "user_lacks" not in case:
            user_id = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()[0]
            rows = conn.execute("SELECT field_name FROM fields").fetchall()
        else:
            user_id = conn.execute("""
                SELECT id FROM users
                WHERE role = 'recruiter'
                  AND id NOT IN (SELECT uf.user_id FROM user_fields uf
                                 JOIN fields f ON f.id = uf.field_id
                                 WHERE f.field_name = %s)
                LIMIT 1""", (case["user_lacks"],)).fetchone()[0]
            rows = conn.execute("""
                SELECT f.field_name FROM user_fields uf
                JOIN fields f ON f.id = uf.field_id
                WHERE uf.user_id = %s""", (user_id,)).fetchall()
    return user_id, [r[0] for r in rows]


def ratio(part, whole):
    """3 out of 4 = 0.75. Empty when there is nothing to count."""
    if not whole:
        return ""
    return round(len(part) / len(whole), 2)


# ---------- run every case ----------

with get_connection() as conn:
    all_fields = [r[0] for r in conn.execute("SELECT field_name FROM fields").fetchall()]

rows = []
traces = []

for case in CASES:
    user_id, allowed = get_user(case)
    fields = case.get("fields", all_fields)   # every field is asked for: the database must still hide the rest

    # 1. ask the RAG
    error = None
    for attempt in range(3):                  # Gemini busy or slow: wait 30 s and try again, at most 3 times
        start = time.perf_counter()           # the clock starts again on every try, so the waiting is not counted
        try:
            conditions, candidates, excerpts, scores = answer(case["question"], user_id, fields)
            error = None
            break
        except Exception as e:
            error = e
            print(case["id"], "try", attempt + 1, "failed:", e)
            time.sleep(30)

    if error:                                 # no answer after 3 tries: this case fails, the run goes on
        print(case["id"], "ERROR", error)
        rows.append({"case": case["id"], "type": case["type"], "passed": False, "message": f"ERROR: {error}"})
        time.sleep(5)
        continue
    seconds = round(time.perf_counter() - start, 1)

    # 2. what came back
    retrieved = list(scores)                                   # the 5 CVs the search brought
    full = [c.name for c in candidates if c.fit == "full"]
    partial = [c.name for c in candidates if c.fit == "partial"]
    message = conditions.message or ""
    answer_text = message + " ".join(reason for c in candidates for reason in c.reasons)

    # 3. the metrics
    expected = case["expected_full"]
    found = [name for name in expected if name in retrieved]           # Retrieval
    shown = [name for name in expected if name in full]                # Completeness
    wrong = [name for name in case["not_full"] if name in full]        # Ranking
    safe = all(e["field"] in allowed for e in excerpts)                # Safety: only the user's fields
    no_contacts = not PRIVATE.search(answer_text)                      # Safety: no phone, email or link

    # 4. passed only if every check is right
    behavior = case["expected_behavior"]
    if behavior == "limit_note":       # only 5 CVs are checked: any of the expected ones may be shown
        right_full = all(name in expected for name in full)
    else:
        right_full = sorted(full) == sorted(expected)

    checks = {
        "right full candidates": right_full,
        "right partial candidates": all(name in partial for name in case["expected_partial"]),
        "safe": safe,
        "no contacts": no_contacts,
        "a message when one is needed": bool(message) or behavior not in ("clarify", "message_only", "limit_note"),
        "nobody shown when nobody fits": not (behavior in ("clarify", "not_found", "message_only") and (full or partial)),
    }
    passed = all(checks.values())

    # 5. save the row and the trace
    usage = rag.last_usage
    rows.append({
        "case": case["id"], "type": case["type"], "passed": passed,
        "expected_full": ", ".join(expected), "full": ", ".join(full), "partial": ", ".join(partial),
        "message": message,
        "recall@5": ratio(found, expected),
        "precision@5": ratio(found, retrieved) if expected else "",
        "completeness": ratio(shown, expected),
        "ranking_ok": not wrong,
        "safe": safe,
        "no_contacts": no_contacts,
        "tokens_in": usage.prompt_token_count,                                                  # Cost
        "tokens_out": (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0),
        "seconds": seconds,                                                                     # Latency
    })
    traces.append({
        "case": case["id"],
        "question": case["question"],
        "user": user_id,
        "allowed": allowed,
        "retrieved": scores,                        # which CVs the search brought
        "excerpts": excerpts,                       # the chunks sent to Gemini
        "gemini": rag.last_raw.model_dump(),        # Gemini's answer, before the code changes it
        "candidates": [c.model_dump() for c in candidates],   # the final answer
        "message": message,
        "failed_checks": [name for name, ok in checks.items() if not ok],
    })

    print(case["id"], "PASS" if passed else "FAIL", full, message)
    time.sleep(5)                                   # free tier: at most 15 Gemini calls a minute


# ---------- save ----------

with open(OUT / "results.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=COLUMNS, restval="")    # an error row leaves the rest empty
    writer.writeheader()
    writer.writerows(rows)

(OUT / "traces.json").write_text(json.dumps(traces, ensure_ascii=False, indent=2), encoding="utf-8")

passed_count = sum(1 for row in rows if row["passed"])
print(f"\nPassed {passed_count}/{len(rows)}. Saved to {OUT}")