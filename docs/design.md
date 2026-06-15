# Codex中心の家庭向け自動化・投資支援システム設計

## 目的

Codex中心で開発・保守を自動化し、ユーザーは commit、PR、本番反映の重要ポイントだけ承認する運用を目指す。

## 基本方針

1. Pythonを主軸にし、保守性とテスト容易性を優先する。
2. LLM依存を最小化し、通常処理はローカルPython処理を優先する。
3. Gemini APIは予算管理、キャッシュ、フォールバックを通じて無料枠を守る。
4. 投資判断を断定せず、自動売買は対象外にする。

## ロードマップ

### Phase 0: Codex運用基盤

- `AGENTS.md` にCodex作業ルールを明記する。
- `pyproject.toml`、CI、README、基本ドキュメントを整備する。
- ruff、pytest、mypyで品質確認できるようにする。

### Phase 1: Gemini API無料枠ガード

- Gemini呼び出しを `llm/service.py` に集約する。
- `budget_guard.py` で日次・月次使用量を管理する。
- `cache.py` で同一入力への再呼び出しを防ぐ。
- 上限到達時は設定に従い、キャッシュ利用、ローカル要約、スキップにフォールバックする。

### Phase 2: データ取得

- 公式APIまたはrobots.txtと利用規約を尊重した取得を行う。
- レート制限とキャッシュを実装する。
- `investment_assistant.ingestion` に安全なfetcher、robots確認、domain別レート制限、SQLite HTTPキャッシュを置く。
- `investment_assistant.crawler` に目的志向IRクロール（配当方針・財務開示ページへ誘導するリンクを
  優先するスコアリングBFS）を置く。リンクは page / document / asset に分類し、HTMLページのみを
  巡回、静的アセット（css/js/画像/フォント）は除外、PDF等の文書はクロールせずクロール報告の
  `documents` に surface する。
- `investment_assistant.edinet` にEDINET APIクライアントとXBRL CSV抽出を置き、配当系指標を
  `financials.csv` に正規化する。
- 取得処理の単体テストでは実ネットワークを呼ばず、fake transport / fakeクライアントを使う。

### Phase 3: RAG

- 文書チャンク、メタデータ、ローカル検索、引用付き回答を実装する。
- まずはGemini APIを呼ばないローカルRAG基盤として、SQLite保存とキーワード検索を実装する。

### Phase 4: 投資スコアリング

- 経費率、リターン、リスク指標、分散指標を用いたランキングを実装する。

### Phase 5: 予測

- 統計モデル、バックテスト、アンサンブル、RAG補助を段階的に導入する。
- 実装済み: `investment_assistant.forecasting` に、実財務データ取得、ベース予測器
  （naive/drift/linear_trend/holt/AR）、オプションML（RandomForest/GradientBoosting）、
  アンサンブル結合（mean/median/weighted）、対数リターン空間オプション、ウォークフォワード
  評価（MAE/RMSE/MAPE/方向的中率/skill）を配置。詳細と評価結果は `docs/forecasting.md`。
