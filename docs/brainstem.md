# 完成設計図 — 脳幹（Brainstem）と全体ロードマップ

**この文書がプロジェクトのマスターブループリント。全スプリントはこの地図上の1マスを埋める作業であり、地図にない機能は作らない（ぐちゃらない原則）。**

- 策定: 2026-07-07（architect(opus) × Codex 独立設計 → オーケストレータ統合）
- オーナー確定方針:
  - 判断基準は「**お金を増やすことに直結するか**」
  - 最終目標は**自動売買による利確**（段階制、下記Phase参照）
  - コストは**できるだけ無料、ダメなら有料もやむなし**
  - 規約グレーは基本なし（例外: Yahoo!ファイナンスのデータ取得のみ）
  - チャットは**ローカル優先、足りなければAPIで補う**
  - データは**軽量・構造化・検索自動化**で無駄なく

---

## 1. 全体地図

```
[削除スプリント D1-D4]                     ← 身軽にする（D1完了）
        ↓
[B0 脳幹骨格]  brainstem/ パッケージ抽出   ← すべての差し込み口
        ↓
[N0 データ仕様] 軽量・構造化・自動インデックス
[N1 NN埋め込み] 検索の質を先に磨く（外堀から埋める）
        ↓
[O1 Ollama]    ローカル脳を立てる（3-4B, 投資特化Modelfile）
[O2 評価ループ] 測って振り分ける（シナプス形成）
        ↓
[O3 モード拡張] rag/web/auto 情報源モード＋文脈書き換え
        ↓
[D5 ルート整理] service.py 解禁後のバックエンド削除（並行セッション完了待ち）
[H1 ホスティング] PCオフでもフルアクセス（方式未定）
        ↓
[Phase2 シグナル] 予測→売買シグナル＋バックテスト＋ペーパートレード
[Phase3 半自動]  証券会社公式API＋1タップ承認（AGENTS.md改訂＋法務レビュー必須）
[Phase4 全自動]  リスクガード付き自動売買（Phase3の実績が昇格条件）
```

## 2. 脳幹 = 全ターンが通る固定パイプライン

新パッケージ `src/investment_assistant/brainstem/`。既存ファイルの編集は最小、
`webapi/service.py` は**最終フック（2行）まで一切触らない**（並行セッション対策）。

```
リクエスト
  → [1 ingest]     BrainstemRequest に正規化
  → [2 context]    ContextResolver: 履歴から文脈解決（モード別）
  → [3 retrieve]   ModeHandler: RAG検索 or ウェブ検索 → Evidence（共通形状）
  → [4 route]      QueryRouter: ローカルかGeminiか（評価ポリシー参照）
  → [5 generate]   Generator: Ollama→(エスカレート)Gemini→(退避)テンプレート
  → [6 comply]     ComplianceGuard: 免責・引用必須・断定助言禁止をサーバ側強制
  → [7 assemble]   chat.turn.v1 形状で返却（既存スキーマ不変）
```

### ファイル構成
| ファイル | 役割 |
|---|---|
| `brainstem/contracts.py` | frozen dataclass 契約: `BrainstemRequest`, `ResolvedContext`, `EvidenceItem`, `RouteDecision`, `GenerationAttempt` |
| `brainstem/pipeline.py` | `BrainstemService.run_turn()` — 上記7段の漏斗 |
| `brainstem/context.py` | `ContextResolver` — rag/history.py のヒューリスティック再利用＋ローカルLLM書き換え（後述の不変条件付き） |
| `brainstem/retrieval.py` | RAG検索ラッパ（既存 hybrid_search） |
| `brainstem/web_search.py` | `WebSearchClient` protocol ＋ `BraveSearchClient` |
| `brainstem/router.py` | `QueryRouter` ＋ `RoutingPolicy`（評価ハーネスの成果物を読む） |
| `brainstem/generation.py` | 生成実行・タイムアウト・エスカレーション |
| `brainstem/compliance.py` | `ComplianceGuard` |
| `brainstem/eval.py` | 評価ハーネス（オフライン専用） |
| `brainstem/webapi_adapter.py` | 既存JSON⇔契約の変換。chat.py はこれを呼ぶ薄いアダプタになる |

### モードは2軸
- **answer_mode**: `answer`（通常）| `detailed`（多段オーケストレーション）
- **source_mode**: `rag`（蓄積データ）| `web`（ウェブ検索）| `auto`（質問の性質で決定論的に自動選択・判断理由をログ）
- シミュレーションは既存 `/api/chat/simulate` を後日 `sim` として統合（v1スコープ外）

