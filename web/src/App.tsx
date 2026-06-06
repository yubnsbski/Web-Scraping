import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";

type Json = Record<string, any>;

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  meta?: string;
  sources?: Json[];
};

type SourcePreset = {
  label: string;
  name: string;
  url: string;
  output_path: string;
  query_hint: string;
};

const DEFAULT_RAG_DB_PATH = ".cache/investment_assistant/rag.sqlite";

const TABS = [
  { id: "search", label: "Research" },
  { id: "answer", label: "AI Chat" },
  { id: "scoring", label: "Score" },
  { id: "forecast", label: "Forecast" },
  { id: "scrape", label: "Data Intake" },
  { id: "ops", label: "Ops" },
] as const;

const HERO_CARDS = [
  { label: "RAG", value: "Evidence", desc: "ローカル文書だけを根拠化" },
  { label: "Score", value: "Compare", desc: "CSVで候補を横比較" },
  { label: "Forecast", value: "Backtest", desc: "同梱データで検証" },
  { label: "Intake", value: "Auto / Manual", desc: "取得失敗時も手動登録" },
] as const;

const SUGGESTED_QUESTIONS = [
  "この銘柄の配当方針と減配リスクを、根拠つきで整理して",
  "S&P500と高配当ETFを比較して、長期保有の弱点を出して",
  "NISA成長投資枠で見る場合、候補の優先順位をどう確認すべき？",
  "取得済みIR資料だけを根拠に、買う前の確認項目を作って",
  "直近の予測結果を踏まえて、判断を保留すべき危険ポイントを出して",
  "このポートフォリオで集中リスクが出る箇所を指摘して",
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

const SAMPLE_CSV =
  "name,expense_ratio,annual_return,volatility,diversification_score\n" +
  "低コスト全世界株式,0.12,0.065,0.18,0.95\n" +
  "高コストテーマ型,1.20,0.080,0.35,0.45\n" +
  "債券バランス型,0.35,0.030,0.08,0.80\n";

const SAMPLE_SOURCES = JSON.stringify([presetToSource(SOURCE_PRESETS[0])], null, 2);

type TabId = (typeof TABS)[number]["id"];

export function App() {
  const [tab, setTab] = useState<TabId>("answer");
  return (
    <div className="app">
      <header className="terminal-hero">
        <div className="hero-copy">
          <p className="eyebrow">Investment Research Terminal</p>
          <h1>Investment Assistant</h1>
          <p className="hero-lead">
            IR資料・ローカルメモ・CSVを根拠に、調査、比較、予測、取得を1画面で進めます。
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

function buildContextualQuery(messages: ChatMessage[], currentQuestion: string) {
  const conversation = messages
    .slice(-8)
    .map((message) => `${message.role === "user" ? "ユーザー" : "アシスタント"}: ${message.content}`)
    .join("\n");
  return [
    "以下の会話履歴を踏まえて、最後の質問に自然に返答してください。",
    "ローカル文書にない事実は推測せず、不明または要検証と明記してください。",
    "出力は日本語で、結論、根拠、不確実性、次アクションの順にしてください。",
    "",
    "会話履歴",
    conversation || "なし",
    "",
    "最後の質問:",
    currentQuestion,
  ].join("\n");
}

function cleanAssistantAnswer(raw: unknown, skipped?: boolean) {
  const text = typeof raw === "string" ? raw.trim() : JSON.stringify(raw, null, 2);
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
          <p className="eyebrow">Research</p>
          <h2>RAG検索</h2>
        </div>
        <span className="badge">BM25 + Embedding</span>
      </div>
      <QuestionChips onPick={setQuery} />
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
                <td>{String(r.text).slice(0, 220)}</td>
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
  const [query, setQuery] = useState("S&P500と高配当ETFを比較して、長期保有の弱点を出して");
  const [dbPath, setDbPath] = useState(DEFAULT_RAG_DB_PATH);
  const [drafts, setDrafts] = useState(2);
  const [hybrid, setHybrid] = useState(true);
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
      const contextualQuery = buildContextualQuery(nextMessages, trimmed);
      const result = await api<Json>("/api/orchestrate", {
        query: contextualQuery,
        db_path: dbPath,
        drafts,
        hybrid,
        limit: 6,
      });
      setLastData(result);
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: cleanAssistantAnswer(result.answer, result.skipped),
          meta: result.skipped ? "RAG未ヒット" : "RAG回答",
          sources: result.results ?? [],
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
        <span className="badge">Local orchestration</span>
      </div>
      <p className="hint">
        直近の会話履歴を質問に含めて送信します。UIから実Gemini APIは呼ばず、ローカル文書の根拠に限定します。
      </p>

      <QuestionChips onPick={setQuery} />

      <div className="chat-window">
        {messages.map((message, index) => (
          <article key={`${message.role}-${index}`} className={`chat-bubble ${message.role}`}>
            <div className="chat-meta">
              <span>{message.role === "user" ? "You" : "Assistant"}</span>
              {message.meta && <small>{message.meta}</small>}
            </div>
            <pre>{message.content}</pre>
            {message.sources && message.sources.length > 0 && (
              <details>
                <summary>根拠候補 {message.sources.length}件</summary>
                <ul className="source-list">
                  {message.sources.slice(0, 5).map((source, i) => (
                    <li key={source.chunk_id ?? i}>
                      <span className="mono">{source.source}</span>
                      <p>{String(source.text ?? "").slice(0, 160)}</p>
                    </li>
                  ))}
                </ul>
              </details>
            )}
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
            送信
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
      </div>

      <Status loading={loading} error={error} />
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
          {sourceResults.length > 0 && <p className="hint">根拠候補: {sourceResults.length}件</p>}
        </details>
      )}
    </section>
  );
}

// --- Scoring ---------------------------------------------------------------

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
        <span className="badge">CSV compare</span>
      </div>
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
  const sourceState = useAsync<Json>();
  const manualState = useAsync<Json>();

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

  function call(dry: boolean) {
    let sources: unknown;
    try {
      sources = JSON.parse(sourcesText);
    } catch {
      sourceState.run(async () => {
        throw new Error("sources は有効なJSON配列にしてください");
      });
      return;
    }
    if (!Array.isArray(sources) || sources.length === 0) {
      sourceState.run(async () => {
        throw new Error("sources は1件以上のJSON配列にしてください");
      });
      return;
    }
    sourceState.run(async () => {
      const result = await api<Json>(dry ? "/api/fetch-job/dry-run" : "/api/fetch-job/run", {
        sources,
      });
      if (!dry && indexAfterFetch) {
        const index = await api<Json>("/api/rag/index-dir", { path: indexPath, db_path: dbPath });
        return { ...result, index };
      }
      return result;
    });
  }

  const saveManual = () =>
    manualState.run(() =>
      api<Json>("/api/manual-doc/save", {
        title: manualTitle,
        source_url: manualSourceUrl,
        text: manualText,
        db_path: dbPath,
      }),
    );

  const results: Json[] = sourceState.data?.results ?? [];
  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Data Intake</p>
          <h2>自動取得 / 手動取込</h2>
        </div>
        <span className="badge warn">robots確認必須</span>
      </div>

      <div className="workflow">
        <article className="step-card">
          <b>1. dry-run</b>
          <span>robots.txt とURL安全性を確認</span>
        </article>
        <article className="step-card">
          <b>2. 取得実行</b>
          <span>HTMLをテキスト化して local_docs に保存</span>
        </article>
        <article className="step-card">
          <b>3. RAG登録</b>
          <span>取得後に自動で検索DBへ登録</span>
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
        <button className="primary" onClick={() => call(true)} disabled={sourceState.loading}>
          dry-run
        </button>
        <button onClick={() => call(false)} disabled={sourceState.loading}>
          取得 + 登録
        </button>
      </div>
      <Status loading={sourceState.loading} error={sourceState.error} />
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
      {sourceState.data?.index && (
        <p className="callout">RAG登録完了: {JSON.stringify(sourceState.data.index)}</p>
      )}

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

// --- Budget / cache --------------------------------------------------------

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
