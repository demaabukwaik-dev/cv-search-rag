from pathlib import Path
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

CVS_DIR = BASE_DIR / "data" / "cvs"
EXTRACTED_DIR = BASE_DIR / "data" / "extracted"
CHUNKS_DIR = BASE_DIR / "data" / "chunks"



# ---------- Intake: field from embeddings ----------

# Fields we don't hire for: a CV closest to one of these goes to review
OTHER_FIELDS = {
    "Human Resources": "HR specialist or recruiter: hiring, onboarding, employee relations, "
                       "performance reviews, HR policies, training and development.",
    "Sales and Customer Service": "Sales representative or customer service agent: selling products, sales targets, "
                                  "client accounts, call center, customer support.",
    "Healthcare": "Nurse, doctor, pharmacist or medical staff: patient care, clinical procedures, hospitals and clinics.",
    "Education": "Teacher at a school: lesson planning, classroom teaching, student assessment, curriculum.",
    "Civil and Mechanical Engineering": "Civil or mechanical engineer: construction sites, structural design, "
                                        "building projects, machinery and maintenance.",
    "Legal": "Lawyer or legal advisor: contracts, legal cases, regulations, litigation.",
    "Hospitality and Logistics": "Hotel, restaurant, travel, supply chain or warehouse staff: operations, shipping, "
                                 "inventory, guest services.",
}

MIN_FIELD_SCORE = 0.70   # closest field below this -> review
MIN_FIELD_GAP = 0.02     # first and second field closer than this -> review

# ---------- Intake: ATS template ----------
MAX_FAR_RIGHT_SHARE = 0.25   # more than this share of a page's lines starting after its first third -> two columns (review)


# The standard CV sections, and the headings that mean each one
SECTIONS = {
    "SUMMARY":              ["summary", "professional summary", "career summary", "profile", "about me", "objective"],
    "WORK EXPERIENCE":      ["experience", "work experience", "professional experience", "employment history"],
    "VOLUNTEER EXPERIENCE": ["volunteer experience"],
    "EDUCATION":            ["education"],
    "SKILLS":               ["skills", "technical skills", "core skills", "key skills", "core competencies"],
    "PROJECTS":             ["projects", "selected projects"],
    "CERTIFICATIONS":       ["certifications", "certificates", "licenses & certifications"],
    "LANGUAGES":            ["languages"],
    "AWARDS":               ["awards", "achievements"],
}

# The sections an ATS-compliant CV must have
REQUIRED_SECTIONS = ["SUMMARY", "WORK EXPERIENCE", "EDUCATION", "SKILLS"]


DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]   # the Drive folder the CVs arrive in
SECRETS_DIR = BASE_DIR / "secrets"                # Google sign-in files (never committed)


def cv_file(drive_file_id, filename):
    """Where a CV is kept on disk: a folder per Drive file, so two files with the same name never clash."""
    return CVS_DIR / drive_file_id / filename