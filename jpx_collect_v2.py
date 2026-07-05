# JPX NeuroFinance - 銘柄数拡張版データ収集 v2
# 目標: 250+ 有効銘柄（現在 127 → 280+ 銘柄）
# 戦略: JPX CSV → バッチ価格DL → 個別.info → 7軸スコア → jpx_data.json
import sys
_log = open(r"C:\Users\ynobe\Desktop\collect_v2_log.txt", "w", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log

import math, time, json, warnings, os
from datetime import datetime, timedelta
import requests
import pandas as pd
import numpy as np
warnings.filterwarnings('ignore')

print("=== JPX NeuroFinance データ収集 v2 ===")
print(f"開始: {datetime.now().isoformat()}")

import yfinance as yf

# ─── 設定 ────────────────────────────────────────────────────────
MAX_TICKERS    = 700    # JPX CSVから試す銘柄数（プライム優先）
CACHE_PATH     = r"C:\Users\ynobe\Desktop\collect_cache_v2.json"
OUT_PATH       = r"C:\Users\ynobe\Desktop\jpx_data.json"
LAMBDA         = 2.0

WEIGHTS = {
    "stability":   0.25,
    "health":      0.20,
    "yield":       0.20,
    "momentum":    0.15,
    "payout":      0.10,
    "streak":      0.07,
    "sector_rank": 0.03,
}

# ─── 7軸スコア関数 ───────────────────────────────────────────────
def _cv(history):
    vals = [v for v in history if v > 0]
    if len(vals) < 2:
        return 0.5
    mean = np.mean(vals)
    return np.std(vals) / mean if mean > 0 else 1.0

def _cagr_3y(history):
    vals = [v for v in history if v > 0]
    if len(vals) < 2:
        return 0.0
    n = min(3, len(vals) - 1)
    if vals[-(n+1)] <= 0:
        return 0.0
    return (vals[-1] / vals[-(n+1)]) ** (1.0 / n) - 1.0

def score_stability(history, has_cut):
    cv = _cv(history)
    if cv <= 0.10:   base = 1.0
    elif cv <= 0.50: base = 1.0 - (cv - 0.10) / 0.40
    else:            base = 0.0
    if has_cut:
        return min(base * 0.10, 0.05)
    return max(0.0, base)

def score_health(equity_ratio, debt_equity):
    if equity_ratio >= 0.40:   eq_s = 1.0
    elif equity_ratio >= 0.20: eq_s = (equity_ratio - 0.20) / 0.20 * 0.7
    else:                      eq_s = equity_ratio / 0.20 * 0.20
    if debt_equity <= 1.0:     de_s = 1.0 - debt_equity * 0.33
    elif debt_equity <= 3.0:   de_s = max(0, 0.67 - (debt_equity - 1.0) / 2.0 * 0.67)
    else:                      de_s = 0.0
    return max(0.0, eq_s * 0.55 + de_s * 0.45)

def score_yield(dy):
    if dy <= 0:    return 0.0
    if dy > 0.12:  return 0.10
    if dy > 0.10:  return max(0.10, 0.30 - (dy - 0.10) / 0.02 * 0.20)
    if dy > 0.08:  return max(0.10, 0.80 - (dy - 0.08) / 0.02 * 0.50)
    return min(1.0, 1 / (1 + math.exp(-15 * (dy - 0.04))))

def score_momentum(history):
    if len(history) < 2:
        return 0.35
    cagr = _cagr_3y(history)
    if cagr >= 0.10:  return 1.0
    if cagr >= 0:     return 0.40 + cagr / 0.10 * 0.60
    return max(0.0, 0.40 + cagr / 0.10 * 0.60 * LAMBDA)

def score_payout(ratio):
    if ratio <= 0:    return 0.20
    if ratio > 1.20:  return 0.0
    if ratio > 1.0:   return max(0.0, 0.10 - (ratio - 1.0) / 0.20 * 0.10)
    if ratio > 0.80:  return max(0.0, 1.0 - (ratio - 0.80) / 0.20 * 0.90)
    if 0.30 <= ratio <= 0.70: return 1.0
    if ratio < 0.30:  return 0.20 + (ratio / 0.30) * 0.80
    return max(0.0, 1.0 - (ratio - 0.70) / 0.10 * 0.10)

def score_streak(years):
    if years <= 0: return 0.0
    return min(1.0, math.log(years + 1) / math.log(26))

# ─── Step 1: JPX CSV 取得 ─────────────────────────────────────────
JPX_CSV_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
)

