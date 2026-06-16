import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import { api } from "./api";
import { DashboardTab } from "./DashboardTab";
import { MarketDataPanel } from "./MarketDataPanel";

type Json = Record<string, any>;

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  meta?: string;
  sources?: Json[];
  question?: string;
};

type SourcePreset = {
  label: string;
  name: string;
  url: string;
  output_path: string;
  query_hint: string;
};

type GuideCard = {
  title: string;
  body: string;
};

type TargetSourceOption = {
  label: string;
  source: string;
  queryContext: string;
};

type CandidateScreenPreset = {
  id: string;
  name: string;
  includeStocks: boolean;
  includeFunds: boolean;
  excludeCut: boolean;
  minEquity: string;
  maxExpense: string;
  nisaOnly: boolean;
  minDiversification: string;
  createdAt: string;
  updatedAt: string;
};

type DetailSeed = {
  code: string;
  assetType: string;
  nonce: number;
};

type CsvDraft = Record<string, string>;

const DEFAULT_RAG_DB_PATH = ".cache/investment_assistant/rag.sqlite";
const CANDIDATE_SCREEN_PRESETS_STORAGE_KEY =
  "investment_assistant.candidate_screen_presets.v1";

const TARGET_SOURCE_OPTIONS: TargetSourceOption[] = [
  {
    label: "指定なし（DB全体）",
    source: "",
    queryContext: "",
  },
  {
    label: "9432 NTT",
    source: "local_docs/nikkei225/9432/ir.txt",
    queryContext:
      "対象銘柄: 9432 NTT\n対象資料: local_docs/nikkei225/9432/ir.txt\nこの対象資料だけを根拠にしてください。",
  },
  {
    label: "2914 JT",
    source: "local_docs/nikkei225/2914/ir.txt",
    queryContext:
      "対象銘柄: 2914 JT\n対象資料: local_docs/nikkei225/2914/ir.txt\nこの対象資料だけを根拠にしてください。",
  },
  {
    label: "8306 MUFG",
    source: "local_docs/nikkei225/8306/ir.txt",
    queryContext:
      "対象銘柄: 8306 MUFG\n対象資料: local_docs/nikkei225/8306/ir.txt\nこの対象資料だけを根拠にしてください。",
  },
];

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "holdings", label: "Holdings" },
  { id: "candidates", label: "Candidates" },
  { id: "detail", label: "Detail" },
  { id: "simulate", label: "Simulate" },
  { id: "report", label: "Report" },
  { id: "evidence", label: "Evidence" },
] as const;

const HERO_CARDS = [
  { label: "Holdings", value: "Analyze", desc: "保有・NISA・損益を集計" },
  { label: "Candidates", value: "Screen", desc: "条件一致だけを提示" },
  { label: "Report", value: "Evidence", desc: "計算式と根拠を保存" },
  { label: "Detail", value: "Review", desc: "銘柄・投信を根拠付き確認" },
] as const;

const SUGGESTED_QUESTIONS = [
  "選択中の対象銘柄について、配当方針と減配リスクを取得済みIR資料だけで整理して",
  "選択中の対象銘柄について、株主還元方針と未確認の危険ポイントを分けて",
  "選択中の対象銘柄について、買う前に追加取得すべき資料を列挙して",
  "取得済みIR資料だけを根拠に、判断を保留すべき危険ポイントを出して",
  "対象sourceに根拠がない項目を、不明として整理して",
  "配当・自己株式取得・営業CFの確認観点をチェックリスト化して",
] as const;

const SOURCE_PRESETS: SourcePreset[] = [
  {
    label: "NTT IR",
    name: "9432_NTT_ir",
    url: "https://group.ntt/jp/ir/",
    output_path: "local_docs/nikkei225/9432/ir.txt",
    query_hint: "9432 NTT 配当 方針 DOE 配当性向 IR",
  },
  {
    label: "トヨタ IR",
    name: "7203_toyota_ir",
    url: "https://global.toyota/jp/ir/",
    output_path: "local_docs/nikkei225/7203/ir.txt",
    query_hint: "7203 トヨタ 配当 方針 株主還元 IR",
  },
  {
    label: "金融庁 NISA",
    name: "fsa_nisa",
    url: "https://www.fsa.go.jp/policy/nisa2/",
    output_path: "local_docs/public/fsa_nisa.txt",
    query_hint: "NISA 成長投資枠 つみたて投資枠 制度 金融庁",
  },
];

const AI_GUIDES: GuideCard[] = [
  {
    title: "1. まず根拠を検索",
    body: "RAG DBから関連チャンクを取得します。ハイブリッド検索を使うと語句一致と意味検索を混ぜます。",
  },
  {
    title: "2. 複数ドラフト",
    body: "コスト、リスク、分散など複数観点で下書きを作ります。ドラフト数を増やすほど確認観点が増えます。",
  },
  {
    title: "3. レビューと統合",
    body: "レビュアーが根拠不足・飛躍・引用漏れを指摘し、統合担当が最終回答へ反映します。",
  },
  {
    title: "4. 実APIは任意",
    body: "標準はローカル擬似AIです。実Geminiを使うにはバックエンドで許可設定が必要です。",
  },
];

const SCRAPE_GUIDES: GuideCard[] = [
  {
    title: "自動取得",
    body: "robots.txt確認、URL安全性確認、レート制限、HTMLテキスト化、保存、RAG登録をまとめて実行します。",
  },
  {
    title: "dry-run",
    body: "本文を取得せず、robots.txtで取得可能かだけ確認します。新しいURLは最初にdry-runしてください。",
  },
  {
    title: "手動取込",
    body: "JavaScript描画やBot対策で取得できない場合、ブラウザで本文をコピーして貼り付けます。",
  },
  {
    title: "法令・規約対応",
    body: "公開HTTP(S)のみ対象です。robotsで禁止されたURL、内部IP、巨大レスポンスは拒否します。",
  },
];

const SAMPLE_CSV =
  "name,expense_ratio,annual_return,volatility,diversification_score\n" +
  "低コスト全世界株式,0.12,0.065,0.18,0.95\n" +
  "高コストテーマ型,1.20,0.080,0.35,0.45\n" +
  "債券バランス型,0.35,0.030,0.08,0.80\n";

const SAMPLE_HOLDINGS_CSV =
  "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source,current_price,annual_income,distribution_per_unit\n" +
  "stock,7203,安定配当ホールディングス,100,1800,tokutei,nisa_growth,examples/investment_holdings_sample.csv,2200,,\n" +
  "stock,9999,景気連動マテリアル,50,1200,tokutei,taxable,examples/investment_holdings_sample.csv,1000,,\n" +
  "fund,FND001,低コスト全世界株式,120,10000,nisa,nisa_tsumitate,examples/investment_holdings_sample.csv,12500,,25\n" +
  "fund,FND002,債券バランス型,80,9000,tokutei,taxable,examples/investment_holdings_sample.csv,9300,,10\n";

const AUDITABLE_SAMPLE_HOLDINGS_CSV =
  "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source,current_price,annual_income,distribution_per_unit,data_provider,price_as_of\n" +
  "stock,7203,Stable Dividend Holdings,100,1800,tokutei,nisa_growth,examples/investment_holdings_sample.csv,2200,,,user_csv,2026-06-10\n" +
  "stock,9999,Scenario Trial,50,1200,tokutei,taxable,examples/investment_holdings_sample.csv,1000,,,user_csv,2026-06-10\n" +
  "fund,FND001,Low Cost Global Equity,120,10000,nisa,nisa_tsumitate,examples/investment_holdings_sample.csv,12500,,25,user_csv,2026-06-10\n" +
  "fund,FND002,Balanced Bond Fund,80,9000,tokutei,taxable,examples/investment_holdings_sample.csv,9300,,10,user_csv,2026-06-10\n";

const SAMPLE_FUNDS_CSV =
  "fund_code,name,asset_class,expense_ratio,distribution_policy,nisa_eligible,provider_id,diversification_score\n" +
  "FND001,低コスト全世界株式,global_equity,0.12,reinvest,true,user_csv,0.95\n" +
  "FND002,債券バランス型,balanced,0.35,distribution,true,user_csv,0.80\n" +
  "FND999,高コストテーマ型,theme,1.20,distribution,false,user_csv,0.40\n";

const SAMPLE_FINANCIALS_PATH = "examples/financials_sample.csv";

const HOLDING_CSV_COLUMNS = [
  "asset_type",
  "ticker_or_fund_code",
  "name",
  "quantity",
  "avg_cost",
  "account_type",
  "tax_wrapper",
  "source",
  "current_price",
  "annual_income",
  "distribution_per_unit",
  "data_provider",
  "price_as_of",
] as const;

const FUND_CSV_COLUMNS = [
  "fund_code",
  "name",
  "asset_class",
  "expense_ratio",
  "distribution_policy",
  "nisa_eligible",
  "provider_id",
  "diversification_score",
] as const;

const DEFAULT_HOLDING_DRAFT: CsvDraft = {
  asset_type: "stock",
  ticker_or_fund_code: "7203",
  name: "Manual Holding",
  quantity: "100",
  avg_cost: "1800",
  account_type: "tokutei",
  tax_wrapper: "taxable",
  source: "manual",
  current_price: "2200",
  annual_income: "",
  distribution_per_unit: "",
  data_provider: "manual",
  price_as_of: "2026-06-11",
};

const DEFAULT_FUND_DRAFT: CsvDraft = {
  fund_code: "FND001",
  name: "Manual Fund",
  asset_class: "global_equity",
  expense_ratio: "0.12",
  distribution_policy: "reinvest",
  nisa_eligible: "true",
  provider_id: "manual",
  diversification_score: "0.90",
};

const SAMPLE_SOURCES = JSON.stringify([presetToSource(SOURCE_PRESETS[0])], null, 2);
const DISCLOSURE_AUTO_SOURCES = [
  {
    name: "edinet_portal",
    url: "https://disclosure2.edinet-fsa.go.jp/",
    output_path: "local_docs/disclosure/edinet_portal.txt",
    query_hint: "EDINET 有価証券報告書 半期報告書 四半期報告書 財務諸表",
    extract_text: true,
    include_metadata: true,
    preview_chars: 800,
  },
  {
    name: "tdnet_portal",
    url: "https://www.release.tdnet.info/inbs/I_main_00.html",
    output_path: "local_docs/disclosure/tdnet_portal.txt",
    query_hint: "TDnet 決算短信 適時開示 決算説明資料 業績予想",
    extract_text: true,
    include_metadata: true,
    preview_chars: 800,
  },
  {
    name: "jpx_listed_company_info",
    url: "https://www.jpx.co.jp/listing/co-search/index.html",
    output_path: "local_docs/disclosure/jpx_listed_company_info.txt",
    query_hint: "東証 上場会社情報 決算短信 有価証券報告書 開示資料",
    extract_text: true,
    include_metadata: true,
    preview_chars: 800,
  },
  {
    name: "ntt_ir_library",
    url: "https://group.ntt/jp/ir/library/",
    output_path: "local_docs/disclosure/9432_ntt_ir_library.txt",
    query_hint: "NTT 有価証券報告書 決算短信 決算説明資料 財務諸表",
    extract_text: true,
    include_metadata: true,
    preview_chars: 800,
  },
  {
    name: "toyota_ir_library",
    url: "https://global.toyota/jp/ir/library/",
    output_path: "local_docs/disclosure/7203_toyota_ir_library.txt",
    query_hint: "トヨタ 有価証券報告書 決算短信 決算説明資料 財務諸表",
    extract_text: true,
    include_metadata: true,
    preview_chars: 800,
  },
];


type TabId = (typeof TABS)[number]["id"];

export function App() {
  const [tab, setTab] = useState<TabId>("dashboard");
  const [detailSeed, setDetailSeed] = useState<DetailSeed>({
    code: "7203",
    assetType: "stock",
    nonce: 0,
  });
  const openDetail = (code: string, assetType: string) => {
    setDetailSeed({ code, assetType, nonce: Date.now() });
    setTab("detail");
  };
  return (
    <div className="app">
      <header className="terminal-hero">
        <div className="hero-copy">
          <p className="eyebrow">Investment Research Terminal</p>
          <h1>Investment Assistant</h1>
          <p className="hero-lead">
            日本株と投信の保有分析、候補抽出、NISA枠、根拠付きレポートを1画面で進めます。
          </p>
        </div>
        <div className="hero-badges">
          <span className="badge safe">自動売買なし</span>
          <span className="badge">売買推奨なし</span>
          <span className="badge">ローカルRAG</span>
        </div>
      </header>

      <section className="metric-grid" aria-label="機能概要">
        {HERO_CARDS.map((card) => (
          <article className="metric-card" key={card.label}>
            <span>{card.label}</span>
            <b>{card.value}</b>
            <small>{card.desc}</small>
          </article>
        ))}
      </section>

      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={t.id === tab ? "tab active" : "tab"}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <main className="panel">
        {tab === "dashboard" && <DashboardTab />}
        {tab === "holdings" && <HoldingsTab />}
        {tab === "candidates" && <CandidateScreenTab onOpenDetail={openDetail} />}
        {tab === "detail" && <InvestmentDetailTab seed={detailSeed} />}
        {tab === "simulate" && <SimulateTab />}
        {tab === "report" && <InvestmentReportTab />}
        {tab === "evidence" && <SearchTab />}
      </main>
      <footer className="footer">
        本ツールは投資助言ではありません。最終的な投資判断はユーザー本人が行います。
      </footer>
    </div>
  );
}

function useAsync<T>() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<T | null>(null);
  async function run(fn: () => Promise<T>): Promise<T | null> {
    setLoading(true);
    setError(null);
    try {
      const result = await fn();
      setData(result);
      return result;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setLoading(false);
    }
  }
  return { loading, error, data, run };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Start a background job and poll until it finishes, so long operations (e.g. a
// multi-minute EDINET ingest) don't time out the port-forward proxy (HTTP 504).
// Falls back to a synchronous result if the backend didn't return a job id.
async function runJob(
  startPath: string,
  body: unknown,
  { intervalMs = 3000, maxAttempts = 600 } = {},
): Promise<Json> {
  const started = await api<Json>(startPath, body);
  const jobId = String(started.job_id ?? "");
  if (!jobId) return started;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    await sleep(intervalMs);
    const job = await api<Json>("/api/jobs/status", { job_id: jobId });
    if (job.status === "done") return (job.result as Json) ?? {};
    if (job.status === "error") throw new Error(String(job.error ?? "job failed"));
  }
  throw new Error("ジョブがタイムアウトしました（バックグラウンドでは継続中の可能性があります）");
}

function Field(props: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      {props.children}
    </label>
  );
}

