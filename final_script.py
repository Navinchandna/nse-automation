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

def calculate_futures_breakup(df_master):
    if df_master.empty: return pd.DataFrame()
    try:
        df = df_master.copy()
        cols_to_convert = ['Future Index Long', 'Future Index Short', 'Future Stock Long', 'Future Stock Short']
        for col in cols_to_convert: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        breakup_df = pd.DataFrame()
        breakup_df['Data_Date'] = df['Data_Date']
        breakup_df['Client_Type'] = df['Client Type']
        breakup_df['Index_Fut_Long'] = df['Future Index Long']
        breakup_df['Index_Fut_Short'] = df['Future Index Short']
        breakup_df['Index_Fut_Net'] = df['Future Index Long'] - df['Future Index Short']
        breakup_df['Stock_Fut_Long'] = df['Future Stock Long']
        breakup_df['Stock_Fut_Short'] = df['Future Stock Short']
        breakup_df['Stock_Fut_Net'] = df['Future Stock Long'] - df['Future Stock Short']
        breakup_df['Index_Sentiment'] = breakup_df['Index_Fut_Net'].apply(lambda x: '🟢 BULLISH LONG' if x > 0 else '🔴 BEARISH SHORT')
        breakup_df['Stock_Sentiment'] = breakup_df['Stock_Fut_Net'].apply(lambda x: '🟢 STOCKS LONG' if x > 0 else '🔴 STOCKS SHORT')
        breakup_df['Download_Time'] = df['Download_Time']
        return breakup_df
    except: return pd.DataFrame()

def calculate_options_deep_breakup(df_master):
    if df_master.empty: return pd.DataFrame()
    try:
        df = df_master.copy()
        opt_cols = ['Option Index Call Long', 'Option Index Call Short', 'Option Index Put Long', 'Option Index Put Short',
                    'Option Stock Call Long', 'Option Stock Call Short', 'Option Stock Put Long', 'Option Stock Put Short']
        for col in opt_cols: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        opt_df = pd.DataFrame()
        opt_df['Data_Date'] = df['Data_Date']
        opt_df['Client_Type'] = df['Client Type']
        opt_df['Idx_Call_Long'] = df['Option Index Call Long']
        opt_df['Idx_Call_Short'] = df['Option Index Call Short']
        opt_df['Idx_Put_Long'] = df['Option Index Put Long']
        opt_df['Idx_Put_Short'] = df['Option Index Put Short']
        opt_df['Stk_Call_Long'] = df['Option Stock Call Long']
        opt_df['Stk_Call_Short'] = df['Option Stock Call Short']
        opt_df['Stk_Put_Long'] = df['Option Stock Put Long']
        opt_df['Stk_Put_Short'] = df['Option Stock Put Short']
        
        opt_df['Idx_Net_Call'] = df['Option Index Call Long'] - df['Option Index Call Short']
        opt_df['Idx_Net_Put'] = df['Option Index Put Long'] - df['Option Index Put Short']
        opt_df['Stk_Net_Call'] = df['Option Stock Call Long'] - df['Option Stock Call Short']
        opt_df['Stk_Net_Put'] = df['Option Stock Put Long'] - df['Option Stock Put Short']
        
        opt_df['Index_Options_View'] = opt_df.apply(lambda r: '🟢 BULLISH (Call Buying)' if r['Idx_Net_Call'] > r['Idx_Net_Put'] else '🔴 BEARISH (Put Buying)', axis=1)
        opt_df['Stock_Options_View'] = opt_df.apply(lambda r: '🟢 BULLISH STOCKS' if r['Stk_Net_Call'] > r['Stk_Net_Put'] else '🔴 BEARISH STOCKS', axis=1)
        opt_df['Download_Time'] = df['Download_Time']
        return opt_df
    except: return pd.DataFrame()

