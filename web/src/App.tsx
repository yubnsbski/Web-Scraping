import { useMemo, useState, type ReactNode } from "react";
import { api } from "./api";

type Json = Record<string, any>;
type TabId = "dashboard" | "data" | "holdings" | "screen" | "detail" | "report" | "chat";

const FINANCIALS_PATH = "examples/financials_sample.csv";

const SAMPLE_HOLDINGS_CSV = [
  "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source,current_price,annual_income,distribution_per_unit,data_provider,price_as_of",
  "stock,8306,三菱UFJフィナンシャル・グループ,100,1000,tokutei,nisa_growth,user_csv,1200,,,user_csv,2026-06-10",
  "stock,9433,KDDI,100,2500,tokutei,taxable,user_csv,2708.5,,,yfinance,2026-06-16",
  "fund,FND001,低コスト全世界株式,120,10000,nisa,nisa_tsumitate,user_csv,12500,,25,user_csv,2026-06-10",
].join("\n");

const SAMPLE_FUNDS_CSV = [
  "fund_code,name,asset_class,expense_ratio,distribution_policy,nisa_eligible,provider_id,diversification_score",
  "FND001,低コスト全世界株式,global_equity,0.12,reinvest,true,user_csv,0.95",
  "FND002,債券バランス型,balanced,0.35,distribution,true,user_csv,0.80",
  "FND999,高コストテーマ型,theme,1.20,distribution,false,user_csv,0.40",
].join("\n");

const TABS: Array<{ id: TabId; label: string; short: string }> = [
  { id: "dashboard", label: "全体", short: "全体" },
  { id: "data", label: "データ更新", short: "更新" },
  { id: "holdings", label: "保有分析", short: "保有" },
  { id: "screen", label: "候補抽出", short: "候補" },
  { id: "detail", label: "詳細", short: "詳細" },
  { id: "report", label: "レポート", short: "報告" },
  { id: "chat", label: "AI確認", short: "AI" },
];

export function App() {
  const [tab, setTab] = useState<TabId>("dashboard");
  const [holdingsCsv, setHoldingsCsv] = useState(SAMPLE_HOLDINGS_CSV);
  const [fundsCsv, setFundsCsv] = useState(SAMPLE_FUNDS_CSV);
  const [financialsPath, setFinancialsPath] = useState(FINANCIALS_PATH);
  const [marketSnapshot, setMarketSnapshot] = useState<Json | null>(null);
  const [analysis, setAnalysis] = useState<Json | null>(null);
  const [candidates, setCandidates] = useState<Json | null>(null);
  const [report, setReport] = useState<Json | null>(null);

  const workState = useMemo(
    () => buildWorkState({ marketSnapshot, analysis, candidates, report }),
    [marketSnapshot, analysis, candidates, report],
  );

  return (
    <div className="app-shell">
      <aside className="side">
        <div className="brand">
          <span>投資支援</span>
          <b>Evidence Desk</b>
        </div>
        <nav className="nav" aria-label="主要画面">
          {TABS.map((item) => (
            <button
              key={item.id}
              className={tab === item.id ? "nav-item active" : "nav-item"}
              onClick={() => setTab(item.id)}
              title={item.label}
            >
              <span>{item.short}</span>
              <b>{item.label}</b>
            </button>
          ))}
        </nav>
        <p className="side-note">売買推奨・自動売買は行いません。判断材料と根拠を整理します。</p>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">non-advisory investment workflow</p>
            <h1>データを更新し、保有を読み、根拠つきで比較する。</h1>
          </div>
          <div className="run-state">
            {workState.map((item) => (
              <span key={item.label} className={item.done ? "state done" : "state"}>
                {item.label}
              </span>
            ))}
          </div>
        </header>

        {tab === "dashboard" && (
          <Dashboard
            marketSnapshot={marketSnapshot}
            analysis={analysis}
            candidates={candidates}
            report={report}
            onMove={setTab}
          />
        )}
        {tab === "data" && (
          <DataUpdatePanel
            financialsPath={financialsPath}
            setFinancialsPath={setFinancialsPath}
            onMarket={setMarketSnapshot}
          />
        )}
        {tab === "holdings" && (
          <HoldingsPanel
            csvText={holdingsCsv}
            setCsvText={setHoldingsCsv}
            financialsPath={financialsPath}
            onAnalysis={setAnalysis}
          />
        )}
        {tab === "screen" && (
          <ScreenPanel
            fundsCsv={fundsCsv}
            setFundsCsv={setFundsCsv}
            financialsPath={financialsPath}
            onCandidates={setCandidates}
          />
        )}
        {tab === "detail" && (
          <DetailPanel
            holdingsCsv={holdingsCsv}
            fundsCsv={fundsCsv}
            financialsPath={financialsPath}
          />
        )}
        {tab === "report" && (
          <ReportPanel
            holdingsCsv={holdingsCsv}
            financialsPath={financialsPath}
            candidates={candidates}
            onReport={setReport}
          />
        )}
        {tab === "chat" && <ChatPanel />}
      </main>
    </div>
  );
}

