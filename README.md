# Investment Assistant

Codex中心で開発・保守を自動化する、家庭向け自動化・投資支援システムの基盤です。

## 方針

- Pythonを主軸にし、LLM依存を最小化します。
- Gemini APIは無料枠を守るため、予算管理・キャッシュ・フォールバックを必須化します。
- Codexは実装、テスト、ドキュメント更新を進め、commit / PR / 本番反映前にユーザー承認を挟む運用を基本にします。
- 自動売買は実装せず、投資判断の最終責任はユーザーに残します。

## セットアップ

このプロジェクトは Python 3.11以上が必須です。`python --version` が Python 2.7.x を指す環境では、必ず `python3` または `python3.11` を使ってください。

```bash
# まず、pyproject.toml があるリポジトリルートへ移動します。
cd /path/to/Web-Scraping
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

## 安全なURL取得CLI（Phase 2）

`robots.txt` 確認、domain単位のレート制限、SQLiteキャッシュを通じてURLを安全に取得します。`--dry-run` では対象URL本体を取得せず、robots.txt確認だけを行います。

```bash
investment-assistant fetch-url --url https://example.com/funds --dry-run
investment-assistant fetch-url --url https://example.com/funds --preview-chars 300
```

詳細は `docs/data_ingestion.md` を参照してください。

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
investment-assistant rag-search --query "投資判断" --limit 5
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

investment-assistant scoring-validate --path local_data/funds.csv
investment-assistant scoring-rank --path local_data/funds.csv --limit 3
```

ランキング結果をJSONファイルに保存する場合は `--output` を指定します。既存ファイルは誤上書きを防ぐため、デフォルトでは上書きしません。上書きする場合だけ `--overwrite` を明示します。

```bash
investment-assistant scoring-rank --path local_data/funds.csv --limit 3 --output local_data/ranking.json
investment-assistant scoring-rank --path local_data/funds.csv --limit 3 --output local_data/ranking.json --overwrite
```

詳細は `docs/scoring.md` を参照してください。


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


## トラブルシューティング

### `does not appear to be a Python project` と表示される

次のようなエラーが出る場合:

```text
ERROR: file:///Users/Ikimono0526 does not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml' found.
```

`pip install -e '.[dev]'` を `pyproject.toml` が存在しないディレクトリで実行しています。`cd` でリポジトリルートへ移動してから再実行してください。

```bash
cd /path/to/Web-Scraping
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
find ~ -maxdepth 4 -name pyproject.toml -path '*Web-Scraping*' 2>/dev/null
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
