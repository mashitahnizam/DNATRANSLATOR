from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st

from auth import get_db_client


# ============================================================
# CONSTANTS
# ============================================================

DATABASE_NAME = "dna_translation_db"
USERS_COLLECTION = "users"


# ============================================================
# SESSION STATE FIX
# ============================================================

def ensure_component_state() -> None:
    """
    Make sure required session-state keys exist before using them.
    This prevents Streamlit Cloud errors such as:
    AttributeError: st.session_state has no attribute "history_page"
    """
    defaults = {
        "history_records_per_page": 10,
        "history_show_full_by_default": False,
        "history_page": 1,
        "confirm_clear_entire_history": False,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# Run once when components.py is imported
ensure_component_state()


# ============================================================
# GENERAL HELPERS
# ============================================================

def _create_preview(value: Any, limit: int = 60) -> str:
    """Create a short preview text for long sequence/result values."""
    text = " ".join(str(value or "").split())

    if len(text) <= limit:
        return text

    return f"{text[:limit]}..."


def _normalise_timestamp(value: Any) -> str:
    """Convert different timestamp formats into readable text."""
    if value is None or value == "":
        return "Not available"

    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")

    try:
        parsed = pd.to_datetime(value)

        if pd.isna(parsed):
            return str(value)

        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    except Exception:
        return str(value)


def _normalise_history_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Convert old and new history formats into one display format.
    Older records may use sequence/result.
    Newer records use sequence_full/result_full.
    """
    sequence = record.get("sequence_full", record.get("sequence", ""))
    result = record.get("result_full", record.get("result", ""))
    organism = record.get("organism", "N/A")

    analysis_type = record.get("analysis_type")

    if not analysis_type:
        result_text = str(result)

        if result_text.startswith("Acc:") or "accession" in result_text.lower():
            analysis_type = "BLAST Validation"
        else:
            analysis_type = "DNA Translation"

    return {
        "history_id": record.get("history_id", ""),
        "sequence": str(sequence or ""),
        "result": str(result or ""),
        "organism": str(organism or "N/A"),
        "analysis_type": str(analysis_type),
        "codon_table": str(record.get("codon_table", "Not recorded")),
        "timestamp": _normalise_timestamp(record.get("timestamp")),
        "raw_record": record,
    }


# ============================================================
# DATABASE HELPERS
# ============================================================

def _get_users_collection():
    """Return MongoDB users collection and client."""
    client = get_db_client()

    if client is None:
        return None, None

    database = client[DATABASE_NAME]
    users_collection = database[USERS_COLLECTION]

    return client, users_collection


def _get_user_history(username: str) -> tuple[list[dict[str, Any]], str | None]:
    """Read one user's saved history from MongoDB."""
    client, users_collection = _get_users_collection()

    if client is None or users_collection is None:
        return [], "The database connection could not be established."

    try:
        user_document = users_collection.find_one(
            {"username": username},
            {"history": 1},
        )

        if not user_document:
            return [], "The registered user profile could not be found."

        history_records = user_document.get("history", [])

        if not isinstance(history_records, list):
            return [], "The stored history format is invalid."

        return history_records, None

    except Exception as error:
        return [], f"The history records could not be loaded: {error}"

    finally:
        client.close()


def _delete_history_record(
    username: str,
    raw_record: dict[str, Any],
) -> tuple[bool, str]:
    """Delete one saved history record."""
    client, users_collection = _get_users_collection()

    if client is None or users_collection is None:
        return False, "The database connection could not be established."

    try:
        history_id = raw_record.get("history_id")

        if history_id:
            update_result = users_collection.update_one(
                {"username": username},
                {"$pull": {"history": {"history_id": history_id}}},
            )
        else:
            update_result = users_collection.update_one(
                {"username": username},
                {"$pull": {"history": raw_record}},
            )

        if update_result.modified_count == 1:
            return True, "History record deleted successfully."

        return False, "The selected history record was not changed."

    except Exception as error:
        return False, f"The history record could not be deleted: {error}"

    finally:
        client.close()


def _clear_user_history(username: str) -> tuple[bool, str]:
    """Clear all saved history records for one user."""
    client, users_collection = _get_users_collection()

    if client is None or users_collection is None:
        return False, "The database connection could not be established."

    try:
        update_result = users_collection.update_one(
            {"username": username},
            {"$set": {"history": []}},
        )

        if update_result.matched_count == 0:
            return False, "The registered user profile could not be found."

        return True, "All history records were cleared successfully."

    except Exception as error:
        return False, f"The history records could not be cleared: {error}"

    finally:
        client.close()


# ============================================================
# HISTORY STORAGE
# ============================================================

def save_search_to_history(
    username: str,
    sequence: str,
    translation: str,
    organism: str = "N/A",
    analysis_type: str | None = None,
    codon_table: str | int | None = None,
) -> bool:
    """
    Save analysis history for registered users only.
    Guest activity is not saved.
    """
    if not username or username == "Guest":
        return False

    sequence_text = str(sequence or "").strip()
    result_text = str(translation or "").strip()
    organism_text = str(organism or "N/A").strip()

    if not sequence_text and not result_text:
        return False

    if analysis_type is None:
        if result_text.startswith("Acc:") or "accession" in result_text.lower():
            analysis_type = "BLAST Validation"
        else:
            analysis_type = "DNA Translation"

    history_item = {
        "history_id": str(uuid4()),
        "analysis_type": analysis_type,
        "sequence_full": sequence_text,
        "result_full": result_text,
        "organism": organism_text,
        "codon_table": str(codon_table) if codon_table is not None else "Not recorded",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    client, users_collection = _get_users_collection()

    if client is None or users_collection is None:
        return False

    try:
        update_result = users_collection.update_one(
            {"username": username},
            {"$push": {"history": history_item}},
        )

        return update_result.modified_count == 1

    except Exception:
        return False

    finally:
        client.close()


# ============================================================
# HISTORY DASHBOARD
# ============================================================

def render_history_dashboard(username: str) -> None:
    """Display saved analysis history."""
    ensure_component_state()

    st.title("📊 Search History Log")
    st.write(
        "Review the DNA translation and BLAST analyses saved under your "
        "registered student profile."
    )

    if not username or username == "Guest":
        st.info(
            "History recording is OFF for guest users. Create an account or "
            "log in to save and revisit previous analyses."
        )
        return

    stored_history, history_error = _get_user_history(username)

    if history_error:
        st.error(history_error)
        return

    if not stored_history:
        st.info(
            "Your history log is empty. Run a DNA translation or BLAST analysis "
            "to create your first saved record."
        )
        return

    normalised_history = [
        _normalise_history_record(record)
        for record in reversed(stored_history)
    ]

    translation_count = sum(
        record["analysis_type"] == "DNA Translation"
        for record in normalised_history
    )

    blast_count = sum(
        record["analysis_type"] == "BLAST Validation"
        for record in normalised_history
    )

    metric_1, metric_2, metric_3 = st.columns(3)
    metric_1.metric("Total Saved Records", len(normalised_history))
    metric_2.metric("Translation Records", translation_count)
    metric_3.metric("BLAST Records", blast_count)

    search_text = st.text_input(
        "Search history",
        placeholder="Search by DNA sequence, result, organism, or analysis type",
    ).strip().lower()

    selected_filter = st.selectbox(
        "Filter by analysis type",
        [
            "All Analyses",
            "DNA Translation",
            "BLAST Validation",
        ],
    )

    filtered_history = []

    for record in normalised_history:
        matches_type = (
            selected_filter == "All Analyses"
            or record["analysis_type"] == selected_filter
        )

        searchable_text = " ".join(
            [
                record["sequence"],
                record["result"],
                record["organism"],
                record["analysis_type"],
                record["timestamp"],
            ]
        ).lower()

        matches_search = (
            not search_text
            or search_text in searchable_text
        )

        if matches_type and matches_search:
            filtered_history.append(record)

    if not filtered_history:
        st.warning("No history records match the selected search and filter.")
        return

    records_per_page = int(st.session_state.get("history_records_per_page", 10))
    records_per_page = max(5, min(records_per_page, 50))

    total_pages = max(
        1,
        (len(filtered_history) + records_per_page - 1) // records_per_page,
    )

    if "history_page" not in st.session_state:
        st.session_state["history_page"] = 1

    if int(st.session_state["history_page"]) > total_pages:
        st.session_state["history_page"] = total_pages

    if total_pages > 1:
        selected_page = st.number_input(
            "History page",
            min_value=1,
            max_value=total_pages,
            value=int(st.session_state["history_page"]),
            step=1,
        )

        st.session_state["history_page"] = int(selected_page)
    else:
        st.session_state["history_page"] = 1

    page_start = (int(st.session_state["history_page"]) - 1) * records_per_page
    page_end = page_start + records_per_page
    page_records = filtered_history[page_start:page_end]

    table_rows = []

    for display_index, record in enumerate(page_records, start=page_start + 1):
        table_rows.append(
            {
                "Record": display_index,
                "Analysis Type": record["analysis_type"],
                "DNA Sequence Preview": _create_preview(record["sequence"], 55),
                "Result Preview": _create_preview(record["result"], 55),
                "Organism or Description": _create_preview(record["organism"], 55),
                "Timestamp": record["timestamp"],
            }
        )

    st.dataframe(
        pd.DataFrame(table_rows),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        f"Showing {page_start + 1}-{min(page_end, len(filtered_history))} "
        f"of {len(filtered_history)} matching record(s)."
    )

    record_labels = {
        (
            f"Record {page_start + index + 1}: "
            f"{record['analysis_type']} — {record['timestamp']}"
        ): record
        for index, record in enumerate(page_records)
    }

    selected_label = st.selectbox(
        "Select a record to inspect",
        list(record_labels.keys()),
    )

    selected_record = record_labels[selected_label]

    with st.expander(
        "View Complete Saved Record",
        expanded=bool(st.session_state.get("history_show_full_by_default", False)),
    ):
        st.write(f"**Analysis type:** {selected_record['analysis_type']}")
        st.write(f"**Timestamp:** {selected_record['timestamp']}")
        st.write(f"**Codon table:** {selected_record['codon_table']}")
        st.write(f"**Organism or description:** {selected_record['organism']}")

        st.write("**Stored DNA sequence**")
        st.code(selected_record["sequence"] or "No sequence was stored.")

        st.write("**Stored result**")
        st.code(selected_record["result"] or "No result was stored.")

    action_col_1, action_col_2, action_col_3 = st.columns(3)

    with action_col_1:
        if st.button(
            "🔁 Load DNA into Analysis Station",
            use_container_width=True,
        ):
            st.session_state["dna"] = selected_record["sequence"]
            st.session_state["last_analysis"] = None
            st.session_state["active_tab"] = "🔬 DNA Analysis Station"
            st.success("The saved DNA sequence was loaded.")
            st.rerun()

    with action_col_2:
        record_download = (
            "DNA WORKSTATION SAVED HISTORY RECORD\n"
            "====================================\n\n"
            f"Analysis Type: {selected_record['analysis_type']}\n"
            f"Timestamp: {selected_record['timestamp']}\n"
            f"Codon Table: {selected_record['codon_table']}\n"
            f"Organism or Description: {selected_record['organism']}\n\n"
            "DNA Sequence\n"
            "------------\n"
            f"{selected_record['sequence']}\n\n"
            "Stored Result\n"
            "-------------\n"
            f"{selected_record['result']}\n"
        )

        st.download_button(
            "📥 Download Selected Record",
            data=record_download,
            file_name="dna_workstation_history_record.txt",
            mime="text/plain",
            use_container_width=True,
        )

    with action_col_3:
        confirm_delete = st.checkbox(
            "Confirm deletion",
            key=f"confirm_delete_{selected_label}",
        )

        if st.button(
            "🗑️ Delete Selected Record",
            disabled=not confirm_delete,
            use_container_width=True,
        ):
            deleted, delete_message = _delete_history_record(
                username,
                selected_record["raw_record"],
            )

            if deleted:
                st.success(delete_message)
                st.rerun()
            else:
                st.error(delete_message)

    st.divider()

    with st.expander("Clear Entire History Log"):
        st.warning(
            "This permanently removes all saved analysis records from your "
            "registered profile."
        )

        confirm_clear = st.checkbox(
            "I understand that this action cannot be undone.",
            key="confirm_clear_entire_history",
        )

        if st.button(
            "Clear All History Records",
            disabled=not confirm_clear,
            use_container_width=True,
        ):
            cleared, clear_message = _clear_user_history(username)

            if cleared:
                st.success(clear_message)
                st.session_state["history_page"] = 1
                st.rerun()
            else:
                st.error(clear_message)


# ============================================================
# ADMIN DASHBOARD
# ============================================================

def _get_all_users_for_admin() -> tuple[list[dict[str, Any]], str | None]:
    """Read all registered user records for admin dashboard."""
    client, users_collection = _get_users_collection()

    if client is None or users_collection is None:
        return [], "The database connection could not be established."

    try:
        user_documents = list(
            users_collection.find(
                {},
                {
                    "username": 1,
                    "email": 1,
                    "role": 1,
                    "history": 1,
                    "password": 1,
                },
            ).sort("username", 1)
        )

        return user_documents, None

    except Exception as error:
        return [], f"Admin records could not be loaded: {error}"

    finally:
        client.close()


def render_admin_dashboard() -> None:
    """Render a simple administrator dashboard."""
    ensure_component_state()

    st.title("🛡️ Admin Dashboard")
    st.write(
        "This page allows the administrator to monitor registered users and "
        "inspect stored analysis history records."
    )

    user_documents, admin_error = _get_all_users_for_admin()

    if admin_error:
        st.error(admin_error)
        return

    if not user_documents:
        st.info("No registered user records were found in MongoDB.")
        return

    total_users = len(user_documents)
    admin_count = sum(
        str(user.get("role", "user")).lower() == "admin"
        for user in user_documents
    )

    total_history_records = sum(
        len(user.get("history", []))
        for user in user_documents
        if isinstance(user.get("history", []), list)
    )

    metric_1, metric_2, metric_3 = st.columns(3)
    metric_1.metric("Total Users", total_users)
    metric_2.metric("Admin Accounts", admin_count)
    metric_3.metric("Saved History Records", total_history_records)

    st.subheader("Registered User Overview")

    overview_rows = []

    for user in user_documents:
        history_records = user.get("history", [])

        if not isinstance(history_records, list):
            history_records = []

        overview_rows.append(
            {
                "Username": user.get("username", "N/A"),
                "Email": user.get("email", "N/A"),
                "Role": user.get("role", "user"),
                "Saved Records": len(history_records),
                "Password Stored As Hash": "Yes" if user.get("password") else "No",
            }
        )

    st.dataframe(
        pd.DataFrame(overview_rows),
        use_container_width=True,
        hide_index=True,
    )

    selectable_users = {
        f"{user.get('username', 'N/A')} ({user.get('email', 'N/A')})": user
        for user in user_documents
    }

    selected_user_label = st.selectbox(
        "Select a user profile to inspect",
        list(selectable_users.keys()),
    )

    selected_user = selectable_users[selected_user_label]
    selected_username = selected_user.get("username", "")

    st.subheader("Selected User Details")

    detail_col_1, detail_col_2, detail_col_3 = st.columns(3)
    detail_col_1.metric("Username", selected_username or "N/A")
    detail_col_2.metric("Role", selected_user.get("role", "user"))

    raw_history = selected_user.get("history", [])

    if not isinstance(raw_history, list):
        raw_history = []

    detail_col_3.metric("History Records", len(raw_history))

    st.write(f"**Email:** {selected_user.get('email', 'N/A')}")
    st.write("**Password field:** stored as a hash value, not plain text.")

    if not raw_history:
        st.info("This user has no saved analysis history.")
        return

    normalised_history = [
        _normalise_history_record(record)
        for record in reversed(raw_history)
    ]

    st.subheader("Selected User History Records")

    history_rows = []

    for index, record in enumerate(normalised_history, start=1):
        history_rows.append(
            {
                "Record": index,
                "Analysis Type": record["analysis_type"],
                "DNA Sequence Preview": _create_preview(record["sequence"], 50),
                "Result Preview": _create_preview(record["result"], 50),
                "Organism or Description": _create_preview(record["organism"], 50),
                "Timestamp": record["timestamp"],
            }
        )

    st.dataframe(
        pd.DataFrame(history_rows),
        use_container_width=True,
        hide_index=True,
    )

    record_options = {
        (
            f"Record {index}: {record['analysis_type']} — "
            f"{record['timestamp']}"
        ): record
        for index, record in enumerate(normalised_history, start=1)
    }

    selected_record_label = st.selectbox(
        "Select a user history record to inspect",
        list(record_options.keys()),
    )

    selected_record = record_options[selected_record_label]

    with st.expander("View Complete User History Record", expanded=True):
        st.write(f"**Analysis type:** {selected_record['analysis_type']}")
        st.write(f"**Timestamp:** {selected_record['timestamp']}")
        st.write(f"**Codon table:** {selected_record['codon_table']}")
        st.write(f"**Organism or description:** {selected_record['organism']}")

        st.write("**Stored DNA sequence**")
        st.code(selected_record["sequence"] or "No sequence was stored.")

        st.write("**Stored result**")
        st.code(selected_record["result"] or "No result was stored.")

    admin_action_col_1, admin_action_col_2 = st.columns(2)

    with admin_action_col_1:
        confirm_admin_delete = st.checkbox(
            "Confirm deletion of selected user history record",
            key=f"admin_confirm_delete_{selected_username}_{selected_record_label}",
        )

        if st.button(
            "Delete Selected User History Record",
            disabled=not confirm_admin_delete,
            use_container_width=True,
        ):
            deleted, delete_message = _delete_history_record(
                selected_username,
                selected_record["raw_record"],
            )

            if deleted:
                st.success(delete_message)
                st.rerun()
            else:
                st.error(delete_message)

    with admin_action_col_2:
        confirm_admin_clear = st.checkbox(
            "Confirm clearing all history for selected user",
            key=f"admin_confirm_clear_{selected_username}",
        )

        if st.button(
            "Clear Selected User History",
            disabled=not confirm_admin_clear,
            use_container_width=True,
        ):
            cleared, clear_message = _clear_user_history(selected_username)

            if cleared:
                st.success(clear_message)
                st.rerun()
            else:
                st.error(clear_message)


# ============================================================
# USER GUIDE
# ============================================================

def render_user_guide() -> None:
    """Render a user guide for the system."""
    ensure_component_state()

    st.title("📘 User Guide Manual")
    st.write(
        "This guide explains how undergraduate bioinformatics students can "
        "use the DNA Workstation safely and correctly."
    )

    input_tab, translation_tab, blast_tab, history_tab, troubleshooting_tab = st.tabs(
        [
            "DNA Input",
            "Guided Translation",
            "BLAST Validation",
            "Saved History",
            "Troubleshooting",
        ]
    )

    with input_tab:
        st.subheader("1. Entering a DNA Sequence")
        st.markdown(
            """
You can begin in one of three ways:

1. Select a built-in learning example.
2. Upload a FASTA, FA, FNA, or TXT file.
3. Paste a raw DNA sequence into the text area.

The cleaning report identifies and removes formatting content such as FASTA headers, spaces, numbers, and punctuation. Unsupported biological letters are reported and must be corrected before translation.
"""
        )

        st.info("A valid DNA sequence for this system contains only A, T, G, and C.")

    with translation_tab:
        st.subheader("2. Running the Guided Translation Analysis")
        st.markdown(
            """
1. Select the genetic code table that matches the sequence source.
2. Click **Run Guided Translation Analysis**.
3. Review the transparent cleaning report.
4. Inspect the nucleotide distribution.
5. Follow the codon-to-amino-acid mapping.
6. Review the translated protein sequence.
7. Interpret the molecular weight, isoelectric point, instability index, and GRAVY.
8. Examine the identified open reading frame, when available.
9. Download the generated student analysis report.

The available genetic code tables are:

- **Standard (1):** commonly used for nuclear DNA.
- **Vertebrate Mitochondrial (2):** used for vertebrate mitochondrial DNA.
- **Bacterial, Archaeal and Plant Plastid (11):** used for bacterial, archaeal, and plastid sequences.
"""
        )

    with blast_tab:
        st.subheader("3. Validating a Sequence with BLAST")
        st.markdown(
            """
1. Enter or upload a valid DNA sequence.
2. Click **Validate Sequence with BLAST**.
3. Wait while the sequence is submitted to the NCBI nucleotide database.
4. Review the accession number, identity percentage, query coverage, E-value, and matched description.

BLAST requires an active internet connection and may take longer when the NCBI service is busy.
"""
        )

        st.warning(
            "Do not repeatedly submit the same BLAST request while a previous "
            "request is still processing."
        )

    with history_tab:
        st.subheader("4. Using the Search History Log")
        st.markdown(
            """
History is available only to registered users.

Saved records can be:

- searched and filtered;
- inspected in full;
- loaded back into the DNA Analysis Station;
- downloaded as a text record;
- deleted individually; or
- cleared from the registered profile.

Guest analyses are not stored.
"""
        )

    with troubleshooting_tab:
        st.subheader("5. Common Messages and Solutions")
        st.markdown(
            """
**Unsupported nucleotide letters detected**  
Correct letters such as N, X, U, or Z before translation. This system currently accepts only A, T, G, and C.

**Incomplete final codon**  
One or two bases remain after the final complete group of three. These bases are shown but are not translated.

**No complete ORF identified**  
The sequence may not contain a valid in-frame start-to-stop region under the selected genetic code.

**No protein properties available**  
The sequence may not have produced a valid amino-acid sequence before the first stop codon.

**BLAST service unavailable**  
Check the internet connection and retry later. NCBI may temporarily delay or reject requests during high usage.

**History not recorded**  
History is disabled in Guest mode. Sign in with a registered profile to save analyses.
"""
        )


# ============================================================
# SETTINGS PANEL
# ============================================================

def render_settings_panel() -> None:
    """Render settings and preferences."""
    ensure_component_state()

    st.title("⚙️ System Settings")
    st.write(
        "Adjust the appearance and history-display preferences for the "
        "current browser session."
    )

    st.subheader("🎨 Visual Theme")

    theme_options = [
        "Classic Pastel Pink (Default)",
        "High-Contrast Charcoal",
        "Nordic Crisp Teal",
    ]

    current_theme = st.session_state.get(
        "current_theme",
        theme_options[0],
    )

    try:
        current_index = theme_options.index(current_theme)
    except ValueError:
        current_index = 0

    selected_theme = st.selectbox(
        "Active Colour Theme",
        theme_options,
        index=current_index,
    )

    if selected_theme != current_theme:
        st.session_state["current_theme"] = selected_theme
        st.success("Theme updated successfully.")
        st.rerun()

    st.caption(f"Current theme: **{st.session_state.get('current_theme', theme_options[0])}**")

    st.divider()
    st.subheader("📊 History Display")

    records_per_page = st.select_slider(
        "Records displayed per history page",
        options=[5, 10, 15, 20, 30, 50],
        value=int(st.session_state.get("history_records_per_page", 10)),
    )

    show_full_by_default = st.checkbox(
        "Open the complete saved-record panel automatically",
        value=bool(st.session_state.get("history_show_full_by_default", False)),
    )

    st.session_state["history_records_per_page"] = records_per_page
    st.session_state["history_show_full_by_default"] = show_full_by_default

    st.success("The current session preferences have been saved.")

    st.divider()
    st.subheader("🧹 Analysis Workspace")

    st.write(
        "Use this option to clear the current sequence and generated analysis "
        "without logging out."
    )

    confirm_workspace_reset = st.checkbox(
        "Confirm workspace reset",
        key="confirm_component_workspace_reset",
    )

    if st.button(
        "Reset Current Analysis Workspace",
        disabled=not confirm_workspace_reset,
        use_container_width=True,
    ):
        st.session_state["dna"] = ""
        st.session_state["table"] = "Standard (1)"
        st.session_state["selected_example"] = "Select an example"
        st.session_state["last_analysis"] = None
        st.session_state["last_upload_hash"] = ""
        st.session_state["uploader_key"] = int(st.session_state.get("uploader_key", 0)) + 1
        st.session_state["active_tab"] = "🔬 DNA Analysis Station"

        st.success("The analysis workspace was reset.")
        st.rerun()