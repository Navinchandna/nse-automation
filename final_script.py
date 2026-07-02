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
today_date = datetime.now().strftime("%Y-%m-%d")

# क्लाउड रन के लिए सबसे मजबूत ब्राउज़र हेडर
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive'
}

# --- GOOGLE SHEETS CONNECTOR ---
try:
    google_secrets = os.environ.get('GOOGLE_CREDENTIALS')
    if not google_secrets:
        raise ValueError("GOOGLE_CREDENTIALS secret not found on GitHub!")
    
    creds_dict = json.loads(google_secrets.strip())
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open("NSE_Market_Data")
    print("Successfully connected to Google Sheets!")
except Exception as e:
    print(f"Google Connection Failed! Details: {e}")
    sys.exit(1)

# NSE Archives (Bhavcopy और Participant OI) के लिए सेफ डाउनलोडर
def download_nse_archive_file(url):
    try:
        # Archives के लिए नॉर्मल गेट रिक्वेस्ट बिना सेशन के भी बेस्ट चलती है
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        if res.status_code == 200:
            return res
    except:
        pass
    return None

# --- 1. Stock Names Tracker ---
def get_stock_wise_names_data():
    try:
        for i in range(5):
            target_date_obj = datetime.now() - timedelta(days=i)
            date_file = target_date_obj.strftime("%d%b%Y").upper()
            display_date = target_date_obj.strftime("%Y-%m-%d")
            url = f"https://archives.nseindia.com/content/fo/fo{date_file}.zip"
            response = download_nse_archive_file(url)
            if response and response.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                    csv_name = f"fo{date_file}.csv"
                    with z.open(csv_name) as f: df = pd.read_csv(f)
                df.columns = [c.strip() for c in df.columns]
                df = df[~df['SYMBOL'].isin(['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'])]
                df['OPEN_INT'] = pd.to_numeric(df['OPEN_INT'], errors='coerce').fillna(0)
                df['CHG_IN_OI'] = pd.to_numeric(df['CHG_IN_OI'], errors='coerce').fillna(0)
                stock_summary = df.groupby('SYMBOL').agg({'OPEN_INT': 'sum', 'CHG_IN_OI': 'sum', 'CLOSE': 'last'}).reset_index()
                stock_summary = stock_summary.sort_values(by='CHG_IN_OI', ascending=False).reset_index(drop=True)
                stock_summary['Trend_Signal'] = stock_summary['CHG_IN_OI'].apply(lambda x: '🟢 NEW POSITIONS BUILT' if x > 0 else '🔴 POSITIONS SQUARE OFF')
                stock_summary['Data_Date'] = display_date
                stock_summary['Download_Time'] = current_download_time
                stock_summary.columns = ['STOCK_NAME', 'TOTAL_OPEN_INTEREST', 'TODAY_OI_CHANGE', 'LAST_PRICE', 'TREND_SIGNAL', 'Data_Date', 'Download_Time']
                return stock_summary
        return pd.DataFrame()
    except: return pd.DataFrame()

# --- 2. Master F&O Data ---
def get_master_participant_oi():
    try:
        for i in range(5):
            target_date_obj = datetime.now() - timedelta(days=i)
            target_date_str = target_date_obj.strftime("%d%m%Y")
            display_date = target_date_obj.strftime("%Y-%m-%d")
            url = f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{target_date_str}.csv"
            response = download_nse_archive_file(url)
            if response and response.status_code == 200:
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

# --- 5. Index Wise Live OI ---
def get_index_wise_live_oi(symbol_name):
    try:
        # गिटहब सर्वर ब्लॉक न हो इसलिए लाइव कुकीज सेशन हर बार फ्रेश बनाना
        session = requests.Session()
        session.verify = False
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        
        url = f"https://www.nseindia.com/api/optionchain-indices?symbol={symbol_name}"
        response = session.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            total_ce_oi = data.get('filtered', {}).get('CE', {}).get('totOI', 0)
            total_pe_oi = data.get('filtered', {}).get('PE', {}).get('totOI', 0)
            pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
            return {'Data_Date': today_date, 'Download_Time': current_download_time, 'INDEX_SYMBOL': symbol_name, 'TOTAL_CALL_OI': total_ce_oi, 'TOTAL_PUT_OI': total_pe_oi, 'NET_OI_DIFFERENCE': total_ce_oi - total_pe_oi, 'LIVE_PCR': pcr}
    except: pass
    return None

# --- 6. Cash Market ---
def get_fii_dii_cash_data():
    try:
        session = requests.Session()
        session.verify = False
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        
        url = "https://www.nseindia.com/api/fiidii-trade-details"
        response = session.get(url, headers=headers, timeout=15)
        if response.status_code == 200 and response.text.strip():
            df = pd.DataFrame(response.json())
            if not df.empty:
                df['Download_Time'] = current_download_time
                if 'date' in df.columns: df = df.rename(columns={'date': 'Data_Date'})
                return df
        return pd.DataFrame()
    except: return pd.DataFrame()

# --- Google Sheets Append Engine ---
def upload_to_google_sheet(sheet_name, new_df, unique_cols=None):
    if new_df is None or new_df.empty: 
        print(f"Skipping {sheet_name} as dataframe is empty.")
        return
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
        else:
            combined = new_df

        worksheet.clear()
        worksheet.update([combined.columns.values.tolist()] + combined.fillna('').astype(str).values.tolist())
        print(f"Appended metrics into Google Sheet: {sheet_name}")
    except Exception as e:
        print(f"Error uploading {sheet_name}: {e}")

# --- Core Execution ---
if __name__ == "__main__":
    print("Starting Process Framework...")
    
    print("Step 1: Downloading Archive Files...")
    df_stock_names = get_stock_wise_names_data()
    df_master = get_master_participant_oi()
    
    print("Step 2: Processing Trading Signals...")
    df_index_signals = calculate_index_signals(df_master)
    df_stock_signals = extract_stock_derivatives_data(df_master)
    
    print("Step 3: Fetching Live Data Fields...")
    df_cash = get_fii_dii_cash_data()
    
    index_positions = []
    n_stats = get_index_wise_live_oi("NIFTY")
    b_stats = get_index_wise_live_oi("BANKNIFTY")
    if n_stats: index_positions.append(n_stats)
    if b_stats: index_positions.append(b_stats)
    df_index_wise = pd.DataFrame(index_positions)

    print("Step 4: Transmitting Data to Google Cloud Sheet...")
    upload_to_google_sheet('Stock_Wise_Names_Live', df_stock_names, unique_cols=['STOCK_NAME', 'Data_Date'])
    upload_to_google_sheet('Index_Wise_Positions', df_index_wise, unique_cols=['INDEX_SYMBOL', 'Download_Time'])
    upload_to_google_sheet('Stock_Derivatives_OI', df_stock_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Trading_Signals_Color', df_index_signals, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('Derivatives_OI_Data', df_master, unique_cols=['Client Type', 'Data_Date'])
    upload_to_google_sheet('FII_DII_Cash_Daily', df_cash, unique_cols=['Data_Date'])
    
    print("All tasks finished successfully!")
