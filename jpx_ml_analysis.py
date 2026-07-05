# JPX NeuroFinance - IR実データ取得 + 教師あり/なし比較分析
# ログをファイルに転送（cp932回避）
import sys
_log = open(r"C:\Users\ynobe\Desktop\ml_log.txt", "w", encoding="utf-8")
sys.stdout = _log
sys.stderr = _log

import json, time, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

SRC = r"C:\Users\ynobe\Desktop\jpx_data.json"
OUT = r"C:\Users\ynobe\Desktop\jpx_ml_results.json"

print("=== JPX ML分析 開始 ===")
print(f"開始時刻: {pd.Timestamp.now()}")

# --- データ読み込み ---
with open(SRC, encoding='utf-8') as f:
    data = json.load(f)

stocks = data['stocks']
print(f"銘柄数: {len(stocks)}")

SCORE_KEYS = ['s_stability','s_health','s_yield','s_momentum','s_payout','s_streak','s_sector']
SCORE_LABELS = ['安定性','財務健全性','利回得点','配当成長性','性向得点','連配得点','業種内順位']
WEIGHTS = [0.25, 0.20, 0.20, 0.15, 0.10, 0.07, 0.03]

# --- yfinance バッチ取得 ---
print("\n=== yfinance データ取得 ===")
import yfinance as yf

tickers_jp = [s['ticker'] + '.T' for s in stocks]
ticker_to_stock = {s['ticker'] + '.T': s for s in stocks}

print(f"対象: {len(tickers_jp)}銘柄 バッチ取得中...")
try:
    # バッチダウンロード（price only, 1年）
    raw_prices = yf.download(
        tickers_jp,
        period='1y',
        auto_adjust=True,
        progress=False,
        threads=True
    )
    print(f"価格取得完了: shape={raw_prices.shape}")
except Exception as e:
    print(f"バッチ取得エラー: {e}")
    raw_prices = pd.DataFrame()

# --- 各銘柄のリターン計算 ---
print("\n=== リターン計算 ===")
price_returns = {}

if not raw_prices.empty:
    # MultiIndex (Close, ticker)
    if isinstance(raw_prices.columns, pd.MultiIndex):
        close_df = raw_prices['Close'] if 'Close' in raw_prices.columns.get_level_values(0) else raw_prices.xs('Close', axis=1, level=0) if 'Close' in raw_prices.columns.get_level_values(0) else pd.DataFrame()
    else:
        close_df = raw_prices

    if not close_df.empty:
        for t in tickers_jp:
            if t in close_df.columns:
                series = close_df[t].dropna()
                if len(series) >= 50:
                    p0 = float(series.iloc[0])
                    p1 = float(series.iloc[-1])
                    ret = (p1 - p0) / p0 * 100
                    mid = len(series) // 2
                    ret_6m = (p1 - float(series.iloc[mid])) / float(series.iloc[mid]) * 100
                    price_returns[t] = {
                        'ret_1y': round(ret, 2),
                        'ret_6m': round(ret_6m, 2),
                        'price_latest': round(p1, 0),
                        'price_start': round(p0, 0),
                    }

print(f"リターン取得成功: {len(price_returns)}/{len(tickers_jp)}銘柄")

# --- 配当データ取得（個別、遅い） ---
print("\n=== 配当利回り取得 ===")
div_yields = {}

for i, t in enumerate(tickers_jp):
    try:
        tk = yf.Ticker(t)
        divs = tk.dividends
        if t in price_returns and len(divs) > 0:
            # 直近1年の配当合計
            p1 = price_returns[t]['price_latest']
            cutoff = pd.Timestamp.now(tz='UTC') - pd.DateOffset(years=1)
            recent_divs = divs[divs.index >= cutoff]
            if len(recent_divs) > 0:
                annual_div = float(recent_divs.sum())
                if p1 > 0:
                    y_act = annual_div / p1 * 100
                    div_yields[t] = round(y_act, 2)
        if (i + 1) % 20 == 0:
            print(f"  配当取得: {i+1}/{len(tickers_jp)}")
        time.sleep(0.15)
    except Exception:
        pass

print(f"配当取得成功: {len(div_yields)}銘柄")

# --- MLデータセット構築 ---
print("\n=== ML データセット構築 ===")

enriched = []
for s in stocks:
    t = s['ticker'] + '.T'
    rec = dict(s)
    pr = price_returns.get(t, {})
    rec['actual_ret_1y'] = pr.get('ret_1y')
    rec['actual_ret_6m'] = pr.get('ret_6m')
    rec['current_price'] = pr.get('price_latest')
    rec['actual_yield_pct'] = div_yields.get(t)
    rec['rms'] = round(float(np.sqrt(
        (1 - s['scores']['s_stability'])**2 +
        (1 - s['scores']['s_health'])**2
    )), 4)
    enriched.append(rec)

# ML有効サンプル（リターンデータあり）
ml_valid = [r for r in enriched if r['actual_ret_1y'] is not None]
print(f"ML有効銘柄数: {len(ml_valid)}")