function csvEscape(value: unknown): string {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function appendCsvDraft(
  csvText: string,
  columns: readonly string[],
  draft: CsvDraft,
): string {
  const header = columns.join(",");
  const row = columns.map((column) => csvEscape(draft[column] ?? "")).join(",");
  const trimmed = csvText.trim();
  if (!trimmed) return `${header}\n${row}\n`;
  const lines = trimmed.split(/\r?\n/);
  const firstLine = lines[0] ?? "";
  const hasRelatedHeader = columns.some((column) => firstLine.split(",").includes(column));
  const body = hasRelatedHeader ? lines.slice(1).join("\n") : trimmed;
  return `${header}\n${body ? `${body}\n` : ""}${row}\n`;
}

function downloadTextFile(filename: string, text: string, type = "text/csv"): void {
  const blob = new Blob([text], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function jsonText(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function Status(props: { loading: boolean; error: string | null }) {
  if (props.loading) return <p className="status">実行中…</p>;
  if (props.error) return <p className="status error">エラー: {props.error}</p>;
  return null;
}

function makeCandidatePresetId(): string {
  const cryptoValue = globalThis.crypto;
  if (typeof cryptoValue?.randomUUID === "function") return cryptoValue.randomUUID();
  return `candidate-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function asPresetString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function sanitizeCandidatePreset(value: unknown): CandidateScreenPreset | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Json;
  const id = asPresetString(record.id).trim();
  const name = asPresetString(record.name).trim();
  if (!id || !name) return null;
  const now = new Date().toISOString();
  return {
    id,
    name,
    includeStocks: Boolean(record.includeStocks),
    includeFunds: Boolean(record.includeFunds),
    excludeCut: Boolean(record.excludeCut),
    minEquity: asPresetString(record.minEquity),
    maxExpense: asPresetString(record.maxExpense),
    nisaOnly: Boolean(record.nisaOnly),
    minDiversification: asPresetString(record.minDiversification),
    createdAt: asPresetString(record.createdAt) || now,
    updatedAt: asPresetString(record.updatedAt) || now,
  };
}

function readCandidateScreenPresets(): CandidateScreenPreset[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CANDIDATE_SCREEN_PRESETS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map(sanitizeCandidatePreset)
      .filter((item): item is CandidateScreenPreset => item !== null)
      .slice(0, 12);
  } catch {
    return [];
  }
}

function writeCandidateScreenPresets(presets: CandidateScreenPreset[]): boolean {
  if (typeof window === "undefined") return false;
  try {
    window.localStorage.setItem(
      CANDIDATE_SCREEN_PRESETS_STORAGE_KEY,
      JSON.stringify(presets.slice(0, 12)),
    );
    return true;
  } catch {
    return false;
  }
}

function evidenceForKeys(evidence: Json[], keys: unknown): Json[] {
  const keySet = Array.isArray(keys)
    ? new Set(keys.map((key) => String(key)))
    : new Set<string>();
  return evidence.filter((item) => keySet.has(String(item.claim_key)));
}

function evidenceRows(value: unknown): Json[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Json =>
      item !== null && typeof item === "object" && !Array.isArray(item),
  );
}

function formatEvidenceRow(row: Json): string {
  const parts = [
    row.claim_key,
    row.source_type,
    row.metric_key,
    row.source_ref,
    row.formula ?? row.note,
  ]
    .filter((part) => part !== undefined && part !== null && String(part).trim() !== "")
    .map((part) => String(part));
  return parts.join(" / ");
}

function evidenceStatus(rows: Json[]): string {
  if (rows.length === 0) return "要確認";
  if (rows.some((row) => !row.last_updated)) return "最終更新未記録";
  const now = Date.now();
  const stale = rows.some((row) => {
    const parsed = Date.parse(String(row.last_updated));
    return Number.isFinite(parsed) && now - parsed > 1000 * 60 * 60 * 24 * 45;
  });
  return stale ? "古いデータを含む" : "根拠確認済み";
}

function EvidencePanel({
  title = "計算式・根拠",
  metric,
  evidence,
  rows,
  disclaimer,
  defaultOpen = false,
}: {
  title?: string;
  metric?: Json;
  evidence?: Json[];
  rows?: Json[];
  disclaimer?: string;
  defaultOpen?: boolean;
}) {
  const resolvedRows = rows ?? evidenceForKeys(evidence ?? [], metric?.evidence_keys);
  const formula = String(metric?.formula ?? "機械集計");
  const lastUpdated = String(
    metric?.last_updated ?? resolvedRows.find((row) => row.last_updated)?.last_updated ?? "-",
  );
  const note = String(metric?.note ?? "");
  const disclaimerText = String(disclaimer ?? metric?.disclaimer ?? "");
  return (
    <details className="evidence-panel kpi-details" open={defaultOpen}>
      <summary>
        {title}
        <span>{evidenceStatus(resolvedRows)}</span>
      </summary>
      <dl>
        <div>
          <dt>計算式</dt>
          <dd>{formula}</dd>
        </div>
        <div>
          <dt>最終更新</dt>
          <dd>{lastUpdated}</dd>
        </div>
        <div>
          <dt>根拠</dt>
          <dd>
            {resolvedRows.length > 0 ? (
              resolvedRows.map((row, index) => (
                <code
                  key={`${String(row.claim_key)}-${String(row.source_ref ?? "")}-${index}`}
                >
                  {formatEvidenceRow(row)}
                </code>
              ))
            ) : (
              <span>根拠行がありません。入力データまたはprovider設定を確認してください。</span>
            )}
          </dd>
        </div>
        {note && (
          <div>
            <dt>注記</dt>
            <dd>{note}</dd>
          </div>
        )}
        <div>
          <dt>免責</dt>
          <dd>
            {disclaimerText ||
              "この表示は比較材料であり、売買推奨や投資助言ではありません。"}
          </dd>
        </div>
      </dl>
    </details>
  );
}

function formatDetailMetric(metric: Json): string {
  const value = metric.value;
  const key = String(metric.metric_key ?? "");
  if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : "なし";
  if (typeof value === "boolean") return value ? "はい" : "いいえ";
  if (typeof value === "number") {
    if (key.includes("ratio") || key.includes("pct") || key.includes("expense")) {
      return `${value}%`;
    }
    if (
      key.includes("market_value") ||
      key.includes("pnl") ||
      key.includes("income") ||
      key.includes("cost")
    ) {
      return yen(value);
    }
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value ?? "-");
}

function GuideCards(props: { items: GuideCard[] }) {
  return (
    <div className="guide-grid">
      {props.items.map((item) => (
        <article className="guide-card" key={item.title}>
          <b>{item.title}</b>
          <p>{item.body}</p>
        </article>
      ))}
    </div>
  );
}

function QuestionChips(props: { onPick: (question: string) => void }) {
  return (
    <div className="chips" aria-label="想定質問">
      {SUGGESTED_QUESTIONS.map((question) => (
        <button key={question} className="chip" onClick={() => props.onPick(question)}>
          {question}
        </button>
      ))}
    </div>
  );
}

function presetToSource(preset: SourcePreset) {
  return {
    name: preset.name,
    url: preset.url,
    output_path: preset.output_path,
    query_hint: preset.query_hint,
    extract_text: true,
    include_metadata: true,
    preview_chars: 500,
  };
}

function buildContextualQuery(
  messages: ChatMessage[],
  currentQuestion: string,
  targetContext?: string,
) {
  const conversation = messages
    .slice(-8)
    .map((message) => `${message.role === "user" ? "ユーザー" : "アシスタント"}: ${message.content}`)
    .join("\n");
  return [
    "以下の会話履歴を踏まえて、最後の質問に自然に返答してください。",
    "ローカル文書にない事実は推測せず、不明または要検証と明記してください。",
    "出力は日本語で、ユーザーに見せる最終回答だけを書いてください。内部の担当名、ドラフト名、レビュー担当名は出さないでください。",
    ...(targetContext ? ["", "対象指定", targetContext] : []),
    "",
    "会話履歴",
    conversation || "なし",
    "",
    "最後の質問:",
    currentQuestion,
  ].join("\n");
}

function stripInternalLabels(text: string) {
  return text
    .replaceAll("統合最終回答（ローカル擬似・実API未使用）", "")
    .replaceAll("ドラフト回答（ローカル擬似・実API未使用）", "")
    .replaceAll("統合担当", "")
    .replaceAll("レビュー担当", "")
    .replaceAll("厳格なレビュアー", "")
    .replaceAll("ローカル擬似", "")
    .replaceAll("実API未使用", "")
    .trim();
}

function cleanAssistantAnswer(raw: unknown, skipped?: boolean) {
  const text = stripInternalLabels(
    typeof raw === "string" ? raw.trim() : JSON.stringify(raw, null, 2)
  );
  if (skipped || text.includes("オーケストレーションをスキップ")) {
    return [
      "参照できるローカル文書がまだありません。",
      "",
      "1. 結論",
      "先にData IntakeでIRページやメモをRAG登録してください。",
      "",
      "2. 根拠",
      "このチャットはローカル文書検索結果を根拠に回答する設計です。未登録の情報は根拠化できません。",
      "",
      "3. 不確実性",
      "未登録データ、取得失敗ページ、JavaScript描画ページは回答から漏れます。",
      "",
      "4. 次アクション",
      "自動取得が失敗する場合は、同じタブの手動テキスト取込に本文を貼り付けてください。",
    ].join("\n");
  }
  return text;
}

// --- RAG search ------------------------------------------------------------

function isHttpUrl(value: unknown): value is string {
  return typeof value === "string" && /^https?:\/\//.test(value);
}

function SourceCite({ source, metadata }: { source: unknown; metadata?: Json }) {
  const url = metadata?.source_url;
  if (isHttpUrl(url)) {
    return (
      <a className="mono cite-link" href={url} target="_blank" rel="noreferrer">
        {url} ↗
      </a>
    );
  }
  return <span className="mono">{String(source)}</span>;
}

function ResultText({ text, limit = 220 }: { text: unknown; limit?: number }) {
  const full = String(text ?? "");
  if (full.length <= limit) return <span className="result-text">{full}</span>;
  return (
    <details className="result-text">
      <summary>{full.slice(0, limit)}…</summary>
      <div className="result-full">{full}</div>
    </details>
  );
}

function SearchTab() {
  const [query, setQuery] = useState("配当 方針 DOE 配当性向");
  const [dbPath, setDbPath] = useState(DEFAULT_RAG_DB_PATH);
  const [limit, setLimit] = useState(5);
  const [hybrid, setHybrid] = useState(true);
  const [alpha, setAlpha] = useState(0.5);
  const { loading, error, data, run } = useAsync<Json>();

  const search = () =>
    run(() => api<Json>("/api/rag/search", { query, db_path: dbPath, limit, hybrid, alpha }));

  const results: Json[] = data?.results ?? [];
  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Evidence</p>
          <h2>根拠検索</h2>
        </div>
        <span className="badge">出典 / 引用</span>
      </div>

      <div className="form">
        <Field label="クエリ">
          <input value={query} onChange={(e) => setQuery(e.target.value)} />
        </Field>
        <Field label="RAG DB パス">
          <input value={dbPath} onChange={(e) => setDbPath(e.target.value)} />
        </Field>
        <Field label="件数">
          <input
            type="number"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          />
        </Field>
        <Field label="ハイブリッド">
          <input type="checkbox" checked={hybrid} onChange={(e) => setHybrid(e.target.checked)} />
        </Field>
        <Field label={`alpha(意味重み)=${alpha}`}>
          <input
            type="range"
            min={0}
            max={5}
            step={0.1}
            value={alpha}
            onChange={(e) => setAlpha(Number(e.target.value))}
            disabled={!hybrid}
          />
        </Field>
        <button className="primary" onClick={search} disabled={loading}>
          検索
        </button>
      </div>
      <Status loading={loading} error={error} />
      {results.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>#</th>
              <th>score</th>
              <th>source</th>
              <th>text</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r, i) => (
              <tr key={r.chunk_id ?? i}>
                <td>{i + 1}</td>
                <td>{Number(r.score).toPrecision(3)}</td>
                <td><SourceCite source={r.source} metadata={r.metadata} /></td>
                <td><ResultText text={r.text} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// --- Investment-only MVP --------------------------------------------------

function CsvValidationPanel(props: { title: string; data?: Json | null }) {
  const data = props.data;
  if (!data) return null;
  const errors: Json[] = Array.isArray(data.errors) ? data.errors : [];
  const warnings: Json[] = Array.isArray(data.warnings) ? data.warnings : [];
  const rows = [...errors, ...warnings];
  const valid = data.valid === true;
  return (
    <div className="subpanel csv-validation-panel">
      <div className="report-audit-head">
        <div>
          <h3>{props.title}</h3>
          <p className="hint">
            Parsed rows: <span className="mono">{String(data.count ?? 0)}</span>
          </p>
        </div>
        <span className={`badge ${valid ? "safe" : "warn"}`}>
          {valid ? "valid" : "needs fix"}
        </span>
      </div>
      {rows.length > 0 ? (
        <table className="grid">
          <thead>
            <tr>
              <th>level</th>
              <th>row</th>
              <th>column</th>
              <th>reason</th>
              <th>message</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item, index) => (
              <tr key={`${String(item.code)}-${String(item.row ?? item.column ?? index)}`}>
                <td>
                  <span className={String(item.level) === "error" ? "badge warn" : "badge"}>
                    {String(item.level ?? "-")}
                  </span>
                </td>
                <td className="mono">{String(item.row ?? "-")}</td>
                <td className="mono">
                  {Array.isArray(item.columns) ? item.columns.join(", ") : String(item.column ?? "-")}
                </td>
                <td>{String(item.code ?? "-")}</td>
                <td>{String(item.message ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="hint">No blocking CSV issues were found.</p>
      )}
    </div>
  );
}

function HoldingsTab() {
  const [csv, setCsv] = useState(AUDITABLE_SAMPLE_HOLDINGS_CSV);
  const importState = useAsync<Json>();
  const analysisState = useAsync<Json>();
  const templateState = useAsync<Json>();
  const validationState = useAsync<Json>();
  const [holdingDraft, setHoldingDraft] = useState<CsvDraft>(DEFAULT_HOLDING_DRAFT);
  const [validationActionMessage, setValidationActionMessage] = useState<string | null>(null);

  const importHoldings = () =>
    importState.run(async () => {
      setValidationActionMessage(null);
      return api<Json>("/api/holdings/import", { csv_text: csv });
    });
  const validateHoldings = () =>
    validationState.run(async () => {
      const validation = await api<Json>("/api/holdings/validate", { csv_text: csv });
      setValidationActionMessage(
        validation.valid === true
          ? "Holding CSV validation passed. Analysis can run."
          : "Holding CSV validation failed. Analysis is blocked until the listed issues are fixed.",
      );
      return validation;
    });
  const analyze = () =>
    analysisState.run(async () => {
      setValidationActionMessage("Validating holding CSV before analysis.");
      const validation = await validationState.run(() =>
        api<Json>("/api/holdings/validate", { csv_text: csv }),
      );
      if (!validation) throw new Error("Holding CSV validation could not complete.");
      if (validation.valid !== true) {
        setValidationActionMessage(
          "Analysis stopped: holding CSV validation failed. Review the validation table.",
        );
        throw new Error("Fix holding CSV validation errors before analysis.");
      }
      setValidationActionMessage("Holding CSV validation passed. Running analysis.");
      const result = await api<Json>("/api/portfolio/analyze", {
        csv_text: csv,
        financials_csv: SAMPLE_FINANCIALS_PATH,
      });
      setValidationActionMessage("Analysis completed after holding CSV validation.");
      return result;
    });
  const loadSampleHoldings = () => setCsv(AUDITABLE_SAMPLE_HOLDINGS_CSV);
  const loadMinimalHoldings = () => setCsv(SAMPLE_HOLDINGS_CSV);
  const updateHoldingDraft = (column: string, value: string) =>
    setHoldingDraft((current) => ({ ...current, [column]: value }));
  const addHoldingDraftRow = () => {
    setCsv((current) => appendCsvDraft(current, HOLDING_CSV_COLUMNS, holdingDraft));
    setValidationActionMessage("Manual holding row was added to the CSV. Validate before import.");
  };
  const importHoldingFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    void file.text().then((text) => {
      setCsv(text);
      setValidationActionMessage(`Loaded ${file.name}. Validate before import or analysis.`);
    });
  };
  const downloadHoldingCsv = () => downloadTextFile("investment_holdings.csv", csv);
  const downloadHoldingImportJson = () =>
    downloadTextFile(
      "investment_holdings_import.json",
      jsonText(importState.data),
      "application/json",
    );
  const loadHoldingTemplate = () =>
    templateState.run(async () => {
      const template = await api<Json>("/api/holdings/template", { include_examples: true });
      setCsv(String(template.csv_text ?? ""));
      return template;
    });

  const summary: Json = analysisState.data?.summary ?? {};
  const rows: Json[] =
    (analysisState.data?.holdings as Json[] | undefined) ??
    (importState.data?.holdings as Json[] | undefined) ??
    [];
  const inputWarnings: Json[] = Array.isArray(importState.data?.input_warnings)
    ? importState.data.input_warnings
    : [];
  const nisaAlerts: Json[] = Array.isArray(summary.nisa?.alerts)
    ? summary.nisa.alerts
    : [];
  const dataAlerts: Json[] = Array.isArray(summary.data_quality?.alerts)
    ? summary.data_quality.alerts
    : [];
  const incomeAlerts: Json[] = Array.isArray(summary.income_quality?.alerts)
    ? summary.income_quality.alerts
    : [];

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Holdings</p>
          <h2>保有一覧・ポートフォリオ分析</h2>
        </div>
        <span className="badge">日本株 + 投信</span>
      </div>
      <p className="hint">
        保有CSVまたは手入力相当のCSVから、評価額、評価損益、配当/分配金見込み、NISA枠、
        集中度を機械的に集計します。売買推奨や注文連携は行いません。
      </p>
      <Field label="保有CSV">
        <textarea rows={7} value={csv} onChange={(e) => setCsv(e.target.value)} />
      </Field>
      <div className="subpanel csv-manual-panel">
        <h3>Manual holding row</h3>
        <p className="hint">
          Fill one row, append it to the CSV, then validate/import/analyze. This does not place orders.
        </p>
        <div className="csv-manual-grid">
          {HOLDING_CSV_COLUMNS.map((column) => (
            <Field key={column} label={column}>
              <input
                value={holdingDraft[column] ?? ""}
                onChange={(event) => updateHoldingDraft(column, event.target.value)}
              />
            </Field>
          ))}
        </div>
        <div className="form">
          <button onClick={addHoldingDraftRow}>Add manual row to CSV</button>
          <label className="button-like">
            Import CSV file
            <input type="file" accept=".csv,text/csv" onChange={importHoldingFile} />
          </label>
          <button onClick={downloadHoldingCsv}>Download CSV</button>
          <button onClick={downloadHoldingImportJson} disabled={!importState.data}>
            Download import JSON
          </button>
        </div>
      </div>
      <div className="form">
        <button onClick={loadSampleHoldings}>サンプル保有CSVを読み込む</button>
        <button onClick={loadHoldingTemplate} disabled={templateState.loading}>
          CSVテンプレート
        </button>
        <button onClick={loadMinimalHoldings}>最小CSVを読み込む</button>
        <button onClick={validateHoldings} disabled={validationState.loading}>
          Validate CSV
        </button>
        <button onClick={importHoldings} disabled={importState.loading}>
          形式を確認
        </button>
        <button className="primary" onClick={analyze} disabled={analysisState.loading}>
          分析
        </button>
      </div>
      <Status loading={templateState.loading} error={templateState.error} />
      <Status loading={validationState.loading} error={validationState.error} />
      <Status loading={importState.loading} error={importState.error} />
      <Status loading={analysisState.loading} error={analysisState.error} />
      {validationActionMessage && <p className="status">{validationActionMessage}</p>}
      <CsvValidationPanel title="Holding CSV validation" data={validationState.data} />

      {inputWarnings.length > 0 && (
        <div className="subpanel csv-guidance-panel">
          <h3>CSV input guidance</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>level</th>
                <th>row</th>
                <th>column</th>
                <th>reason</th>
                <th>message</th>
              </tr>
            </thead>
            <tbody>
              {inputWarnings.map((warning, index) => (
                <tr key={`${String(warning.code)}-${String(warning.row ?? warning.column)}-${index}`}>
                  <td><span className="badge">{String(warning.level)}</span></td>
                  <td className="mono">{String(warning.row ?? "-")}</td>
                  <td className="mono">{String(warning.column ?? "-")}</td>
                  <td>{String(warning.code)}</td>
                  <td>{String(warning.message)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {analysisState.data && (
        <section className="metric-grid">
          <article className="metric-card accent">
            <span>評価額</span>
            <b>{yen(summary.market_value)}</b>
            <small>取得額 {yen(summary.cost_basis)}</small>
          </article>
          <article className={Number(summary.unrealized_pnl) >= 0 ? "metric-card pos" : "metric-card neg"}>
            <span>評価損益</span>
            <b>{yen(summary.unrealized_pnl)}</b>
            <small>{Number(summary.unrealized_pnl_pct ?? 0).toFixed(2)}%</small>
          </article>
          <article className="metric-card pos">
            <span>配当/分配金見込み</span>
            <b>{yen(summary.annual_income_estimate)}</b>
            <small>{Number(summary.income_yield_pct ?? 0).toFixed(2)}%</small>
          </article>
          <article className="metric-card warn">
            <span>NISA総枠残</span>
            <b>{yen(summary.nisa?.remaining_lifetime)}</b>
            <small>成長枠残 {yen(summary.nisa?.growth_remaining)}</small>
          </article>
        </section>
      )}

      {nisaAlerts.length > 0 && (
        <div className="subpanel nisa-alert-panel">
          <h3>NISA alerts</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>level</th>
                <th>bucket</th>
                <th>usage</th>
                <th>remaining</th>
                <th>message</th>
              </tr>
            </thead>
            <tbody>
              {nisaAlerts.map((alert, index) => (
                <tr key={`${String(alert.code)}-${index}`}>
                  <td>
                    <span className={String(alert.level) === "error" ? "badge warn" : "badge"}>
                      {String(alert.level)}
                    </span>
                  </td>
                  <td>{String(alert.bucket)}</td>
                  <td className="mono">
                    {Number(alert.usage_pct ?? 0).toLocaleString(undefined, {
                      maximumFractionDigits: 2,
                    })}
                    %
                  </td>
                  <td className="mono">{yen(alert.remaining)}</td>
                  <td>{String(alert.message)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dataAlerts.length > 0 && (
        <div className="subpanel data-alert-panel">
          <h3>Data freshness alerts</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>level</th>
                <th>source</th>
                <th>reason</th>
                <th>age</th>
                <th>message</th>
              </tr>
            </thead>
            <tbody>
              {dataAlerts.map((alert, index) => (
                <tr key={`${String(alert.code)}-${String(alert.security_code ?? alert.source_ref)}-${index}`}>
                  <td>
                    <span className={String(alert.level) === "error" ? "badge warn" : "badge"}>
                      {String(alert.level)}
                    </span>
                  </td>
                  <td>
                    <span className="mono">
                      {String(alert.security_code ?? alert.source_ref ?? alert.provider_id ?? "-")}
                    </span>
                    <small>{String(alert.provider_id ?? alert.field ?? "")}</small>
                  </td>
                  <td>{String(alert.code)}</td>
                  <td className="mono">
                    {alert.age_days !== undefined ? `${Number(alert.age_days).toFixed(1)}d` : "-"}
                  </td>
                  <td>{String(alert.message)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {incomeAlerts.length > 0 && (
        <div className="subpanel income-alert-panel">
          <h3>Income quality alerts</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>level</th>
                <th>holding</th>
                <th>reason</th>
                <th>value</th>
                <th>message</th>
              </tr>
            </thead>
            <tbody>
              {incomeAlerts.map((alert, index) => (
                <tr key={`${String(alert.code)}-${String(alert.security_code)}-${index}`}>
                  <td>
                    <span className={String(alert.level) === "error" ? "badge warn" : "badge"}>
                      {String(alert.level)}
                    </span>
                  </td>
                  <td>
                    <span className="mono">{String(alert.security_code ?? "-")}</span>
                    <small>{String(alert.name ?? "")}</small>
                  </td>
                  <td>{String(alert.code)}</td>
                  <td className="mono">
                    {String(alert.field) === "income_yield_pct"
                      ? `${Number(alert.value ?? 0).toFixed(2)}%`
                      : String(alert.value ?? "-")}
                  </td>
                  <td>{String(alert.message)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rows.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>種別</th>
              <th>コード</th>
              <th>名称</th>
              <th>数量</th>
              <th>評価額</th>
              <th>損益</th>
              <th>NISA/税区分</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${String(row.ticker_or_fund_code)}-${index}`}>
                <td>{String(row.asset_type)}</td>
                <td className="mono">{String(row.ticker_or_fund_code)}</td>
                <td>{String(row.name)}</td>
                <td className="mono">{String(row.quantity)}</td>
                <td className="mono">{row.market_value ? yen(row.market_value) : "-"}</td>
                <td className="mono">{row.unrealized_pnl ? yen(row.unrealized_pnl) : "-"}</td>
                <td>{String(row.tax_wrapper)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {analysisState.data?.disclaimer && (
        <p className="hint">{String(analysisState.data.disclaimer)}</p>
      )}
    </section>
  );
}

function CandidateScreenTab({ onOpenDetail }: { onOpenDetail: (code: string, assetType: string) => void }) {
  const [includeStocks, setIncludeStocks] = useState(true);
  const [includeFunds, setIncludeFunds] = useState(true);
  const [excludeCut, setExcludeCut] = useState(true);
  const [minEquity, setMinEquity] = useState("40");
  const [maxExpense, setMaxExpense] = useState("0.2");
  const [nisaOnly, setNisaOnly] = useState(true);
  const [minDiversification, setMinDiversification] = useState("0.8");
  const [fundsCsv, setFundsCsv] = useState(SAMPLE_FUNDS_CSV);
  const [presetName, setPresetName] = useState("標準スクリーニング");
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetStatus, setPresetStatus] = useState<string | null>(null);
  const [providerRuntimeMode, setProviderRuntimeMode] = useState("production");
  const [presets, setPresets] = useState<CandidateScreenPreset[]>(() =>
    readCandidateScreenPresets(),
  );
  const state = useAsync<Json>();
  const providerState = useAsync<Json>();
  const fundTemplateState = useAsync<Json>();
  const fundValidationState = useAsync<Json>();
  const [fundDraft, setFundDraft] = useState<CsvDraft>(DEFAULT_FUND_DRAFT);
  const [screenActionMessage, setScreenActionMessage] = useState<string | null>(null);

  const screen = () =>
    state.run(async () => {
      if (includeFunds) {
        setScreenActionMessage("Validating fund CSV before candidate screening.");
        const validation = await fundValidationState.run(() =>
          api<Json>("/api/funds/validate", { funds_csv_text: fundsCsv }),
        );
        if (!validation) throw new Error("Fund CSV validation could not complete.");
        if (validation.valid !== true) {
          setScreenActionMessage(
            "Candidate screening stopped: fund CSV validation failed. Review the validation table.",
          );
          throw new Error("Fix fund CSV validation errors before screening.");
        }
      } else {
        setScreenActionMessage("Fund CSV validation skipped because fund candidates are disabled.");
      }
      setScreenActionMessage("Candidate input validation passed. Running screen.");
      const result = await api<Json>("/api/candidates/screen", {
        asset_types: [
          ...(includeStocks ? ["stock"] : []),
          ...(includeFunds ? ["fund"] : []),
        ],
        exclude_dividend_cut: excludeCut,
        min_equity_ratio: minEquity === "" ? undefined : Number(minEquity),
        max_expense_ratio: maxExpense === "" ? undefined : Number(maxExpense),
        nisa_eligible_only: nisaOnly,
        min_diversification_score:
          minDiversification === "" ? undefined : Number(minDiversification),
        funds_csv_text: fundsCsv,
        financials_csv: SAMPLE_FINANCIALS_PATH,
        sort_by: "score",
      });
      setScreenActionMessage("Candidate screening completed after validation.");
      return result;
    });
  const loadProviderPolicyLedger = () =>
    providerState.run(() =>
      api<Json>("/api/providers/policy", {
        runtime_mode: providerRuntimeMode,
        provider_ids: [
          "edinet",
          "user_csv",
          "manual",
          "stooq_public_csv",
          "yfinance",
          "jquants",
          "alpha_vantage",
        ],
      }),
    );
  const loadSampleFunds = () => setFundsCsv(SAMPLE_FUNDS_CSV);
  const updateFundDraft = (column: string, value: string) =>
    setFundDraft((current) => ({ ...current, [column]: value }));
  const addFundDraftRow = () => {
    setFundsCsv((current) => appendCsvDraft(current, FUND_CSV_COLUMNS, fundDraft));
    setScreenActionMessage("Manual fund row was added to the CSV. Validate before screening.");
  };
  const importFundFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    void file.text().then((text) => {
      setFundsCsv(text);
      setScreenActionMessage(`Loaded ${file.name}. Validate before screening.`);
    });
  };
  const downloadFundCsv = () => downloadTextFile("investment_funds.csv", fundsCsv);
  const downloadFundValidationJson = () =>
    downloadTextFile(
      "investment_funds_validation.json",
      jsonText(fundValidationState.data),
      "application/json",
    );
  const loadFundTemplate = () =>
    fundTemplateState.run(async () => {
      const template = await api<Json>("/api/funds/template", { include_examples: true });
      setFundsCsv(String(template.csv_text ?? ""));
      return template;
    });
  const validateFunds = () =>
    fundValidationState.run(async () => {
      const validation = await api<Json>("/api/funds/validate", { funds_csv_text: fundsCsv });
      setScreenActionMessage(
        validation.valid === true
          ? "Fund CSV validation passed. Candidate screening can run."
          : "Fund CSV validation failed. Candidate screening is blocked until the listed issues are fixed.",
      );
      return validation;
    });
  const selectedPreset = presets.find((preset) => preset.id === selectedPresetId);

  const savePreset = () => {
    const name = presetName.trim();
    if (!name) {
      setPresetStatus("プリセット名を入力してください。");
      return;
    }
    const now = new Date().toISOString();
    const id = selectedPreset?.id ?? makeCandidatePresetId();
    const nextPreset: CandidateScreenPreset = {
      id,
      name,
      includeStocks,
      includeFunds,
      excludeCut,
      minEquity,
      maxExpense,
      nisaOnly,
      minDiversification,
      createdAt: selectedPreset?.createdAt ?? now,
      updatedAt: now,
    };
    const nextPresets = [
      nextPreset,
      ...presets.filter((preset) => preset.id !== id),
    ].slice(0, 12);
    setPresets(nextPresets);
    setSelectedPresetId(id);
    setPresetName(name);
    const saved = writeCandidateScreenPresets(nextPresets);
    setPresetStatus(
      saved
        ? `${name} を保存しました。`
        : "ブラウザ保存に失敗しました。条件は画面上だけ更新されています。",
    );
  };

  const applyPreset = (preset: CandidateScreenPreset) => {
    setIncludeStocks(preset.includeStocks);
    setIncludeFunds(preset.includeFunds);
    setExcludeCut(preset.excludeCut);
    setMinEquity(preset.minEquity);
    setMaxExpense(preset.maxExpense);
    setNisaOnly(preset.nisaOnly);
    setMinDiversification(preset.minDiversification);
    setSelectedPresetId(preset.id);
    setPresetName(preset.name);
    setPresetStatus(`${preset.name} を適用しました。CSV本文は変更していません。`);
  };

  const applySelectedPreset = () => {
    if (!selectedPreset) {
      setPresetStatus("読み込むプリセットを選択してください。");
      return;
    }
    applyPreset(selectedPreset);
  };

  const deleteSelectedPreset = () => {
    if (!selectedPreset) {
      setPresetStatus("削除するプリセットを選択してください。");
      return;
    }
    const nextPresets = presets.filter((preset) => preset.id !== selectedPreset.id);
    setPresets(nextPresets);
    setSelectedPresetId("");
    setPresetName("");
    const saved = writeCandidateScreenPresets(nextPresets);
    setPresetStatus(
      saved
        ? `${selectedPreset.name} を削除しました。`
        : "ブラウザ保存の更新に失敗しました。画面上では削除済みです。",
    );
  };

  const results: Json[] = Array.isArray(state.data?.results) ? state.data.results : [];
  const blocked: Json[] = Array.isArray(state.data?.blocked_providers)
    ? state.data.blocked_providers
    : [];
  const providerRows: Json[] = Array.isArray(providerState.data?.providers)
    ? providerState.data.providers
    : [];

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Candidates</p>
          <h2>条件フィルタ型 候補抽出</h2>
        </div>
        <span className="badge">比較対象の提示のみ</span>
      </div>
      <p className="hint">
        条件に合う日本株・投信を抽出します。結果は比較材料であり、買付・売却・保有継続の
        判断を代行しません。
      </p>
      <div className="subpanel">
        <h3>抽出条件プリセット</h3>
        <p className="hint">
          保存するのは条件だけです。投信プロファイルCSVや抽出結果はブラウザ保存に含めません。
        </p>
        <div className="form">
          <Field label="プリセット名">
            <input value={presetName} onChange={(e) => setPresetName(e.target.value)} />
          </Field>
          <Field label="保存済みプリセット">
            <select
              value={selectedPresetId}
              onChange={(e) => {
                const id = e.target.value;
                const preset = presets.find((item) => item.id === id);
                setSelectedPresetId(id);
                if (preset) setPresetName(preset.name);
              }}
            >
              <option value="">未選択</option>
              {presets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="form">
          <button onClick={savePreset}>現在の条件を保存</button>
          <button onClick={applySelectedPreset} disabled={!selectedPreset}>
            選択条件を読み込む
          </button>
          <button onClick={deleteSelectedPreset} disabled={!selectedPreset}>
            選択条件を削除
          </button>
        </div>
        {presetStatus && <p className="hint">{presetStatus}</p>}
      </div>
      <div className="form">
        <label className="field check-field">
          <input type="checkbox" checked={includeStocks} onChange={(e) => setIncludeStocks(e.target.checked)} />
          <span>日本株</span>
        </label>
        <label className="field check-field">
          <input type="checkbox" checked={includeFunds} onChange={(e) => setIncludeFunds(e.target.checked)} />
          <span>投信</span>
        </label>
        <label className="field check-field">
          <input type="checkbox" checked={excludeCut} onChange={(e) => setExcludeCut(e.target.checked)} />
          <span>減配履歴ありを除外</span>
        </label>
        <label className="field check-field">
          <input type="checkbox" checked={nisaOnly} onChange={(e) => setNisaOnly(e.target.checked)} />
          <span>NISA対象のみ</span>
        </label>
      </div>
      <div className="form">
        <Field label="自己資本比率下限(%)">
          <input value={minEquity} onChange={(e) => setMinEquity(e.target.value)} />
        </Field>
        <Field label="信託報酬上限(%)">
          <input value={maxExpense} onChange={(e) => setMaxExpense(e.target.value)} />
        </Field>
        <Field label="分散度下限(0-1)">
          <input value={minDiversification} onChange={(e) => setMinDiversification(e.target.value)} />
        </Field>
      </div>
      <Field label="投信プロファイルCSV">
        <textarea rows={5} value={fundsCsv} onChange={(e) => setFundsCsv(e.target.value)} />
      </Field>
      <div className="subpanel csv-manual-panel">
        <h3>Manual fund row</h3>
        <p className="hint">
          Add a fund profile row, import a fund CSV file, or export the current profile CSV.
        </p>
        <div className="csv-manual-grid">
          {FUND_CSV_COLUMNS.map((column) => (
            <Field key={column} label={column}>
              <input
                value={fundDraft[column] ?? ""}
                onChange={(event) => updateFundDraft(column, event.target.value)}
              />
            </Field>
          ))}
        </div>
        <div className="form">
          <button onClick={addFundDraftRow}>Add manual row to CSV</button>
          <label className="button-like">
            Import CSV file
            <input type="file" accept=".csv,text/csv" onChange={importFundFile} />
          </label>
          <button onClick={downloadFundCsv}>Download CSV</button>
          <button onClick={downloadFundValidationJson} disabled={!fundValidationState.data}>
            Download validation JSON
          </button>
        </div>
      </div>
      <div className="form">
        <button onClick={loadSampleFunds}>サンプル投信CSVを読み込む</button>
        <button onClick={loadFundTemplate} disabled={fundTemplateState.loading}>
          投信テンプレート
        </button>
        <button onClick={validateFunds} disabled={fundValidationState.loading}>
          Validate funds CSV
        </button>
        <button className="primary" onClick={screen} disabled={state.loading}>
          条件に一致する比較対象を表示
        </button>
      </div>
      <Status loading={fundTemplateState.loading} error={fundTemplateState.error} />
      <Status loading={fundValidationState.loading} error={fundValidationState.error} />
      <Status loading={state.loading} error={state.error} />
      {screenActionMessage && <p className="status">{screenActionMessage}</p>}
      <CsvValidationPanel title="Fund CSV validation" data={fundValidationState.data} />
      <div className="subpanel provider-ledger-panel">
        <div className="report-audit-head">
          <div>
            <h3>Provider policy ledger</h3>
            <p className="hint">本番利用前にproviderごとの契約・再配布・用途の扱いを確認します。</p>
          </div>
          <span className="badge">{String(providerState.data?.runtime_mode ?? providerRuntimeMode)}</span>
        </div>
        <div className="form">
          <Field label="runtime mode">
            <select
              value={providerRuntimeMode}
              onChange={(e) => setProviderRuntimeMode(e.target.value)}
            >
              <option value="production">production</option>
              <option value="development">development</option>
            </select>
          </Field>
          <button onClick={loadProviderPolicyLedger} disabled={providerState.loading}>
            Provider台帳を確認
          </button>
        </div>
        <Status loading={providerState.loading} error={providerState.error} />
        {providerRows.length > 0 && (
          <table className="grid">
            <thead>
              <tr>
                <th>provider</th>
                <th>decision</th>
                <th>category</th>
                <th>commercial</th>
                <th>redistribution</th>
                <th>recommended use</th>
              </tr>
            </thead>
            <tbody>
              {providerRows.map((provider) => (
                <tr key={String(provider.provider_id)}>
                  <td className="mono">{String(provider.provider_id)}</td>
                  <td>
                    <span className={`badge ${provider.production_allowed ? "safe" : "warn"}`}>
                      {String(provider.runtime_decision)}
                    </span>
                  </td>
                  <td>{String(provider.category)}</td>
                  <td>{String(provider.commercial_use)}</td>
                  <td>{String(provider.redistribution)}</td>
                  <td>{String(provider.recommended_use)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {state.data?.non_advisory_boundary && (
        <p className="hint">{String(state.data.non_advisory_boundary)}</p>
      )}
      {blocked.length > 0 && (
        <p className="status error">
          production利用不可provider: {blocked.map((p) => String(p.provider_id)).join(", ")}
        </p>
      )}
      {results.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>種別</th>
              <th>コード</th>
              <th>名称</th>
              <th>条件一致</th>
              <th>指標</th>
              <th>詳細</th>
            </tr>
          </thead>
          <tbody>
            {results.map((item) => (
              <tr key={`${String(item.asset_type)}-${String(item.code)}`}>
                <td>{String(item.asset_type)}</td>
                <td className="mono">{String(item.code)}</td>
                <td>{String(item.name)}</td>
                <td className="hint">
                  {Array.isArray(item.matched_conditions)
                    ? item.matched_conditions.join(" / ")
                    : ""}
                </td>
                <td>
                  <pre>{JSON.stringify(item.metrics ?? {}, null, 2)}</pre>
                  {(() => {
                    const rows = evidenceRows(item.evidence);
                    return rows.length > 0 ? (
                      <EvidencePanel
                        title="候補根拠"
                        rows={rows}
                        metric={{
                          formula: "候補抽出条件と指標が一致した根拠",
                          last_updated: state.data?.generated_at,
                        }}
                        disclaimer={String(state.data?.disclaimer ?? "")}
                      />
                    ) : null;
                  })()}
                </td>
                <td>
                  <button
                    onClick={() =>
                      onOpenDetail(String(item.code), String(item.asset_type))
                    }
                  >
                    詳細
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function InvestmentReportTab() {
  const [holdingsCsv, setHoldingsCsv] = useState(AUDITABLE_SAMPLE_HOLDINGS_CSV);
  const [fundsCsv, setFundsCsv] = useState(SAMPLE_FUNDS_CSV);
  const [targetDividend, setTargetDividend] = useState(60000);
  const state = useAsync<Json>();
  const historyState = useAsync<Json>();
  const markdownState = useAsync<Json>();
  const compareState = useAsync<Json>();
  const reportHoldingValidationState = useAsync<Json>();
  const reportFundValidationState = useAsync<Json>();
  const [reportActionMessage, setReportActionMessage] = useState<string | null>(null);

  useEffect(() => {
    void historyState.run(() => api<Json>("/api/reports/investment-monthly/history"));
  }, []);

  const validateReportInputs = async (actionLabel = "report action"): Promise<boolean> => {
    setReportActionMessage(`Validating report holding CSV before ${actionLabel}.`);
    const holdingValidation = await reportHoldingValidationState.run(() =>
      api<Json>("/api/holdings/validate", { csv_text: holdingsCsv }),
    );
    if (!holdingValidation || holdingValidation.valid !== true) {
      setReportActionMessage(
        "Report action stopped: holding CSV validation failed. Review the validation table.",
      );
      return false;
    }

    if (fundsCsv.trim()) {
      setReportActionMessage(`Validating report fund CSV before ${actionLabel}.`);
      const fundValidation = await reportFundValidationState.run(() =>
        api<Json>("/api/funds/validate", { funds_csv_text: fundsCsv }),
      );
      if (!fundValidation || fundValidation.valid !== true) {
        setReportActionMessage(
          "Report action stopped: fund CSV validation failed. Review the validation table.",
        );
        return false;
      }
    } else {
      setReportActionMessage("Report fund CSV validation skipped because the fund CSV is empty.");
    }
    setReportActionMessage("Report CSV validation passed.");
    return true;
  };
  const validateReportCsvs = () => {
    void validateReportInputs("manual validation");
  };
  const generate = () =>
    state.run(async () => {
      const inputsValid = await validateReportInputs("report generation");
      if (!inputsValid) {
        throw new Error("Fix report CSV validation errors before report generation.");
      }
      setReportActionMessage("Report CSV validation passed. Running candidate screen.");
      const candidates = await api<Json>("/api/candidates/screen", {
        asset_types: ["stock", "fund"],
        exclude_dividend_cut: true,
        max_expense_ratio: 0.2,
        nisa_eligible_only: true,
        funds_csv_text: fundsCsv,
        financials_csv: SAMPLE_FINANCIALS_PATH,
      });
      const report = await api<Json>("/api/reports/investment-monthly", {
        csv_text: holdingsCsv,
        financials_csv: SAMPLE_FINANCIALS_PATH,
        candidates: candidates.results ?? [],
        target_annual_dividend: targetDividend,
        years: 10,
        growth_rate: 0,
        reinvest: true,
        auto_weight: "equal",
        optimization: "balanced",
        dividend_basis: "conservative",
      });
      void historyState.run(() => api<Json>("/api/reports/investment-monthly/history"));
      setReportActionMessage("Report generated after CSV validation.");
      return report;
    });
  const refreshHistory = () =>
    historyState.run(() => api<Json>("/api/reports/investment-monthly/history"));
  const loadSavedReport = (id: string) =>
    state.run(async () => {
      const entry = await api<Json>("/api/reports/investment-monthly/history/load", { id });
      return (entry.report as Json) ?? {};
    });
  const showCurrentMarkdown = () => {
    if (!state.data) return;
    markdownState.run(() =>
      api<Json>("/api/reports/investment-monthly/markdown", { report: state.data }),
    );
  };
  const showSavedMarkdown = (id: string) =>
    markdownState.run(() => api<Json>("/api/reports/investment-monthly/markdown", { id }));
  const compareLatestReports = () => {
    if (reports.length < 2) return;
    compareState.run(() =>
      api<Json>("/api/reports/investment-monthly/history/compare", {
        base_id: reports[1].id,
        compare_id: reports[0].id,
      }),
    );
  };
  const deleteSavedReport = (id: string) => {
    if (
      typeof window !== "undefined" &&
      !window.confirm("保存済みレポートを削除しますか？")
    ) {
      return;
    }
    historyState.run(async () => {
      await api<Json>("/api/reports/investment-monthly/history/delete", { id });
      return api<Json>("/api/reports/investment-monthly/history");
    });
  };
  const loadReportSamples = () => {
    setHoldingsCsv(AUDITABLE_SAMPLE_HOLDINGS_CSV);
    setFundsCsv(SAMPLE_FUNDS_CSV);
    setTargetDividend(60000);
  };

  const kpis: Json[] = Array.isArray(state.data?.kpis) ? state.data.kpis : [];
  const sections: Json[] = Array.isArray(state.data?.sections) ? state.data.sections : [];
  const evidence: Json[] = Array.isArray(state.data?.evidence) ? state.data.evidence : [];
  const publishAudit: Json =
    state.data?.publish_audit && typeof state.data.publish_audit === "object"
      ? state.data.publish_audit
      : {};
  const auditIssues: Json[] = Array.isArray(publishAudit.issues)
    ? publishAudit.issues
    : [];
  const reports: Json[] = Array.isArray(historyState.data?.reports)
    ? historyState.data.reports
    : [];
  const markdownText = String(markdownState.data?.markdown ?? "");
  const comparedMetrics: Json[] = Array.isArray(compareState.data?.metrics)
    ? compareState.data.metrics
    : [];

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Report</p>
          <h2>投資月次レポート</h2>
        </div>
        <span className="badge">決定論生成</span>
      </div>
      <p className="hint">
        保有分析と候補抽出結果から、根拠と計算式つきの非助言レポートを生成します。
      </p>
      <Field label="保有CSV">
        <textarea rows={6} value={holdingsCsv} onChange={(e) => setHoldingsCsv(e.target.value)} />
      </Field>
      <Field label="投信プロファイルCSV（候補抽出用）">
        <textarea rows={4} value={fundsCsv} onChange={(e) => setFundsCsv(e.target.value)} />
      </Field>
      <Field label="目標年間配当（円・任意）">
        <input
          type="number"
          value={targetDividend}
          onChange={(e) => setTargetDividend(Number(e.target.value))}
          placeholder="例: 60000"
        />
      </Field>
      <div className="form">
        <button onClick={loadReportSamples}>サンプルCSVを読み込む</button>
        <button
          onClick={validateReportCsvs}
          disabled={reportHoldingValidationState.loading || reportFundValidationState.loading}
        >
          Validate report CSVs
        </button>
        <button
          className="primary"
          onClick={generate}
          disabled={
            state.loading ||
            reportHoldingValidationState.loading ||
            reportFundValidationState.loading
          }
        >
          レポート生成
        </button>
      </div>
      <Status loading={reportHoldingValidationState.loading} error={reportHoldingValidationState.error} />
      <Status loading={reportFundValidationState.loading} error={reportFundValidationState.error} />
      <Status loading={state.loading} error={state.error} />
      {reportActionMessage && <p className="status">{reportActionMessage}</p>}
      <CsvValidationPanel
        title="Report holding CSV validation"
        data={reportHoldingValidationState.data}
      />
      <CsvValidationPanel
        title="Report fund CSV validation"
        data={reportFundValidationState.data}
      />

      {state.data?.publish_audit && (
        <div className="subpanel report-audit-panel">
          <div className="report-audit-head">
            <div>
              <h3>Publish audit</h3>
              <p className="hint">重要KPI、根拠、計算式、免責、自動売買無効化を確認します。</p>
            </div>
            <span className={`badge ${String(publishAudit.status) === "ok" ? "safe" : "warn"}`}>
              {String(publishAudit.status ?? "unknown")}
            </span>
          </div>
          <dl className="mini-stats">
            <div>
              <dt>issues</dt>
              <dd>{Number(publishAudit.issue_count ?? auditIssues.length).toLocaleString()}</dd>
            </div>
            <div>
              <dt>auto trading</dt>
              <dd>{String(publishAudit.auto_trading ?? false)}</dd>
            </div>
            <div>
              <dt>real API</dt>
              <dd>{String(publishAudit.call_real_api ?? false)}</dd>
            </div>
          </dl>
          {auditIssues.length > 0 && (
            <table className="grid">
              <thead>
                <tr>
                  <th>level</th>
                  <th>code</th>
                  <th>path</th>
                  <th>message</th>
                </tr>
              </thead>
              <tbody>
                {auditIssues.map((issue, index) => (
                  <tr key={`${String(issue.code)}-${String(issue.path)}-${index}`}>
                    <td><span className="badge warn">{String(issue.level)}</span></td>
                    <td>{String(issue.code)}</td>
                    <td className="mono">{String(issue.path)}</td>
                    <td>{String(issue.message)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="subpanel report-history">
        <div className="report-history-head">
          <div>
            <h3>保存済みレポート</h3>
            <p className="hint">生成済みの投資月次レポートを最新順に再表示します。</p>
          </div>
          <button onClick={refreshHistory} disabled={historyState.loading}>
            履歴を更新
          </button>
        </div>
        <Status loading={historyState.loading} error={historyState.error} />
        {reports.length >= 2 && (
          <div className="form">
            <button onClick={compareLatestReports} disabled={compareState.loading}>
              Compare latest reports
            </button>
          </div>
        )}
        <Status loading={compareState.loading} error={compareState.error} />
        {comparedMetrics.length > 0 && (
          <div className="report-diff">
            <table>
              <thead>
                <tr>
                  <th>KPI</th>
                  <th>Base</th>
                  <th>Compare</th>
                  <th>Delta</th>
                </tr>
              </thead>
              <tbody>
                {comparedMetrics.map((metric) => (
                  <tr key={String(metric.metric_key)}>
                    <td>{String(metric.label ?? metric.metric_key)}</td>
                    <td>{formatHistoryValue(metric.base_value, metric.value_format)}</td>
                    <td>{formatHistoryValue(metric.compare_value, metric.value_format)}</td>
                    <td>{formatHistoryDelta(metric)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {reports.length === 0 ? (
          <p className="hint">まだ保存済みレポートはありません。</p>
        ) : (
          <div className="history-list">
            {reports.map((item) => (
              <article className="history-item" key={String(item.id)}>
                <div>
                  <b>{String(item.title ?? "Investment monthly report")}</b>
                  <span>{formatDateTime(item.saved_at)}</span>
                </div>
                <dl>
                  <div>
                    <dt>評価額</dt>
                    <dd>{yen(item.market_value)}</dd>
                  </div>
                  <div>
                    <dt>年額見込み</dt>
                    <dd>{yen(item.annual_income_estimate)}</dd>
                  </div>
                  <div>
                    <dt>目標必要予算</dt>
                    <dd>
                      {item.target_required_budget == null
                        ? "-"
                        : yen(item.target_required_budget)}
                    </dd>
                  </div>
                  <div>
                    <dt>根拠</dt>
                    <dd>{Number(item.evidence_count ?? 0).toLocaleString()}件</dd>
                  </div>
                  <div>
                    <dt>integrity</dt>
                    <dd>
                      <span className={`badge ${String(item.integrity_status) === "ok" ? "safe" : "warn"}`}>
                        {String(item.integrity_status ?? "unknown")}
                      </span>
                    </dd>
                  </div>
                </dl>
                <div className="history-actions">
                  <button onClick={() => loadSavedReport(String(item.id))} disabled={state.loading}>
                    再表示
                  </button>
                  <button
                    onClick={() => showSavedMarkdown(String(item.id))}
                    disabled={markdownState.loading}
                  >
                    Markdown
                  </button>
                  <button
                    onClick={() => deleteSavedReport(String(item.id))}
                    disabled={historyState.loading}
                  >
                    削除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {state.data && (
        <div className="form">
          <button onClick={showCurrentMarkdown} disabled={markdownState.loading}>
            Markdownを表示
          </button>
        </div>
      )}
      <Status loading={markdownState.loading} error={markdownState.error} />
      {markdownText && (
        <div className="subpanel">
          <h3>Markdown</h3>
          <textarea className="markdown-output" rows={12} readOnly value={markdownText} />
        </div>
      )}

      {kpis.length > 0 && (
        <section className="metric-grid">
          {kpis.map((kpi) => (
            <article className="metric-card accent" key={String(kpi.metric_key)}>
              <span>{String(kpi.label)}</span>
              <b>{formatKpiValue(kpi)}</b>
              <small>{String(kpi.formula ?? "")}</small>
              <EvidencePanel
                metric={kpi}
                evidence={evidence}
                disclaimer={String(state.data?.disclaimer ?? "")}
              />
            </article>
          ))}
        </section>
      )}
      {sections.length > 0 && (
        <div className="guide-grid">
          {sections.map((section) => (
            <article className="guide-card" key={String(section.key)}>
              <b>{String(section.title)}</b>
              <p>{String(section.body)}</p>
            </article>
          ))}
        </div>
      )}
      {evidence.length > 0 && (
        <div className="subpanel">
          <EvidencePanel
            title={`根拠一覧（${evidence.length}件）`}
            rows={evidence}
            metric={{
              formula: "レポート内のKPIとclaim-evidence対応表",
              last_updated: state.data?.generated_at,
            }}
            disclaimer={String(state.data?.disclaimer ?? "")}
            defaultOpen
          />
        </div>
      )}
      {state.data?.disclaimer && <p className="hint">{String(state.data.disclaimer)}</p>}
    </section>
  );
}

function InvestmentDetailTab({ seed }: { seed: DetailSeed }) {
  const [code, setCode] = useState(seed.code);
  const [assetType, setAssetType] = useState(seed.assetType);
  const [holdingsCsv, setHoldingsCsv] = useState(AUDITABLE_SAMPLE_HOLDINGS_CSV);
  const [fundsCsv, setFundsCsv] = useState(SAMPLE_FUNDS_CSV);
  const state = useAsync<Json>();

  useEffect(() => {
    setCode(seed.code);
    setAssetType(seed.assetType || "auto");
  }, [seed.assetType, seed.code, seed.nonce]);

  const loadSamples = () => {
    setHoldingsCsv(AUDITABLE_SAMPLE_HOLDINGS_CSV);
    setFundsCsv(SAMPLE_FUNDS_CSV);
  };
  const loadDetail = () =>
    state.run(() =>
      api<Json>("/api/investment/detail", {
        code,
        asset_type: assetType === "auto" ? undefined : assetType,
        csv_text: holdingsCsv,
        funds_csv_text: fundsCsv,
        financials_csv: SAMPLE_FINANCIALS_PATH,
      }),
    );

  const metrics: Json[] = Array.isArray(state.data?.metrics) ? state.data.metrics : [];
  const sections: Json[] = Array.isArray(state.data?.sections) ? state.data.sections : [];
  const evidence: Json[] = Array.isArray(state.data?.evidence) ? state.data.evidence : [];

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Detail</p>
          <h2>銘柄 / 投信 詳細</h2>
        </div>
        <span className="badge">比較材料のみ</span>
      </div>
      <p className="hint">
        保有CSV、投信プロファイルCSV、EDINET由来財務CSVを使い、1コードの保有状況と根拠を確認します。
        売買判断は代行しません。
      </p>
      <div className="form">
        <Field label="コード">
          <input value={code} onChange={(e) => setCode(e.target.value.trim())} />
        </Field>
        <Field label="種別">
          <select value={assetType} onChange={(e) => setAssetType(e.target.value)}>
            <option value="auto">自動判定</option>
            <option value="stock">日本株</option>
            <option value="fund">投信</option>
          </select>
        </Field>
      </div>
      <Field label="保有CSV">
        <textarea rows={5} value={holdingsCsv} onChange={(e) => setHoldingsCsv(e.target.value)} />
      </Field>
      <Field label="投信プロファイルCSV">
        <textarea rows={4} value={fundsCsv} onChange={(e) => setFundsCsv(e.target.value)} />
      </Field>
      <div className="form">
        <button onClick={loadSamples}>サンプルCSVを読み込む</button>
        <button className="primary" onClick={loadDetail} disabled={state.loading || !code.trim()}>
          詳細を表示
        </button>
      </div>
      <Status loading={state.loading} error={state.error} />

      {state.data && (
        <div className="subpanel">
          <h3>
            {String(state.data.code)} {String(state.data.name ?? "")}
          </h3>
          {state.data.available === false && (
            <p className="status error">指定コードの保有・財務・投信プロファイルが見つかりません。</p>
          )}
          {state.data.non_advisory_boundary && (
            <p className="hint">{String(state.data.non_advisory_boundary)}</p>
          )}
        </div>
      )}

      {metrics.length > 0 && (
        <section className="metric-grid">
          {metrics.map((metric) => (
            <article className="metric-card" key={String(metric.metric_key)}>
              <span>{String(metric.label)}</span>
              <b>{formatDetailMetric(metric)}</b>
              <small>{String(metric.formula ?? "")}</small>
              <EvidencePanel
                metric={metric}
                evidence={evidence}
                disclaimer={String(state.data?.disclaimer ?? "")}
              />
            </article>
          ))}
        </section>
      )}

      {sections.length > 0 && (
        <div className="subpanel">
          <h3>確認ポイント</h3>
          <div className="guide-grid">
            {sections.map((section) => (
              <article className="guide-card" key={String(section.key)}>
                <h3>{String(section.title)}</h3>
                <p>{String(section.body)}</p>
              </article>
            ))}
          </div>
        </div>
      )}

      {evidence.length > 0 && (
        <div className="subpanel">
          <h3>根拠一覧</h3>
          <EvidencePanel
            title={`根拠一覧（${evidence.length}件）`}
            rows={evidence}
            metric={{
              formula: "詳細画面のclaim-evidence対応表",
              last_updated: state.data?.generated_at,
            }}
            disclaimer={String(state.data?.disclaimer ?? "")}
            defaultOpen
          />
        </div>
      )}

      {state.data?.disclaimer && <p className="hint">{String(state.data.disclaimer)}</p>}
    </section>
  );
}

// --- AI answer (orchestration, offline) -----------------------------------

function FeedbackButtons({ message }: { message: ChatMessage }) {
  const [sent, setSent] = useState<"up" | "down" | null>(null);

  const rate = async (rating: "up" | "down") => {
    if (sent) return;
    setSent(rating);
    try {
      await api("/api/feedback", {
        rating,
        sources: (message.sources ?? [])
          .map((s) => String(s.source ?? ""))
          .filter(Boolean),
        question: message.question ?? "",
        answer_preview: message.content.slice(0, 200),
      });
    } catch {
      setSent(null);
    }
  };

  if (sent) {
    return (
      <div className="feedback">
        <small className="feedback-thanks">
          {sent === "up" ? "👍" : "👎"} 記録しました。次回以降の検索ランキングに反映されます。
        </small>
      </div>
    );
  }
  return (
    <div className="feedback">
      <span className="feedback-label">この回答は役立ちましたか？</span>
      <button className="feedback-btn" onClick={() => void rate("up")} aria-label="役に立った">
        👍
      </button>
      <button
        className="feedback-btn"
        onClick={() => void rate("down")}
        aria-label="役に立たなかった"
      >
        👎
      </button>
    </div>
  );
}

function AnswerTab() {
  const [query, setQuery] = useState("選択中の対象銘柄について、配当方針と減配リスクを取得済みIR資料だけで整理して");
  const [dbPath, setDbPath] = useState(DEFAULT_RAG_DB_PATH);
  const [targetSource, setTargetSource] = useState(TARGET_SOURCE_OPTIONS[1].source);
  const [evidenceLimit, setEvidenceLimit] = useState(20);
  const [drafts, setDrafts] = useState(3);
  const [hybrid, setHybrid] = useState(true);
  const [useRealApi, setUseRealApi] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "銘柄、比較軸、保有状況、取得済み資料を前提に回答します。根拠がない点は不明として扱います。",
      meta: "system",
    },
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastData, setLastData] = useState<Json | null>(null);
  const selectedTarget =
    TARGET_SOURCE_OPTIONS.find((option) => option.source === targetSource) ??
    TARGET_SOURCE_OPTIONS[0];

  async function ask() {
    const trimmed = query.trim();
    if (!trimmed || loading) return;

    const userMessage: ChatMessage = { role: "user", content: trimmed };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setQuery("");
    setLoading(true);
    setError(null);

    try {
      const contextualQuery = buildContextualQuery(
        nextMessages,
        trimmed,
        selectedTarget.queryContext
      );
      const result = await api<Json>("/api/orchestrate", {
        query: contextualQuery,
        db_path: dbPath,
        target_source: targetSource || undefined,
        drafts,
        hybrid,
        critique: true,
        limit: evidenceLimit,
        call_real_api: useRealApi,
        api_key: apiKeyInput.trim() || undefined,
      });
      setLastData(result);
      if (result.error) {
        setError(String(result.error));
        setMessages(nextMessages);
        return;
      }
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: cleanAssistantAnswer(result.final_answer ?? result.answer, result.skipped),
          meta: result.skipped ? "RAG未ヒット" : "回答",
          sources: result.results ?? [],
          question: trimmed,
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const resetChat = () => {
    setMessages([
      {
        role: "assistant",
        content:
          "会話をリセットしました。まず銘柄・比較対象・判断軸を1つずつ指定してください。",
        meta: "system",
      },
    ]);
    setQuery("");
    setUseRealApi(false);
    setLoading(false);
    setLastData(null);
    setError(null);
  };

  const sourceResults: Json[] = lastData?.results ?? [];
  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">AI Chat</p>
          <h2>文脈保持チャット</h2>
        </div>
        <span className="badge">RAG + Multi-agent orchestration</span>
      </div>
      <p className="hint">
        RAG検索後、複数ドラフト→レビュー→統合の順で回答を作ります。UIの標準動作はローカル擬似AIです。
        実Geminiを使う場合は、バックエンドで許可設定した上で「実APIを使う」を有効にします。
      </p>
      <GuideCards items={AI_GUIDES} />

      <QuestionChips onPick={setQuery} />

      <div className="chat-window">
        {messages.map((message, index) => (
          <article key={`${message.role}-${index}`} className={`chat-bubble ${message.role}`}>
            <div className="chat-meta">
              <span>{message.role === "user" ? "You" : "Assistant"}</span>
              {message.meta && <small>{message.meta}</small>}
            </div>
            <div className="response-text">{message.content}</div>
            {message.sources && message.sources.length > 0 && (
              <details>
                <summary>根拠候補 {message.sources.length}件</summary>
                <ul className="source-list">
                  {message.sources.slice(0, 10).map((source, i) => (
                    <li key={source.chunk_id ?? i}>
                      <SourceCite source={source.source} metadata={source.metadata} />
                      <ResultText text={source.text} limit={160} />
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {message.role === "assistant" &&
              message.sources &&
              message.sources.length > 0 && <FeedbackButtons message={message} />}
          </article>
        ))}
      </div>

      <div className="chat-composer">
        <textarea
          rows={4}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              void ask();
            }
          }}
          placeholder="例: NTTとKDDIの配当方針を比較して、減配リスクだけ抽出して"
        />
        <div className="composer-actions">
          <button className="primary" onClick={() => void ask()} disabled={loading || !query.trim()}>
            回答
          </button>
          <button onClick={resetChat} disabled={loading}>
            リセット
          </button>
        </div>
      </div>

      <div className="form compact-form">
        <Field label="RAG DB パス">
          <input value={dbPath} onChange={(e) => setDbPath(e.target.value)} />
        </Field>
        <Field label="対象銘柄/source">
          <select value={targetSource} onChange={(e) => setTargetSource(e.target.value)}>
            {TARGET_SOURCE_OPTIONS.map((option) => (
              <option key={option.label} value={option.source}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="根拠件数">
          <input
            type="number"
            min={1}
            max={50}
            value={evidenceLimit}
            onChange={(e) => setEvidenceLimit(Number(e.target.value))}
          />
        </Field>
        {targetSource && (
          <p className="hint">
            対象source: <span className="mono">{targetSource}</span>
          </p>
        )}
        <Field label="ドラフト数">
          <input
            type="number"
            value={drafts}
            min={1}
            max={5}
            onChange={(e) => setDrafts(Number(e.target.value))}
          />
        </Field>
        <Field label="ハイブリッド検索">
          <input type="checkbox" checked={hybrid} onChange={(e) => setHybrid(e.target.checked)} />
        </Field>
        <Field label="Gemini API KEY（一時入力・保存しない）">
          <input
            type="password"
            value={apiKeyInput}
            onChange={(e) => setApiKeyInput(e.target.value)}
            placeholder="API KEYを入力"
            autoComplete="off"
          />
        </Field>
        <Field label="実APIを使う（バックエンド許可時のみ）">
          <input
            type="checkbox"
            checked={useRealApi}
            onChange={async (e) => {
              const enabled = e.target.checked;
              const result = await api<Json>("/api/runtime/real-api", { enabled, api_key: apiKeyInput.trim() || undefined });
              setUseRealApi(Boolean(result.usable));
              if (!result.usable) {
                setError(result.error ?? "実APIを有効化できませんでした。GEMINI_API_KEYを確認してください。");
              } else {
                setError(null);
              }
            }}
          />
        </Field>
      </div>

      <Status loading={loading} error={error} />
      {lastData?.real_api_note && <p className="callout warn-callout">{lastData.real_api_note}</p>}
      {lastData?.financial_evidence && (
        <div className="callout">
          <b>財務根拠（EDINET公式数値・減配履歴）</b>
          <pre className="evidence-block">{String(lastData.financial_evidence)}</pre>
        </div>
      )}
      {lastData?.orchestration && (
        <div className="callout">
          実行方式: {lastData.orchestration.drafter} → {lastData.orchestration.critic} →{" "}
          {lastData.orchestration.synthesizer} / draft数: {lastData.orchestration.drafts}
          {lastData.target_source && (
            <p className="hint">対象source: {String(lastData.target_source)}</p>
          )}
          {Array.isArray(lastData.perspectives) && (
            <ul>
              {lastData.perspectives.map((p: string, i: number) => (
                <li key={i}>観点{i + 1}: {p}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {lastData && (
        <details className="debug-panel">
          <summary>生成プロセスを確認</summary>
          {lastData.critique && (
            <>
              <h3>レビュー指摘</h3>
              <pre>{lastData.critique.text}</pre>
            </>
          )}
          {Array.isArray(lastData.drafts) && (
            <>
              <h3>ドラフト</h3>
              {lastData.drafts.map((draft: Json, i: number) => (
                <pre key={draft.cache_key ?? i}>{draft.text}</pre>
              ))}
            </>
          )}
          {lastData.generation_process && (
            <>
              <h3>生成プロセス</h3>
              <pre>{JSON.stringify(lastData.generation_process, null, 2)}</pre>
            </>
          )}
          {sourceResults.length > 0 && <p className="hint">根拠候補: {sourceResults.length}件</p>}
        </details>
      )}
    </section>
  );
}

// --- Scoring ---------------------------------------------------------------

const STRATEGY_OPTIONS: { value: string; label: string }[] = [
  { value: "balanced", label: "バランス" },
  { value: "high_yield", label: "高配当重視" },
  { value: "defensive", label: "安定・ディフェンシブ" },
  { value: "growth", label: "増配・成長" },
];

const BREAKDOWN_KEYS = [
  "dividend_level",
  "dividend_trend",
  "dividend_safety",
  "equity_ratio",
  "operating_cf",
];

function ScoreBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, (Number(value) || 0) * 100));
  return (
    <div className="score-bar">
      <i style={{ width: `${pct}%` }} />
    </div>
  );
}

function StockScorePanel() {
  const [strategy, setStrategy] = useState("balanced");
  const [excludeCut, setExcludeCut] = useState(false);
  const [minEquity, setMinEquity] = useState("");
  const [limit, setLimit] = useState(20);
  const { loading, error, data, run } = useAsync<Json>();

  const score = () =>
    run(() =>
      api<Json>("/api/scoring/stocks", {
        strategy,
        exclude_dividend_cut: excludeCut,
        min_equity_ratio: minEquity === "" ? undefined : Number(minEquity),
        limit,
      }),
    );

  const results: Json[] = data?.results ?? [];
  return (
    <div className="subpanel">
      <h3>EDINET銘柄スコア（自動・配当品質）</h3>
      <p className="hint">
        取得済みの財務（配当・減配履歴・自己資本比率・営業CF）から銘柄を自動採点します。手動CSV不要。売買推奨ではありません。
      </p>
      <div className="form">
        <Field label="戦略プリセット">
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            {STRATEGY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="自己資本比率の下限(%)">
          <input
            type="number"
            value={minEquity}
            placeholder="例: 40（任意）"
            onChange={(e) => setMinEquity(e.target.value)}
          />
        </Field>
        <Field label="上位件数">
          <input type="number" value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
        </Field>
        <label className="field check-field">
          <input
            type="checkbox"
            checked={excludeCut}
            onChange={(e) => setExcludeCut(e.target.checked)}
          />
          <span>減配ありを除外</span>
        </label>
        <button className="primary" onClick={score} disabled={loading}>
          採点
        </button>
      </div>
      <Status loading={loading} error={error} />
      {data && data.available === false && (
        <p className="status">{String(data.hint ?? "financials.csv が見つかりません")}</p>
      )}
      {data && data.available !== false && (
        <p className="hint">
          対象 {String(data.count)} / {String(data.universe)} 銘柄（戦略:{" "}
          {String(data.strategy_label)}）
        </p>
      )}
      {results.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>順位</th>
              <th>銘柄</th>
              <th>総合</th>
              <th>内訳（配当/増配/安全/自己資本/CF）</th>
              <th>根拠</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={String(r.ticker)}>
                <td>{r.rank}</td>
                <td>
                  <b>{r.ticker}</b> {r.name}
                </td>
                <td className="mono">
                  {Number(r.total_score).toFixed(3)}
                  <ScoreBar value={Number(r.total_score)} />
                </td>
                <td>
                  <div className="bd-bars">
                    {BREAKDOWN_KEYS.map((k) => (
                      <ScoreBar key={k} value={Number(r.breakdown?.[k] ?? 0)} />
                    ))}
                  </div>
                </td>
                <td className="hint">
                  {Array.isArray(r.rationale) ? r.rationale.join(" / ") : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ScoringTab() {
  const [csv, setCsv] = useState(SAMPLE_CSV);
  const [limit, setLimit] = useState(10);
  const { loading, error, data, run } = useAsync<Json>();

  const rank = () => run(() => api<Json>("/api/scoring/rank", { csv_text: csv, limit }));
  const results: Json[] = data?.results ?? [];
  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Score</p>
          <h2>投資スコアリング</h2>
        </div>
        <span className="badge">EDINET / CSV</span>
      </div>

      <StockScorePanel />

      <div className="subpanel">
        <h3>ファンド/ETF比較（CSV）</h3>
        <p className="hint">経費率・リターン・リスク・分散度を正規化して比較します。売買推奨ではありません。</p>
      <div className="form">
        <Field label="CSV（name,expense_ratio,annual_return,volatility,diversification_score）">
          <textarea rows={6} value={csv} onChange={(e) => setCsv(e.target.value)} />
        </Field>
        <Field label="上位件数">
          <input type="number" value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
        </Field>
        <button className="primary" onClick={rank} disabled={loading}>
          ランキング
        </button>
      </div>
      <Status loading={loading} error={error} />
      {results.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>順位</th>
              <th>名称</th>
              <th>総合</th>
              <th>経費率</th>
              <th>年率</th>
              <th>ボラ</th>
              <th>分散</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.rank}>
                <td>{r.rank}</td>
                <td>{r.name}</td>
                <td>{Number(r.score?.total_score).toFixed(3)}</td>
                <td>{r.metrics?.expense_ratio}</td>
                <td>{r.metrics?.annual_return}</td>
                <td>{r.metrics?.volatility}</td>
                <td>{r.metrics?.diversification_score}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      </div>
    </section>
  );
}

// --- Forecast --------------------------------------------------------------

function ForecastTab() {
  const [space, setSpace] = useState("returns");
  const [maWindows, setMaWindows] = useState("3,6,12");
  const evalState = useAsync<Json>();
  const predictState = useAsync<Json>();

  const parseWindows = () =>
    maWindows
      .split(",")
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n) && n > 0);

  const evaluate = () =>
    evalState.run(() =>
      api<Json>("/api/forecast/evaluate", { space, ma_windows: parseWindows(), include_ml: false }),
    );
  const predict = () =>
    predictState.run(() => api<Json>("/api/forecast/predict", { horizon: 1, space }));

  const models: Json[] = evalState.data?.models ?? [];
  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Forecast</p>
          <h2>アンサンブル予測</h2>
        </div>
        <span className="badge">Backtest</span>
      </div>
      <p className="hint">同梱S&P500サンプルによる統計的推定です。将来リターンの保証ではありません。</p>
      <div className="form">
        <Field label="空間">
          <select value={space} onChange={(e) => setSpace(e.target.value)}>
            <option value="returns">returns（対数リターン・推奨）</option>
            <option value="level">level（価格水準）</option>
          </select>
        </Field>
        <Field label="移動平均ウィンドウ">
          <input value={maWindows} onChange={(e) => setMaWindows(e.target.value)} />
        </Field>
        <button className="primary" onClick={evaluate} disabled={evalState.loading}>
          ウォークフォワード評価
        </button>
        <button onClick={predict} disabled={predictState.loading}>
          翌期予測
        </button>
      </div>
      <Status loading={evalState.loading} error={evalState.error} />
      {predictState.data && (
        <p className="callout">
          翌期アンサンブル予測: <b>{Number(predictState.data.ensemble_forecast?.[0]).toFixed(2)}</b>{" "}
          （直近値 {Number(predictState.data.last_observed).toFixed(2)}）
        </p>
      )}
      {models.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>モデル</th>
              <th>RMSE</th>
              <th>方向的中</th>
              <th>skill(vs naive)</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.name} className={m.name === evalState.data?.best_model ? "best" : ""}>
                <td>{m.name}</td>
                <td>{Number(m.metrics?.rmse).toFixed(2)}</td>
                <td>{Number(m.metrics?.directional_accuracy).toFixed(2)}</td>
                <td>{Number(m.skill_vs_naive).toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// --- Scraping --------------------------------------------------------------

function ScrapeTab() {
  const [name, setName] = useState(SOURCE_PRESETS[0].name);
  const [url, setUrl] = useState(SOURCE_PRESETS[0].url);
  const [outputPath, setOutputPath] = useState(SOURCE_PRESETS[0].output_path);
  const [queryHint, setQueryHint] = useState(SOURCE_PRESETS[0].query_hint);
  const [previewChars, setPreviewChars] = useState(500);
  const [sourcesText, setSourcesText] = useState(SAMPLE_SOURCES);
  const [indexAfterFetch, setIndexAfterFetch] = useState(true);
  const [indexPath, setIndexPath] = useState("local_docs");
  const [dbPath, setDbPath] = useState(DEFAULT_RAG_DB_PATH);
  const [manualTitle, setManualTitle] = useState("手動取込メモ");
  const [manualSourceUrl, setManualSourceUrl] = useState("");
  const [manualText, setManualText] = useState("");
  const [edinetRegistry, setEdinetRegistry] = useState(
    "examples/source_registry_nikkei225_edinet.yaml",
  );
  const [edinetDays, setEdinetDays] = useState(7);
  const [edinetYears, setEdinetYears] = useState(0);
  const sourceState = useAsync<Json>();
  const manualState = useAsync<Json>();
  const edinetState = useAsync<Json>();

  function currentSource() {
    return {
      name,
      url,
      output_path: outputPath,
      query_hint: queryHint,
      extract_text: true,
      include_metadata: true,
      preview_chars: previewChars,
    };
  }

  function applyPreset(preset: SourcePreset) {
    setName(preset.name);
    setUrl(preset.url);
    setOutputPath(preset.output_path);
    setQueryHint(preset.query_hint);
  }

  function addCurrentSource() {
    const source = currentSource();
    setSourcesText((prev) => {
      try {
        const parsed = JSON.parse(prev);
        const list = Array.isArray(parsed) ? parsed : [];
        return JSON.stringify([...list, source], null, 2);
      } catch {
        return JSON.stringify([source], null, 2);
      }
    });
  }

  function parsedSources() {
    const sources = JSON.parse(sourcesText);
    if (!Array.isArray(sources) || sources.length === 0) {
      throw new Error("sources は1件以上のJSON配列にしてください");
    }
    return sources;
  }

  function call(dry: boolean) {
    sourceState.run(async () => {
      const sources = parsedSources();
      return api<Json>(dry ? "/api/fetch-job/dry-run" : "/api/fetch-job/run", { sources });
    });
  }

  function callAuto() {
    sourceState.run(async () => {
      const sources = parsedSources();
      return api<Json>("/api/fetch-job/auto", {
        sources,
        db_path: dbPath,
        index_path: indexPath,
        index_after_fetch: indexAfterFetch,
      });
    });
  }

  function callDisclosureAuto() {
    sourceState.run(async () => {
      const sources = DISCLOSURE_AUTO_SOURCES;
      setSourcesText(JSON.stringify(sources, null, 2));
      return api<Json>("/api/fetch-job/auto", {
        sources,
        db_path: dbPath,
        index_path: "local_docs",
        index_after_fetch: true,
      });
    });
  }

  const runEdinetIngest = () =>
    edinetState.run(() =>
      runJob("/api/edinet/ingest-async", {
        registry_path: edinetRegistry,
        days: edinetDays,
        years: edinetYears > 0 ? edinetYears : undefined,
        db_path: dbPath,
        index_after_fetch: true,
      }),
    );

  const saveManual = () =>
    manualState.run(() =>
      api<Json>("/api/manual-doc/save", {
        title: manualTitle,
        source_url: manualSourceUrl,
        text: manualText,
        db_path: dbPath,
      }),
    );

  const dryResults: Json[] = sourceState.data?.dry_run?.results ?? [];
  const results: Json[] = sourceState.data?.run?.results ?? sourceState.data?.results ?? [];
  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Data Intake</p>
          <h2>自動取得 / 手動取込</h2>
        </div>
        <span className="badge warn">robots確認必須</span>
      </div>

      <GuideCards items={SCRAPE_GUIDES} />

      <div className="workflow">
        <article className="step-card">
          <b>1. 自動取得</b>
          <span>許可確認、取得、保存、RAG登録を一括実行</span>
        </article>
        <article className="step-card">
          <b>2. dry-run</b>
          <span>取得せずrobots.txtのみ確認</span>
        </article>
        <article className="step-card">
          <b>3. 個別取得</b>
          <span>許可済みURLだけ手動で取得</span>
        </article>
        <article className="step-card">
          <b>4. 手動取込</b>
          <span>失敗時は本文を貼り付けて登録</span>
        </article>
      </div>

      <div className="source-builder">
        <h3>自動取得ソースを作る</h3>
        <div className="chips">
          {SOURCE_PRESETS.map((preset) => (
            <button key={preset.name} className="chip" onClick={() => applyPreset(preset)}>
              {preset.label}
            </button>
          ))}
        </div>
        <div className="form">
          <Field label="name">
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="URL">
            <input value={url} onChange={(e) => setUrl(e.target.value)} />
          </Field>
          <Field label="保存先 output_path">
            <input value={outputPath} onChange={(e) => setOutputPath(e.target.value)} />
          </Field>
          <Field label="検索ヒント query_hint">
            <input value={queryHint} onChange={(e) => setQueryHint(e.target.value)} />
          </Field>
          <Field label="preview_chars">
            <input
              type="number"
              value={previewChars}
              onChange={(e) => setPreviewChars(Number(e.target.value))}
            />
          </Field>
          <button onClick={addCurrentSource}>JSONへ追加</button>
        </div>
      </div>

      <div className="form">
        <Field label="sources（JSON配列）">
          <textarea rows={10} value={sourcesText} onChange={(e) => setSourcesText(e.target.value)} />
        </Field>
        <Field label="RAG DB パス">
          <input value={dbPath} onChange={(e) => setDbPath(e.target.value)} />
        </Field>
        <Field label="RAG登録ディレクトリ">
          <input value={indexPath} onChange={(e) => setIndexPath(e.target.value)} />
        </Field>
        <Field label="取得後にRAG登録">
          <input
            type="checkbox"
            checked={indexAfterFetch}
            onChange={(e) => setIndexAfterFetch(e.target.checked)}
          />
        </Field>
        <button className="primary" onClick={callDisclosureAuto} disabled={sourceState.loading}>
          開示資料を一括取得 + RAG登録
        </button>
        <button onClick={callAuto} disabled={sourceState.loading}>
          現在のJSONで自動取得 + RAG登録
        </button>
        <button onClick={() => call(true)} disabled={sourceState.loading}>
          dry-runのみ
        </button>
        <button onClick={() => call(false)} disabled={sourceState.loading}>
          取得のみ
        </button>
      </div>
      <Status loading={sourceState.loading} error={sourceState.error} />

      {sourceState.data?.policy && (
        <div className="callout">
          法令・規約対応: robots確認={String(sourceState.data.policy.robots_checked)} / blocked={" "}
          {sourceState.data.policy.robots_blocked_count} / SSRF対策={String(sourceState.data.policy.ssrf_protection)} / 
          レート制限={String(sourceState.data.policy.rate_limit)} / サイズ制限={String(sourceState.data.policy.response_size_limit)}
        </div>
      )}
      {dryResults.length > 0 && (
        <details className="debug-panel" open>
          <summary>dry-run結果</summary>
          <FetchResultsTable results={dryResults} />
        </details>
      )}
      {results.length > 0 && <FetchResultsTable results={results} />}
      {sourceState.data?.index && (
        <p className="callout">RAG登録完了: {JSON.stringify(sourceState.data.index)}</p>
      )}

      <div className="edinet-ingest">
        <h3>EDINET（公的API）から財務数値を取得</h3>
        <p className="hint">
          金融庁EDINETの公式開示（XBRL/CSV）から営業CF・自己資本比率・配当性向などの数値を取得し、RAGに登録します。
          通常は月曜6時に自動実行されますが、ここから任意のタイミングで実行できます（バックエンドにEDINET_API_KEYが必要）。
        </p>
        <div className="form">
          <Field label="EDINET registry（YAML）">
            <input value={edinetRegistry} onChange={(e) => setEdinetRegistry(e.target.value)} />
          </Field>
          <Field label="遡る日数（提出日のスキャン範囲）">
            <input
              type="number"
              min={1}
              max={31}
              value={edinetDays}
              onChange={(e) => setEdinetDays(Number(e.target.value))}
            />
          </Field>
          <Field label="遡る年数（バックフィル・0で無効）">
            <input
              type="number"
              min={0}
              max={5}
              value={edinetYears}
              onChange={(e) => setEdinetYears(Number(e.target.value))}
            />
          </Field>
          <button
            className="primary"
            onClick={runEdinetIngest}
            disabled={edinetState.loading}
          >
            EDINETから取得 + RAG登録
          </button>
        </div>
        <Status loading={edinetState.loading} error={edinetState.error} />
        {edinetState.data && (
          <div className="callout">
            取得件数: {String(edinetState.data.ingested_count)} / 対象{" "}
            {String(edinetState.data.targets_count)}社（スキャン日数{" "}
            {Array.isArray(edinetState.data.scanned_dates)
              ? edinetState.data.scanned_dates.length
              : 0}
            ）
            {Array.isArray(edinetState.data.results) && edinetState.data.results.length > 0 && (
              <ul className="source-list">
                {edinetState.data.results.map((r: Json, i: number) => (
                  <li key={r.doc_id ?? i}>
                    <span className="mono">
                      {r.ticker} {r.status}
                    </span>
                    {Array.isArray(r.metrics) && r.metrics.length > 0 && (
                      <p>{r.metrics.join(" / ")}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {edinetState.data.index ? (
              <p className="hint">RAG登録完了: {JSON.stringify(edinetState.data.index)}</p>
            ) : null}
            {edinetState.data.comparison &&
              Array.isArray((edinetState.data.comparison as Json).companies) &&
              (edinetState.data.comparison as Json).companies.length > 0 && (
                <EdinetComparisonTable
                  companies={(edinetState.data.comparison as Json).companies as Json[]}
                />
              )}
          </div>
        )}
      </div>

      <div className="manual-ingest">
        <h3>手動テキスト取込</h3>
        <p className="hint">
          自動取得がブロックされたページは、ブラウザで本文をコピーしてここへ貼り付けます。保存とRAG登録を同時に行います。
        </p>
        <div className="form">
          <Field label="タイトル">
            <input value={manualTitle} onChange={(e) => setManualTitle(e.target.value)} />
          </Field>
          <Field label="取得元URL（任意）">
            <input value={manualSourceUrl} onChange={(e) => setManualSourceUrl(e.target.value)} />
          </Field>
          <Field label="本文">
            <textarea rows={8} value={manualText} onChange={(e) => setManualText(e.target.value)} />
          </Field>
          <button className="primary" onClick={saveManual} disabled={manualState.loading || !manualText.trim()}>
            保存してRAG登録
          </button>
        </div>
        <Status loading={manualState.loading} error={manualState.error} />
        {manualState.data && (
          <div className="callout">
            保存先: <span className="mono">{manualState.data.saved_path}</span>
            <br />
            登録チャンク数: {manualState.data.indexed?.chunks_indexed}
          </div>
        )}
      </div>
    </section>
  );
}

const TREND_LABELS: Record<string, string> = {
  increasing: "増加",
  declining: "減少",
  flat: "横ばい",
  mixed: "増減混在",
  insufficient: "データ不足",
};

function trendLabel(value: unknown): string {
  return TREND_LABELS[String(value)] ?? String(value ?? "-");
}

function fmtYen(value: number): string {
  return `¥${value.toLocaleString("ja-JP", { maximumFractionDigits: 2 })}`;
}

function fmtRatio(value: number): string {
  // EDINET reports 自己資本比率 as either a 0–1 ratio or a 0–100 percent.
  const pct = value <= 1 ? value * 100 : value;
  return `${pct.toFixed(1)}%`;
}

// With only one period a trend cannot be computed, so show the single latest
// actual value (marked "1期のみ") instead of an unhelpful "データ不足".
function trendOrSingle(
  trend: unknown,
  latest: unknown,
  fmt: (value: number) => string,
): string {
  if (String(trend) !== "insufficient") return trendLabel(trend);
  if (typeof latest === "number" && Number.isFinite(latest) && latest !== 0) {
    return `${fmt(latest)}（1期のみ）`;
  }
  return "データ不足";
}

function EdinetComparisonTable(props: { companies: Json[] }) {
  return (
    <div className="edinet-comparison">
      <h4>財務トレンド / 減配履歴（EDINET公式データ・機械集計）</h4>
      <table className="grid">
        <thead>
          <tr>
            <th>銘柄</th>
            <th>期数</th>
            <th>配当推移</th>
            <th>減配年</th>
            <th>営業CF推移</th>
            <th>自己資本比率推移</th>
          </tr>
        </thead>
        <tbody>
          {props.companies.map((c, i) => {
            const cuts = Array.isArray(c.dividend_cut_years) ? c.dividend_cut_years : [];
            const years = Array.isArray(c.years) ? c.years.length : 0;
            return (
              <tr key={c.ticker ?? i}>
                <td className="mono">
                  {c.ticker} {c.name}
                </td>
                <td>{years}</td>
                <td>{trendOrSingle(c.dividend_trend, c.latest_dividend_per_share, fmtYen)}</td>
                <td>{cuts.length > 0 ? cuts.join(", ") : "なし"}</td>
                <td>{trendOrSingle(c.operating_cf_trend, c.latest_operating_cf, fmtYen)}</td>
                <td>{trendOrSingle(c.equity_ratio_trend, c.latest_equity_ratio, fmtRatio)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="hint">
        減配履歴・トレンドは取得済みの複数期から機械的に算出したものです。1期のみの銘柄は最新の実数値（「1期のみ」）を表示します。投資助言ではありません。
      </p>
    </div>
  );
}

function FetchResultsTable(props: { results: Json[] }) {
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>name</th>
          <th>allowed</th>
          <th>source</th>
          <th>status</th>
          <th>saved</th>
        </tr>
      </thead>
      <tbody>
        {props.results.map((r, i) => (
          <tr key={i}>
            <td>{r.name}</td>
            <td>{String(r.fetch?.allowed_by_robots)}</td>
            <td className="mono">{r.fetch?.source}</td>
            <td>{r.fetch?.status_code ?? "-"}</td>
            <td className="mono">{r.fetch?.saved_path ?? "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// --- Budget / cache --------------------------------------------------------

function diffVal(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

function ChangeChip({ change }: { change: Json }) {
  const field = String(change.field ?? "");
  const from = change.from;
  const to = change.to;
  let tone = "";
  if (field === "1株配当" && typeof from === "number" && typeof to === "number") {
    tone = to < from ? " neg" : to > from ? " pos" : "";
  }
  if (field === "新規減配年") tone = " neg";
  const body =
    from !== undefined && from !== null ? `${diffVal(from)} → ${diffVal(to)}` : diffVal(to);
  return (
    <span className={`diff-chip${tone}`}>
      <b>{field}</b> {body}
    </span>
  );
}

function AnalysisTab() {
  const [dbPath, setDbPath] = useState(DEFAULT_RAG_DB_PATH);
  const state = useAsync<Json>();
  const analyze = () => state.run(() => api<Json>("/api/knowledge/diff", { db_path: dbPath }));
  useEffect(() => {
    void analyze();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const data = state.data;
  const snap: Json = data?.snapshot ?? {};
  const rag: Json = snap.rag ?? {};
  const fin: Json = snap.financials ?? {};
  const diff: Json = data?.diff ?? {};
  const ragDiff: Json = diff.rag ?? {};
  const changes: Json[] = Array.isArray(diff.financial_changes) ? diff.financial_changes : [];
  const newSources: string[] = Array.isArray(ragDiff.new_sources) ? ragDiff.new_sources : [];

  const delta = (n: unknown) => {
    const v = Number(n ?? 0);
    if (!v) return null;
    return <small className={v > 0 ? "delta up" : "delta down"}>{v > 0 ? `+${v}` : v}</small>;
  };

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Context</p>
          <h2>コンテキスト解析</h2>
        </div>
        <span className="badge">差分</span>
      </div>
      <p className="hint">
        RAG・財務知識のスナップショットを取り、前回からの差分（学習の更新）を可視化します。
      </p>
      <div className="form compact-form">
        <label className="field">
          <span>RAG DBパス</span>
          <input value={dbPath} onChange={(e) => setDbPath(e.target.value)} />
        </label>
        <button className="primary" onClick={() => void analyze()} disabled={state.loading}>
          解析
        </button>
      </div>
      <Status loading={state.loading} error={state.error} />

      {data && (
        <>
          <section className="metric-grid">
            <article className="metric-card accent">
              <span>RAGソース</span>
              <b>
                {String(rag.sources ?? 0)} {delta(ragDiff.sources_delta)}
              </b>
            </article>
            <article className="metric-card accent">
              <span>チャンク</span>
              <b>
                {String(rag.chunks ?? 0)} {delta(ragDiff.chunks_delta)}
              </b>
            </article>
            <article className="metric-card">
              <span>追跡銘柄</span>
              <b>{Object.keys(fin).length}</b>
            </article>
            <article className="metric-card">
              <span>変化銘柄</span>
              <b>{changes.length}</b>
            </article>
          </section>

          {data.previous_at
            ? !diff.has_changes && (
                <p className="status">前回スナップショットから変化はありません。</p>
              )
            : (
                <p className="hint">
                  初回スナップショットを保存しました。次回以降の解析で差分を表示します。
                </p>
              )}

          {newSources.length > 0 && (
            <div className="diff-block">
              <b>🆕 新規ソース（{newSources.length}）</b>
              <ul className="kv">
                {newSources.slice(0, 12).map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          )}

          {changes.length > 0 && (
            <div className="diff-block">
              <b>💴 財務・配当の変化（{changes.length}）</b>
              <div className="diff-list">
                {changes.map((c) => (
                  <article className="diff-card" key={String(c.ticker)}>
                    <header className="diff-card-head">
                      <b>
                        {String(c.ticker)} {String(c.name ?? "")}
                      </b>
                      {c.kind === "new" && <span className="badge safe">新規</span>}
                    </header>
                    <div className="diff-chips">
                      {(Array.isArray(c.changes) ? c.changes : []).map(
                        (ch: Json, i: number) => (
                          <ChangeChip change={ch} key={i} />
                        ),
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

// --- Dividend portfolio simulator ------------------------------------------

function yen(value: unknown): string {
  return `${Math.round(Number(value) || 0).toLocaleString()}円`;
}

function formatDateTime(value: unknown): string {
  const date = new Date(String(value ?? ""));
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatHistoryValue(value: unknown, valueFormat: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  const format = String(valueFormat ?? "");
  if (format === "text") return String(value);
  if (format === "percent") {
    return `${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
  }
  if (format === "yen") return yen(value);
  if (typeof value === "number") {
    return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}

function formatHistoryDelta(metric: Json): string {
  const delta = metric.delta;
  if (delta === null || delta === undefined) {
    return metric.changed ? "changed" : "-";
  }
  const value = formatHistoryValue(delta, metric.value_format);
  const pct = metric.delta_pct;
  if (pct === null || pct === undefined) return value;
  return `${value} (${Number(pct).toLocaleString(undefined, { maximumFractionDigits: 2 })}%)`;
}

function formatKpiValue(kpi: Json): string {
  const value = kpi.value;
  if (value === null || value === undefined || value === "") return "-";
  const format = String(kpi.value_format ?? "");
  if (format === "text") return String(value);
  if (format === "percent") {
    return `${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
  }
  if (format === "number") {
    return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  if (format === "yen" || typeof value === "number") return yen(value);
  return String(value);
}

const WEIGHT_MODES: { value: string; label: string }[] = [
  { value: "equal", label: "均等" },
  { value: "safety", label: "安全性比例" },
  { value: "amount", label: "投資額（手動）" },
  { value: "shares", label: "株数（手動）" },
];

const OPTIMIZE_MODES: { value: string; label: string }[] = [
  { value: "none", label: "なし（重み付けに従う）" },
  { value: "cash_min", label: "余り最小（予算を使い切る）" },
  { value: "dividend_max", label: "配当最大（利回り重視）" },
  { value: "balanced", label: "バランス（配当×安全性）" },
];

type Holding = { ticker: string; name: string; price: number; shares: number; amount: number; nisa: boolean };

function MultiLineChart({
  series,
  band,
}: {
  series: { label: string; values: number[]; color: string }[];
  band?: { lower: number[]; upper: number[] };
}) {
  const w = 540;
  const h = 210;
  const pad = 30;
  const n = Math.max(...series.map((s) => s.values.length), band?.upper.length ?? 0, 1);
  const max = Math.max(...series.flatMap((s) => s.values), ...(band?.upper ?? []), 1);
  const xs = (i: number) => pad + ((w - pad * 2) * i) / Math.max(n - 1, 1);
  const ys = (v: number) => h - pad - (v / max) * (h - pad * 2);
  let areaPts = "";
  if (band && band.upper.length > 0) {
    const up = band.upper.map((v, i) => `${xs(i)},${ys(v)}`);
    const lo = band.lower.map((v, i) => `${xs(i)},${ys(v)}`).reverse();
    areaPts = up.concat(lo).join(" ");
  }
  return (
    <div>
      <svg className="area-chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="配当推移">
        {[0, 0.5, 1].map((t) => {
          const y = pad + t * (h - pad * 2);
          return <line key={t} x1={pad} y1={y} x2={w - pad} y2={y} stroke="var(--line)" strokeOpacity="0.5" />;
        })}
        {areaPts && <polygon points={areaPts} fill="rgba(245,158,11,0.13)" stroke="none" />}
        {series.map((s) => (
          <polyline
            key={s.label}
            points={s.values.map((v, i) => `${xs(i)},${ys(v)}`).join(" ")}
            fill="none"
            stroke={s.color}
            strokeWidth="2.5"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
      </svg>
      <div className="chart-legend">
        {band && (
          <span>
            <i style={{ background: "rgba(245,158,11,0.5)" }} />
            配当ボリンジャー帯
          </span>
        )}
        {series.map((s) => (
          <span key={s.label}>
            <i style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function Heatmap({ surface }: { surface: Json }) {
  const yields: number[] = surface?.yields ?? [];
  const years: number[] = surface?.years ?? [];
  const z: number[][] = surface?.z ?? [];
  const max = Math.max(...z.flat(), 1);
  return (
    <table className="grid heat">
      <thead>
        <tr>
          <th>利回り＼年</th>
          {years.map((y) => (
            <th key={y}>{y}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {yields.map((yl, ri) => (
          <tr key={yl}>
            <th>{Math.round(yl * 100)}%</th>
            {(z[ri] ?? []).map((v, ci) => (
              <td key={ci} className="heat-cell" style={{ background: `rgba(56,189,248,${Math.min(0.85, v / max)})` }} title={yen(v)} />
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SimulateTab() {
  const [budget, setBudget] = useState(1000000);
  const [years, setYears] = useState(10);
  const [growth, setGrowth] = useState(0);
  const [reinvest, setReinvest] = useState(true);
  const [weightMode, setWeightMode] = useState("equal");
  const [optimizeMode, setOptimizeMode] = useState("none");
  const [targetDividend, setTargetDividend] = useState(0);
  const [netTarget, setNetTarget] = useState(true);
  const [universe, setUniverse] = useState<Json[]>([]);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [pick, setPick] = useState("");
  const [busy, setBusy] = useState(false);
  const [priceProvider, setPriceProvider] = useState("stooq_public_csv");
  const { loading, error, data, run } = useAsync<Json>();

  useEffect(() => {
    api<Json>("/api/portfolio/universe", {})
      .then((r) => setUniverse(Array.isArray(r.universe) ? r.universe : []))
      .catch(() => setUniverse([]));
  }, []);

  const addHolding = () => {
    const u = universe.find((x) => String(x.ticker) === pick);
    if (!u || holdings.some((h) => h.ticker === String(u.ticker))) return;
    setHoldings([
      ...holdings,
      { ticker: String(u.ticker), name: String(u.name ?? ""), price: Number(u.price) || 0, shares: 100, amount: 100000, nisa: false },
    ]);
  };
  const patch = (i: number, p: Partial<Holding>) =>
    setHoldings(holdings.map((h, idx) => (idx === i ? { ...h, ...p } : h)));
  const removeAt = (i: number) => setHoldings(holdings.filter((_, idx) => idx !== i));

  const fetchPrices = async (tickers: string[]): Promise<Record<string, number | null>> => {
    const r = await api<Json>("/api/market/prices", { tickers, provider_id: priceProvider });
    return (r.prices ?? {}) as Record<string, number | null>;
  };

  const updatePrices = async () => {
    if (holdings.length === 0) return;
    setBusy(true);
    try {
      const pm = await fetchPrices(holdings.map((h) => h.ticker));
      setHoldings((hs) => hs.map((h) => (pm[h.ticker] != null ? { ...h, price: Number(pm[h.ticker]) } : h)));
    } catch {
      /* leave prices as-is */
    } finally {
      setBusy(false);
    }
  };

  const simulate = () =>
    run(() =>
      api<Json>("/api/portfolio/simulate", {
        budget,
        years,
        growth_rate: growth / 100,
        reinvest,
        auto_weight: weightMode,
        optimization: optimizeMode,
        dividend_basis: "conservative",
        holdings: holdings.map((h) => ({ ticker: h.ticker, price: h.price, shares: h.shares, amount: h.amount, nisa: h.nisa })),
      }),
    );

  const planTarget = () =>
    run(() =>
      api<Json>("/api/portfolio/target", {
        target_annual_dividend: targetDividend,
        net_target: netTarget,
        years,
        growth_rate: growth / 100,
        reinvest,
        auto_weight: weightMode,
        optimization: optimizeMode,
        dividend_basis: "conservative",
        holdings: holdings.map((h) => ({ ticker: h.ticker, price: h.price, shares: h.shares, amount: h.amount, nisa: h.nisa })),
      }),
    );

  const summary: Json = data?.summary ?? {};
  const target: Json | null = (data?.target as Json) ?? null;
  const concentration: Json = (summary.concentration as Json) ?? {};
  const allocations: Json[] = data?.allocations ?? [];
  const projection: Json = data?.projection ?? {};
  const showShares = weightMode === "shares";
  const showAmount = weightMode === "amount";

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Simulate</p>
          <h2>配当ポートフォリオ シミュレーション</h2>
        </div>
        <span className="badge">参考・非助言</span>
      </div>
      <p className="hint">
        EDINETの銘柄リストからユーザーが選び、市場株価または手入力価格で年間配当を試算します。
        配当はボリンジャー下限で安全側に見積もります。将来を保証しない参考値です。
      </p>

      <div className="form">
        <Field label="投資予算(円)">
          <input type="number" value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
        </Field>
        <Field label="年数">
          <input type="number" value={years} onChange={(e) => setYears(Number(e.target.value))} />
        </Field>
        <Field label="配当成長率(%/年)">
          <input type="number" value={growth} onChange={(e) => setGrowth(Number(e.target.value))} />
        </Field>
        <Field label="重み付け">
          <select value={weightMode} onChange={(e) => setWeightMode(e.target.value)}>
            {WEIGHT_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="最適化（予算配分）">
          <select
            value={optimizeMode}
            onChange={(e) => setOptimizeMode(e.target.value)}
            disabled={showShares || showAmount}
          >
            {OPTIMIZE_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <label className="field check-field">
          <input type="checkbox" checked={reinvest} onChange={(e) => setReinvest(e.target.checked)} />
          <span>配当を再投資</span>
        </label>
      </div>

      <div className="form">
        <Field label="銘柄を選択（EDINET・安全性順）">
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">― 選択 ―</option>
            {universe.map((u) => (
              <option key={String(u.ticker)} value={String(u.ticker)}>
                {String(u.ticker)} {String(u.name ?? "")}（安全性 {Number(u.safety).toFixed(2)}）
              </option>
            ))}
          </select>
        </Field>
        <button onClick={addHolding} disabled={!pick}>
          ＋ 追加（手動）
        </button>
        <Field label="価格ソース">
          <select value={priceProvider} onChange={(e) => setPriceProvider(e.target.value)}>
            <option value="stooq_public_csv">Stooq</option>
            <option value="yfinance">Yahoo!ファイナンス</option>
          </select>
        </Field>
        <button onClick={() => void updatePrices()} disabled={busy || holdings.length === 0}>
          市場価格を更新
        </button>
      </div>

      <MarketDataPanel
        holdingsTickers={holdings.map((h) => h.ticker)}
        onApplyPrices={(pm) =>
          setHoldings((hs) =>
            hs.map((h) => {
              const p = pm[h.ticker];
              return p != null ? { ...h, price: p } : h;
            }),
          )
        }
      />

      {holdings.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>銘柄</th>
              <th>株価</th>
              {showShares && <th>株数</th>}
              {showAmount && <th>投資額</th>}
              <th>NISA</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h, i) => (
              <tr key={h.ticker}>
                <td>
                  <b>{h.ticker}</b> {h.name}
                </td>
                <td>
                  <input type="number" value={h.price} onChange={(e) => patch(i, { price: Number(e.target.value) })} />
                </td>
                {showShares && (
                  <td>
                    <input type="number" value={h.shares} onChange={(e) => patch(i, { shares: Number(e.target.value) })} />
                  </td>
                )}
                {showAmount && (
                  <td>
                    <input type="number" value={h.amount} onChange={(e) => patch(i, { amount: Number(e.target.value) })} />
                  </td>
                )}
                <td>
                  <input
                    type="checkbox"
                    checked={h.nisa}
                    onChange={(e) => patch(i, { nisa: e.target.checked })}
                    title="NISA口座（非課税）として計算"
                  />
                </td>
                <td>
                  <button onClick={() => removeAt(i)}>削除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="form">
        <button className="primary" onClick={simulate} disabled={loading || holdings.length === 0}>
          予算から作成
        </button>
        <Field label="目標 年間配当(円)">
          <input
            type="number"
            value={targetDividend}
            onChange={(e) => setTargetDividend(Number(e.target.value))}
            placeholder="例: 600000"
          />
        </Field>
        <label className="field check-field">
          <input type="checkbox" checked={netTarget} onChange={(e) => setNetTarget(e.target.checked)} />
          <span>手取り（税引後）で指定</span>
        </label>
        <button
          onClick={planTarget}
          disabled={loading || holdings.length === 0 || targetDividend <= 0}
          title="目標の年間配当に必要な予算とポートフォリオを逆算します"
        >
          目標から逆算
        </button>
      </div>

      <Status loading={loading} error={error} />
      {data && target && (
        <p className={`status ${target.reachable ? "" : "warn-text"}`}>
          {target.reachable
            ? `目標 ${yen(target.target_annual_dividend)}/年${target.net_target ? "（手取り）" : ""} → 必要予算 約${yen(target.required_budget)}（達成見込み 手取り${yen(target.achieved_annual_dividend_net)}/年・安全側）`
            : String(data.hint ?? "目標に到達できませんでした。")}
        </p>
      )}
      {busy && <p className="status">市場価格を取得中…</p>}
      {data && data.available === false && <p className="status">{String(data.hint)}</p>}

      {data && data.available !== false && (
        <>
          <section className="metric-grid">
            <article className="metric-card accent">
              <span>投資額 / 残現金</span>
              <b>{yen(summary.invested)}</b>
              <small>残 {yen(summary.cash_left)}</small>
            </article>
            <article className="metric-card pos">
              <span>年間配当（安全側）</span>
              <b>{yen(summary.annual_dividend)}</b>
              <small>名目 {yen(summary.annual_dividend_latest)}</small>
            </article>
            <article className="metric-card pos">
              <span>手取り配当（税引後）</span>
              <b>{yen(summary.annual_dividend_net)}</b>
              <small>税 {yen(summary.dividend_tax)}（20.315%・NISA除く）</small>
            </article>
            <article className="metric-card accent">
              <span>利回り（安全側）</span>
              <b>{(Number(summary.portfolio_yield) * 100).toFixed(2)}%</b>
              <small>名目 {(Number(summary.portfolio_yield_latest) * 100).toFixed(2)}%</small>
            </article>
            <article className="metric-card warn">
              <span>配当レンジ(ボリンジャー)</span>
              <b>{yen(summary.annual_band_lower)}</b>
              <small>〜 {yen(summary.annual_band_upper)}</small>
            </article>
            <article className={`metric-card ${Number(concentration.top_weight) >= 0.5 ? "warn" : "accent"}`}>
              <span>集中度（最大銘柄）</span>
              <b>{(Number(concentration.top_weight) * 100).toFixed(0)}%</b>
              <small>
                {String(concentration.top_ticker ?? "—")}・実効{Number(concentration.effective_names).toFixed(1)}銘柄
                {Number(concentration.top_weight) >= 0.5 ? "・偏り大" : ""}
              </small>
            </article>
          </section>

          {allocations.length > 0 && (
            <table className="grid">
              <thead>
                <tr>
                  <th>銘柄</th>
                  <th>株価</th>
                  <th>株数</th>
                  <th>投資額</th>
                  <th>年配当(安全側)</th>
                  <th>利回り</th>
                  <th>安全性</th>
                </tr>
              </thead>
              <tbody>
                {allocations.map((a) => (
                  <tr key={String(a.ticker)}>
                    <td>
                      <b>{a.ticker}</b> {a.name}
                    </td>
                    <td className="mono">{yen(a.price)}</td>
                    <td className="mono">{String(a.shares)}</td>
                    <td className="mono">{yen(a.invested)}</td>
                    <td className="mono">{yen(a.annual_dividend)}</td>
                    <td className="mono">{(Number(a.yield) * 100).toFixed(2)}%</td>
                    <td className="mono">{(Number(a.safety) * 100).toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="guide-card chart-card chart-card-wide">
            <b>配当推移の予測（ボリンジャー帯・参考）</b>
            <MultiLineChart
              series={[
                { label: "名目", values: projection.nominal ?? [], color: "var(--accent)" },
                { label: "安全側(下限基準)", values: projection.conservative ?? [], color: "var(--warn)" },
                { label: "再投資スノーボール", values: projection.reinvested ?? [], color: "var(--safe)" },
              ]}
              band={{ lower: projection.band_lower ?? [], upper: projection.band_upper ?? [] }}
            />
          </div>

          <div className="guide-card chart-card chart-card-wide">
            <b>累積配当のヒートマップ（年数 × 利回り・再投資・参考）</b>
            <Heatmap surface={data.surface} />
          </div>

          {data.disclaimer && <p className="hint">{String(data.disclaimer)}</p>}
        </>
      )}
    </section>
  );
}

function OpsTab() {
  const budget = useAsync<Json>();
  const cache = useAsync<Json>();
  useEffect(() => {
    budget.run(() => api<Json>("/api/budget"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Ops</p>
          <h2>予算 / キャッシュ</h2>
        </div>
        <span className="badge">Maintenance</span>
      </div>
      <Status loading={budget.loading} error={budget.error} />
      {budget.data && (
        <ul className="kv">
          <li>モデル: {budget.data.model}</li>
          <li>
            日次: {budget.data.daily_used} / {budget.data.hard_daily_limit}
          </li>
          <li>
            月次: {budget.data.monthly_used} / {budget.data.hard_monthly_limit}
          </li>
          <li>警告: {String(budget.data.warning)}</li>
        </ul>
      )}
      <div className="form">
        <button onClick={() => cache.run(() => api<Json>("/api/cache/maintenance", { max_rows: 1000 }))}>
          キャッシュ整理（期限切れ削除＋上限1000）
        </button>
      </div>
      <Status loading={cache.loading} error={cache.error} />
      {cache.data && <pre>{JSON.stringify(cache.data, null, 2)}</pre>}
    </section>
  );
}

// Kept out of the MVP navigation. These legacy tools remain importable for
// local experiments while the product surface stays investment-only and non-advisory.
export const LEGACY_TOOL_TABS = {
  answer: AnswerTab,
  scoring: ScoringTab,
  forecast: ForecastTab,
  scrape: ScrapeTab,
  analysis: AnalysisTab,
  ops: OpsTab,
} as const;
