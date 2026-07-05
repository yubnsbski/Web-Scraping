# JPX ML v2 - 外れ値除外 + 精度改善分析
import sys
_log = open(r"C:\Users\ynobe\Documents\GitHub\Web-Scraping\ml_v2_log.txt", "w", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log

import json
import numpy as np
import warnings
warnings.filterwarnings('ignore')

SRC  = r"C:\Users\ynobe\Documents\GitHub\Web-Scraping\jpx_ml_results.json"
OUT  = r"C:\Users\ynobe\Documents\GitHub\Web-Scraping\jpx_ml_v2_results.json"

print("=== JPX ML v2 (外れ値除外) ===")
with open(SRC, encoding='utf-8') as f:
    data = json.load(f)

stocks = data['stocks']
print(f"元データ: {len(stocks)}銘柄")

SCORE_KEYS = data['score_keys']
SCORE_LABELS = data['score_labels']

# --- 外れ値検出 (IQR法) ---
rets = np.array([s['actual_ret_1y'] for s in stocks])
q1, q3 = np.percentile(rets, 25), np.percentile(rets, 75)
iqr = q3 - q1
lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr

print(f"\n外れ値検出 (IQR法):")
print(f"  Q1={q1:.1f}% Q3={q3:.1f}% IQR={iqr:.1f}%")
print(f"  正常範囲: [{lo:.1f}%, {hi:.1f}%]")

outliers = [s for s in stocks if s['actual_ret_1y'] < lo or s['actual_ret_1y'] > hi]
clean    = [s for s in stocks if lo <= s['actual_ret_1y'] <= hi]
print(f"  外れ値: {len(outliers)}銘柄 → {[o['name'] for o in outliers[:10]]}")
print(f"  クリーン: {len(clean)}銘柄")

# --- ML用データ ---
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score
from sklearn.metrics import r2_score, mean_absolute_error

def run_models(dataset, label):
    X = np.array([[s['scores'][k] for k in SCORE_KEYS] for s in dataset])
    y = np.array([s['actual_ret_1y'] for s in dataset])
    sc = StandardScaler()
    Xs = sc.fit_transform(X)
    n = len(dataset)
    cv_n = min(5, n)
    results = {}
    for name, model in [
        ('Ridge', Ridge(alpha=1.0)),
        ('RandomForest', RandomForestRegressor(n_estimators=100, random_state=42, max_depth=4)),
        ('GradientBoosting', GradientBoostingRegressor(n_estimators=100, random_state=42, max_depth=3)),
    ]:
        cv = cross_val_score(model, Xs, y, cv=cv_n, scoring='r2')
        model.fit(Xs, y)
        yp = model.predict(Xs)
        tr2 = r2_score(y, yp)
        mae = mean_absolute_error(y, yp)
        results[name] = {
            'cv_r2_mean': round(float(np.mean(cv)), 4),
            'cv_r2_std':  round(float(np.std(cv)), 4),
            'train_r2':   round(float(tr2), 4),
            'mae_pct':    round(float(mae), 2),
        }
        print(f"  [{label}] {name}: CV R²={np.mean(cv):.3f}±{np.std(cv):.3f} MAE={mae:.1f}%")
    return results

print("\n--- 全データ (n=127) ---")
res_all   = run_models(stocks, "全")
print("\n--- 外れ値除外 (n={}) ---".format(len(clean)))
res_clean = run_models(clean, "クリーン")

# --- 改善幅計算 ---
improvements = {}
for m in res_all:
    before = res_all[m]['cv_r2_mean']
    after  = res_clean[m]['cv_r2_mean']
    improvements[m] = {
        'before': before,
        'after':  after,
        'delta':  round(after - before, 4),
        'improved': after > before,
    }
    print(f"\n{m}: {before:.3f} → {after:.3f} (Δ{after-before:+.3f})")

# --- K-means (クリーンデータ) ---
from sklearn.cluster import KMeans
X_c = np.array([[s['scores'][k] for k in SCORE_KEYS] for s in clean])
y_c = np.array([s['actual_ret_1y'] for s in clean])
Xs_c = StandardScaler().fit_transform(X_c)
km = KMeans(n_clusters=4, random_state=42, n_init=20)
cl = km.fit_predict(Xs_c)
cluster_avgs = {ci: float(np.mean([y_c[i] for i, c in enumerate(cl) if c == ci])) for ci in range(4)}
y_unsup = np.array([cluster_avgs[c] for c in cl])
unsup_r2  = float(r2_score(y_c, y_unsup))
unsup_mae = float(mean_absolute_error(y_c, y_unsup))
print(f"\nK-means (クリーン) R²={unsup_r2:.3f} MAE={unsup_mae:.1f}%")

# 改善比較
best_sup = max(res_clean, key=lambda k: res_clean[k]['cv_r2_mean'])
print(f"\n最良教師あり: {best_sup} CV R²={res_clean[best_sup]['cv_r2_mean']:.3f}")
print(f"教師なし: R²={unsup_r2:.3f}")

# --- 出力 ---
output = {
    "generated": __import__('datetime').datetime.now().isoformat(),
    "outlier_method": "IQR (Q1-1.5*IQR, Q3+1.5*IQR)",
    "outlier_bounds": {"lo": round(float(lo), 1), "hi": round(float(hi), 1)},
    "n_total": len(stocks),
    "n_outliers": len(outliers),
    "n_clean": len(clean),
    "outlier_stocks": [{"ticker": o["ticker"], "name": o["name"], "actual_ret_1y": o["actual_ret_1y"]} for o in outliers],
    "models_all_data": res_all,
    "models_clean_data": res_clean,
    "improvements": improvements,
    "unsupervised_clean": {
        "r2": round(unsup_r2, 4),
        "mae_pct": round(unsup_mae, 2),
        "cluster_avg_ret": {f"C{k}": round(v, 2) for k, v in cluster_avgs.items()},
    },
    "comparison_summary": {
        "best_model": best_sup,
        "supervised_cv_r2_before": res_all[best_sup]['cv_r2_mean'],
        "supervised_cv_r2_after":  res_clean[best_sup]['cv_r2_mean'],
        "unsupervised_r2_before": data['unsupervised']['r2_vs_actual'],
        "unsupervised_r2_after":  round(unsup_r2, 4),
        "verdict": (
            f"外れ値{len(outliers)}銘柄除外後: CV R²={res_clean[best_sup]['cv_r2_mean']:.3f} "
            f"(改善Δ{res_clean[best_sup]['cv_r2_mean']-res_all[best_sup]['cv_r2_mean']:+.3f})"
        )
    }
}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n完了: {OUT}")
_log.flush()
_log.close()
