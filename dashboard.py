# dashboard.py
# dashboard.py — 청크 1: 라이브러리 임포트 및 앱 초기화 + 단일 app.layout
import dash
from dash import dcc, html, Input, Output
import dash_bootstrap_components as dbc
import pandas as pd
import requests
import yfinance as yf
import pandas_datareader.data as web
from fredapi import Fred
from requests.adapters import HTTPAdapter
import plotly.graph_objs as go
import plotly.express as px

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
server = app.server

# → 이 레이아웃이 유일해야 합니다
app.layout = html.Div(style={'display':'flex','height':'100vh'}, children=[
    # URL 위치 추적
    dcc.Location(id='url', refresh=False),

    # 1) 사이드바
    html.Div([
        html.H2("메뉴", style={'textAlign':'center'}),
        dbc.Nav([
            dbc.NavLink("GDP 전기비",      href="/gdp-qoq",     active="exact"),
            dbc.NavLink("GDP 전기비 전망", href="/gdp-nowcast", active="exact"),
            dbc.NavLink("GDP 전년비",      href="/gdp-yoy",     active="exact"),
            dbc.NavLink("FOMC",           href="/fomc",        active="exact"),
            dbc.NavLink("인플레이션",      href="/inflation",   active="exact"),
            dbc.NavLink("금리",           href="/interest",    active="exact"),
            dbc.NavLink("노동시장",        href="/labor",       active="exact"),
            dbc.NavLink("환율",           href="/exchange",    active="exact"),
            dbc.NavLink("주가(국가)",      href="/stock-country",active="exact"),
            dbc.NavLink("주가(기업)",      href="/stock-company",active="exact"),
            dbc.NavLink("원자재",         href="/commodity",   active="exact"),
            dbc.NavLink("주택시장",        href="/housing",     active="exact"),
        ], vertical=True, pills=True),
    ], style={'width':'18rem','padding':'1rem','backgroundColor':'#f8f9fa'}),

    # 2) 메인 콘텐츠 영역 (여기에 각 탭 레이아웃이 렌더링됩니다)
    html.Div(id="page-content", style={'flex':1,'overflow':'auto','padding':'1rem'})
])



# 청크 2: 데이터 로딩 및 전처리
fred = Fred(api_key="fb40b5238c2c5ff6b281706029681f15")  # 예시: 실제 키로 교체
BEA_API_KEY = "1A43CED6-707A-4E61-B475-A31AAB37AD01" 
BEA_BASE_URL = "https://apps.bea.gov/api/data"
# Q_MAP 정의 (분기말 날짜 매핑)
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
    # TimePeriod → Date (YYYYQ → YYYY-MM-DD)
    df['Date'] = pd.to_datetime(
        df['TimePeriod'].str[:4] + 
        df['TimePeriod'].str[4:].map(Q_MAP)
    )
    # DataValue → numeric Value
    df['Value'] = pd.to_numeric(
        df['DataValue'].str.replace(',',''),
        errors='coerce'
    )
    df['LineDescription'] = df['LineDescription'].astype(str)
    # 필요한 컬럼만 리턴
    return df[['Date','LineDescription','Value']]

def load_fred_series(codes):
    return pd.concat({k: fred.get_series(v) for k,v in codes.items()}, axis=1)

def load_yf_data(tickers):
    return yf.download(tickers, start="2000-01-01", progress=False)["Close"]

def load_fred_datareader(codes, start, end):
    df = web.DataReader(list(codes.values()), "fred", start, end)
    df.columns = list(codes.keys())
    return df.dropna(how='all')

# 1) GDP QoQ
growth_df      = fetch_bea('T10101')
df_contrib_raw = fetch_bea('T10102')
series = ['Gross domestic product','Personal consumption expenditures','Gross private domestic investment',
          'Government consumption expenditures and gross investment','Exports','Imports']
labels = {s:l for s,l in zip(series, ['경제성장률','소비','투자','정부지출','수출','수입'])}
df_pct = (growth_df[growth_df['LineDescription'].isin(series)]
          .pivot(index='Date', columns='LineDescription', values='Value').sort_index())
df_contrib = (df_contrib_raw[df_contrib_raw['LineDescription'].isin(series)]
              .pivot(index='Date', columns='LineDescription', values='Value').sort_index())

# 2) GDP Nowcast
now_codes = {'Atlanta':'GDPNOW','St. Louis':'STLENI'}
now_df = pd.concat({k:fred.get_series(v) for k,v in now_codes.items()}, axis=1)
now_df.index = pd.to_datetime(
    now_df.index
          .to_period('Q')
          .to_timestamp(how='end')   # <- how='end' 을 키워드 인자로 전달
)
# 3) GDP YoY
yoy_raw = fetch_bea('T10111')
yoy_df = (
     yoy_raw[yoy_raw['LineDescription'].isin(series)]
         .groupby(['Date', 'LineDescription'], as_index=False)['Value'].last()
         .pivot(index='Date', columns='LineDescription', values='Value')
         .sort_index()
 )
# 4) FOMC
proj_codes = {
    'Federal funds rate':('FEDTARMD','FEDTARMDLR'),
    'GDP growth':('GDPC1MD','GDPC1MDLR'),
    'PCE inflation':('PCECTPIMD','PCECTPIMDLR'),
    'Unemployment rate':('UNRATEMD','UNRATEMDLR')
}
title_map = {'Federal funds rate':'기준금리','GDP growth':'경제성장률',
             'PCE inflation':'인플레이션','Unemployment rate':'실업률'}
footnote_map = {'Federal funds rate':'※ 장기 목표 수준 금리','GDP growth':'※ 잠재 성장률',
                'PCE inflation':'※ 목표 인플레이션률','Unemployment rate':'※ 자연 실업률'}
years = ['2025','2026','2027','LR']
data_fomc = {}
for name,(m,lr) in proj_codes.items():
    ts = fred.get_series(m); ts_lr = fred.get_series(lr)
    vals = [ts[ts.index.year==y].iloc[-1] if not ts[ts.index.year==y].empty else None for y in [2025,2026,2027]]
    vals.append(ts_lr.iloc[-1] if len(ts_lr)>0 else None)
    data_fomc[name]=vals
df_fomc = pd.DataFrame(data_fomc,index=years)
ymax_fomc = df_fomc.max().max()*1.2

