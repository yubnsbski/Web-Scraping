import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";

type Json = Record<string, any>;

const TABS = [
  { id: "search", label: "RAG検索" },
  { id: "answer", label: "AI回答" },
  { id: "scoring", label: "スコアリング" },
  { id: "forecast", label: "予測" },
  { id: "scrape", label: "取得(スクレイピング)" },
  { id: "ops", label: "予算 / キャッシュ" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function App() {
  const [tab, setTab] = useState<TabId>("search");
  return (
    <div className="app">
      <header className="topbar">
        <h1>Investment Assistant</h1>
        <span className="badge safe">調査支援のみ・自動売買なし・売買推奨なし</span>
      </header>
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
        {tab === "search" && <SearchTab />}
        {tab === "answer" && <AnswerTab />}
        {tab === "scoring" && <ScoringTab />}
        {tab === "forecast" && <ForecastTab />}
        {tab === "scrape" && <ScrapeTab />}
        {tab === "ops" && <OpsTab />}
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
  async function run(fn: () => Promise<T>) {
    setLoading(true);
    setError(null);
    try {
      setData(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }
  return { loading, error, data, run, setData };
}

function Field(props: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      {props.children}
    </label>
  );
}

function Status(props: { loading: boolean; error: string | null }) {
  if (props.loading) return <p className="status">実行中…</p>;
  if (props.error) return <p className="status error">エラー: {props.error}</p>;
  return null;
}

// --- RAG search ------------------------------------------------------------

function SearchTab() {
  const [query, setQuery] = useState("配当 方針 DOE 配当性向");
  const [dbPath, setDbPath] = useState(".cache/investment_assistant/rag.sqlite");
  const [limit, setLimit] = useState(5);
  const [hybrid, setHybrid] = useState(true);
  const [alpha, setAlpha] = useState(0.5);
  const { loading, error, data, run } = useAsync<Json>();

  const search = () =>
    run(() => api("/api/rag/search", { query, db_path: dbPath, limit, hybrid, alpha }));

  const results: Json[] = data?.results ?? [];
  return (
    <section>
      <h2>RAG検索（語彙 BM25 + 意味 埋め込みのハイブリッド）</h2>
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
            max={1}
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
                <td className="mono">{r.source}</td>
                <td>{String(r.text).slice(0, 200)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// --- AI answer (orchestration, offline) -----------------------------------

function AnswerTab() {
  const [query, setQuery] = useState("配当方針について教えて");
  const [dbPath, setDbPath] = useState(".cache/investment_assistant/rag.sqlite");
  const [drafts, setDrafts] = useState(2);
  const [hybrid, setHybrid] = useState(true);
  const { loading, error, data, run } = useAsync<Json>();

  const ask = () =>
    run(() => api("/api/orchestrate", { query, db_path: dbPath, drafts, hybrid }));

  return (
    <section>
      <h2>AI回答（複数AIオーケストレーション・ローカル擬似 / 実API不使用）</h2>
      <p className="hint">
        ドラフト→批評→統合の多段生成です。Gemini APIは呼ばず、ローカル文書の根拠に限定します。
      </p>
      <div className="form">
        <Field label="質問">
          <input value={query} onChange={(e) => setQuery(e.target.value)} />
        </Field>
        <Field label="RAG DB パス">
          <input value={dbPath} onChange={(e) => setDbPath(e.target.value)} />
        </Field>
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
        <button className="primary" onClick={ask} disabled={loading}>
          回答生成
        </button>
      </div>
      <Status loading={loading} error={error} />
      {data && (
        <div className="answer">
          <h3>最終回答</h3>
          <pre>{data.answer}</pre>
          {data.critique && (
            <details>
              <summary>レビュー指摘</summary>
              <pre>{data.critique.text}</pre>
            </details>
          )}
          {Array.isArray(data.drafts) && (
            <details>
              <summary>ドラフト ({data.drafts.length})</summary>
              {data.drafts.map((d: Json, i: number) => (
                <pre key={i}>{d.text}</pre>
              ))}
            </details>
          )}
          {data.disclaimer && <p className="footer">{data.disclaimer}</p>}
        </div>
      )}
    </section>
  );
}

// --- Scoring ---------------------------------------------------------------

const SAMPLE_CSV =
  "name,expense_ratio,annual_return,volatility,diversification_score\n" +
  "低コスト全世界株式,0.12,0.065,0.18,0.95\n" +
  "高コストテーマ型,1.20,0.080,0.35,0.45\n" +
  "債券バランス型,0.35,0.030,0.08,0.80\n";

function ScoringTab() {
  const [csv, setCsv] = useState(SAMPLE_CSV);
  const [limit, setLimit] = useState(10);
  const { loading, error, data, run } = useAsync<Json>();

  const rank = () => run(() => api("/api/scoring/rank", { csv_text: csv, limit }));
  const results: Json[] = data?.results ?? [];
  return (
    <section>
      <h2>投資スコアリング（透明なルール・ローカルCSV）</h2>
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
      api("/api/forecast/evaluate", { space, ma_windows: parseWindows(), include_ml: false }),
    );
  const predict = () =>
    predictState.run(() => api("/api/forecast/predict", { horizon: 1, space }));

  const models: Json[] = evalState.data?.models ?? [];
  return (
    <section>
      <h2>アンサンブル予測（同梱S&P500サンプル・評価/予測）</h2>
      <p className="hint">統計的推定であり将来リターンの保証ではありません。</p>
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

const SAMPLE_SOURCES = JSON.stringify(
  [
    {
      name: "9432_NTT_ir",
      url: "https://group.ntt/jp/ir/",
      output_path: "local_docs/nikkei225/9432/ir.txt",
      query_hint: "9432 NTT 配当 方針 DOE 配当性向 IR",
      extract_text: true,
      include_metadata: true,
      preview_chars: 500,
    },
  ],
  null,
  2,
);

function ScrapeTab() {
  const [sourcesText, setSourcesText] = useState(SAMPLE_SOURCES);
  const { loading, error, data, run } = useAsync<Json>();

  function call(dry: boolean) {
    let sources: unknown;
    try {
      sources = JSON.parse(sourcesText);
    } catch {
      run(async () => {
        throw new Error("sources は有効なJSON配列にしてください");
      });
      return;
    }
    run(() => api(dry ? "/api/fetch-job/dry-run" : "/api/fetch-job/run", { sources }));
  }

  const results: Json[] = data?.results ?? [];
  return (
    <section>
      <h2>安全な取得（fetch-job）</h2>
      <p className="hint warn">
        必ず先に <b>dry-run</b> で robots.txt の許可を確認してください。本取得はネットワークへアクセスします。
        private/loopback等のアドレスやリダイレクト先はSSRF対策で拒否されます。
      </p>
      <div className="form">
        <Field label="sources（JSON配列）">
          <textarea rows={10} value={sourcesText} onChange={(e) => setSourcesText(e.target.value)} />
        </Field>
        <button className="primary" onClick={() => call(true)} disabled={loading}>
          dry-run（robots確認）
        </button>
        <button onClick={() => call(false)} disabled={loading}>
          取得実行
        </button>
      </div>
      <Status loading={loading} error={error} />
      {results.length > 0 && (
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
            {results.map((r, i) => (
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
      )}
    </section>
  );
}

// --- Budget / cache --------------------------------------------------------

function OpsTab() {
  const budget = useAsync<Json>();
  const cache = useAsync<Json>();
  useEffect(() => {
    budget.run(() => api("/api/budget"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <section>
      <h2>予算 / キャッシュ</h2>
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
        <button onClick={() => cache.run(() => api("/api/cache/maintenance", { max_rows: 1000 }))}>
          キャッシュ整理（期限切れ削除＋上限1000）
        </button>
      </div>
      <Status loading={cache.loading} error={cache.error} />
      {cache.data && <pre>{JSON.stringify(cache.data, null, 2)}</pre>}
    </section>
  );
}
