import yfinance as yf
import pandas as pd
import requests
from fredapi import Fred
from requests.adapters import HTTPAdapter
import subprocess
import os

# 1) BEA API 세팅
BEA_API_KEY = "1A43CED6-707A-4E61-B475-A31AAB37AD01"
BEA_BASE_URL = "https://apps.bea.gov/api/data"
Q_MAP = {'Q1':'-03-31','Q2':'-06-30','Q3':'-09-30','Q4':'-12-31'}

def fetch_bea(table):
    sess = requests.Session()
    sess.mount('https://', HTTPAdapter(max_retries=3))
    params = {
        'UserID': BEA_API_KEY,
        'method': 'GetData',
        'datasetname': 'NIPA',
        'TableName': table,
        'Frequency': 'Q',
        'Year': ','.join(str(y) for y in range(2000, 2026)),
        'ResultFormat': 'JSON'
    }
    r = sess.get(BEA_BASE_URL, params=params, timeout=30)
    results = r.json().get('BEAAPI', {}).get('Results', {}).get('Data', [])
    if not results:
        return pd.DataFrame(columns=['Date','LineDescription','Value'])
    df = pd.DataFrame(results)
    df['Date'] = pd.to_datetime(df['TimePeriod'].str[:4] + df['TimePeriod'].str[4:].map(Q_MAP))
    df['Value'] = pd.to_numeric(df['DataValue'].str.replace(',',''), errors='coerce')
    df['LineDescription'] = df['LineDescription'].astype(str)
    return df[['Date','LineDescription','Value']]

# 2) FRED API 세팅
FRED_API_KEY = "fb40b5238c2c5ff6b281706029681f15"
fred = Fred(api_key=FRED_API_KEY)

def load_fred_series(codes):
    data = {}
    for k,v in codes.items():
        try:
            s = fred.get_series(v)
            data[k] = s
        except Exception as e:
            print(f"FRED 시리즈 {k} 불러오기 실패: {e}")
    return pd.DataFrame(data)

# 3) yfinance 데이터 수집 함수
def load_yf_data(tickers):
    df = yf.download(tickers, start="2000-01-01", progress=False)["Close"]
    return df

def update_data():
    print("데이터 수집 시작...")

    # 1) BEA GDP 데이터 (예시)
    growth_df = fetch_bea('T10101')
    contrib_df = fetch_bea('T10102')
    yoy_df = fetch_bea('T10111')

    # 2) FRED 주요 시리즈
    fred_codes = {
        'CPI':'CPIAUCSL', 'Core CPI':'CPILFESL', 'PPI':'PPIACO',
        'PCE':'PCEPI', 'Core PCE':'PCEPILFE',
        'Federal funds rate':'FEDFUNDS',
        'Unemployment rate':'UNRATE',
        '3-month Treasury':'DGS3MO',
        '10-year Treasury':'DGS10'
    }
    fred_data = load_fred_series(fred_codes)

    # 3) yfinance 환율 데이터
    currency_symbols = {
        'KRW':'KRW=X','Dollar Index':'DX-Y.NYB','EURUSD':'EURUSD=X','JPY':'JPY=X',
        'CNY':'CNY=X','GBP':'GBPUSD=X','CAD':'CAD=X',
        'SEK':'SEK=X','CHF':'CHF=X'
    }
    yf_data = load_yf_data(list(currency_symbols.values()))

    # 4) yfinance 원자재 데이터
    commodity_symbols = {
        "WTI":"CL=F","Natural Gas":"NG=F","Copper":"HG=F"
    }
    commodity_data = load_yf_data(list(commodity_symbols.values()))

    # 5) 주가 (국가 & 기업)
    country_indices = {"SP500":"^GSPC","Euro Stoxx":"^STOXX50E","Nikkei":"^N225"}
    company_tickers = {"Apple":"AAPL","Microsoft":"MSFT","Google":"GOOGL"}
    stock_country = load_yf_data(list(country_indices.values()))
    stock_company = load_yf_data(list(company_tickers.values()))

    # 6) 딕셔너리로 통합 저장
    all_data = {
        "bea_growth": growth_df,
        "bea_contrib": contrib_df,
        "bea_yoy": yoy_df,
        "fred": fred_data,
        "yf_currency": yf_data,
        "yf_commodity": commodity_data,
        "yf_stock_country": stock_country,
        "yf_stock_company": stock_company
    }

    # 7) 피클로 저장
    pd.to_pickle(all_data, "latest_data.pkl")
    print("데이터 저장 완료: latest_data.pkl")

def git_commit_push():
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if status.stdout.strip() == "":
        print("변경된 파일이 없습니다. 커밋하지 않습니다.")
        return
    try:
        subprocess.run(["git", "add", "latest_data.pkl"], check=True)
        subprocess.run(["git", "commit", "-m", "자동 데이터 업데이트"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Git 커밋 및 푸시 완료")
    except subprocess.CalledProcessError as e:
        print("Git 오류 발생:", e)

if __name__ == "__main__":
    update_data()
    git_commit_push()
