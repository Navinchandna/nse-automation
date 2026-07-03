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
import time
import traceback

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
current_download_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}

# --- GOOGLE SHEETS CONNECTOR ---
print("=== GOOGLE SHEETS CONNECTION START ===")
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if os.path.exists("google_creds.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)
    else:
        print("❌ ERROR: google_creds.json missing!")
        sys.exit(1)
        
    client = gspread.authorize(creds)
    sheet = client.open("NSE_Market_Data")
    print("✅ SUCCESS: Connected to Google Sheets!")
except Exception as e:
    print(f"❌ Google Connection Failed: {e}")
    sys.exit(1)


# --- DEBUGGED DATE CHECKER ---
def check_date_exists_in_sheet(sheet_name, target_date_str):
    print(f"🔍 DEBUG: Checking if date {target_date_str} exists in sheet '{sheet_name}'...")
    try:
        worksheet = sheet.worksheet(sheet_name)
        existing_records = worksheet.get_all_records()
        print(f"📊 DEBUG: Total rows found in '{sheet_name}' = {len(existing_records)}")
        if existing_records:
            df_existing = pd.DataFrame(existing_records)
            if 'Data_Date' in df_existing.columns:
                dates_list = df_existing['Data_Date'].astype(str).tolist()
                exists = target_date_str in dates_list
                print(f"📊 DEBUG: Date {target_date_str} match result = {exists}")
                return exists
            else:
                print("⚠️ DEBUG ALERT: 'Data_Date' column NOT found in existing sheet!")
    except gspread.exceptions.WorksheetNotFound:
        print(f"ℹ️ DEBUG: Sheet '{sheet_name}' does not exist yet. Will create fresh.")
    except Exception as ex:
        print(f"⚠️ DEBUG ERROR inside check_date_exists: {ex}")
    return False

def download_nse_file(url):
    print(f"🌐 DEBUG: Requesting NSE URL: {url}")
    session = requests.Session()
    session.verify = False
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        time.sleep(1)
        res = session.get(url, headers=headers, timeout=15)
        print(f"🌐 DEBUG: NSE Response Status = {res.status_code}, Content Length = {len(res.content)}")
        if res.status_code == 200 and len(res.content) > 2000:
            return res
    except Exception as e:
        print(f"❌ DEBUG: Download failed for URL {url}. Error: {e}")
    return None

def get_stock_wise_names_data(available_date_obj=None):
    if available_date_obj is None: return pd.DataFrame()
    date_file = available_date_obj.strftime("%d%b%Y").upper()
    display_date = available_date_obj.strftime("%Y-%m-%d")
    
    url = f"https://archives.nseindia.com/content/fo/fo{date_file}.zip"
    response = download_nse_file(url)
    if response:
        try:
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
            print(f"✅ DEBUG: Bhavcopy DataFrame prepared. Shape: {stock_summary.shape}")
            return stock_summary
        except Exception as ex: 
            print(f"❌ DEBUG: Error processing Bhavcopy zip: {ex}")
    return pd.DataFrame()

def get_master_participant_oi(available_date_obj=None):
    if available_date_obj is None: return pd.DataFrame()
    target_date_str = available_date_obj.strftime("%d%m%Y")
    display_date = available_date_obj.strftime("%Y-%m-%d")
    
    url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{target_date_str}.csv"
    response = download_nse_file(url)
    if response:
        try:
            lines = response.text.split('\n')
            data_rows = [line.split(',') for line in lines if line.strip()][1:]
            df = pd.DataFrame(data_rows)
            df.columns = [c.replace('"', '').strip() for c in df.iloc[0]]
            df = df[1:].reset_index(drop=True)
            df['Data_Date'] = display_date
            df['Download_Time'] = current_download_time
            print(f"✅ DEBUG: Participant OI DataFrame prepared. Shape: {df.shape}")
            return df
        except Exception as ex:
            print(f"❌ DEBUG: Error processing Participant CSV: {ex}")
    return pd.DataFrame()

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

def upload_to_google_sheet(sheet_name, new_df, unique_cols=None):
    if new_df is None or new_df.empty: 
        print(f"⚠️ DEBUG: Skipping upload for '{sheet_name}' because DataFrame is empty.")
        return
    try:
        print(f"⏳ DEBUG: Starting upload/append engine for sheet: '{sheet_name}'...")
        try: worksheet = sheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"ℹ️ DEBUG: Worksheet '{sheet_name}' not found, creating fresh one...")
            worksheet = sheet.add_worksheet(title=sheet_name, rows="2000", cols="20")
            worksheet.update([new_df.columns.values.tolist()] + new_df.fillna('').values.tolist())
            print(f"✅ DEBUG: Created and wrote initial data to '{sheet_name}'")
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
        print(f"🚀 SUCCESS: Uploaded & Appended data into '{sheet_name}' successfully!")
    except Exception as e:
        print(f"❌ DEBUG UPLOAD ERROR for {sheet_name}: {e}")

if __name__ == "__main__":
    print("=== MAIN ENGINE STARTED ===")
    
    valid_date_obj = None
    print("⏳ DEBUG: Scanning last 10 days on NSE to find the latest available files...")
    for i in range(0, 10):
        test_date = datetime.now() - timedelta(days=i)
        test_date_str = test_date.strftime("%d%m%Y")
        url_check = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{test_date_str}.csv"
        
        session = requests.Session()
        session.verify = False
        try:
            session.get("https://www.nseindia.com", headers=headers, timeout=5)
            res = session.head(url_check, headers=headers, timeout=5)
            print(f"🔎 DEBUG: Date scan {test_date.strftime('%Y-%m-%d')} -> HTTP Status: {res.status_code}")
            if res.status_code == 200:
                valid_date_obj = test_date
                break
        except Exception as e: 
            print(f"⚠️ DEBUG: Scan warning for date {test_date.strftime('%Y-%m-%d')}: {e}")
            continue

    if not valid_date_obj:
        print("❌ CRITICAL DEBUG: No valid file found on NSE in the last 10 days loop! Exiting.")
        sys.exit(0)
        
    target_display_date = valid_date_obj.strftime("%Y-%m-%d")
    print(f"🎯 DEBUG: Target date decided from NSE: {target_display_date}")

    # शीट चेक
    already_exists = check_date_exists_in_sheet('Derivatives_OI_Data', target_display_date)
    if already_exists:
        print(f"ℹ️ DEBUG: Data for {target_display_date} ALREADY EXISTS in Google Sheet. Stopping to avoid duplicates.")
        sys.exit(0)
        
    print(f"🚀 DEBUG: Data for {target_display_date} is missing. Triggering core downloaders...")
    df_stock_names = get_stock_wise_names_data(valid_date_obj)
    df_master = get_master_participant_oi(valid_date_obj)
    df_index_signals = calculate_index_signals(df_master)
    df_stock_signals = extract_stock_derivatives_data(df_master)
    
    print("⏳ DEBUG: Starting spreadsheet writing operations...")
    upload_to_google_sheet('Stock_Wise_Names_Live', df_stock_names, unique_cols=['STOCK_NAME', 'Data_Date'])
    upload_to_google_sheet('Stock_Derivatives_OI', df_stock_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Trading_Signals_Color', df_index_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Derivatives_OI_Data', df_master, unique_cols=['Client Type', 'Data_Date'])
    
    print("=== ALL PROCESSES COMPLETED SUCCESSFULLY ===")