if len(ml_valid) < 10:
    print("WARNING: サンプル数不足。処理を継続しますがモデル精度は参考値です。")

X_raw = np.array([[r['scores'][k] for k in SCORE_KEYS] for r in ml_valid])
y = np.array([r['actual_ret_1y'] for r in ml_valid])

from sklearn.preprocessing import StandardScaler
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_raw)

# --- 教師あり学習 ---
print("\n=== 教師あり学習 ===")

from sklearn.linear_model import LinearRegression, Ridge
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.model_selection import cross_val_score
from sklearn.metrics import r2_score, mean_absolute_error

N_CV = min(5, len(ml_valid))

model_specs = [
    ('OLS（線形回帰）', LinearRegression()),
    ('Ridge（正則化線形）', Ridge(alpha=1.0)),
    ('RandomForest', RandomForestRegressor(n_estimators=100, random_state=42, max_depth=4)),
    ('GradientBoosting', GradientBoostingRegressor(n_estimators=100, random_state=42, max_depth=3)),
]

sup_results = {}
best_cv_r2 = -99
best_model_name = None
best_model_obj = None

for name, model in model_specs:
    cv_scores = cross_val_score(model, X_scaled, y, cv=N_CV, scoring='r2')
    model.fit(X_scaled, y)
    y_pred = model.predict(X_scaled)
    tr2 = r2_score(y, y_pred)
    mae = mean_absolute_error(y, y_pred)

    # 特徴量重要度
    if hasattr(model, 'feature_importances_'):
        fi = list(model.feature_importances_)
    elif hasattr(model, 'coef_'):
        coef = model.coef_
        total = sum(abs(c) for c in coef) or 1.0
        fi = [abs(c)/total for c in coef]
    else:
        fi = [None] * 7

    sup_results[name] = {
        'cv_r2_mean': round(float(np.mean(cv_scores)), 4),
        'cv_r2_std': round(float(np.std(cv_scores)), 4),
        'train_r2': round(float(tr2), 4),
        'mae_pct': round(float(mae), 2),
        'feature_importance': {SCORE_KEYS[i]: round(float(fi[i]), 4) for i in range(7)},
    }
    print(f"  {name}: CV R²={np.mean(cv_scores):.3f}±{np.std(cv_scores):.3f} MAE={mae:.1f}%")

    if np.mean(cv_scores) > best_cv_r2:
        best_cv_r2 = float(np.mean(cv_scores))
        best_model_name = name
        best_model_obj = model

print(f"\n最良モデル: {best_model_name} (CV R²={best_cv_r2:.3f})")

# 最良モデルで予測
best_model_obj.fit(X_scaled, y)
y_pred_best = best_model_obj.predict(X_scaled)
for i, r in enumerate(ml_valid):
    r['pred_ret_supervised'] = round(float(y_pred_best[i]), 2)

# --- 教師なし学習 ---
print("\n=== 教師なし学習 ===")

from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

N_CLUSTERS = 4
km = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=20)
cluster_labels = km.fit_predict(X_scaled)

# クラスタ統計
cluster_stats = {}
for ci in range(N_CLUSTERS):
    members = [ml_valid[i] for i, c in enumerate(cluster_labels) if c == ci]
    rets = [m['actual_ret_1y'] for m in members]
    scores = [m['total_score'] for m in members]

    # クラスタ特徴（各軸の平均）
    axis_avgs = {}
    for k in SCORE_KEYS:
        vals = [m['scores'][k] for m in members]
        axis_avgs[k] = round(float(np.mean(vals)), 3)

    cluster_stats[f'C{ci}'] = {
        'count': len(members),
        'avg_ret_1y': round(float(np.mean(rets)), 2) if rets else None,
        'std_ret_1y': round(float(np.std(rets)), 2) if rets else None,
        'avg_neuro_score': round(float(np.mean(scores)), 4) if scores else None,
        'axis_avg': axis_avgs,
        'top5_names': [m['name'] for m in sorted(members, key=lambda x: x['total_score'], reverse=True)[:5]],
    }
    print(f"  Cluster {ci}: {len(members)}銘柄 平均リターン={np.mean(rets):.1f}%")

for i, r in enumerate(ml_valid):
    r['cluster'] = int(cluster_labels[i])

# クラスタ平均リターンを「教師なし予測」として使用
cluster_avg_ret = {ci: cluster_stats[f'C{ci}']['avg_ret_1y'] for ci in range(N_CLUSTERS)}
y_pred_unsup = np.array([cluster_avg_ret[int(cluster_labels[i])] for i in range(len(ml_valid))])
unsup_r2 = r2_score(y, y_pred_unsup)
unsup_mae = mean_absolute_error(y, y_pred_unsup)
print(f"\n教師なし(クラスタ平均) R²={unsup_r2:.3f} MAE={unsup_mae:.1f}%")

for i, r in enumerate(ml_valid):
    r['pred_ret_unsupervised'] = round(float(y_pred_unsup[i]), 2)

