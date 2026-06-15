import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import { api } from "./api";
import { DashboardTab } from "./DashboardTab";

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
const FINANCIALS_CSV_STORAGE_KEY =
  "investment_assistant.financials_csv_path.v1";
const AI_CHAT_TARGET_SOURCE_STORAGE_KEY =
  "investment_assistant.ai_chat.target_source.v1";
const AI_CHAT_SELECTED_TICKER_STORAGE_KEY =
  "investment_assistant.ai_chat.selected_ticker.v1";
const AI_CHAT_SELECTED_SECURITY_NAME_STORAGE_KEY =
  "investment_assistant.ai_chat.selected_security_name.v1";

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
  { id: "dashboard", label: "概要" },
  { id: "data", label: "データ" },
  { id: "holdings", label: "保有" },
  { id: "candidates", label: "候補" },
  { id: "simulate", label: "試算" },
  { id: "report", label: "レポート" },
  { id: "detail", label: "詳細" },
  { id: "answer", label: "AIチャット" },
  { id: "evidence", label: "根拠" },
] as const;

const HERO_CARDS = [
  { label: "1", value: "データ", desc: "財務・市場区分を準備" },
  { label: "2", value: "保有", desc: "評価額・損益・NISAを確認" },
  { label: "3", value: "候補", desc: "条件に合う対象を比較" },
  { label: "4", value: "出力", desc: "試算と根拠を残す" },
] as const;

const WORKFLOW_STEPS = [
  {
    id: "data",
    step: "1",
    title: "データ",
    body: "EDINET、CSV、サンプルを選びます。",
    action: "開く",
  },
  {
    id: "holdings",
    step: "2",
    title: "保有",
    body: "保有一覧を入れて集計します。",
    action: "開く",
  },
  {
    id: "candidates",
    step: "3",
    title: "候補",
    body: "条件に合う対象だけを表示します。",
    action: "開く",
  },
  {
    id: "simulate",
    step: "4",
    title: "試算",
    body: "配当・分配金の見込みを見ます。",
    action: "開く",
  },
  {
    id: "report",
    step: "5",
    title: "レポート",
    body: "KPI、計算式、根拠をまとめます。",
    action: "開く",
  },
  {
    id: "answer",
    step: "6",
    title: "AIチャット",
    body: "根拠付きで疑問を整理します。",
    action: "開く",
  },
] satisfies {
  id: TabId;
  step: string;
  title: string;
  body: string;
  action: string;
}[];

const REPORT_WIZARD_STEPS = [
  {
    id: "data",
    step: "1",
    title: "データ確認",
    body: "使う財務データと入力データを確認します。",
  },
  {
    id: "holdings",
    step: "2",
    title: "保有確認",
    body: "保有データを検証し、分析対象を固めます。",
  },
  {
    id: "candidates",
    step: "3",
    title: "候補条件",
    body: "候補抽出に使う条件と投信データを確認します。",
  },
  {
    id: "target",
    step: "4",
    title: "目標配当",
    body: "任意の目標年間配当から必要予算を逆算します。",
  },
  {
    id: "preview",
    step: "5",
    title: "プレビュー",
    body: "生成、KPI、根拠、公開前監査を確認します。",
  },
  {
    id: "export",
    step: "6",
    title: "保存",
    body: "履歴、比較、Markdownを扱います。",
  },
] as const;

type ReportWizardStepId = (typeof REPORT_WIZARD_STEPS)[number]["id"];

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
    title: "1. 根拠を探す",
    body: "登録済み資料から関連箇所を探します。",
  },
  {
    title: "2. 観点を分ける",
    body: "配当、リスク、分散を分けて確認します。",
  },
  {
    title: "3. 確認してまとめる",
    body: "根拠不足や引用漏れを確認してまとめます。",
  },
  {
    title: "4. 実APIは任意",
    body: "標準はローカル動作です。Gemini利用は明示設定時だけです。",
  },
];

