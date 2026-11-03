"""
Step 7: LLM as a judge.
Claude Code grades every answer of one run.
Run:  python 07_judge.py A1
"""

import json
import subprocess
import sys
import config
from app.answer import PRIVATE
from config import BASE_DIR


# Configuration
RUN = sys.argv[1]
EVAL_DIR = BASE_DIR / "data" / "evaluation"
RUN_DIR = EVAL_DIR / "runs" / RUN


# The criteria
CRITERIA = """
You grade answers of a CV search system for recruiters. Only read and grade.
You get the user's request, the correct answer (written by hand),
the system's answer, and the CV parts the system read.
Grade three things:
1. answer_right: true only if
   - the candidates shown as full are exactly expected_full
     (when expected_behavior is limit_note: only names from expected_full, not necessarily all of them),
   - the candidates shown as partial are exactly expected_partial,
   - nobody from not_full is shown as full,
   - when the message refuses, asks the recruiter to clarify, or answers a request for contact details:
     no candidate is shown at all, not even as "none".
2. unsupported_reasons: copy every reason that is not supported by the CV parts whose numbers it gives ([n]).
   A reason that says something is missing is supported only if that candidate's parts really don't show it.
   The line that starts with "Experience:" or "سنوات الخبرة:" is counted by code and is right;
   any other reason that states a different number of years is unsupported.
3. message_right: true if the message does what expected_behavior needs:
   - rank: anything that doesn't contradict the answer;
   - limit_note: says that only the closest CVs were checked;
   - not_found: says that nobody fits, or that the named person is not among the CVs;
   - clarify: says what the request is missing, or why the CVs can't answer it;
   - message_only: gives the refusal or the note described in watch.
   The app's download button is named exactly "Open CV (PDF)": a message that names another button is wrong.
   Judge the meaning, not the words.

In why, one short sentence for each wrong grade.
"""


ANSWER_SHAPE = {
    "type": "object",
    "properties": {
        "answer_right": {"type": "boolean"},
        "unsupported_reasons": {"type": "array", "items": {"type": "string"}},
        "message_right": {"type": "boolean"},
        "why": {"type": "string"},
    },
    "required": [
        "answer_right",
        "unsupported_reasons",
        "message_right",
        "why",
    ],
}


# Build the prompt
def build_prompt(case, trace):
    parts = ""
    for number, part in enumerate(trace["excerpts"], 1):
        text = PRIVATE.sub("", part["context"])
        parts += f"[{number}] ({part['title']}) {text}\n\n"
    correct_answer = json.dumps(case, ensure_ascii=False, indent=2)
    system_answer = json.dumps(trace["candidates"], ensure_ascii=False, indent=2)
    return f"""
REQUEST:
{case['question']}

CORRECT ANSWER:
{correct_answer}

SYSTEM ANSWER:
Message: {trace['message']}
{system_answer}

CV PARTS:
{parts}
"""


# Ask Claude
def ask_claude(prompt):

    command = [
        "claude",
        "-p",
        "--model", "claude-opus-5-5",
        "--effort", "high",
        "--tools", "",
        "--safe-mode",
        "--no-session-persistence",
        "--system-prompt", CRITERIA,
        "--output-format", "json",
        "--json-schema", json.dumps(ANSWER_SHAPE),
    ]

    result = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=RUN_DIR,
    )

    output = json.loads(result.stdout)
    if "structured_output" not in output:
        raise SystemExit(f"Claude did not answer: {output.get('result')}. Run the same command again to continue.")
    grade = output["structured_output"]

    # the judge's own tokens (cache included: it is still text the model read)
    usage = output["usage"]
    grade["tokens_in"] = usage["input_tokens"] + usage["cache_creation_input_tokens"] + usage["cache_read_input_tokens"]
    grade["tokens_out"] = usage["output_tokens"]
    return grade


# Grade every answer
all_cases = json.loads((EVAL_DIR / "eval_cases.json").read_text(encoding="utf-8"))
cases = {}

for case in all_cases:
    cases[case["id"]] = case

traces = json.loads((RUN_DIR / "traces.json").read_text(encoding="utf-8"))

# the cases already graded, if an earlier run stopped half way
grades = []
if (RUN_DIR / "judge.json").exists():
    grades = json.loads((RUN_DIR / "judge.json").read_text(encoding="utf-8"))
done = [grade["case"] for grade in grades]

for trace in traces:
    if trace["case"] in done:
        continue
    case = cases[trace["case"]]
    grade = ask_claude(build_prompt(case, trace))
    grade["case"] = case["id"]
    grade["reasons"] = sum(len(candidate["reasons"]) for candidate in trace["candidates"])
    grades.append(grade)
    print(case["id"], grade)

    # saved after every case, so nothing is lost if the run stops
    (RUN_DIR / "judge.json").write_text(
        json.dumps(grades, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# Summary
reasons = sum(grade["reasons"] for grade in grades)
unsupported = sum(len(grade["unsupported_reasons"]) for grade in grades)
answers_right = sum(grade["answer_right"] for grade in grades)
messages_right = sum(grade["message_right"] for grade in grades)
tokens_in = sum(grade["tokens_in"] for grade in grades)
tokens_out = sum(grade["tokens_out"] for grade in grades)

print()
print("answer right:", answers_right, "/", len(grades))
print("grounding:", reasons - unsupported, "/", reasons)
print("message right:", messages_right, "/", len(grades))
print("judge tokens:", tokens_in, "in,", tokens_out, "out  (per case:",
      tokens_in // len(grades), "in,", tokens_out // len(grades), "out)")