FALLBACK_CODES = [
    # プライム主要高配当銘柄
    "8306","8316","8411","8354","8308","8331","8332","8337","8341","8356","8360",
    "8366","8370","8374","8379","8385","8386","8393","8309",
    "9432","9433","9434",
    "9501","9502","9503","9531","9532","9533","9505",
    "8058","8031","8001","8002","8053",
    "2914","2503","2502",
    "5019","5020","4005","4183","4188","4452",
    "5401","5411","5714","5802","5803",
    "7203","7201","7202","7269","7270","7272","6301","6302",
    "8801","8802","8830","3003","8815",
    "8750","8752","8766","8795","8804",
    "8267","9843","3382","2651",
    "6758","6501","6504","6508","6701","6702","6752",
    "4502","4503","4506","4523","4568",
    "6952","7012","7013","7011",
    "5706","5713",
    "1803","1802","1801",
    "4901","4902",
    "7951","6361","6367","6471","6472","6473","6478",
    "7741","7762","7751",
    "2802","2801","2871",
    "3101","3103","3401","3402",
    "3861","3863","3864",
    "9001","9002","9005","9006","9007","9008","9009","9020","9021",
    # スタンダード高配当
    "1332","1333","1605","1721","1801","1925","1928","2002","2212","2282",
    "2413","2432","2768","3086","3099","3197","3289","3405","3863",
    "4004","4063","4151","4324","4519","4543","4578","4612","4631",
    "5101","5108","5201","5202","5214","5233","5301","5332","5333",
    "5463","5631","5703","5715","5741","5812","5901",
    "6103","6141","6178","6201","6273","6326","6355","6383","6407","6444",
    "6481","6503","6590","6592","6640","6645","6674","6724","6750","6770",
    "7003","7004","7011","7022","7186","7202","7211","7261","7267","7270",
    "7272","7282","7296","7309","7453","7522","7532","7550","7581","7604",
    "7735","7740","7746","7780","7951","7966",
    "8001","8002","8015","8016","8020","8028","8035","8043","8044","8057",
    "8096","8097","8098","8113","8133","8136","8154","8173","8174","8185",
    "8218","8219","8233","8253","8260","8278","8282","8287","8289","8291",
    "8308","8316","8330","8331","8332","8337","8338","8341","8343","8344",
    "8345","8346","8348","8349","8350","8356","8358","8359","8360","8361",
    "8362","8363","8366","8367","8368","8369","8371","8374","8375","8377",
    "8379","8381","8385","8386","8387","8388","8390","8391","8393","8398",
    "8399","8400","8403","8404","8411","8418","8424","8425","8439","8473",
    "8591","8601","8604","8630","8697","8698","8725","8729","8750","8752",
    "8755","8766","8795","8801","8802","8804","8815","8830",
    "9001","9005","9006","9007","9008","9009","9020","9021","9022","9024",
    "9062","9064","9068","9069","9070","9075","9076","9101","9104","9107",
    "9202","9232","9301","9302","9303","9305","9308","9310","9375","9381",
    "9412","9432","9433","9434","9437","9501","9502","9503","9504","9505",
    "9506","9507","9508","9509","9511","9513","9531","9532","9533","9602",
    "9706","9715","9719","9728","9729","9735","9749","9757","9759","9766",
    "9783","9787","9792","9830","9831","9843","9861","9873","9876","9888",
    "9904","9908","9912","9913","9929","9937","9945","9948","9962","9986",
]