# 5) Inflation
series_codes_inf = {'CPI':'CPIAUCSL','Core CPI':'CPILFESL','PPI':'PPIACO',
                    'PCE':'PCEPI','Core PCE':'PCEPILFE',
                    'Expectations 1Y':'EXPINF1YR','Expectations 2Y':'EXPINF2YR',
                    'Expectations 3Y':'EXPINF3YR','Expectations 5Y':'EXPINF5YR',
                    'Expectations 10Y':'EXPINF10YR','Expectations 30Y':'EXPINF30YR'}
data_inf = load_fred_series(series_codes_inf).loc['2000-01-01':]
case_series = fred.get_series('CSUSHPINSA'); case_series.index=pd.to_datetime(case_series.index)
case_series = case_series.loc['2000-01-01':]
def calc_yoy(s): return s.pct_change(12)*100

# 6) Interest rates
series_codes_int = {
    '기준금리':'DFEDTARU','3개월':'DGS3MO','2년':'DGS2','5년':'DGS5',
    '10년':'DGS10','30년':'DGS30','10Y-3M':'T10Y3M','10Y-2Y':'T10Y2Y',
    '30년 모기지 금리':'MORTGAGE30US'  # ✅ 키 정확히 수정
}
data_int = load_fred_series(series_codes_int).loc['2000-01-01':]
latest_int = data_int.dropna(how='all').index.max()

# 연도 마크: 중복 제거
seen_years_int = set()
marks_int = {}
for i, dt in enumerate(data_int.index):
    if dt.month == 1 and dt.year not in seen_years_int:
        marks_int[i] = str(dt.year)
        seen_years_int.add(dt.year)


# 7) Labor market
series_codes_lab = {
    '실업률':'UNRATE','경제활동참가율':'CIVPART','고용률':'EMRATIO',
    '비농업고용자수':'PAYEMS','구인 건수':'JTSJOL',
    '자발적 이직률':'JTSQUR','평균 시급':'CES0500000003'
}
data_lab = load_fred_series(series_codes_lab).loc['2000-01-01':]

# 전처리: 비농업고용, 평균 시급 증감률
data_lab['전월비 비농업고용자수(천명)'] = data_lab['비농업고용자수'].diff()
data_lab['평균 시급 증감률'] = data_lab['평균 시급'].pct_change() * 100

latest_lab = data_lab.dropna(how='all').index.max()

# 슬라이더 마크: 1월만
marks_lab = {
    i: str(dt.year)
    for i, dt in enumerate(data_lab.index)
    if dt.month == 1
}


# 8) Exchange rates
currency_symbols = {
    '원':'KRW=X','달러 인덱스':'DX-Y.NYB','유로':'EURUSD=X','엔':'JPY=X',
    '위안':'CNY=X','파운드':'GBPUSD=X','캐나다달러':'CAD=X',
    '스웨덴 크로나':'SEK=X','스위스 프랑':'CHF=X'
}
data_exch = load_yf_data(list(currency_symbols.values()))
latest_exch = data_exch.dropna(how='all').index.max()

# 슬라이더 마크: 1월만
marks_exch = {
    i: str(dt.year)
    for i, dt in enumerate(data_exch.index)
    if dt.month == 1
}

# 9) Stock country
country_indices = {"미국":"^GSPC","유럽":"^STOXX","중국":"000001.SS","홍콩":"^HSI","일본":"^N225",
                   "대만":"^TWII","독일":"^GDAXI","영국":"^FTSE"}
df_country = load_yf_data(list(country_indices.values()))
index_name_map = {"미국":"S&P 500","유럽":"Euro Stoxx 600","중국":"상해종합지수","홍콩":"항생지수",
                  "일본":"닛케이 225","대만":"타이완 지수","독일":"DAX","영국":"FTSE 100"}
title_map_country = index_name_map

# 10) Stock company
main_indices = {"SP500":"^GSPC","Nasdaq":"^IXIC","DowJones":"^DJI"}
m7_tickers = {"애플":"AAPL","마이크로소프트":"MSFT","구글":"GOOGL","아마존":"AMZN",
              "메타":"META","테슬라":"TSLA","엔비디아":"NVDA"}
df_main = load_yf_data(list(main_indices.values()))
df_m7   = load_yf_data(list(m7_tickers.values()))

# ── 11) Stock company 제목 매핑 ──
title_map_company = {
    "SP500":    "S&P 500",
    "Nasdaq":   "Nasdaq",
    "DowJones": "Dow Jones"
}

# 12) Commodities
commodity_symbols = {"미국 유가 (WTI)":"CL=F","미국 천연가스 (HH)":"NG=F",
                     "유럽 천연가스 (TTF)":"TTF=F","미국 구리":"HG=F"}
EURUSD_TICKER="EURUSD=X"; MWH=0.293071; POUND=2204.62
df_commodity = load_yf_data(list(commodity_symbols.values())+[EURUSD_TICKER])

# 13) Housing market
housing_inds = {"중앙값 주택 가격":"MSPUS","주택 가격 지수":"CSUSHPINSA","주택 착공 건수":"HOUST",
                "건축 허가 건수":"PERMIT","주택 소유율":"RSAHORUSQ156S","신규 주택 판매":"HSN1FNSA","30년 모기지 금리":"MORTGAGE30US"}
df_housing = load_fred_datareader(housing_inds,"2000-01-01",pd.to_datetime("today").strftime("%Y-%m-%d"))
# 청크 3: GDP 전기비 탭 레이아웃 및 콜백

# 레이아웃 정의
layout_gdp_qoq = html.Div([
    html.H2('경제성장률 (GDP 전기비 연율)', style={'textAlign':'center'}),
    dcc.RangeSlider(
        id='date-slider',
        min=0, max=len(df_pct)-1,
        value=[len(df_pct)-20, len(df_pct)-1],
        marks={i: str(d.year) for i,d in enumerate(df_pct.index)
               if d.month==12 and d.year%5==0},
        allowCross=False
    ),
    dcc.Dropdown(
        id='contrib-dropdown',
        options=[{'label':f"{d.year} Q{(d.month-1)//3+1}", 'value':i}
                 for i,d in enumerate(df_pct.index)],
        value=len(df_pct)-1,
        clearable=False,
        style={'width':'200px','margin':'20px auto'}
    ),
    html.Div(id='charts', style={
        'display':'grid',
        'gridTemplateColumns':'repeat(2, 1fr)',
        'gap':'20px',
        'paddingTop':'20px'
    })
])

