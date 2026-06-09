import { useEffect, useState } from "react";
import { api } from "./api";

type Json = Record<string, any>;

function toNumber(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function yen(value: unknown): string {
  return `${Math.round(toNumber(value)).toLocaleString()}円`;
}

function pct(value: unknown): string {
  return `${toNumber(value).toFixed(2)}%`;
}

type Tone = "accent" | "pos" | "neg" | "warn";

function Metric(props: { label: string; value: string; tone?: Tone }) {
  return (
    <article className={`metric-card${props.tone ? ` ${props.tone}` : ""}`}>
      <span>{props.label}</span>
      <b>{props.value}</b>
    </article>
  );
}

function BarChart(props: { rows: Json[]; valueKey: string; fmt?: (v: number) => string }) {
  if (props.rows.length === 0) return <p className="hint">データがありません。</p>;
  const values = props.rows.map((r) => toNumber(r[props.valueKey]));
  const max = Math.max(...values, 1);

  return (
    <div className="chart-bars">
      {props.rows.map((row, index) => {
        const value = toNumber(row[props.valueKey]);
        const height = `${Math.max(3, (value / max) * 100)}%`;
        return (
          <div className="chart-bar" key={`${row.period ?? index}`}>
            <small className="chart-bar-val">
              {props.fmt ? props.fmt(value) : value.toLocaleString()}
            </small>
            <div className="chart-bar-track">
              <i style={{ height }} />
            </div>
            <small className="chart-bar-label">{String(row.period ?? "")}</small>
          </div>
        );
      })}
    </div>
  );
}

function AreaChart(props: {
  rows: Json[];
  valueKey: string;
  label: string;
  tone?: "accent" | "good" | "bad";
  fmt?: (v: number) => string;
}) {
  const values = props.rows.map((r) => toNumber(r[props.valueKey]));
  if (values.length === 0) return <p className="hint">データがありません。</p>;

  const width = 480;
  const height = 170;
  const pad = 24;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const xs = (i: number) => pad + ((width - pad * 2) * i) / Math.max(values.length - 1, 1);
  const ys = (v: number) => height - pad - ((v - min) / range) * (height - pad * 2);

  const line = values.map((v, i) => `${xs(i)},${ys(v)}`).join(" ");
  const area = `${pad},${height - pad} ${line} ${xs(values.length - 1)},${height - pad}`;
  const stroke =
    props.tone === "good" ? "var(--safe)" : props.tone === "bad" ? "var(--error)" : "var(--accent)";
  const gid = `dash-grad-${props.valueKey}-${props.tone ?? "accent"}`;
  const last = values[values.length - 1];

  return (
    <svg className="area-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={props.label}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.34" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0, 0.5, 1].map((t) => {
        const y = pad + t * (height - pad * 2);
        return (
          <line key={t} x1={pad} y1={y} x2={width - pad} y2={y} stroke="var(--line)" strokeOpacity="0.5" />
        );
      })}
      <polygon points={area} fill={`url(#${gid})`} />
      <polyline
        points={line}
        fill="none"
        stroke={stroke}
        strokeWidth="2.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={xs(values.length - 1)} cy={ys(last)} r="4" fill={stroke} />
      <text x={width - pad} y={ys(last) - 9} textAnchor="end" className="area-last" fill={stroke}>
        {props.fmt ? props.fmt(last) : last.toLocaleString()}
      </text>
    </svg>
  );
}

