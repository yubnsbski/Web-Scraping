import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";

type Json = Record<string, any>;
type TabId = "dashboard" | "data" | "holdings" | "screen" | "detail" | "report" | "chat";
type DetailRequest = { code: string; assetType: "stock" | "fund"; version: number };

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
  const [detailRequest, setDetailRequest] = useState<DetailRequest>({
    code: "8306",
    assetType: "stock",
    version: 0,
  });

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
            onOpenDetail={(code) => {
              setDetailRequest((prev) => ({ code, assetType: "stock", version: prev.version + 1 }));
              setTab("detail");
            }}
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
            onOpenDetail={(code, assetType) => {
              setDetailRequest((prev) => ({ code, assetType, version: prev.version + 1 }));
              setTab("detail");
            }}
          />
        )}
        {tab === "detail" && (
          <DetailPanel
            holdingsCsv={holdingsCsv}
            fundsCsv={fundsCsv}
            financialsPath={financialsPath}
            detailRequest={detailRequest}
            onMove={setTab}
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
  onOpenDetail: (code: string) => void;
}) {
  const [mode, setMode] = useState<"financials" | "ohlcv" | "intraday" | "inbox">("financials");
  const [scope, setScope] = useState<"tickers" | "nikkei225" | "financials_csv">("tickers");
  const [tickers, setTickers] = useState("8306,9433,7203");
  const [range, setRange] = useState("1mo");
  const [maxCount, setMaxCount] = useState("20");
  const { loading, error, data, run } = useAsync<Json>();
  const inventory = useAsync<Json>();
  const financialsPreview = useAsync<Json>();
  const tickerList = splitTickers(tickers);
  const isInbox = mode === "inbox";
  const needsTickers = !isInbox && (mode === "intraday" || scope === "tickers");
  const canUseUniverse = !isInbox && mode !== "intraday";

  const refreshInventory = () =>
    inventory.run(() =>
      api<Json>("/api/data/status", {
        financials_csv: props.financialsPath,
      }),
    );

  const refreshFinancialsPreview = () =>
    financialsPreview.run(() =>
      api<Json>("/api/financials/preview", {
        financials_csv: props.financialsPath,
        limit: 20,
      }),
    );

  const refreshDataView = () => {
    void refreshInventory();
    void refreshFinancialsPreview();
  };

  useEffect(() => {
    refreshDataView();
  }, [props.financialsPath]);

  const executeUpdate = async (
    selectedMode: "financials" | "ohlcv" | "intraday" | "inbox" = mode,
    selectedScope: "tickers" | "nikkei225" | "financials_csv" = scope,
  ) => {
    if (selectedMode === "inbox") {
      const result = await run(() => api<Json>("/api/market/inbox", {}));
      if (result) {
        props.onMarket(result);
        refreshDataView();
      }
      return;
    }
    const endpoint =
      selectedMode === "financials"
        ? "/api/market/financials"
        : selectedMode === "ohlcv"
          ? "/api/market/bars/universe"
          : "/api/market/intraday";
    const selectedNeedsTickers = selectedMode === "intraday" || selectedScope === "tickers";
    const body: Json = {
      max_count: Number(maxCount) || 0,
      save_csv: selectedMode !== "intraday",
    };
    if (selectedMode === "ohlcv") body.range = range;
    if (selectedNeedsTickers) body.tickers = tickerList;
    else body.universe = selectedScope;
    if (selectedScope === "financials_csv") body.financials_csv = props.financialsPath;
    const result = await run(() => api<Json>(endpoint, body));
    if (result) {
      props.onMarket(result);
      refreshDataView();
    }
  };

  const update = () => executeUpdate();

  const runInventoryAction = async (action: Json) => {
    const type = String(action.action_type ?? "");
    if (type === "market_financials") {
      setMode("financials");
      await executeUpdate("financials", scope);
    } else if (type === "daily_bars") {
      setMode("ohlcv");
      await executeUpdate("ohlcv", scope);
    } else if (type === "price_inbox") {
      setMode("inbox");
      await executeUpdate("inbox", scope);
    }
  };

  return (
    <section className="screen">
      <ScreenTitle title="データ更新" body="取得対象とデータ種別を選び、1つのボタンでCSVへ反映します。" />
      <DataInventory
        data={inventory.data}
        loading={inventory.loading}
        error={inventory.error}
        onRefresh={refreshDataView}
        onRunAction={(action) => void runInventoryAction(action)}
        runningAction={loading}
      />
      <FinancialsPreviewPanel
        data={financialsPreview.data}
        loading={financialsPreview.loading}
        error={financialsPreview.error}
        onRefresh={() => void refreshFinancialsPreview()}
        onOpenDetail={props.onOpenDetail}
      />
      <EdinetAcquisitionPanel
        onFinished={refreshDataView}
        onFinancialsCsv={props.setFinancialsPath}
      />
      <div className="form-grid">
        <Field label="データ種別">
          <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
            <option value="financials">市場財務指標</option>
            <option value="ohlcv">株価四本値・出来高</option>
            <option value="intraday">当日分足</option>
            <option value="inbox">ファイル取込（inbox）</option>
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

function EdinetAcquisitionPanel(props: {
  onFinished: () => void;
  onFinancialsCsv: (value: string) => void;
}) {
  const [registryPath, setRegistryPath] = useState("examples/source_registry_nikkei225_edinet.yaml");
  const [outputDir, setOutputDir] = useState("local_docs/edinet");
  const [days, setDays] = useState("7");
  const [years, setYears] = useState("0");
  const [maxPeriods, setMaxPeriods] = useState("1");
  const [indexAfterFetch, setIndexAfterFetch] = useState(true);
  const [jobId, setJobId] = useState("");
  const [job, setJob] = useState<Json | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const status = useAsync<Json>();
  const start = useAsync<Json>();
  const poll = useAsync<Json>();
  const keySave = useAsync<Json>();

  const buildBody = (): Json => ({
    registry_path: registryPath.trim() || "examples/source_registry_nikkei225_edinet.yaml",
    output_dir: outputDir.trim() || "local_docs/edinet",
    days: Number(days) || 7,
    years: Number(years) || 0,
    max_periods: Number(maxPeriods) || 0,
    index_after_fetch: indexAfterFetch,
  });

  const checkStatus = () => status.run(() => api<Json>("/api/edinet/status", buildBody()));

  const saveApiKey = async () => {
    const result = await keySave.run(() =>
      api<Json>("/api/edinet/api-key", { api_key: apiKeyDraft }),
    );
    if (result?.api_key_configured) {
      setApiKeyDraft("");
      await checkStatus();
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void checkStatus();
    }, 250);
    return () => window.clearTimeout(timer);
  }, [registryPath, outputDir, days, years, maxPeriods, indexAfterFetch]);

  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    const tick = async () => {
      const result = await poll.run(() => api<Json>("/api/jobs/status", { job_id: jobId }));
      if (!alive || !result) return;
      setJob(result);
      const jobStatus = String(result.status ?? "");
      if (jobStatus === "done" || jobStatus === "error") {
        setJobId("");
        if (jobStatus === "done") {
          const resultBody = asJson(result.result);
          const financialsCsv = String(resultBody?.financials_csv ?? status.data?.financials_csv ?? "");
          if (financialsCsv) props.onFinancialsCsv(financialsCsv);
          props.onFinished();
        }
      }
    };
    void tick();
    const interval = window.setInterval(() => {
      void tick();
    }, 2000);
    return () => {
      alive = false;
      window.clearInterval(interval);
    };
  }, [jobId]);

  const startIngest = async () => {
    const plan = await checkStatus();
    if (!plan?.can_start) return;
    const result = await start.run(() => api<Json>("/api/edinet/ingest-async", plan.start_payload));
    if (result?.job_id) {
      setJob(result);
      setJobId(String(result.job_id));
    }
  };

  const plan = status.data;
  const warnings = Array.isArray(plan?.warnings) ? (plan.warnings as unknown[]) : [];
  const sampleTargets = Array.isArray(plan?.sample_targets) ? (plan.sample_targets as Json[]) : [];
  const setup = asJson(plan?.setup_guidance);
  const setupSteps = Array.isArray(setup?.steps) ? (setup.steps as unknown[]) : [];
  const envReload = asJson(plan?.env_reload);
  const envFiles = Array.isArray(envReload?.loaded_files) ? (envReload.loaded_files as unknown[]) : [];
  const envKeys = Array.isArray(envReload?.loaded_keys) ? (envReload.loaded_keys as unknown[]) : [];
  const envDiagnostics = asJson(plan?.env_diagnostics);
  const expectedEnv = Array.isArray(envDiagnostics?.expected)
    ? asJson((envDiagnostics.expected as unknown[])[0])
    : null;
  const relatedEnvKeys = Array.isArray(envDiagnostics?.related_keys)
    ? (envDiagnostics.related_keys as unknown[])
    : [];
  const jobResult = asJson(job?.result);
  const jobStatus = String(job?.status ?? "");
  const jobSeconds = job?.duration_seconds ?? job?.elapsed_seconds;
  const canStart = Boolean(plan?.can_start) && !start.loading && !jobId;

  return (
    <section className="edinet-panel">
      <header className="edinet-head">
        <div>
          <h3>EDINET 財務データ</h3>
          <p>公式開示から財務CSVとRAG用テキストを更新します。取得前に対象数とAPIキー状態だけ確認します。</p>
        </div>
        <InventoryPill
          label="取得準備"
          value={plan?.can_start ? "開始可" : "要確認"}
          tone={plan?.can_start ? "ready" : "warn"}
        />
      </header>
      <div className="edinet-grid">
        <Field label="EDINET registry">
          <input value={registryPath} onChange={(e) => setRegistryPath(e.target.value)} />
        </Field>
        <Field label="出力先">
          <input value={outputDir} onChange={(e) => setOutputDir(e.target.value)} />
        </Field>
        <Field label="直近日数">
          <input value={days} inputMode="numeric" onChange={(e) => setDays(e.target.value)} />
        </Field>
        <Field label="バックフィル年数">
          <input value={years} inputMode="numeric" onChange={(e) => setYears(e.target.value)} />
        </Field>
        <Field label="最大提出書類数">
          <input value={maxPeriods} inputMode="numeric" onChange={(e) => setMaxPeriods(e.target.value)} />
        </Field>
        <Check label="取得後にRAGへ登録" checked={indexAfterFetch} onChange={setIndexAfterFetch} />
      </div>
      <div className="edinet-summary">
        <InventoryPill
          label="APIキー"
          value={plan?.api_key_configured ? "検出済み" : "未検出"}
          tone={plan?.api_key_configured ? "ready" : "error"}
        />
        <InventoryPill label="対象企業" value={`${String(plan?.target_count ?? 0)}件`} tone="muted" />
        <InventoryPill label="財務CSV" value={String(plan?.financials_csv ?? "-")} tone="muted" />
      </div>
      {sampleTargets.length > 0 && (
        <div className="edinet-samples">
          {sampleTargets.slice(0, 6).map((target) => (
            <span key={`${String(target.ticker)}-${String(target.company)}`}>
              {String(target.ticker)} {String(target.company)}
            </span>
          ))}
        </div>
      )}
      {warnings.length > 0 && (
        <ul className="warning-list">
          {warnings.map((warning, index) => (
            <li key={`${String(warning)}-${index}`}>{String(warning)}</li>
          ))}
        </ul>
      )}
      {plan && !plan.api_key_configured && setup && (
        <div className="setup-guide">
          <b>APIキー設定</b>
          <p>バックエンドが {String(setup.env_var ?? "EDINET_API_KEY")} を読めると、取得を開始できます。</p>
          <code>{String(setup.example_line ?? "EDINET_API_KEY=<your-edinet-api-key>")}</code>
          {setupSteps.length > 0 && (
            <ol>
              {setupSteps.map((step, index) => (
                <li key={`${String(step)}-${index}`}>{String(step)}</li>
              ))}
            </ol>
          )}
          <span>{String(setup.secret_policy ?? "APIキーの値は表示しません。")}</span>
          <span>
            env確認:{" "}
            {envFiles.length > 0
              ? [
                  envFiles.map((file) => shortPath(String(file))).join(", "),
                  envKeys.map(String).join(", ") || "キーなし",
                ].join(" / ")
              : "読込ファイルなし"}
          </span>
          {expectedEnv && (
            <span>
              キー診断: {String(expectedEnv.key ?? "EDINET_API_KEY")}=
              {expectedEnv.present ? (expectedEnv.has_value ? "値あり" : "空です") : "未記載"}
              {relatedEnvKeys.length > 0 ? ` / 近いキー: ${relatedEnvKeys.map(String).join(", ")}` : ""}
            </span>
          )}
          <div className="secret-row">
            <input
              type="password"
              value={apiKeyDraft}
              autoComplete="off"
              onChange={(event) => setApiKeyDraft(event.target.value)}
              placeholder="EDINET APIキーを入力"
            />
            <button disabled={keySave.loading || !apiKeyDraft.trim()} onClick={() => void saveApiKey()}>
              {keySave.loading ? "保存中..." : "このPCに保存"}
            </button>
          </div>
          <Status loading={keySave.loading} error={keySave.error} />
          {keySave.data?.api_key_configured && <span>APIキーを保存しました。値は表示しません。</span>}
        </div>
      )}
      <ActionRow>
        <button className="primary" disabled={!canStart} onClick={() => void startIngest()}>
          {start.loading || jobId ? "EDINET取得中..." : "EDINET取得を開始"}
        </button>
        <button disabled={status.loading} onClick={() => void checkStatus()}>
          {status.loading ? "確認中..." : "事前確認"}
        </button>
      </ActionRow>
      <Status loading={status.loading || start.loading || poll.loading} error={status.error || start.error || poll.error} />
      {job && (
        <article className={`job-card ${jobStatus === "error" ? "error" : jobStatus === "done" ? "done" : ""}`}>
          <div className="job-card-head">
            <b>{jobStatusLabel(jobStatus)}</b>
            <span>{formatSeconds(jobSeconds)}</span>
          </div>
          <div className="job-meta">
            <span>ID: {String(job.job_id ?? "")}</span>
            <span>開始: {formatDateTime(job.started_at)}</span>
            {job.finished_at && <span>終了: {formatDateTime(job.finished_at)}</span>}
          </div>
          {jobStatus === "running" && (
            <p>EDINETの提出書類を検索・取得し、財務CSVとRAG用テキストを作成しています。</p>
          )}
          {job.error && <p className="status error">{String(job.error)}</p>}
          {jobResult && (
            <div className="job-result-grid">
              <span>取得件数</span>
              <b>{String(jobResult.ingested_count ?? 0)}件</b>
              <span>財務CSV</span>
              <code>{String(jobResult.financials_csv ?? "-")}</code>
            </div>
          )}
        </article>
      )}
    </section>
  );
}

