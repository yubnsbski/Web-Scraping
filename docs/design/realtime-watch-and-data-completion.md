# 設計図: リアルタイム株価ウォッチ & データ補完パイプライン

非助言（non-advisory）の原則は不変。本書はデータ補完と「常時ウォッチできる」UIを足すための設計図。

## 大きな目的 (Big Purpose)
手間をかけずに市場データを**完全・最新**に保ち、ユーザーが**価格を一目で常時ウォッチ**できる
（ヒートマップ）投資ダッシュボードにする。断定的推奨・自動売買は行わない。

## データの現状（grounding）
- `local_docs/market/yahoo_financials.csv` … price/PER/PBR/DPS/利回り（Yahoo, 断続的に取得失敗）
- `local_docs/market/daily_bars.csv` … 日足OHLCV（chart APIで安定取得・銘柄数が多い）
- `local_docs/edinet/financials.csv` … 財務（EDINET, 991銘柄）
- 取得は `portfolio/yahoo_financials.py::fetch_yahoo_financials`、保存は
  `cli_market.py::run_market_financials`（追記マージ済み）。

## 小さな目標 (Small Goals) — 上から順に実装
1. **データ補完の堅牢化**（最優先・低リスク）
   - v7 quote / HTMLが失敗しても **chartエンドポイント（日足と同じv8）から株価をフォールバック取得**し、
     `not_found` を価格だけでも埋める。`fetch_yahoo_financials` に追加。
   - 効果: 断続失敗でも各銘柄の「株価」は確実に残る → ウォッチ/評価額が安定。
2. **不足データの可視化と一括補完**
   - 「どの銘柄が price / dps を欠くか」を返す `market financials gaps` ヘルパ＋APIを追加し、
     UIから「不足だけ補完」ボタンで対象だけ再取得（マージ保存）。
3. **常時ウォッチ ヒートマップUI**
   - 新タブ「ウォッチ」: 保有＋ウォッチリストの銘柄を、日次騰落率で色分け（緑=上昇/赤=下落）した
     グリッド表示。`daily_bars.csv`（直近2終値）＋`yahoo_financials.csv`（price）から算出。
   - 自動更新（ポーリング）とウォッチリストの localStorage 永続化。
4. **パイプライン改善**
   - 騰落率算出は `/api/market/heatmap`（決定的・サーバ集計）に集約しフロントは表示のみ。
   - daily_refresh に「不足補完パス」を組み込み、毎朝の取得漏れを翌日に自動回収。

## 進め方（運用）
- 1ターン = 1つの小目標を「設計→実装→テスト→push→draft PR」まで。**マージはユーザーの確認待ち**。
- ゲート: `ruff`, `mypy src`, `pytest`, フロントは `tsc --noEmit` + `vite build`。
- 既存の非助言ガード・evidence/disclaimer 構造は維持。

## 完了の定義（Definition of Done, 各目標）
- 決定的なサーバ集計（数値ロジックはPython側）＋ユニットテスト。
- フロントは表示のみ。投資助言・売買指示を出さない文言を維持。