# 콜백 정의
@app.callback(
    Output('charts','children'),
    [Input('date-slider','value'),
     Input('contrib-dropdown','value')]
)
def render_gdp_qoq(date_range, contrib_idx):
    start, end = date_range
    dates = df_pct.index[start:end+1]
    latest = df_pct.index[contrib_idx]
    qnum = (latest.month-1)//3 + 1
    cards = []
    colors = px.colors.qualitative.Plotly

    # 1) GDP 성장률
    vals = df_pct['Gross domestic product'].loc[dates]
    fig1 = go.Figure(go.Scatter(x=dates, y=vals, mode='lines', line_color=colors[0]))
    fig1.update_layout(title='경제성장률', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig1, config={'responsive':True},
                  style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: {latest.year} Q{qnum} / {vals.loc[latest]:.2f}%",
               style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px',
              'borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # 2) 기여도 차트
    vals2 = df_contrib.loc[latest, series]
    fig2 = go.Figure(go.Bar(
        x=[labels[s] for s in series],
        y=vals2.values,
        marker_color=colors
    ))
    fig2.update_layout(title='기여도', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig2, config={'responsive':True},
                  style={'width':'100%','minHeight':'400px'}),
        html.P(f"GDP: {vals2['Gross domestic product']:.2f}%pt",
               style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px',
              'borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # 3+) 기타 시리즈
    for i, key in enumerate(series[1:], start=1):
        vals3 = df_pct[key].loc[dates]
        fig = go.Figure(go.Scatter(x=dates, y=vals3, mode='lines', line_color=colors[i]))
        fig.update_layout(title=labels[key], template='plotly_white', hovermode='x unified')
        cards.append(html.Div([
            dcc.Graph(figure=fig, config={'responsive':True},
                      style={'width':'100%','minHeight':'400px'}),
            html.P(f"{labels[key]}: {vals3.loc[latest]:.2f}%",
                   style={'textAlign':'center','fontSize':'12px'})
        ], style={'backgroundColor':'white','padding':'10px',
                  'borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    return cards



# 청크 4: GDP 전기비 전망 (Nowcast) 탭 레이아웃 및 콜백

# 레이아웃 정의
layout_gdp_nowcast = html.Div([
    html.H2('경제성장률 전망 (GDP Nowcast, 전기비 연율)', style={'textAlign':'center'}),
    dcc.RangeSlider(
        id='now-slider',
        min=0, max=len(now_df)-1,
        value=[len(now_df)-8, len(now_df)-1],
        marks={i: str(d.year) for i,d in enumerate(now_df.index) if d.quarter==2},
        allowCross=False
    ),
    html.Div(id='nowcast-graphs', style={
        'display':'grid',
        'gridTemplateColumns':'1fr 1fr',
        'gap':'20px',
        'paddingTop':'20px'
    })
])

# 콜백 정의
@app.callback(
    Output('nowcast-graphs','children'),
    Input('now-slider','value')
)
def render_gdp_nowcast(idx_range):
    s,e = idx_range
    dates = now_df.index[s:e+1]
    cards = []
    colors = px.colors.qualitative.Plotly
    for i,region in enumerate(now_df.columns):
        vals = now_df[region].loc[dates]
        fig = go.Figure(go.Scatter(x=dates, y=vals, mode='lines', line_color=colors[i]))
        fig.update_layout(title=f'{region} Fed Nowcast',
                          template='plotly_white', hovermode='x unified')
        cards.append(html.Div([
            dcc.Graph(figure=fig, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
            html.P(f"최신: {dates[-1].date()} / {vals.iloc[-1]:.2f}%", style={'textAlign':'center','fontSize':'12px'})
        ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))
    return cards
# 청크 5: GDP 전년비 탭 레이아웃 및 콜백

# 레이아웃 정의
layout_gdp_yoy = html.Div([
    html.H2('경제성장률 (GDP, 전년비)', style={'textAlign':'center'}),
    dcc.RangeSlider(
        id='yoy-slider',
        min=0, max=len(yoy_df)-1,
        value=[len(yoy_df)-8, len(yoy_df)-1],
        marks={i: str(d.year) for i, d in enumerate(yoy_df.index) if d.month==12 and d.year%5==0},
        allowCross=False
    ),
    html.Div(id='graphs-yoy', style={
        'display':'grid',
        'gridTemplateColumns':'1fr 1fr',
        'gap':'20px',
        'paddingTop':'20px'
    })
])

# 콜백 정의
@app.callback(
    Output('graphs-yoy','children'),
    Input('yoy-slider','value')
)
def render_gdp_yoy(rng):
    s, e = rng
    dates = yoy_df.index[s:e+1]
    cards = []
    colors = px.colors.qualitative.Plotly

    for i, key in enumerate(series):
        vals = yoy_df[key].loc[dates]
        fig = go.Figure(go.Scatter(
            x=dates, y=vals, mode='lines', line_color=colors[i],
            hovertemplate='%{x|%Y-%m-%d}<br>%{y:.2f}%'
        ))
        fig.update_layout(
            title=labels[key],
            template='plotly_white',
            hovermode='x unified'
        )
        cards.append(html.Div([
            dcc.Graph(figure=fig, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
            html.P(f"최신: {dates[-1].date()} / {vals.iloc[-1]:.2f}%", style={'textAlign':'center','fontSize':'12px'})
        ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    return cards
# 청크 6: FOMC 탭 레이아웃 및 콜백

# 레이아웃 정의
layout_fomc = html.Div([
    html.H2('FOMC 전망', style={'textAlign':'center'}),
    html.P(
        '※ 장기 전망은 정책 입안자가 추가 충격 없이 적절한 통화 정책 하에서 경제가 정상화된다고 가정한 전망치',
        style={'fontSize':'12px','fontStyle':'italic','color':'#666','textAlign':'center'}
    ),
    html.Div(id='fomc-charts', style={
        'display':'grid',
        'gridTemplateColumns':'1fr 1fr',
        'gap':'20px',
        'paddingTop':'20px'
    })
])

# 콜백 정의
@app.callback(
    Output('fomc-charts','children'),
    Input('url','pathname')  # FOMC 탭 진입 시
)
def render_fomc(path):
    if path != '/fomc':
        return []
    cards = []
    palette = px.colors.qualitative.Plotly
    for i, col in enumerate(df_fomc.columns):
        fig = go.Figure(go.Bar(
            x=years,
            y=df_fomc[col],
            text=df_fomc[col],
            textposition='inside',
            marker_color=palette[i],
            name=col
        ))
        fig.update_layout(
            title=title_map[col],
            template='plotly_white',
            yaxis=dict(range=[0, ymax_fomc], title='%'),
            hovermode='x unified'
        )
        cards.append(html.Div([
            dcc.Graph(figure=fig, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
            html.P(footnote_map[col], style={'fontSize':'12px','color':'#666','textAlign':'center'})
        ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))
    return cards
# 청크 7: 인플레이션 탭 레이아웃 및 콜백

# 레이아웃 정의
layout_inflation = html.Div([
    html.H2('인플레이션', style={'textAlign':'center'}),
    dcc.RangeSlider(
        id='inflation-slider',
        min=0, max=len(data_inf)-1,
        value=[0, len(data_inf)-1],
        marks={i: str(idx.year) for i, idx in enumerate(data_inf.index) if idx.month==1 and idx.year%5==0},
        allowCross=False
    ),
    html.Div(id='inflation-charts', style={
        'display':'grid',
        'gridTemplateColumns':'1fr 1fr',
        'gap':'20px',
        'paddingTop':'20px'
    })
])

# 콜백 정의
@app.callback(
    Output('inflation-charts','children'),
    Input('inflation-slider','value')
)
def render_inflation(rng):
    s, e = rng
    idx = data_inf.index[s:e+1]
    cards = []

    # CPI / Core CPI / PPI
    cpi = calc_yoy(data_inf['CPI']).reindex(idx)
    core = calc_yoy(data_inf['Core CPI']).reindex(idx)
    ppi = calc_yoy(data_inf['PPI']).reindex(idx)
    fig1 = go.Figure([
        go.Scatter(x=idx, y=cpi, name='CPI'),
        go.Scatter(x=idx, y=core, name='Core CPI'),
        go.Scatter(x=idx, y=ppi, name='PPI')
    ])
    fig1.update_layout(title='인플레이션(CPI, PPI)', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig1, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: {cpi.last_valid_index().date()} | CPI {cpi.iloc[-1]:.2f}% / Core {core.iloc[-1]:.2f}% / PPI {ppi.iloc[-1]:.2f}%", style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # PCE / Core PCE
    pce = calc_yoy(data_inf['PCE']).reindex(idx)
    cpce = calc_yoy(data_inf['Core PCE']).reindex(idx)
    fig2 = go.Figure([
        go.Scatter(x=idx, y=pce, name='PCE'),
        go.Scatter(x=idx, y=cpce, name='Core PCE')
    ])
    fig2.update_layout(title='개인소비지출 물가지수', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig2, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: {pce.last_valid_index().date()} | PCE {pce.iloc[-1]:.2f}% / Core {cpce.iloc[-1]:.2f}%", style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # 기대 인플레이션
    exp_df = data_inf[[col for col in data_inf.columns if 'Expectations' in col]].reindex(idx)
    fig3 = go.Figure([go.Scatter(x=idx, y=exp_df[col], name=col.split()[-1]) for col in exp_df])
    fig3.update_layout(title='기대 인플레이션', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig3, config={'responsive':True}, style={'width':'100%','minHeight':'400px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # Case-Shiller
    cs = calc_yoy(case_series).reindex(idx)
    fig4 = go.Figure(go.Scatter(x=idx, y=cs, name='CS HPI'))
    fig4.update_layout(title='케이스실러 주택 가격 지수', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig4, config={'responsive':True}, style={'width':'100%','minHeight':'400px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    return cards
layout_interest = html.Div([
    html.H2('금리', style={'textAlign':'center'}),
    dcc.RangeSlider(
        id='rate-slider',
        min=0, max=len(data_int)-1,
        value=[0, len(data_int)-1],
        marks=marks_int,  # ✅ 중복 제거된 마크 사용
        allowCross=False
    ),
    html.Div(id='charts-interest', style={
        'display':'grid',
        'gridTemplateColumns':'1fr 1fr',
        'gap':'20px',
        'paddingTop':'20px'
    })
])

@app.callback(
    Output('charts-interest','children'),
    Input('rate-slider','value')
)
def render_interest(rng):
    start_idx, _ = rng
    window = data_int.iloc[start_idx:]
    cards = []

    # 1) 기준금리
    s0 = window['기준금리']
    fig1 = go.Figure(go.Scatter(x=s0.index, y=s0, mode='lines'))
    fig1.update_layout(title='기준금리(상단)', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig1, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: {s0.index.max().date()} / {s0.iloc[-1]:.2f}%", style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # 2) 국채 금리
    bonds = ['3개월','2년','5년','10년','30년']
    fig2 = go.Figure([go.Scatter(x=window.index, y=window[col], name=col, mode='lines') for col in bonds])
    fig2.update_layout(title='국채 금리', template='plotly_white', hovermode='x unified')
    last_vals = window[bonds].dropna().iloc[-1]
    caption2 = ' | '.join(f"{col} {last_vals[col]:.2f}%" for col in bonds)
    cards.append(html.Div([
        dcc.Graph(figure=fig2, style={'width':'100%','minHeight':'400px'}),
        html.P(caption2, style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # 3) 장단기 금리 스프레드
    spreads = ['10Y-3M','10Y-2Y']
    fig3 = go.Figure([go.Scatter(x=window.index, y=window[col], name=col, mode='lines') for col in spreads])
    fig3.update_layout(title='장단기 금리 스프레드', template='plotly_white', hovermode='x unified')
    last_spd = window[spreads].dropna().iloc[-1]
    caption3 = ' | '.join(f"{col} {last_spd[col]:.2f}%" for col in spreads)
    cards.append(html.Div([
        dcc.Graph(figure=fig3, style={'width':'100%','minHeight':'400px'}),
        html.P(caption3, style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # 4) 30년 모기지 금리 ✅ (키 이름 수정)
    m = window['30년 모기지 금리'].dropna()
    fig4 = go.Figure(go.Scatter(x=m.index, y=m, mode='lines'))
    fig4.update_layout(title='30년 모기지 금리', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig4, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: {m.index.max().date()} / {m.iloc[-1]:.2f}%", style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    return cards



# 청크 9: 노동시장 탭 레이아웃 및 콜백

layout_labor = html.Div([
    html.H2('노동시장', style={'textAlign':'center'}),
    dcc.RangeSlider(
        id='labor-slider',
        min=0, max=len(data_lab)-1,
        value=[0, len(data_lab)-1],
        marks=marks_lab,
        allowCross=False
    ),
    html.Div(id='charts-labor', style={
        'display':'grid',
        'gridTemplateColumns':'1fr 1fr',
        'gap':'20px',
        'paddingTop':'20px'
    })
])

@app.callback(
    Output('charts-labor','children'),
    Input('labor-slider','value')
)
def render_labor(rng):
    start_idx, _ = rng
    window = data_lab.iloc[start_idx:]
    cards = []

    # 1) 실업률
    u = window['실업률'].dropna()
    fig1 = go.Figure(go.Scatter(x=u.index, y=u, mode='lines'))
    fig1.update_layout(title='실업률', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig1, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: {u.index.max().date()} / {u.iloc[-1]:.2f}%", style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # 2) 경제활동참가율 & 고용률
    part = window['경제활동참가율'].dropna()
    emp  = window['고용률'].dropna()
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=part.index, y=part, name='참가율', mode='lines'))
    fig2.add_trace(go.Scatter(x=emp.index, y=emp, name='고용률', mode='lines'))
    fig2.update_layout(title='참가율 & 고용률', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig2, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: 참가율 {part.iloc[-1]:.2f}%, 고용률 {emp.iloc[-1]:.2f}%", style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

    # 3) 비농업고용자수 변화
    c = window['전월비 비농업고용자수(천명)'].dropna()
    fig3 = go.Figure(go.Scatter(x=c.index, y=c, mode='lines'))
    fig3.update_layout(title='비농업고용자수 변화', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig3, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: {c.iloc[-1]:.0f} 천명", style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

       # 4) 구인 건수 및 이직률 (이직률은 우측 축)
    j = window['구인 건수'].dropna()
    q = window['자발적 이직률'].dropna()

    from plotly.subplots import make_subplots
    fig4 = make_subplots(specs=[[{"secondary_y": True}]])
    fig4.add_trace(go.Scatter(x=j.index, y=j, name='구인 건수', mode='lines'), secondary_y=False)
    fig4.add_trace(go.Scatter(x=q.index, y=q, name='이직률', mode='lines'), secondary_y=True)
    fig4.update_layout(title='구인 건수 & 이직률', template='plotly_white', hovermode='x unified')
    fig4.update_yaxes(title_text="구인 건수", secondary_y=False)
    fig4.update_yaxes(title_text="이직률 (%)", secondary_y=True)

    cards.append(html.Div([
        dcc.Graph(figure=fig4, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: 구인 {j.iloc[-1]:.0f}, 이직률 {q.iloc[-1]:.2f}%", style={'textAlign':'center','fontSize':'12px'})
    ], style={
        'backgroundColor':'white',
        'padding':'10px',
        'borderRadius':'5px',
        'boxShadow':'0 2px 4px rgba(0,0,0,0.1)'
    }))

    # 5) 평균 시급 수준
    lvl = window['평균 시급'].dropna()
    fig5 = go.Figure(go.Scatter(x=lvl.index, y=lvl, mode='lines'))
    fig5.update_layout(title='평균 시급 (USD)', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig5, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: {lvl.iloc[-1]:.2f} USD", style={'textAlign':'center','fontSize':'12px'})
    ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))

   # 6) 평균 시급 증감률
    pct = window['평균 시급 증감률'].dropna()
    fig6 = go.Figure(go.Scatter(x=pct.index, y=pct, mode='lines'))
    fig6.update_layout(title='평균 시급 증감률', template='plotly_white', hovermode='x unified')
    cards.append(html.Div([
        dcc.Graph(figure=fig6, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
        html.P(f"최신: {pct.iloc[-1]:.2f} %", style={'textAlign':'center','fontSize':'12px'})
    ], style={
        'backgroundColor':'white',
        'padding':'10px',
        'borderRadius':'5px',
        'boxShadow':'0 2px 4px rgba(0,0,0,0.1)'
    }))

    return cards
# ── 청크 10: 환율 탭 레이아웃 및 콜백 ──

# ✅ 슬라이더 마크 중복 방지
seen_years_exch = set()
marks_exch = {}
for i, dt in enumerate(data_exch.index):
    if dt.month == 1 and dt.year not in seen_years_exch:
        marks_exch[i] = str(dt.year)
        seen_years_exch.add(dt.year)

layout_exchange = html.Div([
    html.H2('환율', style={'textAlign':'center'}),
    dcc.RangeSlider(
        id='exchange-slider',
        min=0, max=len(data_exch)-1,
        value=[0, len(data_exch)-1],
        marks=marks_exch,
        allowCross=False
    ),
    html.Div(id='charts-exchange', style={
        'display':'grid','gridTemplateColumns':'1fr 1fr','gap':'20px','paddingTop':'20px'
    }),

    html.H3('환율 정규화', style={'textAlign':'center','marginTop':'40px'}),

    html.Div([
        dcc.Dropdown(
            id='norm-currencies',
            options=[{'label':k,'value':k} for k in currency_symbols],
            value=list(currency_symbols.keys()),
            multi=True,
            style={'width':'300px','margin':'0 auto 20px auto'}
        ),
        dcc.DatePickerRange(
            id='norm-range',
            min_date_allowed=data_exch.index.min(),
            max_date_allowed=latest_exch,
            start_date=data_exch.index.min(),
            end_date=latest_exch,
            display_format='YYYY-MM-DD',
            style={'display':'block','margin':'0 auto'}
        ),
        html.Div([
            dcc.Graph(id='norm-line', style={'width':'100%','minHeight':'400px'}),
            dcc.Graph(id='norm-bar',  style={'width':'100%','minHeight':'400px'})
        ], style={'display':'grid','gridTemplateColumns':'2fr 1fr','gap':'20px','paddingTop':'20px'})
    ])
])

# 메인 환율 그래프 콜백
@app.callback(
    Output('charts-exchange','children'),
    Input('exchange-slider','value')
)
def render_exchange(rng):
    start_idx, _ = rng
    window = data_exch.iloc[start_idx:]
    cards = []
    for name, sym in currency_symbols.items():
        if sym not in window.columns:
            continue
        series = window[sym].dropna()
        if series.empty:
            continue
        fig = go.Figure(go.Scatter(x=series.index, y=series, mode='lines', name=name))
        fig.update_layout(title=name, template='plotly_white', hovermode='x unified')
        cards.append(html.Div([
            dcc.Graph(figure=fig, style={'width':'100%','minHeight':'400px'}),
            html.P(f"최신: {series.index.max().date()} / {series.iloc[-1]:.2f}",
                   style={'textAlign':'center','fontSize':'12px'})
        ], style={
            'backgroundColor':'white','padding':'10px','borderRadius':'5px',
            'boxShadow':'0 2px 4px rgba(0,0,0,0.1)'
        }))
    return cards

# 정규화 선형 + 막대 콜백
@app.callback(
    Output('norm-line','figure'),
    Output('norm-bar','figure'),
    Input('norm-range','start_date'),
    Input('norm-range','end_date'),
    Input('norm-currencies','value')
)
def render_exchange_norm(start, end, selected):
    s, e = pd.to_datetime(start), pd.to_datetime(end)
    df = data_exch.loc[s:e].dropna(how='all')

    # 선택된 통화 필터링
    tickers = [currency_symbols[k] for k in selected if k in currency_symbols]
    df_sel = df[tickers].dropna()

    # 예외처리: 데이터 없을 경우 빈 figure
    if df_sel.empty:
        return go.Figure(), go.Figure()

    base = df_sel.iloc[0]
    norm = df_sel.div(base).mul(100)

    fig1 = go.Figure()
    for k in selected:
        sym = currency_symbols[k]
        if sym in norm.columns:
            fig1.add_trace(go.Scatter(
                x=norm.index, y=norm[sym],
                mode='lines', name=k
            ))
    fig1.update_layout(
        title=f"정규화 환율 (기준=100): {s.date()} ~ {e.date()}",
        template='plotly_white',
        hovermode='x unified'
    )

    # 막대 그래프
    last = norm.iloc[-1]
    fig2 = go.Figure()
    for k in selected:
        sym = currency_symbols[k]
        if sym in last:
            change = last[sym] - 100
            fig2.add_trace(go.Bar(x=[change], y=[k], name=k, orientation='h'))
    fig2.update_layout(
        title="변화율 (%)",
        template='plotly_white',
        yaxis={'autorange':'reversed'},
        hovermode='x unified'
    )

    return fig1, fig2


# 청크 11: 주가(국가) 탭 레이아웃 및 콜백

layout_stock_country = html.Div([
    html.H2("주가 (국가)", style={'textAlign':'center'}),
    html.Div([
        html.Label("기간 선택:", style={'marginRight':'10px'}),
        dcc.DatePickerRange(
            id='country-range',
            min_date_allowed=df_country.index.min(),
            max_date_allowed=df_country.index.max(),
            start_date=df_country.index.min(),
            end_date=df_country.index.max(),
            display_format='YYYY-MM-DD'
        )
    ], style={'display':'flex','justifyContent':'center','alignItems':'center','margin':'20px 0'}),
    html.Div(id='charts-stock-country', style={
        'display':'grid',
        'gridTemplateColumns':'1fr 1fr',
        'gap':'20px',
        'paddingTop':'20px'
    }),
    html.H3("정규화 비교", style={'textAlign':'center','marginTop':'40px'}),
    html.Div([
        dcc.Dropdown(
            id='country-norm-select',
            options=[{'label': name, 'value': name} for name in title_map_country],
            value=list(title_map_country.keys()),
            multi=True,
            style={'width':'300px','margin':'0 auto 20px auto'}
        ),
        html.Div([
            dcc.Graph(id='country-norm-line', config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
            dcc.Graph(id='country-norm-bar',  config={'responsive':True}, style={'width':'100%','minHeight':'400px'})
        ], style={'display':'grid','gridTemplateColumns':'1fr 1fr','gap':'20px'})
    ])
])

@app.callback(
    Output('charts-stock-country','children'),
    Input('country-range','start_date'),
    Input('country-range','end_date')
)
def render_stock_country(start, end):
    s, e = pd.to_datetime(start), pd.to_datetime(end)
    df = df_country.loc[s:e].dropna(how='all')
    cards = []
    for country, ticker in country_indices.items():
        series = df[ticker]
        fig = go.Figure(go.Scatter(x=series.index, y=series.values, mode='lines', name=country))
        fig.update_layout(title=title_map_country[country], template='plotly_white', hovermode='x unified')
        cards.append(html.Div([
            dcc.Graph(figure=fig, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
            html.P(f"최신: {series.index.max().date()} / {series.iloc[-1]:.1f}", style={'textAlign':'center','fontSize':'12px'})
        ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))
    return cards

@app.callback(
    Output('country-norm-line','figure'),
    Output('country-norm-bar','figure'),
    Input('country-range','start_date'),
    Input('country-range','end_date'),
    Input('country-norm-select','value')
)
def render_stock_country_norm(start, end, selected):
    s, e = pd.to_datetime(start), pd.to_datetime(end)
    df = df_country.loc[s:e].dropna(how='all')
    base = df.iloc[0]
    norm = df.div(base).mul(100)
    # 선형
    fig1 = go.Figure()
    for country in selected:
        fig1.add_trace(go.Scatter(x=norm.index, y=norm[country_indices[country]], mode='lines', name=country))
    fig1.update_layout(title=f"정규화 선: {s.date()} ~ {e.date()}", template='plotly_white', hovermode='x unified')
    # 막대
    last = norm.iloc[-1]
    fig2 = go.Figure()
    for country in selected:
        change = last[country_indices[country]] - 100
        fig2.add_trace(go.Bar(x=[change], y=[country], name=country, orientation='h'))
    fig2.update_layout(title="변화율 (%)", template='plotly_white', yaxis={'autorange':'reversed'}, hovermode='x unified')
    return fig1, fig2


# ── 청크 11.6: 주가(기업) 탭 레이아웃 정의 ──
layout_stock_company = html.Div([
    html.H2("주가 (기업)", style={'textAlign':'center'}),
    html.Div([
        html.Label("기간 선택:", style={'marginRight':'10px'}),
        dcc.DatePickerRange(
            id='company-range',
            min_date_allowed=df_m7.index.min(),
            max_date_allowed=df_m7.index.max(),
            start_date=df_m7.index.min(),
            end_date=df_m7.index.max(),
            display_format='YYYY-MM-DD'
        )
    ], style={'display':'flex','justifyContent':'center','alignItems':'center','margin':'20px 0'}),

    html.Div(id='charts-stock-company', style={
        'display':'grid',
        'gridTemplateColumns':'1fr 1fr',
        'gap':'20px',
        'paddingTop':'20px'
    }),

    html.H3("M7 정규화 비교", style={'textAlign':'center','marginTop':'40px'}),
    html.Div([
        dcc.Dropdown(
            id='company-norm-select',
            options=[{'label':k,'value':k} for k in m7_tickers],
            value=list(m7_tickers.keys()),
            multi=True,
            style={'width':'300px','margin':'0 auto 20px auto'}
        ),
        dcc.DatePickerRange(
            id='company-norm-range',
            min_date_allowed=df_m7.index.min(),
            max_date_allowed=df_m7.index.max(),
            start_date=df_m7.index.min(),
            end_date=df_m7.index.max(),
            display_format='YYYY-MM-DD',
            style={'display':'block','margin':'0 auto'}
        ),
        html.Div([
            dcc.Graph(id='company-norm-line', config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
            dcc.Graph(id='company-norm-bar', config={'responsive':True}, style={'width':'100%','minHeight':'400px'})
        ], style={'display':'grid','gridTemplateColumns':'2fr 1fr','gap':'20px','paddingTop':'20px'})
    ])
])


# ── 청크 11.5: 주가(기업) 탭 M7 정규화 콜백 ──
@app.callback(
    Output('company-norm-line','figure'),
    Output('company-norm-bar','figure'),
    Input('company-norm-range','start_date'),
    Input('company-norm-range','end_date'),
    Input('company-norm-select','value')
)
def render_company_norm(start, end, selected):
    s, e = pd.to_datetime(start), pd.to_datetime(end)
    dfm7_window = df_m7.loc[s:e].dropna(how='all')
    # 정규화 계산
    base = dfm7_window.iloc[0]
    norm = dfm7_window.div(base).mul(100)

    # 정규화 선형 차트
    fig1 = go.Figure()
    for name in selected:
        ticker = m7_tickers[name]
        fig1.add_trace(go.Scatter(x=norm.index, y=norm[ticker], mode='lines', name=name))
    fig1.update_layout(
        title=f"M7 기업 정규화: {s.date()} ~ {e.date()}",
        template='plotly_white',
        hovermode='x unified'
    )

    # 정규화 막대 차트
    last = norm.iloc[-1]
    fig2 = go.Figure()
    for name in selected:
        ticker = m7_tickers[name]
        change = last[ticker] - 100
        fig2.add_trace(go.Bar(x=[change], y=[name], orientation='h', name=name))
    fig2.update_layout(
        title="변화율 (%)",
        template='plotly_white',
        yaxis={'autorange':'reversed'},
        hovermode='x unified'
    )

    return fig1, fig2


# ── 청크 12 START ──
@app.callback(
    Output('charts-stock-company','children'),
    Input('company-range','start_date'),
    Input('company-range','end_date')
)
def render_stock_company(start, end):
    s, e = pd.to_datetime(start), pd.to_datetime(end)
    cards = []

    # 1) 주요 지수 (SP500, Nasdaq, DowJones)
    dfm_main = df_main.loc[s:e]
    for name, ticker in main_indices.items():
        series = dfm_main[ticker].dropna()
        fig = go.Figure(go.Scatter(
            x=series.index, y=series, mode='lines', name=name
        ))
        # 제목 매핑을 title_map_company로 변경
        fig.update_layout(
            title=title_map_company[name],
            template='plotly_white',
            hovermode='x unified'
        )
        cards.append(html.Div([
            dcc.Graph(figure=fig, config={'responsive':True},
                      style={'width':'100%','minHeight':'400px'}),
            html.P(f"최신: {series.index.max().date()} / {series.iloc[-1]:.1f}",
                   style={'textAlign':'center','fontSize':'12px'})
        ], style={
            'backgroundColor':'white','padding':'10px','borderRadius':'5px',
            'boxShadow':'0 2px 4px rgba(0,0,0,0.1)'
        }))

    # 2) M7 기업 비정규화
    dfm7 = df_m7.loc[s:e].dropna(how='all')
    figm = go.Figure()
    for name, ticker in m7_tickers.items():
        figm.add_trace(go.Scatter(
            x=dfm7.index, y=dfm7[ticker], mode='lines', name=name
        ))
    figm.update_layout(
        title='M7 기업',
        template='plotly_white',
        hovermode='x unified'
    )
    cards.append(html.Div([
        dcc.Graph(figure=figm, config={'responsive':True},
                  style={'width':'100%','minHeight':'400px'}),
        html.P(
            " ".join([f"{name}: {dfm7[ticker].iloc[-1]:.1f}"
                      for name, ticker in m7_tickers.items()]),
            style={'textAlign':'center','fontSize':'12px'}
        )
    ], style={
        'backgroundColor':'white','padding':'10px','borderRadius':'5px',
        'boxShadow':'0 2px 4px rgba(0,0,0,0.1)'
    }))

    return cards
# ── 청크 12 END ──


# 청크 13: 원자재 탭 레이아웃 및 콜백

layout_commodity = html.Div([
    html.H2("원자재", style={'textAlign':'center'}),
    html.Div([
        html.Label("기간 선택:", style={'marginRight':'10px'}),
        dcc.DatePickerRange(
            id='commodity-range',
            min_date_allowed=df_commodity.index.min(),
            max_date_allowed=df_commodity.index.max(),
            start_date=df_commodity.index.min(),
            end_date=df_commodity.index.max(),
            display_format='YYYY-MM-DD'
        )
    ], style={'display':'flex','justifyContent':'center','alignItems':'center','margin':'20px 0'}),
    html.Div(id='charts-commodity', style={
        'display':'grid',
        'gridTemplateColumns':'1fr 1fr',
        'gap':'20px',
        'paddingTop':'20px'
    }),
    html.H3("정규화 비교", style={'textAlign':'center','marginTop':'40px'}),
    html.Div([
        dcc.Dropdown(
            id='commodity-norm-select',
            options=[{'label':k,'value':k} for k in commodity_symbols],
            value=list(commodity_symbols.keys()),
            multi=True,
            style={'width':'300px','margin':'0 auto 20px auto'}
        ),
        html.Div([
            dcc.Graph(id='commodity-norm-line', config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
            dcc.Graph(id='commodity-norm-bar',  config={'responsive':True}, style={'width':'100%','minHeight':'400px'})
        ], style={'display':'grid','gridTemplateColumns':'3fr 1fr','gap':'20px'})
    ])
])

@app.callback(
    Output('charts-commodity','children'),
    Input('commodity-range','start_date'),
    Input('commodity-range','end_date')
)
def render_commodity(start, end):
    s,e = pd.to_datetime(start), pd.to_datetime(end)
    cards=[]
    dfc = df_commodity.loc[s:e]
    for name,sym in commodity_symbols.items():
        series = dfc[sym]
        if name=="유럽 천연가스 (TTF)":
            series = series*dfc[EURUSD_TICKER]*MWH
        if name=="미국 구리":
            series = series*POUND
        fig=go.Figure(go.Scatter(x=series.index, y=series.values, mode='lines', name=name))
        fig.update_layout(title=name, template='plotly_white', hovermode='x unified')
        cards.append(html.Div([
            dcc.Graph(figure=fig, config={'responsive':True}, style={'width':'100%','minHeight':'400px'}),
            html.P(f"최신: {series.iloc[-1]:.1f}", style={'textAlign':'center','fontSize':'12px'})
        ], style={'backgroundColor':'white','padding':'10px','borderRadius':'5px','boxShadow':'0 2px 4px rgba(0,0,0,0.1)'}))
    return cards

@app.callback(
    Output('commodity-norm-line','figure'),
    Output('commodity-norm-bar','figure'),
    Input('commodity-range','start_date'),
    Input('commodity-range','end_date'),
    Input('commodity-norm-select','value')
)
def render_commodity_norm(start, end, selected):
    s,e = pd.to_datetime(start), pd.to_datetime(end)
    dfc = df_commodity.loc[s:e]
    trans = {}
    for name,sym in commodity_symbols.items():
        series = dfc[sym]
        if name=="유럽 천연가스 (TTF)":
            series = series*dfc[EURUSD_TICKER]*MWH
        if name=="미국 구리":
            series = series*POUND
        trans[name]=series
    df_t = pd.DataFrame(trans).dropna(how='all')
    base = df_t.iloc[0]
    norm = df_t.div(base).mul(100)
    fig1=go.Figure(); fig2=go.Figure()
    for name in selected:
        fig1.add_trace(go.Scatter(x=norm.index, y=norm[name], mode='lines', name=name))
        change = norm[name].iloc[-1]-100
        fig2.add_trace(go.Bar(x=[change], y=[name], name=name, orientation='h'))
    fig1.update_layout(title='정규화 선', template='plotly_white', hovermode='x unified')
    fig2.update_layout(title='변화율 (%)', template='plotly_white', yaxis={'autorange':'reversed'}, hovermode='x unified')
    return fig1, fig2
# ── 청크 14: 주택시장 탭 레이아웃 및 콜백 ──

# 슬라이더 마크 (연도 중복 방지)
seen_years = set()
marks_housing = {}
for i, dt in enumerate(df_housing.index):
    if dt.month == 1 and dt.year not in seen_years:
        marks_housing[i] = str(dt.year)
        seen_years.add(dt.year)

layout_housing = html.Div([
    html.H2("주택시장", style={'textAlign':'center'}),
    dcc.RangeSlider(
        id='housing-slider',
        min=0,
        max=len(df_housing)-1,
        value=[0, len(df_housing)-1],
        marks=marks_housing,
        allowCross=False
    ),
    html.Div(id='charts-housing', style={
        'display': 'grid',
        'gridTemplateColumns': '1fr 1fr',
        'gap': '20px',
        'paddingTop': '20px'
    })
])

@app.callback(
    Output('charts-housing','children'),
    Input('housing-slider','value')
)
def render_housing(idx_range):
    start_idx, end_idx = idx_range
    if start_idx >= len(df_housing) or end_idx >= len(df_housing) or end_idx < start_idx:
        return [html.Div("유효하지 않은 슬라이더 범위입니다.")]

    dates = df_housing.index[start_idx:end_idx+1]
    dfh = df_housing.loc[dates]
    cards = []

    for name in housing_inds:
        if name not in dfh.columns:
            continue

        series = dfh[name].dropna()
        if series.empty:
            continue

        # 분기 단위 날짜 조정
        if name == "중앙값 주택 가격":
            series.index = pd.to_datetime([
                f"{d.year}-{'03-31' if d.quarter==1 else '06-30' if d.quarter==2 else '09-30' if d.quarter==3 else '12-31'}"
                for d in series.index.to_period('Q')
            ])

        if name == "주택 소유율":
            series.index = series.index.to_period('Q').to_timestamp(how='end')


        title_text = "주택 가격(중위값)" if name == "중앙값 주택 가격" else name
        fig = go.Figure(go.Scatter(x=series.index, y=series, mode='lines', name=name))
        fig.update_layout(title=title_text, template='plotly_white', hovermode='x unified')

        cards.append(html.Div([
            dcc.Graph(figure=fig, style={'width':'100%','minHeight':'400px'}),
            html.P(f"최신: {series.index[-1].date()} / {series.iloc[-1]:,.1f}",
                   style={'textAlign':'center','fontSize':'12px'})
        ], style={
            'backgroundColor': 'white',
            'padding': '10px',
            'borderRadius': '5px',
            'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'
        }))

    if not cards:
        return [html.Div("표시할 수 있는 주택시장 데이터가 없습니다.", style={'textAlign':'center','marginTop':'20px'})]

    return cards



# ── 청크 15: URL 경로별 페이지 라우팅 ──

@app.callback(
    Output('page-content', 'children'),
    Input('url', 'pathname')
)
def display_page(pathname):
    # pathname에 따라 미리 정의한 레이아웃을 반환합니다.
    return {
        '/':               layout_gdp_qoq,          # 기본 페이지
        '/gdp-qoq':        layout_gdp_qoq,
        '/gdp-nowcast':    layout_gdp_nowcast,
        '/gdp-yoy':        layout_gdp_yoy,
        '/fomc':           layout_fomc,
        '/inflation':      layout_inflation,
        '/interest':       layout_interest,
        '/labor':          layout_labor,
        '/exchange':       layout_exchange,
        '/stock-country':  layout_stock_country,
        '/stock-company':  layout_stock_company,
        '/commodity':      layout_commodity,
        '/housing':        layout_housing,
    }.get(
        pathname,
        # 정의되지 않은 경로일 경우 안내 문구 출력
        html.Div("메뉴에서 탭을 선택하세요.", style={'padding':'2rem','fontSize':'1.2rem'})
    )

# 청크 16: 앱 실행

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8050)

