// Evidence-rendering components shared by the RAG search tab, the legacy
// one-shot ChatPanel, and the new chat/ (Sprint B) UI.
//
// Extracted from App.tsx verbatim (CitationLinkedText, RagEvidenceCards,
// RagEvidenceQuality) so both call sites render identically. The small pure
// helpers these three components need (asJson/shortPath/formatScore/
// previewText/ragResultKey/evidenceSummary/ragEvidenceWarnings/QualityNotice)
// are intentionally duplicated here in private (non-exported) form rather
// than imported back from App.tsx: those helpers are also used broadly
// elsewhere in App.tsx for unrelated rendering, so importing them would
// create a circular App.tsx <-> Evidence.tsx dependency for no behavior
// benefit. Keep any future fix to citation/evidence-card rendering in sync
// between here and App.tsx's copies if App.tsx's copies ever diverge.
import type { ReactNode } from "react";

type Json = Record<string, any>;

function asJson(value: unknown): Json | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Json;
}

function shortPath(value: string): string {
  return value.split(/[\\/]/).filter(Boolean).pop() ?? value;
}

function formatScore(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return numeric.toLocaleString("ja-JP", { maximumFractionDigits: 4 });
}

function previewText(value: unknown, maxLength: number): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text || "-";
  return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`;
}

function ragResultKey(result: Json, index: number): string {
  return String(result.chunk_id ?? `${result.source ?? "source"}-${result.chunk_index ?? index}`);
}

function ragEvidenceWarnings(results: Json[], requestedLimit: number, selectedCount?: number): string[] {
  const warnings: string[] = [];
  const count = results.length;
  if (selectedCount !== undefined && selectedCount === 0) {
    warnings.push("AI確認に渡す根拠が0件です。チェックを入れるか、追加検索してください。");
  }
  if (count === 0) {
    warnings.push("一致する根拠が0件です。検索語を広げるか、データ更新で資料をRAGへ追加してください。");
    return warnings;
  }
  if (count < 2) warnings.push("根拠が1件だけです。単一ソース依存のため、反証・比較には不足しています。");
  if (requestedLimit > 0 && count < Math.min(requestedLimit, 5)) {
    warnings.push(`要求件数${requestedLimit}件に対して${count}件のみです。検索語・登録データの見直しが必要です。`);
  }
  const badIntegrity = results.filter((result) => {
    const citation = asJson(result.citation) ?? {};
    const status = String(citation.integrity_status ?? result.integrity_status ?? "").toLowerCase();
    return status && status !== "ok" && status !== "unknown" && status !== "-";
  }).length;
  if (badIntegrity > 0) warnings.push(`整合性が要確認の根拠が${badIntegrity}件あります。回答前に根拠カードを確認してください。`);
  return warnings;
}

function QualityNotice(props: {
  title: string;
  warnings: string[];
  okMessage: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  const ok = props.warnings.length === 0;
  return (
    <section className={ok ? "quality-notice safe" : "quality-notice"} aria-label={props.title}>
      <strong>{props.title}</strong>
      {ok ? (
        <p>{props.okMessage}</p>
      ) : (
        <>
          <ul>
            {props.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
          {props.onAction && props.actionLabel && (
            <button className="table-action quality-action" onClick={props.onAction}>
              {props.actionLabel}
            </button>
          )}
        </>
      )}
    </section>
  );
}

export function RagEvidenceQuality(props: {
  title: string;
  results: Json[];
  requestedLimit: number;
  selectedCount?: number;
  actionLabel?: string;
  onAction?: () => void;
}) {
  const warnings = ragEvidenceWarnings(props.results, props.requestedLimit, props.selectedCount);
  return (
    <QualityNotice
      title={props.title}
      warnings={warnings}
      okMessage={`${props.results.length}件の根拠を確認できます。`}
      actionLabel={props.actionLabel}
      onAction={props.onAction}
    />
  );
}

export function CitationLinkedText(props: { text: string; citationCount: number; targetPrefix: string }) {
  const { text, citationCount, targetPrefix } = props;
  const parts: ReactNode[] = [];
  const pattern = /\[(\d+)\]/g;
  let cursor = 0;
  let match = pattern.exec(text);
  while (match) {
    if (match.index > cursor) {
      parts.push(text.slice(cursor, match.index));
    }
    const citationNumber = Number(match[1]);
    const label = match[0];
    if (Number.isInteger(citationNumber) && citationNumber >= 1 && citationNumber <= citationCount) {
      parts.push(
        <a
          className="citation-link"
          href={`#${targetPrefix}-${citationNumber}`}
          key={`${targetPrefix}-${citationNumber}-${match.index}`}
          aria-label={`根拠 ${citationNumber} へ移動`}
        >
          {label}
        </a>,
      );
    } else {
      parts.push(label);
    }
    cursor = match.index + label.length;
    match = pattern.exec(text);
  }
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }
  return <div className="answer-text">{parts.length ? parts : text}</div>;
}

function evidenceSummary(result: Json, index: number) {
  const citation = asJson(result.citation) ?? {};
  const url = typeof citation.url === "string" && citation.url ? citation.url : null;
  return {
    number: index + 1,
    label: String(citation.label ?? shortPath(String(result.source ?? ""))),
    report_id: String(citation.report_id ?? "-"),
    integrity_status: String(citation.integrity_status ?? "-"),
    chunk_index: String(citation.chunk_index ?? result.chunk_index ?? "-"),
    score: formatScore(citation.score ?? result.score),
    source: shortPath(String(citation.source ?? result.source ?? "")),
    url,
  };
}

export function RagEvidenceCards({ title, results, idPrefix }: { title: string; results: Json[]; idPrefix?: string }) {
  return (
    <section className="detail-section evidence-cards" aria-label={title}>
      <h4>{title}</h4>
      <div className="evidence-card-list">
        {results.map((result, index) => {
          const citation = evidenceSummary(result, index);
          return (
            <article
              className="evidence-card"
              id={idPrefix ? `${idPrefix}-${citation.number}` : undefined}
              key={ragResultKey(result, index)}
            >
              <header>
                <b>
                  [{citation.number}]{" "}
                  {citation.url ? (
                    <a href={citation.url} target="_blank" rel="noopener noreferrer">
                      {citation.label}
                    </a>
                  ) : (
                    citation.label
                  )}
                </b>
                <span>{citation.score}</span>
              </header>
              <p>{previewText(result.text, 240)}</p>
              <div className="rag-meta">
                <span>文書: {citation.source}</span>
                <span>チャンク: {citation.chunk_index}</span>
                {citation.report_id !== "-" && <span>レポートID: {citation.report_id}</span>}
                {citation.integrity_status !== "-" && <span>整合性: {citation.integrity_status}</span>}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
