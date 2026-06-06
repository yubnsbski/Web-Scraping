# Phase 4: 投資スコアリング

## 目的

ローカルCSVに入力した投資候補を、経費率、年率リターン、ボラティリティ、分散度で比較する。
この機能は比較材料を作るためのローカル処理であり、投資助言、売買推奨、自動売買ではない。
最終的な投資判断はユーザーが行う。

## コピペで動くローカル確認

以下はターミナルにそのまま貼り付けて実行できる。
Gemini API、外部API、証券口座、実注文機能は使わない。

```bash
cd /path/to/Web-Scraping
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

investment-assistant scoring-validate --path examples/funds.csv
investment-assistant scoring-rank --path examples/funds.csv --limit 3
```

手元でCSVを作って試す場合は、次のコマンドを使う。
`local_data/` は実行時データ置き場として `.gitignore` 対象にしているため、通常はコミットしない。

```bash
mkdir -p local_data
cat > local_data/funds.csv <<'DATA'
name,expense_ratio,annual_return,volatility,diversification_score
低コスト全世界株式,0.12,0.065,0.18,0.95
高コストテーマ型,1.20,0.080,0.35,0.45
債券バランス型,0.35,0.030,0.08,0.80
DATA

investment-assistant scoring-validate --path local_data/funds.csv
investment-assistant scoring-rank --path local_data/funds.csv --limit 3

# 比較テーブル表示 / JSON保存（上書きは --overwrite を明示）
investment-assistant scoring-rank --path local_data/funds.csv --limit 3 --format table
investment-assistant scoring-rank --path local_data/funds.csv --limit 3 --output local_data/ranking.json
investment-assistant scoring-rank --path local_data/funds.csv --limit 3 --output local_data/ranking.json --overwrite
```

## 出力オプション

- `--format table`: 順位・名称・総合スコア・各指標を人間向けの比較表で表示します（既定は `json`）。
- `--output PATH`: ランキングJSONをファイルへ保存し、標準出力には保存先と件数の要約を返します。
- `--overwrite`: `--output` 先が既に存在する場合の上書きを許可します（既定は誤上書き防止のため拒否）。
- 出力パスは `..` によるディレクトリ脱出を拒否します。

## CSV形式

必須列は以下の5列。

| 列名 | 意味 | 評価方向 | 例 |
| --- | --- | --- | --- |
| `name` | 投資候補名 | ラベル | `低コスト全世界株式` |
| `expense_ratio` | 経費率 | 低いほど高評価 | `0.12` |
| `annual_return` | 年率リターン | 高いほど高評価 | `0.065` |
| `volatility` | ボラティリティ | 低いほど高評価 | `0.18` |
| `diversification_score` | 分散度スコア | 高いほど高評価 | `0.95` |

`diversification_score` は0〜1の範囲で入力する。
`expense_ratio` と `volatility` は0以上にする。
`annual_return` はマイナス値も入力できるが、過去実績や想定値にすぎない点に注意する。

## スコア計算

各指標を0〜1に正規化してから、重み付き平均で合計スコアを作る。
デフォルト重みは以下。

| 指標 | デフォルト重み |
| --- | ---: |
| 経費率 | `0.30` |
| 年率リターン | `0.30` |
| ボラティリティ | `0.25` |
| 分散度 | `0.15` |

重みはCLIオプションで変更できる。

```bash
investment-assistant scoring-rank \
  --path examples/funds.csv \
  --limit 3 \
  --expense-weight 0.40 \
  --return-weight 0.20 \
  --volatility-weight 0.25 \
  --diversification-weight 0.15
```

## コンプライアンス上の注意

- Gemini APIは呼ばない。
- 実ネットワーク取得は行わない。
- 証券口座や取引APIには接続しない。
- 自動売買は行わない。
- ランキングは投資助言や売買推奨ではない。
- 根拠、不確実性、免責文を確認し、最終判断はユーザーが行う。
