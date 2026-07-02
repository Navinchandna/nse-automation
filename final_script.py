import os
import io
import json
import zipfile
import pandas as pd
from datetime import datetime, timedelta
import requests
import urllib3
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import sys

# Warnings बंद करना
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

current_download_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
headers = {'User-Agent': 'Mozilla/5.0'}

# --- GOOGLE SHEETS CONNECTOR (DIRECT SECURE CONFIG) ---
print("Connecting to Google Sheets...")
try:
    # अपनी .json फाइल से देखकर नीचे इन 3 बॉक्स में सही वैल्यू भरें:
    creds_dict = {
        "type": "service_account",
        "project_id": "nse-automation-tracker", # अगर प्रोजेक्ट आईडी अलग है तो बदलें
        "private_key_id": "3090e631715075a173e7f13f3fb68456d0881c2b",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDCm7ZzAdMqNwep\nspR3do/Nzjv6kg+5WHr2SSH57QQ5nCHFv43qIP2TTh4w7Hj5Y9WYrFTaGzos6ZXC\nofErHmR/rlHZXOfUEZMK2YpMJlk07HuNP0QckDCAo7/8hMz2WL2H70aL3dMQO8pf\nYWpk2LMqhukDxQ1cx6+pDdCNDHmLO2UROZtDTjUJkAtKKkVXBB+fXeebFfpkdaa3\n8220q3J0cyE7lPNsze7cnSWZCJHmUGc1jJRX4Bb2PGZohdsZ7c3J9xjdJ+KiT/x3\n4sQtSic7ekpRh4AsCCSjeuZ1VPm1G9ZQs1aododQFgXphWD+PfClfvzL/zN4J4wT\n2aKxI8IbAgMBAAECggEATXLu/4JAadKQyCZ8E7cpr/xdvnEWtOrTtOSSEwcS4WKT\nxkFf10fd4xv5w/q4gngK78HV2x9u3aTwpw8QDdsAoBfeFyV0Vd/Qp0bAVWIFqpxa\n53HAR6XSx79jjrnDYF8cvtapOszDTPiep6r7Trs3QruCTK/Fi6Ek9aC72QaX8KK2\nK53CGMzun27tZVzPPoFg3/YNXxYiD3D2+XCHQcl6NO4+MFa2owFZHlajYOhIl1Ul\nsb7+Bn0/XnyAQeNHBcAkKTl1mH25x9uj1mq+z9ydhqi4yyyXVgL5zp75nQrGjetY\nbpr0oznNWqoazhcp6YV28sHA1nBXvQKQteWso1LmMQKBgQD2BDz6ruyVGcsjpMJF\n9c/LqcyAU3huqZbfrbnq7vcW4cTy0dwQ/ydwLMTII8D0Z09X+7tdML0aO6ZBXdsG\nvbBy1b0ZMnsOMT0oyaeiiAbWPP80lzC/9XfYYwSoiwiGjme5Fi74FWUp4tMG6IM9\npdbGAWFzqkCWRXUdavGZQePEFQKBgQDKgWpYKFhdZ9VEuwlznjWmN5NukjI3Fn6u\nwM/VZL4nQQN24fgauya9MXKLg/dzGSUDJPaI+jq9y+HVC0LChpw62EvVrYIwoU+l\nE9UKkuoGEmw/6iUZvdBkk+wy1/C9lTQ9ArvGGnlXalKMcGQ7K36o17yGtyPTnq5L\nAabRxckJbwKBgQCVYJNqHyZVjhjTJqozcoLehdY/IO+iOeT7IfAeX0S2pxU/3v8B\nbvwSV4yQfW0euU/q+1WTyxE3SXq0e/mOyUTHJVKxZv5i6rDZAECCJpgII3dOBnM6\nSyCeydi9QdZGZVdDgd25EryfRzOdITb3CqgzCAmVAo4+8COhXhseVGyo1QKBgDsD\nyhUU9OOLrfhQtalvEt101s9jZaTuNk8BO9BJgqz34mWT5vULU3fRYDtOYx+01Td8\nXyh+G/5R22d116fPCNqRTFBiN02qxQYrqGtjczX/ynI570P4MDIPdcc/bRYi1E1v\nbX+HGZOjFZl964fe3hOgg32TA6rZVJvhSFdb14GbAoGBALXpe9hkWB54IwmGqHZM\nnsZqCKZKOE+JXeZbjuAEZoZuIdzR21reAUm9Bify0yoopzQErUHWxDdewbEaY3Lo\nLMghxGihP5WkzYJUQKdgAOezSB69+NSG4oexYOHUImng8BrKxqtHzeo1RRq37Zvr\nJ0418v9yw6XO/dH8S5IKJRxH\n-----END PRIVATE KEY-----\n",
        "client_email": "nse-tracker@sheetsapi-project-467812.iam.gserviceaccount.com",
        "client_id": "123456789", # इसमें कुछ भी लिखा रहने दे सकते हैं
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
    }
    
    # न्यू लाइन कैरेक्टर फिक्स करना ताकि की (Key) टूटे नहीं
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open("NSE_Market_Data")
    print("Successfully connected to Google Sheets Dynamically!")
