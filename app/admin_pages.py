"""The Dashboard and Review tabs of the CV app."""
import html

import pandas as pd
import streamlit as st

from app.db import get_connection
from config import cv_file


def load(sql, params=()):
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


def show_dashboard(is_admin, allowed_fields):
    """Counts and the newest CVs. An admin sees every CV; a recruiter only the CVs of their fields."""
    rows = load("""
        SELECT d.created_at, d.title, f.field_name, d.status, d.created_at > now() - interval '7 days'
        FROM documents d
        LEFT JOIN fields f ON f.id = d.field_id
        WHERE %s OR f.field_name = ANY(%s)
        ORDER BY d.created_at DESC
    """, (is_admin, list(allowed_fields)))
    cvs = pd.DataFrame(rows, columns=["Received", "Candidate", "Field", "Status", "New"])
    cvs["Received"] = cvs["Received"].dt.strftime("%b %d, %H:%M")

    # one number per status (a recruiter only has ready CVs)
    statuses = ["ready", "needs_review", "failed", "rejected"] if is_admin else ["ready"]
    for column, status in zip(st.columns(len(statuses)), statuses):
        with column.container(border=True):
            st.metric(status.replace("_", " ").capitalize(), int((cvs["Status"] == status).sum()))

    left, right = st.columns([3, 2])
    with left:
        st.subheader("New this week")
        new = cvs[cvs["New"]].drop(columns="New")
        st.dataframe(new, hide_index=True, use_container_width=True)
    with right:
        st.subheader("Ready CVs per field")
        st.bar_chart(cvs[cvs["Status"] == "ready"]["Field"].value_counts(), horizontal=True)


def show_message(ok, text, seconds=3):
    """A green (done) or red (failed) box that fades out by itself after a few seconds.
    The fading is done by the browser (CSS), so the page does not wait for it."""
    colors = ("rgba(61, 213, 109, 0.2)", "#5ce488") if ok else ("rgba(255, 43, 43, 0.15)", "#ff6c6c")
    st.markdown(f"""
        <style>
        @keyframes review-msg-out {{ to {{ opacity: 0; max-height: 0; padding: 0 1rem; margin: 0; }} }}
        .review-msg {{ background: {colors[0]}; color: {colors[1]}; padding: 1rem; border-radius: 0.5rem;
                       max-height: 6rem; overflow: hidden;
                       animation: review-msg-out 0.6s ease {seconds}s forwards; }}
        </style>
        <div class="review-msg">{html.escape(text)}</div>""", unsafe_allow_html=True)


def show_review(hiring_fields):
    """CVs that need a person: approve them with a name and a field, or reject them. Failed files below."""
    rows = load("""
        SELECT d.id, d.drive_file_id, d.title, d.filename, d.created_at, d.reasons,  f.field_name
        FROM documents d
        LEFT JOIN fields f ON f.id = d.field_id
        WHERE d.status = 'needs_review'
        ORDER BY d.created_at
    """)

    # the result of the last Approve / Reject: st.rerun() clears the page, so it is kept until here
    if "review_msg" in st.session_state:
        ok, text = st.session_state.pop("review_msg")
        show_message(ok, text)

    st.subheader(f"Needs review ({len(rows)})")

    for doc_id, drive_file_id, title, filename, received, reasons, field in rows:
        with st.container(border=True):
            top, open_cv = st.columns([5, 1])
            top.markdown(f"### {title}")
            top.caption(f"{filename} · received {received:%b %d, %H:%M}")
            pdf = cv_file(drive_file_id, filename)
            open_cv.download_button("Open CV", pdf.read_bytes(), file_name=filename, key=f"open-{doc_id}")

            for reason in reasons:
                st.warning(reason, icon="⚠️")

            shown, decide = st.columns([2, 1])
            shown.markdown(f"**Field**  \n{field or '—'}")

            with decide:
                name = st.text_input("Name", title, key=f"name-{doc_id}")
                # no field known: the list starts empty, so a CV is never approved into a field by accident
                index = hiring_fields.index(field) if field in hiring_fields else None
                chosen = st.selectbox("Field", hiring_fields, index=index, key=f"field-{doc_id}",
                                      placeholder="Choose a field")

                approve, reject = st.columns(2)
                if approve.button("Approve", type="primary", key=f"approve-{doc_id}", use_container_width=True,
                                  disabled=chosen is None):
                    try:
                        done = load("""UPDATE documents SET status = 'ready', title = %s, updated_at = now(),
                                           field_id = (SELECT id FROM fields WHERE field_name = %s)
                                       WHERE id = %s AND status = 'needs_review' RETURNING id""",
                                    (name, chosen, doc_id))
                        if done:
                            st.session_state.review_msg = (True, f"{name} approved and added to {chosen}")
                        else:   # already handled, e.g. in another tab
                            st.session_state.review_msg = (False, f"{name} was already reviewed")
                    except Exception as error:
                        st.session_state.review_msg = (False, f"Could not approve {name}: {error}")
                    st.rerun()
                if reject.button("Reject", key=f"reject-{doc_id}", use_container_width=True):
                    try:
                        load("UPDATE documents SET status = 'rejected', updated_at = now() WHERE id = %s RETURNING id",
                             (doc_id,))
                        load("DELETE FROM document_chunks WHERE document_id = %s RETURNING id", (doc_id,))
                        st.session_state.review_msg = (True, f"{name} rejected")
                    except Exception as error:
                        st.session_state.review_msg = (False, f"Could not reject {name}: {error}")
                    st.rerun()

    failed = load("SELECT filename, reasons, created_at FROM documents WHERE status = 'failed' ORDER BY created_at")
    st.subheader(f"Failed ({len(failed)})")
    st.dataframe(pd.DataFrame([(name, "; ".join(reasons), f"{received:%b %d, %H:%M}") for name, reasons, received in failed],
                              columns=["File", "Reason", "Received"]),
                 hide_index=True, use_container_width=True)