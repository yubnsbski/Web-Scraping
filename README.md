# Investment Assistant

Codex中心で開発・保守を自動化する、家庭向け自動化・投資支援システムの基盤です。

## 方針

- Pythonを主軸にし、LLM依存を最小化します。
- Gemini APIは無料枠を守るため、予算管理・キャッシュ・フォールバックを必須化します。
- Codexは実装、テスト、ドキュメント更新を進め、commit / PR / 本番反映前にユーザー承認を挟む運用を基本にします。
- 自動売買は実装せず、投資判断の最終責任はユーザーに残します。


## ターミナルにコピペできる運用Runbook

AI伴奏型で作業するときは、セットアップ、スクレイピング、RAG、スコアリング、品質チェックをターミナルへそのまま貼り付けられる形で進めます。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
source .venv/bin/activate
python -m pytest -q
ruff check .
mypy src
```

詳細なコピペ用コマンド集は `docs/terminal_runbook.md` を参照してください。

## セットアップ

このプロジェクトは Python 3.11以上が必須です。`python --version` が Python 2.7.x を指す環境では、必ず `python3` または `python3.11` を使ってください。

```bash
# まず、pyproject.toml があるリポジトリルートへ移動します。
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
pwd
ls pyproject.toml

python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

macOSなどで `python3 --version` が 3.11 未満の場合は、pyenvやHomebrew等で Python 3.11以上をインストールしてから仮想環境を作成してください。

## テスト

```bash
ruff check .
pytest
mypy src
```

## Phase 0〜1の範囲

- Phase 0: Codex運用基盤、Pythonプロジェクト設定、CI、ドキュメント。
- Phase 1: Gemini API無料枠ガード、SQLite使用量記録、SQLiteキャッシュ、サービス層、mockテスト。


## Gemini予算確認CLI

Gemini APIを呼ばずに、現在のローカル使用量を確認できます。

```bash
investment-assistant budget --json
python3 scripts/check_gemini_budget.py
```

## LLMサービスのスモークテスト

実Gemini APIを呼ばずに、fake clientで `LlmService` のキャッシュ・予算管理経路を確認できます。

```bash
investment-assistant smoke --prompt "hello"
python3 scripts/smoke_llm_service.py
```

## 安全なURL取得・スクレイピングCLI（Phase 2）

`robots.txt` 確認、domain単位のレート制限、SQLiteキャッシュを通じてURLを安全に取得します。`--dry-run` では対象URL本体を取得せず、robots.txt確認だけを行います。Webサイトを確認するときは、まずdry-runで許可状態を確認してから本文取得に進んでください。

```bash
# robots.txt確認だけ
investment-assistant fetch-url --url https://example.com/funds --dry-run

# 許可される場合だけ本文を取得し、SQLiteキャッシュに保存
investment-assistant fetch-url --url https://example.com/funds --preview-chars 300
```

取得本文をローカルファイルへ保存し、そのままRAGへindexする場合は `--save-text` を使います。HTMLページは `--extract-text` を付けると、タグ、script、styleを除いた本文テキストに正規化してから保存します。`--include-metadata` を付けると、保存ファイルの先頭に取得元URLや取得時刻も付与します。

```bash
mkdir -p local_docs
TARGET_URL="https://example.com/"
OUTPUT_PATH="local_docs/example.txt"

investment-assistant fetch-url \
  --url "$TARGET_URL" \
  --preview-chars 500 \
  --extract-text \
  --include-metadata \
  --save-text "$OUTPUT_PATH"

investment-assistant rag-index-dir --path local_docs
investment-assistant rag-search --query "Example Domain" --limit 5
investment-assistant rag-search --query "Example Domain" --limit 5 --format table
investment-assistant rag-search \
  --query "Example Domain" \
  --limit 5 \
  --format table \
  --columns rank,source_url,fetched_at,text_preview
investment-assistant rag-answer-context --query "Example Domain" --limit 5
```


複数URLをまとめて保存する場合は、ジョブ定義ファイルを使います。

```bash
investment-assistant fetch-job --path examples/fetch_job.yaml --dry-run
investment-assistant fetch-job --path examples/fetch_job.yaml
investment-assistant rag-index-dir --path local_docs
investment-assistant rag-search-job \
  --path examples/fetch_job.yaml \
  --format table \
  --columns rank,source_url,fetched_at,text_preview \
  --save-report local_reports/rag_search_job.md
```

ローカルでコピペ実行する手順と注意点は `docs/data_ingestion.md` を参照してください。

## ローカルRAG CLI（Phase 3）

Gemini APIを呼ばずに、ローカル文書をチャンク化してSQLiteに保存し、キーワード検索と引用用context作成を行います。

