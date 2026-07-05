from __future__ import annotations

import hashlib
import html
import os
import re
import secrets
import smtplib
import time
from email.mime.text import MIMEText
from typing import Any

import pandas as pd
import streamlit as st

from auth import add_user, get_user_role, login_user, update_password, verify_email_exists
from components import (
    render_admin_dashboard,
    render_history_dashboard,
    render_settings_panel,
    render_user_guide,
    save_search_to_history,
)
from translator import (
    blast_sequence,
    build_codon_mapping,
    create_student_report,
    find_orf,
    get_cleaning_report,
    get_genetic_code_name,
    get_protein_details,
    interpret_analysis_results,
    translate_dna,
    validate_dna,
)


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="DNA Workstation",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CONSTANTS
# ============================================================

APP_NAME = "DNA Workstation"
RESET_PIN_LIFETIME_SECONDS = 10 * 60

# ============================================================
# EMAIL CONFIGURATION FOR PASSWORD RECOVERY
# ============================================================
# Configure password-recovery email with environment variables or
# .streamlit/secrets.toml. Never commit Gmail app passwords.
FALLBACK_SENDER_EMAIL = "noreply.dnaworkstation@gmail.com"
FALLBACK_SENDER_PASSWORD = "qujsgqunvrwshemw"

CODON_TABLE_OPTIONS = {
    "Standard (1)": 1,
    "Vertebrate Mitochondrial (2)": 2,
    "Bacterial, Archaeal and Plant Plastid (11)": 11,
}

EXAMPLE_SEQUENCES: dict[str, dict[str, str]] = {
    "Select an example": {
        "sequence": "",
        "table": "Standard (1)",
        "objective": "Choose a prepared sequence to explore the analysis workflow.",
    },
    "Simple start-to-stop example": {
        "sequence": "ATGGCTTTTTAA",
        "table": "Standard (1)",
        "objective": (
            "Demonstrates a start codon, two amino-acid codons, "
            "and a stop codon."
        ),
    },
    "Human DNA translation example": {
        "sequence": "ATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAG",
        "table": "Standard (1)",
        "objective": (
            "Demonstrates translation of a longer sequence using the standard "
            "genetic code."
        ),
    },
    "Vertebrate mitochondrial example": {
        "sequence": "ATGAGATTTTAA",
        "table": "Vertebrate Mitochondrial (2)",
        "objective": (
            "Demonstrates how a mitochondrial genetic code can interpret a "
            "codon differently from the standard table."
        ),
    },
    "Bacterial ORF example": {
        "sequence": "ATGAAAGGCTGCTAA",
        "table": "Bacterial, Archaeal and Plant Plastid (11)",
        "objective": (
            "Demonstrates a complete open reading frame using the bacterial "
            "genetic code."
        ),
    },
    "Formatting-noise example": {
        "sequence": ">Example_Sequence\n1 ATG GCT 123 TTT-TAA",
        "table": "Standard (1)",
        "objective": (
            "Demonstrates how FASTA headers, spaces, numbers, and formatting "
            "symbols are removed transparently."
        ),
    },
    "Invalid biological-input example": {
        "sequence": ">Invalid_Sequence\nATGCXTGZAA",
        "table": "Standard (1)",
        "objective": (
            "Demonstrates how unsupported nucleotide letters are detected "
            "instead of silently accepted."
        ),
    },
}


# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================

DEFAULT_SESSION_VALUES: dict[str, Any] = {
    "dna": "",
    "table": "Standard (1)",
    "uploader_key": 0,
    "last_upload_hash": "",
    "logged_in": False,
    "username": "",
    "user_role": "",
    "reset_pin": None,
    "reset_pin_created_at": None,
    "reset_email": "",
    "current_theme": "Classic Pastel Pink (Default)",
    "active_tab": "🔬 DNA Analysis Station",
    "selected_example": "Select an example",
    "last_analysis": None,
}

for state_key, default_value in DEFAULT_SESSION_VALUES.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = default_value

# Migrate the older table label used by the previous app version.
if st.session_state.table == "Bacterial (11)":
    st.session_state.table = "Bacterial, Archaeal and Plant Plastid (11)"
elif st.session_state.table not in CODON_TABLE_OPTIONS:
    st.session_state.table = "Standard (1)"