function Dashboard(props: {
  marketSnapshot: Json | null;
  analysis: Json | null;
  candidates: Json | null;
  report: Json | null;
  onMove: (tab: TabId) => void;
}) {
  const summary = props.analysis?.summary ?? {};
  const kpis = [
    { label: "評価額", value: yen(summary.market_value), active: props.analysis !== null },
    { label: "候補", value: String(props.candidates?.count ?? "-"), active: props.candidates !== null },
    { label: "市場データ", value: marketCount(props.marketSnapshot), active: props.marketSnapshot !== null },
    { label: "レポート", value: props.report ? "作成済み" : "-", active: props.report !== null },
  ];
  return (
    <section className="screen">
      <div className="screen-head">
        <div>
          <h2>作業の現在地</h2>
          <p>まずデータ更新、次に保有分析、最後に候補とレポートを確認します。</p>
        </div>
      </div>
      <div className="kpi-grid">
        {kpis.map((kpi) => (
          <article className={kpi.active ? "kpi active" : "kpi"} key={kpi.label}>
            <span>{kpi.label}</span>
            <b>{kpi.value}</b>
          </article>
        ))}
      </div>
      <div className="flow">
        <FlowStep title="1. 市場データ更新" body="Yahoo由来の価格系列・市場財務指標を更新します。" onClick={() => props.onMove("data")} />
        <FlowStep title="2. 保有分析" body="CSVまたは手入力を読み、評価額・NISA・配当を集計します。" onClick={() => props.onMove("holdings")} />
        <FlowStep title="3. 候補抽出" body="条件一致だけを表示します。売買推奨は出しません。" onClick={() => props.onMove("screen")} />
        <FlowStep title="4. レポート" body="根拠・計算式・免責をまとめた月次レポートを生成します。" onClick={() => props.onMove("report")} />
      </div>
    </section>
  );
}

