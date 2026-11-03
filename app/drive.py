from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from config import SECRETS_DIR

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]   
CREDENTIALS = SECRETS_DIR / "credentials.json" 
TOKEN = SECRETS_DIR / "token.json" 


def connect():
    """Sign in in the browser the first time; after that the saved token is used, and refreshed when it expires."""
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if TOKEN.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
        creds = flow.run_local_server(port=0)
        
    TOKEN.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds)


def list_files(drive, folder_id):
    """Every file in the folder: id, name, type, and Drive's fingerprint of the content (md5Checksum).
    Google Docs and Sheets have no md5Checksum."""
    files, page = [], None
    while True:
        result = drive.files().list(
            # q=f"'{folder_id}' in parents and trashed = false",
            q=f"'{folder_id}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'",
            fields="nextPageToken, files(id, name, mimeType, md5Checksum, modifiedTime)",
            pageToken=page).execute()
        files += result["files"]
        page = result.get("nextPageToken")
        if not page:
            return files


def download(drive, file, path):
    """Save one Drive file to path. Google Docs and Sheets can't be downloaded as they are:
    an empty file is saved instead, so step 2 marks it as failed (not a PDF)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if file["mimeType"].startswith("application/vnd.google-apps"):
        path.write_bytes(b"")
        return
    with open(path, "wb") as out:
        downloader = MediaIoBaseDownload(out, drive.files().get_media(fileId=file["id"]))
        done = False
        while not done:
            _, done = downloader.next_chunk()