### 絶対不変条件（キャッシュ・コンプライアンス）
1. **会話履歴はGeminiプロンプトに絶対に入れない**。Gemini用質問文＝「最新の質問＋引き継ぎ銘柄トークンのみ」の決定論的関数（無料枠キャッシュ保護）。履歴の影響は検索クエリまで
2. **ローカルLLMのみ**文脈書き換え（クエリリライト）可（無料なので）。`RouteDecision.allow_context_rewrite` はローカル経路のみ true
3. 根拠ゼロなら生成スキップ＋CTA（現行踏襲）。引用と免責は `ComplianceGuard` がサーバ側で強制
4. 断定的売買推奨なし・自動売買コードは脳幹に置かない（Phase3以降で別モジュール＋AGENTS.md改訂後）

## 3. 振り分け（ローカル vs Gemini）

- **v0（O1と同時）決定論ヒューリスティック**: 既定はローカル。`detailed`/高品質要求→Gemini(orchestrate)。根拠ゼロ→生成なし
- **v1（O2で）評価駆動**: オフライン評価ハーネスが「モード×複雑さ×根拠数」ごとのローカル品質スコアを測り、`RoutingPolicy` 成果物を出力。ルータはそれを読むだけ。**本番リクエスト上でのA/B比較は絶対にしない**（無料枠保護）
- **タイムアウトUX**: ローカル既定45秒。超過→Geminiエスカレート（予算内なら）→ダメならテンプレート＋warning。UI文言「ローカルLLMで生成中です。CPUのみのため30〜60秒かかることがあります。」SSEは作らない（スキーマはstream_ready維持）

## 4. データ仕様（N0 — オーナー要件: 高品質・無駄なし）

- **軽量**: 生ダンプを貯めない。要点チャンク＋数値テーブルのみ（8GB RAM制約）。保存しないものを仕様で明記
- **構造化**: チャンクに ticker / 日付 / 出典 / 指標種別 のメタデータスキーマ。「トヨタの直近配当」は構造で直接引けること
- **検索自動化**: 取り込み→チャンク化→埋め込み→インデックス更新まで人手ゼロのパイプライン（既存 market-daily-refresh に接続）

## 5. 技術選定（コスト方針: 無料優先）

| 部品 | 選定 | 根拠 |
|---|---|---|
| ローカルLLM | Ollama ＋ 3-4B Q4（Qwen3 4B / Gemma 3 4B を評価で選ぶ） | HW上限: 8GB RAM・dGPUなし・i7-1065G7 |
| 埋め込み | multilingual-e5-small / ruri-small（sentence-transformers, CPU, 遅延import） | 既存 `Embedder` protocol に刺す。ハッシュ既定は維持、再インデックスで移行 |
| ウェブ検索 | **Brave Search API**（公式・無料枠） | Google CSE は新規受付終了（〜2027移行）のため不採用 |
| API LLM | Gemini 無料枠（既存 budget_guard/cache/fallback） | 継続 |
| 除外 | codex_cli プロバイダ（D2で削除） | 規約グレー方針。開発時のCodexレビューは対象外（継続） |

## 6. 作らないもの（アンチスコープ）

サーバ側会話ストア / SSEストリーミング / エージェント的ツールループ・多段プランニング /
Ollama本体の改造・ファインチューニング / ベクタDB新設（SQLite＋Embedder seamのみ） /
LLMによるモード分類器（v1は決定論） / 本番経路でのA/B比較 / 検索結果ページのスクレイピング
（公式APIスニペットのみ。ページ取得は将来SafeFetcher経由で別件） / 断定助言・実注文（Phase3前）

## 7. スプリント順序と理由

1. **D2-D4**（削除継続）: 身軽が先
2. **B0** 脳幹骨格: 純リファクタ（chat.turn.v1 のバイト同一性を既存テストで固定）。全部の差し込み口
3. **N0+N1** データ仕様＋NN埋め込み: 検索は全経路に複利で効く。既知バグ（多語日本語クエリ0.0）修正
4. **O1** Ollama: ローカル脳。`TextGenerationClient` protocol 実装＋`LlmService(enforce_budget=False)`
5. **O2** 評価ハーネス＋ルータv1: ローカルができて初めて測れる。シナプス形成の中核
6. **O3** モード拡張（web/auto＋ローカル書き換え）: 面の拡張は脳が強くなってから
7. **D5 / H1**: 並行セッション完了後のルート整理、ホスティング
8. **Phase2→4**: ペーパートレードの成績が各段昇格の関門

## 8. 検証原則

- 全ステージ注入可能（fake network / fake LLM）でオフラインpytest維持
- 実プロバイダ比較は `@pytest.mark.integration` でopt-in
- 各スプリント終了時: `pytest -q && ruff check . && mypy src` ＋ フロント変更時 `npm run build` ＋ 実サーバE2E（チャット1問）
