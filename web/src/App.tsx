import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";

type Json = Record<string, any>;
type TabId = "dashboard" | "watch" | "data" | "holdings" | "screen" | "detail" | "forecast" | "report" | "rag" | "chat";
type DetailRequest = { code: string; assetType: "stock" | "fund"; version: number };
type RagSearchDraft = { query: string; dbPath: string; limit: string; version: number };
type ChatDraft = { query: string; dbPath: string; limit: number; evidence?: Json[]; searchQuery?: string };

const FINANCIALS_PATH = "local_docs/edinet/financials.csv";
const DEFAULT_RAG_DB_PATH = ".cache/investment_assistant/rag.sqlite";
const DEFAULT_CHAT_QUERY = "KDDIの配当利回りと根拠を、投資助言にならない形で確認して";
const DEFAULT_CHAT_LIMIT = 5;
const WATCHLIST_STORAGE_KEY = "ia.watchlist";
const DEFAULT_WATCHLIST = "7203 8306 9433 9432 6758 6861 8058 9984";
// Shared one-tap presets for RAG search and AI chat, so both stay in sync.
const QUICK_QUERY_PRESETS = [
  "配当 方針 根拠",
  "減配 リスク",
  "自己資本比率",
  "株主還元 自社株買い",
  "NISA 枠",
  "集中リスク",
];

function parseTickers(text: string): string[] {
  return text.split(/[\s,]+/).map((code) => code.trim()).filter(Boolean);
}

// Header-only defaults: no pre-loaded sample holdings/funds. Build your own
// via the 銘柄選択 builder / 候補抽出, or use the "テンプレート" button for examples.
const SAMPLE_HOLDINGS_CSV =
  "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source,current_price,annual_income,distribution_per_unit,data_provider,price_as_of";

const SAMPLE_FUNDS_CSV =
  "fund_code,name,asset_class,expense_ratio,distribution_policy,nisa_eligible,provider_id,diversification_score";

const TABS: Array<{ id: TabId; label: string; short: string }> = [
  { id: "dashboard", label: "全体", short: "全体" },
  { id: "watch", label: "ウォッチ", short: "監視" },
  { id: "data", label: "データ更新", short: "更新" },
  { id: "holdings", label: "保有分析", short: "保有" },
  { id: "screen", label: "候補抽出", short: "候補" },
  { id: "detail", label: "詳細", short: "詳細" },
  { id: "forecast", label: "予測スクリーニング", short: "予測" },
  { id: "report", label: "レポート", short: "報告" },
  { id: "rag", label: "RAG検索", short: "RAG" },
  { id: "chat", label: "AI確認", short: "AI" },
];

