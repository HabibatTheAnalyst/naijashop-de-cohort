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