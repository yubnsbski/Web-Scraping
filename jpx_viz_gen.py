# JPX NeuroFinance - 総合可視化 HTML 生成 v2
import sys
_log = open(r"C:\Users\ynobe\Documents\GitHub\Web-Scraping\viz_gen_log.txt", "w", encoding="utf-8")
sys.stdout = _log; sys.stderr = _log

import json, math, numpy as np

# ── データ読み込み ──────────────────────────────────────────────
WS = r"C:\Users\ynobe\Documents\GitHub\Web-Scraping"
with open(WS + r"\jpx_data.json", encoding='utf-8') as f:
    raw = json.load(f)
with open(WS + r"\jpx_ml_results.json", encoding='utf-8') as f:
    ml = json.load(f)
with open(WS + r"\extra_features_cache_v290.json", encoding='utf-8') as f:
    cache = json.load(f)
with open(WS + r"\jpx_ml_v3_results.json", encoding='utf-8') as f:
    v3 = json.load(f)

print("データ読み込み完了")

payout_map = {s['ticker']: s.get('payout_pct') for s in raw['stocks']}
extra_map  = cache['extra']
ml_stocks  = ml['stocks']
print(f"銘柄数: {len(ml_stocks)}")

IQR_LO = v3['outlier_bounds']['lo']
IQR_HI = v3['outlier_bounds']['hi']

# ── 銘柄データ統合 ──────────────────────────────────────────────
stocks_out = []
for s in ml_stocks:
    tk  = s['ticker']
    ex  = extra_map.get(tk, {})
    ret = s.get('actual_ret_1y')
    is_outlier = (ret is not None) and (ret < IQR_LO or ret > IQR_HI)
    scores = s.get('scores', {})

    stocks_out.append({
        'ticker':      tk,
        'name':        s['name'],
        'sector':      s.get('sector', 'Unknown'),
        'rank':        s.get('rank', 0),
        'total_score': round(s.get('total_score', 0), 4),
        'ret':         ret,
        'ret6m':       s.get('actual_ret_6m'),
        'yield':       s.get('actual_yield_pct') or s.get('yield_pct_original'),
        'payout':      payout_map.get(tk),
        'roe':         ex.get('roe'),
        'op_margin':   ex.get('op_margin'),
        'beta':        ex.get('beta'),
        'is_outlier':  is_outlier,
        'scores': {
            's_stability': round(scores.get('s_stability', 0), 3),
            's_health':    round(scores.get('s_health', 0), 3),
            's_yield':     round(scores.get('s_yield', 0), 3),
            's_momentum':  round(scores.get('s_momentum', 0), 3),
            's_payout':    round(scores.get('s_payout', 0), 3),
            's_streak':    round(scores.get('s_streak', 0), 3),
            's_sector':    round(scores.get('s_sector', 0), 3),
        }
    })

print(f"統合完了: {len(stocks_out)}銘柄")

# ── 象限計算 ──────────────────────────────────────────────────
clean = [s for s in stocks_out if not s['is_outlier'] and s['ret'] is not None and s['payout'] is not None]
rets    = [s['ret']    for s in clean]
payouts = [s['payout'] for s in clean]
rmin, rmax = min(rets), max(rets)
pmin, pmax = min(payouts), max(payouts)

def norm(v, lo, hi):
    return (v - lo) / (hi - lo) if hi > lo else 0.5

quad_count = {'HH': 0, 'HL': 0, 'LH': 0, 'LL': 0}
for s in clean:
    rn = norm(s['ret'], rmin, rmax)
    pn = norm(s['payout'], pmin, pmax)
    s['quadrant'] = ('H' if rn >= 0.5 else 'L') + ('H' if pn >= 0.5 else 'L')
    quad_count[s['quadrant']] += 1

print(f"象限分布: {quad_count}")

# ── セクター集計 ──────────────────────────────────────────────
sector_data = {}
for s in stocks_out:
    sec = s['sector']
    sector_data.setdefault(sec, {'rets': [], 'count': 0})
    if s['ret'] is not None:
        sector_data[sec]['rets'].append(s['ret'])
    sector_data[sec]['count'] += 1