function DataUpdatePanel(props: {
  financialsPath: string;
  setFinancialsPath: (value: string) => void;
  onMarket: (value: Json) => void;
}) {
  const [mode, setMode] = useState<"financials" | "ohlcv" | "intraday">("financials");
  const [scope, setScope] = useState<"tickers" | "nikkei225" | "financials_csv">("tickers");
  const [tickers, setTickers] = useState("8306,9433,7203");
  const [range, setRange] = useState("1mo");
  const [maxCount, setMaxCount] = useState("20");
  const { loading, error, data, run } = useAsync<Json>();
  const tickerList = splitTickers(tickers);
  const needsTickers = mode === "intraday" || scope === "tickers";
  const canUseUniverse = mode !== "intraday";

  const update = async () => {
    const endpoint =
      mode === "financials"
        ? "/api/market/financials"
        : mode === "ohlcv"
          ? "/api/market/bars/universe"
          : "/api/market/intraday";
    const body: Json = {
      max_count: Number(maxCount) || 0,
      save_csv: mode !== "intraday",
    };
    if (mode === "ohlcv") body.range = range;
    if (needsTickers) body.tickers = tickerList;
    else body.universe = scope;
    if (scope === "financials_csv") body.financials_csv = props.financialsPath;
    const result = await run(() => api<Json>(endpoint, body));
    if (result) props.onMarket(result);
  };

  return (
    <section className="screen">
      <ScreenTitle title="データ更新" body="取得対象とデータ種別を選び、1つのボタンでCSVへ反映します。" />
      <div className="form-grid">
        <Field label="データ種別">
          <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
            <option value="financials">市場財務指標</option>
            <option value="ohlcv">株価四本値・出来高</option>
            <option value="intraday">当日分足</option>
          </select>
        </Field>
        <Field label="対象">
          <select
            value={canUseUniverse ? scope : "tickers"}
            disabled={!canUseUniverse}
            onChange={(e) => setScope(e.target.value as typeof scope)}
          >
            <option value="tickers">入力した銘柄</option>
            <option value="nikkei225">日経225</option>
            <option value="financials_csv">財務CSVの全銘柄</option>
          </select>
        </Field>
        <Field label="上限件数">
          <input value={maxCount} inputMode="numeric" onChange={(e) => setMaxCount(e.target.value)} />
        </Field>
        {mode === "ohlcv" && (
          <Field label="期間">
            <select value={range} onChange={(e) => setRange(e.target.value)}>
              <option value="5d">5日</option>
              <option value="1mo">1か月</option>
              <option value="3mo">3か月</option>
              <option value="1y">1年</option>
            </select>
          </Field>
        )}
        <Field label="財務CSV">
          <input value={props.financialsPath} onChange={(e) => props.setFinancialsPath(e.target.value)} />
        </Field>
        {needsTickers && (
          <Field label="銘柄コード">
            <input value={tickers} onChange={(e) => setTickers(e.target.value)} placeholder="8306,9433" />
          </Field>
        )}
      </div>
      <ActionRow>
        <button className="primary" disabled={loading || (needsTickers && tickerList.length === 0)} onClick={() => void update()}>
          {loading ? "更新中..." : "更新する"}
        </button>
      </ActionRow>
      <Status loading={loading} error={error} />
      {data && <MarketResult data={data} mode={mode} />}
    </section>
  );
}

function HoldingsPanel(props: {
  csvText: string;
  setCsvText: (value: string) => void;
  financialsPath: string;
  onAnalysis: (value: Json) => void;
}) {
  const validation = useAsync<Json>();
  const analysis = useAsync<Json>();
  const template = useAsync<Json>();

  const loadTemplate = async () => {
    const result = await template.run(() => api<Json>("/api/holdings/template", { include_examples: true }));
    if (result?.csv_text) props.setCsvText(String(result.csv_text));
  };
  const validate = () => validation.run(() => api<Json>("/api/holdings/validate", { csv_text: props.csvText }));
  const analyze = async () => {
    const result = await analysis.run(() =>
      api<Json>("/api/portfolio/analyze", {
        csv_text: props.csvText,
        financials_csv: props.financialsPath,
      }),
    );
    if (result) props.onAnalysis(result);
  };

  return (
    <section className="screen">
      <ScreenTitle title="保有分析" body="CSVを貼るだけで、評価額・損益・NISA区分・配当見込みを集計します。" />
      <textarea value={props.csvText} onChange={(e) => props.setCsvText(e.target.value)} spellCheck={false} />
      <ActionRow>
        <button onClick={() => void loadTemplate()}>テンプレート</button>
        <button onClick={() => void validate()}>検証</button>
        <button className="primary" onClick={() => void analyze()}>
          分析
        </button>
      </ActionRow>
      <Status loading={template.loading || validation.loading || analysis.loading} error={template.error ?? validation.error ?? analysis.error} />
      {validation.data && <ValidationResult data={validation.data} />}
      {analysis.data && <AnalysisResult data={analysis.data} />}
    </section>
  );
}