except Exception as e:
    print(f"Actual Google Connection Failed! Details: {e}")
    sys.exit(1)

# NSE Archives डाउनलोडर
def download_nse_archive(url):
    try:
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        if res.status_code == 200: return res
    except: pass
    return None

# --- 1. Stock Names Tracker ---
def get_stock_wise_names_data():
    print("Fetching Stock Wise Bhavcopy...")
    try:
        for i in range(5):
            target_date_obj = datetime.now() - timedelta(days=i)
            date_file = target_date_obj.strftime("%d%b%Y").upper()
            display_date = target_date_obj.strftime("%Y-%m-%d")
            url = f"https://archives.nseindia.com/content/fo/fo{date_file}.zip"
            response = download_nse_archive(url)
            if response:
                with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                    csv_name = f"fo{date_file}.csv"
                    with z.open(csv_name) as f: df = pd.read_csv(f)
                df.columns = [c.strip() for c in df.columns]
                df = df[~df['SYMBOL'].isin(['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'])]
                df['OPEN_INT'] = pd.to_numeric(df['OPEN_INT'], errors='coerce').fillna(0)
                df['CHG_IN_OI'] = pd.to_numeric(df['CHG_IN_OI'], errors='coerce').fillna(0)
                stock_summary = df.groupby('SYMBOL').agg({'OPEN_INT': 'sum', 'CHG_IN_OI': 'sum', 'CLOSE': 'last'}).reset_index()
                stock_summary = stock_summary.sort_values(by='CHG_IN_OI', ascending=False).reset_index(drop=True)
                stock_summary['Trend_Signal'] = stock_summary['CHG_IN_OI'].apply(lambda x: '🟢 NEW POSITIONS' if x > 0 else '🔴 SQUARE OFF')
                stock_summary['Data_Date'] = display_date
                stock_summary['Download_Time'] = current_download_time
                stock_summary.columns = ['STOCK_NAME', 'TOTAL_OPEN_INTEREST', 'TODAY_OI_CHANGE', 'LAST_PRICE', 'TREND_SIGNAL', 'Data_Date', 'Download_Time']
                return stock_summary
        return pd.DataFrame()
    except: return pd.DataFrame()

# --- 2. Master F&O Participant Data ---
def get_master_participant_oi():
    print("Fetching Participant OI Data...")
    try:
        for i in range(5):
            target_date_obj = datetime.now() - timedelta(days=i)
            target_date_str = target_date_obj.strftime("%d%m%Y")
            display_date = target_date_obj.strftime("%Y-%m-%d")
            url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{target_date_str}.csv"
            response = download_nse_archive(url)
            if response:
                lines = response.text.split('\n')
                data_rows = [line.split(',') for line in lines if line.strip()][1:]
                df = pd.DataFrame(data_rows)
                df.columns = [c.replace('"', '').strip() for c in df.iloc[0]]
                df = df[1:].reset_index(drop=True)
                df['Data_Date'] = display_date
                df['Download_Time'] = current_download_time
                return df
        return pd.DataFrame()
    except: return pd.DataFrame()

