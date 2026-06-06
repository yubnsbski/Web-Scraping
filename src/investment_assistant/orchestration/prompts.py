"""Prompt builders for the multi-model orchestration pipeline."""

from __future__ import annotations

from collections.abc import Sequence

DISCLAIMER = (
    "これは投資助言ではなく、ローカル文書に基づく調査メモの下書きです。"
    "自動売買は行わず、最終的な投資判断はユーザー本人が行ってください。"
)

_GROUNDING_RULES = (
    "以下のローカル文書コンテキストだけを根拠に回答してください。",
    "コンテキストに無い情報は推測せず、不足する場合はその旨を明記してください。",
    "各主張の文末に [n] のコンテキスト番号で引用を付けてください。",
    "個別商品の売買を断定的に推奨せず、自動売買・実注文・確定的判断は行いません。",
)


def draft_prompt(*, query: str, context: str, perspective: str | None = None) -> str:
    """Prompt for a drafter role; ``perspective`` diversifies self-consistency drafts."""

    lines = [
        "あなたは投資調査メモ作成を補助するドラフト担当アシスタントです。",
        *_GROUNDING_RULES,
    ]
    if perspective:
        lines.append(f"今回は次の観点を特に重視してください: {perspective}")
    lines += [
        "",
        "質問",
        query,
        "",
        "ローカル文書コンテキスト",
        context,
        "",
        "出力要件",
        "- 要点（各文に [n] 引用）",
        "- 根拠と引用",
        "- 不確実性",
    ]
    return "\n".join(lines)


def critique_prompt(*, query: str, context: str, drafts: Sequence[str]) -> str:
    """Prompt for the critic role to review drafts against the context."""

    lines = [
        "あなたは厳格なレビュアーです。以下のドラフト回答を、コンテキストに照らして検証します。",
        "次の観点で問題点だけを箇条書きで簡潔に指摘してください（修正案は不要）:",
        "- コンテキストで裏付けられない主張（ハルシネーション）",
        "- 事実誤り・論理の飛躍",
        "- 引用 [n] の欠落や誤り",
        "- 不確実性やリスクの記載漏れ",
        "問題が無ければ「重大な問題なし」と書いてください。",
        "",
        "質問",
        query,
        "",
        "ローカル文書コンテキスト",
        context,
    ]
    for index, draft in enumerate(drafts, 1):
        lines += ["", f"ドラフト{index}", draft]
    return "\n".join(lines)


def synthesis_prompt(*, query: str, context: str, drafts: Sequence[str], critique: str) -> str:
    """Prompt for the synthesizer role to produce the final answer."""

    lines = [
        "あなたは統合担当アシスタントです。",
        "以下のドラフト群とレビュー指摘を踏まえ、最終回答を作成してください。",
        *_GROUNDING_RULES,
        "レビュー指摘は必ず反映し、裏付けの無い主張は削除してください。",
        "",
        "質問",
        query,
        "",
        "ローカル文書コンテキスト",
        context,
    ]
    for index, draft in enumerate(drafts, 1):
        lines += ["", f"ドラフト{index}", draft]
    lines += [
        "",
        "レビュー指摘",
        critique,
        "",
        "出力要件",
        "- 要点（各文に [n] 引用）",
        "- 根拠と引用",
        "- 不確実性",
        "- 信頼度: 高 / 中 / 低",
        f"- 免責: {DISCLAIMER}",
    ]
    return "\n".join(lines)
