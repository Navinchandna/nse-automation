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

# ========================================================
# 🛑 STAGE 1: GOOGLE SHIETS MULTI-TAB & STRUCTURE DEBUGGER
# ========================================================
print("\n=== 1️⃣ STAGE 1: GOOGLE SHEETS DEEP VERIFICATION ===")
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if not os.path.exists("google_creds.json"):
        print("❌ CRITICAL: google_creds.json was NOT created by workflow!")
        sys.exit(1)
        
    creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)
    client = gspread.authorize(creds)
    
    # शीट को ओपन करके उसकी ID और सारे टैब्स के नाम प्रिंट करना
    sheet = client.open("NSE_Market_Data")
    print(f"✅ CONNECTED! Spreadsheet Title: '{sheet.title}'")
    print(f"📊 Spreadsheet ID: {sheet.id}")
    
    worksheets_list = sheet.worksheets()
    print(f"📋 Found Tabs inside this sheet: {[w.title for w in worksheets_list]}")
    
except Exception as e:
    print(f"❌ STAGE 1 FAILED: Cannot connect or read sheet. Details: {e}")
    traceback.print_exc()
    sys.exit(1)


# --- SMART DATE CHECKER (WITH RAW GRID AUDIT) ---
def check_date_exists_in_sheet(sheet_name, target_date_str):
    print(f"\n🔍 AUDITING TAB: '{sheet_name}' for Date: {target_date_str}")
    try:
        try:
            worksheet = sheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"ℹ️ Tab '{sheet_name}' does not even exist. So date cannot exist!")
            return False
            
        # पूरी शीट का कच्चा डेटा (Raw Values) रीड करना ताकि ब्लैंक का पता चले
        raw_values = worksheet.get_all_values()
        print(f"📊 Raw Grid Audit: Tab has {len(raw_values)} rows in total (including header).")
        
        if len(raw_values) <= 1:
            print(f"⚠️ Tab '{sheet_name}' is effectively EMPTY (only header or completely blank).")
            return False
            
        # DataFrame में बदल कर चेक करना
        df_existing = pd.DataFrame(raw_values[1:], columns=raw_values[0])
        if 'Data_Date' in df_existing.columns:
            dates_list = df_existing['Data_Date'].astype(str).str.strip().tolist()
            exists = target_date_str in dates_list
            print(f"🎯 Date matching status for {target_date_str}: {exists}")
            return exists
        else:
            print("⚠️ 'Data_Date' column header is missing in this tab!")
            return False
    except Exception as ex:
        print(f"⚠️ Error while auditing tab data: {ex}")
        return False

# ========================================================
# 🛑 STAGE 2: NSE NETWORK & DOWNLOAD ENGINE DEBUGGER
# ========================================================
def download_nse_file(url):
    print(f"🌐 FETCHING FROM NSE -> URL: {url}")
    session = requests.Session()
    session.verify = False
    try:
        # नखरे से बचने के लिए पहले बेस होमपेज हिट करना
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        time.sleep(1)
        res = session.get(url, headers=headers, timeout=15)
        print(f"📥 NSE RESPONSE STATUS: {res.status_code} | Bytes Received: {len(res.content)}")
        if res.status_code == 200 and len(res.content) > 2000:
            return res
        else:
            print(f"❌ NSE rejected or returned empty block for this URL.")
    except Exception as e:
        print(f"❌ Network crash during NSE download: {e}")
    return None

def get_stock_wise_names_data(available_date_obj):
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
            return stock_summary
        except Exception as e:
            print(f"❌ Error compiling Stock Wise Bhavcopy: {e}")
    return pd.DataFrame()

def get_master_participant_oi(available_date_obj):
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
            return df
        except Exception as e:
            print(f"❌ Error compiling Participant OI: {e}")
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

