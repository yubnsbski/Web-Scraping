# 市場データ運用 Runbook（Yahoo!ファイナンス）

「データ更新」画面で**市場データが入らない / 取得行数が少ない**ときに、原因を切り分けて確実にデータを入れるための運用ガイド。コードの仕様ではなく**運用上の勘所**を中心にまとめる。

## TL;DR

- ライブ取得（Yahoo直叩き）は **robots.txt とネットワーク**に依存し、環境によっては空になる。
- **確実に動くのは「ファイル取込（inbox）」**：手動エクスポートしたCSVを所定パスに置くだけ。
- 「全件 daily_bars」で行数が少ないのは **J-Quants が契約必須**だから（ユニバースを変えても直らない）。
- **「全株式（国内株式）」のユニバースは JPX の公開銘柄一覧から構築**する（下記）。未構築だと `domestic`/`prime` は財務CSVの数十件に縮退する。

## データ種別とエンドポイント

「データ更新」パネルの「データ種別」と、対応するAPIルート:

| データ種別 | エンドポイント | 取得元 | 備考 |
|---|---|---|---|
| 市場財務指標 | `POST /api/market/financials` | Yahoo v7 quote（＋日本版HTMLフォールバック） | PER/PBR/配当利回り/EPS/DPS/時価総額 |
| 株価四本値・出来高 | `POST /api/market/bars/universe` | Yahoo v8 chart | レジストリ/ユニバース展開→ `daily_bars` 集約 |
| 当日分足 | `POST /api/market/intraday` | finance.yahoo.co.jp 埋め込みJSON | その日のみ取得可 |
| ファイル取込（inbox） | `POST /api/market/inbox` | **ローカルCSV（取得なし）** | ネットワーク不要・確実 |

その他: `POST /api/market/prices`（最新終値）、`/api/market/ohlcv`、`/api/market/bars`。

## 全株式（国内株式）ユニバースの構築

`bars/universe` の `universe` に `domestic`/`all`/`prime`/`standard`/`growth` を指定したとき、**JPX由来のユニバースCSVがあればそれを使う**。無ければ従来どおり財務CSV（少数）にフォールバックする。全件を取りたいときは、まず一度だけユニバースを構築する。

1. JPX の「東証上場銘柄一覧」`data_j.xls` を入手（公開・契約不要）し、CSVに保存（Shift_JIS/CP932 のままでよい）。
   - 配布元: JPX「その他統計資料」内の上場銘柄一覧。
2. ユニバースCSVを構築（素の証券コードに整形、ETF/REIT/出資証券/外国株を除外）:

   ```bash
   investment-assistant market-universe-build --jpx data_j.csv \
     --output local_docs/market/domestic_universe.csv --scope domestic
   # → {"ticker_count": 3900+, "output_path": "local_docs/market/domestic_universe.csv"}
   ```

   `--scope` は `domestic|all|prime|standard|growth`。市場区分で絞り込める。
3. 既定パス（`local_docs/market/domestic_universe.csv`）以外に置く場合は環境変数で指定:

   ```bash
   export MARKET_DOMESTIC_UNIVERSE_PATH=/path/to/domestic_universe.csv
   ```

4. 全件 OHLCV を取得（**ネットワークが通る環境**で。コードは `.T` を自動付与）:

   ```bash
   # API 経由（フロントの「データ更新」と同じ経路）
   curl -s localhost:8000/api/market/bars/universe -d '{"universe":"domestic"}'
   # CLI 経由（レジストリ/明示ティッカーの場合）
   MARKET_ALLOW_ROBOTS_BYPASS=1 investment-assistant market-ohlcv \
     --tickers $(cut -d, -f1 local_docs/market/domestic_universe.csv | tail -n +2 | paste -sd,) \
     --max 0 --range 1mo --output-dir local_docs/market/ohlcv
   ```

> 注: 隔離実行環境（外向きHTTPが403/遮断）では手順4は空になる。その場合は許可付きのネットワークポリシーで環境を作り直すか、手元の通信可能な環境で実行する。ユニバース構築（手順1–3）はネットワーク不要。

## ライブ取得が空になる主因

1. **robots.txt** — Yahoo は chart/quote 系を robots で拒否しており、robots尊重フェッチは**空ボディ**を返す。
2. **外向きネットワーク不可** — 隔離環境（CI/サンドボックス等）は外部HTTPが 403/遮断され、robots.txt 自体が取れず**フェイルクローズ**で全拒否。
3. **レート制限 (429)** — 大量取得時。共有ランナーが間隔/リトライ/バッチ休憩で緩和するが、一度BANされると数時間空く。

### 個人利用の robots バイパス（オプトイン）

個人利用の範囲で robots ゲートだけ skip したい場合:

```bash
export MARKET_ALLOW_ROBOTS_BYPASS=1
```

- **robots だけ**を無視し、**SSRF対策・レート制限・User-Agent・キャッシュは維持**される。
- 既定は OFF（robots 尊重）。再配布・販売は不可。常時ポーリングは避ける。

## ファイル取込（inbox）= 確実な経路（推奨）

ネットワーク・契約・robots に依存しない取込。

1. Yahoo!ファイナンス等で確認した個人利用CSVを次に置く:

   ```
   local_docs/market/yahoo_prices_inbox.csv
   ```

2. UI「データ更新 → データ種別＝ファイル取込（inbox）→ 更新」。状態 `present` と銘柄→価格が表示される。

**受け付けるCSV**（ヘッダは寛容）:
- ティッカー列: `ticker` / `symbol` / `code` / `コード` / `銘柄` / `銘柄コード`
- 価格列: `close` / `adj close` / `終値` / `price` / `株価` / `現在値`
- BOM可、複数行ある場合は**後の行（新しい日付）が優先**。

例:

```csv
ticker,date,close,volume
8306,2026-06-15,1825,12000000
7203,2026-06-15,3120,8500000
```

毎日定刻（例 7:00）に同じファイルを更新しておけば、スケジュール取込でも同じデータが使える。

## 「取得行数が少ない（例: 81行で一定）」の切り分け

- まず**ユニバースが縮退していないか**を確認。`domestic`/`prime` でユニバースCSV未構築だと財務CSVの数十件に落ちる（上記「全株式ユニバースの構築」で解消）。レスポンスの `universe_source` が `domestic_universe:...` なら全件、`financials_csv:...` なら縮退している。
- 行数が**ユニバース件数に依らず一定**なら、それは銘柄ループのバグではなく**データソース側の制限**。
- 全件 `daily_bars` の少数行は、**J-Quants が契約必須**（provider policy 上 `jquants` は `contract_required`、`_ALWAYS_ALLOWED` ではない）であるため。無料/未契約ティアは遅延・限定データしか返さない。
- 対処: 有効な **J-Quants 有料契約**を使う、または日付窓を契約プランの範囲に合わせる。Yahoo 系（本Runbookの対象）とは独立。

## 価格プロバイダの切替（最新終値）

`/api/market/prices` の既定は Stooq。Yahoo にする場合:

```bash
export MARKET_PRICE_PROVIDER=yfinance   # 既定: stooq_public_csv
```

または API リクエストで `provider_id: "yfinance"` を渡す。

## コンプライアンス

- すべて**個人利用・オンデマンド**前提。取得データの**再配布・販売は不可**。
- 本番（`runtime_mode=production`）では未契約プロバイダはAPIが 400 を返す（provider policy）。
- 自動売買・断定的な売買推奨は本システムの対象外。
