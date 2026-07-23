"""
One-time setup: run this manually once to authorize Google Calendar access.
Opens a browser for you to log in and consent, then saves token.json with a
refresh token so book_tennis.py can create calendar events unattended.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

def main():
    flow = InstalledAppFlow.from_client_secrets_file("calendar_credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    with open("token.json", "w") as f:
        f.write(creds.to_json())
    print("Done! token.json saved.")

if __name__ == "__main__":
    main()
