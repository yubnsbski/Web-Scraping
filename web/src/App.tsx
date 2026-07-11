import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { ChatView } from "./chat/ChatView";
import { VirtualTradeView } from "./vtrade/VirtualTradeView";

type Json = Record<string, any>;
type TabId = "watch" | "data" | "holdings" | "vtrade" | "screen" | "detail" | "forecast" | "report" | "chat" | "plans";
type DetailRequest = { code: string; assetType: "stock" | "fund"; version: number };

const FINANCIALS_PATH = "local_docs/edinet/financials.csv";
const DEFAULT_RAG_DB_PATH = ".cache/investment_assistant/rag.sqlite";
const WATCHLIST_STORAGE_KEY = "ia.watchlist";
const DEFAULT_WATCHLIST = "7203 8306 9433 9432 6758 6861 8058 9984";

function parseTickers(text: string): string[] {
  return text.split(/[\s,]+/).map((code) => code.trim()).filter(Boolean);
}

// Header-only defaults: no pre-loaded sample holdings/funds. Build your own
// via the 銘柄選択 builder / 候補抽出, or use the "テンプレート" button for examples.
const SAMPLE_HOLDINGS_CSV =
  "asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source,current_price,annual_income,distribution_per_unit,data_provider,price_as_of";

const SAMPLE_FUNDS_CSV =
  "fund_code,name,asset_class,expense_ratio,distribution_policy,nisa_eligible,provider_id,diversification_score";

const TABS: Array<{
  id: TabId;
  label: string;
  short: string;
  group: "main" | "more";
}> = [
  // Sprint-2 nav reorg: the AI advisor is the front door. Primary (main)
  // group is the 4-step "just ask" workflow; everything else moves to the
  // 詳細機能 (advanced) group below.
  { id: "chat", label: "AIアドバイザー", short: "AI", group: "main" },
  { id: "holdings", label: "保有分析", short: "保有", group: "main" },
  { id: "vtrade", label: "仮想取引", short: "売買", group: "main" },
  { id: "screen", label: "候補抽出", short: "候補", group: "main" },
  { id: "data", label: "データ更新", short: "更新", group: "main" },
  { id: "report", label: "レポート", short: "報告", group: "more" },
  { id: "watch", label: "ウォッチ", short: "監視", group: "more" },
  { id: "forecast", label: "予測スクリーニング", short: "予測", group: "more" },
  { id: "detail", label: "詳細", short: "詳細", group: "more" },
  { id: "plans", label: "プラン設計", short: "設計", group: "more" },
];

const MAIN_TABS = TABS.filter((item) => item.group === "main");
const MORE_TABS = TABS.filter((item) => item.group === "more");

