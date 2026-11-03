"""The Dashboard and Review tabs of the CV app."""
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


def show_review(hiring_fields):
    """CVs that need a person: approve them with a name and a field, or reject them. Failed files below."""
    rows = load("""
        SELECT d.id, d.drive_file_id, d.title, d.filename, d.created_at, d.reasons, d.metadata, f.field_name
        FROM documents d
        LEFT JOIN fields f ON f.id = d.field_id
        WHERE d.status = 'needs_review'
        ORDER BY d.created_at
    """)
    st.subheader(f"Needs review ({len(rows)})")

    for doc_id, drive_file_id, title, filename, received, reasons, guess, field in rows:
        with st.container(border=True):
            top, open_cv = st.columns([5, 1])
            top.markdown(f"### {title}")
            top.caption(f"{filename} · received {received:%b %d, %H:%M}")
            pdf = cv_file(drive_file_id, filename)
            open_cv.download_button("Open CV", pdf.read_bytes(), file_name=filename, key=f"open-{doc_id}")

            for reason in reasons:
                st.warning(reason, icon="⚠️")

            closest, second, decide = st.columns(3)
            if field:                            # the field is clear: the problem is elsewhere
                closest.markdown(f"**Field**  \n{field}")
            else:                                # the field is the problem: show the guess
                closest.markdown(f"**Closest field**  \n{guess.get('closest', '—')}  \n`score {guess.get('score', '—')}`")
                second.markdown(f"**Second field**  \n{guess.get('second', '—')}  \n`gap {guess.get('gap', '—')}`")

            with decide:
                name = st.text_input("Name", title, key=f"name-{doc_id}")
                suggested = field or guess.get("closest")
                index = hiring_fields.index(suggested) if suggested in hiring_fields else 0
                chosen = st.selectbox("Field", hiring_fields, index=index, key=f"field-{doc_id}")

                approve, reject = st.columns(2)
                if approve.button("Approve", type="primary", key=f"approve-{doc_id}", use_container_width=True):
                    load("""UPDATE documents SET status = 'ready', title = %s, updated_at = now(),
                                field_id = (SELECT id FROM fields WHERE field_name = %s)
                            WHERE id = %s RETURNING id""", (name, chosen, doc_id))
                    st.rerun()
                if reject.button("Reject", key=f"reject-{doc_id}", use_container_width=True):
                    load("UPDATE documents SET status = 'rejected', updated_at = now() WHERE id = %s RETURNING id",
                         (doc_id,))
                    load("DELETE FROM document_chunks WHERE document_id = %s RETURNING id", (doc_id,))
                    st.rerun()

    failed = load("SELECT filename, reasons, created_at FROM documents WHERE status = 'failed' ORDER BY created_at")
    st.subheader(f"Failed ({len(failed)})")
    st.dataframe(pd.DataFrame([(name, "; ".join(reasons), f"{received:%b %d, %H:%M}") for name, reasons, received in failed],
                              columns=["File", "Reason", "Received"]),
                 hide_index=True, use_container_width=True)
    