def fetch_jpx_list():
    try:
        r = requests.get(JPX_CSV_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            from io import BytesIO
            df = pd.read_excel(BytesIO(r.content), header=0)
            df.columns = [str(c).strip() for c in df.columns]
            code_col  = next((c for c in df.columns if "コード" in c), None)
            name_col  = next((c for c in df.columns if "銘柄名" in c or "会社名" in c), None)
            market_col = next((c for c in df.columns if "市場" in c or "区分" in c), None)
            if code_col:
                result = pd.DataFrame()
                result["code"]   = df[code_col].astype(str).str.strip().str.zfill(4)
                result["name"]   = df[name_col].astype(str) if name_col else result["code"]
                result["market"] = df[market_col].astype(str) if market_col else "東証"
                result = result[result["code"].str.match(r"^\d{4}$")].copy()
                # プライム優先ソート
                prime = result["market"].str.contains("プライム|Prime", case=False, na=False)
                result = pd.concat([result[prime], result[~prime]]).reset_index(drop=True)
                print(f"JPX CSV取得成功: {len(result)}銘柄 (プライム優先)")
                return result
    except Exception as e:
        print(f"JPX CSV失敗: {e} → フォールバックリスト使用")
    codes = list(dict.fromkeys(FALLBACK_CODES))  # 重複除去
    result = pd.DataFrame({"code": codes, "name": codes, "market": "東証プライム"})
    print(f"フォールバックリスト: {len(result)}銘柄")
    return result

tickers_df = fetch_jpx_list().head(MAX_TICKERS)
codes      = tickers_df["code"].tolist()
yf_tickers = [f"{c}.T" for c in codes]
code_to_name = dict(zip(tickers_df["code"], tickers_df["name"]))
print(f"対象銘柄数: {len(yf_tickers)}")

# ─── Step 2: バッチ価格取得 → 生存フィルタ ──────────────────────
print(f"\nバッチ価格取得中 ({len(yf_tickers)}銘柄)...")
try:
    raw_prices = yf.download(
        yf_tickers,
        period="1y",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    print(f"  shape: {raw_prices.shape}")
except Exception as e:
    print(f"バッチ取得エラー: {e}")
    raw_prices = pd.DataFrame()

# Close 列抽出
if not raw_prices.empty:
    if isinstance(raw_prices.columns, pd.MultiIndex):
        try:
            close_df = raw_prices["Close"]
        except Exception:
            close_df = pd.DataFrame()
    else:
        close_df = raw_prices
else:
    close_df = pd.DataFrame()

# 100日以上の価格がある銘柄を「生存」と見なす
alive = []
if not close_df.empty:
    for t in yf_tickers:
        if t in close_df.columns:
            n_valid = close_df[t].dropna().__len__()
            if n_valid >= 100:
                alive.append(t)

print(f"生存確認 (≥100日): {len(alive)}/{len(yf_tickers)} 銘柄")

alive_codes = [t.replace(".T", "") for t in alive]

# ─── Step 3: 個別.info 取得（キャッシュ活用） ────────────────────
cache = {}
if os.path.exists(CACHE_PATH):
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"\nキャッシュ読み込み: {len(cache)}銘柄")
    except Exception:
        cache = {}
else:
    print("\nキャッシュなし → 全件取得")

records_raw = []
n_skip = 0
n_fetch = 0
n_fail  = 0

print(f"\n個別.info 取得中 ({len(alive_codes)}銘柄)...")

for idx, code in enumerate(alive_codes):
    yticker = code + ".T"
    name    = code_to_name.get(code, code)

    # キャッシュヒット
    if code in cache:
        raw = cache[code]
        records_raw.append(raw)
        n_skip += 1
        if (idx + 1) % 50 == 0:
            print(f"  {idx+1}/{len(alive_codes)} (キャッシュ:{n_skip} 取得:{n_fetch} 失敗:{n_fail})")
        continue

    # 新規取得
    try:
        t = yf.Ticker(yticker)
        try:
            full_info = t.info
        except Exception:
            full_info = {}

        price = full_info.get("regularMarketPrice") or full_info.get("currentPrice")
        if not price:
            try:
                fi = t.fast_info
                price = getattr(fi, "last_price", None)
            except Exception:
                price = None
        if not price or price <= 0:
            n_fail += 1
            time.sleep(0.2)
            continue

        div_yield    = full_info.get("dividendYield", 0) or 0
        div_rate     = full_info.get("dividendRate", 0) or 0
        payout_ratio = full_info.get("payoutRatio", 0) or 0
        market_cap_m = (full_info.get("marketCap", 0) or 0) / 1_000_000
        sector       = full_info.get("sector", "") or full_info.get("industry", "") or ""

        # バランスシート
        equity_ratio = 0.30
        debt_equity  = 1.0
        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                te_keys  = [k for k in bs.index if "Stockholders" in str(k) or "Equity" in str(k)]
                ta_keys  = [k for k in bs.index if "Total Assets" in str(k) or "TotalAssets" in str(k)]
                ltd_keys = [k for k in bs.index if "Long Term Debt" in str(k) or "LongTermDebt" in str(k)]
                if te_keys and ta_keys:
                    te = float(bs.loc[te_keys[0]].iloc[0])
                    ta = float(bs.loc[ta_keys[0]].iloc[0])
                    if ta > 0:
                        equity_ratio = te / ta
                if te_keys and ltd_keys:
                    te_v  = float(bs.loc[te_keys[0]].iloc[0])
                    ltd_v = float(bs.loc[ltd_keys[0]].iloc[0])
                    if te_v > 0:
                        debt_equity = ltd_v / te_v
        except Exception:
            pass

        # 配当履歴
        dps_history        = []
        consecutive_raises = 0
        has_cut            = False
        try:
            divs = t.dividends
            if divs is not None and len(divs) > 0:
                div_annual = divs.groupby(divs.index.year).sum()
                dps_history = div_annual.tolist()
                n_raises = 0
                for k in range(len(dps_history) - 1, 0, -1):
                    if dps_history[k] > dps_history[k - 1] * 1.001:
                        n_raises += 1
                    else:
                        break
                consecutive_raises = n_raises
                for k in range(1, len(dps_history)):
                    if dps_history[k] < dps_history[k - 1] * 0.95:
                        has_cut = True
                        break
        except Exception:
            pass

        # DPS 補完
        if div_rate <= 0 and div_yield > 0:
            div_rate = price * div_yield
        if div_rate <= 0 and dps_history:
            div_rate = dps_history[-1]

        # 配当性向補完
        if payout_ratio <= 0 or payout_ratio > 1.5:
            eps = full_info.get("trailingEps", 0) or 0
            if eps > 0 and div_rate > 0:
                payout_ratio = div_rate / eps
            else:
                payout_ratio = 0.50

        raw = {
            "code": code,
            "name": name,
            "price": price,
            "dps": round(div_rate, 1),
            "div_yield_pct": round(div_yield * 100, 2),
            "payout_ratio": min(payout_ratio, 1.5),
            "equity_ratio": min(max(equity_ratio, 0), 1.0),
            "debt_equity": max(debt_equity, 0),
            "consecutive_raises": consecutive_raises,
            "has_cut": has_cut,
            "dps_history": dps_history,
            "market_cap_m": market_cap_m,
            "sector": sector,
        }
        records_raw.append(raw)
        cache[code] = raw
        n_fetch += 1

        # 50件ごとにキャッシュ保存
        if n_fetch % 50 == 0:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)

    except Exception as e:
        n_fail += 1

    if (idx + 1) % 50 == 0:
        print(f"  {idx+1}/{len(alive_codes)} (キャッシュ:{n_skip} 取得:{n_fetch} 失敗:{n_fail})")
    time.sleep(0.3)