# 📊 न्यू फीचर: कल और आज के डेटा के बीच का बदलाव (Figures & % Change Tracker)
def track_daily_changes(sheet, new_master_df, current_date_str):
    print("⏳ Calculating daily changes over previous trading day...")
    try:
        # शीट से पुराना डेटा रीड करना
        try:
            worksheet = sheet.worksheet('Derivatives_OI_Data')
            raw_vals = worksheet.get_all_values()
        except:
            print("⚠️ Derivatives_OI_Data tab not found. No previous data to compare.")
            return pd.DataFrame()

        if len(raw_vals) <= 1:
            print("⚠️ Not enough historical data rows in sheet to calculate changes yet.")
            return pd.DataFrame()

        df_historical = pd.DataFrame(raw_vals[1:], columns=raw_vals[0])
        
        # आज की तारीख का पुराना डेटा फिल्टर करके हटा देना, केवल कल या उससे पुराना रखना
        df_old_days = df_historical[df_historical['Data_Date'] != current_date_str]
        if df_old_days.empty:
            print("⚠️ Previous trading day data not available in sheet logs yet.")
            return pd.DataFrame()

        # सबसे लेटेस्ट उपलब्ध पिछली तारीख निकालना
        last_available_date = df_old_days['Data_Date'].max()
        df_prev_day = df_old_days[df_old_days['Data_Date'] == last_available_date].copy()
        print(f"📊 Comparing today ({current_date_str}) against last saved sheet date ({last_available_date})")

        change_rows = []
        numeric_cols = [
            'Future Index Long', 'Future Index Short', 'Future Stock Long', 'Future Stock Short',
            'Option Index Call Long', 'Option Index Call Short', 'Option Index Put Long', 'Option Index Put Short',
            'Option Stock Call Long', 'Option Stock Call Short', 'Option Stock Put Long', 'Option Stock Put Short'
        ]

        # FII, DII, Client, Pro के हिसाब से कंपेयर करना
        for client in ['CLIENT', 'DII', 'FII', 'PRO', 'TOTAL']:
            today_client = new_master_df[new_master_df['Client Type'] == client]
            prev_client = df_prev_day[df_prev_day['Client Type'] == client]

            if today_client.empty or prev_client.empty: continue

            row_data = {'Data_Date': current_date_str, 'Compared_With_Date': last_available_date, 'Client_Type': client}

            for col in numeric_cols:
                val_today = pd.to_numeric(today_client[col].values[0], errors='coerce') or 0
                val_prev = pd.to_numeric(prev_client[col].values[0], errors='coerce') or 0

                # अंतर (Absolute Change)
                diff = val_today - val_prev
                # प्रतिशत बदलाव (% Change)
                pct_change = (diff / val_prev * 100) if val_prev != 0 else (100.0 if diff > 0 else 0.0)

                col_clean = col.replace(' ', '_')
                row_data[f'{col_clean}_Chg_Qty'] = int(diff)
                row_data[f'{col_clean}_Chg_Pct'] = f"{pct_change:+.1f}%"

            change_rows.append(row_data)

        print("✅ Daily changes dashboard successfully calculated!")
        return pd.DataFrame(change_rows)
    except Exception as e:
        print(f"❌ Error in daily change calculation: {e}")
        return pd.DataFrame()

def upload_to_google_sheet(sheet, sheet_name, new_df, unique_cols=None):
    if new_df is None or new_df.empty: return
    try:
        print(f"⏳ Syncing tab: '{sheet_name}'...")
        try: worksheet = sheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=sheet_name, rows="3000", cols="30")
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
    df_stock_names = get_stock_wise_names_data(valid_date_obj)
    df_master = get_master_participant_oi(saved_response, valid_date_obj)
    df_futures_breakup = calculate_futures_breakup(df_master)
    df_options_breakup = calculate_options_deep_breakup(df_master)
    
    # ⚡ डेली चेंज कैलकुलेटर को ट्रिगर करना
    df_daily_changes = track_daily_changes(sheet, df_master, target_display_date)
    
    print("\n=== UPLOADING TO GOOGLE SHEET ===")
    upload_to_google_sheet(sheet, 'Stock_Wise_Names_Live', df_stock_names, unique_cols=['STOCK_NAME', 'Data_Date'])
    upload_to_google_sheet(sheet, 'Index_Stock_Futures_Breakup', df_futures_breakup, unique_cols=['Client_Type', 'Data_Date'])
    upload_to_google_sheet(sheet, 'Fando_Options_Deep_Breakup', df_options_breakup, unique_cols=['Client_Type', 'Data_Date'])
    upload_to_google_sheet(sheet, 'Fando_Daily_Changes_Dashboard', df_daily_changes, unique_cols=['Client_Type', 'Data_Date'])
    upload_to_google_sheet(sheet, 'Derivatives_OI_Data', df_master, unique_cols=['Client Type', 'Data_Date'])
    
    print("\n=== 🎉 ALL PROCESSES COMPLETED SUCCESSFULLY ===")
