# AGENTS.md

## リポジトリ作業ガイド（AI向け）

エージェントが最短で立ち上がるための要点。

- **品質ゲート**（変更後は必ず全て緑にする）:
  ```bash
  python -m pytest -q && ruff check . && mypy src
  ```
- **全体像を1コマンドで掴む**: `investment-assistant demo` がデータ取得→RAG→EDINET→配当
  シミュレーションをオフラインで通しで実行する（実装は `src/investment_assistant/demo.py`）。
- **アーキテクチャ**（`src/investment_assistant/` 配下）:
  - `ingestion/` 安全なfetcher・robots・レート制限・HTTPキャッシュ（SSRF対策込み）
  - `crawler/` 目的志向IRクロール（リンク種別判定: page/document/asset、PDFは別枠で surface）
  - `edinet/` EDINET APIクライアントとXBRL CSV抽出 → `financials.csv`
  - `rag/` チャンク化・SQLite保存・キーワード/ハイブリッド検索
  - `portfolio/` 配当シミュレータ（手取り計算・目標逆算）
  - `cli.py` 全サブコマンドの入口、`webapi/` HTTP層
- **オフラインファースト規約**: 単体テストとデモは実ネットワーク・実APIを呼ばない。
  ネットワーク境界（fetcher / EDINETクライアント / LLM）は注入可能にし、fakeを渡す。
- **テスト**: 変更には `tests/unit/` にテストを追加・更新する。

## 基本方針

- Pythonを優先し、保守性・テスト容易性・疎結合を重視する。
- Gemini APIの無料枠を超えない設計を必須とする。
- Gemini API呼び出しには必ず予算管理、キャッシュ、フォールバックを適用する。
- 投資判断を断定せず、自動売買機能は実装しない。
- 最終的な投資判断はユーザーが行う前提にする。

## Codex作業ルール

- Codexは実装、テスト、リファクタリング、ドキュメント更新、CI設定更新を自動で進めてよい。
- `git commit`、PR作成、本番反映の前はユーザー承認を求める運用を基本とする。
- この環境で上位指示がコミットやPR作成を要求している場合は、その上位指示に従う。
- コード変更後は関連テストを追加または更新する。
- `.env`、APIキー、個人情報、データ成果物、モデル成果物、RAGインデックスをコミットしない。

## Gemini APIルール

- Gemini APIを直接呼ばず、必ず `src/investment_assistant/llm/service.py` を経由する。
- API呼び出し前に `budget_guard.py` で日次・月次予算を確認する。
- 同一入力に対しては `cache.py` の結果を優先する。
- 無料枠上限に近づいた場合は警告し、上限到達時は設定されたフォールバックを使用する。
- 単体テストではGemini APIを呼ばず、mockまたはfake clientを使う。

## Codexプロバイダ (codex_cli) ルール

- `codex_cli` も必ず `src/investment_assistant/llm/service.py` 経由（予算・キャッシュ・
  フォールバック適用）で呼び出す。`llm/codex_client.py` を直接、あるいは
  `LlmService`/`ChainLlmService` を経由せずに呼び出さない。
- ChatGPT OAuthトークンの抽出・直接API利用は禁止（規約違反）。`codex exec` CLI経由の
  呼び出しのみを行う。
- デフォルト無効（`config/llm.yaml` の `providers.codex_cli.enabled: false`）。有効化は
  オーナーの明示判断で行う。グレーゾーンの利用であることを認識した上で使うこと。
- ローカル専用の想定。`webapi` をLAN/外部に公開する構成にする場合は `codex_cli` を
  無効化する。
- 自主上限は1日10回（`daily_request_limit`、失敗した試行も含めてカウント）。
  レート制限エラー後はクールダウン（既定30分）を置き、その間は起動せずスキップする。
  一括呼び出しや、上限に達するかどうかを探るための呼び出しは行わない。
- 単体テストでは `subprocess` を起動しない。`CodexCliClient` を使うテストは必ず fake
  クライアント（または `subprocess.Popen` のパッチ）を使う。実サブプロセスを伴うテストを
  追加する場合は `@pytest.mark.integration` を付け、デフォルトの `pytest -q` から除外する。

## 投資・コンプライアンス

- 個別商品の売買を断定的に推奨しない。
- レポートには根拠、不確実性、免責文を含める。
- 実注文や自動売買を追加する場合は、別途法務レビューを必須にする。
