"""CV Search UI.   Run:  streamlit run app.py"""
import html
import logging
import re
import time

import httpx
import streamlit as st
from google.genai import errors

from app.admin_pages import show_dashboard, show_review
from app.answer import answer
from app.db import get_connection
from config import cv_file

logging.basicConfig(format="%(asctime)s %(message)s")
logging.getLogger("httpx").setLevel(logging.INFO)   # print every request to Gemini and its status

st.set_page_config(page_title="CV Search", layout="wide")
# each line takes its direction from its first letter: the job description and the message
st.markdown("<style>textarea, [data-testid='stAlert'] p { unicode-bidi: plaintext; text-align: start; }</style>",
            unsafe_allow_html=True)


def load_users():
    with get_connection() as conn:
        return conn.execute("""
            SELECT u.id, u.name, u.role,
                   array_agg(f.field_name ORDER BY f.field_name)
                       FILTER (WHERE f.field_name IS NOT NULL)
            FROM users u
            LEFT JOIN user_fields uf ON uf.user_id = u.id
            LEFT JOIN fields f ON f.id = uf.field_id
            GROUP BY u.id, u.name, u.role
            ORDER BY u.id
        """).fetchall()


def load_fields():
    with get_connection() as conn:
        return [r[0] for r in conn.execute("SELECT field_name FROM fields ORDER BY field_name").fetchall()]


@st.cache_data(show_spinner=False)
def cached_answer(question, user_id, fields, _on_step=None):
    """Same question + same user + same fields = same answer, without calling Gemini again.
    _on_step starts with _ so the cache ignores it: it only reports progress."""
    return answer(question, user_id, fields, on_step=_on_step or (lambda text: None))


def bidi(text):
    """Keep each English phrase as one block, so it doesn't jump around in Arabic text.
    The phrases are found in the raw text and escaped afterwards, so "&" is never split from its entity."""
    parts = re.split(r"([A-Za-z][A-Za-z0-9 .,+#/&\-]*[A-Za-z0-9])", text)
    return "".join(f"<bdi>{html.escape(p)}</bdi>" if i % 2 else html.escape(p)
                   for i, p in enumerate(parts))


# ---------- sidebar: who is searching ----------
users = load_users()
if not users:
    st.error("No users. Run: sql/seed.sql")
    st.stop()

with st.sidebar:
    st.title("CV Search")
    st.caption("Recruiter assistant")
    user = st.selectbox("Signed in as", users, format_func=lambda u: f"{u[1]} ({u[2]})")
    st.caption("Demo user picker. Real sign-in is out of scope.")
    st.divider()
    st.markdown(f"**Role:** {user[2]}")

    # the fields this user may search: all for an admin, their own for a recruiter
    is_admin = user[2] == "admin"
    allowed = load_fields() if is_admin else (user[3] or [])
    fields = st.multiselect("Search in fields", allowed, default=allowed)

    if st.button("Clear cache"):
        st.cache_data.clear()

# ---------- tabs: Review is for the admin only ----------
tabs = st.tabs(["Search", "Dashboard", "Review"] if is_admin else ["Search", "Dashboard"])

with tabs[1]:
    show_dashboard(is_admin, allowed)

if is_admin:
    with tabs[2]:
        show_review(load_fields())