```bash
mkdir -p local_docs
cat > local_docs/sample.md <<'EOF'
# サンプル投資メモ

投資判断はユーザー本人が行います。
自動売買は行いません。
EOF

investment-assistant rag-index --path local_docs/sample.md
investment-assistant rag-index-dir --path local_docs
investment-assistant rag-search --query "投資判断" --limit 5
investment-assistant rag-search --query "投資判断" --limit 5 --format table
investment-assistant rag-answer-context --query "自動売買" --limit 5
```

詳細は `docs/rag.md` を参照してください。

## 投資スコアリングCLI（Phase 4）

Gemini APIを呼ばずに、ユーザーが用意したローカルCSVを透明なルールで比較します。これは投資助言や売買推奨ではなく、最終判断はユーザー本人が行います。自動売買は行いません。

```bash
mkdir -p local_data
cat > local_data/funds.csv <<'DATA'
name,expense_ratio,annual_return,volatility,diversification_score
低コスト全世界株式,0.12,0.065,0.18,0.95
高コストテーマ型,1.20,0.080,0.35,0.45
債券バランス型,0.35,0.030,0.08,0.80
DATA

investment-assistant scoring-rank --path local_data/funds.csv --limit 3

# 人間向けの比較テーブル表示
investment-assistant scoring-rank --path local_data/funds.csv --limit 3 --format table

# 結果をJSONファイルへ保存（既存ファイルは誤上書き防止。上書きは --overwrite を明示）
investment-assistant scoring-rank --path local_data/funds.csv --limit 3 --output local_data/ranking.json
investment-assistant scoring-rank --path local_data/funds.csv --limit 3 --output local_data/ranking.json --overwrite
```

`scoring-validate` はスコア計算前にCSVの入力検証だけを行い、成功時は `valid=true`、行数、警告一覧をJSONで返します。失敗時は `valid=false` とエラー一覧をJSONで返します。

詳細は `docs/scoring.md` を参照してください。


## アンサンブル予測CLI（Phase 5）

実際の財務データ（Shiller S&P500 月次系列、GitHubホスト）を取得し、複数のベース予測器を
組み合わせたアンサンブル予測を、取得・評価（ウォークフォワード・バックテスト）・予測まで
一貫して行います。これは投資助言ではなく、自動売買も行いません。最終判断はユーザー本人です。

```bash
# ベース予測器（naive/drift/linear_trend/holt/AR）は標準ライブラリのみで動作。
# 木アンサンブル（random_forest/gradient_boosting）を使う場合のみ追加依存を入れます。
python -m pip install -e '.[forecast]'

investment-assistant forecast-fetch-data --dest market/sp500.csv
investment-assistant forecast-evaluate --path market/sp500.csv --tail 240 --space returns
investment-assistant forecast-predict --path market/sp500.csv --horizon 1
```

ネットワークが無い場合は同梱の実データ小サンプル `examples/sp500_monthly_sample.csv` を
`--path` に指定すれば同じ評価・予測を再現できます。評価で得られた知見（リターン空間化で
アンサンブルが naive を上回る等）は `docs/forecasting.md` を参照してください。

## 複数AIオーケストレーションCLI

複数のLLM役割（ドラフト→レビュー→統合）を協調させ、根拠の確かな回答を作ります。すべて
ガード付き `LlmService` 経由で予算・キャッシュ・フォールバックが適用されます。`--call-real-api`
を付けなければローカル擬似クライアントでオフライン実行できます。

```bash
investment-assistant orchestrate-answer --query "分散投資の要点" --drafts 2 --hybrid
```

役割別に異なるモデルを割り当てる設計や注意点は `docs/orchestration.md` を参照してください。

## ハイブリッドRAG検索とキャッシュ整理

```bash
# BM25(語彙) + 埋め込み(意味) のハイブリッド検索（alphaで意味側の重み）
investment-assistant rag-search --query "債券 リスク" --hybrid --alpha 0.5

# キャッシュの期限切れ削除と件数上限の適用
investment-assistant cache-maintenance --max-rows 1000
```

## LlmService factory

`config/gemini.yaml` から、予算管理・キャッシュ・フォールバックを備えた `LlmService` を生成します。

```python
from investment_assistant.llm.factory import build_llm_service

service = build_llm_service()
response = service.generate(task_type="rag_answer", prompt="質問内容")
```


## Gemini実APIの手動確認（Phase 1.5）

実Gemini APIを呼ぶ経路は、単体テストでは使いません。手動確認時だけ `GEMINI_API_KEY` を設定し、明示的に `--call-real-api` を付けて実行します。

```bash
python -m pip install -e '.[gemini]'
export GEMINI_API_KEY=your_api_key
investment-assistant gemini-live --prompt "短く挨拶して" --call-real-api
python3 scripts/manual_gemini_check.py --prompt "短く挨拶して" --call-real-api
```

このコマンドも `LlmService` 経由なので、キャッシュ、予算ガード、使用量記録、フォールバックが適用されます。