# ========================================================
# 🛑 STAGE 3: UPLOAD ENGINE WITH FORCED ROW WRITER
# ========================================================
def upload_to_google_sheet(sheet_name, new_df, unique_cols=None):
    if new_df is None or new_df.empty:
        print(f"⚠️ Dataframe for '{sheet_name}' is EMPTY. Skipping sheet write.")
        return
    try:
        print(f"⏳ Writing {len(new_df)} rows to tab '{sheet_name}'...")
        try: 
            worksheet = sheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"ℹ️ Creating new tab '{sheet_name}'...")
            worksheet = sheet.add_worksheet(title=sheet_name, rows="3000", cols="25")
            worksheet.update([new_df.columns.values.tolist()] + new_df.fillna('').values.tolist())
            print(f"✅ Successfully created and initialized '{sheet_name}'!")
            return

        raw_vals = worksheet.get_all_values()
        if len(raw_vals) > 1:
            old_df = pd.DataFrame(raw_vals[1:], columns=raw_vals[0])
            for col in new_df.columns:
                if col not in old_df.columns: old_df[col] = ''
            for col in old_df.columns:
                if col not in new_df.columns: new_df[col] = ''
            combined = pd.concat([old_df, new_df], ignore_index=True)
            if unique_cols:
                combined.drop_duplicates(subset=unique_cols, keep='last', inplace=True)
        else: 
            combined = new_df

        worksheet.clear()
        worksheet.update([combined.columns.values.tolist()] + combined.fillna('').astype(str).values.tolist())
        print(f"🚀 SUCCESS: Data successfully synced in '{sheet_name}'!")
    except Exception as e:
        print(f"❌ Sheet Sync Error on '{sheet_name}': {e}")

# ========================================================
# 🛑 MAIN EXECUTION PIPELINE
# ========================================================
if __name__ == "__main__":
    print("\n=== 2️⃣ STAGE 2: SCANNING NSE FOR LATEST FILES ===")
    valid_date_obj = None
    
    for i in range(0, 10):
        test_date = datetime.now() - timedelta(days=i)
        test_date_str = test_date.strftime("%d%m%Y")
        url_check = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{test_date_str}.csv"
        
        session = requests.Session()
        session.verify = False
        try:
            session.get("https://www.nseindia.com", headers=headers, timeout=5)
            res = session.head(url_check, headers=headers, timeout=5)
            print(f"🔍 Day -{i} Scan ({test_date.strftime('%Y-%m-%d')}): HTTP Status = {res.status_code}")
            if res.status_code == 200:
                valid_date_obj = test_date
                break
        except: continue

    if not valid_date_obj:
        print("❌ CRITICAL: No data files found on NSE server for the past 10 days loop!")
        sys.exit(0)
        
    target_display_date = valid_date_obj.strftime("%Y-%m-%d")
    print(f"🎯 CHOSEN TRADING DATE FROM NSE: {target_display_date}")

    # शीट के डेटा का मिलान चेक करना
    already_exists = check_date_exists_in_sheet('Derivatives_OI_Data', target_display_date)
    
    if already_exists:
        print(f"ℹ️ SKIPPED: Date {target_display_date} is already registered in the sheet data grid.")
        # टेस्टिंग के लिए एग्जिट को हटा रहे हैं ताकि जबरदस्ती राइट कर सके अगर शीट ब्लैंक दिख रही है तो!
        print("⚠️ DEBUG OVERRIDE: Forcing download anyway to double check visual blankness...")
        
    print(f"\n=== 3️⃣ STAGE 3: DOWNLOADING AND PROCESSING CORES ===")
    df_stock_names = get_stock_wise_names_data(valid_date_obj)
    df_master = get_master_participant_oi(valid_date_obj)
    df_index_signals = calculate_index_signals(df_master)
    df_stock_signals = extract_stock_derivatives_data(df_master)
    
    print(f"\n=== 4️⃣ STAGE 4: WRITING DATA FIELDS TO SPREADSHEETS ===")
    print(f"Data Summary to write -> Stock Names: {len(df_stock_names)} rows, Master OI: {len(df_master)} rows")
    
    upload_to_google_sheet('Stock_Wise_Names_Live', df_stock_names, unique_cols=['STOCK_NAME', 'Data_Date'])
    upload_to_google_sheet('Stock_Derivatives_OI', df_stock_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Trading_Signals_Color', df_index_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Derivatives_OI_Data', df_master, unique_cols=['Client Type', 'Data_Date'])
    
    print("\n=== 🎉 ALL STAGES FINISHED EXECUTING SUCCESSFULLY ===")
