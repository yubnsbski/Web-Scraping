# JPX ML v3 - 特徴量拡充 (ROE, Beta, OperatingMargin, SectorReturn)
import sys
_log = open(r"C:\Users\ynobe\Documents\GitHub\Web-Scraping\ml_v3_log.txt", "w", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log

import json
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

print("=== JPX ML v3 (特徴量拡充) ===")

SRC   = r"C:\Users\ynobe\Documents\GitHub\Web-Scraping\jpx_ml_results.json"
OUT   = r"C:\Users\ynobe\Documents\GitHub\Web-Scraping\jpx_ml_v3_results.json"
CACHE = r"C:\Users\ynobe\Documents\GitHub\Web-Scraping\extra_features_cache_v290.json"

with open(SRC, encoding='utf-8') as f:
    data = json.load(f)

stocks = data['stocks']
print(f"元データ: {len(stocks)}銘柄")

# --- yfinance で追加特徴量取得 (キャッシュ優先) ---
import yfinance as yf

if os.path.exists(CACHE):
    with open(CACHE, encoding='utf-8') as f:
        cache_data = json.load(f)
    extra = cache_data['extra']
    topix_ret_1y = cache_data.get('topix_ret_1y', 0.0)
    print(f"\nキャッシュ読み込み: {CACHE}")
    print(f"  TOPIX 1年リターン: {topix_ret_1y:.1f}%")
else:
    print("\n追加特徴量取得中 (yfinance)...")

    # TOPIX
    topix_ret_1y = 0.0
    try:
        topix = yf.download('1570.T', period='1y', auto_adjust=True, progress=False)['Close']
        t0 = float(topix.iloc[0].item() if hasattr(topix.iloc[0], 'item') else topix.iloc[0])
        t1 = float(topix.iloc[-1].item() if hasattr(topix.iloc[-1], 'item') else topix.iloc[-1])
        topix_ret_1y = (t1 - t0) / t0 * 100
        print(f"  TOPIX 1年リターン: {topix_ret_1y:.1f}%")
    except Exception as e:
        print(f"  TOPIX取得失敗: {e}")

    # 各銘柄の追加情報
    extra = {}
    fail_count = 0
    for i, s in enumerate(stocks):
        tk_str = s['ticker'] + '.T'
        try:
            tk = yf.Ticker(tk_str)
            full_info = tk.info
            roe       = full_info.get('returnOnEquity', None)
            op_margin = full_info.get('operatingMargins', None)
            beta_yf   = full_info.get('beta', None)

            def safe_float(v):
                try:
                    f = float(v)
                    return None if np.isnan(f) else f
                except Exception:
                    return None

            extra[s['ticker']] = {
                'roe':       safe_float(roe),
                'op_margin': safe_float(op_margin),
                'beta':      safe_float(beta_yf),
            }
        except Exception as e:
            extra[s['ticker']] = {'roe': None, 'op_margin': None, 'beta': None}
            fail_count += 1

        if (i + 1) % 20 == 0:
            n_ok = sum(1 for v in extra.values() if v.get('roe') is not None)
            print(f"  進捗: {i+1}/{len(stocks)} (ROE取得成功: {n_ok}件)")

    print(f"\n取得完了 (エラー: {fail_count}銘柄)")
    for feat in ['roe', 'op_margin', 'beta']:
        n_ok = sum(1 for v in extra.values() if v.get(feat) is not None)
        print(f"  {feat}: {n_ok}/{len(stocks)}")

    # キャッシュ保存
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump({'extra': extra, 'topix_ret_1y': topix_ret_1y}, f, ensure_ascii=False, indent=2)
    print(f"  キャッシュ保存: {CACHE}")

# --- セクター平均リターン ---
sector_rets = {}
for s in stocks:
    sec = s.get('sector', 'Unknown')
    r = s.get('actual_ret_1y', None)
    if r is not None:
        sector_rets.setdefault(sec, []).append(r)

sector_avg = {sec: float(np.mean(rets)) for sec, rets in sector_rets.items()}
print(f"\nセクター平均リターン:")
for sec, avg in sorted(sector_avg.items(), key=lambda x: -x[1]):
    print(f"  {sec}: {avg:.1f}%")

# --- 特徴量定義 ---
SCORE_KEYS  = data['score_keys']
EXTRA_KEYS  = ['roe', 'op_margin', 'beta']

def get_sector_ret(ticker):
    s = next((x for x in stocks if x['ticker'] == ticker), None)
    if s:
        return sector_avg.get(s.get('sector', ''), 0.0)
    return 0.0

def build_features(stock_list, include_extra=True):
    rows = []
    for s in stock_list:
        ex = extra.get(s['ticker'], {})
        base = [s['scores'][k] for k in SCORE_KEYS]
        if include_extra:
            ext_vals = [ex.get(k) for k in EXTRA_KEYS]
            ext_vals.append(get_sector_ret(s['ticker']))
            rows.append(base + ext_vals)
        else:
            rows.append(base)

    arr = np.array(rows, dtype=float)
    # NaN補完: 列の中央値 (all-NaN列は0)
    for col in range(arr.shape[1]):
        nan_mask = np.isnan(arr[:, col])
        if nan_mask.any():
            med = float(np.nanmedian(arr[:, col]))
            arr[nan_mask, col] = 0.0 if np.isnan(med) else med

    return arr

# --- IQR外れ値除外 ---
rets_all = np.array([s['actual_ret_1y'] for s in stocks])
q1, q3 = np.percentile(rets_all, 25), np.percentile(rets_all, 75)
iqr = q3 - q1
lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
clean = [s for s in stocks if lo <= s['actual_ret_1y'] <= hi]
print(f"\nクリーンデータ: {len(clean)}銘柄")

# --- ML ---
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score
from sklearn.metrics import r2_score, mean_absolute_error

def run_models(dataset, label, include_extra=True):
    X = build_features(dataset, include_extra=include_extra)
    y = np.array([s['actual_ret_1y'] for s in dataset])
    Xs = StandardScaler().fit_transform(X)
    cv_n = min(5, len(dataset))
    results = {}
    for name, model in [
        ('Ridge',           Ridge(alpha=1.0)),
        ('RandomForest',    RandomForestRegressor(n_estimators=100, random_state=42, max_depth=4)),
        ('GradientBoosting',GradientBoostingRegressor(n_estimators=100, random_state=42, max_depth=3)),
    ]:
        cv = cross_val_score(model, Xs, y, cv=cv_n, scoring='r2')
        model.fit(Xs, y)
        yp = model.predict(Xs)
        results[name] = {
            'cv_r2_mean': round(float(np.mean(cv)), 4),
            'cv_r2_std':  round(float(np.std(cv)), 4),
            'train_r2':   round(float(r2_score(y, yp)), 4),
            'mae_pct':    round(float(mean_absolute_error(y, yp)), 2),
        }
        print(f"  [{label}] {name}: CV R²={np.mean(cv):.3f}±{np.std(cv):.3f} MAE={mean_absolute_error(y,yp):.1f}%")

        if name == 'RandomForest' and include_extra:
            fi = model.feature_importances_
            n_base = len(SCORE_KEYS)
            results[name]['fi_base']  = {SCORE_KEYS[i]: round(float(fi[i]), 4) for i in range(n_base)}
            ext_names = EXTRA_KEYS + ['sector_avg_ret']
            results[name]['fi_extra'] = {ext_names[i]: round(float(fi[n_base+i]), 4) for i in range(len(ext_names))}

    return results

print("\n=== 7軸のみ (ベースライン) ===")
res_base = run_models(clean, "7軸", include_extra=False)

print("\n=== 7軸 + ROE + Beta + 営業利益率 + セクターリターン ===")
res_v3 = run_models(clean, "v3", include_extra=True)

print("\n改善幅 (ベースライン→v3):")
for m in ['Ridge', 'RandomForest', 'GradientBoosting']:
    b = res_base[m]['cv_r2_mean']
    a = res_v3[m]['cv_r2_mean']
    print(f"  {m}: {b:.3f} → {a:.3f} (Δ{a-b:+.3f})")

best_v3 = max(res_v3, key=lambda k: res_v3[k]['cv_r2_mean'])
print(f"\n最良モデル (v3): {best_v3} CV R²={res_v3[best_v3]['cv_r2_mean']:.3f}")

output = {
    "generated": __import__('datetime').datetime.now().isoformat(),
    "n_clean":   len(clean),
    "features_base":  SCORE_KEYS,
    "features_extra": EXTRA_KEYS + ['sector_avg_ret'],
    "outlier_bounds": {"lo": round(float(lo), 1), "hi": round(float(hi), 1)},
    "models_baseline": res_base,
    "models_v3":       res_v3,
    "improvement": {
        m: {"before": res_base[m]['cv_r2_mean'],
            "after":  res_v3[m]['cv_r2_mean'],
            "delta":  round(res_v3[m]['cv_r2_mean'] - res_base[m]['cv_r2_mean'], 4)}
        for m in res_base
    },
    "best_model_v3": best_v3,
    "sector_avg_ret": sector_avg,
    "topix_ret_1y": topix_ret_1y,
}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n完了: {OUT}")
_log.flush()
_log.close()