# 最終キャッシュ保存
with open(CACHE_PATH, "w", encoding="utf-8") as f:
    json.dump(cache, f, ensure_ascii=False)

print(f"\n取得完了: 有効レコード {len(records_raw)}件")
print(f"  (キャッシュ:{n_skip} 新規:{n_fetch} 失敗:{n_fail})")

# ─── Step 4: スコアリング ─────────────────────────────────────────
print("\nスコアリング中...")

scored = []
for row in records_raw:
    history  = row.get("dps_history", [])
    dy_frac  = row["div_yield_pct"] / 100.0 if row["div_yield_pct"] > 0 else (
        row["dps"] / row["price"] if row["price"] > 0 and row["dps"] > 0 else 0
    )
    s_stab = score_stability(history, row["has_cut"])
    s_hlth = score_health(row["equity_ratio"], row["debt_equity"])
    s_yld  = score_yield(dy_frac)
    s_mom  = score_momentum(history)
    s_pay  = score_payout(row["payout_ratio"])
    s_str  = score_streak(row["consecutive_raises"])
    s_sect = 0.50  # 後でパーセンタイルで更新

    cv_val   = _cv(history)
    cagr_val = _cagr_3y(history)
    dy_pct   = round(dy_frac * 100, 2)

    scored.append({
        **row,
        "div_yield_pct": dy_pct,
        "s_stability": round(s_stab, 4),
        "s_health":    round(s_hlth, 4),
        "s_yield":     round(s_yld, 4),
        "s_momentum":  round(s_mom, 4),
        "s_payout":    round(s_pay, 4),
        "s_streak":    round(s_str, 4),
        "s_sector":    round(s_sect, 4),
        "dps_cv":      round(cv_val, 3),
        "dps_cagr_3y_pct": round(cagr_val * 100, 1),
    })