const SCRAPE_GUIDES: GuideCard[] = [
  {
    title: "自動取得",
    body: "robots.txt確認、URL安全性確認、レート制限、HTMLテキスト化、保存、RAG登録をまとめて実行します。",
  },
  {
    title: "事前確認",
    body: "本文取得前に、取得可能かだけ確認します。",
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
const DEFAULT_FINANCIALS_PATH = "local_docs/edinet/financials.csv";
const SAMPLE_FINANCIALS_CSV =
  "ticker,name,fiscal_year,operating_cf,equity_ratio,dividend_per_share,payout_policy\n" +
  "7203,安定配当ホールディングス,2021,820000,58.2,42,連結配当性向30%目安・累進配当を志向\n" +
  "7203,安定配当ホールディングス,2022,910000,59.1,46,連結配当性向30%目安・累進配当を志向\n" +
  "7203,安定配当ホールディングス,2023,985000,60.4,52,連結配当性向30%目安・累進配当を志向\n" +
  "7203,安定配当ホールディングス,2024,1040000,61.0,58,連結配当性向30%目安・累進配当を志向\n" +
  "7203,安定配当ホールディングス,2025,1105000,62.3,64,連結配当性向30%目安・累進配当を志向\n" +
  "9999,景気連動マテリアル,2021,310000,38.5,80,業績連動・配当性向40%（下限なし）\n" +
  "9999,景気連動マテリアル,2022,420000,41.2,100,業績連動・配当性向40%（下限なし）\n" +
  "9999,景気連動マテリアル,2023,150000,36.8,40,業績連動・配当性向40%（下限なし）\n" +
  "9999,景気連動マテリアル,2024,260000,39.0,55,業績連動・配当性向40%（下限なし）\n" +
  "9999,景気連動マテリアル,2025,180000,37.4,45,業績連動・配当性向40%（下限なし）\n";

const SAMPLE_JPX_LISTED_ISSUES_DATA =
  "日付,コード,銘柄名,市場・商品区分,33業種区分\n" +
  "2026-05-31,7203,トヨタ自動車,プライム（国内株式）,輸送用機器\n" +
  "2026-05-31,8306,三菱ＵＦＪフィナンシャル・グループ,プライム（国内株式）,銀行業\n" +
  "2026-05-31,9999,サンプルスタンダード,スタンダード（国内株式）,サービス業\n";

const MARKET_SCOPE_OPTIONS = [
  { value: "prime", label: "東証プライム" },
  { value: "nikkei225", label: "日経225" },
  { value: "financials", label: "財務データあり" },
  { value: "all", label: "全件" },
] as const;

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
  const [financialsCsvPath, setFinancialsCsvPath] = useState(() =>
    readLocalStorageString(FINANCIALS_CSV_STORAGE_KEY, DEFAULT_FINANCIALS_PATH),
  );
  const [financialsRefreshNonce, setFinancialsRefreshNonce] = useState(0);
  const [detailSeed, setDetailSeed] = useState<DetailSeed>({
    code: "7203",
    assetType: "stock",
    nonce: 0,
  });
  const openDetail = (code: string, assetType: string) => {
    setDetailSeed({ code, assetType, nonce: Date.now() });
    setTab("detail");
  };
  const markFinancialsDataUpdated = () => {
    setFinancialsRefreshNonce((value) => value + 1);
  };
  useEffect(() => {
    writeLocalStorageString(FINANCIALS_CSV_STORAGE_KEY, financialsCsvPath);
  }, [financialsCsvPath]);
  return (
    <div className="app">
      <header className="terminal-hero">
        <div className="hero-copy">
          <p className="eyebrow">投資支援ツール</p>
          <h1>投資アシスタント</h1>
          <p className="hero-lead">
            日本株と投信のデータ準備、保有分析、候補比較、試算、レポートを順番に進めます。
            断定的な推奨や自動売買は行いません。
          </p>
        </div>
        <div className="hero-badges">
          <span className="badge safe">非助言</span>
          <span className="badge">日本株 + 投信</span>
          <span className="badge">EDINET / CSV</span>
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

      <nav className="tabs" aria-label="主要ナビゲーション">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={t.id === tab ? "tab active" : "tab"}
            aria-current={t.id === tab ? "page" : undefined}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <FinancialsSourceBar
        value={financialsCsvPath}
        onChange={setFinancialsCsvPath}
        onOpenData={() => setTab("data")}
        onDataUpdated={markFinancialsDataUpdated}
        refreshKey={financialsRefreshNonce}
      />
      <section className="top-security-picker" aria-label="証券コードと企業選択">
        <SecuritySearch
          financialsCsvPath={financialsCsvPath}
          title="証券コード・企業を選択"
          onUseSample={() => setFinancialsCsvPath(SAMPLE_FINANCIALS_PATH)}
          onOpenData={() => setTab("data")}
          onSelect={(security) =>
            openDetail(String(security.ticker ?? security.code ?? ""), "stock")
          }
        />
      </section>
      <section className="workflow quick-workflow" aria-label="操作ステップ">
        {WORKFLOW_STEPS.map((step) => (
          <button
            key={step.id}
            className={step.id === tab ? "step-card active" : "step-card"}
            onClick={() => setTab(step.id)}
          >
            <span className="step-number">{step.step}</span>
            <b>{step.title}</b>
            <span>{step.body}</span>
            <small>{step.action}</small>
          </button>
        ))}
      </section>
      <main className="panel">
        {tab === "dashboard" && <DashboardTab />}
        {tab === "holdings" && (
          <HoldingsTab
            financialsCsvPath={financialsCsvPath}
            onFinancialsCsvPathChange={setFinancialsCsvPath}
            onOpenData={() => setTab("data")}
          />
        )}
        {tab === "candidates" && (
          <CandidateScreenTab
            financialsCsvPath={financialsCsvPath}
            onOpenDetail={openDetail}
          />
        )}
        {tab === "detail" && (
          <InvestmentDetailTab
            seed={detailSeed}
            financialsCsvPath={financialsCsvPath}
            onFinancialsCsvPathChange={setFinancialsCsvPath}
            onOpenData={() => setTab("data")}
          />
        )}
        {tab === "simulate" && (
          <SimulateTab
            financialsCsvPath={financialsCsvPath}
            onFinancialsCsvPathChange={setFinancialsCsvPath}
            onOpenData={() => setTab("data")}
          />
        )}
        {tab === "report" && <InvestmentReportTab financialsCsvPath={financialsCsvPath} />}
        {tab === "answer" && (
          <AnswerTab
            financialsCsvPath={financialsCsvPath}
            onFinancialsCsvPathChange={setFinancialsCsvPath}
            onOpenData={() => setTab("data")}
          />
        )}
        {tab === "data" && (
          <ScrapeTab
            financialsCsvPath={financialsCsvPath}
            onFinancialsCsvPathChange={setFinancialsCsvPath}
            onFinancialsDataUpdated={markFinancialsDataUpdated}
          />
        )}
        {tab === "evidence" && <SearchTab />}
      </main>
      <footer className="footer">
        本ツールは投資助言ではありません。表示内容は比較材料であり、最終的な投資判断はユーザー本人が行います。
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

function readLocalStorageString(key: string, fallback = ""): string {
  if (typeof window === "undefined") return fallback;
  try {
    const value = window.localStorage.getItem(key);
    return value && value.trim() ? value : fallback;
  } catch {
    return fallback;
  }
}

function writeLocalStorageString(key: string, value: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    if (value.trim()) {
      window.localStorage.setItem(key, value);
    } else {
      window.localStorage.removeItem(key);
    }
    return true;
  } catch {
    return false;
  }
}

function FinancialsSourceBar(props: {
  value: string;
  onChange: (value: string) => void;
  onOpenData: () => void;
  onDataUpdated: () => void;
  refreshKey: number;
}) {
  const statusState = useAsync<Json>();
  const updateState = useAsync<Json>();
  const refreshStatus = () =>
    statusState.run(() =>
      api<Json>("/api/financials/status", {
        path: props.value,
        stale_after_days: 7,
      }),
    );
  const runOneClickUpdate = () =>
    updateState.run(async () => {
      const result = await runJob("/api/financials/refresh-async", {
        registry_path: "examples/source_registry_nikkei225_edinet.yaml",
        days: 7,
        output_dir: "local_docs/edinet",
        db_path: DEFAULT_RAG_DB_PATH,
        index_after_fetch: true,
      });
      const csvPath = String(result.financials_csv ?? "local_docs/edinet/financials.csv");
      if (result.financials_updated !== false) {
        props.onChange(csvPath);
        props.onDataUpdated();
      }
      await statusState.run(() =>
        api<Json>("/api/financials/status", {
          path: csvPath,
          stale_after_days: 7,
        }),
      );
      return result;
    });
  useEffect(() => {
    void refreshStatus();
  }, [props.value, props.refreshKey]);
  const status = String(statusState.data?.status ?? "checking");
  const statusLabel =
    status === "fresh"
      ? "利用可能"
      : status === "stale"
        ? "更新推奨"
        : status === "missing"
          ? "未作成"
          : status === "invalid"
            ? "要確認"
            : "確認中";
  const statusBadgeClass = status === "fresh" ? "safe" : status === "checking" ? "" : "warn";
  return (
    <section className="financials-source-bar" aria-label="EDINET financials source">
      <div>
        <b>現在使う財務データ</b>
        <span>候補抽出、銘柄詳細、試算、レポートで共通利用します。</span>
        <span className="mono">{props.value}</span>
        <div className="financials-status-summary">
          <span className={`badge ${statusBadgeClass}`}>{statusLabel}</span>
          {statusState.data?.available === true && (
            <>
              <span>{Number(statusState.data.company_count ?? 0).toLocaleString()}社</span>
              <span>{Number(statusState.data.point_count ?? 0).toLocaleString()}件</span>
              <span>更新: {formatDateTime(statusState.data.modified_at)}</span>
            </>
          )}
          {statusState.data?.available === false && (
            <span>{String(statusState.data.hint ?? "Dataタブで財務データを更新してください。")}</span>
          )}
        </div>
      </div>
      <div className="financials-source-actions">
        <input
          value={props.value}
          onChange={(event) => props.onChange(event.target.value)}
          aria-label="財務データパス"
        />
        <button onClick={() => props.onChange(DEFAULT_FINANCIALS_PATH)}>
          取得済み
        </button>
        <button onClick={() => props.onChange(SAMPLE_FINANCIALS_PATH)}>
          サンプル
        </button>
        <button onClick={() => void refreshStatus()} disabled={statusState.loading}>
          状態更新
        </button>
        <button onClick={runOneClickUpdate} disabled={updateState.loading}>
          ワンクリック自動更新
        </button>
        <button onClick={props.onOpenData}>
          Dataで更新
        </button>
      </div>
      <Status loading={updateState.loading} error={updateState.error} />
      {updateState.data && (
        <p className="status">
          {updateState.data.financials_updated === false
            ? "公式ページ取得のみ実行しました: "
            : "財務データを更新しました: "}
          <span className="mono">
            {String(updateState.data.financials_csv ?? "local_docs/edinet/financials.csv")}
          </span>
          {updateState.data.hint ? <span> {String(updateState.data.hint)}</span> : null}
        </p>
      )}
    </section>
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

async function readCsvFileText(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  for (const encoding of ["utf-8", "shift_jis"]) {
    try {
      return new TextDecoder(encoding, { fatal: true }).decode(buffer);
    } catch {
      // Try the next common Japanese CSV encoding.
    }
  }
  return new TextDecoder("utf-8").decode(buffer);
}

function jsonText(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function Status(props: { loading: boolean; error: string | null }) {
  if (props.loading) return <p className="status">実行中…</p>;
  if (props.error) return <p className="status error">エラー: {props.error}</p>;
  return null;
}

function edinetApiKeySourceLabel(value: unknown): string {
  switch (String(value ?? "")) {
    case "runtime_input":
      return "画面入力";
    case "dotenv":
      return ".env";
    case "process_env":
      return "環境変数";
    case "missing":
      return "未設定";
    default:
      return "確認中";
  }
}

function refreshModeLabel(value: unknown): string {
  switch (String(value ?? "")) {
    case "edinet_api":
      return "財務CSV更新";
    case "disclosure_scrape_only":
      return "公式ページ取得のみ";
    default:
      return "更新結果";
  }
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

function formatCompactNumber(value: unknown): string {
  if (typeof value === "number") {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value ?? "-");
}

function formatRatio(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function incomeSourceLabel(value: unknown): string {
  const source = String(value ?? "");
  const labels: Record<string, string> = {
    edinet_latest_dividend_per_share: "EDINET最新1株配当",
    user_annual_income: "ユーザー入力 年間収入",
    user_distribution: "ユーザー入力 分配単価",
    not_available: "未入力",
  };
  return labels[source] ?? (source || "-");
}

function EdinetSummaryPanel({ summary }: { summary?: Json | null }) {
  if (!summary || typeof summary !== "object") return null;
  const cutYears = Array.isArray(summary.dividend_cut_years)
    ? summary.dividend_cut_years.join(", ")
    : "";
  return (
    <div className="edinet-summary">
      <div className="edinet-summary-head">
        <b>EDINET財務</b>
        <span className="badge">FY{String(summary.latest_fiscal_year ?? "-")}</span>
      </div>
      <dl>
        <div>
          <dt>自己資本比率</dt>
          <dd>{formatCompactNumber(summary.latest_equity_ratio)}%</dd>
        </div>
        <div>
          <dt>1株配当</dt>
          <dd>{formatCompactNumber(summary.latest_dividend_per_share)}</dd>
        </div>
        <div>
          <dt>営業CF</dt>
          <dd>{String(summary.operating_cf_trend_label ?? summary.operating_cf_trend ?? "-")}</dd>
        </div>
        <div>
          <dt>減配年度</dt>
          <dd>{cutYears || "なし"}</dd>
        </div>
      </dl>
      <small>{String(summary.source_ref ?? "")}</small>
    </div>
  );
}

function CandidateMetrics({ item }: { item: Json }) {
  const metrics = item.metrics ?? {};
  const summary = item.edinet_summary as Json | undefined;
  const assetType = String(item.asset_type ?? "");
  const score = typeof item.score === "number" ? item.score : Number(item.score);
  return (
    <div className="candidate-metrics">
      <EdinetSummaryPanel summary={summary} />
      {assetType === "fund" && (
        <FundScorePanel
          score={Number.isFinite(score) ? score : null}
          breakdown={Array.isArray(item.score_breakdown) ? item.score_breakdown : []}
          model={item.scoring_model as Json | undefined}
        />
      )}
      <details className="raw-metrics">
        <summary>指標JSON</summary>
        <pre>{JSON.stringify(metrics, null, 2)}</pre>
      </details>
    </div>
  );
}

function FundScorePanel({
  score,
  breakdown,
  model,
}: {
  score: number | null;
  breakdown: Json[];
  model?: Json;
}) {
  return (
    <div className="fund-score-panel">
      <div className="edinet-summary-head">
        <b>投信スコア</b>
        <span className="badge">{score === null ? "-" : score.toFixed(3)}</span>
      </div>
      <small>{String(model?.note ?? "条件比較のための決定論スコアです。")}</small>
      {breakdown.length > 0 && (
        <table className="score-breakdown-table">
          <thead>
            <tr>
              <th>項目</th>
              <th>重み</th>
              <th>値</th>
              <th>寄与</th>
            </tr>
          </thead>
          <tbody>
            {breakdown.map((row) => (
              <tr key={String(row.key)}>
                <td>
                  <b>{String(row.label ?? row.key)}</b>
                  <small>{String(row.formula ?? "")}</small>
                </td>
                <td className="mono">{formatRatio(row.weight)}</td>
                <td>{String(row.raw_value ?? "-")}</td>
                <td className="mono">{formatRatio(row.contribution)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function SecuritySearch({
  financialsCsvPath,
  onSelect,
  onUseSample,
  onOpenData,
  title = "証券コード検索",
}: {
  financialsCsvPath: string;
  onSelect: (security: Json) => void;
  onUseSample?: () => void;
  onOpenData?: () => void;
  title?: string;
}) {
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(10);
  const [scope, setScope] = useState("prime");
  const state = useAsync<Json>();
  const securities: Json[] = Array.isArray(state.data?.securities)
    ? state.data.securities
    : [];
  const search = () =>
    state.run(() =>
      api<Json>("/api/market/universe", {
        financials_csv: financialsCsvPath,
        query,
        limit,
        scope,
      }),
    );
  const currentScopeLabel =
    MARKET_SCOPE_OPTIONS.find((option) => option.value === scope)?.label ?? scope;
  return (
    <div className="security-search">
      <div className="report-audit-head">
        <div>
          <h3>{title}</h3>
          <p className="hint">
            東証プライム、日経225、財務データありの範囲を切り替えて、証券コードまたは企業名で検索します。
            空欄で検索すると選択中の範囲を一覧表示します。
            選択しても売買操作は行いません。
          </p>
        </div>
        <span className="badge">{currentScopeLabel}</span>
      </div>
      <div className="form">
        <Field label="対象範囲">
          <select value={scope} onChange={(event) => setScope(event.target.value)}>
            {MARKET_SCOPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="証券コード / 名称">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="例: 7203 / トヨタ"
          />
        </Field>
        <Field label="件数">
          <input
            type="number"
            min={1}
            max={50}
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
          />
        </Field>
        <button onClick={search} disabled={state.loading}>
          検索
        </button>
        <button
          onClick={() =>
            state.run(() =>
              api<Json>("/api/market/universe", {
                financials_csv: financialsCsvPath,
                query: "",
                limit,
                scope,
              }),
            )
          }
          disabled={state.loading}
        >
          一覧表示
        </button>
      </div>
      <Status loading={state.loading} error={state.error} />
      {state.data?.hint && <p className="hint">{String(state.data.hint)}</p>}
      {state.data?.sources && (
        <details className="evidence-panel kpi-details">
          <summary>
            公式ソース
            <span>JPX / Nikkei</span>
          </summary>
          <dl>
            <div>
              <dt>JPX</dt>
              <dd>
                <a
                  className="cite-link"
                  href={String(state.data.sources?.jpx_listed_issues?.page_url ?? "#")}
                  target="_blank"
                  rel="noreferrer"
                >
                  東証上場銘柄一覧
                </a>
              </dd>
            </div>
            <div>
              <dt>Nikkei 225</dt>
              <dd>
                <a
                  className="cite-link"
                  href={String(state.data.sources?.nikkei225_components?.page_url ?? "#")}
                  target="_blank"
                  rel="noreferrer"
                >
                  Nikkei 225 Components
                </a>
              </dd>
            </div>
          </dl>
        </details>
      )}
      {state.data?.available === false && (
        <div className="callout warn-callout">
          <b>銘柄データがまだありません</b>
          <p>
            {String(
              state.data.hint
                ?? "DataタブでEDINET取得/手動保存を行うか、サンプルデータに切り替えてください。",
            )}
          </p>
          <div className="form">
            {onUseSample && (
              <button onClick={onUseSample}>サンプルデータに切替</button>
            )}
            {onOpenData && (
              <button onClick={onOpenData}>Dataタブで取得・保存</button>
            )}
          </div>
        </div>
      )}
      {securities.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>コード</th>
              <th>名称</th>
              <th>市場</th>
              <th>日経225</th>
              <th>財務</th>
              <th>最新年度</th>
              <th>自己資本比率</th>
              <th>1株配当</th>
              <th>選択</th>
            </tr>
          </thead>
          <tbody>
            {securities.map((security) => (
              <tr key={String(security.ticker)}>
                <td className="mono">{String(security.ticker)}</td>
                <td>{String(security.name)}</td>
                <td>{String(security.market_segment_label ?? security.market_segment ?? "-")}</td>
                <td>{security.is_nikkei225 ? <span className="badge safe">日経225</span> : "-"}</td>
                <td>{security.has_financials ? <span className="badge safe">あり</span> : "未取得"}</td>
                <td>{String(security.latest_fiscal_year ?? "-")}</td>
                <td className="mono">
                  {security.latest_equity_ratio !== undefined
                    ? `${formatCompactNumber(security.latest_equity_ratio)}%`
                    : "-"}
                </td>
                <td className="mono">
                  {formatCompactNumber(security.latest_dividend_per_share)}
                </td>
                <td>
                  <button onClick={() => onSelect(security)}>選択</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {state.data && securities.length === 0 && (
        <p className="hint">
          {state.data.available === false
            ? "財務データまたは市場区分データが見つからないため、銘柄一覧を表示できません。"
            : "一致する銘柄がありません。対象範囲、データ取込状況、検索語を確認してください。"}
        </p>
      )}
    </div>
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
      "先にデータ画面でIRページやメモをRAG登録してください。",
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

function OperatorCatalog({ data }: { data?: Json | null }) {
  const groups: Json[] = Array.isArray(data?.groups) ? data.groups : [];
  if (!groups.length) return null;
  return (
    <div className="subpanel operator-catalog">
      <div className="section-head">
        <div>
          <h3>演算子カタログ</h3>
          <p className="hint">
            数値計算、候補抽出、RAG検索がどの式で動くかをレビューできるように固定表示します。
          </p>
        </div>
        <span className="badge">非助言 / 自動売買なし</span>
      </div>
      <div className="operator-grid">
        {groups.map((group) => {
          const operators: Json[] = Array.isArray(group.operators) ? group.operators : [];
          const weights: Json[] = Array.isArray(group.weights) ? group.weights : [];
          return (
            <article className="operator-card" key={String(group.key)}>
              <h4>{String(group.label ?? group.key)}</h4>
              <p>{String(group.purpose ?? "")}</p>
              {group.formula && <code>{String(group.formula)}</code>}
              {weights.length > 0 && (
                <div className="operator-weights">
                  {weights.map((weight) => (
                    <span key={String(weight.key)}>
                      {String(weight.label ?? weight.key)} {Number(weight.weight ?? 0).toFixed(2)}
                    </span>
                  ))}
                </div>
              )}
              <ul>
                {operators.slice(0, 5).map((operator) => (
                  <li key={String(operator.key)}>
                    <b>{String(operator.label ?? operator.key)}</b>
                    <span>{String(operator.formula ?? "")}</span>
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>
      <p className="hint">{String(data?.non_advisory_boundary ?? "")}</p>
    </div>
  );
}

function SearchTabEnhanced() {
  const [query, setQuery] = useState("配当方針 DOE 配当性向");
  const [dbPath, setDbPath] = useState(DEFAULT_RAG_DB_PATH);
  const [limit, setLimit] = useState(5);
  const [hybrid, setHybrid] = useState(true);
  const [enhanced, setEnhanced] = useState(true);
  const [queryExpansion, setQueryExpansion] = useState(true);
  const [maxPerSource, setMaxPerSource] = useState(3);
  const [alpha, setAlpha] = useState(0.5);
  const { loading, error, data, run } = useAsync<Json>();
  const operators = useAsync<Json>();

  const search = () =>
    run(() =>
      api<Json>("/api/rag/search", {
        query,
        db_path: dbPath,
        limit,
        hybrid,
        alpha,
        enhanced,
        query_expansion: queryExpansion,
        max_per_source: maxPerSource,
      }),
    );

  useEffect(() => {
    operators.run(() => api<Json>("/api/operators/catalog"));
  }, []);

  const results: Json[] = data?.results ?? [];
  const queries: string[] = Array.isArray(data?.queries) ? data.queries.map(String) : [];
  const diagnostics = data?.diagnostics ?? null;
  const diagnosticOperators: Json[] = Array.isArray(diagnostics?.operators)
    ? diagnostics.operators
    : [];
  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">根拠</p>
          <h2>根拠検索と計算式</h2>
          <p className="hint">
            資料から根拠候補を探し、検索方法と計算式を確認できます。
          </p>
        </div>
        <span className="badge">出典 / 計算式 / 免責</span>
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
            min={1}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          />
        </Field>
        <Field label="拡張検索">
          <input type="checkbox" checked={enhanced} onChange={(e) => setEnhanced(e.target.checked)} />
        </Field>
        <Field label="クエリ分解">
          <input
            type="checkbox"
            checked={queryExpansion}
            onChange={(e) => setQueryExpansion(e.target.checked)}
            disabled={!enhanced}
          />
        </Field>
        <Field label="ハイブリッド">
          <input type="checkbox" checked={hybrid} onChange={(e) => setHybrid(e.target.checked)} />
        </Field>
        <Field label={`alpha(意味検索の重み)=${alpha}`}>
          <input
            type="range"
            min={0}
            max={1}
            step={0.1}
            value={alpha}
            onChange={(e) => setAlpha(Number(e.target.value))}
            disabled={!hybrid}
          />
        </Field>
        <Field label="出典ごとの上限">
          <input
            type="number"
            min={1}
            max={10}
            value={maxPerSource}
            onChange={(e) => setMaxPerSource(Number(e.target.value))}
            disabled={!enhanced}
          />
        </Field>
        <button className="primary" onClick={search} disabled={loading}>
          検索
        </button>
      </div>
      <Status loading={loading} error={error} />
      {diagnostics && (
        <div className="subpanel rag-diagnostics">
          <div className="section-head">
            <div>
              <h3>検索診断</h3>
              <p className="hint">
                方式: <span className="mono">{String(diagnostics.mode ?? "")}</span> / 候補:{" "}
                <span className="mono">{String(diagnostics.candidate_count ?? 0)}</span>
              </p>
            </div>
            <span className="badge">RRF k={String(diagnostics.rrf_k ?? "-")}</span>
          </div>
          {queries.length > 0 && (
            <div className="chips">
              {queries.map((item) => (
                <span className="badge" key={item}>{item}</span>
              ))}
            </div>
          )}
          {diagnosticOperators.length > 0 && (
            <table className="grid compact-grid">
              <thead>
                <tr>
                  <th>演算子</th>
                  <th>式</th>
                  <th>目的</th>
                </tr>
              </thead>
              <tbody>
                {diagnosticOperators.map((operator) => (
                  <tr key={String(operator.key)}>
                    <td>{String(operator.label ?? operator.key)}</td>
                    <td className="mono">{String(operator.formula ?? "")}</td>
                    <td>{String(operator.purpose ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {results.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>#</th>
              <th>score</th>
              <th>出典</th>
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
      <Status loading={operators.loading} error={operators.error} />
      <OperatorCatalog data={operators.data} />
    </section>
  );
}

function SearchTab() {
  return <SearchTabEnhanced />;
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
        <p className="hint">入力データにブロック要因はありません。</p>
      )}
    </div>
  );
}

function HoldingsTab({
  financialsCsvPath,
  onFinancialsCsvPathChange,
  onOpenData,
}: {
  financialsCsvPath: string;
  onFinancialsCsvPathChange: (value: string) => void;
  onOpenData: () => void;
}) {
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
          ? "保有データの検証に通りました。分析できます。"
          : "保有データの検証に失敗しました。表示された問題を修正してください。",
      );
      return validation;
    });
  const analyze = () =>
    analysisState.run(async () => {
      setValidationActionMessage("分析前に保有データを検証しています。");
      const validation = await validationState.run(() =>
        api<Json>("/api/holdings/validate", { csv_text: csv }),
      );
      if (!validation) throw new Error("保有データの検証を完了できませんでした。");
      if (validation.valid !== true) {
        setValidationActionMessage(
          "保有データの検証に失敗したため、分析を停止しました。検証結果を確認してください。",
        );
        throw new Error("分析前に保有データの検証エラーを修正してください。");
      }
      setValidationActionMessage("保有データの検証に通りました。分析を実行しています。");
      const result = await api<Json>("/api/portfolio/analyze", {
        csv_text: csv,
        financials_csv: financialsCsvPath,
      });
      setValidationActionMessage("保有データ検証後に分析が完了しました。");
      return result;
    });
  const loadSampleHoldings = () => setCsv(AUDITABLE_SAMPLE_HOLDINGS_CSV);
  const loadMinimalHoldings = () => setCsv(SAMPLE_HOLDINGS_CSV);
  const updateHoldingDraft = (column: string, value: string) =>
    setHoldingDraft((current) => ({ ...current, [column]: value }));
  const addHoldingDraftRow = () => {
    setCsv((current) => appendCsvDraft(current, HOLDING_CSV_COLUMNS, holdingDraft));
    setValidationActionMessage("手入力行を保有データに追加しました。取込前に検証してください。");
  };
  const importHoldingFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    void readCsvFileText(file).then((text) => {
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
          <p className="eyebrow">保有</p>
          <h2>保有分析</h2>
        </div>
        <span className="badge">日本株 + 投信</span>
      </div>
      <p className="hint">
        保有データまたは手入力データから、評価額、評価損益、配当/分配金見込み、NISA枠、
        集中度を機械的に集計します。売買推奨や注文連携は行いません。
      </p>
      <Field label="保有データ">
        <textarea rows={7} value={csv} onChange={(e) => setCsv(e.target.value)} />
      </Field>
      <div className="subpanel csv-manual-panel">
        <h3>保有を手入力</h3>
        <p className="hint">
          1行ずつ手入力して保有データへ追加できます。注文や売買操作は行いません。
        </p>
        <SecuritySearch
          financialsCsvPath={financialsCsvPath}
          title="保有入力用の銘柄検索"
          onUseSample={() => onFinancialsCsvPathChange(SAMPLE_FINANCIALS_PATH)}
          onOpenData={onOpenData}
          onSelect={(security) => {
            updateHoldingDraft("asset_type", "stock");
            updateHoldingDraft("ticker_or_fund_code", String(security.ticker ?? ""));
            updateHoldingDraft("name", String(security.name ?? ""));
            setValidationActionMessage("銘柄検索結果を手入力行に反映しました。");
          }}
        />
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
          <button onClick={addHoldingDraftRow}>手入力行を追加</button>
          <label className="button-like">
            ファイル取込
            <input type="file" accept=".csv,text/csv" onChange={importHoldingFile} />
          </label>
          <button onClick={downloadHoldingCsv}>データを出力</button>
          <button onClick={downloadHoldingImportJson} disabled={!importState.data}>
            取込結果を出力
          </button>
        </div>
      </div>
      <div className="form">
        <button onClick={loadSampleHoldings}>サンプル保有データを読み込む</button>
        <button onClick={loadHoldingTemplate} disabled={templateState.loading}>
          データテンプレート
        </button>
        <button onClick={loadMinimalHoldings}>最小データを読み込む</button>
        <button onClick={validateHoldings} disabled={validationState.loading}>
          データ検証
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
      <CsvValidationPanel title="保有データ検証" data={validationState.data} />

      {inputWarnings.length > 0 && (
        <div className="subpanel csv-guidance-panel">
          <h3>データ入力ガイド</h3>
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
      {analysisState.data && (
        <p className="hint">
          EDINETカバー: {String(summary.edinet_covered_holdings ?? 0)}件 / 出典{" "}
          <span className="mono">{String(summary.edinet_source_ref ?? financialsCsvPath)}</span>
        </p>
      )}

      {nisaAlerts.length > 0 && (
        <div className="subpanel nisa-alert-panel">
          <h3>NISA確認</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>重要度</th>
                <th>枠</th>
                <th>利用率</th>
                <th>残り</th>
                <th>内容</th>
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
          <h3>データ鮮度</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>重要度</th>
                <th>出典</th>
                <th>理由</th>
                <th>経過</th>
                <th>内容</th>
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
          <h3>配当/分配金の確認</h3>
          <table className="grid">
            <thead>
              <tr>
                <th>重要度</th>
                <th>保有</th>
                <th>理由</th>
                <th>値</th>
                <th>内容</th>
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
              <th>配当/分配金</th>
              <th>EDINET</th>
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
                <td>
                  <span className="mono">
                    {row.annual_income_estimate !== undefined
                      ? yen(row.annual_income_estimate)
                      : "-"}
                  </span>
                  <small>{incomeSourceLabel(row.annual_income_source)}</small>
                </td>
                <td>
                  {row.edinet_summary ? (
                    <EdinetSummaryPanel summary={row.edinet_summary as Json} />
                  ) : (
                    <span className="hint">対象外 / 未取得</span>
                  )}
                </td>
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

function CandidateScreenTab({
  financialsCsvPath,
  onOpenDetail,
}: {
  financialsCsvPath: string;
  onOpenDetail: (code: string, assetType: string) => void;
}) {
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
        setScreenActionMessage("候補抽出前に投信データを検証しています。");
        const validation = await fundValidationState.run(() =>
          api<Json>("/api/funds/validate", { funds_csv_text: fundsCsv }),
        );
        if (!validation) throw new Error("投信データの検証を完了できませんでした。");
        if (validation.valid !== true) {
          setScreenActionMessage(
            "投信データの検証に失敗したため、候補抽出を停止しました。検証結果を確認してください。",
          );
          throw new Error("候補抽出前に投信データの検証エラーを修正してください。");
        }
      } else {
        setScreenActionMessage("投信候補が無効のため、投信データ検証をスキップしました。");
      }
      setScreenActionMessage("入力確認が完了しました。候補を抽出しています。");
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
        financials_csv: financialsCsvPath,
        sort_by: "score",
      });
      setScreenActionMessage("候補抽出が完了しました。");
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
    setScreenActionMessage("手入力行を投信データに追加しました。候補抽出前に検証してください。");
  };
  const importFundFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    void readCsvFileText(file).then((text) => {
      setFundsCsv(text);
      setScreenActionMessage(`${file.name} を読み込みました。候補抽出前に検証してください。`);
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
          ? "投信データの検証に通りました。候補抽出できます。"
          : "投信データの検証に失敗しました。表示された問題を修正してください。",
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
    setPresetStatus(`${preset.name} を適用しました。入力データ本文は変更していません。`);
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
          <p className="eyebrow">候補</p>
          <h2>条件で候補を探す</h2>
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
          保存するのは条件だけです。投信データや抽出結果はブラウザ保存に含めません。
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
      <Field label="投信データ">
        <textarea rows={5} value={fundsCsv} onChange={(e) => setFundsCsv(e.target.value)} />
      </Field>
      <div className="subpanel csv-manual-panel">
        <h3>投信を手入力</h3>
        <p className="hint">
          投信プロファイルを手入力、ファイル取込、または現在のデータとして出力できます。
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
          <button onClick={addFundDraftRow}>手入力行を追加</button>
          <label className="button-like">
            ファイル取込
            <input type="file" accept=".csv,text/csv" onChange={importFundFile} />
          </label>
          <button onClick={downloadFundCsv}>データを出力</button>
          <button onClick={downloadFundValidationJson} disabled={!fundValidationState.data}>
            Download validation JSON
          </button>
        </div>
      </div>
      <div className="form">
        <button onClick={loadSampleFunds}>サンプル投信データを読み込む</button>
        <button onClick={loadFundTemplate} disabled={fundTemplateState.loading}>
          投信テンプレート
        </button>
        <button onClick={validateFunds} disabled={fundValidationState.loading}>
          投信データ検証
        </button>
        <button className="primary" onClick={screen} disabled={state.loading}>
          条件に一致する比較対象を表示
        </button>
      </div>
      <Status loading={fundTemplateState.loading} error={fundTemplateState.error} />
      <Status loading={fundValidationState.loading} error={fundValidationState.error} />
      <Status loading={state.loading} error={state.error} />
      {screenActionMessage && <p className="status">{screenActionMessage}</p>}
      <CsvValidationPanel title="投信データ検証" data={fundValidationState.data} />
      <div className="subpanel provider-ledger-panel">
        <div className="report-audit-head">
          <div>
            <h3>データ提供元の利用条件</h3>
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
      {state.data?.financials_source_ref && (
        <p className="hint">
          EDINET財務データ: <span className="mono">{String(state.data.financials_source_ref)}</span>
        </p>
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
                  <CandidateMetrics item={item} />
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

function InvestmentReportTab({ financialsCsvPath }: { financialsCsvPath: string }) {
  const [holdingsCsv, setHoldingsCsv] = useState(AUDITABLE_SAMPLE_HOLDINGS_CSV);
  const [fundsCsv, setFundsCsv] = useState(SAMPLE_FUNDS_CSV);
  const [targetDividend, setTargetDividend] = useState(60000);
  const [wizardStep, setWizardStep] = useState<ReportWizardStepId>("data");
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
    setReportActionMessage(`レポート用の保有データを検証しています: ${actionLabel}`);
    const holdingValidation = await reportHoldingValidationState.run(() =>
      api<Json>("/api/holdings/validate", { csv_text: holdingsCsv }),
    );
    if (!holdingValidation || holdingValidation.valid !== true) {
      setReportActionMessage(
        "保有データの検証に失敗したため、レポート操作を停止しました。検証結果を確認してください。",
      );
      return false;
    }

    if (fundsCsv.trim()) {
      setReportActionMessage(`レポート用の投信データを検証しています: ${actionLabel}`);
      const fundValidation = await reportFundValidationState.run(() =>
        api<Json>("/api/funds/validate", { funds_csv_text: fundsCsv }),
      );
      if (!fundValidation || fundValidation.valid !== true) {
        setReportActionMessage(
          "投信データの検証に失敗したため、レポート操作を停止しました。検証結果を確認してください。",
        );
        return false;
      }
    } else {
      setReportActionMessage("投信データが空のため、投信データ検証をスキップしました。");
    }
    setReportActionMessage("レポート入力データの検証に通りました。");
    return true;
  };
  const validateReportCsvs = () => {
    void validateReportInputs("manual validation");
  };
  const generate = () =>
    state.run(async () => {
      const inputsValid = await validateReportInputs("report generation");
      if (!inputsValid) {
        throw new Error("レポート生成前に入力データの検証エラーを修正してください。");
      }
      setReportActionMessage("入力データの検証に通りました。候補抽出を実行しています。");
      const candidates = await api<Json>("/api/candidates/screen", {
        asset_types: ["stock", "fund"],
        exclude_dividend_cut: true,
        max_expense_ratio: 0.2,
        nisa_eligible_only: true,
        funds_csv_text: fundsCsv,
        financials_csv: financialsCsvPath,
      });
      const report = await api<Json>("/api/reports/investment-monthly", {
        csv_text: holdingsCsv,
        financials_csv: financialsCsvPath,
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
      setReportActionMessage("入力データ検証後にレポートを生成しました。");
      setWizardStep("preview");
      return report;
    });
  const refreshHistory = () =>
    historyState.run(() => api<Json>("/api/reports/investment-monthly/history"));
  const loadSavedReport = (id: string) =>
    state.run(async () => {
      const entry = await api<Json>("/api/reports/investment-monthly/history/load", { id });
      setWizardStep("preview");
      return (entry.report as Json) ?? {};
    });
  const showCurrentMarkdown = () => {
    if (!state.data) return;
    setWizardStep("export");
    markdownState.run(() =>
      api<Json>("/api/reports/investment-monthly/markdown", { report: state.data }),
    );
  };
  const showSavedMarkdown = (id: string) => {
    setWizardStep("export");
    markdownState.run(() => api<Json>("/api/reports/investment-monthly/markdown", { id }));
  };
  const compareLatestReports = () => {
    if (reports.length < 2) return;
    setWizardStep("export");
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
  const wizardIndex = REPORT_WIZARD_STEPS.findIndex((step) => step.id === wizardStep);
  const currentWizardStep = REPORT_WIZARD_STEPS[Math.max(wizardIndex, 0)];
  const canGoBack = wizardIndex > 0;
  const canGoNext = wizardIndex >= 0 && wizardIndex < REPORT_WIZARD_STEPS.length - 1;
  const holdingCsvValid = reportHoldingValidationState.data?.valid === true;
  const fundCsvValid = !fundsCsv.trim() || reportFundValidationState.data?.valid === true;
  const reportGenerated = Boolean(state.data);
  const goBack = () => {
    if (!canGoBack) return;
    setWizardStep(REPORT_WIZARD_STEPS[wizardIndex - 1].id);
  };
  const goNext = () => {
    if (!canGoNext) return;
    setWizardStep(REPORT_WIZARD_STEPS[wizardIndex + 1].id);
  };

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">レポート</p>
          <h2>投資月次レポート</h2>
        </div>
        <span className="badge">決定論生成</span>
      </div>
      <p className="hint">
        保有分析と候補抽出結果から、根拠と計算式つきの非助言レポートを生成します。
      </p>
      <div className="report-wizard">
        <div className="report-wizard-rail" aria-label="レポート生成ステップ">
          {REPORT_WIZARD_STEPS.map((step, index) => (
            <button
              key={step.id}
              className={step.id === wizardStep ? "wizard-step active" : "wizard-step"}
              onClick={() => setWizardStep(step.id)}
            >
              <span>{step.step}</span>
              <b>{step.title}</b>
              <small>{step.body}</small>
              {index < wizardIndex && <i>完了</i>}
            </button>
          ))}
        </div>
        <article className="report-wizard-panel">
          <div className="report-audit-head">
            <div>
              <p className="eyebrow">手順 {currentWizardStep.step}</p>
              <h3>{currentWizardStep.title}</h3>
              <p className="hint">{currentWizardStep.body}</p>
            </div>
            <span className="badge">非助言レポート</span>
          </div>

          {wizardStep === "data" && (
            <>
              <div className="callout">
                <b>このレポートで使うデータ</b>
                <p>
                  財務データは候補抽出と根拠表示に使います。保有データと投信データは下のステップで確認します。
                  まだ本番EDINETデータがなければ、サンプルで流れを確認できます。
                </p>
                <p className="mono">{financialsCsvPath}</p>
              </div>
              <div className="form">
                <button onClick={loadReportSamples}>サンプルデータを読み込む</button>
                <button onClick={() => setWizardStep("holdings")}>保有確認へ</button>
              </div>
            </>
          )}

          {wizardStep === "holdings" && (
            <>
              <Field label="保有データ">
                <textarea
                  rows={8}
                  value={holdingsCsv}
                  onChange={(e) => setHoldingsCsv(e.target.value)}
                />
              </Field>
              <div className="form">
                <button
                  onClick={validateReportCsvs}
                  disabled={reportHoldingValidationState.loading || reportFundValidationState.loading}
                >
                  データを検証
                </button>
                <button onClick={() => setWizardStep("candidates")}>
                  候補条件へ
                </button>
              </div>
              <CsvValidationPanel
                title="レポート用保有データ検証"
                data={reportHoldingValidationState.data}
              />
            </>
          )}

          {wizardStep === "candidates" && (
            <>
              <div className="callout">
                <b>候補抽出条件</b>
                <p>
                  現在は「日本株+投信」「減配履歴なし」「信託報酬0.2%以下」
                  「NISA対象」を固定条件として、比較対象だけを抽出します。推奨ではありません。
                </p>
              </div>
              <Field label="投信データ（候補抽出用）">
                <textarea rows={7} value={fundsCsv} onChange={(e) => setFundsCsv(e.target.value)} />
              </Field>
              <div className="form">
                <button
                  onClick={validateReportCsvs}
                  disabled={reportHoldingValidationState.loading || reportFundValidationState.loading}
                >
                  データを検証
                </button>
                <button onClick={() => setWizardStep("target")}>
                  目標配当へ
                </button>
              </div>
              <CsvValidationPanel
                title="レポート用投信データ検証"
                data={reportFundValidationState.data}
              />
            </>
          )}

          {wizardStep === "target" && (
            <>
              <Field label="目標年間配当（円・任意）">
                <input
                  type="number"
                  value={targetDividend}
                  onChange={(e) => setTargetDividend(Number(e.target.value))}
                  placeholder="例: 60000"
                />
              </Field>
              <div className="callout">
                <b>逆算の意味</b>
                <p>
                  目標配当から必要予算を機械的に逆算します。達成を保証するものではなく、
                  現在の入力条件での試算です。
                </p>
              </div>
              <div className="form">
                <button onClick={() => setWizardStep("preview")}>プレビューへ</button>
              </div>
            </>
          )}

          {wizardStep === "preview" && (
            <>
              <dl className="mini-stats">
                <div>
                  <dt>保有データ</dt>
                  <dd>{holdingCsvValid ? "検証OK" : "未検証/要確認"}</dd>
                </div>
                <div>
                  <dt>投信データ</dt>
                  <dd>{fundCsvValid ? "検証OK" : "未検証/要確認"}</dd>
                </div>
                <div>
                  <dt>レポート</dt>
                  <dd>{reportGenerated ? "生成済み" : "未生成"}</dd>
                </div>
              </dl>
              <div className="form">
                <button
                  onClick={validateReportCsvs}
                  disabled={reportHoldingValidationState.loading || reportFundValidationState.loading}
                >
                  入力を再検証
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
                {state.data && (
                  <button onClick={() => setWizardStep("export")}>
                    保存/Markdownへ
                  </button>
                )}
              </div>
            </>
          )}

          {wizardStep === "export" && (
            <div className="callout">
              <b>保存と出力</b>
              <p>
                レポート生成時に履歴へ保存されます。ここでは履歴の再表示、比較、Markdown出力を行います。
              </p>
            </div>
          )}

          <div className="wizard-actions">
            <button onClick={goBack} disabled={!canGoBack}>戻る</button>
            <button onClick={goNext} disabled={!canGoNext}>次へ</button>
          </div>
        </article>
      </div>
      <Status loading={reportHoldingValidationState.loading} error={reportHoldingValidationState.error} />
      <Status loading={reportFundValidationState.loading} error={reportFundValidationState.error} />
      <Status loading={state.loading} error={state.error} />
      {reportActionMessage && <p className="status">{reportActionMessage}</p>}

      {wizardStep === "preview" && state.data?.publish_audit && (
        <div className="subpanel report-audit-panel">
          <div className="report-audit-head">
            <div>
              <h3>公開前チェック</h3>
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

      {wizardStep === "export" && (
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
      )}

      {wizardStep === "export" && state.data && (
        <div className="form">
          <button onClick={showCurrentMarkdown} disabled={markdownState.loading}>
            Markdownを表示
          </button>
        </div>
      )}
      {wizardStep === "export" && <Status loading={markdownState.loading} error={markdownState.error} />}
      {wizardStep === "export" && markdownText && (
        <div className="subpanel">
          <h3>Markdown</h3>
          <textarea className="markdown-output" rows={12} readOnly value={markdownText} />
        </div>
      )}

      {wizardStep === "preview" && kpis.length > 0 && (
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
      {wizardStep === "preview" && sections.length > 0 && (
        <div className="guide-grid">
          {sections.map((section) => (
            <article className="guide-card" key={String(section.key)}>
              <b>{String(section.title)}</b>
              <p>{String(section.body)}</p>
            </article>
          ))}
        </div>
      )}
      {wizardStep === "preview" && evidence.length > 0 && (
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
      {wizardStep === "preview" && state.data?.disclaimer && (
        <p className="hint">{String(state.data.disclaimer)}</p>
      )}
    </section>
  );
}

function InvestmentDetailTab({
  seed,
  financialsCsvPath,
  onFinancialsCsvPathChange,
  onOpenData,
}: {
  seed: DetailSeed;
  financialsCsvPath: string;
  onFinancialsCsvPathChange: (value: string) => void;
  onOpenData: () => void;
}) {
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
        financials_csv: financialsCsvPath,
      }),
    );

  const metrics: Json[] = Array.isArray(state.data?.metrics) ? state.data.metrics : [];
  const sections: Json[] = Array.isArray(state.data?.sections) ? state.data.sections : [];
  const evidence: Json[] = Array.isArray(state.data?.evidence) ? state.data.evidence : [];

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">詳細</p>
          <h2>銘柄 / 投信 詳細</h2>
        </div>
        <span className="badge">比較材料のみ</span>
      </div>
      <p className="hint">
        保有データ、投信データ、EDINET由来財務データを使い、1コードの保有状況と根拠を確認します。
        売買判断は代行しません。
      </p>
      <SecuritySearch
        financialsCsvPath={financialsCsvPath}
        onUseSample={() => onFinancialsCsvPathChange(SAMPLE_FINANCIALS_PATH)}
        onOpenData={onOpenData}
        onSelect={(security) => {
          setCode(String(security.ticker ?? ""));
          setAssetType("stock");
        }}
      />
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
      <Field label="保有データ">
        <textarea rows={5} value={holdingsCsv} onChange={(e) => setHoldingsCsv(e.target.value)} />
      </Field>
      <Field label="投信データ">
        <textarea rows={4} value={fundsCsv} onChange={(e) => setFundsCsv(e.target.value)} />
      </Field>
      <div className="form">
        <button onClick={loadSamples}>サンプルデータを読み込む</button>
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

      {state.data?.edinet_summary && (
        <div className="subpanel">
          <EdinetSummaryPanel summary={state.data.edinet_summary as Json} />
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

function AnswerTab({
  financialsCsvPath,
  onFinancialsCsvPathChange,
  onOpenData,
}: {
  financialsCsvPath: string;
  onFinancialsCsvPathChange: (value: string) => void;
  onOpenData: () => void;
}) {
  const [query, setQuery] = useState("選択中の対象銘柄について、配当方針と減配リスクを取得済みIR資料だけで整理して");
  const [dbPath, setDbPath] = useState(DEFAULT_RAG_DB_PATH);
  const [targetSource, setTargetSource] = useState(() =>
    readLocalStorageString(AI_CHAT_TARGET_SOURCE_STORAGE_KEY, TARGET_SOURCE_OPTIONS[1].source),
  );
  const [selectedTicker, setSelectedTicker] = useState(() =>
    readLocalStorageString(AI_CHAT_SELECTED_TICKER_STORAGE_KEY),
  );
  const [selectedSecurityName, setSelectedSecurityName] = useState(() =>
    readLocalStorageString(AI_CHAT_SELECTED_SECURITY_NAME_STORAGE_KEY),
  );
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

  useEffect(() => {
    writeLocalStorageString(AI_CHAT_TARGET_SOURCE_STORAGE_KEY, targetSource);
  }, [targetSource]);

  useEffect(() => {
    writeLocalStorageString(AI_CHAT_SELECTED_TICKER_STORAGE_KEY, selectedTicker);
    writeLocalStorageString(
      AI_CHAT_SELECTED_SECURITY_NAME_STORAGE_KEY,
      selectedSecurityName,
    );
  }, [selectedSecurityName, selectedTicker]);

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
        [
          selectedTarget.queryContext,
          selectedTicker
            ? `対象証券コード: ${selectedTicker}\n対象銘柄名: ${selectedSecurityName || "未指定"}`
            : "",
          `EDINET財務データ: ${financialsCsvPath}`,
        ]
          .filter(Boolean)
          .join("\n")
      );
      const result = await api<Json>("/api/orchestrate", {
        query: contextualQuery,
        db_path: dbPath,
        ticker: selectedTicker || undefined,
        financials_csv: financialsCsvPath,
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
    setSelectedTicker("");
    setSelectedSecurityName("");
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
          <p className="eyebrow">AIチャット</p>
          <h2>根拠付きチャット</h2>
        </div>
        <span className="badge">RAG + AI整理</span>
      </div>
      <p className="hint">
        RAG検索後、複数ドラフト→レビュー→統合の順で回答を作ります。UIの標準動作はローカル擬似AIです。
        実Geminiを使う場合は、バックエンドで許可設定した上で「実APIを使う」を有効にします。
      </p>
      <GuideCards items={AI_GUIDES} />

      <SecuritySearch
        financialsCsvPath={financialsCsvPath}
        title="AI回答に使う証券コード検索"
        onUseSample={() => onFinancialsCsvPathChange(SAMPLE_FINANCIALS_PATH)}
        onOpenData={onOpenData}
        onSelect={(security) => {
          setSelectedTicker(String(security.ticker ?? ""));
          setSelectedSecurityName(String(security.name ?? ""));
          setQuery(
            `${String(security.ticker ?? "")} ${String(security.name ?? "")} の配当方針、減配履歴、営業CFと自己資本比率を根拠付きで整理して`,
          );
        }}
      />

      {selectedTicker && (
        <div className="callout">
          選択中: <span className="mono">{selectedTicker}</span> {selectedSecurityName}
          <br />
          EDINET財務データ: <span className="mono">{financialsCsvPath}</span>
        </div>
      )}

      <QuestionChips onPick={setQuery} />

      <div className="chat-window">
        {messages.map((message, index) => (
          <article key={`${message.role}-${index}`} className={`chat-bubble ${message.role}`}>
            <div className="chat-meta">
              <span>{message.role === "user" ? "あなた" : "AI"}</span>
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
        取得済みの財務（配当・減配履歴・自己資本比率・営業CF）から銘柄を自動採点します。手動データ入力は不要です。売買推奨ではありません。
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
        <p className="status">{String(data.hint ?? "財務データが見つかりません")}</p>
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
          <p className="eyebrow">スコア</p>
          <h2>投資スコアリング</h2>
        </div>
        <span className="badge">EDINET / データ</span>
      </div>

      <StockScorePanel />

      <div className="subpanel">
        <h3>ファンド/ETF比較データ</h3>
        <p className="hint">経費率・リターン・リスク・分散度を正規化して比較します。売買推奨ではありません。</p>
      <div className="form">
        <Field label="比較データ（name,expense_ratio,annual_return,volatility,diversification_score）">
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
          <p className="eyebrow">予測</p>
          <h2>アンサンブル予測</h2>
        </div>
        <span className="badge">検証</span>
      </div>
      <p className="hint">同梱S&P500サンプルによる統計的推定です。将来リターンの保証ではありません。</p>
      <div className="form">
        <Field label="空間">
          <select value={space} onChange={(e) => setSpace(e.target.value)}>
            <option value="returns">リターン（推奨）</option>
            <option value="level">価格水準</option>
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
              <th>改善度</th>
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

function ScrapeTab({
  financialsCsvPath,
  onFinancialsCsvPathChange,
  onFinancialsDataUpdated,
}: {
  financialsCsvPath: string;
  onFinancialsCsvPathChange: (path: string) => void;
  onFinancialsDataUpdated: () => void;
}) {
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
  const [edinetOutputDir, setEdinetOutputDir] = useState("local_docs/edinet");
  const [edinetApiKeyInput, setEdinetApiKeyInput] = useState("");
  const [manualFinancialsCsv, setManualFinancialsCsv] = useState(SAMPLE_FINANCIALS_CSV);
  const [manualFinancialsOutputPath, setManualFinancialsOutputPath] =
    useState(financialsCsvPath);
  const [jpxListedText, setJpxListedText] = useState(SAMPLE_JPX_LISTED_ISSUES_DATA);
  const [jpxListedOutputPath, setJpxListedOutputPath] =
    useState("local_docs/jpx/listed_issues.csv");
  const sourceState = useAsync<Json>();
  const manualState = useAsync<Json>();
  const edinetState = useAsync<Json>();
  const edinetStatusState = useAsync<Json>();
  const financialsState = useAsync<Json>();
  const jpxListedState = useAsync<Json>();
  const jpxDownloadState = useAsync<Json>();

  useEffect(() => {
    setManualFinancialsOutputPath(financialsCsvPath);
  }, [financialsCsvPath]);

  useEffect(() => {
    void edinetStatusState.run(() => api<Json>("/api/edinet/status"));
  }, []);

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

  const runEdinetIngest = (days = edinetDays, years = edinetYears) =>
    edinetState.run(async () => {
      if (edinetApiKeyInput.trim()) {
        await edinetStatusState.run(() =>
          api<Json>("/api/edinet/api-key", {
            api_key: edinetApiKeyInput.trim(),
          }),
        );
      }
      const result = await runJob("/api/financials/refresh-async", {
        registry_path: edinetRegistry,
        days,
        years: years > 0 ? years : undefined,
        output_dir: edinetOutputDir,
        db_path: dbPath,
        index_after_fetch: true,
      });
      const csvPath = String(
        result.financials_csv ?? `${edinetOutputDir.replace(/[\\/]$/, "")}/financials.csv`,
      );
      if (result.financials_updated !== false) {
        onFinancialsCsvPathChange(csvPath);
        onFinancialsDataUpdated();
        setManualFinancialsOutputPath(csvPath);
      }
      await edinetStatusState.run(() => api<Json>("/api/edinet/status"));
      return result;
    });

  const importFinancialsFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    void readCsvFileText(file).then((text) => setManualFinancialsCsv(text));
  };

  const loadSampleFinancials = () => setManualFinancialsCsv(SAMPLE_FINANCIALS_CSV);
  const downloadManualFinancialsCsv = () =>
    downloadTextFile("financials_manual.csv", manualFinancialsCsv);
  const previewManualFinancials = () =>
    financialsState.run(() =>
      api<Json>("/api/financials/import", {
        csv_text: manualFinancialsCsv,
        save: false,
      }),
    );
  const saveManualFinancials = () =>
    financialsState.run(async () => {
      const result = await api<Json>("/api/financials/import", {
        csv_text: manualFinancialsCsv,
        save: true,
        output_path: manualFinancialsOutputPath,
      });
      const savedPath = String(result.saved_path ?? manualFinancialsOutputPath);
      onFinancialsCsvPathChange(savedPath);
      onFinancialsDataUpdated();
      setManualFinancialsOutputPath(savedPath);
      return result;
    });
  const compareCurrentFinancials = () =>
    financialsState.run(() =>
      api<Json>("/api/financials/import", {
        path: financialsCsvPath,
        save: false,
      }),
    );

  const importJpxListedFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    void readCsvFileText(file).then((text) => setJpxListedText(text));
  };
  const loadJpxListedTemplate = () =>
    jpxListedState.run(async () => {
      const template = await api<Json>("/api/market/jpx-listed/template");
      setJpxListedText(String(template.csv_text ?? SAMPLE_JPX_LISTED_ISSUES_DATA));
      return template;
    });
  const saveJpxListedData = () =>
    jpxListedState.run(() =>
      api<Json>("/api/market/jpx-listed/import", {
        csv_text: jpxListedText,
        output_path: jpxListedOutputPath,
        save: true,
      }),
    );
  const downloadOfficialJpxListedData = () =>
    jpxDownloadState.run(async () => {
      const result = await api<Json>("/api/market/jpx-listed/download-import", {
        download_output_path: "local_docs/jpx/data_j.xls",
        converted_output_path: "local_docs/jpx/data_j_converted.csv",
        output_path: jpxListedOutputPath,
        save: true,
      });
      if (result.saved_path) {
        setJpxListedOutputPath(String(result.saved_path));
      }
      return result;
    });

  const applyEdinetApiKey = () =>
    edinetStatusState.run(() =>
      api<Json>("/api/edinet/api-key", {
        api_key: edinetApiKeyInput.trim() || undefined,
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
          <p className="eyebrow">データ</p>
          <h2>データ取得・手動取込</h2>
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
          <b>2. 事前確認</b>
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
          事前確認のみ
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
          <summary>事前確認結果</summary>
          <FetchResultsTable results={dryResults} />
        </details>
      )}
      {results.length > 0 && <FetchResultsTable results={results} />}
      {sourceState.data?.index && (
        <p className="callout">RAG登録完了: {JSON.stringify(sourceState.data.index)}</p>
      )}

      <div className="edinet-ingest">
        <div className="report-audit-head">
          <div>
            <h3>市場区分データ（JPX公式）</h3>
            <p className="hint">
              東証プライムで銘柄を選択するためのデータです。価格や指数ウェイトは扱わず、市場区分と会社名だけを選択補助として使います。
            </p>
          </div>
          <span className="badge">JPX</span>
        </div>
        <div className="callout">
          <b>公式ソース</b>
          <p className="hint">
            JPXの東証上場銘柄一覧は毎月更新されます。公式ファイルは旧Excel形式のため、このアプリでは取得後にExcel等でCSV/TSVへ変換したデータを保存します。
          </p>
          <p>
            <a
              className="cite-link"
              href="https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
              target="_blank"
              rel="noreferrer"
            >
              JPX 東証上場銘柄一覧
            </a>{" "}
            /{" "}
            <a
              className="cite-link"
              href="https://indexes.nikkei.co.jp/en/nkave/index/component?idx=nk225"
              target="_blank"
              rel="noreferrer"
            >
              Nikkei 225 Components
            </a>
          </p>
        </div>
        <div className="form">
          <Field label="保存先 listed_issues">
            <input
              value={jpxListedOutputPath}
              onChange={(event) => setJpxListedOutputPath(event.target.value)}
            />
          </Field>
          <button onClick={downloadOfficialJpxListedData} disabled={jpxDownloadState.loading}>
            JPX公式データを取得して反映
          </button>
          <button onClick={loadJpxListedTemplate} disabled={jpxListedState.loading}>
            入力テンプレート
          </button>
          <label className="button-like">
            データを読み込む
            <input type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" onChange={importJpxListedFile} />
          </label>
          <button
            className="primary"
            onClick={saveJpxListedData}
            disabled={jpxListedState.loading || !jpxListedText.trim()}
          >
            保存して東証プライム選択に反映
          </button>
        </div>
        <Field label="市場区分データ">
          <textarea
            rows={8}
            value={jpxListedText}
            onChange={(event) => setJpxListedText(event.target.value)}
          />
        </Field>
        <Status loading={jpxDownloadState.loading} error={jpxDownloadState.error} />
        <Status loading={jpxListedState.loading} error={jpxListedState.error} />
        {jpxDownloadState.data && (
          <div className="callout">
            取得結果: <span className="mono">{String(jpxDownloadState.data.saved_path ?? "-")}</span>
            {jpxDownloadState.data.count ? (
              <>
                <br />
                保存件数: {String(jpxDownloadState.data.count)} / 東証プライム:{" "}
                {String(jpxDownloadState.data.prime_count ?? 0)}
              </>
            ) : null}
            {jpxDownloadState.data.converted_path ? (
              <>
                <br />
                変換CSV:{" "}
                <span className="mono">{String(jpxDownloadState.data.converted_path)}</span>
              </>
            ) : null}
            <br />
            {String(jpxDownloadState.data.hint ?? "")}
          </div>
        )}
        {jpxListedState.data && (
          <div className="callout">
            保存件数: {String(jpxListedState.data.count ?? 0)} / 東証プライム:{" "}
            {String(jpxListedState.data.prime_count ?? 0)}
            {jpxListedState.data.saved_path ? (
              <>
                <br />
                保存先: <span className="mono">{String(jpxListedState.data.saved_path)}</span>
              </>
            ) : null}
          </div>
        )}
      </div>

      <div className="edinet-ingest">
        <div className="report-audit-head">
          <div>
            <h3>EDINET（公的API）から財務数値を取得</h3>
            <p className="hint">
              金融庁EDINETの公式開示データから営業CF・自己資本比率・配当性向などの数値を取得し、RAGと財務データに反映します。
            </p>
          </div>
          <span className={`badge ${edinetStatusState.data?.api_key_configured ? "safe" : "warn"}`}>
            APIキー {edinetStatusState.data?.api_key_configured ? "設定済み" : "未設定"}
          </span>
        </div>
        <p className="hint">
          取得後はこの画面の財務データパスを自動で更新します。以後の保有分析・候補抽出・詳細・レポートは同じデータを参照します。
        </p>
        {edinetStatusState.data && (
          <div className="callout">
            <b>更新状態</b>
            <p className="hint">
              APIキー:{" "}
              {edinetStatusState.data.api_key_configured ? "設定済み" : "未設定"} / 読み込み元:{" "}
              {edinetApiKeySourceLabel(edinetStatusState.data.api_key_source)}
            </p>
            <p className="hint">
              財務CSVの自動更新にはEDINET APIキーが必要です。未設定の場合は、EDINET/JPXの公式ページをRAG用に取得します。
            </p>
          </div>
        )}
        <div className="form">
          <Field label="EDINET API KEY（一時入力・保存しない）">
            <input
              type="password"
              value={edinetApiKeyInput}
              onChange={(e) => setEdinetApiKeyInput(e.target.value)}
              placeholder="EDINET API KEY"
              autoComplete="off"
            />
          </Field>
          <button onClick={applyEdinetApiKey} disabled={edinetStatusState.loading}>
            API KEYを反映
          </button>
          <Field label="EDINET registry（YAML）">
            <input value={edinetRegistry} onChange={(e) => setEdinetRegistry(e.target.value)} />
          </Field>
          <Field label="出力ディレクトリ">
            <input value={edinetOutputDir} onChange={(e) => setEdinetOutputDir(e.target.value)} />
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
            onClick={() => runEdinetIngest(7, 0)}
            disabled={edinetState.loading}
          >
            ワンクリック自動更新
          </button>
          <button onClick={() => runEdinetIngest()} disabled={edinetState.loading}>
            設定値で更新
          </button>
          <button onClick={() => runEdinetIngest(31, 1)} disabled={edinetState.loading}>
            1年分をバックフィル
          </button>
          <button
            onClick={() => void edinetStatusState.run(() => api<Json>("/api/edinet/status"))}
            disabled={edinetStatusState.loading}
          >
            キー状態を再確認
          </button>
        </div>
        <Status loading={edinetStatusState.loading} error={edinetStatusState.error} />
        <Status loading={edinetState.loading} error={edinetState.error} />
        {edinetState.data && (
          <div className="callout">
            <b>{refreshModeLabel(edinetState.data.mode)}</b>
            <p className="hint">{String(edinetState.data.hint ?? "")}</p>
            {edinetState.data.financials_updated === false ? (
              <p>
                財務CSV: <span className="mono">未更新</span> / 取得許可:{" "}
                {String((edinetState.data.scrape as Json | undefined)?.allowed_sources_count ?? 0)}
                件 / ブロック:{" "}
                {String(
                  Array.isArray((edinetState.data.scrape as Json | undefined)?.blocked_results)
                    ? ((edinetState.data.scrape as Json).blocked_results as Json[]).length
                    : 0,
                )}
                件
              </p>
            ) : (
              <p>
                財務データ:{" "}
                <span className="mono">
                  {String(edinetState.data.financials_csv ?? financialsCsvPath)}
                </span>
                <br />
                取得件数: {String(edinetState.data.ingested_count)} / 対象{" "}
                {String(edinetState.data.targets_count)}社（スキャン日数{" "}
                {Array.isArray(edinetState.data.scanned_dates)
                  ? edinetState.data.scanned_dates.length
                  : 0}
                ）
              </p>
            )}
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
            <DividendQualityPanel quality={edinetState.data.dividend_quality as Json | undefined} />
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

      <div className="edinet-ingest manual-financials-panel">
        <div className="report-audit-head">
          <div>
            <h3>手動EDINET財務データ</h3>
            <p className="hint">
              データを貼り付けるかファイルから読み込み、検証してから現在の財務データとして保存します。
            </p>
          </div>
          <span className="badge">データ</span>
        </div>
        <div className="form">
          <Field label="保存先 financials.csv">
            <input
              value={manualFinancialsOutputPath}
              onChange={(e) => setManualFinancialsOutputPath(e.target.value)}
            />
          </Field>
          <button onClick={loadSampleFinancials}>サンプルデータを読み込む</button>
          <label className="button-like">
            ファイルを読み込む
            <input type="file" accept=".csv,text/csv" onChange={importFinancialsFile} />
          </label>
          <button onClick={downloadManualFinancialsCsv}>データをダウンロード</button>
          <button onClick={previewManualFinancials} disabled={financialsState.loading}>
            検証/プレビュー
          </button>
          <button
            className="primary"
            onClick={saveManualFinancials}
            disabled={financialsState.loading || !manualFinancialsCsv.trim()}
          >
            保存して分析に反映
          </button>
          <button onClick={compareCurrentFinancials} disabled={financialsState.loading}>
            現在の財務データを確認
          </button>
        </div>
        <Field label="財務データ">
          <textarea
            rows={9}
            value={manualFinancialsCsv}
            onChange={(e) => setManualFinancialsCsv(e.target.value)}
          />
        </Field>
        <Status loading={financialsState.loading} error={financialsState.error} />
        {financialsState.data && (
          <div className="callout">
            行数: {String(financialsState.data.count ?? 0)} / 会社数:{" "}
            {String(financialsState.data.company_count ?? 0)}
            {financialsState.data.saved_path ? (
              <>
                <br />
                保存先: <span className="mono">{String(financialsState.data.saved_path)}</span>
              </>
            ) : null}
            <DividendQualityPanel quality={financialsState.data.dividend_quality as Json | undefined} />
            {financialsState.data.comparison &&
              Array.isArray((financialsState.data.comparison as Json).companies) && (
                <EdinetComparisonTable
                  companies={(financialsState.data.comparison as Json).companies as Json[]}
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

function DividendQualityPanel(props: { quality?: Json | null }) {
  const quality = props.quality;
  if (!quality) return null;
  const checks = Array.isArray(quality.checks) ? (quality.checks as Json[]) : [];
  return (
    <div className="edinet-comparison">
      <h4>配当値チェック</h4>
      <dl className="mini-stats">
        <div>
          <dt>状態</dt>
          <dd>{String(quality.status ?? "ok")}</dd>
        </div>
        <div>
          <dt>補正</dt>
          <dd>{String(quality.corrected_count ?? 0)}</dd>
        </div>
        <div>
          <dt>警告</dt>
          <dd>{String(quality.warning_count ?? 0)}</dd>
        </div>
      </dl>
      {checks.length > 0 && (
        <table className="grid">
          <thead>
            <tr>
              <th>銘柄</th>
              <th>年度</th>
              <th>元値</th>
              <th>確認後</th>
              <th>理由</th>
            </tr>
          </thead>
          <tbody>
            {checks.slice(0, 8).map((check, index) => (
              <tr key={`${String(check.ticker)}-${String(check.fiscal_year)}-${index}`}>
                <td className="mono">{String(check.ticker ?? "-")}</td>
                <td className="mono">{String(check.fiscal_year ?? "-")}</td>
                <td className="mono">{formatCompactNumber(check.original_value)}</td>
                <td className="mono">{formatCompactNumber(check.checked_value)}</td>
                <td>{String(check.code ?? check.message ?? "-")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="hint">
        1株配当が過年度比で10倍/100倍に見える場合、取り込み時に単位を補正します。
        高すぎる利回りは警告として残します。
      </p>
    </div>
  );
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

function SimulateTab({
  financialsCsvPath,
  onFinancialsCsvPathChange,
  onOpenData,
}: {
  financialsCsvPath: string;
  onFinancialsCsvPathChange: (value: string) => void;
  onOpenData: () => void;
}) {
  const [budget, setBudget] = useState(1000000);
  const [years, setYears] = useState(10);
  const [growth, setGrowth] = useState(0);
  const [reinvest, setReinvest] = useState(true);
  const [weightMode, setWeightMode] = useState("equal");
  const [optimizeMode, setOptimizeMode] = useState("none");
  const [targetDividend, setTargetDividend] = useState(0);
  const [netTarget, setNetTarget] = useState(true);
  const [universeScope, setUniverseScope] = useState("prime");
  const [universe, setUniverse] = useState<Json[]>([]);
  const [universeMeta, setUniverseMeta] = useState<Json | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [pick, setPick] = useState("");
  const [busy, setBusy] = useState(false);
  const { loading, error, data, run } = useAsync<Json>();

  useEffect(() => {
    let active = true;
    setPick("");
    api<Json>("/api/portfolio/universe", {
      financials_csv: financialsCsvPath,
      scope: universeScope,
    })
      .then((r) => {
        if (active) {
          setUniverse(Array.isArray(r.universe) ? r.universe : []);
          setUniverseMeta(r);
        }
      })
      .catch(() => {
        if (active) {
          setUniverse([]);
          setUniverseMeta(null);
        }
      });
    return () => {
      active = false;
    };
  }, [financialsCsvPath, universeScope]);

  const appendHolding = (next: Holding) =>
    setHoldings((current) =>
      current.some((h) => h.ticker === next.ticker) ? current : [...current, next],
    );

  const addHolding = () => {
    const u = universe.find((x) => String(x.ticker) === pick);
    if (!u) return;
    appendHolding({
      ticker: String(u.ticker),
      name: String(u.name ?? ""),
      price: Number(u.price) || 0,
      shares: 100,
      amount: 100000,
      nisa: false,
    });
  };

  const addSearchedSecurity = (security: Json) => {
    const ticker = String(security.ticker ?? security.code ?? "").trim();
    if (!ticker) return;
    appendHolding({
      ticker,
      name: String(security.name ?? ""),
      price: Number(security.price) || 0,
      shares: 100,
      amount: 100000,
      nisa: false,
    });
  };
  const patch = (i: number, p: Partial<Holding>) =>
    setHoldings(holdings.map((h, idx) => (idx === i ? { ...h, ...p } : h)));
  const removeAt = (i: number) => setHoldings(holdings.filter((_, idx) => idx !== i));

  const fetchPrices = async (tickers: string[]): Promise<Record<string, number | null>> => {
    const r = await api<Json>("/api/market/prices", { tickers });
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
        financials_csv: financialsCsvPath,
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
        financials_csv: financialsCsvPath,
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
          <p className="eyebrow">試算</p>
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
        <Field label="選択対象">
          <select value={universeScope} onChange={(event) => setUniverseScope(event.target.value)}>
            {MARKET_SCOPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="銘柄を選択（安全性順）">
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">― 選択 ―</option>
            {universe.map((u) => (
              <option key={String(u.ticker)} value={String(u.ticker)}>
                {String(u.ticker)} {String(u.name ?? "")}
                {u.is_nikkei225 ? " / 日経225" : ""}
                {u.is_prime ? " / Prime" : ""}
                （安全性 {Number(u.safety).toFixed(2)}）
              </option>
            ))}
          </select>
        </Field>
        <button onClick={addHolding} disabled={!pick}>
          ＋ 追加（手動）
        </button>
        <button onClick={() => void updatePrices()} disabled={busy || holdings.length === 0}>
          市場価格を更新
        </button>
      </div>

      {universe.length === 0 && (
        <p className="hint">
          試算銘柄リストが空です。{String(universeMeta?.hint ?? "")}
          上部の財務データパスを確認するか、Dataタブで市場区分データ/EDINET財務データを取得してください。
          下の証券コード検索からも追加できます。
        </p>
      )}
      <div className="subpanel csv-manual-panel">
        <SecuritySearch
          financialsCsvPath={financialsCsvPath}
          title="シミュレート用の証券コード検索"
          onUseSample={() => onFinancialsCsvPathChange(SAMPLE_FINANCIALS_PATH)}
          onOpenData={onOpenData}
          onSelect={addSearchedSecurity}
        />
      </div>

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
          <p className="eyebrow">運用</p>
          <h2>予算 / キャッシュ</h2>
        </div>
        <span className="badge">保守</span>
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
  scoring: ScoringTab,
  forecast: ForecastTab,
  analysis: AnalysisTab,
  ops: OpsTab,
} as const;
