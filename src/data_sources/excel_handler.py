import openpyxl
import csv
from pathlib import Path
from src.utils.logger import setup_logger

logger = setup_logger("excel_handler")


class ExcelHandler:
    """Read student data from Excel (.xlsx) or CSV files."""

    def read_excel(self, file_path: str, sheet_name: str = None) -> list[dict]:
        """Read an Excel file and return list of dicts."""
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

        if sheet_name:
            ws = wb[sheet_name]
        else:
            ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[0])]
        data = []
        for row in rows[1:]:
            record = {}
            for header, value in zip(headers, row):
                record[header] = value
            data.append(record)

        wb.close()
        logger.info(f"Read {len(data)} rows from Excel: {file_path}")
        return data

    def read_csv(self, file_path: str) -> list[dict]:
        """Read a CSV file and return list of dicts."""
        data = []
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(dict(row))
        logger.info(f"Read {len(data)} rows from CSV: {file_path}")
        return data

    def read_file(self, file_path: str) -> list[dict]:
        """Auto-detect file type and read."""
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            return self.read_csv(file_path)
        elif ext in {".xlsx", ".xls"}:
            return self.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