# DataFrame 化してセクター内順位更新
df = pd.DataFrame(scored)

# セクター内利回りパーセンタイル
for _, grp in df.groupby("sector"):
    if len(grp) > 1:
        rank_vals = grp["div_yield_pct"].rank(pct=True, ascending=False)
        df.loc[grp.index, "s_sector"] = rank_vals.apply(lambda r: round(1.0 - r, 4))

# 総合スコア
w = WEIGHTS
df["total_score"] = (
    df["s_stability"]   * w["stability"] +
    df["s_health"]      * w["health"] +
    df["s_yield"]       * w["yield"] +
    df["s_momentum"]    * w["momentum"] +
    df["s_payout"]      * w["payout"] +
    df["s_streak"]      * w["streak"] +
    df["s_sector"]      * w["sector_rank"]
).round(4)

# 配当ありのみ + スコア降順
df = df[df["div_yield_pct"] > 0].copy()
df = df.sort_values("total_score", ascending=False).reset_index(drop=True)
df["rank_new"] = range(1, len(df) + 1)

print(f"スコアリング完了: {len(df)} 銘柄（配当あり）")

# セクター分布
print("\nセクター分布:")
for sec, cnt in df["sector"].value_counts().head(15).items():
    print(f"  {sec}: {cnt}銘柄")

# ─── Step 5: jpx_data.json 出力 ──────────────────────────────────
SCORE_COLS = ["s_stability","s_health","s_yield","s_momentum","s_payout","s_streak","s_sector"]

records_out = []
for _, row in df.iterrows():
    yp = row["div_yield_pct"]
    records_out.append({
        "rank":       int(row["rank_new"]),
        "ticker":     str(row["code"]),
        "name":       str(row["name"]),
        "sector":     str(row.get("sector", "")),
        "total_score": round(float(row["total_score"]), 4),
        "yield_pct":  round(float(yp), 2) if pd.notna(yp) and 0 < yp <= 20 else None,
        "streak":     int(row.get("consecutive_raises", 0)),
        "payout_pct": round(float(row["payout_ratio"]) * 100, 1) if pd.notna(row.get("payout_ratio")) else None,
        "equity_pct": round(float(row["equity_ratio"]) * 100, 1) if pd.notna(row.get("equity_ratio")) else None,
        "has_cut":    "あり⚠" if row.get("has_cut") else "なし",
        "price":      float(row.get("price", 0)),
        "dps":        float(row.get("dps", 0)),
        "market_cap_m": float(row.get("market_cap_m", 0)),
        "dps_cv":     float(row.get("dps_cv", 0)),
        "dps_cagr_3y_pct": float(row.get("dps_cagr_3y_pct", 0)),
        "scores": {c: round(float(row[c]), 4) for c in SCORE_COLS},
    })

out = {
    "generated": datetime.now().isoformat(),
    "count":     len(records_out),
    "stocks":    records_out,
}

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"\n✅ 完了: {OUT_PATH}")
print(f"   銘柄数: {len(records_out)}")
print(f"   終了: {datetime.now().isoformat()}")

_log.flush()
_log.close()