function DataInventory(props: {
  data: Json | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onRunAction: (action: Json) => void;
  runningAction: boolean;
}) {
  const summary = (props.data?.summary ?? {}) as Json;
  const datasets = Array.isArray(props.data?.datasets) ? (props.data.datasets as Json[]) : [];
  const actions = Array.isArray(props.data?.actions) ? (props.data.actions as Json[]) : [];
  const status = String(props.data?.status ?? "unknown");
  return (
    <section className="inventory">
      <header className="inventory-head">
        <div>
          <h3>データ状態</h3>
          <p>保存済みデータの件数、更新時刻、取得元を確認します。</p>
        </div>
        <button onClick={props.onRefresh} disabled={props.loading}>
          {props.loading ? "確認中..." : "再確認"}
        </button>
      </header>
      {props.error && <p className="status error">エラー: {props.error}</p>}
      <div className="inventory-summary">
        <InventoryPill label="全体" value={statusLabel(status)} tone={statusTone(status)} />
        <InventoryPill label="利用可" value={`${String(summary.ready_count ?? 0)}件`} tone="ready" />
        <InventoryPill label="未取得" value={`${String(summary.missing_count ?? 0)}件`} tone="muted" />
        <InventoryPill label="要更新" value={`${String(summary.stale_count ?? 0)}件`} tone="warn" />
      </div>
      <RefreshActions actions={actions} onRun={props.onRunAction} running={props.runningAction} />
      <div className="inventory-list">
        {datasets.map((item) => (
          <article className="inventory-row" key={String(item.id)}>
            <div>
              <b>{String(item.label ?? item.id)}</b>
              <span>{String(item.role ?? "-")}</span>
              <code>{String(item.path ?? "-")}</code>
            </div>
            <div className="inventory-metrics">
              <span className={`badge ${statusTone(String(item.status ?? ""))}`}>
                {statusLabel(String(item.status ?? ""))}
              </span>
              <span>{String(item.provider ?? "-")}</span>
              <span>{formatRows(item)}</span>
              <span>{formatFreshness(item)}</span>
            </div>
          </article>
        ))}
        {datasets.length === 0 && !props.loading && <p className="muted">まだ状態を取得していません。</p>}
      </div>
    </section>
  );
}

