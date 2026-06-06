# 複数AIによる高度プロンプティング・オーケストレーション

複数のLLM「役割」を協調させ、単一プロンプトより緻密で根拠の確かな回答を作る多段パイプラインです。
すべて既存のガード付き `LlmService` を経由するため、**予算・キャッシュ・フォールバック**が常に適用され、
無料枠を超えません。投資助言ではなく、自動売買も行いません。

## 設計

```
RAG検索(BM25/ハイブリッド) → コンテキスト
      │
      ▼
  ドラフト担当（drafter, N案・観点を分散）   ← self-consistency
      │
      ▼
  レビュー担当（critic, ハルシネーション/引用漏れ/リスク欠落を指摘）
      │
      ▼
  統合担当（synthesizer, 指摘を反映し最終回答・引用・信頼度・免責）
```

- **役割別モデル割当（`RoleModels`）**: drafter / critic / synthesizer に別々のモデルIDを割当可能
  （例: drafter=flash で量産、critic/synthesizer=上位モデルで品質）。同一モデルでも、役割別プロンプトで
  「複数AI」的な相互チェックが働きます。
- **共有ガード**: 役割ごとに `LlmService` を生成しますが、予算DB・キャッシュDBは設定で共有するため、
  役割を増やしても無料枠管理は一元化されます。
- **self-consistency**: `--drafts N` で観点（コスト/リスク/分散…）を変えた複数ドラフトを生成し、
  統合担当が突き合わせて頑健化。
- **オフライン実行**: `--call-real-api` を付けなければ決定的なローカル擬似クライアントで全段を実行でき、
  テストとドライランがネット・APIキー無しで完結します。

## 使い方

```bash
# ローカル擬似（実API未使用）で多段オーケストレーション
investment-assistant orchestrate-answer --query "分散投資の要点" --db-path .cache/investment_assistant/rag.sqlite \
  --drafts 2 --hybrid

# 実Gemini経由（予算・キャッシュ・フォールバック適用、手動承認の上で）
investment-assistant orchestrate-answer --query "分散投資の要点" --drafts 3 --call-real-api
```

出力には各段（drafts/critique/synthesis）のテキストとガード由来メタデータ（source/warning/skipped/cache_key）、
最終 `answer`、`disclaimer` が含まれます。

## 役割別に異なるモデルを使う（API例）

```python
from investment_assistant.orchestration.factory import build_orchestrator
from investment_assistant.orchestration.orchestrator import OrchestrationConfig, RoleModels

orchestrator = build_orchestrator(
    role_models=RoleModels(drafter="gemini-2.0-flash", critic="gemini-2.0-flash", synthesizer="gemini-2.0-pro"),
    config=OrchestrationConfig(n_drafts=3, include_critique=True),
    call_real_api=True,
)
result = orchestrator.run(query="...", context="[1] ...")
print(result.answer)
```

## 限界・注意

- 多段化はAPI呼び出し回数を増やすため、予算ガードと併せて `--drafts` を抑制的に使ってください。
- レビュー段は品質を上げますが完全な正確性は保証しません。最終判断はユーザー本人が行います。
- 別プロバイダ（例: OpenAI/Anthropic）を役割に割り当てる場合は、`TextGenerationClient` を実装した
  クライアントを `build_orchestrator(client=...)` に渡す形で拡張できます（本リポジトリの既定はGemini）。