# ============================================================
# GENERAL HELPERS
# ============================================================


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate the password policy used during registration and recovery."""
    if len(password) < 10:
        return False, "Password must contain at least 10 characters."

    if not re.search(r"[@$!%*?&#]", password):
        return (
            False,
            "Password must contain at least one special symbol: @, $, !, %, *, ?, &, or #.",
        )

    return True, "Strong password."



def is_valid_email(email_address: str) -> bool:
    """Perform basic email-format validation."""
    return bool(
        re.fullmatch(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            email_address.strip(),
        )
    )



def get_email_credentials() -> tuple[str, str]:
    """
    Load Gmail credentials for password recovery.

    Priority order:
    1. Environment variables
    2. Streamlit secrets
    3. Local fallback values inside app.py for demonstration

    Environment variable names:
        DNA_WORKSTATION_SENDER_EMAIL
        DNA_WORKSTATION_SENDER_PASSWORD

    Optional .streamlit/secrets.toml:
        sender_email = "yourgmail@gmail.com"
        sender_password = "your_gmail_app_password"
    """
    sender_email = os.getenv("DNA_WORKSTATION_SENDER_EMAIL", "").strip()
    sender_password = os.getenv("DNA_WORKSTATION_SENDER_PASSWORD", "").strip()

    try:
        secrets_email = st.secrets.get("sender_email", "")
        secrets_password = st.secrets.get("sender_password", "")

        if secrets_email:
            sender_email = str(secrets_email).strip()

        if secrets_password:
            sender_password = str(secrets_password).strip()

    except Exception:
        # The application can still start when no Streamlit secrets file exists.
        pass

    if not sender_email:
        sender_email = FALLBACK_SENDER_EMAIL.strip()

    if not sender_password:
        sender_password = FALLBACK_SENDER_PASSWORD.strip()

    return sender_email, sender_password

def send_verification_email(receiver_email: str, pin: int) -> tuple[bool, str]:
    """Send a temporary password-recovery verification code."""
    sender_email, sender_password = get_email_credentials()

    if (
        not sender_email
        or not sender_password
        or sender_email == "yourgmail@gmail.com"
        or sender_password == "your_gmail_app_password"
    ):
        return (
            False,
            "Email sender details are not configured. Replace "
            "FALLBACK_SENDER_EMAIL and FALLBACK_SENDER_PASSWORD inside app.py "
            "with your Gmail address and Gmail App Password, or configure "
            ".streamlit/secrets.toml / environment variables.",
        )

    email_body = f"""
Hello,

A password reset request was received for your DNA Workstation account.

Your temporary verification code is:

{pin}

This code expires in 10 minutes.

If you did not request a password reset, you may ignore this email.