sector_summary = {
    sec: {
        'avg':    round(float(np.mean(d['rets'])), 1),
        'median': round(float(np.median(d['rets'])), 1),
        'std':    round(float(np.std(d['rets'])), 1),
        'count':  d['count'],
        'q1':     round(float(np.percentile(d['rets'], 25)), 1),
        'q3':     round(float(np.percentile(d['rets'], 75)), 1),
    }
    for sec, d in sector_data.items() if d['rets']
}

# ── ML比較データ ──────────────────────────────────────────────
def _r2(src, model): return round(src.get(model, {}).get('cv_r2_mean', 0), 3)

ml_cmp = {
    'v1': {
        'Ridge':           round(ml['supervised']['models']['Ridge（正則化線形）']['cv_r2_mean'], 3),
        'RandomForest':    round(ml['supervised']['models']['RandomForest']['cv_r2_mean'], 3),
        'GradientBoosting':round(ml['supervised']['models']['GradientBoosting']['cv_r2_mean'], 3),
        'n':               ml.get('n_stocks', len(ml_stocks)),
    },
    'v2': {k: _r2(v3['models_baseline'], k) for k in ['Ridge','RandomForest','GradientBoosting']},
    'v3': {k: _r2(v3['models_v3'], k)       for k in ['Ridge','RandomForest','GradientBoosting']},
    'n_clean': v3['n_clean'],
    'fi_base':  v3['models_v3']['RandomForest'].get('fi_base', {}),
    'fi_extra': v3['models_v3']['RandomForest'].get('fi_extra', {}),
    'sector_avg': v3['sector_avg_ret'],
    'topix_ret':  v3.get('topix_ret_1y', 0),
}

print("可視化データ準備完了")

# ── JSON埋め込み ──────────────────────────────────────────────
stocks_json  = json.dumps(stocks_out,    ensure_ascii=False)
sector_json  = json.dumps(sector_summary, ensure_ascii=False)
ml_json      = json.dumps(ml_cmp,        ensure_ascii=False)
n_total      = len(stocks_out)
n_outlier    = sum(1 for s in stocks_out if s['is_outlier'])
n_clean_val  = v3['n_clean']

# ── HTML生成 ─────────────────────────────────────────────────
HTML = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JPX NeuroFinance Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {{
  --bg:      #080b14;
  --surface: #0e1422;
  --border:  #1c2540;
  --blue:    #3b82f6;
  --green:   #10b981;
  --yellow:  #f59e0b;
  --red:     #ef4444;
  --muted:   #475569;
  --text:    #e2e8f0;
  --sub:     #94a3b8;
  --r: 6px;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ height: 100%; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  line-height: 1.5;
}}

/* ── header ── */
.hdr {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 52px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
}}
.hdr-title {{ font-size: 15px; font-weight: 700; color: var(--text); letter-spacing: -0.3px; }}
.hdr-sub {{ font-size: 11px; color: var(--sub); margin-left: 10px; }}
.hdr-stats {{ display: flex; gap: 20px; }}
.stat {{ text-align: right; }}
.stat .val {{ font-size: 18px; font-weight: 700; color: var(--blue); }}
.stat .lbl {{ font-size: 10px; color: var(--sub); text-transform: uppercase; letter-spacing: 0.06em; }}

/* ── tabs ── */
.tabs {{
  display: flex;
  gap: 2px;
  padding: 0 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}}
.tab {{
  padding: 10px 16px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  color: var(--sub);
  border-bottom: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s;
  white-space: nowrap;
}}
.tab:hover {{ color: var(--text); }}
.tab.active {{ color: var(--blue); border-bottom-color: var(--blue); }}

/* ── layout ── */
.panel {{ display: none; padding: 20px 24px; }}
.panel.active {{ display: block; }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.grid3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
.grid4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}

/* ── card ── */
.card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 16px;
}}
.card-title {{
  font-size: 11px;
  font-weight: 600;
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  margin-bottom: 14px;
}}