export function DashboardTab() {
  const [dividendsPath, setDividendsPath] = useState("examples/portfolio_dividends_sample.csv");
  const [performancePath, setPerformancePath] = useState("examples/portfolio_performance_sample.csv");
  const [dividends, setDividends] = useState<Json | null>(null);
  const [performance, setPerformance] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);

    try {
      const [dividendResult, performanceResult] = await Promise.all([
        api<Json>("/api/portfolio/dividends", { path: dividendsPath }),
        api<Json>("/api/portfolio/performance", { path: performancePath }),
      ]);

      setDividends(dividendResult);
      setPerformance(performanceResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const [topStocks, setTopStocks] = useState<Json[]>([]);

  useEffect(() => {
    void load();
    api<Json>("/api/scoring/stocks", { strategy: "balanced", limit: 5 })
      .then((r) => setTopStocks(Array.isArray(r.results) ? r.results : []))
      .catch(() => setTopStocks([]));
  }, []);

  const dividendSeries: Json[] = Array.isArray(dividends?.series) ? dividends.series : [];
  const performanceSeries: Json[] = Array.isArray(performance?.series) ? performance.series : [];
  const pnl = toNumber(performance?.pnl);
  const pnlPositive = pnl >= 0;

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h2>運用実績</h2>
        </div>
        <span className="badge">Portfolio CSV</span>
      </div>

      <p className="hint">
        ユーザー提供CSVを機械的に集計します。投資助言・売買推奨・自動売買は行いません。
      </p>

      <div className="form compact-form">
        <label className="field">
          <span>配当CSVパス</span>
          <input value={dividendsPath} onChange={(e) => setDividendsPath(e.target.value)} />
        </label>

        <label className="field">
          <span>運用CSVパス</span>
          <input value={performancePath} onChange={(e) => setPerformancePath(e.target.value)} />
        </label>

        <button className="primary" onClick={() => void load()} disabled={loading}>
          読み込み
        </button>
      </div>

      {loading && <p className="status">実行中…</p>}
      {error && <p className="status error">エラー: {error}</p>}

      <section className="metric-grid">
        <Metric label="評価額" value={yen(performance?.market_value)} tone="accent" />
        <Metric label="損益" value={yen(performance?.pnl)} tone={pnlPositive ? "pos" : "neg"} />
        <Metric label="最大DD" value={pct(performance?.max_drawdown_pct)} tone="warn" />
        <Metric label="年間配当" value={yen(dividends?.latest_annual)} tone="pos" />
        <Metric label="平均利回り" value={pct(dividends?.avg_yield_pct)} tone="accent" />
        <Metric
          label="増配継続"
          value={`${Math.round(toNumber(dividends?.increase_streak))}期`}
        />
      </section>

      <section className="dash-charts">
        <article className="guide-card chart-card chart-card-wide">
          <b>評価額推移</b>
          <AreaChart
            rows={performanceSeries}
            valueKey="market_value"
            label="評価額推移"
            tone="accent"
            fmt={(v) => yen(v)}
          />
        </article>

        <article className="guide-card chart-card">
          <b>損益率</b>
          <AreaChart
            rows={performanceSeries}
            valueKey="pnl_pct"
            label="損益率"
            tone={pnlPositive ? "good" : "bad"}
            fmt={(v) => `${v.toFixed(2)}%`}
          />
        </article>

        <article className="guide-card chart-card chart-card-wide">
          <b>年間配当</b>
          <BarChart rows={dividendSeries} valueKey="dividend_received" fmt={(v) => yen(v)} />
        </article>
      </section>

      {topStocks.length > 0 && (
        <article className="guide-card chart-card chart-card-wide">
          <b>配当品質スコア 上位（EDINET・バランス戦略）</b>
          <table className="grid">
            <thead>
              <tr>
                <th>順位</th>
                <th>銘柄</th>
                <th>スコア</th>
              </tr>
            </thead>
            <tbody>
              {topStocks.map((s) => (
                <tr key={String(s.ticker)}>
                  <td>{String(s.rank)}</td>
                  <td>
                    <b>{String(s.ticker)}</b> {String(s.name ?? "")}
                  </td>
                  <td className="mono">{Number(s.total_score).toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      )}

      {(dividends?.disclaimer || performance?.disclaimer) && (
        <p className="hint">{String(dividends?.disclaimer ?? performance?.disclaimer)}</p>
      )}
    </section>
  );
}