# --- 3. Index Signal Calculator ---
def calculate_index_signals(df_oi):
    if df_oi.empty: return pd.DataFrame()
    try:
        df = df_oi.copy()
        cols = ['Future Index Long', 'Future Index Short', 'Option Index Call Long', 'Option Index Call Short', 'Option Index Put Long', 'Option Index Put Short']
        for col in cols: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df['Future_Net_Antar'] = df['Future Index Long'] - df['Future Index Short']
        df['Call_Net'] = df['Option Index Call Long'] - df['Option Index Call Short']
        df['Put_Net'] = df['Option Index Put Long'] - df['Option Index Put Short']
        df['Option_Call_vs_Put_Antar'] = df['Call_Net'] - df['Put_Net']
        df['Market_Signal'] = df.apply(lambda r: 'TOTAL MARKET VOLUME' if r['Client Type'] == 'TOTAL' else ('🟢 BULLISH (BUY)' if r['Option_Call_vs_Put_Antar'] > 0 else '🔴 BEARISH (SELL)'), axis=1)
        return df[['Data_Date', 'Client Type', 'Market_Signal', 'Option_Call_vs_Put_Antar', 'Future_Net_Antar', 'Call_Net', 'Put_Net', 'Download_Time']]
    except: return pd.DataFrame()

# --- 4. Stock Signal Calculator ---
def extract_stock_derivatives_data(df_master):
    if df_master.empty: return pd.DataFrame()
    try:
        df = df_master.copy()
        stock_cols = ['Future Stock Long', 'Future Stock Short', 'Option Stock Call Long', 'Option Stock Call Short', 'Option Stock Put Long', 'Option Stock Put Short']
        for col in stock_cols: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df['Stock_Future_Net'] = df['Future Stock Long'] - df['Future Stock Short']
        df['Stock_Call_Net'] = df['Option Stock Call Long'] - df['Option Stock Call Short']
        df['Stock_Put_Net'] = df['Option Stock Put Long'] - df['Option Stock Put Short']
        df['Stock_Option_Total_Antar'] = df['Stock_Call_Net'] - df['Stock_Put_Net']
        df['Stock_Market_Signal'] = df.apply(lambda r: 'TOTAL VOLUME' if r['Client Type'] == 'TOTAL' else ('🟢 STOCKS BULLISH' if r['Stock_Option_Total_Antar'] > 0 else '🔴 STOCKS BEARISH'), axis=1)
        return df[['Data_Date', 'Client Type', 'Stock_Market_Signal', 'Stock_Option_Total_Antar', 'Stock_Future_Net', 'Stock_Call_Net', 'Stock_Put_Net', 'Download_Time']]
    except: return pd.DataFrame()

# --- Google Sheets Append Engine ---
def upload_to_google_sheet(sheet_name, new_df, unique_cols=None):
    if new_df is None or new_df.empty: return
    try:
        try:
            worksheet = sheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=sheet_name, rows="2000", cols="20")
            worksheet.update([new_df.columns.values.tolist()] + new_df.fillna('').values.tolist())
            print(f"Created new sheet: {sheet_name}")
            return

        existing_records = worksheet.get_all_records()
        if existing_records:
            old_df = pd.DataFrame(existing_records)
            for col in new_df.columns:
                if col not in old_df.columns: old_df[col] = ''
            for col in old_df.columns:
                if col not in new_df.columns: new_df[col] = ''
            
            combined = pd.concat([old_df, new_df], ignore_index=True)
            if unique_cols:
                combined.drop_duplicates(subset=unique_cols, keep='last', inplace=True)
        else: combined = new_df

        worksheet.clear()
        worksheet.update([combined.columns.values.tolist()] + combined.fillna('').astype(str).values.tolist())
        print(f"Successfully uploaded: {sheet_name}")
    except Exception as e:
        print(f"Error uploading {sheet_name}: {e}")

# --- Core Execution ---
if __name__ == "__main__":
    print("Framework Started...")
    df_stock_names = get_stock_wise_names_data()
    df_master = get_master_participant_oi()
    df_index_signals = calculate_index_signals(df_master)
    df_stock_signals = extract_stock_derivatives_data(df_master)
    
    print("Writing Data to Google Sheets...")
    upload_to_google_sheet('Stock_Wise_Names_Live', df_stock_names, unique_cols=['STOCK_NAME', 'Data_Date'])
    upload_to_google_sheet('Stock_Derivatives_OI', df_stock_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Trading_Signals_Color', df_index_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Derivatives_OI_Data', df_master, unique_cols=['Client Type', 'Data_Date'])
    print("All tasks finished successfully!")