function ScreenPanel(props: {
  fundsCsv: string;
  setFundsCsv: (value: string) => void;
  financialsPath: string;
  onCandidates: (value: Json) => void;
}) {
  const [minEquity, setMinEquity] = useState("30");
  const [maxExpense, setMaxExpense] = useState("0.3");
  const [nisaOnly, setNisaOnly] = useState(true);
  const [excludeCut, setExcludeCut] = useState(true);
  const state = useAsync<Json>();

  const runScreen = async () => {
    const result = await state.run(() =>
      api<Json>("/api/candidates/screen", {
        asset_types: ["stock", "fund"],
        funds_csv_text: props.fundsCsv,
        financials_csv: props.financialsPath,
        min_equity_ratio: Number(minEquity) || undefined,
        max_expense_ratio: Number(maxExpense) || undefined,
        nisa_eligible_only: nisaOnly,
        exclude_dividend_cut: excludeCut,
      }),
    );
    if (result) props.onCandidates(result);
  };

  return (
    <section className="screen">
      <ScreenTitle title="候補抽出" body="条件に一致した比較対象だけを表示します。おすすめ・買い指示は出しません。" />
      <div className="form-grid">
        <Field label="自己資本比率下限">
          <input value={minEquity} onChange={(e) => setMinEquity(e.target.value)} inputMode="decimal" />
        </Field>
        <Field label="信託報酬上限">
          <input value={maxExpense} onChange={(e) => setMaxExpense(e.target.value)} inputMode="decimal" />
        </Field>
        <Check label="NISA対象のみ" checked={nisaOnly} onChange={setNisaOnly} />
        <Check label="減配履歴を除外" checked={excludeCut} onChange={setExcludeCut} />
      </div>
      <textarea value={props.fundsCsv} onChange={(e) => props.setFundsCsv(e.target.value)} spellCheck={false} />
      <ActionRow>
        <button className="primary" onClick={() => void runScreen()}>
          条件で抽出
        </button>
      </ActionRow>
      <Status loading={state.loading} error={state.error} />
      {state.data && <CandidateTable data={state.data} />}
    </section>
  );
}

function DetailPanel(props: { holdingsCsv: string; fundsCsv: string; financialsPath: string }) {
  const [code, setCode] = useState("8306");
  const [assetType, setAssetType] = useState<"stock" | "fund">("stock");
  const state = useAsync<Json>();
  const load = () =>
    state.run(() =>
      api<Json>("/api/investment/detail", {
        code,
        asset_type: assetType,
        csv_text: props.holdingsCsv,
        funds_csv_text: props.fundsCsv,
        financials_csv: props.financialsPath,
      }),
    );
  return (
    <section className="screen">
      <ScreenTitle title="銘柄・投信詳細" body="保有、財務、投信プロファイルを1コードに集約して確認します。" />
      <div className="form-grid tight">
        <Field label="コード">
          <input value={code} onChange={(e) => setCode(e.target.value)} />
        </Field>
        <Field label="種別">
          <select value={assetType} onChange={(e) => setAssetType(e.target.value as typeof assetType)}>
            <option value="stock">国内株式</option>
            <option value="fund">投資信託</option>
          </select>
        </Field>
      </div>
      <ActionRow>
        <button className="primary" onClick={() => void load()}>
          詳細を表示
        </button>
      </ActionRow>
      <Status loading={state.loading} error={state.error} />
      {state.data && <DetailResult data={state.data} />}
    </section>
  );
}

function ReportPanel(props: {
  holdingsCsv: string;
  financialsPath: string;
  candidates: Json | null;
  onReport: (value: Json) => void;
}) {
  const [targetDividend, setTargetDividend] = useState("10000");
  const state = useAsync<Json>();
  const create = async () => {
    const result = await state.run(() =>
      api<Json>("/api/reports/investment-monthly", {
        csv_text: props.holdingsCsv,
        financials_csv: props.financialsPath,
        candidates: props.candidates?.results ?? [],
        target_annual_dividend: Number(targetDividend) || 0,
        optimization: "balanced",
      }),
    );
    if (result) props.onReport(result);
  };
  return (
    <section className="screen">
      <ScreenTitle title="投資レポート" body="保有状況、集中リスク、配当見込み、候補、根拠、免責をまとめます。" />
      <div className="form-grid tight">
        <Field label="目標年間配当">
          <input value={targetDividend} onChange={(e) => setTargetDividend(e.target.value)} inputMode="numeric" />
        </Field>
      </div>
      <ActionRow>
        <button className="primary" onClick={() => void create()}>
          レポート生成
        </button>
      </ActionRow>
      <Status loading={state.loading} error={state.error} />
      {state.data && <ReportResult data={state.data} />}
    </section>
  );
}

