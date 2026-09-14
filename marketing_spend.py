"""
NaijaShop marketing spend ingestion - Method B: Google Sheets API (private sheets)

Use this instead of Method A when the sheet CANNOT be made public, even via
"Publish to web." Same end result, more setup, no public exposure.

ONE-TIME SETUP (do this once, not every run):
1. Go to console.cloud.google.com -> create a project (or reuse one)
2. APIs & Services -> Library -> enable "Google Sheets API"
3. APIs & Services -> Credentials -> Create Credentials -> Service Account
4. Give it a name (e.g. "naijashop-ingestion"), no special roles needed
5. Open the service account -> Keys -> Add Key -> Create new key -> JSON
   This downloads a .json credentials file - keep it private, never commit
   it to Git (add it to .gitignore)
6. Open the actual Google Sheet -> Share -> paste in the service account's
   email (looks like naijashop-ingestion@yourproject.iam.gserviceaccount.com)
   -> give it "Viewer" access
   (This step is what makes the private sheet readable by the script -
   without it, the API will return a permissions error)

Usage:
    python ingest_marketing_sheets_api.py \
        --credentials service_account.json \ == --credentials naijashop-ingestion-70e2d912e6fa.json
        --sheet-id 1AbCdEfGhIjKlMnOpQrStUvWxYz \ == --sheet-id 1_Fv13CpdgdO6UthSnw7cBvJyXBlvJ8MQ0nJUAPkVLjM
        --range "Sheet1!A1:G100" \ == --range "naijashop_marketing_ad_spend.csv!A1:G308"
        --dsn "dbname=naijashop user=postgres password=Joey4432 host=localhost"

The --sheet-id is the long ID in the sheet's URL, between /d/ and /edit

FIXED VERSION: primary key is (campaign_id, spend_date) together, not campaign_id
alone - this matters because the real sheet logs spend PER DAY per campaign,
so the same campaign_id legitimately appears many times with different dates.

"""
 
import argparse
import sys
 
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS marketing_spend (
    campaign_id     VARCHAR(20) NOT NULL,
    campaign_name   VARCHAR(150) NOT NULL,
    channel         VARCHAR(50) NOT NULL,
    spend_date      DATE NOT NULL,
    amount_ngn      NUMERIC(12, 2) NOT NULL,
    clicks          INTEGER,
    conversions     INTEGER,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (campaign_id, spend_date)
);
"""
 
# Now keyed on BOTH campaign_id and spend_date - so "CMP001" on 2026-08-01
# and "CMP001" on 2026-08-02 are two different, valid rows. Only a genuine
# re-run for the exact same campaign+day updates the existing row instead
# of duplicating it.
UPSERT_SQL = """
INSERT INTO marketing_spend
    (campaign_id, campaign_name, channel, spend_date, amount_ngn, clicks, conversions)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (campaign_id, spend_date) DO UPDATE SET
    campaign_name = EXCLUDED.campaign_name,
    channel       = EXCLUDED.channel,
    amount_ngn    = EXCLUDED.amount_ngn,
    clicks        = EXCLUDED.clicks,
    conversions   = EXCLUDED.conversions,
    loaded_at     = now();
"""
 
 
def fetch_sheet_rows(credentials_path: str, sheet_id: str, cell_range: str) -> list:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
 
    creds = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    service = build("sheets", "v4", credentials=creds)
 
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=cell_range
    ).execute()
 
    values = result.get("values", [])
    if not values:
        raise ValueError("Sheet returned no rows - check the range and sharing settings")
 
    header, *rows = values
    return [dict(zip(header, row)) for row in rows]
 
 
def load_to_postgres(dsn: str, rows: list):
    import psycopg2
 
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
 
    loaded = 0
    for row in rows:
        try:
            cur.execute(UPSERT_SQL, (
                row["campaign_id"],
                row["campaign_name"],
                row["channel"],
                row["spend_date"],
                float(row["amount_ngn"]),
                int(row["clicks"]) if row.get("clicks") else None,
                int(row["conversions"]) if row.get("conversions") else None,
            ))
            loaded += 1
        except Exception as e:
            print(f"  skipped a row (bad data?): {row} -- {e}", file=sys.stderr)
 
    conn.commit()
    cur.close()
    conn.close()
    return loaded
 
 
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--sheet-id", required=True)
    parser.add_argument("--range", default="naijashop_marketing_ad_spend.csv!A1:G308")
    parser.add_argument(
        "--dsn",
        default="dbname=naijashop user=postgres password=Joe4432 host=localhost",
    )
    args = parser.parse_args()
 
    print("Fetching marketing sheet via Google Sheets API...")
    try:
        rows = fetch_sheet_rows(args.credentials, args.sheet_id, args.range)
    except Exception as e:
        print(f"ERROR: could not read sheet: {e}", file=sys.stderr)
        sys.exit(1)
 
    print(f"  found {len(rows)} rows in the sheet")
 
    try:
        loaded = load_to_postgres(args.dsn, rows)
    except Exception as e:
        print(f"ERROR: could not load into Postgres: {e}", file=sys.stderr)
        sys.exit(1)
 
    print(f"Loaded {loaded} rows into marketing_spend table.")
 
 
if __name__ == "__main__":
    main()