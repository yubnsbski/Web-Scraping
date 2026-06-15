# Investment Assistant

Codex中心で開発・保守を自動化する、家庭向け自動化・投資支援システムの基盤です。

## 方針

- Pythonを主軸にし、LLM依存を最小化します。
- Gemini APIは無料枠を守るため、予算管理・キャッシュ・フォールバックを必須化します。
- Codexは実装、テスト、ドキュメント更新を進め、commit / PR / 本番反映前にユーザー承認を挟む運用を基本にします。
- 自動売買は実装せず、投資判断の最終責任はユーザーに残します。


## クイックスタート（オフライン実証）

ネットワークもAPIキーも不要で、データ取得→RAG→財務抽出→配当シミュレーションの全工程を
1コマンドで実演できます。挙動を一望したいとき、または環境が正しく動くかを確認したいときに使います。

```bash
investment-assistant demo          # または: python -m investment_assistant.demo
```

`IR crawl（フィクスチャHTML）→ RAG検索 → EDINET ingest（fake API）→ 配当シミュレータ＋手取り逆算`
を、本物のCLI経路にfakeを注入して順に実行します。実運用コマンドは下記Runbookと
`docs/dividend_data_runbook.md` を参照してください。

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
