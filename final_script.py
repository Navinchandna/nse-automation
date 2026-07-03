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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
current_download_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive'
}

# --- GOOGLE SHEETS CONNECTOR ---
print("=== CONNECTING TO GOOGLE SHEETS ===")
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if os.path.exists("google_creds.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)
    else:
        print("❌ CRITICAL: google_creds.json missing!")
        sys.exit(1)
        
    client = gspread.authorize(creds)
    sheet = client.open("NSE_Market_Data")
    print(f"✅ CONNECTED SUCCESSFULLY TO SHEET: {sheet.title}")
except Exception as e:
    print(f"❌ Google Connection Failed: {e}")
    sys.exit(1)

def download_nse_file(url):
    print(f"🌐 FETCHING -> {url}")
    session = requests.Session()
    try:
        # COOKIE GENERATION PASS
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        time.sleep(2)
        res = session.get(url, headers=headers, timeout=15)
        print(f"📥 Response Code: {res.status_code} | Size: {len(res.content)} bytes")
        if res.status_code == 200 and len(res.content) > 1000:
            return res
    except Exception as e:
        print(f"❌ Network issue: {e}")
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
            print(f"❌ Error parsing Zip: {e}")
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
            print(f"❌ Error parsing CSV: {e}")
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
        print(f"⚠️ Empty DataFrame for {sheet_name}. Skipping upload.")
        return
    try:
        print(f"⏳ Syncing tab: '{sheet_name}'...")
        try: 
            worksheet = sheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=sheet_name, rows="3000", cols="25")
            worksheet.update([new_df.columns.values.tolist()] + new_df.fillna('').values.tolist())
            print(f"✅ Created fresh tab: '{sheet_name}'")
            return

        raw_vals = worksheet.get_all_values()
        if len(raw_vals) > 1:
            old_df = pd.DataFrame(raw_vals[1:], columns=raw_vals[0])
            combined = pd.concat([old_df, new_df], ignore_index=True)
            if unique_cols:
                combined.drop_duplicates(subset=unique_cols, keep='last', inplace=True)
        else: 
            combined = new_df

        worksheet.clear()
        worksheet.update([combined.columns.values.tolist()] + combined.fillna('').astype(str).values.tolist())
        print(f"🚀 SUCCESS: Sync complete for '{sheet_name}'")
    except Exception as e:
        print(f"❌ Upload Error: {e}")

if __name__ == "__main__":
    print("\n=== SCANNING NSE FOR LIVE FILES ===")
    valid_date_obj = None
    
    # गिटहब रनर को बाईपास करने के लिए GET चेक का इस्तेमाल
    for i in range(0, 10):
        test_date = datetime.now() - timedelta(days=i)
        # शनिवार-रविवार को स्किप करना
        if test_date.weekday() >= 5: 
            continue
            
        test_date_str = test_date.strftime("%d%m%Y")
        url_check = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{test_date_str}.csv"
        
        print(f"Checking availability for date: {test_date.strftime('%Y-%m-%d')}...")
        res = download_nse_file(url_check)
        if res:
            valid_date_obj = test_date
            break
        time.sleep(1)

    if not valid_date_obj:
        print("❌ CRITICAL: NSE servers blocked data fetch or files not ready. Stopping pipeline.")
        sys.exit(1) # अब यह 0 की जगह 1 पर एग्जिट होगा ताकि फेलियर का पता चले!
        
    target_display_date = valid_date_obj.strftime("%Y-%m-%d")
    print(f"\n🎯 FINAL TRADING DATE DETECTED: {target_display_date}")

    print("\n=== PROCESSING CORES ===")
    df_stock_names = get_stock_wise_names_data(valid_date_obj)
    df_master = get_master_participant_oi(valid_date_obj)
    df_index_signals = calculate_index_signals(df_master)
    df_stock_signals = extract_stock_derivatives_data(df_master)
    
    print("\n=== UPLOADING TO GOOGLE SHEET ===")
    upload_to_google_sheet('Stock_Wise_Names_Live', df_stock_names, unique_cols=['STOCK_NAME', 'Data_Date'])
    upload_to_google_sheet('Stock_Derivatives_OI', df_stock_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Trading_Signals_Color', df_index_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Derivatives_OI_Data', df_master, unique_cols=['Client Type', 'Data_Date'])
    
    print("\n=== 🎉 ALL PROCESSES COMPLETED SUCCESSFULLY ===")
