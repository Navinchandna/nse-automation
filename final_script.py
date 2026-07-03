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
import traceback  # फुल डीबगिंग के लिए

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
current_download_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ==========================================
# 🛑 FULL DEBUGGING & GOOGLE CONNECTOR ENGINE
# ==========================================
print("=== STARTING GOOGLE SHEETS CONNECTION TEST ===")

try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # 1. चेक करना कि क्या फाइल सच में बनी
    if not os.path.exists("google_creds.json"):
        print("❌ DEBUG: google_creds.json file DOES NOT exist at all!")
        sys.exit(1)
        
    # 2. फाइल के अंदर झाँक कर देखना (कंटेंट क्या है)
    with open("google_creds.json", "r") as f:
        file_content = f.read().strip()
    
    print(f"📊 DEBUG: File Content Length = {len(file_content)} characters")
    if len(file_content) > 0:
        print(f"📊 DEBUG: First 30 characters of file = '{file_content[:30]}'")
        print(f"📊 DEBUG: Last 20 characters of file = '{file_content[-20:]}'")
    else:
        print("❌ DEBUG: File is completely EMPTY!")
        sys.exit(1)

    # 3. क्रेडेंशियल लोड करने की कोशिश
    print("⏳ DEBUG: Attempting to parse JSON and authorize with Google...")
    
    # अगर फाइल JSON नहीं है, तो json.loads यहाँ एरर फेंक देगा
    try:
        json_test = json.loads(file_content)
        print("✅ DEBUG: File is a valid JSON structure!")
        if "private_key" not in json_test:
            print("❌ DEBUG ALERT: 'private_key' field is MISSING inside JSON!")
    except Exception as json_err:
        print(f"❌ DEBUG ALERT: Content is NOT a valid JSON! JSON Error: {json_err}")

    creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)
    client = gspread.authorize(creds)
    
    print("⏳ DEBUG: Google Authorized. Now trying to open the specific spreadsheet 'NSE_Market_Data'...")
    sheet = client.open("NSE_Market_Data")
    print("===> ✅ SUCCESS: Connected to Google Sheets perfectly!")

except Exception as e:
    print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print("❌ CRITICAL BUG DETECTED! HERE ARE THE FULL DETAILS:")
    print(f"Error Type: {type(e).__name__}")
    print(f"Error Message/String: {e}")
    print("\n--- FULL STACK TRACEBACK (EXACT LINE OF FAILURE) ---")
    traceback.print_exc() # यह प्रिंट करेगा कि पायथन किस लाइन पर मरा
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
    sys.exit(1)

# --- CHECK IF DATA ALREADY EXISTS IN SHEET ---
def check_date_exists_in_sheet(sheet_name, target_date_str):
    try:
        worksheet = sheet.worksheet(sheet_name)
        existing_records = worksheet.get_all_records()
        if existing_records:
            df_existing = pd.DataFrame(existing_records)
            if 'Data_Date' in df_existing.columns:
                dates_list = df_existing['Data_Date'].astype(str).tolist()
                if target_date_str in dates_list:
                    return True
    except: pass
    return False

def download_nse_file(url):
    session = requests.Session()
    session.verify = False
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        time.sleep(1)
        res = session.get(url, headers=headers, timeout=15)
        if res.status_code == 200 and len(res.content) > 2000:
            return res
    except: pass
    return None

def get_stock_wise_names_data(available_date_obj=None):
    if available_date_obj is None: return pd.DataFrame()
    date_file = available_date_obj.strftime("%d%b%Y").upper()
    display_date = available_date_obj.strftime("%Y-%m-%d")
    print(f"Downloading Stock Wise Bhavcopy for {display_date}...")
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
        except: pass
    return pd.DataFrame()

def get_master_participant_oi(available_date_obj=None):
    if available_date_obj is None: return pd.DataFrame()
    target_date_str = available_date_obj.strftime("%d%m%Y")
    display_date = available_date_obj.strftime("%Y-%m-%d")
    print(f"Downloading Participant OI Data for {display_date}...")
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
        except: pass
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
    if new_df is None or new_df.empty: return
    try:
        try: worksheet = sheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=sheet_name, rows="2000", cols="20")
            worksheet.update([new_df.columns.values.tolist()] + new_df.fillna('').values.tolist())
            return
        existing_records = worksheet.get_all_records()
        if existing_records:
            old_df = pd.DataFrame(existing_records)
            for col in new_df.columns:
                if col not in old_df.columns: old_df[col] = ''
            for col in old_df.columns:
                if col not in new_df.columns: new_df[col] = ''
            combined = pd.concat([old_df, new_df], ignore_index=True)
            if unique_cols: combined.drop_duplicates(subset=unique_cols, keep='last', inplace=True)
        else: combined = new_df
        worksheet.clear()
        worksheet.update([combined.columns.values.tolist()] + combined.fillna('').astype(str).values.tolist())
        print(f"Successfully uploaded/appended: {sheet_name}")
    except Exception as e:
        print(f"Error uploading {sheet_name}: {e}")

if __name__ == "__main__":
    print("Framework Started...")
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
            if res.status_code == 200:
                valid_date_obj = test_date
                break
        except: continue

    if not valid_date_obj:
        print("No valid file found on NSE for the last 10 days.")
        sys.exit(0)
        
    target_display_date = valid_date_obj.strftime("%Y-%m-%d")
    print(f"Latest available date on NSE is: {target_display_date}")

    print("Checking if this date already exists in your Google Sheet...")
    already_exists = check_date_exists_in_sheet('Derivatives_OI_Data', target_display_date)
    if already_exists:
        print(f"Data for {target_display_date} ALREADY EXISTS in Google Sheet. Skipping execution.")
        sys.exit(0)
        
    print(f"Data for {target_display_date} is missing. Starting fresh download...")
    df_stock_names = get_stock_wise_names_data(valid_date_obj)
    df_master = get_master_participant_oi(valid_date_obj)
    df_index_signals = calculate_index_signals(df_master)
    df_stock_signals = extract_stock_derivatives_data(df_master)
    
    if df_stock_names.empty and df_master.empty:
        print("Data download returned empty blocks. Exiting.")
        sys.exit(0)
        
    print("Writing Data to Google Sheets...")
    upload_to_google_sheet('Stock_Wise_Names_Live', df_stock_names, unique_cols=['STOCK_NAME', 'Data_Date'])
    upload_to_google_sheet('Stock_Derivatives_OI', df_stock_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Trading_Signals_Color', df_index_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Derivatives_OI_Data', df_master, unique_cols=['Client Type', 'Data_Date'])
    print("All tasks finished successfully!")