/* ── kpi ── */
.kpi {{ display: flex; flex-direction: column; }}
.kpi .v {{ font-size: 28px; font-weight: 700; line-height: 1; }}
.kpi .l {{ font-size: 11px; color: var(--sub); margin-top: 4px; }}
.kpi-row {{ display: flex; gap: 12px; margin-bottom: 16px; }}
.kpi-sm {{ flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r); padding: 12px 14px; }}
.kpi-sm .v {{ font-size: 20px; font-weight: 700; }}
.kpi-sm .l {{ font-size: 10px; color: var(--sub); margin-top: 2px; }}

/* ── chart wrapper ── */
.ch {{ position: relative; }}
.ch-280 {{ height: 280px; }}
.ch-340 {{ height: 340px; }}
.ch-200 {{ height: 200px; }}

/* ── table ── */
.toolbar {{
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
}}
.toolbar label {{ font-size: 11px; color: var(--sub); font-weight: 500; }}
input[type=text], select {{
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 12px;
  outline: none;
}}
input[type=text]:focus, select:focus {{ border-color: var(--blue); }}
input[type=text] {{ width: 220px; }}

.tbl-wrap {{ overflow: auto; max-height: 620px; border-radius: var(--r); border: 1px solid var(--border); }}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}}
thead tr {{
  background: #111827;
  position: sticky;
  top: 0;
  z-index: 2;
}}
th {{
  padding: 9px 12px;
  text-align: left;
  font-size: 10px;
  font-weight: 600;
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid var(--border);
}}
th:hover {{ color: var(--text); }}
th.sorted {{ color: var(--blue); }}
td {{
  padding: 8px 12px;
  border-bottom: 1px solid #111827;
  white-space: nowrap;
  color: var(--sub);
}}
td:first-child {{ color: var(--muted); font-size: 11px; }}
td.name-col {{ color: var(--text); font-weight: 500; max-width: 160px; overflow: hidden; text-overflow: ellipsis; }}
td.ticker-col {{ color: var(--sub); font-family: monospace; }}
tbody tr:hover {{ background: #0d1525; }}

.pos {{ color: var(--green) !important; }}
.neg {{ color: var(--red) !important; }}
.neu {{ color: var(--sub) !important; }}

/* ── score bar ── */
.sbar {{ display: flex; align-items: center; gap: 6px; }}
.sbar-bg {{
  flex: 1;
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
}}
.sbar-fill {{
  height: 100%;
  border-radius: 3px;
  background: var(--blue);
  transition: width 0.2s;
}}
.sbar-val {{ font-size: 11px; font-weight: 600; color: var(--text); min-width: 36px; text-align: right; }}

/* ── badges ── */
.badge {{
  display: inline-block;
  padding: 2px 7px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.03em;
}}
.b-hh {{ background: rgba(16,185,129,.15); color: var(--green); }}
.b-hl {{ background: rgba(59,130,246,.15); color: var(--blue); }}
.b-lh {{ background: rgba(245,158,11,.15); color: var(--yellow); }}
.b-ll {{ background: rgba(71,85,105,.2);   color: var(--muted); }}
.b-out {{ background: rgba(239,68,68,.15); color: var(--red); }}

/* ── dividers / misc ── */
hr {{ border: none; border-top: 1px solid var(--border); margin: 16px 0; }}
.note {{
  background: rgba(59,130,246,.08);
  border-left: 3px solid var(--blue);
  border-radius: 0 4px 4px 0;
  padding: 9px 14px;
  font-size: 11px;
  color: var(--sub);
  margin-bottom: 14px;
  line-height: 1.6;
}}
.row-kv {{ display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid var(--border); font-size: 12px; }}
.row-kv:last-child {{ border-bottom: none; }}
.row-kv .k {{ color: var(--sub); }}
.row-kv .v {{ font-weight: 600; }}
</style>
</head>
<body>

<!-- header -->
<div class="hdr">
  <div style="display:flex;align-items:baseline;gap:0">
    <span class="hdr-title">JPX NeuroFinance</span>
    <span class="hdr-sub">290銘柄 · 7軸スコアリング + ML拡張</span>
  </div>
  <div class="hdr-stats">
    <div class="stat"><div class="val">{n_total}</div><div class="lbl">Total Stocks</div></div>
    <div class="stat"><div class="val">{n_outlier}</div><div class="lbl">Outliers (IQR)</div></div>
    <div class="stat"><div class="val">{n_clean_val}</div><div class="lbl">Clean Set</div></div>
  </div>
</div>

<!-- tabs -->
<div class="tabs">
  <div class="tab active" onclick="tab(0)">ランキング</div>
  <div class="tab" onclick="tab(1)">MLモデル</div>
  <div class="tab" onclick="tab(2)">セクター</div>
  <div class="tab" onclick="tab(3)">散布図</div>
</div>

<!-- ─── TAB 0: ランキング ─────────────────────────────────── -->
<div class="panel active" id="p0">
  <div class="toolbar">
    <label>検索</label>
    <input type="text" id="q" placeholder="銘柄名 / コード / セクター..." oninput="renderTable()">
    <label>セクター</label>
    <select id="secSel" onchange="renderTable()"><option value="">全て</option></select>
    <label>表示</label>
    <select id="showSel" onchange="renderTable()">
      <option value="all">全銘柄</option>
      <option value="clean">外れ値除外</option>
      <option value="top50">上位50</option>
    </select>
    <span id="countBadge" style="font-size:11px;color:var(--sub);margin-left:auto"></span>
  </div>
  <div class="tbl-wrap">
    <table id="mainTbl">
      <thead>
        <tr>
          <th onclick="sortBy('rank')">順位</th>
          <th onclick="sortBy('name')">銘柄名</th>
          <th onclick="sortBy('ticker')" class="ticker-col">コード</th>
          <th onclick="sortBy('sector')">セクター</th>
          <th onclick="sortBy('total_score')">スコア</th>
          <th onclick="sortBy('yield')" style="text-align:right">利回り%</th>
          <th onclick="sortBy('ret')" style="text-align:right">1年R%</th>
          <th onclick="sortBy('payout')" style="text-align:right">配当性向%</th>
          <th onclick="sortBy('roe')" style="text-align:right">ROE%</th>
          <th onclick="sortBy('op_margin')" style="text-align:right">営業利益率%</th>
          <th onclick="sortBy('beta')" style="text-align:right">Beta</th>
        </tr>
      </thead>
      <tbody id="tblBody"></tbody>
    </table>
  </div>
</div>

<!-- ─── TAB 1: ML モデル ──────────────────────────────────── -->
<div class="panel" id="p1">
  <div class="grid4" style="margin-bottom:16px">
    <div class="card">
      <div class="card-title">最良モデル (v3)</div>
      <div class="kpi"><div class="v pos" id="bestR2">—</div><div class="l">RandomForest CV R²</div></div>
    </div>
    <div class="card">
      <div class="card-title">改善幅 RF</div>
      <div class="kpi"><div class="v pos" id="rfDelta">—</div><div class="l">7軸のみ → 拡充特徴量</div></div>
    </div>
    <div class="card">
      <div class="card-title">改善幅 GB</div>
      <div class="kpi"><div class="v pos" id="gbDelta">—</div><div class="l">GradientBoosting</div></div>
    </div>
    <div class="card">
      <div class="card-title">学習サンプル</div>
      <div class="kpi"><div class="v" id="nClean">—</div><div class="l">外れ値除外後</div></div>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <div class="card-title">CV R² — バージョン × モデル</div>
      <div class="ch ch-340"><canvas id="mlBar"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">特徴量重要度 — RF v3</div>
      <div class="ch ch-340"><canvas id="fiBar"></canvas></div>
    </div>
  </div>
  <div class="note" style="margin-top:14px">
    <b>v3のポイント:</b> セクター平均リターンが重要度最大（&gt;30%）— マクロテーマの影響をセクター変数が捕捉。
    7軸NeuroFinanceスコアの合計重要度は約22%で、ファンダメンタル説明力は限定的。
    Ridge（線形）は特徴量追加で悪化 → 予測因子に非線形交互作用が存在することを示唆。
  </div>
</div>

<!-- ─── TAB 2: セクター ───────────────────────────────────── -->
<div class="panel" id="p2">
  <div class="grid2" style="margin-bottom:16px">
    <div class="card">
      <div class="card-title">セクター平均リターン (%)</div>
      <div class="ch ch-340"><canvas id="secBar"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">セクター詳細</div>
      <div style="overflow:auto;max-height:340px">
        <table id="secTbl" style="width:100%;font-size:11px;border-collapse:collapse">
          <thead><tr>
            <th style="padding:6px 10px;text-align:left;color:var(--sub);font-size:10px;text-transform:uppercase;border-bottom:1px solid var(--border)">セクター</th>
            <th style="padding:6px 10px;text-align:right;color:var(--sub);font-size:10px;text-transform:uppercase;border-bottom:1px solid var(--border)">銘柄</th>
            <th style="padding:6px 10px;text-align:right;color:var(--sub);font-size:10px;text-transform:uppercase;border-bottom:1px solid var(--border)">平均R%</th>
            <th style="padding:6px 10px;text-align:right;color:var(--sub);font-size:10px;text-transform:uppercase;border-bottom:1px solid var(--border)">中央値%</th>
            <th style="padding:6px 10px;text-align:right;color:var(--sub);font-size:10px;text-transform:uppercase;border-bottom:1px solid var(--border)">Q1~Q3%</th>
          </tr></thead>
          <tbody id="secTblBody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ─── TAB 3: 散布図 ─────────────────────────────────────── -->
<div class="panel" id="p3">
  <div class="note">
    <b>象限定義</b> — 正規化リターン・配当性向の中央を基準に4象限分類。
    <span style="color:var(--green)">■ HH</span> 高R高配当性向 &nbsp;
    <span style="color:var(--blue)">■ HL</span> 高R低配当性向 &nbsp;
    <span style="color:var(--yellow)">■ LH</span> 低R高配当性向 &nbsp;
    <span style="color:var(--muted)">■ LL</span> 低R低配当性向 &nbsp;
    <span style="color:var(--red)">● 外れ値</span>
  </div>
  <div class="grid2">
    <div class="card">
      <div class="card-title">配当性向 vs 1年リターン</div>
      <div class="ch ch-340"><canvas id="scatter"></canvas></div>
    </div>
    <div class="card">
      <div class="card-title">象限分布</div>
      <div class="ch ch-200"><canvas id="quadDoughnut"></canvas></div>
      <hr>
      <div id="quadStats"></div>
    </div>
  </div>
</div>

<script>
const STOCKS  = {stocks_json};
const SECTORS = {sector_json};
const ML      = {ml_json};

// ─── tab switch ──────────────────────────────────────────────
function tab(i) {{
  document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('active',i===j));
  document.querySelectorAll('.panel').forEach((p,j)=>p.classList.toggle('active',i===j));
  if (i===1&&!window._ml)   {{ initML();  window._ml=true; }}
  if (i===2&&!window._sec)  {{ initSec(); window._sec=true; }}
  if (i===3&&!window._sc)   {{ initScatter(); window._sc=true; }}
}}

// ─── chart defaults ──────────────────────────────────────────
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#1c2540';
Chart.defaults.font.family = '-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif';

const _opts = (extra={{}}) => ({{
  responsive:true, maintainAspectRatio:false,
  plugins:{{ legend:{{ labels:{{ font:{{size:11}}, boxWidth:12 }} }} }},
  ...extra
}});

// ─── TAB 0: ランキング ───────────────────────────────────────
const sectors = [...new Set(STOCKS.map(s=>s.sector))].sort();
const sel = document.getElementById('secSel');
sectors.forEach(s=>{{ const o=document.createElement('option'); o.value=o.text=s; sel.appendChild(o); }});

let _sortKey='rank', _sortDir=1;

function sortBy(k) {{
  if(_sortKey===k) _sortDir*=-1; else {{ _sortKey=k; _sortDir=1; }}
  document.querySelectorAll('th').forEach(th=>th.classList.remove('sorted'));
  const clicked = [...document.querySelectorAll('th')].find(t=>t.getAttribute('onclick')==='sortBy(\''+k+'\')');
  if(clicked) clicked.classList.add('sorted');
  renderTable();
}}

function fmt(v, digits=1, suffix='') {{
  if(v==null) return '<span style="color:#334155">—</span>';
  const n = typeof v==='number'? v : parseFloat(v);
  if(isNaN(n)) return '<span style="color:#334155">—</span>';
  const s = n>=0 ? '+'+n.toFixed(digits) : n.toFixed(digits);
  const cls = n>0?'pos':n<0?'neg':'';
  return `<span class="${{cls}}">${{s}}${{suffix}}</span>`;
}}

function scoreBar(v) {{
  const pct = Math.round((v||0)*100);
  const hue = 200; // blue
  return `<div class="sbar"><div class="sbar-bg"><div class="sbar-fill" style="width:${{pct}}%"></div></div><span class="sbar-val">${{(v||0).toFixed(3)}}</span></div>`;
}}

function quadBadge(s) {{
  const q = s.quadrant;
  if(s.is_outlier) return '<span class="badge b-out">OUT</span>';
  if(!q) return '';
  const cls = {{HH:'b-hh',HL:'b-hl',LH:'b-lh',LL:'b-ll'}}[q]||'';
  return `<span class="badge ${{cls}}">${{q}}</span>`;
}}

function renderTable() {{
  const q = document.getElementById('q').value.toLowerCase();
  const sec = document.getElementById('secSel').value;
  const show = document.getElementById('showSel').value;

  let data = STOCKS.filter(s => {{
    if(sec && s.sector!==sec) return false;
    if(show==='clean' && s.is_outlier) return false;
    if(!q) return true;
    return s.name.toLowerCase().includes(q) ||
           s.ticker.includes(q) ||
           s.sector.toLowerCase().includes(q);
  }});

  data = [...data].sort((a,b) => {{
    let av = a[_sortKey], bv = b[_sortKey];
    if(av==null) av = _sortDir>0 ? Infinity : -Infinity;
    if(bv==null) bv = _sortDir>0 ? Infinity : -Infinity;
    return (av - bv) * _sortDir;
  }});

  if(show==='top50') data=data.slice(0,50);

  document.getElementById('countBadge').textContent = `${{data.length}} 銘柄`;

  const rows = data.map(s => `<tr>
    <td>${{s.rank}}</td>
    <td class="name-col" title="${{s.name}}">${{s.name}}</td>
    <td class="ticker-col">${{s.ticker}}</td>
    <td style="color:var(--sub)">${{s.sector}}</td>
    <td>${{scoreBar(s.total_score)}}</td>
    <td style="text-align:right">${{fmt(s.yield,'1','%')}}</td>
    <td style="text-align:right">${{fmt(s.ret,'1','%')}}</td>
    <td style="text-align:right">${{fmt(s.payout,'1','%')}}</td>
    <td style="text-align:right">${{s.roe!=null?fmt(s.roe*100,'1','%'):'<span style="color:#334155">—</span>'}}</td>
    <td style="text-align:right">${{s.op_margin!=null?fmt(s.op_margin*100,'1','%'):'<span style="color:#334155">—</span>'}}</td>
    <td style="text-align:right">${{fmt(s.beta,'2')}}</td>
  </tr>`).join('');

  document.getElementById('tblBody').innerHTML = rows;
}}

renderTable();

// ─── TAB 1: ML ──────────────────────────────────────────────
function initML() {{
  const m = ML;
  const rfV2 = m.v2.RandomForest, rfV3 = m.v3.RandomForest;
  const gbV2 = m.v2.GradientBoosting, gbV3 = m.v3.GradientBoosting;

  document.getElementById('bestR2').textContent = rfV3.toFixed(3);
  document.getElementById('rfDelta').textContent = (rfV3-rfV2>=0?'+':'') + (rfV3-rfV2).toFixed(3);
  document.getElementById('gbDelta').textContent = (gbV3-gbV2>=0?'+':'') + (gbV3-gbV2).toFixed(3);
  document.getElementById('nClean').textContent  = m.n_clean + '銘柄';

  const models = ['Ridge','RandomForest','GradientBoosting'];
  new Chart(document.getElementById('mlBar'), {{
    type:'bar',
    data:{{
      labels: models,
      datasets:[
        {{ label:'v1 全7軸',       data:models.map(k=>m.v1[k]||0), backgroundColor:'rgba(71,85,105,.6)',   borderWidth:0 }},
        {{ label:'v2 外れ値除外',  data:models.map(k=>m.v2[k]||0), backgroundColor:'rgba(245,158,11,.65)', borderWidth:0 }},
        {{ label:'v3 拡充特徴量',  data:models.map(k=>m.v3[k]||0), backgroundColor:'rgba(59,130,246,.8)',  borderWidth:0 }},
      ]
    }},
    options:_opts({{
      scales:{{
        x:{{ grid:{{color:'#1c2540'}} }},
        y:{{ grid:{{color:'#1c2540'}}, title:{{display:true,text:'CV R²',font:{{size:11}}}}, suggestedMin:-0.8, suggestedMax:0.5 }}
      }}
    }})
  }});

  const fi = {{ ...m.fi_base, ...m.fi_extra }};
  const keys = Object.keys(fi).sort((a,b)=>fi[b]-fi[a]);
  const isExtra = k => m.fi_extra && m.fi_extra[k]!==undefined;
  new Chart(document.getElementById('fiBar'), {{
    type:'bar',
    data:{{
      labels: keys.map(k=>k.replace('s_','').replace('_avg_ret','_avg')),
      datasets:[{{ data:keys.map(k=>fi[k]), backgroundColor:keys.map(k=>isExtra(k)?'rgba(245,158,11,.8)':'rgba(59,130,246,.7)'), borderWidth:0 }}]
    }},
    options:_opts({{
      indexAxis:'y',
      plugins:{{
        legend:{{display:false}},
        tooltip:{{callbacks:{{label:ctx=>` ${{(ctx.raw*100).toFixed(1)}}%`}}}}
      }},
      scales:{{
        x:{{ grid:{{color:'#1c2540'}}, ticks:{{callback:v=>(v*100).toFixed(0)+'%'}} }},
        y:{{ grid:{{color:'#1c2540'}}, ticks:{{font:{{size:11}}}} }}
      }}
    }})
  }});
}}

// ─── TAB 2: セクター ─────────────────────────────────────────
function initSec() {{
  const secs = Object.keys(SECTORS).sort((a,b)=>SECTORS[b].avg-SECTORS[a].avg);
  const avgs = secs.map(s=>SECTORS[s].avg);

  new Chart(document.getElementById('secBar'), {{
    type:'bar', indexAxis:'y',
    data:{{
      labels:secs,
      datasets:[{{ data:avgs, backgroundColor:avgs.map(v=>v>=0?'rgba(16,185,129,.75)':'rgba(239,68,68,.7)'), borderWidth:0 }}]
    }},
    options:_opts({{
      plugins:{{ legend:{{display:false}}, tooltip:{{callbacks:{{label:ctx=>` ${{ctx.raw?.toFixed(1)}}%`}}}} }},
      scales:{{
        x:{{ grid:{{color:'#1c2540'}}, title:{{display:true,text:'平均リターン (%)',font:{{size:11}}}} }},
        y:{{ grid:{{color:'#1c2540'}}, ticks:{{font:{{size:11}}}} }}
      }}
    }})
  }});

  const tbody = document.getElementById('secTblBody');
  tbody.innerHTML = secs.map(s => {{
    const d=SECTORS[s];
    const ac=d.avg>=0?'color:var(--green)':'color:var(--red)';
    return `<tr>
      <td style="padding:5px 10px;color:var(--text)">${{s}}</td>
      <td style="padding:5px 10px;text-align:right;color:var(--sub)">${{d.count}}</td>
      <td style="padding:5px 10px;text-align:right;${{ac}};font-weight:600">${{d.avg>=0?'+':''}}${{d.avg}}%</td>
      <td style="padding:5px 10px;text-align:right;color:var(--sub)">${{d.median>=0?'+':''}}${{d.median}}%</td>
      <td style="padding:5px 10px;text-align:right;color:var(--sub)">${{d.q1}}~${{d.q3}}%</td>
    </tr>`;
  }}).join('');
}}

// ─── TAB 3: 散布図 ───────────────────────────────────────────
function initScatter() {{
  const clean   = STOCKS.filter(s=>!s.is_outlier&&s.ret!=null&&s.payout!=null);
  const outlier = STOCKS.filter(s=>s.is_outlier&&s.ret!=null&&s.payout!=null);
  const qcol = {{HH:'rgba(16,185,129,.8)',HL:'rgba(59,130,246,.8)',LH:'rgba(245,158,11,.8)',LL:'rgba(71,85,105,.65)'}};

  new Chart(document.getElementById('scatter'), {{
    type:'scatter',
    data:{{
      datasets:[
        ...['HH','HL','LH','LL'].map(q=>( {{
          label:q,
          data:clean.filter(s=>s.quadrant===q).map(s=>({{x:s.payout,y:s.ret,n:s.name,t:s.ticker}})),
          backgroundColor:qcol[q],
          pointRadius:4, pointHoverRadius:7,
        }})),
        {{
          label:'外れ値',
          data:outlier.map(s=>({{x:s.payout,y:s.ret,n:s.name,t:s.ticker}})),
          backgroundColor:'rgba(239,68,68,.9)',
          pointRadius:7, pointHoverRadius:10, pointStyle:'triangle',
        }}
      ]
    }},
    options:_opts({{
      plugins:{{
        legend:{{labels:{{font:{{size:11}},boxWidth:10}}}},
        tooltip:{{callbacks:{{
          label:ctx=>{{
            const p=ctx.raw;
            return [`${{p.n}} (${{p.t}})`,`配当性向: ${{p.x?.toFixed(1)}}%`,`1年R: ${{p.y?.toFixed(1)}}%`];
          }}
        }}}}
      }},
      scales:{{
        x:{{ grid:{{color:'#1c2540'}}, title:{{display:true,text:'配当性向 (%)',font:{{size:11}}}} }},
        y:{{ grid:{{color:'#1c2540'}}, title:{{display:true,text:'1年リターン (%)',font:{{size:11}}}} }}
      }}
    }})
  }});

  const qc = {{}};
  clean.forEach(s=>{{ qc[s.quadrant]=(qc[s.quadrant]||0)+1; }});
  const qlabels=['HH 高R高配当性向','HL 高R低配当性向','LH 低R高配当性向','LL 低R低配当性向'];
  new Chart(document.getElementById('quadDoughnut'), {{
    type:'doughnut',
    data:{{
      labels:qlabels,
      datasets:[{{
        data:[qc.HH||0,qc.HL||0,qc.LH||0,qc.LL||0],
        backgroundColor:['rgba(16,185,129,.8)','rgba(59,130,246,.8)','rgba(245,158,11,.8)','rgba(71,85,105,.65)'],
        borderWidth:0,
      }}]
    }},
    options:_opts({{
      cutout:'60%',
      plugins:{{ legend:{{position:'bottom',labels:{{font:{{size:10}},boxWidth:10}}}} }}
    }})
  }});

  document.getElementById('quadStats').innerHTML = [
    {{q:'HH',lbl:'高R 高配当性向',cls:'pos'}},
    {{q:'HL',lbl:'高R 低配当性向',cls:'pos'}},
    {{q:'LH',lbl:'低R 高配当性向',cls:'neg'}},
    {{q:'LL',lbl:'低R 低配当性向',cls:'neu'}},
  ].map(r=>`<div class="row-kv"><span class="k">${{r.lbl}}</span><span class="v ${{r.cls}}">${{qc[r.q]||0}} 銘柄</span></div>`).join('');
}}
</script>
</body>
</html>"""

OUT_HTML = r"C:\Users\ynobe\Documents\GitHub\Web-Scraping\JPX_NeuroFinance_Dashboard.html"
with open(OUT_HTML, 'w', encoding='utf-8') as f:
    f.write(HTML)

print(f"\n完了: {OUT_HTML}")
_log.flush()
_log.close()
