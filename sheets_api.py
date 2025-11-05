import os
import json
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime

def get_service():
    """Створює Google Sheets API service з credentials з Replit Secrets"""
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not google_creds_json:
        raise ValueError("❌ GOOGLE_CREDENTIALS_JSON не знайдено у Replit Secrets!")
    
    # Парсимо JSON з credentials
    creds_data = json.loads(google_creds_json)
    
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = service_account.Credentials.from_service_account_info(
        creds_data, scopes=SCOPES
    )
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()

def append_task(name, description, tag="#інше"):
    """Додає задачу до Google Sheets"""
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise ValueError("❌ SPREADSHEET_ID не знайдено у Replit Secrets!")
    
    sheet = get_service()

    # Час у зручному текстовому форматі
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_row = [
        "",             # Task ID (порожній — заповнимо пізніше)
        name,           # Назва
        description,    # Опис
        "", "", "", "", "",  # інші поля залишаємо порожніми
        tag,
        "FALSE",
        timestamp,      # Created
        timestamp       # Updated
    ]

    request = sheet.values().append(
        spreadsheetId=spreadsheet_id,
        range="A:L",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [new_row]}
    )
    response = request.execute()
    return response