function FinancialsPreviewPanel(props: {
  data: Json | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onOpenDetail: (code: string) => void;
}) {
  const [query, setQuery] = useState("");
  const status = String(props.data?.status ?? "unknown");
  const rows = Array.isArray(props.data?.rows) ? (props.data.rows as Json[]) : [];
  const normalizedQuery = query.trim().toLowerCase();
  const filteredRows = normalizedQuery
    ? rows.filter((row) =>
        [row.ticker, row.name]
          .map((value) => String(value ?? "").toLowerCase())
          .some((value) => value.includes(normalizedQuery)),
      )
    : rows;
  const warnings = Array.isArray(props.data?.warnings) ? (props.data.warnings as unknown[]) : [];
  const years = Array.isArray(props.data?.fiscal_years) ? props.data.fiscal_years.map(String).join(", ") : "-";
  return (
    <section className="inventory financials-preview">
      <header className="inventory-head">
        <div>
          <h3>財務CSVの中身</h3>
          <p>選択中の財務CSVから、銘柄ごとの最新年度データを確認します。</p>
        </div>
        <button onClick={props.onRefresh} disabled={props.loading}>
          {props.loading ? "読込中..." : "再読込"}
        </button>
      </header>
      <Status loading={props.loading} error={props.error} />
      {props.data && (
        <>
          <div className="inventory-summary">
            <InventoryPill label="状態" value={statusLabel(status)} tone={statusTone(status)} />
            <InventoryPill label="銘柄数" value={`${String(props.data.company_count ?? 0)}件`} tone="ready" />
            <InventoryPill label="行数" value={`${String(props.data.row_count ?? 0)}行`} tone="muted" />
            <InventoryPill label="年度" value={years} tone="muted" />
          </div>
          <code className="path-chip">{String(props.data.path ?? "-")}</code>
          {warnings.length > 0 && (
            <ul className="warning-list">
              {warnings.map((warning, index) => (
                <li key={`${String(warning)}-${index}`}>{String(warning)}</li>
              ))}
            </ul>
          )}
          {rows.length > 0 && (
            <div className="inline-filter">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="証券コード・企業名で検索"
                aria-label="財務CSVを検索"
              />
              <span>{filteredRows.length}件表示</span>
            </div>
          )}
          {filteredRows.length > 0 ? (
            <FinancialsPreviewTable rows={filteredRows} onOpenDetail={props.onOpenDetail} />
          ) : (
            <p className="muted">表示できる財務データがありません。</p>
          )}
        </>
      )}
    </section>
  );
}