export function App() {
  const [tab, setTab] = useState<TabId>(() => {
    const saved = localStorage.getItem("ia.tab");
    return TABS.some((item) => item.id === saved) ? (saved as TabId) : "dashboard";
  });
  useEffect(() => {
    localStorage.setItem("ia.tab", tab);
  }, [tab]);
  const [holdingsCsv, setHoldingsCsv] = useState(SAMPLE_HOLDINGS_CSV);
  const [fundsCsv, setFundsCsv] = useState(SAMPLE_FUNDS_CSV);
  const [financialsPath, setFinancialsPath] = useState(FINANCIALS_PATH);
  const [marketSnapshot, setMarketSnapshot] = useState<Json | null>(null);
  const [analysis, setAnalysis] = useState<Json | null>(null);
  const [candidates, setCandidates] = useState<Json | null>(null);
  const [report, setReport] = useState<Json | null>(null);
  const [ragDraft, setRagDraft] = useState<RagSearchDraft>({
    query: "配当 利回り 根拠",
    dbPath: DEFAULT_RAG_DB_PATH,
    limit: "8",
    version: 0,
  });
  const [chatDraft, setChatDraft] = useState<ChatDraft>({
    query: DEFAULT_CHAT_QUERY,
    dbPath: DEFAULT_RAG_DB_PATH,
    limit: DEFAULT_CHAT_LIMIT,
  });
  const [detailRequest, setDetailRequest] = useState<DetailRequest>({
    code: "8306",
    assetType: "stock",
    version: 0,
  });
  const [watchlist, setWatchlist] = useState(
    () => localStorage.getItem(WATCHLIST_STORAGE_KEY) || DEFAULT_WATCHLIST,
  );
  useEffect(() => {
    localStorage.setItem(WATCHLIST_STORAGE_KEY, watchlist);
  }, [watchlist]);
  const watchTickers = useMemo(() => parseTickers(watchlist), [watchlist]);
  const openStockDetail = (code: string) =>
    setDetailRequest((prev) => ({ code, assetType: "stock", version: prev.version + 1 }));

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

        <TickerTape
          tickers={watchTickers}
          financialsPath={financialsPath}
          onOpenDetail={(code) => {
            openStockDetail(code);
            setTab("detail");
          }}
          onOpenWatch={() => setTab("watch")}
        />

        {tab === "dashboard" && (
          <>
            <OneClickPanel
              holdingsCsv={holdingsCsv}
              financialsPath={financialsPath}
              watchTickers={watchTickers}
              onMarket={setMarketSnapshot}
              onAnalysis={setAnalysis}
              onCandidates={setCandidates}
              onReport={setReport}
              onMove={setTab}
            />
            <Dashboard
              marketSnapshot={marketSnapshot}
              analysis={analysis}
              candidates={candidates}
              report={report}
              onMove={setTab}
            />
          </>
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
            onUseForReport={(csv) => {
              setHoldingsCsv(csv);
              setTab("report");
            }}
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
            onOpenRag={(codes) => {
              setRagDraft((prev) => ({
                ...prev,
                query: codes.length > 0 ? codes.join(" ") : prev.query,
                version: Date.now(),
              }));
              setTab("rag");
            }}
            onUseForReport={(csv) => {
              setHoldingsCsv(csv);
              setTab("report");
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
        {tab === "watch" && <WatchPanel
          financialsPath={financialsPath}
          watchlist={watchlist}
          setWatchlist={setWatchlist}
          holdingsCsv={holdingsCsv}
          onOpenDetail={(code) => {
            openStockDetail(code);
            setTab("detail");
          }}
        />}
        {tab === "forecast" && <ForecastScreenPanel onOpenDetail={(code) => {
          setDetailRequest((prev) => ({ code, assetType: "stock", version: prev.version + 1 }));
          setTab("detail");
        }} />}
        {tab === "report" && (
          <ReportPanel
            holdingsCsv={holdingsCsv}
            financialsPath={financialsPath}
            ragDbPath={ragDraft.dbPath}
            candidates={candidates}
            onReport={setReport}
          />
        )}
        {tab === "rag" && (
          <RagSearchPanel
            draft={ragDraft}
            onDraftChange={setRagDraft}
            onOpenData={() => setTab("data")}
            onAskDraft={(draft) => {
              setChatDraft(draft);
              setTab("chat");
            }}
          />
        )}
        {tab === "chat" && (
          <ChatPanel
            draft={chatDraft}
            onDraftChange={setChatDraft}
            onSearchAgain={(draft) => {
              setRagDraft(draft);
              setTab("rag");
            }}
            onOpenData={() => setTab("data")}
          />
        )}
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
    { label: "配当見込み", value: yen(summary.annual_income_estimate), active: props.analysis !== null },
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
  const [scope, setScope] = useState<"tickers" | "nikkei225" | "financials_csv" | "domestic">("tickers");
  const [tickers, setTickers] = useState("8306,9433,7203");
  const [range, setRange] = useState("1mo");
  const [maxCount, setMaxCount] = useState("20");
  const [indexRag, setIndexRag] = useState(true);
  const { loading, error, data, run } = useAsync<Json>();
  const inventory = useAsync<Json>();
  const financialsPreview = useAsync<Json>();
  const ragBuild = useAsync<Json>();
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
    selectedScope: "tickers" | "nikkei225" | "financials_csv" | "domestic" = scope,
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
    if (selectedMode === "financials") body.index_rag = indexRag;
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
            <option value="domestic">全国内株式（JPX一覧）</option>
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
        {mode === "financials" && (
          <Check label="取得後にRAGへ登録" checked={indexRag} onChange={setIndexRag} />
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
        <button
          className="ghost"
          disabled={ragBuild.loading}
          title="取得済みの財務・株価CSVから銘柄ごとの根拠文書を作り、RAGに登録します"
          onClick={() =>
            void ragBuild
              .run(() => api<Json>("/api/market/rag/build", {}))
              .then((result) => {
                if (result) refreshDataView();
              })
          }
        >
          {ragBuild.loading ? "RAG登録中..." : "市場データをRAGへ登録"}
        </button>
      </ActionRow>
      <Status loading={loading} error={error} />
      {data && <MarketResult data={data} mode={mode} />}
      <Status loading={ragBuild.loading} error={ragBuild.error} />
      {ragBuild.data && (
        <p className="hint">
          RAG登録: {String(ragBuild.data.documents_written ?? 0)} 件の銘柄文書を生成・索引しました。
        </p>
      )}
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

type HoldingRow = {
  code: string;
  name: string;
  qty: string;
  avgCost: string;
  account: "tokutei" | "nisa_growth" | "nisa_tsumitate";
};

const ACCOUNT_LABELS: Record<HoldingRow["account"], string> = {
  tokutei: "特定/一般",
  nisa_growth: "NISA成長投資枠",
  nisa_tsumitate: "NISAつみたて枠",
};

function holdingRowsToCsv(rows: HoldingRow[]): string {
  const header =
    "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source";
  const lines = rows
    .filter((r) => r.code.trim())
    .map((r) => {
      const accountType = r.account === "tokutei" ? "tokutei" : "nisa";
      const taxWrapper = r.account === "tokutei" ? "taxable" : r.account;
      const name = (r.name.trim() || r.code.trim()).replace(/,/g, " ");
      return [
        "stock",
        r.code.trim(),
        name,
        r.qty.trim() || "0",
        r.avgCost.trim() || "0",
        accountType,
        taxWrapper,
        "user_csv",
      ].join(",");
    });
  return [header, ...lines].join("\n");
}

function candidatesToHoldingsCsv(rows: Json[], selected: Set<string>, perTicker: number): string {
  const header =
    "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source,current_price";
  const price = Math.max(Math.round(perTicker), 0);
  const lines = rows
    .filter((row) => {
      const code = candidateCode(row);
      return code && selected.has(code);
    })
    .map((row) => {
      const code = candidateCode(row);
      const assetType = detailAssetType(row.asset_type);
      const name = String(row.name || code).replace(/,/g, " ");
      // quantity=1 at a per-ticker price -> equal-weight by budget; avg=price -> no paper PnL.
      return [assetType, code, name, "1", String(price), "tokutei", "taxable", "user_csv", String(price)].join(",");
    });
  return [header, ...lines].join("\n");
}

function HoldingsBuilder({
  onApply,
  financialsPath,
}: {
  onApply: (csv: string) => void;
  financialsPath: string;
}) {
  const [rows, setRows] = useState<HoldingRow[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<HoldingRow>({
    code: "",
    name: "",
    qty: "100",
    avgCost: "",
    account: "tokutei",
  });

  useEffect(() => {
    void api<Json>("/api/market/names", { financials_csv: financialsPath })
      .then((data) => {
        const map: Record<string, string> = {};
        const list = Array.isArray(data.names) ? (data.names as Json[]) : [];
        for (const item of list) map[String(item.ticker)] = String(item.name);
        setNames(map);
      })
      .catch(() => {});
  }, [financialsPath]);

  // Resolve a typed code or company name to {code, name}; tap a datalist option
  // (value = code) or type a name and it is matched against the picker list.
  const resolve = (input: string): { code: string; name: string } => {
    const raw = input.trim();
    const code = raw.toUpperCase().replace(/\.T$/, "");
    if (/^\d{4,5}[A-Za-z]?$/.test(code)) return { code, name: names[code] || "" };
    const hit = Object.entries(names).find(([, name]) =>
      name.toLowerCase().includes(raw.toLowerCase()),
    );
    return hit ? { code: hit[0], name: hit[1] } : { code: raw, name: "" };
  };

  const onCodeInput = (value: string) => {
    const known = names[value.trim().toUpperCase().replace(/\.T$/, "")];
    setDraft((prev) => ({ ...prev, code: value, name: known || prev.name }));
  };

  const addRow = () => {
    if (!draft.code.trim()) return;
    const resolved = resolve(draft.code);
    setRows((prev) => [
      ...prev,
      { ...draft, code: resolved.code, name: draft.name.trim() || resolved.name },
    ]);
    setDraft({ code: "", name: "", qty: "100", avgCost: "", account: draft.account });
  };
  const removeRow = (index: number) => setRows((prev) => prev.filter((_, i) => i !== index));

  return (
    <div className="detail-section" aria-label="銘柄選択で保有を作成">
      <h4>銘柄を選んで保有を作成</h4>
      <p className="hint">コードと数量を追加していくと、下のCSVに反映できます（CSVを直接書く必要はありません）。</p>
      <div className="form-grid tight">
        <Field label="銘柄を検索して選択（コード or 会社名）">
          <input
            list="holdings-code-options"
            value={draft.code}
            onChange={(e) => onCodeInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addRow();
              }
            }}
            placeholder="例: 7203 / トヨタ / ソニー"
          />
          <datalist id="holdings-code-options">
            {Object.entries(names).map(([code, name]) => (
              <option key={code} value={code}>{`${code} ${name}`}</option>
            ))}
          </datalist>
        </Field>
        <Field label="銘柄名（自動・任意）">
          <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="トヨタ" />
        </Field>
        <Field label="数量（株）">
          <input value={draft.qty} inputMode="numeric" onChange={(e) => setDraft({ ...draft, qty: e.target.value })} />
        </Field>
        <Field label="平均取得単価">
          <input value={draft.avgCost} inputMode="decimal" onChange={(e) => setDraft({ ...draft, avgCost: e.target.value })} placeholder="2000" />
        </Field>
        <Field label="口座区分">
          <select value={draft.account} onChange={(e) => setDraft({ ...draft, account: e.target.value as HoldingRow["account"] })}>
            <option value="tokutei">特定/一般</option>
            <option value="nisa_growth">NISA成長投資枠</option>
            <option value="nisa_tsumitate">NISAつみたて枠</option>
          </select>
        </Field>
      </div>
      <ActionRow>
        <button onClick={addRow} disabled={!draft.code.trim()}>銘柄を追加</button>
        <button
          className="primary"
          disabled={rows.length === 0}
          onClick={() => onApply(holdingRowsToCsv(rows))}
        >
          選択した{rows.length}銘柄をCSVへ反映
        </button>
      </ActionRow>
      {rows.length > 0 && (
        <table className="data-table">
          <thead>
            <tr><th>コード</th><th>銘柄</th><th>数量</th><th>取得単価</th><th>口座</th><th></th></tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.code}-${i}`}>
                <td>{r.code}</td>
                <td>{r.name || "-"}</td>
                <td>{r.qty}</td>
                <td>{r.avgCost || "-"}</td>
                <td>{ACCOUNT_LABELS[r.account]}</td>
                <td><button className="table-action" onClick={() => removeRow(i)}>削除</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function HoldingsPanel(props: {
  csvText: string;
  setCsvText: (value: string) => void;
  financialsPath: string;
  onAnalysis: (value: Json) => void;
  onUseForReport: (csv: string) => void;
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
      <ScreenTitle title="保有分析" body="銘柄を選ぶ（またはCSVを貼る）と、評価額・損益・NISA区分・配当見込みを集計します。" />
      <HoldingsBuilder onApply={props.setCsvText} financialsPath={props.financialsPath} />
      <textarea value={props.csvText} onChange={(e) => props.setCsvText(e.target.value)} spellCheck={false} />
      <ActionRow>
        <button onClick={() => void loadTemplate()}>テンプレート</button>
        <button onClick={() => void validate()}>検証</button>
        <button className="primary" onClick={() => void analyze()}>
          分析
        </button>
        <button
          disabled={!props.csvText.trim()}
          title="この保有でレポート（配当見込みを含む）を作成します"
          onClick={() => props.onUseForReport(props.csvText)}
        >
          このポートフォリオでレポート
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
  onOpenRag: (codes: string[]) => void;
  onUseForReport: (csv: string) => void;
}) {
  const [minEquity, setMinEquity] = useState("30");
  const [maxExpense, setMaxExpense] = useState("0.3");
  const [nisaOnly, setNisaOnly] = useState(true);
  const [excludeCut, setExcludeCut] = useState(true);
  const [budget, setBudget] = useState("1000000");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [simCsv, setSimCsv] = useState("");
  const state = useAsync<Json>();
  const sim = useAsync<Json>();

  const candidateRows: Json[] = Array.isArray(state.data?.results) ? (state.data!.results as Json[]) : [];

  const runScreen = async () => {
    setSelected(new Set());
    sim.reset();
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

  const toggle = (code: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  const simulate = () => {
    const perTicker = (Number(budget) || 0) / Math.max(selected.size, 1);
    const csv = candidatesToHoldingsCsv(candidateRows, selected, perTicker);
    setSimCsv(csv);
    void sim.run(() => api<Json>("/api/portfolio/analyze", { csv_text: csv, financials_csv: props.financialsPath }));
  };

  return (
    <section className="screen">
      <ScreenTitle title="候補抽出" body="条件で抽出 → 銘柄を選んで「ポートフォリオ試算」。おすすめ・買い指示は出しません。" />
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
      {state.data && (
        <>
          <div className="detail-section" aria-label="選択銘柄でポートフォリオ試算">
            <h4>選択した銘柄でポートフォリオ試算</h4>
            <p className="hint">表のチェックで銘柄を選び、予算を等分して評価額・配当・集中度を試算します（非助言）。</p>
            <div className="form-grid tight">
              <Field label="投資予算（円・等分）">
                <input value={budget} inputMode="numeric" onChange={(e) => setBudget(e.target.value)} />
              </Field>
              <Field label="選択数">
                <input value={`${selected.size} 銘柄`} readOnly />
              </Field>
            </div>
            <ActionRow>
              <button className="primary" disabled={selected.size === 0 || sim.loading} onClick={simulate}>
                {sim.loading ? "試算中..." : "選択銘柄でポートフォリオ試算"}
              </button>
              <button disabled={selected.size === 0} onClick={() => props.onOpenRag([...selected])}>
                選択銘柄をRAG検索
              </button>
            </ActionRow>
          </div>
          <CandidateTable data={state.data} onOpenDetail={props.onOpenDetail} selected={selected} onToggle={toggle} />
          <Status loading={sim.loading} error={sim.error} />
          {sim.data && (
            <>
              <AnalysisResult data={sim.data} />
              <ActionRow>
                <button
                  className="primary"
                  disabled={!simCsv}
                  title="この試算ポートフォリオでレポート（配当見込みを含む）を作成します"
                  onClick={() => props.onUseForReport(simCsv)}
                >
                  このポートフォリオでレポート作成
                </button>
              </ActionRow>
            </>
          )}
        </>
      )}
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
  const forecast = useAsync<Json>();
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
        {assetType === "stock" && (
          <button
            className="ghost"
            disabled={forecast.loading || !code.trim()}
            title="取得済みのdaily_barsから次5営業日の終値を統計的に予測します"
            onClick={() =>
              void forecast.run(() =>
                api<Json>("/api/market/forecast", { ticker: code.trim(), horizon: 5 }),
              )
            }
          >
            {forecast.loading ? "予測中..." : "株価予測（5日）"}
          </button>
        )}
      </ActionRow>
      <Status loading={state.loading} error={state.error} />
      {state.data && <DetailResult data={state.data} onMove={props.onMove} />}
      <Status loading={forecast.loading} error={forecast.error} />
      {forecast.data && <ForecastResult data={forecast.data} />}
    </section>
  );
}

type StepState = "pending" | "running" | "done" | "error";

function OneClickPanel(props: {
  holdingsCsv: string;
  financialsPath: string;
  watchTickers: string[];
  onMarket: (value: Json) => void;
  onAnalysis: (value: Json) => void;
  onCandidates: (value: Json) => void;
  onReport: (value: Json) => void;
  onMove: (tab: TabId) => void;
}) {
  const labels = ["市場データ更新", "保有分析", "候補抽出", "レポート生成", "RAGに保存・索引"];
  const [status, setStatus] = useState<StepState[]>([
    "pending",
    "pending",
    "pending",
    "pending",
    "pending",
  ]);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const holdingTickers = useMemo(
    () => holdingStockTickers(props.holdingsCsv),
    [props.holdingsCsv],
  );
  const hasHoldings = holdingTickers.length > 0;

  const run = async () => {
    setRunning(true);
    setNote(null);
    setStatus(["pending", "pending", "pending", "pending", "pending"]);
    const setStep = (index: number, value: StepState) =>
      setStatus((prev) => prev.map((current, idx) => (idx === index ? value : current)));
    const errors: string[] = [];
    const step = async (index: number, fn: () => Promise<void>, skip = false) => {
      if (skip) {
        setStep(index, "done");
        return;
      }
      setStep(index, "running");
      try {
        await fn();
        setStep(index, "done");
      } catch (caught) {
        setStep(index, "error");
        errors.push(`${labels[index]}: ${caught instanceof Error ? caught.message : String(caught)}`);
      }
    };

    // 1. refresh market data for the holdings (fall back to the watch list).
    const refreshTickers = hasHoldings ? holdingTickers : props.watchTickers;
    await step(0, async () => {
      const result = await api<Json>("/api/market/refresh", { tickers: refreshTickers });
      props.onMarket(result);
    }, refreshTickers.length === 0);

    // 2. portfolio analysis (needs holdings).
    await step(1, async () => {
      const result = await api<Json>("/api/portfolio/analyze", {
        csv_text: props.holdingsCsv,
        financials_csv: props.financialsPath,
      });
      props.onAnalysis(result);
    }, !hasHoldings);

    // 3. candidate screening.
    let candidateRows: Json[] = [];
    await step(2, async () => {
      const result = await api<Json>("/api/candidates/screen", {
        asset_types: ["stock", "fund"],
        financials_csv: props.financialsPath,
      });
      props.onCandidates(result);
      candidateRows = Array.isArray(result.results) ? (result.results as Json[]) : [];
    });

    // 4. monthly report (needs holdings).
    let reportObj: Json | null = null;
    await step(3, async () => {
      const result = await api<Json>("/api/reports/investment-monthly", {
        csv_text: props.holdingsCsv,
        financials_csv: props.financialsPath,
        candidates: candidateRows,
        save_history: true,
      });
      props.onReport(result);
      reportObj = result;
    }, !hasHoldings);

    // 5. save the report as markdown and index it into the RAG store, so the
    //    AI / RAG search can cite this run's analysis. Strengthens RAG search.
    await step(4, async () => {
      if (!reportObj) throw new Error("レポートが無いため索引できません");
      await api<Json>("/api/reports/investment-monthly/markdown/save", {
        report: reportObj,
        index_after_save: true,
      });
    }, !hasHoldings || !reportObj);

    setRunning(false);
    if (errors.length) {
      setNote(`一部スキップ/失敗: ${errors.join(" / ")}`);
    } else if (!hasHoldings) {
      setNote("保有銘柄が未入力のため、候補抽出のみ実行しました。保有分析タブで保有を入力すると全工程（レポート→RAG索引）が動きます。");
    } else {
      setNote("完了：データ更新→保有分析→候補抽出→レポート→RAG索引まで実行しました。AI確認/RAG検索で今回の分析を根拠に使えます。");
    }
  };

  const icon = (state: StepState) =>
    state === "done" ? "✓" : state === "running" ? "…" : state === "error" ? "×" : "・";

  return (
    <section className="oneclick">
      <div className="oneclick-head">
        <div>
          <h3>ワンクリック実行</h3>
          <p className="muted">データ更新 → 保有分析 → 候補抽出 → レポートを順に自動実行します（非助言）。</p>
        </div>
        <button className="primary" disabled={running} onClick={() => void run()}>
          {running ? "実行中..." : "▶ 全工程を実行"}
        </button>
      </div>
      <ol className="oneclick-steps">
        {labels.map((label, index) => (
          <li key={label} className={`oneclick-step ${status[index]}`}>
            <span className="oc-icon">{icon(status[index])}</span>
            <span className="oc-label">{`${index + 1}. ${label}`}</span>
          </li>
        ))}
      </ol>
      {note && <p className="hint">{note}</p>}
      {status[3] === "done" && (
        <button className="ghost" onClick={() => props.onMove("report")}>レポートを開く →</button>
      )}
    </section>
  );
}

function TickerTape(props: {
  tickers: string[];
  financialsPath: string;
  onOpenDetail: (code: string) => void;
  onOpenWatch: () => void;
}) {
  const [cells, setCells] = useState<Json[]>([]);
  const key = props.tickers.join(",");

  useEffect(() => {
    if (props.tickers.length === 0) {
      setCells([]);
      return;
    }
    let active = true;
    const fetchTape = async () => {
      try {
        const data = await api<Json>("/api/market/heatmap", {
          tickers: props.tickers,
          sort_by: "ticker",
          limit: 0,
          financials_csv: props.financialsPath,
        });
        if (active && Array.isArray(data.cells)) setCells(data.cells as Json[]);
      } catch {
        /* keep the last good tape on a transient error */
      }
    };
    void fetchTape();
    const id = window.setInterval(() => void fetchTape(), 30000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, props.financialsPath]);

  if (cells.length === 0) return null;
  const items = [...cells, ...cells]; // duplicated for a seamless loop
  return (
    <div className="ticker-tape" aria-label="株価ティッカー" title="クリックでウォッチへ" onClick={props.onOpenWatch}>
      <div
        className="ticker-track"
        style={{ animationDuration: `${Math.max(cells.length * 4, 20)}s` }}
      >
        {items.map((cell, index) => {
          const pct = cell.change_pct == null ? null : Number(cell.change_pct);
          const tone = pct == null ? "flat" : pct > 0 ? "up" : pct < 0 ? "down" : "flat";
          return (
            <button
              key={`${String(cell.ticker)}-${index}`}
              className={`ticker-item ${tone}`}
              title={`${String(cell.name)} (${String(cell.ticker)})`}
              onClick={(event) => {
                event.stopPropagation();
                props.onOpenDetail(String(cell.ticker));
              }}
            >
              <span className="ti-name">{String(cell.name)}</span>
              <span className="ti-price">{Number(cell.last_close).toLocaleString()}</span>
              <span className="ti-change">
                {pct == null ? "—" : `${pct > 0 ? "▲" : pct < 0 ? "▼" : ""}${Math.abs(pct).toFixed(2)}%`}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="heatmap-spark-empty" />;
  const width = 120;
  const height = 28;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const points = values
    .map((value, index) => `${(index * step).toFixed(1)},${(height - ((value - min) / span) * height).toFixed(1)}`)
    .join(" ");
  const rising = values[values.length - 1] >= values[0];
  return (
    <svg className="heatmap-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points} fill="none" stroke={rising ? "#bbf7d0" : "#fecaca"} strokeWidth={2} />
    </svg>
  );
}

function heatColor(pct: number | null, fullAt = 2.5): string {
  if (pct == null) return "#242932"; // deep slate; no washed-out transparency
  // `fullAt` = the % move at which colour reaches full strength (smaller =
  // stronger/darker for small moves). Driven by the "色の濃さ" slider.
  const t = Math.min(Math.abs(pct) / Math.max(fullAt, 0.1), 1);
  if (pct >= 0) {
    // deep green -> rich green; darker overall so white text reads clearly
    const g = Math.round(95 + t * 70); // 95..165
    return `rgb(${Math.round(5 + t * 6)},${g},${Math.round(32 + t * 22)})`;
  }
  // deep red -> rich red
  const r = Math.round(140 + t * 70); // 140..210
  return `rgb(${r},${Math.round(20 + t * 18)},${Math.round(20 + t * 18)})`;
}

function watchBreadth(cells: Json[]): { up: number; down: number; flat: number; avg: number } {
  let up = 0;
  let down = 0;
  let flat = 0;
  let sum = 0;
  let counted = 0;
  for (const cell of cells) {
    const pct = cell.change_pct == null ? null : Number(cell.change_pct);
    if (pct == null || !Number.isFinite(pct)) {
      flat += 1;
      continue;
    }
    sum += pct;
    counted += 1;
    if (pct > 0) up += 1;
    else if (pct < 0) down += 1;
    else flat += 1;
  }
  return { up, down, flat, avg: counted > 0 ? sum / counted : 0 };
}

function holdingStockTickers(csv: string): string[] {
  const lines = csv.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length < 2) return [];
  const header = lines[0].split(",").map((cell) => cell.trim());
  const codeIdx = header.indexOf("ticker_or_fund_code");
  const typeIdx = header.indexOf("asset_type");
  if (codeIdx < 0) return [];
  const out: string[] = [];
  for (let i = 1; i < lines.length; i += 1) {
    const cols = lines[i].split(",");
    const code = (cols[codeIdx] || "").trim().toUpperCase().replace(/\.T$/, "");
    const type = typeIdx >= 0 ? (cols[typeIdx] || "").trim().toLowerCase() : "stock";
    if (code && type === "stock") out.push(code);
  }
  return out;
}

function WatchPanel(props: {
  financialsPath: string;
  watchlist: string;
  setWatchlist: (value: string) => void;
  holdingsCsv: string;
  onOpenDetail: (code: string) => void;
}) {
  const watchlist = props.watchlist;
  const setWatchlist = props.setWatchlist;
  const [sortBy, setSortBy] = useState(() => localStorage.getItem("ia.watchSort") || "change");
  const [auto, setAuto] = useState(() => localStorage.getItem("ia.watchAuto") !== "0");
  const [strength, setStrength] = useState(
    () => Number(localStorage.getItem("ia.heatmapStrength")) || 8,
  );
  useEffect(() => {
    localStorage.setItem("ia.heatmapStrength", String(strength));
  }, [strength]);
  useEffect(() => {
    localStorage.setItem("ia.watchSort", sortBy);
  }, [sortBy]);
  useEffect(() => {
    localStorage.setItem("ia.watchAuto", auto ? "1" : "0");
  }, [auto]);
  const heatmap = useAsync<Json>();
  const gaps = useAsync<Json>();
  const backfill = useAsync<Json>();
  const refresh = useAsync<Json>();
  const cells: Json[] = Array.isArray(heatmap.data?.cells) ? (heatmap.data!.cells as Json[]) : [];
  const breadth = watchBreadth(cells);
  const missing: string[] = Array.isArray(gaps.data?.missing_any)
    ? (gaps.data!.missing_any as string[])
    : [];
  const gapCounts: Json = (gaps.data?.counts as Json) ?? {};

  const tickers = useMemo(() => parseTickers(watchlist), [watchlist]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");

  useEffect(() => {
    void api<Json>("/api/market/names", { financials_csv: props.financialsPath })
      .then((data) => {
        const map: Record<string, string> = {};
        const list = Array.isArray(data.names) ? (data.names as Json[]) : [];
        for (const item of list) map[String(item.ticker)] = String(item.name);
        setNames(map);
      })
      .catch(() => {});
  }, [props.financialsPath]);

  const holdingCodes = useMemo(
    () => holdingStockTickers(props.holdingsCsv),
    [props.holdingsCsv],
  );
  const newHoldingCodes = holdingCodes.filter((code) => !tickers.includes(code));

  const addTicker = (code: string) => {
    const normalized = code.trim().toUpperCase().replace(/\.T$/, "");
    if (!normalized || tickers.includes(normalized)) return;
    setWatchlist([...tickers, normalized].join(" "));
  };
  const addTickers = (codes: string[]) => {
    const merged = [...tickers];
    for (const code of codes) {
      const normalized = code.trim().toUpperCase().replace(/\.T$/, "");
      if (normalized && !merged.includes(normalized)) merged.push(normalized);
    }
    setWatchlist(merged.join(" "));
  };
  const removeTicker = (code: string) =>
    setWatchlist(tickers.filter((item) => item !== code).join(" "));
  const addFromQuery = () => {
    const q = query.trim();
    if (!q) return;
    if (/^\d{4,5}[A-Za-z]?$/.test(q)) {
      addTicker(q);
    } else {
      const hit = Object.entries(names).find(([, name]) =>
        name.toLowerCase().includes(q.toLowerCase()),
      );
      if (hit) addTicker(hit[0]);
    }
    setQuery("");
  };

  const load = () =>
    heatmap.run(() =>
      api<Json>("/api/market/heatmap", {
        tickers,
        sort_by: sortBy,
        limit: 0,
        financials_csv: props.financialsPath,
      }),
    );
  const loadGaps = () => gaps.run(() => api<Json>("/api/market/gaps", { tickers }));
  const runBackfill = async () => {
    const result = await backfill.run(() => api<Json>("/api/market/backfill", { tickers }));
    if (result) {
      void load();
      void loadGaps();
    }
  };
  const runRefresh = async () => {
    const result = await refresh.run(() => api<Json>("/api/market/refresh", { tickers }));
    if (result) {
      void load();
      void loadGaps();
    }
  };

  useEffect(() => {
    void load();
    void loadGaps();
    if (!auto) return;
    const id = setInterval(() => void load(), 60000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, sortBy, watchlist]);

  return (
    <section className="screen">
      <ScreenTitle
        title="ウォッチ（ヒートマップ）"
        body="登録銘柄の前日終値比を色で一目確認します（緑=上昇 / 赤=下落）。価格系列の機械集計であり、売買推奨ではありません。"
      />
      <Field label="ウォッチリストに追加（コード or 会社名で検索）">
        <div className="watch-add">
          <input
            list="watch-name-options"
            value={query}
            placeholder="例: 7203 / トヨタ / ソニー"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addFromQuery();
              }
            }}
          />
          <button className="primary" onClick={addFromQuery}>＋追加</button>
          <datalist id="watch-name-options">
            {Object.entries(names).map(([code, name]) => (
              <option key={code} value={code}>{`${code} ${name}`}</option>
            ))}
          </datalist>
        </div>
      </Field>
      {newHoldingCodes.length > 0 && (
        <button className="ghost watch-holdings-add" onClick={() => addTickers(newHoldingCodes)}>
          保有銘柄をウォッチに追加（{newHoldingCodes.length}）
        </button>
      )}
      <div className="watch-chips" aria-label="ウォッチ銘柄">
        {tickers.length === 0 && <span className="muted">銘柄がありません。上で追加してください。</span>}
        {tickers.map((code) => (
          <span key={code} className="watch-chip">
            <button
              className="chip-label"
              title="詳細を見る"
              onClick={() => props.onOpenDetail(code)}
            >
              <b>{code}</b>
              <small>{names[code] || ""}</small>
            </button>
            <button className="chip-remove" title="削除" onClick={() => removeTicker(code)}>×</button>
          </span>
        ))}
      </div>
      <div className="form-grid tight">
        <Field label="並び順">
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="change">変動が大きい順</option>
            <option value="gain">上昇順</option>
            <option value="loss">下落順</option>
            <option value="ticker">コード順</option>
          </select>
        </Field>
        <Field label={`色の濃さ（薄い ◀ ▶ 濃い）: ${strength}`}>
          <input
            type="range"
            min={1}
            max={10}
            step={1}
            value={strength}
            onChange={(e) => setStrength(Number(e.target.value))}
          />
        </Field>
      </div>
      <ActionRow>
        <button className="primary" disabled={refresh.loading} onClick={() => void runRefresh()}>
          {refresh.loading ? "価格取得中..." : "価格を更新（最新取得）"}
        </button>
        <button className="ghost" disabled={heatmap.loading} onClick={() => void load()}>
          {heatmap.loading ? "再描画中..." : "再描画"}
        </button>
        {missing.length > 0 && (
          <button className="ghost" disabled={backfill.loading} onClick={() => void runBackfill()}>
            {backfill.loading ? "補完中..." : `不足を補完（${missing.length}銘柄）`}
          </button>
        )}
        <Check label="自動更新（60秒）" checked={auto} onChange={setAuto} />
      </ActionRow>
      {gaps.data && (
        <p className="hint">
          {missing.length === 0
            ? "データはすべて揃っています。"
            : `不足: 株価 ${String(gapCounts.missing_price ?? 0)} 銘柄 / 日足 ${String(
                gapCounts.missing_bars ?? 0,
              )} 銘柄。「不足を補完」で該当銘柄だけ取得します。`}
        </p>
      )}
      <Status
        loading={heatmap.loading || backfill.loading || refresh.loading}
        error={heatmap.error || backfill.error || refresh.error}
      />
      {heatmap.data && (
        <>
          <p className="hint">
            {String(heatmap.data.count ?? cells.length)} 銘柄
            {cells.some((cell) => cell.price_source === "intraday")
              ? "（現在値・当日比）"
              : `（前日終値比 / 基準日 ${String(heatmap.data.as_of ?? "-")}）`}
            ・非助言。「価格を更新」で最新を取得します。
          </p>
          {cells.length > 0 && (
            <div className="watch-breadth" aria-label="ウォッチ全体の騰落">
              <span className="breadth-pill up">▲ 上昇 {breadth.up}</span>
              <span className="breadth-pill down">▼ 下落 {breadth.down}</span>
              <span className="breadth-pill flat">— 変わらず {breadth.flat}</span>
              <span className={`breadth-avg ${breadth.avg >= 0 ? "up" : "down"}`}>
                平均 {breadth.avg >= 0 ? "+" : ""}
                {breadth.avg.toFixed(2)}%
              </span>
            </div>
          )}
          <div className="heatmap-grid">
            {cells.map((cell) => {
              const pct = cell.change_pct == null ? null : Number(cell.change_pct);
              return (
                <button
                  key={String(cell.ticker)}
                  className="heatmap-cell"
                  style={{ background: heatColor(pct, 11 - strength) }}
                  title={`${String(cell.name)} (${String(cell.ticker)})`}
                  onClick={() => props.onOpenDetail(String(cell.ticker))}
                >
                  <span className="heatmap-code">{String(cell.ticker)}</span>
                  <span className="heatmap-name">{String(cell.name)}</span>
                  <Sparkline values={Array.isArray(cell.spark) ? (cell.spark as number[]) : []} />
                  <span className="heatmap-price">{Number(cell.last_close).toLocaleString()}</span>
                  <span className="heatmap-change">
                    {pct == null ? "—" : `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`}
                  </span>
                </button>
              );
            })}
          </div>
          {cells.length === 0 && (
            <p className="muted">
              該当データがありません。「データ更新」で日足（daily_bars）を取得してください。
            </p>
          )}
        </>
      )}
    </section>
  );
}

function ForecastScreenPanel(props: { onOpenDetail: (code: string) => void }) {
  const [horizon, setHorizon] = useState("5");
  const [top, setTop] = useState("50");
  const [maxAbsReturn, setMaxAbsReturn] = useState("30");
  const screen = useAsync<Json>();
  const results: Json[] = Array.isArray(screen.data?.results) ? (screen.data!.results as Json[]) : [];

  const run = () =>
    screen.run(() =>
      api<Json>("/api/market/forecast/screen", {
        horizon: Number(horizon) || 5,
        top: Number(top) || 50,
        max_abs_return: Number(maxAbsReturn) || 0,
      }),
    );

  return (
    <section className="screen">
      <ScreenTitle
        title="予測スクリーニング"
        body="取得済みの株価系列から、銘柄ごとの期待リターンを統計的に予測してランキングします。買い推奨ではありません。"
      />
      <div className="form-grid tight">
        <Field label="予測期間（営業日）">
          <input value={horizon} inputMode="numeric" onChange={(e) => setHorizon(e.target.value)} />
        </Field>
        <Field label="上位件数">
          <input value={top} inputMode="numeric" onChange={(e) => setTop(e.target.value)} />
        </Field>
        <Field label="妥当性上限（±%）">
          <input value={maxAbsReturn} inputMode="numeric" onChange={(e) => setMaxAbsReturn(e.target.value)} />
        </Field>
      </div>
      <ActionRow>
        <button className="primary" disabled={screen.loading} onClick={() => void run()}>
          {screen.loading ? "予測中..." : "予測スクリーニング実行"}
        </button>
      </ActionRow>
      <Status loading={screen.loading} error={screen.error} />
      {screen.data && (
        <div className="detail-section">
          <p className="hint">
            {String(screen.data.ranked_count ?? results.length)} 件（期待リターン降順 /
            {" "}非助言の統計推定）
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>コード</th>
                <th>直近終値</th>
                <th>予測終値</th>
                <th>期待リターン</th>
                <th>RMSE%</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => (
                <tr key={String(row.ticker)}>
                  <td>{String(row.ticker)}</td>
                  <td>{Math.round(Number(row.last_close)).toLocaleString()}</td>
                  <td>{Math.round(Number(row.forecast_close)).toLocaleString()}</td>
                  <td>{Number(row.expected_return_pct).toFixed(2)}%</td>
                  <td>{row.rmse_pct == null ? "-" : `${Number(row.rmse_pct).toFixed(2)}%`}</td>
                  <td>
                    <button className="table-action" onClick={() => props.onOpenDetail(String(row.ticker))}>
                      詳細
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ForecastResult({ data }: { data: Json }) {
  const values: number[] = Array.isArray(data.forecast) ? (data.forecast as number[]) : [];
  const rmse = data.backtest_rmse;
  return (
    <div className="detail-section rag-stats" aria-label="株価予測">
      <h3>株価予測（統計的推定・投資助言ではありません）</h3>
      <p className="hint">
        直近終値 {Math.round(Number(data.last_close)).toLocaleString()} 円（{String(data.last_date)}） /
        観測 {String(data.observations)} 営業日
      </p>
      <ol className="forecast-list">
        {values.map((value, index) => (
          <li key={index}>
            +{index + 1}営業日後: <b>{Math.round(value).toLocaleString()} 円</b>
          </li>
        ))}
      </ol>
      <p className="hint">
        バックテスト最良モデル: {String(data.backtest_best_model ?? "-")} / RMSE{" "}
        {typeof rmse === "number" ? rmse.toFixed(4) : "-"}
      </p>
    </div>
  );
}

function ReportPanel(props: {
  holdingsCsv: string;
  financialsPath: string;
  ragDbPath: string;
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
  const createFromCandidates = async () => {
    const rows = Array.isArray(props.candidates?.results) ? (props.candidates!.results as Json[]) : [];
    const codes = rows.map(candidateCode).filter(Boolean).slice(0, 10);
    if (codes.length === 0) return;
    const perTicker = Math.round(1_000_000 / codes.length);
    const csv = candidatesToHoldingsCsv(rows, new Set(codes), perTicker);
    const result = await state.run(() =>
      api<Json>("/api/reports/investment-monthly", {
        csv_text: csv,
        financials_csv: props.financialsPath,
        candidates: rows,
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
          <p className="hint">
            配当見込みは下の「保有明細」（保有分析や候補抽出で試算したポートフォリオ）から自動計算されます。
            別のポートフォリオにするには、保有分析・候補抽出で「このポートフォリオでレポート」を押してください。
          </p>
          <div className="detail-metrics">
            <DetailFact label="保有明細" value={`${holdingRows}行`} />
            <DetailFact label="財務CSV" value={shortPath(props.financialsPath) || "-"} />
            <DetailFact label="候補" value={`${candidateCount}件`} />
            <DetailFact label="RAG DB" value={shortPath(props.ragDbPath) || "-"} />
            <DetailFact label="保存" value="履歴に保存" tone="safe" />
          </div>
        </div>
        {holdingRows === 0 && candidateCount > 0 && (
          <div className="report-shortcut">
            <p className="hint">
              保有が空でも、<b>条件一致の候補 上位10件</b>を等金額（計100万円）で試算してレポートを作れます。
              これは比較材料の機械試算であり、売買推奨ではありません（非助言）。
            </p>
            <button className="primary" disabled={state.loading} onClick={() => void createFromCandidates()}>
              候補上位10件で試算してレポート
            </button>
          </div>
        )}
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
      {displayReport && <ReportResult data={displayReport} ragDbPath={props.ragDbPath} />}
    </section>
  );
}

function RagSearchPanel(props: {
  draft: RagSearchDraft;
  onDraftChange: (value: RagSearchDraft) => void;
  onOpenData: () => void;
  onAskDraft: (value: ChatDraft) => void;
}) {
  const { draft } = props;
  const { query, dbPath, limit } = draft;
  const [hybrid, setHybrid] = useState(true);
  const [selectedEvidence, setSelectedEvidence] = useState<Record<string, boolean>>({});
  const searchState = useAsync<Json>();
  const statsState = useAsync<Json>();
  const results = Array.isArray(searchState.data?.results) ? (searchState.data.results as Json[]) : [];
  const selectedResults = results.filter((result, index) => selectedEvidence[ragResultKey(result, index)] !== false);
  const requestedLimit = Number(limit) || 8;
  const updateDraft = (patch: Partial<Omit<RagSearchDraft, "version">>) => {
    props.onDraftChange({ ...draft, ...patch });
  };

  const searchWith = (q: string) =>
    searchState.run(() =>
      api<Json>("/api/rag/search", {
        query: q,
        db_path: dbPath,
        limit: requestedLimit,
        hybrid,
      }),
    );
  const search = () => searchWith(query);

  const sendToChat = () => {
    props.onAskDraft({
      query: buildRagChatPrompt(query, selectedResults),
      dbPath,
      limit: Number(limit) || DEFAULT_CHAT_LIMIT,
      evidence: selectedResults,
      searchQuery: query,
    });
  };

  const setAllEvidence = (value: boolean) =>
    setSelectedEvidence(
      Object.fromEntries(results.map((result, index) => [ragResultKey(result, index), value])),
    );
  const allSelected = results.length > 0 && selectedResults.length === results.length;

  const refreshStats = () =>
    statsState.run(() =>
      api<Json>("/api/rag/stats", {
        db_path: dbPath,
      }),
    );

  useEffect(() => {
    void refreshStats();
  }, []);

  useEffect(() => {
    setSelectedEvidence(
      Object.fromEntries(results.map((result, index) => [ragResultKey(result, index), true])),
    );
  }, [searchState.data]);

  // When navigated here from another panel (e.g. candidate selection bumps the
  // draft version), auto-run the search for the handed-off query.
  useEffect(() => {
    if (props.draft.version > 0 && query.trim()) void search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.draft.version]);

  return (
    <section className="screen">
      <ScreenTitle
        title="RAG検索"
        body="保存済みレポートや開示文書を先に検索し、AIへ渡す前の根拠を確認します。"
      />
      <div className="form-grid">
        <Field label="検索語">
          <input
            value={query}
            onChange={(event) => updateDraft({ query: event.target.value })}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void search();
              }
            }}
            placeholder="Enterで検索"
          />
        </Field>
        <Field label="RAG DB">
          <input value={dbPath} onChange={(event) => updateDraft({ dbPath: event.target.value })} />
        </Field>
        <Field label="件数">
          <input value={limit} onChange={(event) => updateDraft({ limit: event.target.value })} inputMode="numeric" />
        </Field>
        <Check label="ハイブリッド検索" checked={hybrid} onChange={setHybrid} />
      </div>
      <div className="quick-queries" aria-label="検索例">
        {QUICK_QUERY_PRESETS.map((item) => (
          <button
            key={item}
            className="table-action"
            onClick={() => {
              updateDraft({ query: item });
              void searchWith(item);
            }}
          >
            {item}
          </button>
        ))}
      </div>
      <ActionRow>
        <button className="primary" onClick={() => void search()}>
          検索
        </button>
        <button onClick={sendToChat}>AI確認へ送る（{selectedResults.length}件）</button>
        <button onClick={() => void refreshStats()}>索引を確認</button>
      </ActionRow>
      <Status loading={searchState.loading || statsState.loading} error={searchState.error || statsState.error} />
      {statsState.data && (
        <>
          <RagIndexQuality data={statsState.data} onOpenData={props.onOpenData} />
          <RagStatsSummary data={statsState.data} />
        </>
      )}
      {searchState.data && (
        <ResultBlock title="検索結果" meta={`${results.length}件 / ${hybrid ? "hybrid" : "keyword"}`}>
          <RagEvidenceQuality
            title="検索結果の根拠量"
            results={results}
            requestedLimit={requestedLimit}
            selectedCount={selectedResults.length}
            actionLabel="データ更新へ"
            onAction={props.onOpenData}
          />
          {results.length > 1 && (
            <div className="evidence-toolbar" aria-label="根拠の一括選択">
              <span>{selectedResults.length}/{results.length} 件をAI確認に使用</span>
              <button
                className="table-action"
                disabled={allSelected}
                onClick={() => setAllEvidence(true)}
              >
                すべて選択
              </button>
              <button
                className="table-action"
                disabled={selectedResults.length === 0}
                onClick={() => setAllEvidence(false)}
              >
                すべて解除
              </button>
            </div>
          )}
          <RagSearchResults
            results={results}
            selectedEvidence={selectedEvidence}
            onToggleEvidence={(key, value) => {
              setSelectedEvidence((prev) => ({ ...prev, [key]: value }));
            }}
          />
          <JsonDetails data={searchState.data} />
        </ResultBlock>
      )}
    </section>
  );
}

function RagIndexQuality({ data, onOpenData }: { data: Json; onOpenData: () => void }) {
  const warnings = ragIndexWarnings(data);
  return (
    <QualityNotice
      title="RAGデータ量"
      warnings={warnings}
      okMessage="RAG索引には検索に使える文書とチャンクがあります。"
      actionLabel="データ更新へ"
      onAction={onOpenData}
    />
  );
}

function RagStatsSummary({ data }: { data: Json }) {
  return (
    <section className="detail-section rag-stats" aria-label="RAG索引の状態">
      <h4>索引の状態</h4>
      <div className="detail-metrics">
        <DetailFact label="文書" value={`${String(data.sources_count ?? 0)}件`} />
        <DetailFact label="チャンク" value={`${String(data.chunks_count ?? 0)}件`} />
        <DetailFact label="文字数" value={String(data.total_chars ?? 0)} />
        <DetailFact label="DB" value={shortPath(String(data.db_path ?? "")) || "-"} />
      </div>
    </section>
  );
}

function RagSearchResults(props: {
  results: Json[];
  selectedEvidence?: Record<string, boolean>;
  onToggleEvidence?: (key: string, value: boolean) => void;
}) {
  const { results, selectedEvidence, onToggleEvidence } = props;
  if (results.length === 0) {
    return <p className="muted">一致する根拠は見つかりませんでした。</p>;
  }
  return (
    <div className="rag-results">
      {results.map((result, index) => {
        const citation = asJson(result.citation) ?? {};
        const key = ragResultKey(result, index);
        const checked = selectedEvidence?.[key] !== false;
        return (
          <article className={checked ? "rag-result selected" : "rag-result"} key={key}>
            <header>
              <div className="rag-title">
                <b>{String(citation.label ?? `#${index + 1}`)}</b>
                {onToggleEvidence && (
                  <label className="rag-select">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) => onToggleEvidence(key, event.target.checked)}
                    />
                    <span>AI確認に使う</span>
                  </label>
                )}
              </div>
              <span>{formatScore(citation.score ?? result.score)}</span>
            </header>
            <p>{previewText(result.text, 360)}</p>
            <div className="rag-meta">
              <span>文書: {shortPath(String(result.source ?? ""))}</span>
              <span>チャンク: {String(result.chunk_index ?? "-")}</span>
              {citation.report_id && <span>レポートID: {String(citation.report_id)}</span>}
              {citation.integrity_status && <span>整合性: {String(citation.integrity_status)}</span>}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function ChatPanel(props: {
  draft: ChatDraft;
  onDraftChange: (value: ChatDraft) => void;
  onSearchAgain: (value: RagSearchDraft) => void;
  onOpenData: () => void;
}) {
  const [query, setQuery] = useState(props.draft.query);
  const [dbPath, setDbPath] = useState(props.draft.dbPath);
  const [limit, setLimit] = useState(String(props.draft.limit));
  const state = useAsync<Json>();
  const ragResults = Array.isArray(state.data?.results) ? (state.data.results as Json[]) : [];
  const handoffEvidence = Array.isArray(props.draft.evidence) ? props.draft.evidence : [];
  const answerText = String(state.data?.answer ?? state.data?.text ?? "回答がありません。");
  const requestedLimit = Number(limit) || DEFAULT_CHAT_LIMIT;
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const copyAnswer = async () => {
    try {
      await copyTextToClipboard(buildAnswerCopyText(query, answerText, ragResults));
      setCopyNotice("回答と根拠をコピーしました。");
    } catch (caught) {
      setCopyNotice(`コピーに失敗しました: ${caught instanceof Error ? caught.message : String(caught)}`);
    }
  };
  useEffect(() => {
    setQuery(props.draft.query);
    setDbPath(props.draft.dbPath);
    setLimit(String(props.draft.limit));
  }, [props.draft]);
  const updateQuery = (value: string) => {
    setQuery(value);
    props.onDraftChange({
      query: value,
      dbPath,
      limit: Number(limit) || DEFAULT_CHAT_LIMIT,
      evidence: props.draft.evidence,
      searchQuery: props.draft.searchQuery,
    });
  };
  const updateDbPath = (value: string) => {
    setDbPath(value);
    props.onDraftChange({
      query,
      dbPath: value,
      limit: Number(limit) || DEFAULT_CHAT_LIMIT,
      evidence: props.draft.evidence,
      searchQuery: props.draft.searchQuery,
    });
  };
  const updateLimit = (value: string) => {
    setLimit(value);
    props.onDraftChange({
      query,
      dbPath,
      limit: Number(value) || DEFAULT_CHAT_LIMIT,
      evidence: props.draft.evidence,
      searchQuery: props.draft.searchQuery,
    });
  };
  const searchAgain = () => {
    props.onSearchAgain({
      query: props.draft.searchQuery ?? suggestedRagQueryFromChat(query),
      dbPath,
      limit: String(Number(limit) || DEFAULT_CHAT_LIMIT),
      version: Date.now(),
    });
  };
  const ask = () =>
    state.run(() =>
      api<Json>("/api/rag/answer", {
        query,
        db_path: dbPath,
        limit: Number(limit) || DEFAULT_CHAT_LIMIT,
        call_real_api: false,
      }),
    );
  const askWith = (q: string) => {
    updateQuery(q);
    return state.run(() =>
      api<Json>("/api/rag/answer", {
        query: q,
        db_path: dbPath,
        limit: Number(limit) || DEFAULT_CHAT_LIMIT,
        call_real_api: false,
      }),
    );
  };
  return (
    <section className="screen">
      <ScreenTitle title="AI確認" body="RAGの根拠を確認するための補助チャットです。数値判断は決定論エンジンを優先します。" />
      <div className="form-grid tight">
        <Field label="RAG DB">
          <input value={dbPath} onChange={(event) => updateDbPath(event.target.value)} />
        </Field>
        <Field label="件数">
          <input value={limit} onChange={(event) => updateLimit(event.target.value)} inputMode="numeric" />
        </Field>
      </div>
      <textarea
        value={query}
        onChange={(e) => updateQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            void ask();
          }
        }}
        placeholder="質問を入力（Ctrl/⌘+Enterで確認）"
      />
      <div className="quick-queries" aria-label="よく使う質問">
        {QUICK_QUERY_PRESETS.map((item) => (
          <button
            key={item}
            className="table-action"
            onClick={() => void askWith(item)}
          >
            {item}
          </button>
        ))}
      </div>
      <RagEvidenceQuality
        title="AI確認に渡す根拠量"
        results={handoffEvidence}
        requestedLimit={requestedLimit}
        selectedCount={handoffEvidence.length}
        actionLabel="データ更新へ"
        onAction={props.onOpenData}
      />
      {handoffEvidence.length > 0 && (
        <RagEvidenceCards title="AI確認に渡した根拠" results={handoffEvidence} idPrefix="handoff-evidence" />
      )}
      <ActionRow>
        <button className="primary" onClick={() => void ask()}>
          確認する
        </button>
        <button onClick={searchAgain}>根拠を追加検索</button>
      </ActionRow>
      <Status loading={state.loading} error={state.error} />
      {state.data && (
        <div className="answer">
          <div className="answer-head">
            <h3>回答</h3>
            <button className="table-action" onClick={() => void copyAnswer()}>
              回答をコピー
            </button>
          </div>
          {copyNotice && <p className="notice safe">{copyNotice}</p>}
          <ForecastHighlights highlights={Array.isArray(state.data.highlights) ? (state.data.highlights as Json[]) : []} />
          <RagEvidenceQuality
            title="回答時の根拠量"
            results={ragResults}
            requestedLimit={requestedLimit}
            actionLabel="データ更新へ"
            onAction={props.onOpenData}
          />
          <CitationLinkedText text={answerText} citationCount={ragResults.length} targetPrefix="answer-evidence" />
          {ragResults.length > 0 && (
            <RagEvidenceCards title="回答時に照合した根拠" results={ragResults} idPrefix="answer-evidence" />
          )}
          <JsonDetails data={state.data} />
        </div>
      )}
    </section>
  );
}

function ForecastHighlights({ highlights }: { highlights: Json[] }) {
  if (highlights.length === 0) return null;
  return (
    <div className="detail-section" aria-label="予測ハイライト">
      <h4>予測ハイライト（統計推定・非助言）</h4>
      <ul className="forecast-highlights">
        {highlights.map((item, index) => (
          <li key={`${String(item.ticker ?? item.source ?? index)}`}>
            <b>
              {item.name ? `${String(item.name)}` : ""}
              {item.ticker ? `（${String(item.ticker)}）` : ""}
            </b>
            {item.forecast ? <div>予測: {String(item.forecast)}</div> : null}
            {item.tags ? <div className="hint">特徴: {String(item.tags)}</div> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function RagEvidenceQuality(props: {
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

function CitationLinkedText(props: { text: string; citationCount: number; targetPrefix: string }) {
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

function RagEvidenceCards({ title, results, idPrefix }: { title: string; results: Json[]; idPrefix?: string }) {
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
                <b>[{citation.number}] {citation.label}</b>
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

function evidenceSummary(result: Json, index: number) {
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

const PIE_COLORS = [
  "#4f8cff", "#ff8a5b", "#2dd4bf", "#f6c453", "#a78bfa",
  "#f472b6", "#34d399", "#fb7185", "#60a5fa", "#facc15",
];

function PieChart({ slices }: { slices: { label: string; value: number }[] }) {
  const sorted = slices.filter((s) => s.value > 0).sort((a, b) => b.value - a.value);
  const total = sorted.reduce((sum, s) => sum + s.value, 0);
  if (total <= 0) return null;

  // Keep the chart readable: top 8 slices, the rest grouped as "その他".
  const top = sorted.slice(0, 8);
  const restValue = sorted.slice(8).reduce((sum, s) => sum + s.value, 0);
  const segments = restValue > 0 ? [...top, { label: "その他", value: restValue }] : top;

  const cx = 80, cy = 80, r = 72;
  let angle = -Math.PI / 2;
  const arcs = segments.map((seg, index) => {
    const frac = seg.value / total;
    const a0 = angle;
    const a1 = angle + frac * 2 * Math.PI;
    angle = a1;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    const large = frac > 0.5 ? 1 : 0;
    const d = `M${cx},${cy} L${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)} Z`;
    return { d, color: PIE_COLORS[index % PIE_COLORS.length], label: seg.label, pct: frac * 100 };
  });

  return (
    <div style={{ display: "flex", gap: "1.2rem", alignItems: "center", flexWrap: "wrap", margin: "0.6rem 0" }}>
      <svg viewBox="0 0 160 160" width="170" height="170" role="img" aria-label="ポートフォリオ構成比">
        {segments.length === 1 ? (
          <circle cx={cx} cy={cy} r={r} fill={arcs[0].color} />
        ) : (
          arcs.map((a, i) => <path key={i} d={a.d} fill={a.color} stroke="#0b1220" strokeWidth="0.6" />)
        )}
      </svg>
      <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: "0.85rem", lineHeight: 1.7 }}>
        {arcs.map((a, i) => (
          <li key={i} style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <span style={{ width: 11, height: 11, borderRadius: 3, background: a.color, display: "inline-block", flexShrink: 0 }} />
            <span>{a.label}</span>
            <b style={{ marginLeft: "auto", paddingLeft: "0.8rem" }}>{a.pct.toFixed(1)}%</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AnalysisResult({ data }: { data: Json }) {
  const rows = Array.isArray(data.holdings) ? data.holdings : [];
  const slices = rows
    .map((row) => ({
      label: String(row.name || row.ticker_or_fund_code || "?"),
      value: Number(row.market_value) || 0,
    }))
    .filter((s) => s.value > 0);
  return (
    <ResultBlock title="分析結果" meta={`評価額: ${yen(data.summary?.market_value)}`}>
      {slices.length > 0 && (
        <>
          <h4>ポートフォリオ構成比（評価額）</h4>
          <PieChart slices={slices} />
        </>
      )}
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
  selected,
  onToggle,
}: {
  data: Json;
  onOpenDetail: (code: string, assetType: "stock" | "fund") => void;
  selected: Set<string>;
  onToggle: (code: string) => void;
}) {
  const rows = Array.isArray(data.results) ? data.results : [];
  return (
    <ResultBlock title="候補抽出結果" meta={`${String(data.count ?? rows.length)} 件`}>
      {rows.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>選択</th>
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
                    <td>
                      <input
                        type="checkbox"
                        disabled={!code}
                        checked={Boolean(code) && selected.has(code)}
                        onChange={() => code && onToggle(code)}
                        aria-label={`${code} を選択`}
                      />
                    </td>
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

function ReportResult({ data, ragDbPath }: { data: Json; ragDbPath: string }) {
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
        db_path: ragDbPath,
        index_after_save: true,
      }),
    );
    if (result?.saved_path) {
      const indexed = asJson(result.indexed);
      const chunks = indexed?.chunks_indexed ?? "-";
      const indexedDbPath = String(indexed?.db_path ?? result.db_path ?? ragDbPath);
      setMarkdownNotice(
        `ローカル保存しました: ${String(result.saved_path)} / RAG ${String(chunks)}チャンク / DB ${shortPath(indexedDbPath)}`,
      );
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
            PDFは印刷保存、.md保存は端末へのダウンロード、RAG保存はlocal_docs/reportsへ保存し、現在のRAG DBへ登録します。
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
  function reset() {
    setData(null);
    setError(null);
    setLoading(false);
  }
  return { loading, error, data, run, reset };
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

function buildRagChatPrompt(query: string, results: Json[]): string {
  const trimmedQuery = query.trim() || "RAG検索結果";
  const citations = results
    .slice(0, 5)
    .map((result, index) => {
      const citation = asJson(result.citation) ?? {};
      const source = shortPath(String(result.source ?? ""));
      const rawLabel = citation.label ?? source;
      const label = String(rawLabel || `根拠${index + 1}`);
      const preview = previewText(result.text, 180);
      return `- [${index + 1}] ${label}${source ? ` / ${source}` : ""}\n  要約: ${preview}`;
    })
    .filter(Boolean);
  const citationBlock =
    citations.length > 0 ? `\n\n確認済み根拠候補:\n${citations.join("\n")}` : "";
  return `「${trimmedQuery}」について、RAGの根拠を引用しながら、投資助言にならない形で要点・不確実性・追加確認事項を簡潔に説明して。${citationBlock}`;
}

function buildAnswerCopyText(query: string, answerText: string, results: Json[]): string {
  const lines = [`Q: ${query.trim() || "(質問なし)"}`, "", answerText.trim()];
  if (results.length > 0) {
    lines.push("", "根拠:");
    results.forEach((result, index) => {
      const citation = asJson(result.citation) ?? {};
      const source = shortPath(String(result.source ?? ""));
      const label = String(citation.label ?? source ?? `根拠${index + 1}`);
      lines.push(`[${index + 1}] ${label}${source && label !== source ? ` / ${source}` : ""}`);
    });
  }
  lines.push("", "※本ツールは投資助言・売買推奨を行いません（根拠確認の補助）。");
  return lines.join("\n");
}

function suggestedRagQueryFromChat(query: string): string {
  const trimmed = query.trim();
  const quoted = trimmed.match(/^「(.+?)」について/);
  if (quoted?.[1]?.trim()) return quoted[1].trim();
  return trimmed.slice(0, 120) || "配当 利回り 根拠";
}

function ragIndexWarnings(data: Json): string[] {
  const sources = Number(data.sources_count ?? 0);
  const chunks = Number(data.chunks_count ?? 0);
  const chars = Number(data.total_chars ?? 0);
  const warnings: string[] = [];
  if (!sources || !chunks) {
    warnings.push("RAG索引に登録済み文書がありません。レポート保存・開示文書取得・RAG保存で根拠を追加してください。");
    return warnings;
  }
  if (sources < 3) warnings.push(`登録文書が${sources}件です。比較や反証には複数ソースの追加が必要です。`);
  if (chunks < 10) warnings.push(`検索チャンクが${chunks}件です。回答の根拠が薄くなりやすい状態です。`);
  if (chars < 1000) warnings.push("登録テキスト量が少ないため、本文PDF/HTML/レポート本文の追加登録を推奨します。");
  return warnings;
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

function ragResultKey(result: Json, index: number): string {
  return String(result.chunk_id ?? `${result.source ?? "source"}-${result.chunk_index ?? index}`);
}

function previewText(value: unknown, maxLength: number): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text || "-";
  return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`;
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