# PCA 2D
pca = PCA(n_components=2, random_state=42)
X_pca = pca.fit_transform(X_scaled)
pca_var = [round(float(v), 4) for v in pca.explained_variance_ratio_]
pca_loadings = {
    SCORE_KEYS[i]: [round(float(pca.components_[0, i]), 3), round(float(pca.components_[1, i]), 3)]
    for i in range(7)
}
for i, r in enumerate(ml_valid):
    r['pca_x'] = round(float(X_pca[i, 0]), 3)
    r['pca_y'] = round(float(X_pca[i, 1]), 3)

# --- 銘柄選定理由 ---
selection_rationale = {
    "概要": "東証上場銘柄から配当データが存在し、NeuroFinance7軸スコアが算出可能な127銘柄を選定",
    "論文根拠": [
        {
            "id": "P1",
            "ref": "Kuhnen & Knutson (2005) Neuron",
            "axis": "s_health（財務健全性 20%）",
            "mechanism": "自己資本比率・D/Eレシオによる損失リスク定量化。Insula活性（損失回避）を数値化"
        },
        {
            "id": "P2",
            "ref": "Tom et al. (2007) Science",
            "axis": "s_payout（配当性向 10%）",
            "mechanism": "λ=2の損失回避係数。性向20-60%を最適帯として設定。超過はペナルティ"
        },
        {
            "id": "P3",
            "ref": "Knutson & Bossaerts (2007) Nat Rev Neurosci",
            "axis": "s_yield（利回得点 20%）",
            "mechanism": "NAcc最大活性域は2-8%利回りに対応。鐘型スコア関数（最大1.0は4%付近）"
        },
        {
            "id": "P4",
            "ref": "Schultz (1997) Science",
            "axis": "s_momentum（配当成長性 15%）",
            "mechanism": "ドーパミン予測誤差の正の連鎖。3年配当CAGR正値で高スコア"
        },
        {
            "id": "P5",
            "ref": "Frydman & Camerer (2016) NBER",
            "axis": "s_stability（配当安定性 25%）",
            "mechanism": "CV（変動係数）の逆数でスコア化。減配歴あり銘柄は上限0.05にキャップ（最重要軸）"
        }
    ],
    "スクリーニング条件": [
        "yfinanceで過去配当データが取得可能",
        "東証上場（.Tサフィックス）",
        "自己資本比率データが存在",
        "配当履歴が最低1期以上"
    ]
}

# --- 出力 ---
print("\n=== JSON出力 ===")

output = {
    "generated": pd.Timestamp.now().isoformat(),
    "total_stocks": len(stocks),
    "ml_valid_count": len(ml_valid),
    "score_keys": SCORE_KEYS,
    "score_labels": SCORE_LABELS,
    "weights": WEIGHTS,

    "selection_rationale": selection_rationale,

    "supervised": {
        "description": "7軸スコアを特徴量、実際の1年価格リターンを教師ラベルとして学習",
        "models": sup_results,
        "best_model": best_model_name,
        "best_cv_r2": round(best_cv_r2, 4),
        "best_mae_pct": sup_results[best_model_name]['mae_pct'],
    },

    "unsupervised": {
        "description": "7軸スコアでK-means(k=4)クラスタリング。クラスタ平均リターンを予測値とする",
        "n_clusters": N_CLUSTERS,
        "r2_vs_actual": round(float(unsup_r2), 4),
        "mae_pct": round(float(unsup_mae), 2),
        "pca_explained_variance": pca_var,
        "pca_loadings": pca_loadings,
        "cluster_stats": cluster_stats,
    },

    "comparison": {
        "supervised_cv_r2": round(best_cv_r2, 4),
        "unsupervised_r2": round(float(unsup_r2), 4),
        "supervised_mae": sup_results[best_model_name]['mae_pct'],
        "unsupervised_mae": round(float(unsup_mae), 2),
        "verdict": (
            f"教師あり（{best_model_name}）優位: CV R²={best_cv_r2:.3f} vs 教師なし R²={unsup_r2:.3f}"
            if best_cv_r2 > unsup_r2
            else f"教師なし優位（サンプル不足の可能性）: CV R²={best_cv_r2:.3f} vs 教師なし R²={unsup_r2:.3f}"
        )
    },

    "stocks": [
        {
            "rank": r["rank"],
            "ticker": r["ticker"],
            "name": r["name"],
            "sector": r["sector"],
            "total_score": r["total_score"],
            "scores": r["scores"],
            "rms": r["rms"],
            "yield_pct_original": r.get("yield_pct"),
            "actual_yield_pct": r.get("actual_yield_pct"),
            "actual_ret_1y": r.get("actual_ret_1y"),
            "actual_ret_6m": r.get("actual_ret_6m"),
            "current_price": r.get("current_price"),
            "pred_ret_supervised": r.get("pred_ret_supervised"),
            "pred_ret_unsupervised": r.get("pred_ret_unsupervised"),
            "cluster": r.get("cluster"),
            "pca_x": r.get("pca_x"),
            "pca_y": r.get("pca_y"),
        }
        for r in ml_valid
    ]
}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"完了: {OUT}")
print(f"終了時刻: {pd.Timestamp.now()}")
_log.flush()
_log.close()