Regards,
DNA Workstation System
""".strip()

    message = MIMEText(email_body)
    message["Subject"] = "DNA Workstation Password Reset Verification Code"
    message["From"] = sender_email
    message["To"] = receiver_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, message.as_string())

        return True, "Verification code sent successfully."

    except Exception as e:
        return (
            False,
            f"The verification email could not be sent. Actual error: {e}",
        )



def save_history_if_registered(
    sequence: str,
    result: str,
    organism: str,
) -> None:
    """Store history only for authenticated registered users."""
    if st.session_state.username != "Guest":
        save_search_to_history(
            st.session_state.username,
            sequence,
            result,
            organism=organism,
        )



def load_selected_example() -> None:
    """Load the currently selected learning example into the analysis form."""
    selected = EXAMPLE_SEQUENCES[st.session_state.selected_example]
    st.session_state.dna = selected["sequence"]
    st.session_state.table = selected["table"]
    st.session_state.last_analysis = None
    st.session_state.last_upload_hash = ""
    st.session_state.uploader_key += 1



def reset_analysis_workspace() -> None:
    """Reset only the analysis workspace while preserving login and theme."""
    st.session_state.dna = ""
    st.session_state.table = "Standard (1)"
    st.session_state.selected_example = "Select an example"
    st.session_state.last_analysis = None
    st.session_state.last_upload_hash = ""
    st.session_state.uploader_key += 1



def logout_user() -> None:
    """End the current session and clear account-recovery information."""
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.user_role = ""
    st.session_state.active_tab = "🔬 DNA Analysis Station"
    st.session_state.reset_pin = None
    st.session_state.reset_pin_created_at = None
    st.session_state.reset_email = ""
    st.session_state.last_analysis = None



def render_codon_visualization(mapping: list[dict[str, Any]]) -> None:
    """Display codons and amino acids as a simple student-friendly visual map."""
    complete_rows = [
        row
        for row in mapping
        if row.get("Role") != "Not translated"
    ]

    incomplete_rows = [
        row
        for row in mapping
        if row.get("Role") == "Not translated"
    ]

    if not complete_rows and not incomplete_rows:
        return

    codon_badges = []
    amino_badges = []

    role_colours = {
        "Start codon": ("#D1FAE5", "#065F46"),
        "Stop codon": ("#FEE2E2", "#991B1B"),
        "Amino acid codon": ("#DBEAFE", "#1E3A8A"),
    }

    for row in complete_rows:
        background, foreground = role_colours.get(
            row["Role"],
            ("#F3F4F6", "#111827"),
        )

        codon = html.escape(str(row["Codon"]))
        amino_name = html.escape(str(row["Amino Acid Name"]))

        codon_badges.append(
            f'<span style="display:inline-block;margin:4px;padding:8px 12px;'
            f'border-radius:8px;background:{background};color:{foreground};'
            f'font-weight:700;border:1px solid {foreground};">{codon}</span>'
        )

        amino_badges.append(
            f'<span style="display:inline-block;margin:4px;padding:8px 12px;'
            f'border-radius:8px;background:{background};color:{foreground};'
            f'font-weight:600;border:1px solid {foreground};">{amino_name}</span>'
        )

    if codon_badges:
        st.markdown("**DNA codons**")
        st.markdown("".join(codon_badges), unsafe_allow_html=True)
        st.markdown("**Amino acids**")
        st.markdown("".join(amino_badges), unsafe_allow_html=True)

    if incomplete_rows:
        remainder = html.escape(str(incomplete_rows[0]["Codon"]))
        st.warning(
            f"Incomplete final codon: {remainder}. These remaining bases were "
            "not translated because a complete codon requires three bases."
        )



def render_download_button() -> None:
    """Display a report-download button when analysis data are available."""
    if not st.session_state.last_analysis:
        return

    report_text = create_student_report(st.session_state.last_analysis)

    st.download_button(
        label="📥 Download Student Analysis Report",
        data=report_text,
        file_name="dna_workstation_student_report.txt",
        mime="text/plain",
        use_container_width=True,
    )


# ============================================================
# STUDENT LEARNING HUB
# ============================================================


def render_student_learning_hub() -> None:
    """Render tutorials, interpretation notes, and a mini learning check."""
    st.title("🎓 Student Learning Hub")
    st.write(
        "Use these short notes before or after an analysis to understand how "
        "DNA input becomes a protein result."
    )

    translation_tab, codon_tab, protein_tab, blast_tab, quiz_tab = st.tabs(
        [
            "DNA Translation",
            "Codons and ORFs",
            "Protein Properties",
            "BLAST",
            "Learning Check",
        ]
    )

    with translation_tab:
        st.subheader("DNA-to-Protein Translation")
        st.write(
            "Translation reads DNA in groups of three bases called codons. "
            "Each complete codon corresponds to an amino acid or a stop signal."
        )
        st.code(
            "DNA codons:    ATG | GCT | TTT | TAA\n"
            "Amino acids:   Met | Ala | Phe | Stop"
        )
        st.info(
            "ATG commonly marks the beginning of a coding region. In the "
            "standard genetic code, TAA, TAG, and TGA are stop codons."
        )

    with codon_tab:
        st.subheader("Codon Tables and Open Reading Frames")
        st.markdown(
            """
**Standard table (1)**  
Commonly used for nuclear DNA sequences.

**Vertebrate mitochondrial table (2)**  
Used for vertebrate mitochondrial DNA, where some codons have meanings that differ from the standard code.

**Bacterial, archaeal and plant plastid table (11)**  
Commonly used for bacterial, archaeal, and plastid sequences.

An **open reading frame (ORF)** begins with a valid start codon and ends with an in-frame stop codon without interruption.
"""
        )

    with protein_tab:
        st.subheader("Protein Property Interpretation")
        st.markdown(
            """
**Molecular weight**  
Estimates the mass of the translated protein in Daltons.

**Isoelectric point (pI)**  
Estimates the pH at which the protein has no overall electrical charge.

**Instability index**  
Provides an estimate of protein stability. A value below 40 is commonly interpreted as potentially stable.

**GRAVY**  
Provides a general indication of whether a protein is relatively hydrophobic or hydrophilic.
"""
        )

    with blast_tab:
        st.subheader("Understanding BLAST")
        st.write(
            "BLAST compares a submitted DNA sequence with known sequences in "
            "the NCBI nucleotide database."
        )
        st.markdown(
            """