## プライバシーと個人情報に関する注意

- `rag-answer --call-real-api` や `gemini-live` で**実Gemini APIを呼ぶと、プロンプトに含まれるローカル文書の内容（資産・口座などの個人情報を含む可能性があります）がGoogleに送信されます**。送信されて困る情報はローカル文書に含めないか、`--call-real-api` を付けずローカルのフェイククライアントで実行してください。
- LLMの応答は `data/runtime/llm_cache.sqlite` に、取得したWebページ本文は `.cache/` 配下のSQLiteに平文で保存されます。いずれも `.gitignore` 済みですが、個人情報を含みうるため、不要になったら手動で削除してください。
- スクレイピング時の `User-Agent` は環境変数 `INVESTMENT_ASSISTANT_USER_AGENT` で上書きできます。連絡先などを自分の運用に合わせて設定してください。
- 安全対策として、取得対象URLが private / loopback / link-local などの非公開アドレス（クラウドメタデータ 169.254.169.254 を含む）に解決される場合は取得を拒否します（SSRF対策）。リダイレクト先も各ホップで同様に検証します。


## トラブルシューティング


### `fatal: not a git repository` または Python 2.7 の `No module named pytest` が出る

ホームディレクトリなど、リポジトリ外でコマンドを実行しています。次をそのまま貼り付けて、`pyproject.toml` がある場所へ移動してから再実行してください。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
pwd
test -f pyproject.toml
git status --short

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```


### `invalid choice: fetch-job` / `rag-index-dir` / `rag-search-job` が出る

仮想環境内の `investment-assistant` コマンドが古い版を指しています。新しいCLIは `pyproject.toml` のconsole scriptから `investment_assistant.cli:main` を呼び出すため、リポジトリルートで editable install を更新してください。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e '.[dev]' --force-reinstall
hash -r

investment-assistant --help
investment-assistant fetch-job --help
investment-assistant rag-index-dir --help
investment-assistant rag-search-job --help
```

それでも同じエラーが出る場合は、インストール済みconsole scriptではなく、現在の作業ツリーを直接指定して実行してください。

```bash
PYTHONPATH=src python -m investment_assistant.cli fetch-job --help
PYTHONPATH=src python -m investment_assistant.cli rag-index-dir --help
PYTHONPATH=src python -m investment_assistant.cli rag-search-job --help
```

`PYTHONPATH=src python -m ...` でも同じ `invalid choice` が出る場合は、ローカルの作業ツリー自体が古い可能性が高いです。まず現在読み込まれているファイルと、ソース内に新コマンドが存在するか確認してください。

```bash
python - <<'PY'
import investment_assistant.cli as cli
print(cli.__file__)
PY
rg -n 'fetch-job|rag-index-dir|rag-search-job' src/investment_assistant/cli.py
git status --short --branch
git log --oneline -3
```

`rg` で新コマンドが出ない場合は、最新コミットがローカルに入っていません。未保存の作業がないことを確認してから、次で更新してください。

```bash
git fetch --all --prune
git pull --ff-only
python -m pip install -e '.[dev]' --force-reinstall
hash -r
PYTHONPATH=src python -m investment_assistant.cli fetch-job --help
PYTHONPATH=src python -m investment_assistant.cli rag-index-dir --help
PYTHONPATH=src python -m investment_assistant.cli rag-search-job --help
```

### `does not appear to be a Python project` と表示される

次のようなエラーが出る場合:

```text
ERROR: file:///Users/Ikimono0526 does not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml' found.
```

`pip install -e '.[dev]'` を `pyproject.toml` が存在しないディレクトリで実行しています。`cd` でリポジトリルートへ移動してから再実行してください。

```bash
if test -f pyproject.toml; then
  REPO_DIR="$PWD"
else
  REPO_MARKER="$(find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1)"
  REPO_DIR="$(dirname "$REPO_MARKER")"
fi
cd "$REPO_DIR"
test -f pyproject.toml
ls pyproject.toml
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

`ls pyproject.toml` が失敗する場合は、まだリポジトリをcloneしていないか、別のディレクトリにいます。


### どこにcloneしたか分からない場合

まず、ホームディレクトリ配下で `pyproject.toml` を探してください。

```bash
find "$HOME" -name pyproject.toml -path "*/Web-Scraping/pyproject.toml" -print 2>/dev/null | head -n 1
```

見つかったパスの親ディレクトリがリポジトリルートです。例えば `/Users/Ikimono0526/Web-Scraping/pyproject.toml` が見つかった場合は、次を実行します。

```bash
cd /Users/Ikimono0526/Web-Scraping
ls pyproject.toml
python3 scripts/doctor.py
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

`cd` せずにインストールしたい場合は、リポジトリへの絶対パスを指定します。

```bash
python -m pip install -e '/Users/Ikimono0526/Web-Scraping[dev]'
```