function FinancialsPreviewTable(props: { rows: Json[]; onOpenDetail: (code: string) => void }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>コード</th>
            <th>企業名</th>
            <th>年度</th>
            <th>営業CF</th>
            <th>自己資本比率</th>
            <th>1株配当</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {props.rows.slice(0, 100).map((row) => {
            const code = String(row.ticker ?? "");
            return (
              <tr key={`${code}-${String(row.fiscal_year ?? "")}`}>
                <td>{code || "-"}</td>
                <td>{formatCell(row.name)}</td>
                <td>{formatCell(row.fiscal_year)}</td>
                <td>{formatCell(row.operating_cf)}</td>
                <td>{formatCell(row.equity_ratio)}</td>
                <td>{formatCell(row.dividend_per_share)}</td>
                <td>
                  <button className="table-action" disabled={!code} onClick={() => props.onOpenDetail(code)}>
                    詳細
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RefreshActions(props: { actions: Json[]; onRun: (action: Json) => void; running: boolean }) {
  if (props.actions.length === 0) {
    return <p className="status">追加で必要な更新はありません。</p>;
  }
  return (
    <div className="refresh-actions">
      <div>
        <h4>次の更新</h4>
        <p>未取得・古いデータから、次に処理すべきものを並べています。</p>
      </div>
      <div className="refresh-action-list">
        {props.actions.map((action) => {
          const safe = Boolean(action.safe_to_run);
          return (
            <article className="refresh-action" key={String(action.id)}>
              <div>
                <b>{String(action.label ?? action.id)}</b>
                <span>{String(action.reason ?? "")}</span>
              </div>
              {safe ? (
                <button disabled={props.running} onClick={() => props.onRun(action)}>
                  実行
                </button>
              ) : (
                <span className="manual-chip">手動確認</span>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function InventoryPill({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className={`inventory-pill ${tone}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
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
  onOpenDetail: (code: string, assetType: "stock" | "fund") => void;
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
      {state.data && <CandidateTable data={state.data} onOpenDetail={props.onOpenDetail} />}
    </section>
  );
}

function DetailPanel(props: {
  holdingsCsv: string;
  fundsCsv: string;
  financialsPath: string;
  detailRequest: DetailRequest;
  onMove: (tab: TabId) => void;
}) {
  const [code, setCode] = useState(props.detailRequest.code);
  const [assetType, setAssetType] = useState<"stock" | "fund">(props.detailRequest.assetType);
  const state = useAsync<Json>();
  const load = (targetCode = code, targetAssetType = assetType) =>
    state.run(() =>
      api<Json>("/api/investment/detail", {
        code: targetCode,
        asset_type: targetAssetType,
        csv_text: props.holdingsCsv,
        funds_csv_text: props.fundsCsv,
        financials_csv: props.financialsPath,
      }),
    );

  useEffect(() => {
    if (props.detailRequest.version <= 0) return;
    setCode(props.detailRequest.code);
    setAssetType(props.detailRequest.assetType);
    void load(props.detailRequest.code, props.detailRequest.assetType);
  }, [props.detailRequest.version]);

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
      {state.data && <DetailResult data={state.data} onMove={props.onMove} />}
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
  const [displayReport, setDisplayReport] = useState<Json | null>(null);
  const state = useAsync<Json>();
  const historyState = useAsync<Json>();
  const loadState = useAsync<Json>();
  const candidateCount = Array.isArray(props.candidates?.results) ? props.candidates.results.length : 0;
  const holdingRows = csvDataRows(props.holdingsCsv);
  const preflight = reportPreflight({
    candidateCount,
    financialsPath: props.financialsPath,
    holdingRows,
    targetDividend,
  });
  const refreshHistory = () => historyState.run(() => api<Json>("/api/reports/investment-monthly/history", { limit: 20 }));
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
    if (result) {
      setDisplayReport(result);
      props.onReport(result);
      void refreshHistory();
    }
  };
  const loadReport = async (reportId: string) => {
    const result = await loadState.run(() =>
      api<Json>("/api/reports/investment-monthly/history/load", {
        report_id: reportId,
      }),
    );
    const report = asJson(result?.report);
    if (report) {
      setDisplayReport(report);
      props.onReport(report);
    }
  };
  return (
    <section className="screen">
      <ScreenTitle title="投資レポート" body="保有状況、集中リスク、配当見込み、候補、根拠、免責をまとめます。" />
      <section className="report-preflight" aria-label="生成前の確認">
        <div className="detail-section">
          <h4>使うデータ</h4>
          <div className="detail-metrics">
            <DetailFact label="保有明細" value={`${holdingRows}行`} />
            <DetailFact label="財務CSV" value={shortPath(props.financialsPath) || "-"} />
            <DetailFact label="候補" value={`${candidateCount}件`} />
            <DetailFact label="保存" value="履歴に保存" tone="safe" />
          </div>
        </div>
        {preflight.length > 0 && (
          <div className="report-checks">
            {preflight.map((item) => (
              <p key={item}>{item}</p>
            ))}
          </div>
        )}
      </section>
      <div className="form-grid tight">
        <Field label="目標年間配当">
          <input value={targetDividend} onChange={(e) => setTargetDividend(e.target.value)} inputMode="numeric" />
        </Field>
      </div>
      <ActionRow>
        <button className="primary" onClick={() => void create()}>
          レポート生成
        </button>
        <button onClick={() => void refreshHistory()}>
          {historyState.data ? "履歴を更新" : "履歴を見る"}
        </button>
      </ActionRow>
      <Status
        loading={state.loading || historyState.loading || loadState.loading}
        error={state.error || historyState.error || loadState.error}
      />
      {historyState.data && <ReportHistoryTable data={historyState.data} onLoad={loadReport} onRefresh={refreshHistory} />}
      {displayReport && <ReportResult data={displayReport} />}
    </section>
  );
}

function ChatPanel() {
  const [query, setQuery] = useState("KDDIの配当利回りと根拠を、投資助言にならない形で確認して");
  const state = useAsync<Json>();
  const ragResults = Array.isArray(state.data?.results) ? (state.data.results as Json[]) : [];
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
          {ragResults.length > 0 && <RagCitationList results={ragResults} />}
          <JsonDetails data={state.data} />
        </div>
      )}
    </section>
  );
}

function RagCitationList({ results }: { results: Json[] }) {
  const rows = results.map((result, index) => {
    const citation = asJson(result.citation) ?? {};
    return {
      number: index + 1,
      label: String(citation.label ?? shortPath(String(result.source ?? ""))),
      report_id: String(citation.report_id ?? "-"),
      integrity_status: String(citation.integrity_status ?? "-"),
      chunk_index: String(citation.chunk_index ?? result.chunk_index ?? "-"),
      score: formatScore(citation.score ?? result.score),
      source: shortPath(String(citation.source ?? result.source ?? "")),
    };
  });
  return (
    <section className="detail-section citation-list" aria-label="引用・根拠">
      <h4>引用・根拠</h4>
      <SimpleTable
        rows={rows}
        columns={[
          ["number", "#"],
          ["label", "引用"],
          ["report_id", "レポートID"],
          ["integrity_status", "整合性"],
          ["chunk_index", "チャンク"],
          ["score", "スコア"],
          ["source", "文書"],
        ]}
      />
    </section>
  );
}

function MarketResult({ data, mode }: { data: Json; mode: string }) {
  if (mode === "inbox") {
    const prices = (data.prices ?? {}) as Record<string, number>;
    const rows = Object.entries(prices).map(([ticker, price]) => ({ ticker, price }));
    return (
      <ResultBlock
        title="ファイル取込（inbox）"
        meta={`状態: ${String(data.status ?? "-")} / ${String(data.tickers ?? 0)}銘柄 / 入力: ${String(data.path ?? "-")}`}
      >
        {rows.length > 0 ? (
          <SimpleTable rows={rows} columns={[["ticker", "コード"], ["price", "価格"]]} />
        ) : (
          <p className="muted">
            ファイルが見つかりません。Yahoo!ファイナンス等の個人利用CSVを表示中のパスに置いてください。
          </p>
        )}
      </ResultBlock>
    );
  }
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

function CandidateTable({
  data,
  onOpenDetail,
}: {
  data: Json;
  onOpenDetail: (code: string, assetType: "stock" | "fund") => void;
}) {
  const rows = Array.isArray(data.results) ? data.results : [];
  return (
    <ResultBlock title="候補抽出結果" meta={`${String(data.count ?? rows.length)} 件`}>
      {rows.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>コード</th>
                <th>名称</th>
                <th>種別</th>
                <th>スコア</th>
                <th>根拠</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 100).map((row, index) => {
                const code = candidateCode(row);
                const assetType = detailAssetType(row.asset_type);
                return (
                  <tr key={`${code || String(row.name ?? "candidate")}-${index}`}>
                    <td>{code || "-"}</td>
                    <td>{formatCell(row.name)}</td>
                    <td>{assetTypeLabel(assetType)}</td>
                    <td>{formatCell(row.score)}</td>
                    <td>{formatCell(row.reason)}</td>
                    <td>
                      <button
                        className="table-action"
                        disabled={!code}
                        onClick={() => onOpenDetail(code, assetType)}
                      >
                        詳細
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">表示できるデータがありません。</p>
      )}
    </ResultBlock>
  );
}

function DetailResult({ data, onMove }: { data: Json; onMove: (tab: TabId) => void }) {
  const holdingSummary = asJson(data.holding_summary);
  const financials = asJson(data.financials);
  const fundProfile = asJson(data.fund_profile);
  const metrics = Array.isArray(data.metrics) ? (data.metrics as Json[]) : [];
  const evidence = Array.isArray(data.evidence) ? (data.evidence as Json[]) : [];
  const sections = Array.isArray(data.sections) ? (data.sections as Json[]) : [];
  const available = Boolean(data.available);
  const title = `${String(data.name ?? data.code ?? "詳細")} ${data.code ? `(${String(data.code)})` : ""}`.trim();
  const primaryNext = !available ? "data" : holdingSummary ? "report" : "holdings";
  const nextActions: Array<{ tab: TabId; label: string }> = [
    { tab: "data", label: "データ更新" },
    { tab: "holdings", label: "保有分析" },
    { tab: "screen", label: "候補抽出" },
    { tab: "report", label: "レポート" },
  ];

  return (
    <ResultBlock title={title} meta={available ? "表示可能" : "未検出"}>
      <div className="detail-hero">
        <DetailFact label="コード" value={String(data.code ?? "-")} />
        <DetailFact label="種別" value={assetTypeLabel(data.asset_type)} />
        <DetailFact label="生成時刻" value={formatDateTime(data.generated_at)} />
        <DetailFact label="自動売買" value={data.auto_trading ? "有効" : "なし"} tone={data.auto_trading ? undefined : "safe"} />
      </div>

      {!available && (
        <p className="notice">
          入力コードに一致する保有、財務データ、投信プロファイルが見つかりません。データ更新またはCSV入力を確認してください。
        </p>
      )}

      {sections.length > 0 && (
        <div className="detail-notes" aria-label="要点">
          {sections.map((section) => (
            <article key={String(section.key ?? section.title)} className="detail-note">
              <b>{String(section.title ?? "要点")}</b>
              <p>{String(section.body ?? "-")}</p>
            </article>
          ))}
        </div>
      )}

      {holdingSummary && (
        <section className="detail-section">
          <h4>保有サマリー</h4>
          <div className="detail-metrics">
            <DetailFact label="評価額" value={yen(holdingSummary.market_value)} />
            <DetailFact label="取得額" value={yen(holdingSummary.cost_basis)} />
            <DetailFact label="評価損益" value={yen(holdingSummary.unrealized_pnl)} />
            <DetailFact label="損益率" value={percent(holdingSummary.unrealized_pnl_pct)} />
            <DetailFact label="年収入見込み" value={yen(holdingSummary.annual_income_estimate)} />
            <DetailFact label="収入利回り" value={percent(holdingSummary.income_yield_pct)} />
          </div>
        </section>
      )}

      {metrics.length > 0 && (
        <section className="detail-section">
          <h4>主要指標と計算式</h4>
          <SimpleTable
            rows={metrics}
            columns={[
              ["label", "指標"],
              ["value", "値"],
              ["formula", "計算式"],
              ["last_updated", "更新"],
            ]}
          />
        </section>
      )}

      {financials && (
        <section className="detail-section">
          <h4>財務データ</h4>
          <div className="detail-metrics">
            <DetailFact label="企業名" value={String(financials.name ?? "-")} />
            <DetailFact label="最新年度" value={String(financials.latest_fiscal_year ?? "-")} />
            <DetailFact label="自己資本比率" value={percent(financials.latest_equity_ratio)} />
            <DetailFact label="1株配当" value={yen(financials.latest_dividend_per_share)} />
            <DetailFact label="営業CF傾向" value={String(financials.operating_cf_trend ?? "-")} />
            <DetailFact label="減配年度" value={formatCell(financials.dividend_cut_years)} />
          </div>
        </section>
      )}

      {fundProfile && (
        <section className="detail-section">
          <h4>投信プロファイル</h4>
          <div className="detail-metrics">
            <DetailFact label="名称" value={String(fundProfile.name ?? "-")} />
            <DetailFact label="資産クラス" value={String(fundProfile.asset_class ?? "-")} />
            <DetailFact label="信託報酬" value={percent(fundProfile.expense_ratio)} />
            <DetailFact label="分配方針" value={String(fundProfile.distribution_policy ?? "-")} />
            <DetailFact label="NISA対象" value={formatCell(fundProfile.nisa_eligible)} />
            <DetailFact label="分散度" value={formatCell(fundProfile.diversification_score)} />
          </div>
        </section>
      )}

      {evidence.length > 0 && (
        <section className="detail-section">
          <h4>根拠</h4>
          <SimpleTable
            rows={evidence}
            columns={[
              ["claim_key", "根拠キー"],
              ["source_type", "出所"],
              ["source_ref", "参照"],
              ["formula", "算出方法"],
              ["last_updated", "更新"],
            ]}
          />
        </section>
      )}

      <section className="detail-boundary">
        <b>非助言の境界</b>
        <p>{String(data.non_advisory_boundary ?? data.disclaimer ?? "売買推奨・自動売買は行いません。最終判断はユーザーが行います。")}</p>
      </section>

      <section className="detail-section">
        <h4>次の作業</h4>
        <div className="detail-actions">
          {nextActions.map((action) => (
            <button
              key={action.tab}
              className={action.tab === primaryNext ? "primary" : undefined}
              onClick={() => onMove(action.tab)}
            >
              {action.label}
            </button>
          ))}
        </div>
      </section>
      <JsonDetails data={data} />
    </ResultBlock>
  );
}

function DetailFact({ label, value, tone }: { label: string; value: string; tone?: "safe" }) {
  return (
    <div className={tone === "safe" ? "detail-fact safe" : "detail-fact"}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function ReportHistoryTable({
  data,
  onLoad,
  onRefresh,
}: {
  data: Json;
  onLoad: (reportId: string) => void;
  onRefresh: () => Promise<Json | null>;
}) {
  const rows = reportHistoryRows(data);
  const [baseSelection, setBaseSelection] = useState("");
  const [compareSelection, setCompareSelection] = useState("");
  const verifyState = useAsync<Json>();
  const deleteState = useAsync<Json>();
  const compareState = useAsync<Json>();
  const baseId = selectedReportId(baseSelection, rows, 0);
  const compareId = selectedReportId(compareSelection, rows, 1);
  const baseRow = reportHistoryRowById(rows, baseId);
  const compareDisabled = !baseId || !compareId || baseId === compareId;
  const verifySelected = () => {
    if (!baseId) return;
    void verifyState.run(() =>
      api<Json>("/api/reports/investment-monthly/history/verify", {
        report_id: baseId,
      }),
    );
  };
  const deleteSelected = async () => {
    if (!baseId) return;
    const label = baseRow ? `${formatDateTime(baseRow.saved_at)} ${String(baseRow.title ?? "")}` : baseId;
    if (!window.confirm(`保存済みレポートを削除します。元に戻せません。\n\n${label}`)) return;
    const result = await deleteState.run(() =>
      api<Json>("/api/reports/investment-monthly/history/delete", {
        report_id: baseId,
      }),
    );
    if (result?.deleted) {
      setBaseSelection("");
      setCompareSelection("");
      void onRefresh();
    }
  };
  const compareSelected = () => {
    if (compareDisabled) return;
    void compareState.run(() =>
      api<Json>("/api/reports/investment-monthly/history/compare", {
        base_id: baseId,
        compare_id: compareId,
      }),
    );
  };
  if (rows.length === 0) {
    return (
      <section className="detail-section report-history">
        <h4>レポート履歴</h4>
        <p className="muted">保存済みレポートはまだありません。先にレポート生成を実行してください。</p>
      </section>
    );
  }
  return (
    <section className="detail-section report-history" aria-label="レポート履歴">
      <h4>レポート履歴</h4>
      <div className="history-toolbar">
        <Field label="基準">
          <select value={baseId} onChange={(event) => setBaseSelection(event.target.value)}>
            {rows.map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                {historyOptionLabel(row)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="比較先">
          <select value={compareId} onChange={(event) => setCompareSelection(event.target.value)}>
            {rows.map((row) => (
              <option key={String(row.id)} value={String(row.id)}>
                {historyOptionLabel(row)}
              </option>
            ))}
          </select>
        </Field>
        <div className="history-actions">
          <button onClick={verifySelected} disabled={!baseId}>
            整合性確認
          </button>
          <button onClick={compareSelected} disabled={compareDisabled}>
            比較
          </button>
          <button onClick={() => void deleteSelected()} disabled={!baseId}>
            削除
          </button>
        </div>
      </div>
      <Status
        loading={verifyState.loading || deleteState.loading || compareState.loading}
        error={verifyState.error || deleteState.error || compareState.error}
      />
      {verifyState.data && <ReportHistoryVerification data={verifyState.data} />}
      {compareState.data && <ReportHistoryComparison data={compareState.data} />}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>保存日時</th>
              <th>タイトル</th>
              <th>評価額</th>
              <th>年間収入</th>
              <th>NISA残枠</th>
              <th>候補</th>
              <th>状態</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const reportId = String(row.id ?? "");
              const auditStatus = String(row.publish_audit_status ?? "unknown");
              const integrityStatus = String(row.integrity_status ?? "unknown");
              const ok = auditStatus === "ok" && integrityStatus === "ok";
              const rowClass = [
                "history-row",
                ok ? "" : "warn",
                reportId === baseId ? "selected" : "",
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <tr key={reportId || String(row.saved_at)} className={rowClass}>
                  <td>{formatDateTime(row.saved_at)}</td>
                  <td>
                    <b>{String(row.title ?? "投資月次レポート")}</b>
                    <span className="history-sub">{shortHash(row.report_hash)}</span>
                  </td>
                  <td>{yenWithZero(row.market_value)}</td>
                  <td>{yenWithZero(row.annual_income_estimate)}</td>
                  <td>{yenWithZero(row.nisa_remaining)}</td>
                  <td>{formatCell(row.candidate_count)}</td>
                  <td>
                    {historyStatusLabel(auditStatus, integrityStatus)}
                    {row.publish_audit_issue_count ? (
                      <span className="history-sub">指摘 {String(row.publish_audit_issue_count)}件</span>
                    ) : null}
                  </td>
                  <td>
                    <button className="table-action" disabled={!reportId} onClick={() => onLoad(reportId)}>
                      表示
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted">履歴から開いたレポートも、同じ根拠一覧とPDF出力を利用できます。</p>
    </section>
  );
}

function ReportHistoryVerification({ data }: { data: Json }) {
  const ok = String(data.integrity_status ?? "") === "ok";
  return (
    <p className={ok ? "notice safe" : "notice"}>
      整合性: {String(data.integrity_status ?? "-")} / 保存ハッシュ: {shortHash(data.report_hash)} / 再計算:{" "}
      {shortHash(data.calculated_report_hash)}
    </p>
  );
}

function ReportHistoryComparison({ data }: { data: Json }) {
  const metrics = Array.isArray(data.metrics) ? (data.metrics as Json[]) : [];
  const evidence = asJson(data.evidence);
  const base = asJson(data.base);
  const compare = asJson(data.compare);
  return (
    <section className="detail-section history-comparison" aria-label="レポート比較結果">
      <h4>比較結果</h4>
      <div className="detail-metrics">
        <DetailFact label="基準" value={formatDateTime(base?.saved_at)} />
        <DetailFact label="比較先" value={formatDateTime(compare?.saved_at)} />
        <DetailFact label="根拠 差分" value={historyEvidenceDeltaLabel(evidence)} />
        <DetailFact label="自動売買" value={data.auto_trading ? "有効" : "なし"} tone={data.auto_trading ? undefined : "safe"} />
      </div>
      <SimpleTable
        rows={metrics.map((metric) => ({
          ...metric,
          base_value: formatReportValue(metric.base_value, metric.value_format),
          compare_value: formatReportValue(metric.compare_value, metric.value_format),
          delta: formatReportDelta(metric.delta, metric.value_format),
          delta_pct: formatReportDelta(metric.delta_pct, "percent"),
          changed: metric.changed ? "変化あり" : "変化なし",
        }))}
        columns={[
          ["label", "項目"],
          ["base_value", "基準"],
          ["compare_value", "比較"],
          ["delta", "差分"],
          ["delta_pct", "差分率"],
          ["changed", "状態"],
          ["formula", "計算式"],
        ]}
      />
      <p className="muted">比較は保存済みレポートのKPI差分です。売買判断や予測ではありません。</p>
    </section>
  );
}

function ReportMarkdownLibrary({ data }: { data: Json }) {
  const docs = Array.isArray(data.docs) ? (data.docs as Json[]) : [];
  return (
    <section className="detail-section markdown-library" aria-label="保存済みレポート文書">
      <h4>保存済みMarkdown</h4>
      <div className="detail-metrics">
        <DetailFact label="保存先" value={String(data.output_dir ?? "-")} />
        <DetailFact label="件数" value={`${String(data.count ?? docs.length)}件`} />
        <DetailFact label="用途" value="RAG検索用" tone="safe" />
        <DetailFact label="自動売買" value={data.auto_trading ? "有効" : "なし"} tone={data.auto_trading ? undefined : "safe"} />
      </div>
      <SimpleTable
        rows={docs.map((doc) => ({
          ...doc,
          size_bytes: formatBytes(doc.size_bytes),
          modified_at: formatDateTime(doc.modified_at),
          saved_at: formatDateTime(doc.saved_at),
        }))}
        columns={[
          ["filename", "ファイル"],
          ["title", "タイトル"],
          ["report_id", "レポートID"],
          ["integrity_status", "整合性"],
          ["size_bytes", "サイズ"],
          ["modified_at", "更新"],
          ["path", "パス"],
        ]}
      />
      <p className="muted">ここにあるMarkdownは `local_docs/reports` 配下のローカル生成物です。Gitには含めません。</p>
    </section>
  );
}

function ReportResult({ data }: { data: Json }) {
  const markdownState = useAsync<Json>();
  const saveMarkdownState = useAsync<Json>();
  const markdownLibraryState = useAsync<Json>();
  const [markdownNotice, setMarkdownNotice] = useState("");
  const [markdownActionError, setMarkdownActionError] = useState<string | null>(null);
  const kpis = Array.isArray(data.kpis) ? data.kpis : [];
  const sections = Array.isArray(data.sections) ? (data.sections as Json[]) : [];
  const evidence = Array.isArray(data.evidence) ? (data.evidence as Json[]) : [];
  const audit = asJson(data.publish_audit);
  const auditIssues = Array.isArray(audit?.issues) ? (audit.issues as Json[]) : [];
  const history = asJson(data.history);
  const auditStatus = String(audit?.status ?? "未監査");
  const auditOk = auditStatus === "ok";
  const markdown = String(markdownState.data?.markdown ?? "");
  const generateMarkdown = () => {
    setMarkdownNotice("");
    setMarkdownActionError(null);
    return markdownState.run(() =>
      api<Json>("/api/reports/investment-monthly/markdown", {
        report: data,
      }),
    );
  };
  const markdownText = async () => {
    if (markdown) return markdown;
    const result = await generateMarkdown();
    return String(result?.markdown ?? "");
  };
  const copyMarkdown = async () => {
    setMarkdownNotice("");
    setMarkdownActionError(null);
    try {
      const text = await markdownText();
      if (!text) return;
      await copyTextToClipboard(text);
      setMarkdownNotice("Markdownをコピーしました。");
    } catch (caught) {
      setMarkdownActionError(caught instanceof Error ? caught.message : String(caught));
    }
  };
  const downloadMarkdown = async () => {
    setMarkdownNotice("");
    setMarkdownActionError(null);
    try {
      const text = await markdownText();
      if (!text) return;
      downloadTextFile(`${reportFileBaseName(data)}.md`, text, "text/markdown;charset=utf-8");
      setMarkdownNotice("Markdownファイルを作成しました。");
    } catch (caught) {
      setMarkdownActionError(caught instanceof Error ? caught.message : String(caught));
    }
  };
  const saveMarkdownToRag = async () => {
    setMarkdownNotice("");
    setMarkdownActionError(null);
    const result = await saveMarkdownState.run(() =>
      api<Json>("/api/reports/investment-monthly/markdown/save", {
        report: data,
        output_dir: "local_docs/reports",
        index_after_save: true,
      }),
    );
    if (result?.saved_path) {
      const indexed = asJson(result.indexed);
      const chunks = indexed?.chunks_indexed ?? "-";
      setMarkdownNotice(`ローカル保存しました: ${String(result.saved_path)} / RAG ${String(chunks)}チャンク`);
      void loadMarkdownLibrary();
    }
  };
  const loadMarkdownLibrary = () =>
    markdownLibraryState.run(() =>
      api<Json>("/api/reports/investment-monthly/markdown/library", {
        output_dir: "local_docs/reports",
        limit: 20,
      }),
    );
  return (
    <div className="report-print-area">
      <ResultBlock title={String(data.title ?? "投資月次レポート")} meta={auditOk ? "監査OK" : auditStatus}>
        <div className="report-export">
          <div className="report-export-actions">
            <button className="primary" onClick={() => exportReportPdf(data)}>
              PDF出力
            </button>
            <button onClick={() => void generateMarkdown()}>Markdown生成</button>
            <button onClick={() => void copyMarkdown()}>コピー</button>
            <button onClick={() => void downloadMarkdown()}>.md保存</button>
            <button onClick={() => void saveMarkdownToRag()}>RAG保存</button>
            <button onClick={() => void loadMarkdownLibrary()}>保存一覧</button>
          </div>
          <span>
            PDFは印刷保存、.md保存は端末へのダウンロード、RAG保存はlocal_docs/reportsへ登録します。
          </span>
        </div>
        <Status
          loading={markdownState.loading || saveMarkdownState.loading || markdownLibraryState.loading}
          error={markdownState.error || saveMarkdownState.error || markdownLibraryState.error || markdownActionError}
        />
        {markdownNotice && <p className="notice safe">{markdownNotice}</p>}
        {markdownLibraryState.data && <ReportMarkdownLibrary data={markdownLibraryState.data} />}
        {markdown && (
          <details className="markdown-preview">
            <summary>Markdownを確認</summary>
            <pre>{markdown}</pre>
          </details>
        )}

        <div className="detail-hero">
          <DetailFact label="生成時刻" value={formatDateTime(data.generated_at)} />
          <DetailFact label="候補" value={`${String(data.candidate_count ?? 0)}件`} />
          <DetailFact label="根拠" value={`${evidence.length}件`} />
          <DetailFact label="監査" value={auditOk ? "OK" : auditStatus} tone={auditOk ? "safe" : undefined} />
        </div>

        {history && (
          <section className="detail-section">
            <h4>保存状態</h4>
            <div className="detail-metrics">
              <DetailFact label="レポートID" value={String(history.id ?? "-")} />
              <DetailFact label="保存時刻" value={formatDateTime(history.saved_at)} />
              <DetailFact label="整合性" value={String(history.integrity_status ?? "-")} />
              <DetailFact label="ハッシュ" value={shortHash(history.report_hash)} />
            </div>
          </section>
        )}

        {sections.length > 0 && (
          <section className="detail-section">
            <h4>章立て</h4>
            <div className="detail-notes">
              {sections.map((section) => (
                <article key={String(section.key ?? section.title)} className="detail-note">
                  <b>{String(section.title ?? "章")}</b>
                  <p>{String(section.body ?? "-")}</p>
                </article>
              ))}
            </div>
          </section>
        )}

        <section className="detail-section">
          <h4>主要KPIと計算式</h4>
          <SimpleTable
            rows={kpis.map((kpi) => ({
              ...kpi,
              value: formatReportValue(kpi.value, kpi.value_format),
              evidence_count: Array.isArray(kpi.evidence_keys) ? kpi.evidence_keys.length : 0,
            }))}
            columns={[
              ["label", "項目"],
              ["value", "値"],
              ["formula", "計算式"],
              ["evidence_count", "根拠数"],
              ["last_updated", "更新"],
            ]}
          />
        </section>

        {evidence.length > 0 && (
          <section className="detail-section">
            <h4>根拠一覧</h4>
            <SimpleTable
              rows={evidence.slice(0, 30)}
              columns={[
                ["claim_key", "根拠キー"],
                ["source_type", "出所"],
                ["source_ref", "参照"],
                ["formula", "算出方法"],
                ["last_updated", "更新"],
              ]}
            />
          </section>
        )}

        <section className="detail-section">
          <h4>監査状態</h4>
          {auditIssues.length > 0 ? (
            <SimpleTable
              rows={auditIssues}
              columns={[
                ["code", "コード"],
                ["path", "場所"],
                ["message", "内容"],
              ]}
            />
          ) : (
            <p className="notice safe">重要KPIの根拠と計算式を確認できました。</p>
          )}
        </section>

        <section className="detail-boundary">
          <b>免責</b>
          <p>{String(data.disclaimer ?? "これは投資助言・売買推奨ではありません。最終判断はユーザーが行います。")}</p>
        </section>
        <JsonDetails data={data} />
      </ResultBlock>
    </div>
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

function asJson(value: unknown): Json | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Json;
}

function shortPath(value: string): string {
  return value.split(/[\\/]/).filter(Boolean).pop() ?? value;
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

function statusLabel(value: string): string {
  const labels: Record<string, string> = {
    ready: "利用可",
    stale: "要更新",
    missing: "未取得",
    empty: "空",
    error: "エラー",
    needs_setup: "要設定",
    unknown: "未確認",
  };
  return labels[value] ?? value;
}

function jobStatusLabel(value: string): string {
  if (value === "done") return "完了";
  if (value === "error") return "失敗";
  return "取得中";
}

function formatSeconds(value: unknown): string {
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) return "経過 -";
  const rounded = Math.max(0, Math.floor(seconds));
  if (rounded < 60) return `経過 ${rounded}秒`;
  const minutes = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return `経過 ${minutes}分${rest.toString().padStart(2, "0")}秒`;
}

function formatDateTime(value: unknown): string {
  if (!value) return "-";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ja-JP", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function statusTone(value: string): string {
  if (value === "ready") return "ready";
  if (value === "stale") return "warn";
  if (value === "error" || value === "needs_setup") return "error";
  return "muted";
}

function formatRows(item: Json): string {
  if (item.kind === "sqlite" && item.table_count !== undefined) {
    return `${String(item.table_count)}表 / ${String(item.row_count ?? 0)}件`;
  }
  if (item.kind === "log" && item.line_count !== undefined) return `${String(item.line_count)}行`;
  if (item.row_count !== undefined) {
    const tickerCount = item.ticker_count !== undefined ? ` / ${String(item.ticker_count)}銘柄` : "";
    return `${String(item.row_count)}件${tickerCount}`;
  }
  return "-";
}

function formatBytes(value: unknown): string {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toLocaleString("ja-JP", { maximumFractionDigits: 1 })} KB`;
  return `${(bytes / (1024 * 1024)).toLocaleString("ja-JP", { maximumFractionDigits: 1 })} MB`;
}

function formatScore(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return numeric.toLocaleString("ja-JP", { maximumFractionDigits: 4 });
}

function formatFreshness(item: Json): string {
  if (!item.exists) return "ファイルなし";
  const latest = item.latest_value ? `最新値 ${String(item.latest_value)}` : "";
  const age = typeof item.age_hours === "number" ? `${Math.round(item.age_hours)}時間前` : "";
  return [latest, age].filter(Boolean).join(" / ") || "-";
}

function csvDataRows(value: string): number {
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return Math.max(0, lines.length - 1);
}

function reportPreflight(input: {
  candidateCount: number;
  financialsPath: string;
  holdingRows: number;
  targetDividend: string;
}): string[] {
  const warnings: string[] = [];
  if (input.holdingRows === 0) warnings.push("保有明細が空です。レポート生成前に保有CSVを確認してください。");
  if (!input.financialsPath.trim()) warnings.push("財務CSVパスが空です。根拠付きの財務章が薄くなります。");
  if (input.candidateCount === 0) warnings.push("候補抽出結果がありません。候補章は空のまま生成されます。");
  if ((Number(input.targetDividend) || 0) <= 0) warnings.push("目標年間配当が0です。逆算KPIは追加されません。");
  return warnings;
}

function reportHistoryRows(data: Json | null): Json[] {
  return Array.isArray(data?.reports) ? (data.reports as Json[]) : [];
}

function selectedReportId(selection: string, rows: Json[], fallbackIndex: number): string {
  if (rows.some((row) => String(row.id ?? "") === selection)) return selection;
  return String(rows[fallbackIndex]?.id ?? rows[0]?.id ?? "");
}

function reportHistoryRowById(rows: Json[], reportId: string): Json | null {
  return rows.find((row) => String(row.id ?? "") === reportId) ?? null;
}

function historyOptionLabel(row: Json): string {
  const time = formatDateTime(row.saved_at);
  const title = String(row.title ?? "投資月次レポート");
  const value = yenWithZero(row.market_value);
  return `${time} / ${title} / ${value}`;
}

function historyStatusLabel(auditStatus: string, integrityStatus: string): string {
  const audit = auditStatus === "ok" ? "監査OK" : `監査 ${auditStatus}`;
  const integrity = integrityStatus === "ok" ? "整合OK" : `整合 ${integrityStatus}`;
  return `${audit} / ${integrity}`;
}

function historyEvidenceDeltaLabel(evidence: Json | null): string {
  if (!evidence) return "-";
  const added = Array.isArray(evidence.added) ? evidence.added.length : 0;
  const removed = Array.isArray(evidence.removed) ? evidence.removed.length : 0;
  return `追加 ${added} / 削除 ${removed}`;
}

function yen(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric === 0) return "-";
  return `${Math.round(numeric).toLocaleString("ja-JP")}円`;
}

function percent(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return `${numeric.toLocaleString("ja-JP", { maximumFractionDigits: 2 })}%`;
}

function assetTypeLabel(value: unknown): string {
  const text = String(value ?? "").toLowerCase();
  if (text === "stock") return "国内株式";
  if (text === "fund") return "投資信託";
  if (text === "unknown" || text === "") return "未判定";
  return String(value);
}

function formatReportValue(value: unknown, valueFormat: unknown): string {
  const format = String(valueFormat ?? "");
  if (format === "yen") return yenWithZero(value);
  if (format === "percent") return percent(value);
  if (typeof value === "boolean") return value ? "はい" : "いいえ";
  return formatCell(value);
}

function formatReportDelta(value: unknown, valueFormat: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  const prefix = numeric > 0 ? "+" : "";
  const format = String(valueFormat ?? "");
  if (format === "yen") return `${prefix}${yenWithZero(numeric)}`;
  if (format === "percent") {
    return `${prefix}${numeric.toLocaleString("ja-JP", { maximumFractionDigits: 2 })}%`;
  }
  return `${prefix}${numeric.toLocaleString("ja-JP", { maximumFractionDigits: 2 })}`;
}

function exportReportPdf(data: Json): void {
  const previousTitle = document.title;
  let restored = false;
  const restoreTitle = () => {
    if (restored) return;
    restored = true;
    document.title = previousTitle;
    window.removeEventListener("afterprint", restoreTitle);
  };
  document.title = reportPdfTitle(data);
  window.addEventListener("afterprint", restoreTitle);
  window.print();
  window.setTimeout(restoreTitle, 5000);
}

function reportPdfTitle(data: Json): string {
  return reportFileBaseName(data);
}

function reportFileBaseName(data: Json): string {
  const title = String(data.title ?? "投資月次レポート").replace(/[\\/:*?"<>|]/g, "-");
  const generated = String(data.generated_at ?? "").slice(0, 10) || "report";
  return `${title}-${generated}`;
}

async function copyTextToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }
}

function downloadTextFile(filename: string, text: string, type: string): void {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function shortHash(value: unknown): string {
  const text = String(value ?? "");
  return text ? `${text.slice(0, 12)}...` : "-";
}

function yenWithZero(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return `${Math.round(numeric).toLocaleString("ja-JP")}円`;
}

function detailAssetType(value: unknown): "stock" | "fund" {
  const text = String(value ?? "").toLowerCase();
  return text === "fund" || text === "mutual_fund" || text === "investment_fund" ? "fund" : "stock";
}

function candidateCode(row: Json): string {
  return String(row.code ?? row.ticker ?? row.ticker_or_fund_code ?? row.fund_code ?? "").trim();
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return value.toLocaleString("ja-JP", { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "はい" : "いいえ";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