**Accession number:** Identifier of the matched database record.  
**Identity percentage:** Percentage of matching positions in the alignment.  
**Query coverage:** Percentage of the submitted sequence represented in the alignment.  
**E-value:** Estimate of how likely the match could occur by chance; smaller values usually indicate stronger evidence.
"""
        )

    with quiz_tab:
        st.subheader("Mini Learning Check")

        with st.form("student_learning_quiz"):
            question_1 = st.radio(
                "1. Which codon commonly begins translation?",
                ["TAA", "ATG", "TAG", "TGA"],
            )
            question_2 = st.radio(
                "2. What does an instability index below 40 generally suggest?",
                [
                    "The sequence is DNA",
                    "The protein may be stable",
                    "No protein was translated",
                    "The BLAST search failed",
                ],
            )
            question_3 = st.radio(
                "3. What is the main purpose of BLAST?",
                [
                    "To create a user account",
                    "To compare a sequence with database records",
                    "To calculate a password hash",
                    "To select the visual theme",
                ],
            )

            submitted = st.form_submit_button("Check Answers")

        if submitted:
            score = 0
            score += question_1 == "ATG"
            score += question_2 == "The protein may be stable"
            score += question_3 == "To compare a sequence with database records"

            if score == 3:
                st.success("Excellent. You scored 3 out of 3.")
            elif score == 2:
                st.info("Good work. You scored 2 out of 3.")
            else:
                st.warning(
                    f"You scored {score} out of 3. Review the notes and try again."
                )


# ============================================================
# DYNAMIC THEME CONFIGURATION
# ============================================================

if st.session_state.current_theme == "Classic Pastel Pink (Default)":
    background_colour = "#FFD1DC"
    text_colour = "#13265C"
    button_colour = "#D875A2"
    heading_colour = "#111111"

elif st.session_state.current_theme == "High-Contrast Charcoal":
    background_colour = "#2B2B2B"
    text_colour = "#FFFFFF"
    button_colour = "#4F4F4F"
    heading_colour = "#FFD1DC"

else:
    background_colour = "#E0F2F1"
    text_colour = "#004D40"
    button_colour = "#26A69A"
    heading_colour = "#00796B"


# ============================================================
# CUSTOM VISUAL STYLING
# ============================================================

st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {background_colour};
        color: {text_colour};
    }}

    h1, h2, h3 {{
        color: {heading_colour};
    }}

    p, label {{
        color: {text_colour};
    }}

    textarea {{
        background-color: #F7F7F7 !important;
        border: 2px solid white !important;
        border-radius: 10px !important;
        box-shadow: 2px 2px 10px rgba(0, 0, 0, 0.15) !important;
        color: black !important;
    }}

    div[data-baseweb="select"] {{
        background-color: #F7F7F7 !important;
        border: 2px solid white !important;
        border-radius: 10px !important;
        box-shadow: 2px 2px 10px rgba(0, 0, 0, 0.15) !important;
    }}

    [data-testid="stFileUploader"] {{
        background-color: #F7F7F7;
        border: 2px solid white;
        border-radius: 10px;
        padding: 10px;
        box-shadow: 2px 2px 10px rgba(0, 0, 0, 0.15);
    }}

    [data-testid="stFileUploader"] button {{
        background-color: white;
        color: black;
        border-radius: 8px;
    }}

    .stButton > button,
    .stDownloadButton > button {{
        background-color: {button_colour};
        color: black !important;
        border-radius: 10px;
        border: none;
        padding: 10px 20px;
        box-shadow: 2px 2px 10px rgba(0, 0, 0, 0.15);
        width: 100%;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SECURITY GATEWAY
# ============================================================

if not st.session_state.logged_in:
    st.title("DNA to Protein Translator 🧬")
    st.write(
        "A guided educational workstation for undergraduate bioinformatics students."
    )

    authentication_choice = st.sidebar.selectbox(
        "Access Gateway",
        ["Login", "Sign Up", "Forgot Password"],
    )

    if authentication_choice == "Login":
        st.subheader("🔑 System Login")

        with st.form("login_form"):
            user_input = st.text_input("Username")
            password_input = st.text_input("Password", type="password")
            login_submitted = st.form_submit_button("Log In")

        if login_submitted:
            if not user_input or not password_input:
                st.warning("Enter both your username and password.")
            elif login_user(user_input.strip(), password_input):
                st.session_state.logged_in = True
                st.session_state.username = user_input.strip()
                st.session_state.user_role = get_user_role(user_input.strip())
                st.session_state.active_tab = "🔬 DNA Analysis Station"
                st.success(f"Welcome back, {user_input.strip()}.")
                st.rerun()
            else:
                st.error("The username or password is incorrect.")

        if st.button("Continue as Guest 👤", use_container_width=True):
            st.session_state.logged_in = True
            st.session_state.username = "Guest"
            st.session_state.user_role = "guest"
            st.session_state.active_tab = "🔬 DNA Analysis Station"
            st.rerun()

        st.caption(
            "Guest users may perform analyses, but search history is not stored."
        )

    elif authentication_choice == "Sign Up":
        st.subheader("📝 Create Undergraduate Student Profile")

        with st.form("registration_form"):
            new_username = st.text_input("Create Username")
            new_email = st.text_input("Institutional Email Address")
            new_password = st.text_input(
                "Create Password",
                type="password",
                help=(
                    "Use at least 10 characters and include one of these symbols: "
                    "@, $, !, %, *, ?, &, #."
                ),
            )
            registration_submitted = st.form_submit_button("Register Account")

        if registration_submitted:
            is_strong, password_message = validate_password_strength(new_password)

            if not new_username.strip() or not new_email.strip() or not new_password:
                st.warning("All registration fields are required.")
            elif not is_valid_email(new_email):
                st.error("Enter a valid email address.")
            elif not is_strong:
                st.error(password_message)
            else:
                success, database_message = add_user(
                    new_username.strip(),
                    new_email.strip().lower(),
                    new_password,
                )

                if success:
                    st.success(
                        "Student profile registered successfully. Select Login to continue."
                    )
                else:
                    st.error(f"Registration could not be completed: {database_message}")

    elif authentication_choice == "Forgot Password":
        st.subheader("🔄 Account Password Recovery")

        with st.form("request_reset_form"):
            recovery_email = st.text_input("Enter Registered Email Address")
            request_submitted = st.form_submit_button("Send Verification Code")

        if request_submitted:
            normalized_email = recovery_email.strip().lower()

            if not is_valid_email(normalized_email):
                st.error("Enter a valid registered email address.")
            else:
                user_record = verify_email_exists(normalized_email)

                if user_record:
                    generated_pin = secrets.randbelow(900000) + 100000
                    sent, email_message = send_verification_email(
                        normalized_email,
                        generated_pin,
                    )

                    if sent:
                        st.session_state.reset_pin = generated_pin
                        st.session_state.reset_pin_created_at = time.time()
                        st.session_state.reset_email = normalized_email
                        st.success(
                            "A six-digit verification code was sent to your "
                            "registered email address."
                        )
                    else:
                        st.error(email_message)
                else:
                    st.error("No registered account was found for that email address.")

        if st.session_state.reset_pin is not None:
            st.divider()
            st.write("The verification code expires 10 minutes after it is sent.")

            with st.form("complete_reset_form"):
                entered_pin = st.text_input(
                    "Enter 6-Digit Verification Code",
                    max_chars=6,
                )
                updated_password = st.text_input(
                    "Create New Secure Password",
                    type="password",
                    help=(
                        "Use at least 10 characters and include one of these symbols: "
                        "@, $, !, %, *, ?, &, #."
                    ),
                )
                reset_submitted = st.form_submit_button("Change Password")

            if reset_submitted:
                is_strong, password_message = validate_password_strength(
                    updated_password
                )

                pin_created_at = st.session_state.reset_pin_created_at or 0
                pin_expired = (
                    time.time() - pin_created_at
                    > RESET_PIN_LIFETIME_SECONDS
                )

                if pin_expired:
                    st.error(
                        "The verification code has expired. Request a new code."
                    )
                    st.session_state.reset_pin = None
                    st.session_state.reset_pin_created_at = None
                    st.session_state.reset_email = ""
                elif not entered_pin.isdigit() or len(entered_pin) != 6:
                    st.error("Enter the complete six-digit verification code.")
                elif entered_pin != str(st.session_state.reset_pin):
                    st.error("The verification code is incorrect.")
                elif not is_strong:
                    st.error(password_message)
                elif update_password(
                    st.session_state.reset_email,
                    updated_password,
                ):
                    st.success(
                        "Password updated successfully. Select Login to access your account."
                    )
                    st.session_state.reset_pin = None
                    st.session_state.reset_pin_created_at = None
                    st.session_state.reset_email = ""
                else:
                    st.error("The password could not be updated in the database.")


# ============================================================
# PROTECTED APPLICATION INTERFACE
# ============================================================

else:
    st.sidebar.markdown(f"## 👋 Hi, {st.session_state.username}!")

    current_user_role = st.session_state.get("user_role", "user")
    if current_user_role == "admin":
        st.sidebar.success("Admin access enabled.")

    if st.session_state.username == "Guest":
        st.sidebar.info("Guest mode: history recording is OFF.")

    st.sidebar.divider()
    st.sidebar.markdown("### 🗺️ Navigation Menu")

    navigation_items = [
        "🔬 DNA Analysis Station",
        "📊 Search History Log",
        "🎓 Student Learning Hub",
        "📘 User Guide Manual",
        "⚙️ System Settings",
    ]

    if st.session_state.get("user_role") == "admin":
        navigation_items.append("🛡️ Admin Dashboard")

    for navigation_item in navigation_items:
        if st.sidebar.button(navigation_item):
            st.session_state.active_tab = navigation_item
            st.rerun()

    st.sidebar.divider()

    st.sidebar.button(
        "Log Out / Exit Context",
        on_click=logout_user,
        use_container_width=True,
    )

    if st.session_state.active_tab == "🛡️ Admin Dashboard":
        if st.session_state.get("user_role") == "admin":
            render_admin_dashboard()
        else:
            st.error("Admin access is required to view this page.")

    elif st.session_state.active_tab == "📊 Search History Log":
        if st.session_state.username == "Guest":
            st.title("📊 Search History Log")
            st.info(
                "History recording is OFF for guest users. Create an account or "
                "log in to save and revisit previous analyses."
            )
        else:
            render_history_dashboard(st.session_state.username)

    elif st.session_state.active_tab == "🎓 Student Learning Hub":
        render_student_learning_hub()

    elif st.session_state.active_tab == "📘 User Guide Manual":
        render_user_guide()

    elif st.session_state.active_tab == "⚙️ System Settings":
        render_settings_panel()

    elif st.session_state.active_tab == "🔬 DNA Analysis Station":
        st.title("DNA to Protein Translator 🧬")
        st.write(
            "Follow the guided steps to clean, translate, interpret, and validate "
            "a DNA sequence."
        )

        # ----------------------------------------------------
        # STEP 1: INPUT
        # ----------------------------------------------------
        st.header("Step 1: Select, Upload, or Enter a DNA Sequence")

        st.selectbox(
            "Built-in Learning Example",
            list(EXAMPLE_SEQUENCES.keys()),
            key="selected_example",
        )

        st.caption(EXAMPLE_SEQUENCES[st.session_state.selected_example]["objective"])

        example_col, reset_col = st.columns(2)

        with example_col:
            st.button(
                "Load Selected Example",
                on_click=load_selected_example,
                use_container_width=True,
            )

        with reset_col:
            st.button(
                "Reset Analysis Workspace",
                on_click=reset_analysis_workspace,
                use_container_width=True,
            )

        uploaded_file = st.file_uploader(
            "Upload FASTA or TXT file",
            type=["fasta", "fa", "fna", "txt"],
            key=f"uploader_{st.session_state.uploader_key}",
        )

        if uploaded_file is not None:
            uploaded_bytes = uploaded_file.getvalue()
            upload_hash = hashlib.sha256(uploaded_bytes).hexdigest()

            if upload_hash != st.session_state.last_upload_hash:
                try:
                    uploaded_content = uploaded_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    uploaded_content = uploaded_bytes.decode(
                        "utf-8",
                        errors="replace",
                    )

                st.session_state.dna = uploaded_content
                st.session_state.last_upload_hash = upload_hash
                st.session_state.last_analysis = None

        st.text_area(
            "DNA Sequence",
            key="dna",
            height=180,
            help=(
                "Paste a raw DNA sequence or FASTA record. The cleaning report "
                "will show spaces, numbers, headers, symbols, and unsupported "
                "letters found in the input."
            ),
        )

        st.selectbox(
            "Select Genetic Code Table",
            list(CODON_TABLE_OPTIONS.keys()),
            key="table",
            help=(
                "Choose the genetic code that matches the biological source of "
                "the sequence."
            ),
        )

        table_number = CODON_TABLE_OPTIONS[st.session_state.table]

        action_col_1, action_col_2 = st.columns(2)

        with action_col_1:
            translate_clicked = st.button(
                "🧬 Run Guided Translation Analysis",
                use_container_width=True,
            )

        with action_col_2:
            blast_clicked = st.button(
                "🔎 Validate Sequence with BLAST",
                use_container_width=True,
            )

        # ----------------------------------------------------
        # GUIDED TRANSLATION ANALYSIS
        # ----------------------------------------------------
        if translate_clicked:
            original_input = st.session_state.dna

            if not original_input.strip():
                st.warning("Enter, upload, or load a DNA sequence first.")
            else:
                cleaning_report = get_cleaning_report(original_input)
                cleaned_dna = cleaning_report["cleaned_sequence"]

                st.header("Step 2: Transparent Sequence-Cleaning Report")

                metric_1, metric_2, metric_3, metric_4 = st.columns(4)
                metric_1.metric("Original Characters", cleaning_report["original_length"])
                metric_2.metric("Cleaned Nucleotides", cleaning_report["cleaned_length"])
                metric_3.metric("Complete Codons", cleaning_report["complete_codon_count"])
                metric_4.metric("Removed Characters", cleaning_report["total_characters_removed"])

                with st.expander("View Complete Cleaning Details", expanded=True):
                    detail_col_1, detail_col_2, detail_col_3, detail_col_4 = st.columns(4)
                    detail_col_1.metric(
                        "FASTA Headers",
                        cleaning_report["fasta_headers_removed"],
                    )
                    detail_col_2.metric(
                        "Whitespace",
                        cleaning_report["whitespace_removed"],
                    )
                    detail_col_3.metric("Digits", cleaning_report["digits_removed"])
                    detail_col_4.metric(
                        "Formatting Symbols",
                        cleaning_report["symbols_removed"],
                    )

                    st.write("**Original input**")
                    st.code(cleaning_report["original_sequence"] or "No input")
                    st.write("**Cleaned DNA sequence**")
                    st.code(cleaned_dna or "No valid DNA bases remain")

                if cleaning_report["has_invalid_letters"]:
                    invalid_details = ", ".join(
                        f"{item['character']} at position {item['position']}"
                        for item in cleaning_report["invalid_letter_details"]
                    )
                    st.error(
                        "Unsupported nucleotide letters were detected: "
                        f"{invalid_details}. Correct the input before translation."
                    )

                elif not cleaned_dna or not validate_dna(cleaned_dna):
                    st.error(
                        "No valid DNA sequence remains after cleaning. DNA input "
                        "must contain A, T, G, or C."
                    )

                else:
                    st.success("Sequence cleaning and validation completed.")

                    st.header("Step 3: Nucleotide Distribution")
                    nucleotide_counts = {
                        base: cleaned_dna.count(base)
                        for base in "ATGC"
                    }
                    nucleotide_dataframe = pd.DataFrame(
                        nucleotide_counts.items(),
                        columns=["Base", "Count"],
                    )
                    st.bar_chart(nucleotide_dataframe.set_index("Base"))

                    st.header("Step 4: Visual Codon-to-Amino-Acid Mapping")
                    codon_mapping = build_codon_mapping(
                        cleaned_dna,
                        table=table_number,
                    )
                    render_codon_visualization(codon_mapping)

                    codon_dataframe = pd.DataFrame(codon_mapping)
                    st.dataframe(
                        codon_dataframe,
                        use_container_width=True,
                        hide_index=True,
                    )

                    if cleaning_report["incomplete_base_count"]:
                        st.warning(
                            f"The sequence ends with "
                            f"{cleaning_report['incomplete_base_count']} incomplete "
                            "base(s). These bases are not translated."
                        )

                    st.header("Step 5: Protein Translation and Feature Extraction")

                    try:
                        protein_sequence = translate_dna(
                            cleaned_dna,
                            table=table_number,
                        )
                    except ValueError as translation_error:
                        st.error(str(translation_error))
                        protein_sequence = ""

                    if not protein_sequence:
                        st.warning(
                            "No amino-acid sequence was produced. The sequence may "
                            "be shorter than one complete codon or may begin with a "
                            "stop signal."
                        )
                    else:
                        st.success("Translated Protein Sequence")
                        st.code(protein_sequence)

                        try:
                            protein_details = get_protein_details(protein_sequence)
                        except ValueError as protein_error:
                            st.error(str(protein_error))
                            protein_details = None

                        if protein_details:
                            protein_col_1, protein_col_2, protein_col_3, protein_col_4 = st.columns(4)

                            protein_col_1.metric(
                                "Molecular Weight",
                                f"{protein_details['molecular_weight']['value']} "
                                f"{protein_details['molecular_weight']['unit']}",
                            )
                            protein_col_2.metric(
                                "Isoelectric Point",
                                protein_details["isoelectric_point"]["value"],
                            )
                            protein_col_3.metric(
                                "Instability Index",
                                protein_details["instability_index"]["value"],
                            )
                            protein_col_4.metric(
                                "GRAVY",
                                protein_details["gravy"]["value"],
                            )

                            st.subheader("Educational Interpretation")
                            interpretations = interpret_analysis_results(
                                protein_details
                            )

                            for interpretation in interpretations:
                                st.info(interpretation)

                            with st.expander("Understand Each Protein Property"):
                                st.write(
                                    "**Molecular Weight:** "
                                    + protein_details["molecular_weight"]["desc"]
                                )
                                st.write(
                                    "**Isoelectric Point:** "
                                    + protein_details["isoelectric_point"]["desc"]
                                )
                                st.write(
                                    "**Instability Index:** "
                                    + protein_details["instability_index"]["desc"]
                                )
                                st.write(
                                    "**GRAVY:** "
                                    + protein_details["gravy"]["desc"]
                                )
                        else:
                            interpretations = []

                        st.header("Step 6: Open Reading Frame Assessment")
                        open_reading_frame = find_orf(
                            cleaned_dna,
                            table=table_number,
                        )

                        if open_reading_frame:
                            st.success("A complete open reading frame was identified.")
                            st.code(open_reading_frame)
                            st.caption(
                                "The identified ORF begins with a valid start codon "
                                "and ends with an in-frame stop codon."
                            )
                        else:
                            st.warning(
                                "No complete start-to-stop open reading frame was "
                                "identified in the forward reading frames."
                            )

                        st.session_state.last_analysis = {
                            "original_sequence": original_input,
                            "cleaned_sequence": cleaned_dna,
                            "codon_table": table_number,
                            "codon_table_name": get_genetic_code_name(table_number),
                            "protein_sequence": protein_sequence,
                            "molecular_weight": (
                                protein_details["molecular_weight"]["value"]
                                if protein_details
                                else "Not available"
                            ),
                            "isoelectric_point": (
                                protein_details["isoelectric_point"]["value"]
                                if protein_details
                                else "Not available"
                            ),
                            "instability_index": (
                                protein_details["instability_index"]["value"]
                                if protein_details
                                else "Not available"
                            ),
                            "gravy": (
                                protein_details["gravy"]["value"]
                                if protein_details
                                else "Not available"
                            ),
                            "orf": (
                                open_reading_frame
                                if open_reading_frame
                                else "No complete open reading frame was identified."
                            ),
                            "blast_title": "BLAST analysis was not performed.",
                            "blast_identity": "Not available",
                            "blast_accession": "Not available",
                            "interpretations": interpretations,
                        }

                        save_history_if_registered(
                            cleaned_dna,
                            protein_sequence,
                            organism="Direct Translation",
                        )

                        st.header("Step 7: Download Student Analysis Report")
                        render_download_button()

        # ----------------------------------------------------
        # BLAST VALIDATION
        # ----------------------------------------------------
        if blast_clicked:
            original_input = st.session_state.dna

            if not original_input.strip():
                st.warning("Enter, upload, or load a DNA sequence first.")
            else:
                cleaning_report = get_cleaning_report(original_input)
                cleaned_dna = cleaning_report["cleaned_sequence"]

                if cleaning_report["has_invalid_letters"]:
                    st.error(
                        "Correct unsupported nucleotide letters before submitting "
                        "the sequence to NCBI BLAST."
                    )
                elif not cleaned_dna or not validate_dna(cleaned_dna):
                    st.error("A valid DNA sequence is required for BLAST.")
                else:
                    with st.spinner(
                        "Submitting the sequence to the NCBI nucleotide database..."
                    ):
                        blast_result = blast_sequence(cleaned_dna)

                    if "error" in blast_result:
                        st.error(blast_result["error"])

                        if blast_result.get("technical_details"):
                            with st.expander("Technical details"):
                                st.code(blast_result["technical_details"])
                    else:
                        st.success("Sequence alignment completed successfully.")
                        st.subheader("BLAST Alignment Summary")

                        metric_1, metric_2, metric_3, metric_4 = st.columns(4)
                        metric_1.metric(
                            "Accession",
                            blast_result["accession"],
                        )
                        metric_2.metric(
                            "Identity",
                            f"{blast_result['identity']}%",
                        )
                        metric_3.metric(
                            "Query Coverage",
                            f"{blast_result.get('query_coverage', 'N/A')}%",
                        )
                        metric_4.metric(
                            "E-value",
                            blast_result.get("e_value", "N/A"),
                        )

                        with st.expander(
                            "View Matched Database Record",
                            expanded=True,
                        ):
                            st.write(f"**Description:** {blast_result['title']}")
                            st.write(
                                f"**Alignment length:** "
                                f"{blast_result.get('alignment_length', 'N/A')} bases"
                            )

                        save_history_if_registered(
                            cleaned_dna,
                            f"Accession: {blast_result['accession']}",
                            organism=blast_result["title"],
                        )

                        if st.session_state.last_analysis:
                            st.session_state.last_analysis.update(
                                {
                                    "blast_title": blast_result["title"],
                                    "blast_identity": f"{blast_result['identity']}%",
                                    "blast_accession": blast_result["accession"],
                                }
                            )
                        else:
                            st.session_state.last_analysis = {
                                "original_sequence": original_input,
                                "cleaned_sequence": cleaned_dna,
                                "codon_table": table_number,
                                "codon_table_name": get_genetic_code_name(
                                    table_number
                                ),
                                "protein_sequence": "Translation was not performed.",
                                "molecular_weight": "Not available",
                                "isoelectric_point": "Not available",
                                "instability_index": "Not available",
                                "gravy": "Not available",
                                "orf": "ORF analysis was not performed.",
                                "blast_title": blast_result["title"],
                                "blast_identity": f"{blast_result['identity']}%",
                                "blast_accession": blast_result["accession"],
                                "interpretations": [
                                    (
                                        "The submitted DNA sequence produced a "
                                        f"{blast_result['identity']}% identity match "
                                        "with the top NCBI nucleotide database record."
                                    )
                                ],
                            }

                        st.subheader("Updated Student Analysis Report")
                        render_download_button()