function ChatPanel() {
  const [query, setQuery] = useState("KDDIの配当利回りと根拠を、投資助言にならない形で確認して");
  const state = useAsync<Json>();
  const ask = () =>
    state.run(() =>
      api<Json>("/api/rag/answer", {
        query,
        limit: 5,
        call_real_api: false,
      }),
    );
  return (
    <section className="screen">
      <ScreenTitle title="AI確認" body="RAGの根拠を確認するための補助チャットです。数値判断は決定論エンジンを優先します。" />
      <textarea value={query} onChange={(e) => setQuery(e.target.value)} />
      <ActionRow>
        <button className="primary" onClick={() => void ask()}>
          確認する
        </button>
      </ActionRow>
      <Status loading={state.loading} error={state.error} />
      {state.data && (
        <div className="answer">
          <h3>回答</h3>
          <p>{String(state.data.answer ?? state.data.text ?? "回答がありません。")}</p>
          <JsonDetails data={state.data} />
        </div>
      )}
    </section>
  );
}

function MarketResult({ data, mode }: { data: Json; mode: string }) {
  if (mode === "financials") {
    const rows = Object.entries((data.financials ?? {}) as Record<string, Json>).map(([ticker, row]) => ({
      ticker,
      ...row,
    }));
    return (
      <ResultBlock title="市場財務指標" meta={`保存先: ${String(data.output_path ?? "-")}`}>
        <SimpleTable
          rows={rows}
          columns={[
            ["ticker", "コード"],
            ["name", "名称"],
            ["price", "株価"],
            ["dividend_yield_percent", "配当利回り"],
            ["dps", "1株配当"],
            ["per", "PER"],
            ["pbr", "PBR"],
          ]}
        />
      </ResultBlock>
    );
  }
  const key = mode === "intraday" ? "intraday" : "ohlcv";
  const series = (data[key] ?? {}) as Record<string, Json[]>;
  const firstTicker = Object.keys(series)[0];
  return (
    <ResultBlock title="価格系列" meta={`保存先: ${String(data.daily_bars_path ?? data.output_dir ?? "-")}`}>
      {firstTicker ? (
        <SimpleTable
          rows={(series[firstTicker] ?? []).slice(0, 30)}
          columns={mode === "intraday" ? [["time", "時刻"], ["close", "終値"], ["volume", "出来高"]] : [["date", "日付"], ["open", "始値"], ["high", "高値"], ["low", "安値"], ["close", "終値"], ["volume", "出来高"]]}
        />
      ) : (
        <p className="muted">表示できる行がありません。</p>
      )}
    </ResultBlock>
  );
}

function AnalysisResult({ data }: { data: Json }) {
  const rows = Array.isArray(data.holdings) ? data.holdings : [];
  return (
    <ResultBlock title="分析結果" meta={`評価額: ${yen(data.summary?.market_value)}`}>
      <SimpleTable
        rows={rows}
        columns={[
          ["ticker_or_fund_code", "コード"],
          ["name", "名称"],
          ["market_value", "評価額"],
          ["unrealized_pnl", "損益"],
          ["tax_wrapper", "口座"],
        ]}
      />
      <JsonDetails data={data.summary ?? {}} />
    </ResultBlock>
  );
}