export function App() {
  // AI-first: every load lands on the chat assistant, regardless of the tab
  // remembered from the previous session ("ia.tab" still drives in-session
  // navigation state).
  const [tab, setTab] = useState<TabId>("chat");
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
    <div className={tab === "chat" ? "app-shell chat-mode" : "app-shell"}>
      {tab !== "chat" && (
        <aside className="side">
          <div className="brand">
            <span>投資支援</span>
            <b>Evidence Desk</b>
          </div>
          <nav className="nav" aria-label="主要画面">
            {MAIN_TABS.map((item) => (
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
            <details className="nav-more">
              <summary>詳細機能</summary>
              <div className="nav-more-list">
                {MORE_TABS.map((item) => (
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
              </div>
            </details>
          </nav>
          <p className="side-note">売買推奨・自動売買は行いません。判断材料と根拠を整理します。</p>
        </aside>
      )}

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

        {tab === "data" && (
          <DataUpdatePanel
            financialsPath={financialsPath}
            setFinancialsPath={setFinancialsPath}
            onMarket={setMarketSnapshot}
            onOpenDetail={(code) => {
              setDetailRequest((prev) => ({ code, assetType: "stock", version: prev.version + 1 }));
              setTab("detail");
            }}
            onMove={setTab}
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
        {tab === "vtrade" && <VirtualTradeView />}
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
            ragDbPath={DEFAULT_RAG_DB_PATH}
            candidates={candidates}
            onReport={setReport}
          />
        )}
        {tab === "chat" && <ChatView onNavigate={(tabId) => setTab(tabId as TabId)} />}
        {tab === "plans" && <PlanBuilderPanel />}
      </main>
    </div>
  );
}

function DataUpdatePanel(props: {
  financialsPath: string;
  setFinancialsPath: (value: string) => void;
  onMarket: (value: Json) => void;
  onOpenDetail: (code: string) => void;
  onMove: (tab: TabId) => void;
}) {
  const [mode, setMode] = useState<"financials" | "ohlcv" | "intraday" | "inbox">("financials");
  const [scope, setScope] = useState<"tickers" | "nikkei225" | "financials_csv" | "domestic">("domestic");
  const [tickers, setTickers] = useState("8306,9433,7203");
  const [range, setRange] = useState("1mo");
  const [maxCount, setMaxCount] = useState("20");
  const [indexRag, setIndexRag] = useState(true);
  const [batchSteps, setBatchSteps] = useState<Json[]>([]);
  const [batchSummary, setBatchSummary] = useState<Json | null>(null);
  const [safePresetNotice, setSafePresetNotice] = useState("");
  const { loading, error, data, run } = useAsync<Json>();
  const inventory = useAsync<Json>();
  const diagnostics = useAsync<Json>();
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

  const refreshDiagnostics = () => diagnostics.run(() => api<Json>("/api/system/diagnostics"));

  const refreshDataView = () => {
    void refreshDiagnostics();
    void refreshInventory();
    void refreshFinancialsPreview();
  };

  useEffect(() => {
    refreshDataView();
  }, [props.financialsPath]);

  const executeUpdate = async (
    selectedMode: "financials" | "ohlcv" | "intraday" | "inbox" = mode,
    selectedScope: "tickers" | "nikkei225" | "financials_csv" | "domestic" = scope,
    options: { maxCount?: string | number; range?: string } = {},
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
      max_count: Number(options.maxCount ?? maxCount) || 0,
      save_csv: selectedMode !== "intraday",
    };
    if (selectedMode === "ohlcv") body.range = options.range ?? range;
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

  const useSafeYahooPreset = () => {
    setMode("financials");
    setScope("domestic");
    setMaxCount("20");
    setRange("1mo");
    setIndexRag(true);
    setSafePresetNotice("安全設定に戻しました。全国内株式から20件、1か月分を取得します。");
  };

  const runYahooBatchUpdate = async () => {
    const selectedScope = canUseUniverse ? scope : "tickers";
    const selectedNeedsTickers = selectedScope === "tickers";
    if (selectedNeedsTickers && tickerList.length === 0) return;
    setBatchSummary(null);
    setSafePresetNotice("");
    let financialRows = 0;
    let financialsPath = "-";
    let dailyBarsRows = 0;
    let dailyBarsPath = "-";
    let ragDocuments = indexRag ? "-" : "skip";
    const baseBody: Json = {
      max_count: Number(maxCount) || 0,
      save_csv: true,
    };
    if (selectedNeedsTickers) baseBody.tickers = tickerList;
    else baseBody.universe = selectedScope;
    if (selectedScope === "financials_csv") baseBody.financials_csv = props.financialsPath;

    const steps: Json[] = [
      { key: "financials", label: "市場財務指標", status: "running" },
      { key: "ohlcv", label: "株価四本値・出来高", status: "pending" },
      { key: "rag", label: "RAG登録", status: indexRag ? "pending" : "skip", message: indexRag ? undefined : "任意" },
    ];
    setBatchSteps(steps);
    const mark = (key: string, patch: Json) => {
      setBatchSteps((current) => current.map((step) => (step.key === key ? { ...step, ...patch } : step)));
    };

    const financials = await run(() =>
      api<Json>("/api/market/financials", {
        ...baseBody,
        index_rag: indexRag,
      }),
    );
    if (!financials) {
      mark("financials", { status: "error", message: "取得できませんでした" });
      setBatchSummary({ status: "error", finished_at: new Date().toISOString(), message: "市場財務指標の取得で停止しました。", financial_rows: financialRows, financials_path: financialsPath, daily_bars_rows: dailyBarsRows, daily_bars_path: dailyBarsPath, rag_documents: ragDocuments });
      return;
    }
    financialRows = Object.keys((financials.financials ?? {}) as Json).length;
    financialsPath = String(financials.output_path ?? "-");
    mark("financials", {
      status: "done",
      message: `${Object.keys((financials.financials ?? {}) as Json).length}件 / ${String(financials.output_path ?? "-")}`,
    });
    props.onMarket(financials);

    mark("ohlcv", { status: "running" });
    const bars = await run(() =>
      api<Json>("/api/market/bars/universe", {
        ...baseBody,
        range,
      }),
    );
    if (!bars) {
      mark("ohlcv", { status: "error", message: "取得できませんでした" });
      setBatchSummary({ status: "partial", finished_at: new Date().toISOString(), message: "市場財務指標は取得済みですが、株価四本値・出来高で停止しました。", financial_rows: financialRows, financials_path: financialsPath, daily_bars_rows: dailyBarsRows, daily_bars_path: dailyBarsPath, rag_documents: ragDocuments });
      refreshDataView();
      return;
    }
    dailyBarsRows = Number(bars.daily_bars_count ?? 0);
    dailyBarsPath = String(bars.daily_bars_path ?? "-");
    mark("ohlcv", {
      status: "done",
      message: `${String(bars.daily_bars_count ?? 0)}行 / ${String(bars.daily_bars_path ?? "-")}`,
    });
    props.onMarket(bars);
    setMode("ohlcv");
    if (!indexRag) {
      setBatchSummary({ status: "done", finished_at: new Date().toISOString(), message: "市場財務指標と株価四本値・出来高を更新しました。", financial_rows: financialRows, financials_path: financialsPath, daily_bars_rows: dailyBarsRows, daily_bars_path: dailyBarsPath, rag_documents: ragDocuments });
      refreshDataView();
      return;
    }

    mark("rag", { status: "running" });
    const rag = await ragBuild.run(() => api<Json>("/api/market/rag/build", {}));
    if (rag) {
      ragDocuments = String(rag.documents_written ?? 0);
      mark("rag", { status: "done", message: `${String(rag.documents_written ?? 0)}件` });
    } else {
      ragDocuments = "error";
      mark("rag", { status: "error", message: "登録できませんでした" });
    }
    setBatchSummary({ status: ragDocuments === "error" ? "partial" : "done", finished_at: new Date().toISOString(), message: ragDocuments === "error" ? "市場データは更新済みですが、RAG登録で確認が必要です。" : "市場データとRAG材料を更新しました。", financial_rows: financialRows, financials_path: financialsPath, daily_bars_rows: dailyBarsRows, daily_bars_path: dailyBarsPath, rag_documents: ragDocuments });
    refreshDataView();
  };
  const runInventoryAction = async (action: Json) => {
    const type = String(action.action_type ?? "");
    const actionScope = normalizeUpdateScope(action.recommended_scope) ?? scope;
    const actionMaxCount = action.recommended_max_count ?? maxCount;
    const actionRange = String(action.recommended_range ?? range);
    if (type === "market_financials") {
      setMode("financials");
      setScope(actionScope);
      setMaxCount(String(actionMaxCount));
      await executeUpdate("financials", actionScope, { maxCount: actionMaxCount });
    } else if (type === "daily_bars") {
      setMode("ohlcv");
      setScope(actionScope);
      setMaxCount(String(actionMaxCount));
      setRange(actionRange);
      await executeUpdate("ohlcv", actionScope, { maxCount: actionMaxCount, range: actionRange });
    } else if (type === "price_inbox") {
      setMode("inbox");
      await executeUpdate("inbox", scope);
    }
  };

  const batchDisabledReason =
    needsTickers && tickerList.length === 0
      ? "銘柄コードを入力してください。"
      : loading || ragBuild.loading
        ? "処理中です。完了後に再実行できます。"
        : "";
  return (
    <section className="screen">
      <ScreenTitle title="データ更新" body="取得対象とデータ種別を選び、1つのボタンでCSVへ反映します。" />
      <SystemDiagnosticsPanel
        data={diagnostics.data}
        loading={diagnostics.loading}
        error={diagnostics.error}
        onRefresh={() => void refreshDiagnostics()}
      />
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
      <YahooBatchUpdatePanel
        steps={batchSteps}
        summary={batchSummary}
        loading={loading || ragBuild.loading}
        disabled={(needsTickers && tickerList.length === 0) || loading || ragBuild.loading}
        scope={canUseUniverse ? scope : "tickers"}
        maxCount={maxCount}
        range={range}
        indexRag={indexRag}
        tickerCount={tickerList.length}
        financialsPath={props.financialsPath}
        disabledReason={batchDisabledReason}
        safePresetNotice={safePresetNotice}
        onMove={props.onMove}
        onUseSafePreset={useSafeYahooPreset}
        onRun={() => void runYahooBatchUpdate()}
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

function YahooBatchUpdatePanel(props: {
  steps: Json[];
  summary: Json | null;
  loading: boolean;
  disabled: boolean;
  scope: string;
  maxCount: string;
  range: string;
  indexRag: boolean;
  tickerCount: number;
  financialsPath: string;
  disabledReason: string;
  safePresetNotice: string;
  onMove: (tab: TabId) => void;
  onUseSafePreset: () => void;
  onRun: () => void;
}) {
  const scopeLabel: Record<string, string> = {
    tickers: "入力銘柄",
    nikkei225: "日経225",
    financials_csv: "財務CSV",
    domestic: "全国内株式",
  };
  const steps = props.steps.length > 0
    ? props.steps
    : [
        { key: "financials", label: "市場財務指標", status: "pending" },
        { key: "ohlcv", label: "株価四本値・出来高", status: "pending" },
        { key: "rag", label: "RAG登録", status: props.indexRag ? "pending" : "skip", message: "任意" },
      ];
  return (
    <section className="inventory yahoo-batch-panel">
      <header className="inventory-head">
        <div>
          <h3>Yahoo!一括更新</h3>
          <p>市場財務指標と株価四本値・出来高を続けて取得します。初期設定は全国内株式から少数取得です。</p>
        </div>
        <div className="batch-head-actions">
          <button className="ghost" disabled={props.loading} onClick={props.onUseSafePreset}>
            安全設定に戻す
          </button>
          <button className="primary" disabled={props.disabled} onClick={props.onRun}>
            {props.loading ? "一括更新中..." : "Yahoo!を一括更新"}
          </button>
        </div>
      </header>
      <div className="inventory-summary">
        <InventoryPill label={"対象"} value={scopeLabel[props.scope] ?? props.scope} tone="muted" />
        <InventoryPill label={"上限"} value={props.maxCount === "0" ? "全件" : `${props.maxCount}件`} tone="muted" />
        <InventoryPill label={"期間"} value={props.range} tone="muted" />
        <InventoryPill label={"入力"} value={props.scope === "tickers" ? `${props.tickerCount}件` : "自動展開"} tone={props.disabledReason ? "warn" : "ready"} />
      </div>
      {props.summary && (
        <div className="batch-summary">
          <b>{String(props.summary.message ?? "今回の更新結果")}</b>
          <span>完了: {formatDateTime(props.summary.finished_at)}</span>
          <span>市場財務: {String(props.summary.financial_rows ?? "-")}件</span>
          <span>OHLCV: {String(props.summary.daily_bars_rows ?? "-")}行</span>
          <span>RAG: {String(props.summary.rag_documents ?? "-")}</span>
          <code>{String(props.summary.financials_path ?? "-")}</code>
          <code>{String(props.summary.daily_bars_path ?? "-")}</code>
        </div>
      )}
      <div className="batch-preflight">
        <span>実行内容: 市場財務指標 → 株価四本値・出来高{props.indexRag ? " → RAG登録" : ""}</span>
        <code>{props.financialsPath}</code>
        {props.disabledReason ? <b>{props.disabledReason}</b> : <b>{props.scope === "domestic" && props.maxCount !== "0" ? "安全な少数取得" : "実行できます"}</b>}
      </div>
      {props.safePresetNotice && <p className="notice safe batch-preset-notice">{props.safePresetNotice}</p>}
      <div className="batch-impact" aria-label="更新データの反映先">
        <b>反映先</b>
        <span>市場財務 → 候補抽出・詳細・レポート</span>
        <span>OHLCV → 予測・価格確認</span>
        <span>RAG → AIアドバイザーでの根拠確認</span>
      </div>
      <div className="batch-step-list">
        {steps.map((step) => (
          <article className={`batch-step ${String(step.status ?? "pending")}`} key={String(step.key)}>
            <b>{String(step.label ?? step.key)}</b>
            <span>{batchStepLabel(String(step.status ?? "pending"))}</span>
            {step.message && <code>{String(step.message)}</code>}
          </article>
        ))}
      </div>
      {steps.some((step) => step.status === "done") && (
        <div className="batch-next-actions" aria-label="次に見る画面">
          <span>次に見る</span>
          <button className="table-action" onClick={() => props.onMove("forecast")}>予測へ</button>
          <button className="table-action" onClick={() => props.onMove("chat")}>AIで確認</button>
          <button className="table-action" onClick={() => props.onMove("screen")}>候補抽出へ</button>
        </div>
      )}
      <p className="notice safe">売買推奨・自動売買は行いません。取得データを比較材料として整理します。</p>
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

function SystemDiagnosticsPanel(props: {
  data: Json | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  const status = String(props.data?.status ?? "unknown");
  const criticalRoutes = (asJson(props.data?.critical_routes) ?? {}) as Json;
  const frontend = asJson(props.data?.frontend) ?? {};
  const routeEntries = Object.entries(criticalRoutes);
  const missingRoutes = routeEntries.filter(([, ok]) => ok !== true);
  const frontendAssets = Number(frontend.asset_count ?? 0);
  const safeFlagsOk = props.data?.auto_trading === false && props.data?.call_real_api === false;
  return (
    <section className="inventory system-diagnostics">
      <header className="inventory-head">
        <div>
          <h3>{"\u63a5\u7d9a\u8a3a\u65ad"}</h3>
          <p>{"\u30d5\u30ed\u30f3\u30c8\u3068\u30d0\u30c3\u30af\u30a8\u30f3\u30c9\u306e\u63a5\u7d9a\u3001\u4e3b\u8981API\u3001\u753b\u9762\u8cc7\u7523\u306e\u72b6\u614b\u3092\u78ba\u8a8d\u3057\u307e\u3059\u3002"}</p>
        </div>
        <button onClick={props.onRefresh} disabled={props.loading}>
          {props.loading ? "\u78ba\u8a8d\u4e2d..." : "\u518d\u78ba\u8a8d"}
        </button>
      </header>
      <Status loading={props.loading} error={props.error} />
      <div className="inventory-summary">
        <InventoryPill label="\u30b5\u30fc\u30d0" value={status === "ok" ? "\u6b63\u5e38" : "\u8981\u78ba\u8a8d"} tone={status === "ok" ? "ready" : "warn"} />
        <InventoryPill label="API\u6570" value={String(props.data?.route_count ?? 0)} tone="muted" />
        <InventoryPill label="\u4e3b\u8981API" value={missingRoutes.length === 0 ? "\u4e0d\u8db3\u306a\u3057" : `${missingRoutes.length}\u4ef6\u4e0d\u8db3`} tone={missingRoutes.length === 0 ? "ready" : "error"} />
        <InventoryPill label="\u753b\u9762\u8cc7\u7523" value={frontendAssets > 0 ? "\u751f\u6210\u6e08\u307f" : "\u672a\u691c\u51fa"} tone={frontendAssets > 0 ? "ready" : "warn"} />
      </div>
      <div className="diagnostic-route-list" aria-label="critical API routes">
        {routeEntries.map(([path, ok]) => (
          <span className={`diagnostic-route ${ok === true ? "ready" : "error"}`} key={path}>
            <code>{path}</code>
            <b>{ok === true ? "\u5229\u7528\u53ef" : "\u4e0d\u8db3"}</b>
          </span>
        ))}
        {routeEntries.length === 0 && !props.loading && <p className="muted">{"\u4e3b\u8981API\u306e\u72b6\u614b\u306f\u307e\u3060\u53d6\u5f97\u3057\u3066\u3044\u307e\u305b\u3093\u3002"}</p>}
      </div>
      <p className={`notice ${safeFlagsOk ? "safe" : ""}`}>
        {"\u5b89\u5168\u30d5\u30e9\u30b0: \u81ea\u52d5\u58f2\u8cb7=false / \u5b9fAPI\u547c\u3073\u51fa\u3057=false"}
      </p>
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
  const coreDatasetIds = new Set(["market_financials", "daily_bars", "selected_financials", "rag_db"]);
  const coreDatasets = datasets.filter((item) => coreDatasetIds.has(String(item.id ?? "")));
  const attentionDatasets = datasets.filter(isActionableAttentionDataset);
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
        <InventoryPill label="今すぐ必要" value={`${String(summary.required_action_count ?? 0)}件`} tone={Number(summary.required_action_count ?? 0) > 0 ? "warn" : "ready"} />
        <InventoryPill label="任意補完" value={`${String(summary.optional_action_count ?? 0)}件`} tone={Number(summary.optional_action_count ?? 0) > 0 ? "muted" : "ready"} />
      </div>
      <DataInventoryGuide coreDatasets={coreDatasets} attentionDatasets={attentionDatasets} actions={actions} />
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

function isActionableAttentionDataset(item: Json): boolean {
  const itemStatus = String(item.status ?? "");
  if (!["missing", "stale", "partial", "empty", "error"].includes(itemStatus)) {
    return false;
  }
  if (itemStatus === "empty" && item.required !== true) {
    return false;
  }
  return true;
}
function formatDatasetAge(item: Json | undefined): string {
  if (!item) return "経過時間不明";
  const ageHours = Number(item.age_hours ?? NaN);
  const freshnessDays = Number(item.freshness_days ?? NaN);
  const ageText = Number.isFinite(ageHours)
    ? ageHours >= 24
      ? `約${(ageHours / 24).toLocaleString("ja-JP", { maximumFractionDigits: 1 })}日経過`
      : `約${Math.round(ageHours)}時間経過`
    : "経過時間不明";
  const freshnessText = Number.isFinite(freshnessDays) ? `基準${freshnessDays}日` : "基準不明";
  return `${ageText} / ${freshnessText}`;
}

function formatAttentionDataset(item: Json): string {
  const label = String(item.label ?? item.id ?? "データ");
  const status = statusLabel(String(item.status ?? "unknown"));
  const rows = formatRows(item);
  const age = formatDatasetAge(item);
  return `${label}: ${status}（${rows}、${age}）`;
}
function DataInventoryGuide(props: { coreDatasets: Json[]; attentionDatasets: Json[]; actions: Json[] }) {
  if (props.coreDatasets.length === 0 && props.attentionDatasets.length === 0 && props.actions.length === 0) return null;
  const marketFinancials = props.coreDatasets.find((item) => String(item.id ?? "") === "market_financials");
  const dailyBars = props.coreDatasets.find((item) => String(item.id ?? "") === "daily_bars");
  const marketTickerCount = Number(marketFinancials?.ticker_count ?? 0);
  const barsTickerCount = Number(dailyBars?.ticker_count ?? 0);
  const rawCoveragePercent = Number(dailyBars?.coverage_percent ?? (marketTickerCount > 0 ? (barsTickerCount / marketTickerCount) * 100 : 0));
  const coveragePercent = Number.isFinite(rawCoveragePercent) ? rawCoveragePercent : 0;
  const coverageMinimum = marketTickerCount > 0 ? Math.min(marketTickerCount, 50) : 0;
  const coverageMeetsMinimum = marketTickerCount > 0 && barsTickerCount >= coverageMinimum;
  const coverageBroad = marketTickerCount > 0 && (barsTickerCount >= marketTickerCount || coveragePercent >= 25);
  const coverageText = marketTickerCount > 0
    ? `OHLCV ${barsTickerCount}/${marketTickerCount}銘柄（${formatCompactPercent(coveragePercent)}）`
    : "市場財務の銘柄数を確認中です。";
  const barsStale = String(dailyBars?.status ?? "") === "stale";
  const coverageHint = barsStale
    ? `価格系列が古くなっています（${formatDatasetAge(dailyBars)}）。OHLCV更新を優先してください。`
    : coverageBroad
      ? "広い範囲で価格系列を確認できます。"
      : coverageMeetsMinimum
        ? `最低基準（${coverageMinimum}銘柄）は達成していますが、全体カバーは低めです。必要ならOHLCV更新を追加してください。`
        : "予測は一部銘柄だけになります。必要ならYahoo!一括更新でOHLCVを増やしてください。";
  const coreText = props.coreDatasets.length > 0
    ? props.coreDatasets.map((item) => `${String(item.label ?? item.id)} ${formatRows(item)}`).join(" / ")
    : "主要データはまだ確認していません。";
  const attentionText = props.attentionDatasets.length > 0
    ? props.attentionDatasets.slice(0, 3).map(formatAttentionDataset).join(" / ")
    : "主要データは利用できます。";
  const requiredActions = props.actions.filter((action) => !Boolean(action.optional));
  const optionalActions = props.actions.filter((action) => Boolean(action.optional));
  const actionText = requiredActions.length > 0
    ? `今すぐ必要: ${requiredActions.slice(0, 2).map(refreshActionSummary).join(" / ")}`
    : optionalActions.length > 0
      ? `今すぐ必要はありません。任意: ${optionalActions.slice(0, 2).map(refreshActionSummary).join(" / ")}`
      : "追加の実行アクションはありません。";
  return (
    <div className="inventory-guide" aria-label="データ状態の読み方">
      <div>
        <b>中心データ</b>
        <span>{coreText}</span>
      </div>
      <div className={coverageBroad ? "ready" : "attention"}>
        <b>OHLCVカバー率</b>
        <span>{coverageText}。{coverageHint}</span>
      </div>
      <div className={props.attentionDatasets.length > 0 ? "attention" : "ready"}>
        <b>{props.attentionDatasets.length > 0 ? "確認点" : "状態"}</b>
        <span>{attentionText}</span>
      </div>
      <div className={requiredActions.length > 0 ? "attention" : "ready"}>
        <b>{requiredActions.length > 0 ? "次の作業" : "任意補完"}</b>
        <span>{actionText}</span>
      </div>
    </div>
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

function actionScopeLabel(value: unknown): string {
  const scope = String(value ?? "");
  const labels: Record<string, string> = {
    tickers: "入力した銘柄",
    nikkei225: "日経225",
    financials_csv: "財務CSV",
    domestic: "全国内株式",
  };
  return labels[scope] ?? scope;
}

function formatRecommendedCount(value: unknown): string | null {
  const raw = String(value ?? "").trim();
  if (!raw) {
    return null;
  }
  return raw === "0" ? "全件" : `${raw}件`;
}

function refreshActionMeta(action: Json): string[] {
  const meta: string[] = [];
  if (action.recommended_scope) {
    meta.push(`対象: ${actionScopeLabel(action.recommended_scope)}`);
  }
  const count = formatRecommendedCount(action.recommended_max_count);
  if (count) {
    meta.push(`上限: ${count}`);
  }
  const range = String(action.recommended_range ?? "").trim();
  if (range) {
    meta.push(`期間: ${range}`);
  }
  return meta;
}

function refreshActionSummary(action: Json): string {
  const label = String(action.label ?? action.id ?? "更新");
  const meta = refreshActionMeta(action).join(" / ");
  return meta ? `${label}（${meta}）` : label;
}

function RefreshActions(props: { actions: Json[]; onRun: (action: Json) => void; running: boolean }) {
  if (props.actions.length === 0) {
    return <p className="status">追加で必要な更新はありません。</p>;
  }
  const requiredActions = props.actions.filter((action) => !Boolean(action.optional));
  const optionalActions = props.actions.filter((action) => Boolean(action.optional));
  const renderAction = (action: Json) => {
    const safe = Boolean(action.safe_to_run);
    const optional = Boolean(action.optional);
    const meta = refreshActionMeta(action);
    return (
      <article className={optional ? "refresh-action optional" : "refresh-action"} key={String(action.id)}>
        <div className="refresh-action-content">
          <div className="refresh-action-title-row">
            <b>{String(action.label ?? action.id)}</b>
            <span className={optional ? "optional-chip" : "recommended-chip"}>{optional ? "任意" : "推奨"}</span>
          </div>
          <span>{String(action.reason ?? "")}</span>
          {meta.length > 0 && (
            <div className="refresh-action-meta">
              {meta.map((item) => (
                <span className="action-meta-chip" key={item}>{item}</span>
              ))}
            </div>
          )}
        </div>
        {safe ? (
          <button className={optional ? "secondary-action" : undefined} disabled={props.running} onClick={() => props.onRun(action)}>
            実行
          </button>
        ) : (
          <span className="manual-chip">手動確認</span>
        )}
      </article>
    );
  };
  return (
    <div className="refresh-actions">
      <div>
        <h4>次の更新・任意の補完</h4>
        <p>{requiredActions.length > 0 ? "不足データを優先して表示します。" : "必須の不足はありません。必要な範囲だけ追加取得できます。"}</p>
      </div>
      {requiredActions.length > 0 && (
        <section className="refresh-action-section">
          <div className="refresh-action-section-head">
            <h5>優先して実行</h5>
            <span>{requiredActions.length}件</span>
          </div>
          <div className="refresh-action-list">{requiredActions.map(renderAction)}</div>
        </section>
      )}
      {optionalActions.length > 0 && (
        <section className="refresh-action-section optional">
          <div className="refresh-action-section-head">
            <h5>必要なら補完</h5>
            <span>{optionalActions.length}件</span>
          </div>
          <div className="refresh-action-list">{optionalActions.map(renderAction)}</div>
        </section>
      )}
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
      {screen.data && results.length === 0 && (
        <p className="hint">
          条件に合う銘柄がありません。OHLCV取得数を増やすか、妥当性上限(±%)を緩めてください。
        </p>
      )}
      {screen.data && results.length > 0 && (
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

const DONUT_COLORS = ["#534AB7","#0F6E56","#993C1D","#185FA5","#854F0B","#993556","#3B6D11","#636363"];

function DonutChart({ allocations, summary }: { allocations: Json[]; summary?: Json }) {
  const [sel, setSel] = useState<number | null>(null);
  const R = 155, CX = 190, CY = 190, SW = 46;
  const C = 2 * Math.PI * R;
  const total = allocations.reduce((s, a) => s + Number(a.invested), 0);
  let cum = 0;
  const segs = allocations.map((a, i) => {
    const len = (Number(a.invested) / total) * C;
    const off = cum;
    cum += len;
    return { a, len, off, color: DONUT_COLORS[i % DONUT_COLORS.length] };
  });
  const selSeg = sel !== null ? segs[sel] : null;

  return (
    <div style={{ marginTop: "16px" }}>
      {/* Summary cards */}
      <div style={{ display:"flex", gap:"10px", marginBottom:"16px", flexWrap:"wrap" }}>
        {[
          { label:"投資総額", value:`${(total/10000).toFixed(0)}万円` },
          { label:"年間配当", value: summary?.annual_dividend ? `${(Number(summary.annual_dividend)/10000).toFixed(1)}万円` : "-" },
          { label:"利回り",   value: summary?.portfolio_yield ? `${(Number(summary.portfolio_yield)*100).toFixed(2)}%` : "-" },
        ].map(c => (
          <div key={c.label} style={{ background:"var(--color-background-secondary)", borderRadius:"8px", padding:"10px 16px", flex:1, minWidth:"100px" }}>
            <p style={{ fontSize:"12px", color:"var(--color-text-secondary)", margin:"0 0 3px" }}>{c.label}</p>
            <p style={{ fontSize:"20px", fontWeight:"500", margin:0 }}>{c.value}</p>
          </div>
        ))}
      </div>

      {/* SVG donut — full-width responsive */}
      <svg viewBox="0 0 380 380"
        style={{ width:"100%", maxWidth:"520px", display:"block", margin:"0 auto", overflow:"visible" }}>
        {segs.map(({ len, off, color }, i) => (
          <circle key={i} r={R} cx={CX} cy={CY} fill="none" stroke={color}
            strokeWidth={sel === i ? SW + 10 : SW}
            strokeDasharray={`${len} ${C - len}`}
            strokeDashoffset={C - off}
            transform={`rotate(-90 ${CX} ${CY})`}
            style={{ cursor:"pointer", transition:"stroke-width 0.2s, opacity 0.2s",
                     opacity: sel !== null && sel !== i ? 0.35 : 1 }}
            onClick={() => setSel(sel === i ? null : i)}
          />
        ))}
        {/* Center text */}
        {selSeg ? (
          <>
            <text x={CX} y={CY - 32} textAnchor="middle" fontSize="16" fill="var(--color-text-secondary)">{String(selSeg.a.name ?? "")}</text>
            <text x={CX} y={CY + 4}  textAnchor="middle" fontSize="30" fontWeight="500" fill="var(--color-text-primary)">{(Number(selSeg.a.invested)/10000).toFixed(0)}万円</text>
            <text x={CX} y={CY + 34} textAnchor="middle" fontSize="17" fill="var(--color-text-secondary)">{(Number(selSeg.a.invested)/total*100).toFixed(1)}%</text>
            <text x={CX} y={CY + 58} textAnchor="middle" fontSize="15" fill="var(--color-text-secondary)">利回り {(Number(selSeg.a.yield)*100).toFixed(2)}%</text>
          </>
        ) : (
          <>
            <text x={CX} y={CY - 22} textAnchor="middle" fontSize="16" fill="var(--color-text-secondary)">投資総額</text>
            <text x={CX} y={CY + 14} textAnchor="middle" fontSize="32" fontWeight="500" fill="var(--color-text-primary)">{(total/10000).toFixed(0)}万円</text>
            <text x={CX} y={CY + 46} textAnchor="middle" fontSize="16" fill="var(--color-text-secondary)">
              {summary?.portfolio_yield ? `利回り ${(Number(summary.portfolio_yield)*100).toFixed(2)}%` : ""}
            </text>
          </>
        )}
      </svg>

      {/* Allocation table — always visible */}
      <table className="data-table" style={{ marginTop: "14px", width: "100%" }}>
        <thead>
          <tr>
            <th></th>
            <th style={{ textAlign: "left" }}>銘柄</th>
            <th style={{ textAlign: "right" }}>株数</th>
            <th style={{ textAlign: "right" }}>単価</th>
            <th style={{ textAlign: "right" }}>投資額</th>
            <th style={{ textAlign: "right" }}>年間配当</th>
            <th style={{ textAlign: "right" }}>利回り</th>
            <th style={{ textAlign: "right" }}>比率</th>
          </tr>
        </thead>
        <tbody>
          {segs.map(({ a, color }, i) => {
            const pct = (Number(a.invested) / total * 100).toFixed(1);
            const isSel = sel === i;
            return (
              <tr key={i} onClick={() => setSel(sel === i ? null : i)}
                style={{ cursor: "pointer", background: isSel ? "var(--color-background-secondary)" : "transparent" }}>
                <td style={{ width: "10px", padding: "6px 4px" }}>
                  <span style={{ display: "inline-block", width: "10px", height: "10px", borderRadius: "2px", background: color }} />
                </td>
                <td>
                  <span style={{ fontWeight: isSel ? "700" : "500" }}>{String(a.name ?? "")}</span>
                  <span style={{ fontSize: "0.8em", color: "var(--color-text-secondary)", marginLeft: "4px" }}>{String(a.ticker ?? "")}</span>
                </td>
                <td style={{ textAlign: "right", fontWeight: "700", fontSize: "1.05em" }}>
                  {a.shares ? `${Number(a.shares).toLocaleString()}株` : "-"}
                </td>
                <td style={{ textAlign: "right", fontSize: "0.9em" }}>
                  {a.price ? `${Number(a.price).toLocaleString()}円` : "-"}
                </td>
                <td style={{ textAlign: "right" }}>
                  {(Number(a.invested) / 10000).toFixed(1)}万円
                </td>
                <td style={{ textAlign: "right", color: "var(--color-accent,#1a7a4a)" }}>
                  {Number(a.annual_dividend ?? 0).toLocaleString()}円
                </td>
                <td style={{ textAlign: "right", fontWeight: "600", color: "var(--color-accent,#1a7a4a)" }}>
                  {a.yield ? `${(Number(a.yield) * 100).toFixed(2)}%` : "-"}
                </td>
                <td style={{ textAlign: "right", color: "var(--color-text-secondary)" }}>{pct}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Plan Builder ──────────────────────────────────────────────────────────

type StockRow = { ticker: string; name: string; price: string; dps2026: string; dps2027: string };
type PlanDef = { id: string; label: string; stocks: StockRow[] };

const DEFAULT_PLAN_DEFS: PlanDef[] = [
  { id: "A", label: "プランA", stocks: [] },
  { id: "B", label: "プランB", stocks: [] },
  { id: "C", label: "プランC", stocks: [] },
  { id: "D", label: "プランD", stocks: [] },
];

function migratePlanDefs(raw: unknown[]): PlanDef[] {
  return raw.map((p: unknown) => {
    const plan = p as Record<string, unknown>;
    return {
      id: String(plan.id ?? ""),
      label: String(plan.label ?? ""),
      stocks: (Array.isArray(plan.stocks) ? plan.stocks : []).map((s: unknown) => {
        const row = s as Record<string, unknown>;
        return {
          ticker: String(row.ticker ?? ""),
          name: String(row.name ?? ""),
          price: String(row.price ?? ""),
          dps2026: String(row.dps2026 ?? row.dps ?? ""),
          dps2027: String(row.dps2027 ?? ""),
        };
      }),
    };
  });
}

function PlanBuilderPanel() {
  const [plans, setPlans] = useState<PlanDef[]>(() => {
    try {
      const saved = localStorage.getItem("ia.plan-builder.defs");
      if (saved) return migratePlanDefs(JSON.parse(saved) as unknown[]);
    } catch { /* ignore */ }
    return DEFAULT_PLAN_DEFS;
  });
  const [activePlan, setActivePlan] = useState("A");
  const [targetMode, setTargetMode] = useState<"target" | "budget">("target");
  const [targetValue, setTargetValue] = useState("1200000");
  const [fetchingDps, setFetchingDps] = useState(false);
  const [result, setResult] = useState<Json | null>(null);
  const [loading, setLoading] = useState(false);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [selectedResultPlan, setSelectedResultPlan] = useState<string>("");
  const [selectedResultYear, setSelectedResultYear] = useState<"2026" | "2027">("2026");
  const [showSaveInput, setShowSaveInput] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [savedSims, setSavedSims] = useState<Json[]>([]);
  const [showSaved, setShowSaved] = useState(false);

  // Persist plan defs
  useEffect(() => {
    try { localStorage.setItem("ia.plan-builder.defs", JSON.stringify(plans)); } catch { /* ignore */ }
  }, [plans]);

  const loadSavedSims = async () => {
    try {
      const res = await api<Json>("/api/simulations");
      if (Array.isArray(res.simulations)) setSavedSims(res.simulations as Json[]);
    } catch { /* ignore */ }
  };
  useEffect(() => { void loadSavedSims(); }, []);

  const currentPlan = plans.find((p) => p.id === activePlan) ?? plans[0];

  const updatePlanDef = (id: string, update: Partial<PlanDef>) =>
    setPlans((prev) => prev.map((p) => (p.id === id ? { ...p, ...update } : p)));

  const addPlan = () => {
    const usedIds = new Set(plans.map((p) => p.id));
    let newId = "";
    for (let i = 0; i < 26; i++) {
      const c = String.fromCharCode(65 + i);
      if (!usedIds.has(c)) { newId = c; break; }
    }
    if (!newId) return;
    setPlans((prev) => [...prev, { id: newId, label: `プラン${newId}`, stocks: [] }]);
    setActivePlan(newId);
  };

  const removePlan = (id: string) => {
    if (plans.length <= 1) return;
    setPlans((prev) => prev.filter((p) => p.id !== id));
    if (activePlan === id) setActivePlan(plans.find((p) => p.id !== id)?.id ?? "");
  };

  const addStock = () => {
    updatePlanDef(activePlan, {
      stocks: [...(currentPlan?.stocks ?? []), { ticker: "", name: "", price: "", dps2026: "", dps2027: "" }],
    });
  };

  const updateStock = (idx: number, field: keyof StockRow, value: string) => {
    const stocks = [...(currentPlan?.stocks ?? [])];
    stocks[idx] = { ...stocks[idx], [field]: value };
    updatePlanDef(activePlan, { stocks });
  };

  const removeStock = (idx: number) => {
    const stocks = (currentPlan?.stocks ?? []).filter((_, i) => i !== idx);
    updatePlanDef(activePlan, { stocks });
  };

  const copyStocksFrom = (fromId: string) => {
    const src = plans.find((p) => p.id === fromId);
    if (!src) return;
    updatePlanDef(activePlan, { stocks: src.stocks.map((s) => ({ ...s })) });
  };

  const fetchDps = async () => {
    const tickers = (currentPlan?.stocks ?? []).map((s) => s.ticker).filter(Boolean);
    if (!tickers.length) return;
    setFetchingDps(true);
    try {
      const res = await api<Json>("/api/yahoo/dps", { tickers });
      if (res.dps && typeof res.dps === "object") {
        const dpsMap = res.dps as Record<string, number>;
        const stocks = (currentPlan?.stocks ?? []).map((s) => ({
          ...s,
          dps2026: s.ticker && dpsMap[s.ticker] != null ? String(dpsMap[s.ticker]) : s.dps2026,
        }));
        updatePlanDef(activePlan, { stocks });
      }
    } catch { /* ignore */ } finally {
      setFetchingDps(false);
    }
  };

  const computePlans = async () => {
    setLoading(true);
    setComputeError(null);
    try {
      const makePayload = (dpsField: "dps2026" | "dps2027"): Json => {
        const base: Json = {
          plans: plans.map((p) => ({
            id: p.id,
            label: p.label,
            stocks: p.stocks
              .filter((s) => s.ticker.trim())
              .map((s) => ({
                ticker: s.ticker.trim(),
                name: s.name.trim() || s.ticker.trim(),
                price: parseFloat(s.price) || 0,
                dps: parseFloat(s[dpsField]) || 0,
              })),
          })),
        };
        if (targetMode === "target") {
          base.target_annual_dividend = parseFloat(targetValue) || 1200000;
        } else {
          base.budget = parseFloat(targetValue) || 30000000;
        }
        return base;
      };

      const [res2026, res2027] = await Promise.all([
        api<Json>("/api/simulations/compute-plans", makePayload("dps2026")),
        api<Json>("/api/simulations/compute-plans", makePayload("dps2027")),
      ]);

      // Build DPS comparison from current plan stock definitions
      const stockMap = new Map<string, { name: string; dps2026: string; dps2027: string }>();
      plans.forEach((p) =>
        p.stocks.forEach((s) => {
          if (s.ticker.trim()) {
            stockMap.set(s.ticker.trim(), {
              name: s.name.trim() || s.ticker.trim(),
              dps2026: s.dps2026,
              dps2027: s.dps2027,
            });
          }
        })
      );
      const dps_comparison = Array.from(stockMap.entries()).map(([ticker, v]) => ({
        ticker,
        name: v.name,
        dps_2026: parseFloat(v.dps2026) || 0,
        dps_2027: parseFloat(v.dps2027) || 0,
        diff: (parseFloat(v.dps2027) || 0) - (parseFloat(v.dps2026) || 0),
      }));

      const combined: Json = {
        plans_2026: res2026.plans,
        plan_comparison_2026: res2026.plan_comparison,
        plans_2027: res2027.plans,
        plan_comparison_2027: res2027.plan_comparison,
        dps_comparison,
        // For SavedSimsPanel compat:
        plan_comparison: res2026.plan_comparison,
        plans: res2026.plans,
        available: true,
      };
      setResult(combined);
      setSelectedResultYear("2026");
      const firstPlan = Array.isArray(res2026.plan_comparison) && res2026.plan_comparison.length > 0
        ? String((res2026.plan_comparison as Json[])[0].plan ?? "")
        : "";
      setSelectedResultPlan(firstPlan);
    } catch (e) {
      setComputeError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const saveResult = async () => {
    if (!result) return;
    const name = saveName.trim() || `Plans-${new Date().toISOString().slice(0, 16).replace("T", "_")}`;
    try {
      const res = await api<Json>("/api/simulations/save", {
        name,
        query: `プラン設計 ${targetMode === "target" ? "目標配当" : "予算"}${Number(targetValue).toLocaleString()}円`,
        result: { ...result, plan_defs: plans, target_value: targetValue, target_mode: targetMode },
      });
      setSaveNotice(`✅ 保存しました（合計 ${String(res.total ?? "")} 件）`);
      setSaveName("");
      setShowSaveInput(false);
      void loadSavedSims();
    } catch (e) {
      setSaveNotice(`❌ ${e instanceof Error ? e.message : String(e)}`);
    }
    setTimeout(() => setSaveNotice(null), 4000);
  };

  const deleteSim = async (simId: string) => {
    try {
      await api<Json>("/api/simulations/delete", { id: simId });
      void loadSavedSims();
    } catch { /* ignore */ }
  };

  const planComparison2026 = Array.isArray(result?.plan_comparison_2026) ? (result!.plan_comparison_2026 as Json[]) : [];
  const planComparison2027 = Array.isArray(result?.plan_comparison_2027) ? (result!.plan_comparison_2027 as Json[]) : [];
  const dpsComparison = Array.isArray(result?.dps_comparison) ? (result!.dps_comparison as Json[]) : [];
  const resultPlans2026 = result?.plans_2026 as Record<string, Json> | undefined;
  const resultPlans2027 = result?.plans_2027 as Record<string, Json> | undefined;
  const activeResultPlans = selectedResultYear === "2026" ? resultPlans2026 : resultPlans2027;
  const selPlanData = activeResultPlans && selectedResultPlan ? activeResultPlans[selectedResultPlan] as Json | undefined : undefined;
  const selAllocs = Array.isArray(selPlanData?.allocations) ? selPlanData!.allocations as Json[] : [];
  const selSummary = selPlanData?.summary as Json | undefined;

  return (
    <section className="screen">
      <ScreenTitle title="プラン設計" body="銘柄を自由に組み合わせてプランA-Dを定義し、配当シミュレーションを一括実行・保存します。" />

      {/* Shared params */}
      <div className="form-grid tight" style={{ marginBottom: "16px" }}>
        <Field label="計算モード">
          <select value={targetMode} onChange={(e) => setTargetMode(e.target.value as "target" | "budget")}
            style={{ padding: "4px 8px", borderRadius: "4px" }}>
            <option value="target">目標配当額（逆算）</option>
            <option value="budget">予算（順算）</option>
          </select>
        </Field>
        <Field label={targetMode === "target" ? "目標年間配当（円）" : "投資予算（円）"}>
          <input value={targetValue} onChange={(e) => setTargetValue(e.target.value)} inputMode="numeric"
            placeholder={targetMode === "target" ? "1200000" : "30000000"} />
        </Field>
      </div>

      {/* Plan tabs */}
      <div style={{ display: "flex", gap: "4px", marginBottom: "0", borderBottom: "1px solid var(--color-border,#e0e0e0)", flexWrap: "wrap" }}>
        {plans.map((p) => (
          <button key={p.id}
            onClick={() => setActivePlan(p.id)}
            style={{
              padding: "6px 14px", border: "none", borderRadius: "6px 6px 0 0",
              background: activePlan === p.id ? "var(--color-background-secondary)" : "transparent",
              fontWeight: activePlan === p.id ? "600" : "400",
              borderBottom: activePlan === p.id ? "2px solid var(--color-accent,#1a7a4a)" : "2px solid transparent",
              cursor: "pointer",
            }}>
            {p.label}
          </button>
        ))}
        <button onClick={addPlan}
          style={{ padding: "6px 10px", border: "none", background: "transparent", cursor: "pointer", opacity: 0.6 }}>
          ＋プラン追加
        </button>
      </div>

      {/* Active plan editor */}
      {currentPlan && (
        <div style={{ border: "1px solid var(--color-border,#e0e0e0)", borderTop: "none", padding: "14px 16px", marginBottom: "16px" }}>
          {/* Plan header */}
          <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "10px", flexWrap: "wrap" }}>
            <input
              value={currentPlan.label}
              onChange={(e) => updatePlanDef(activePlan, { label: e.target.value })}
              style={{ fontWeight: "600", fontSize: "0.95em", padding: "3px 8px", border: "1px solid var(--color-border,#ccc)", borderRadius: "4px", width: "140px" }}
              placeholder="プラン名"
            />
            {plans.filter((p) => p.id !== activePlan).map((p) => (
              <button key={p.id} className="table-action" onClick={() => copyStocksFrom(p.id)}>
                {p.label}からコピー
              </button>
            ))}
            <span style={{ flex: 1 }} />
            {plans.length > 1 && (
              <button className="table-action" style={{ color: "var(--color-danger,#c00)" }} onClick={() => removePlan(activePlan)}>
                このプランを削除
              </button>
            )}
          </div>

          {/* Stock table */}
          {currentPlan.stocks.length > 0 && (
            <table className="data-table" style={{ marginBottom: "8px" }}>
              <thead>
                <tr>
                  <th>ティッカー</th>
                  <th>銘柄名</th>
                  <th>株価（円）</th>
                  <th style={{ color: "var(--color-accent,#1a7a4a)" }}>DPS 2026</th>
                  <th style={{ color: "#2563eb" }}>DPS 2027</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {currentPlan.stocks.map((s, idx) => (
                  <tr key={idx}>
                    <td><input value={s.ticker} onChange={(e) => updateStock(idx, "ticker", e.target.value)}
                      placeholder="8316" style={{ width: "70px", padding: "2px 6px", fontSize: "0.9em" }} /></td>
                    <td><input value={s.name} onChange={(e) => updateStock(idx, "name", e.target.value)}
                      placeholder="銘柄名" style={{ width: "120px", padding: "2px 6px", fontSize: "0.9em" }} /></td>
                    <td><input value={s.price} onChange={(e) => updateStock(idx, "price", e.target.value)}
                      placeholder="3233" inputMode="decimal" style={{ width: "80px", padding: "2px 6px", fontSize: "0.9em" }} /></td>
                    <td><input value={s.dps2026} onChange={(e) => updateStock(idx, "dps2026", e.target.value)}
                      placeholder="60" inputMode="decimal" style={{ width: "66px", padding: "2px 6px", fontSize: "0.9em", borderColor: "var(--color-accent,#1a7a4a)" }} /></td>
                    <td><input value={s.dps2027} onChange={(e) => updateStock(idx, "dps2027", e.target.value)}
                      placeholder="65" inputMode="decimal" style={{ width: "66px", padding: "2px 6px", fontSize: "0.9em", borderColor: "#2563eb" }} /></td>
                    <td><button className="table-action" style={{ color: "var(--color-danger,#c00)" }} onClick={() => removeStock(idx)}>削除</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {currentPlan.stocks.length === 0 && (
            <p className="hint" style={{ marginBottom: "8px" }}>銘柄を追加してください。ティッカー・株価・2026/2027年DPSを入力するか、Yahoo取得でDPS 2026を自動入力できます。</p>
          )}
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button className="table-action" onClick={addStock}>＋銘柄追加</button>
            <button className="table-action" onClick={() => void fetchDps()} disabled={fetchingDps}>
              {fetchingDps ? "取得中…" : "📡 Yahoo DPS取得"}
            </button>
          </div>
        </div>
      )}

      {/* Run */}
      <ActionRow>
        <button className="primary" onClick={() => void computePlans()} disabled={loading}>
          {loading ? "計算中…" : "▶ 全プラン計算"}
        </button>
      </ActionRow>
      {computeError && <p className="notice error">{computeError}</p>}

      {/* Results */}
      {result && (
        <div style={{ marginTop: "20px" }}>

          {/* DPS比較表 */}
          {dpsComparison.length > 0 && (
            <div style={{ marginBottom: "20px" }}>
              <h4 style={{ marginBottom: "8px" }}>DPS比較（2026 vs 2027）</h4>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>銘柄</th>
                    <th style={{ color: "var(--color-accent,#1a7a4a)" }}>2026年DPS</th>
                    <th style={{ color: "#2563eb" }}>2027年DPS</th>
                    <th>増減</th>
                    <th>増減率</th>
                  </tr>
                </thead>
                <tbody>
                  {dpsComparison.map((d, i) => {
                    const rawDiff = Number(d.diff ?? 0);
                    const diff = Math.round(rawDiff * 100) / 100; // 浮動小数点丸め
                    const d26 = Number(d.dps_2026 ?? 0);
                    const d27 = Number(d.dps_2027 ?? 0);
                    const pct = d26 > 0 ? (diff / d26 * 100).toFixed(1) : "-";
                    const color = diff > 0 ? "var(--color-accent,#1a7a4a)" : diff < 0 ? "#c00" : "inherit";
                    const fmtDps = (v: number) => v % 1 === 0 ? `${v}円` : `${v}円`;
                    return (
                      <tr key={i}>
                        <td style={{ minWidth: "120px" }}>
                          <div style={{ fontWeight: "700", fontSize: "1.08em", lineHeight: 1.2 }}>{String(d.name ?? "")}</div>
                          <div style={{ fontSize: "0.76em", color: "var(--color-text-secondary,#888)", marginTop: "2px" }}>{String(d.ticker ?? "")}</div>
                        </td>
                        <td style={{ fontSize: "1.05em", fontWeight: "600" }}>{d26 > 0 ? fmtDps(d26) : "-"}</td>
                        <td style={{ fontSize: "1.05em", fontWeight: "600", color: "#2563eb" }}>{d27 > 0 ? fmtDps(d27) : "-"}</td>
                        <td style={{ color, fontWeight: diff !== 0 ? "700" : "400", fontSize: "1.0em" }}>
                          {diff !== 0 ? `${diff > 0 ? "+" : ""}${diff}円` : "±0"}
                        </td>
                        <td style={{ color }}>{diff !== 0 && d26 > 0 ? `${diff > 0 ? "+" : ""}${pct}%` : "-"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* プランA-D 年度別比較 */}
          {(planComparison2026.length > 0 || planComparison2027.length > 0) && (
            <div style={{ marginBottom: "16px" }}>
              <h4 style={{ marginBottom: "8px" }}>プランA-D 年度別比較</h4>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>プラン</th>
                    <th style={{ color: "var(--color-accent,#1a7a4a)" }}>2026 投資額</th>
                    <th style={{ color: "var(--color-accent,#1a7a4a)" }}>2026 年間配当</th>
                    <th style={{ color: "var(--color-accent,#1a7a4a)" }}>2026 利回り</th>
                    <th style={{ color: "#2563eb" }}>2027 年間配当</th>
                    <th style={{ color: "#2563eb" }}>2027 利回り</th>
                    <th>配当増減</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {planComparison2026.map((p26, i) => {
                    const pid = String(p26.plan ?? "");
                    const p27 = planComparison2027.find((x) => String(x.plan ?? "") === pid);
                    const isAvail26 = (resultPlans2026?.[pid] as Json | undefined)?.available !== false;
                    const isAvail27 = (resultPlans2027?.[pid] as Json | undefined)?.available !== false;
                    const div26 = Number(p26.annual_dividend ?? 0);
                    const div27 = p27 ? Number(p27.annual_dividend ?? 0) : 0;
                    const divDiff = div27 - div26;
                    const isSel = selectedResultPlan === pid;
                    return (
                      <tr key={i} style={{ background: isSel ? "var(--color-background-secondary)" : "transparent" }}>
                        <td><b>{pid}</b> <span style={{ fontSize: "0.82em" }}>{String(p26.label ?? "")}</span></td>
                        <td>{isAvail26 ? `${Number(p26.invested).toLocaleString()}円` : "-"}</td>
                        <td>{isAvail26 ? `${div26.toLocaleString()}円` : "-"}</td>
                        <td style={{ color: "var(--color-accent,#1a7a4a)", fontWeight: "bold" }}>
                          {isAvail26 ? `${(Number(p26.yield) * 100).toFixed(2)}%` : "-"}
                        </td>
                        <td>{isAvail27 && p27 ? `${div27.toLocaleString()}円` : "-"}</td>
                        <td style={{ color: "#2563eb", fontWeight: "bold" }}>
                          {isAvail27 && p27 ? `${(Number(p27.yield) * 100).toFixed(2)}%` : "-"}
                        </td>
                        <td style={{ color: divDiff > 0 ? "var(--color-accent,#1a7a4a)" : divDiff < 0 ? "#c00" : "inherit", fontWeight: "600" }}>
                          {div26 > 0 || div27 > 0 ? `${divDiff >= 0 ? "+" : ""}${divDiff.toLocaleString()}円` : "-"}
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                            {isAvail26 && (
                              <button className="table-action"
                                style={{ borderColor: isSel && selectedResultYear === "2026" ? "var(--color-accent,#1a7a4a)" : undefined, fontSize: "0.8em" }}
                                onClick={() => { setSelectedResultPlan(pid); setSelectedResultYear("2026"); }}>
                                2026詳細
                              </button>
                            )}
                            {isAvail27 && (
                              <button className="table-action"
                                style={{ borderColor: isSel && selectedResultYear === "2027" ? "#2563eb" : undefined, fontSize: "0.8em" }}
                                onClick={() => { setSelectedResultPlan(pid); setSelectedResultYear("2027"); }}>
                                2027詳細
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Selected plan donut */}
          {selAllocs.length > 0 && (
            <div style={{ marginBottom: "16px" }}>
              <h4 style={{ marginBottom: "8px" }}>
                プラン{selectedResultPlan}（{selectedResultYear}年） 詳細
              </h4>
              <DonutChart allocations={selAllocs} summary={selSummary} />
            </div>
          )}

          {/* Save */}
          <div style={{ marginTop: "16px", display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
            {!showSaveInput ? (
              <button className="table-action" onClick={() => {
                setSaveName(`Plans-${new Date().toISOString().slice(0,16).replace("T","_")}`);
                setShowSaveInput(true);
              }}>
                💾 結果を保存
              </button>
            ) : (
              <>
                <input value={saveName} onChange={(e) => setSaveName(e.target.value)}
                  placeholder="保存名" style={{ padding: "4px 10px", border: "1px solid var(--color-border,#ccc)", borderRadius: "4px", minWidth: "220px" }}
                  onKeyDown={(e) => { if (e.key === "Enter") void saveResult(); if (e.key === "Escape") setShowSaveInput(false); }} />
                <button className="primary" onClick={() => void saveResult()}>保存</button>
                <button onClick={() => setShowSaveInput(false)}>キャンセル</button>
              </>
            )}
          </div>
          {saveNotice && <p className="notice safe" style={{ marginTop: "8px" }}>{saveNotice}</p>}
        </div>
      )}

      {/* Saved sims panel */}
      <SavedSimsPanel
        savedSims={savedSims}
        showSaved={showSaved}
        onToggle={() => { setShowSaved((v) => !v); void loadSavedSims(); }}
        onReload={() => {}}
        onDelete={(id) => void deleteSim(id)}
      />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function SavedSimCard({ sim, onReload, onDelete }: { sim: Json; onReload: (s: Json) => void; onDelete: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [selPlan, setSelPlan] = useState("A");
  const [selYear, setSelYear] = useState<"2026" | "2027">("2026");

  const simId = String(sim.id ?? "");
  const r = sim.result as Json | undefined;
  const savedAt = String(sim.saved_at ?? "").slice(0, 16).replace("T", " ");

  // Detect format: new = has plan_comparison_2026
  const isNew = Array.isArray(r?.plan_comparison_2026);
  const pc26 = isNew ? (r!.plan_comparison_2026 as Json[]) : [];
  const pc27 = isNew ? (r!.plan_comparison_2027 as Json[]) : [];
  const plans26 = ((isNew ? r?.plans_2026 : r?.plans) ?? {}) as Record<string, Json>;
  const plans27 = (r?.plans_2027 ?? plans26) as Record<string, Json>;
  const dpsComp = Array.isArray(r?.dps_comparison) ? (r!.dps_comparison as Json[]) : [];

  // Legacy single-plan saves
  const legacyAllocs = Array.isArray(r?.allocations) ? (r!.allocations as Json[]) : [];
  const legacySummary = r?.summary as Json | undefined;
  const legacyInvested = legacySummary?.invested ? `${Number(legacySummary.invested).toLocaleString()}円` : null;
  const legacyYld = legacySummary?.portfolio_yield ? `${(Number(legacySummary.portfolio_yield) * 100).toFixed(2)}%` : null;

  const activeDonutPlans = selYear === "2026" ? plans26 : plans27;
  const selPlanData = activeDonutPlans[selPlan] as Json | undefined;
  const selAllocs = Array.isArray(selPlanData?.allocations) ? (selPlanData!.allocations as Json[]) : [];
  const selSummary = selPlanData?.summary as Json | undefined;

  return (
    <div style={{ border: "1px solid var(--color-border, #e0e0e0)", borderRadius: "6px", marginBottom: "8px", overflow: "hidden" }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "10px 14px", background: "var(--color-surface, #f8f8f8)", flexWrap: "wrap" }}>
        <b style={{ minWidth: "140px", fontSize: "0.95em" }}>{String(sim.name ?? "")}</b>
        <span style={{ color: "var(--color-muted, #888)", fontSize: "0.82em" }}>{savedAt}</span>
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "0.82em" }}>{String(sim.query ?? "")}</span>
        {legacyInvested && <span><b>{legacyInvested}</b></span>}
        {legacyYld && <span style={{ color: "var(--color-accent, #1a7a4a)", fontWeight: "bold" }}>{legacyYld}</span>}
        <button className="table-action" onClick={() => setExpanded(v => !v)}>{expanded ? "閉じる" : "内訳"}</button>
        <button className="table-action" onClick={() => onReload(sim)}>再クエリ</button>
        <button className="table-action" onClick={() => onDelete(simId)} style={{ color: "var(--color-danger, #c00)" }}>削除</button>
      </div>

      {expanded && (
        <div style={{ padding: "14px 16px" }}>
          {/* DPS comparison */}
          {dpsComp.length > 0 && (
            <div style={{ marginBottom: "16px" }}>
              <h4 style={{ marginBottom: "8px" }}>DPS比較（2026 vs 2027）</h4>
              <table className="data-table">
                <thead><tr><th>銘柄</th><th>2026年DPS</th><th>2027年DPS</th><th>増減</th><th>増減率</th></tr></thead>
                <tbody>
                  {dpsComp.map((d, i) => {
                    const rawDiff = Number(d.diff ?? 0);
                    const diff = Math.round(rawDiff * 100) / 100;
                    const d26 = Number(d.dps_2026 ?? 0);
                    const d27 = Number(d.dps_2027 ?? 0);
                    const pct = d26 > 0 ? (diff / d26 * 100).toFixed(1) : "-";
                    const color = diff > 0 ? "var(--color-accent,#1a7a4a)" : diff < 0 ? "#c00" : "inherit";
                    return (
                      <tr key={i}>
                        <td style={{ minWidth: "120px" }}>
                          <div style={{ fontWeight: "700", fontSize: "1.08em", lineHeight: 1.2 }}>{String(d.name ?? "")}</div>
                          <div style={{ fontSize: "0.76em", color: "var(--color-text-secondary,#888)", marginTop: "2px" }}>{String(d.ticker ?? "")}</div>
                        </td>
                        <td style={{ fontSize: "1.05em", fontWeight: "600" }}>{d26 > 0 ? `${d26}円` : "-"}</td>
                        <td style={{ fontSize: "1.05em", fontWeight: "600", color: "#2563eb" }}>{d27 > 0 ? `${d27}円` : "-"}</td>
                        <td style={{ color, fontWeight: diff !== 0 ? "700" : "400", fontSize: "1.0em" }}>
                          {diff !== 0 ? `${diff > 0 ? "+" : ""}${diff}円` : "±0"}
                        </td>
                        <td style={{ color }}>{diff !== 0 && d26 > 0 ? `${diff > 0 ? "+" : ""}${pct}%` : "-"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* New-format: 年度別比較 */}
          {isNew && pc26.length > 0 && (
            <div style={{ marginBottom: "16px" }}>
              <h4 style={{ marginBottom: "8px" }}>プランA-D 年度別比較</h4>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>プラン</th>
                    <th style={{ color: "var(--color-accent,#1a7a4a)" }}>2026 投資額</th>
                    <th style={{ color: "var(--color-accent,#1a7a4a)" }}>2026 利回り</th>
                    <th style={{ color: "#2563eb" }}>2027 年間配当</th>
                    <th style={{ color: "#2563eb" }}>2027 利回り</th>
                    <th>配当増減</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {pc26.map((p26, i) => {
                    const pid = String(p26.plan ?? "");
                    const p27 = pc27.find(x => String(x.plan ?? "") === pid);
                    const div26 = Number(p26.annual_dividend ?? 0);
                    const div27 = p27 ? Number(p27.annual_dividend ?? 0) : 0;
                    const divDiff = div27 - div26;
                    const isSel = selPlan === pid;
                    return (
                      <tr key={i} style={{ background: isSel ? "var(--color-background-secondary)" : "transparent" }}>
                        <td><b>{pid}</b></td>
                        <td>{Number(p26.invested).toLocaleString()}円</td>
                        <td style={{ color: "var(--color-accent,#1a7a4a)", fontWeight: "bold" }}>{(Number(p26.yield) * 100).toFixed(2)}%</td>
                        <td>{p27 ? `${div27.toLocaleString()}円` : "-"}</td>
                        <td style={{ color: "#2563eb", fontWeight: "bold" }}>{p27 ? `${(Number(p27.yield) * 100).toFixed(2)}%` : "-"}</td>
                        <td style={{ color: divDiff > 0 ? "var(--color-accent,#1a7a4a)" : divDiff < 0 ? "#c00" : "inherit", fontWeight: "600" }}>
                          {div26 > 0 ? `${divDiff >= 0 ? "+" : ""}${divDiff.toLocaleString()}円` : "-"}
                        </td>
                        <td style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                          <button className="table-action" style={{ fontSize: "0.8em", borderColor: isSel && selYear === "2026" ? "var(--color-accent,#1a7a4a)" : undefined }}
                            onClick={() => { setSelPlan(pid); setSelYear("2026"); }}>2026</button>
                          {p27 && <button className="table-action" style={{ fontSize: "0.8em", borderColor: isSel && selYear === "2027" ? "#2563eb" : undefined }}
                            onClick={() => { setSelPlan(pid); setSelYear("2027"); }}>2027</button>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* DonutChart */}
          {isNew && selAllocs.length > 0 && (
            <div style={{ marginBottom: "16px" }}>
              <h4 style={{ marginBottom: "8px" }}>プラン{selPlan}（{selYear}年）内訳</h4>
              <DonutChart allocations={selAllocs} summary={selSummary} />
            </div>
          )}

          {/* Legacy single-plan donut */}
          {!isNew && legacyAllocs.length > 0 && (
            <div style={{ marginBottom: "16px" }}>
              <h4 style={{ marginBottom: "8px" }}>銘柄内訳</h4>
              <DonutChart allocations={legacyAllocs} summary={legacySummary} />
            </div>
          )}

          {/* Fallback: answer text */}
          {legacyAllocs.length === 0 && !isNew && dpsComp.length === 0 && r?.answer && (
            <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.85em", fontFamily: "inherit" }}>{String(r.answer)}</pre>
          )}
        </div>
      )}
    </div>
  );
}

function SavedSimsPanel(props: {
  savedSims: Json[];
  showSaved: boolean;
  onToggle: () => void;
  onReload: (sim: Json) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="detail-section" style={{ marginTop: "24px" }}>
      <div className="answer-head">
        <h3>保存済みシミュレーション</h3>
        <button className="table-action" onClick={props.onToggle}>
          {props.showSaved ? "折りたたむ" : `一覧を見る（${props.savedSims.length}件）`}
        </button>
      </div>
      {props.showSaved && (
        props.savedSims.length === 0
          ? <p className="hint">まだ保存されたシミュレーションはありません。</p>
          : <div>
              {props.savedSims.map(sim => (
                <SavedSimCard key={String(sim.id ?? "")} sim={sim} onReload={props.onReload} onDelete={props.onDelete} />
              ))}
            </div>
      )}
    </div>
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
        <MarketResultDiagnostics data={data} mode={mode} rowCount={rows.length} />
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
        <MarketResultDiagnostics data={data} mode={mode} rowCount={rows.length} />
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
  const rowCount = Object.values(series).reduce((sum, rows) => sum + (Array.isArray(rows) ? rows.length : 0), 0);
  return (
    <ResultBlock title="価格系列" meta={`保存先: ${String(data.daily_bars_path ?? data.output_dir ?? "-")}`}>
      <MarketResultDiagnostics data={data} mode={mode} rowCount={rowCount} />
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

function MarketResultDiagnostics({ data, mode, rowCount }: { data: Json; mode: string; rowCount: number }) {
  const warnings = marketResultWarnings(data, mode, rowCount);
  const saved = data.saved === true || Number(data.daily_bars_count ?? 0) > 0 || Boolean(data.output_path || data.daily_bars_path);
  const tickerCount = Number(data.ticker_count ?? data.tickers_count ?? data.tickers ?? 0);
  const outputPath = String(data.output_path ?? data.daily_bars_path ?? data.output_dir ?? data.path ?? "-");
  const source = String(data.universe_source ?? data.provider ?? data.provider_id ?? "Yahoo!/local");
  return (
    <section className="market-result-diagnostics">
      <div className="inventory-summary">
        <InventoryPill label="取得行" value={`${rowCount}件`} tone={rowCount > 0 ? "ready" : "warn"} />
        <InventoryPill label="銘柄" value={tickerCount ? `${tickerCount}件` : "-"} tone="muted" />
        <InventoryPill label="保存" value={saved ? "あり" : "なし"} tone={saved ? "ready" : "warn"} />
        <InventoryPill label="取得元" value={source} tone="muted" />
      </div>
      <code className="path-chip">{outputPath}</code>
      {warnings.length > 0 ? (
        <ul className="warning-list market-warning-list">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : (
        <p className="notice safe">データ取得結果を確認できました。売買推奨ではなく、比較材料として表示しています。</p>
      )}
    </section>
  );
}

function marketResultWarnings(data: Json, mode: string, rowCount: number): string[] {
  const warnings: string[] = [];
  const rawWarnings = Array.isArray(data.warnings) ? data.warnings : [];
  for (const warning of rawWarnings) warnings.push(String(warning));
  if (data.error) warnings.push(String(data.error));
  if (rowCount > 0) return warnings;
  if (mode === "financials") {
    warnings.push("市場財務指標が0件です。銘柄コード、対象範囲、Yahoo!取得の制限、またはネットワーク状態を確認してください。");
    warnings.push("保存先CSVが更新されない場合は、対象を『入力した銘柄』にして少数銘柄から再実行してください。");
  } else if (mode === "inbox") {
    warnings.push("inboxに読み取れる価格ファイルがありません。CSVの保存場所と文字コードを確認してください。");
  } else {
    warnings.push("価格系列が0件です。対象銘柄、期間、Yahoo!取得制限、またはdaily_bars.csvの保存状態を確認してください。");
    warnings.push("大量取得ではレート制限が起きやすいため、まず上限件数を小さくして再実行してください。");
  }
  return Array.from(new Set(warnings));
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
  const summary = asJson(data.summary) ?? {};
  const largest = asJson(summary.largest_position);
  const pnlPositive = (Number(summary.unrealized_pnl) || 0) >= 0;
  const slices = rows
    .map((row) => ({
      label: String(row.name || row.ticker_or_fund_code || "?"),
      value: Number(row.market_value) || 0,
    }))
    .filter((s) => s.value > 0);
  return (
    <ResultBlock title="分析結果" meta={`評価額: ${yen(data.summary?.market_value)}`}>
      {Object.keys(summary).length > 0 && (
        <section className="detail-section">
          <h4>サマリー</h4>
          <div className="detail-metrics">
            <DetailFact label="評価額" value={yen(summary.market_value)} />
            <DetailFact label="取得額" value={yen(summary.cost_basis)} />
            <DetailFact
              label="評価損益"
              value={yen(summary.unrealized_pnl)}
              tone={pnlPositive ? "safe" : undefined}
            />
            <DetailFact label="損益率" value={percent(summary.unrealized_pnl_pct)} />
            <DetailFact label="年間配当見込み" value={yen(summary.annual_income_estimate)} />
            <DetailFact label="収入利回り" value={percent(summary.income_yield_pct)} />
            {largest && (
              <DetailFact
                label="最大保有"
                value={`${String(largest.name ?? largest.code ?? "-")}（${percent(largest.share_pct)}）`}
              />
            )}
          </div>
        </section>
      )}
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

function normalizeUpdateScope(value: unknown): "tickers" | "nikkei225" | "financials_csv" | "domestic" | null {
  if (value === "tickers" || value === "nikkei225" || value === "financials_csv" || value === "domestic") {
    return value;
  }
  return null;
}

function batchStepLabel(value: string): string {
  const labels: Record<string, string> = {
    pending: "待機",
    running: "処理中",
    done: "完了",
    error: "要確認",
    skip: "任意",
  };
  return labels[value] ?? value;
}
function formatCompactPercent(value: number): string {
  if (!Number.isFinite(value)) return "-";
  const digits = value > 0 && value < 10 ? 1 : 0;
  return `${value.toFixed(digits)}%`;
}
function statusLabel(value: string): string {
  const labels: Record<string, string> = {
    ready: "利用可",
    stale: "要更新",
    partial: "一部のみ",
    needs_attention: "要確認",
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
  if (value === "stale" || value === "partial" || value === "needs_attention") return "warn";
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
