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
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        time.sleep(2)
        res = session.get(url, headers=headers, timeout=15)
        print(f"📥 Response Code: {res.status_code} | Size: {len(res.content)} bytes")
        if res.status_code == 200 and len(res.content) > 500:
            return res
    except Exception as e:
        print(f"❌ Network issue: {e}")
    return None

# 📊 न्यू इंजन: नाम के हिसाब से इंडेक्स और स्टॉक के CE/PE का डेटा निकालना
def process_script_wise_ce_pe(available_date_obj):
    date_file = available_date_obj.strftime("%d%b%Y").upper()
    display_date = available_date_obj.strftime("%Y-%m-%d")
    url = f"https://archives.nseindia.com/content/fo/fo{date_file}.zip"
    
    response = download_nse_file(url)
    if not response:
        return pd.DataFrame(), pd.DataFrame()
        
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            csv_name = f"fo{date_file}.csv"
            with z.open(csv_name) as f: 
                df = pd.read_csv(f)
                
        df.columns = [c.strip() for c in df.columns]
        
        # केवल ऑप्शंस डेटा फ़िल्टर करना (CE और PE)
        df_opt = df[df['INSTRUMENT'].isin(['OPTIDX', 'OPTSTK'])].copy()
        df_opt['OPEN_INT'] = pd.to_numeric(df_opt['OPEN_INT'], errors='coerce').fillna(0)
        df_opt['CHG_IN_OI'] = pd.to_numeric(df_opt['CHG_IN_OI'], errors='coerce').fillna(0)
        
        # 1. इंडेक्स वाइस CE/PE ब्रेकअप (Nifty, BankNifty, etc.)
        df_idx = df_opt[df_opt['INSTRUMENT'] == 'OPTIDX'].copy()
        idx_summary = df_idx.groupby(['SYMBOL', 'OPTION_TYP']).agg({'OPEN_INT': 'sum', 'CHG_IN_OI': 'sum'}).reset_index()
        
        idx_pivot = idx_summary.pivot(index='SYMBOL', columns='OPTION_TYP', values=['OPEN_INT', 'CHG_IN_OI']).fillna(0)
        idx_pivot.columns = [f"{col[1]}_{col[0]}" for col in idx_pivot.columns]
        idx_pivot = idx_pivot.reset_index()
        idx_pivot['Data_Date'] = display_date
        idx_pivot['Download_Time'] = current_download_time
        
        # कॉलम्स को आसान नाम देना
        idx_final = idx_pivot[['Data_Date', 'SYMBOL', 'CE_OPEN_INT', 'CE_CHG_IN_OI', 'PE_OPEN_INT', 'PE_CHG_IN_OI', 'Download_Time']].copy()
        idx_final.columns = ['Data_Date', 'Index_Name', 'Call_Total_OI', 'Call_OI_Change', 'Put_Total_OI', 'Put_OI_Change', 'Download_Time']
        
        # 2. केवल एक्टिव F&O स्टॉक्स का CE/PE ब्रेकअप (Reliance, Kotak, etc.)
        df_stk = df_opt[df_opt['INSTRUMENT'] == 'OPTSTK'].copy()
        stk_summary = df_stk.groupby(['SYMBOL', 'OPTION_TYP']).agg({'OPEN_INT': 'sum', 'CHG_IN_OI': 'sum'}).reset_index()
        
        stk_pivot = stk_summary.pivot(index='SYMBOL', columns='OPTION_TYP', values=['OPEN_INT', 'CHG_IN_OI']).fillna(0)
        stk_pivot.columns = [f"{col[1]}_{col[0]}" for col in stk_pivot.columns]
        stk_pivot = stk_pivot.reset_index()
        stk_pivot['Data_Date'] = display_date
        stk_pivot['Download_Time'] = current_download_time
        
        stk_final = stk_pivot[['Data_Date', 'SYMBOL', 'CE_OPEN_INT', 'CE_CHG_IN_OI', 'PE_OPEN_INT', 'PE_CHG_IN_OI', 'Download_Time']].copy()
        stk_final.columns = ['Data_Date', 'Stock_Name', 'Call_Total_OI', 'Call_OI_Change', 'Put_Total_OI', 'Put_OI_Change', 'Download_Time']
        stk_final = stk_final.sort_values(by='Call_OI_Change', ascending=False).reset_index(drop=True)
        
        return idx_final, stk_final
    except Exception as e:
        print(f"❌ Error processing Script Wise CE/PE: {e}")
        return pd.DataFrame(), pd.DataFrame()

def get_master_participant_oi(response_obj, available_date_obj):
    display_date = available_date_obj.strftime("%Y-%m-%d")
    try:
        lines = response_obj.text.split('\n')
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

def upload_to_google_sheet(sheet, sheet_name, new_df, unique_cols=None):
    if new_df is None or new_df.empty: return
    try:
        print(f"⏳ Syncing tab: '{sheet_name}'...")
        try: worksheet = sheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=sheet_name, rows="4000", cols="20")
            worksheet.update([new_df.columns.values.tolist()] + new_df.fillna('').values.tolist())
            print(f"✅ Created fresh tab: '{sheet_name}'")
            return

        raw_vals = worksheet.get_all_values()
        if len(raw_vals) > 1:
            old_df = pd.DataFrame(raw_vals[1:], columns=raw_vals[0])
            combined = pd.concat([old_df, new_df], ignore_index=True)
            if unique_cols: combined.drop_duplicates(subset=unique_cols, keep='last', inplace=True)
        else: combined = new_df

        worksheet.clear()
        worksheet.update([combined.columns.values.tolist()] + combined.fillna('').astype(str).values.tolist())
        print(f"🚀 SUCCESS: Sync complete for '{sheet_name}'")
    except Exception as e: print(f"❌ Upload Error: {e}")

if __name__ == "__main__":
    print("\n=== SCANNING NSE FOR LIVE FILES ===")
    valid_date_obj = None; saved_response = None
    
    for i in range(0, 10):
        test_date = datetime.now() - timedelta(days=i)
        if test_date.weekday() >= 5: continue
        test_date_str = test_date.strftime("%d%m%Y")
        url_check = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{test_date_str}.csv"
        
        res = download_nse_file(url_check)
        if res:
            valid_date_obj = test_date; saved_response = res
            break
        time.sleep(1)

    if not valid_date_obj:
        print("❌ CRITICAL: NSE data files not ready. Stopping pipeline.")
        sys.exit(1)
        
    target_display_date = valid_date_obj.strftime("%Y-%m-%d")
    print(f"\n🎯 FINAL TRADING DATE DETECTED: {target_display_date}")

    print("\n=== PROCESSING CORES ===")
    df_master = get_master_participant_oi(saved_response, valid_date_obj)
    
    # ⚡ नए इंडेक्स और स्टॉक वाइज CE/PE डेटा को प्रोसेस करना
    df_index_ce_pe, df_stock_ce_pe = process_script_wise_ce_pe(valid_date_obj)
    
    print("\n=== UPLOADING TO GOOGLE SHEET ===")
    upload_to_google_sheet(sheet, 'Index_Wise_Options_Live', df_index_ce_pe, unique_cols=['Index_Name', 'Data_Date'])
    upload_to_google_sheet(sheet, 'Stock_Wise_Options_Live', df_stock_ce_pe, unique_cols=['Stock_Name', 'Data_Date'])
    upload_to_google_sheet(sheet, 'Derivatives_OI_Data', df_master, unique_cols=['Client Type', 'Data_Date'])
    
    print("\n=== 🎉 ALL PROCESSES COMPLETED SUCCESSFULLY ===")