function ValidationResult({ data }: { data: Json }) {
  const ok = Boolean(data.valid ?? data.error_count === 0);
  return (
    <ResultBlock title={ok ? "CSV検証 OK" : "CSV検証で確認が必要"} meta={`${String(data.count ?? 0)} 行`}>
      <JsonDetails data={data} />
    </ResultBlock>
  );
}

function CandidateTable({ data }: { data: Json }) {
  const rows = Array.isArray(data.results) ? data.results : [];
  return (
    <ResultBlock title="候補抽出結果" meta={`${String(data.count ?? rows.length)} 件`}>
      <SimpleTable
        rows={rows}
        columns={[
          ["code", "コード"],
          ["name", "名称"],
          ["asset_type", "種別"],
          ["score", "スコア"],
          ["reason", "根拠"],
        ]}
      />
    </ResultBlock>
  );
}

function DetailResult({ data }: { data: Json }) {
  return (
    <ResultBlock title="詳細" meta={data.available ? "表示可能" : "未検出"}>
      <JsonDetails data={data} />
    </ResultBlock>
  );
}

function ReportResult({ data }: { data: Json }) {
  const kpis = Array.isArray(data.kpis) ? data.kpis : [];
  return (
    <ResultBlock title="生成結果" meta={String(data.publish_audit?.status ?? "未監査")}>
      <SimpleTable
        rows={kpis}
        columns={[
          ["label", "項目"],
          ["value", "値"],
          ["formula", "計算式"],
          ["last_updated", "更新"],
        ]}
      />
      <JsonDetails data={data} />
    </ResultBlock>
  );
}

function SimpleTable({ rows, columns }: { rows: Json[]; columns: Array<[string, string]> }) {
  if (rows.length === 0) return <p className="muted">表示できるデータがありません。</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map(([, label]) => (
              <th key={label}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 100).map((row, index) => (
            <tr key={`${String(row.code ?? row.ticker ?? row.name ?? "row")}-${index}`}>
              {columns.map(([key]) => (
                <td key={key}>{formatCell(row[key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResultBlock({ title, meta, children }: { title: string; meta?: string; children: ReactNode }) {
  return (
    <section className="result">
      <header>
        <h3>{title}</h3>
        {meta && <span>{meta}</span>}
      </header>
      {children}
    </section>
  );
}

function FlowStep(props: { title: string; body: string; onClick: () => void }) {
  return (
    <button className="flow-step" onClick={props.onClick}>
      <b>{props.title}</b>
      <span>{props.body}</span>
    </button>
  );
}

function ScreenTitle({ title, body }: { title: string; body: string }) {
  return (
    <div className="screen-head">
      <div>
        <h2>{title}</h2>
        <p>{body}</p>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

function ActionRow({ children }: { children: ReactNode }) {
  return <div className="actions">{children}</div>;
}

function Status({ loading, error }: { loading: boolean; error: string | null }) {
  if (loading) return <p className="status">処理中...</p>;
  if (error) return <p className="status error">エラー: {error}</p>;
  return null;
}

function JsonDetails({ data }: { data: unknown }) {
  return (
    <details className="json">
      <summary>JSONを確認</summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
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
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return null;
    } finally {
      setLoading(false);
    }
  }
  return { loading, error, data, run };
}

function buildWorkState(input: {
  marketSnapshot: Json | null;
  analysis: Json | null;
  candidates: Json | null;
  report: Json | null;
}) {
  return [
    { label: "データ", done: input.marketSnapshot !== null },
    { label: "保有", done: input.analysis !== null },
    { label: "候補", done: input.candidates !== null },
    { label: "報告", done: input.report !== null },
  ];
}

function splitTickers(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function marketCount(value: Json | null): string {
  if (!value) return "-";
  if (value.matched_tickers !== undefined) return `${String(value.matched_tickers)}銘柄`;
  if (value.daily_bars_count !== undefined) return `${String(value.daily_bars_count)}行`;
  return "取得済み";
}

function yen(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric === 0) return "-";
  return `${Math.round(numeric).toLocaleString("ja-JP")}円`;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return value.toLocaleString("ja-JP", { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "はい" : "いいえ";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
