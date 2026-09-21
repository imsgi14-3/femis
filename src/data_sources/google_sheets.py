import gspread
from oauth2client.service_account import ServiceAccountCredentials
from src.utils.logger import setup_logger

logger = setup_logger("google_sheets")


class GoogleSheetsReader:
    """Read student data from a Google Sheets spreadsheet (exported from Google Forms)."""

    SCOPES = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(self, credentials_path: str, spreadsheet_id: str = None):
        self.credentials_path = credentials_path
        self.spreadsheet_id = spreadsheet_id
        self._client = None

    def _get_client(self) -> gspread.Client:
        if self._client is None:
            creds = ServiceAccountCredentials.from_json_keyfile_name(self.credentials_path, self.SCOPES)
            self._client = gspread.authorize(creds)
        return self._client

    def read_all(self, sheet_name: str = None) -> list[dict]:
        """Read all rows from a sheet. Returns list of dicts (column header -> value)."""
        client = self._get_client()
        spreadsheet = client.open_by_key(self.spreadsheet_id)

        if sheet_name:
            worksheet = spreadsheet.worksheet(sheet_name)
        else:
            worksheet = spreadsheet.sheet1

        rows = worksheet.get_all_records()
        logger.info(f"Read {len(rows)} rows from sheet: {worksheet.title}")
        return rows

    def read_from_url(self, url: str) -> list[dict]:
        """Read directly from a Google Sheets URL."""
        client = self._get_client()
        spreadsheet = client.open_by_url(url)
        worksheet = spreadsheet.sheet1
        rows = worksheet.get_all_records()
        logger.info(f"Read {len(rows)} rows from: {url}")
        return rows