# ================= Search =================
with tabs[0]:
    question = st.text_area("Job description", height=110,
                            placeholder="e.g. We need a SOC analyst in Egypt with at least 3 years, hands-on with Splunk.")

    if st.button("Find candidates", type="primary") and question.strip():
        if not fields:
            st.warning("Choose at least one field.")
            st.stop()

        status = st.status("Starting...")
        steps = []   # (step name, when it started)

        def on_step(text):
            steps.append((text.rstrip(". "), time.perf_counter()))
            status.update(label=text)

        try:
            start = time.perf_counter()
            try:
                filters, candidates, excerpts, scores = cached_answer(
                    question.strip(), user[0], tuple(sorted(fields)), _on_step=on_step)
            except httpx.TransportError:
                # often a connection Google already closed while the app sat idle: one more try opens a new one
                steps.clear()
                filters, candidates, excerpts, scores = cached_answer(
                    question.strip(), user[0], tuple(sorted(fields)), _on_step=on_step)
            end = time.perf_counter()
            seconds = end - start
            status.update(label=f"Done in {seconds:.1f} s", state="complete")

            # where the time went, inside the Done box: each step lasts until the next one starts
            with status:
                if not steps:
                    st.caption("Same question as before: taken from the cache, no call to Gemini.")
                for i, (name, began) in enumerate(steps):
                    ended = steps[i + 1][1] if i + 1 < len(steps) else end
                    st.caption(f"{name}: **{ended - began:.1f} s** ({(ended - began) / seconds:.0%})")
        except errors.ClientError as error:
            if error.code != 429:
                raise
            status.update(label="Gemini limit reached. Try again in a minute.", state="error")
            st.stop()
        except errors.ServerError:
            status.update(label="Gemini is busy. Try again in a few seconds.", state="error")
            st.stop()
        except httpx.TransportError:
            status.update(label="Lost the connection to Gemini. Try again.", state="error")
            st.stop()

        # how the question was understood
        with st.container(border=True):
            st.caption("HOW THE QUESTION WAS UNDERSTOOD")
            used = {k: v for k, v in filters.model_dump().items() if v and k != "message"}
            st.markdown("**Filters:** " + (" · ".join(f"`{k} = {v}`" for k, v in used.items()) or "none"))
            st.markdown(f"**Searched as:** `{question.strip()}`")
            st.caption(f"Time: {seconds:.1f} s")

        # the reasons are written in the question's language
        direction = "rtl" if re.search(r"[؀-ۿ]", question) else "ltr"

        def show_candidate(rank, c, nested=False):
            """One candidate card. nested=True inside the "not a fit" expander:
            Streamlit does not allow an expander inside an expander, so the sources become plain lines there."""
            own = next(e for e in excerpts if e["title"] == c.name)   # any part of this candidate's CV
            with st.container(border=True):
                left, right = st.columns([8, 1], vertical_alignment="center")

                # name + fit badge
                badge = {"full": ":green-badge[Full match]",
                         "partial": ":orange-badge[Partial match]",
                         "none": ":gray-badge[Not a fit]"}[c.fit]
                left.markdown(f"#### {rank}. {c.name} &nbsp; {badge}")

                # the field, in one quiet line, from the search results
                left.caption(own["field"])

                # match, on the right, level with the name
                right.markdown(f"<div style='text-align: center'>"
                               f"<div style='font-size: 1.6rem; font-weight: 500'>{scores.get(c.name, '—')}</div>"
                               f"<div style='font-size: 0.75rem; opacity: 0.7'>match</div></div>",
                               unsafe_allow_html=True)

                # the reasons, one claim per line
                for claim in c.reasons:
                    first, *jobs = claim.split("\n")
                    st.markdown(f"<div dir='{direction}' style='text-align: start'>• {bidi(first)}</div>",
                                unsafe_allow_html=True)
                    for job in jobs:
                        side = "right" if direction == "rtl" else "left"
                        st.markdown(f"<div dir='ltr' style='text-align: {side}; font-size: 0.85rem; opacity: 0.75'>"
                                    f"{html.escape(job)}</div>", unsafe_allow_html=True)

                # each source on its own
                for n in c.citations:
                    e = excerpts[n - 1]
                    label = f"[{n}] {e['section'] or 'Excerpt'} · page {e['page']} · {e['filename']}"
                    if nested:
                        st.caption(label)
                    else:
                        with st.expander(label):
                            st.markdown(f"<div style='white-space: pre-wrap'>{html.escape(e['context'])}</div>",
                                        unsafe_allow_html=True)

                pdf = cv_file(own["drive_file_id"], own["filename"])
                st.download_button("Open CV (PDF)", pdf.read_bytes(), file_name=pdf.name, key=f"pdf-{c.name}")

        # full and partial matches first; the rest folded away, each with its reason
        fits = [c for c in candidates if c.fit != "none"]
        not_fits = [c for c in candidates if c.fit == "none"]

        if filters.message:
            st.info(filters.message)
        elif not fits:
            st.write("No matching candidates.")
        for rank, c in enumerate(fits, start=1):
            show_candidate(rank, c)

        if not_fits:
            with st.expander(f"Checked but not a fit ({len(not_fits)})"):
                for rank, c in enumerate(not_fits, start=len(fits) + 1):
                    show_candidate(rank, c, nested=True)