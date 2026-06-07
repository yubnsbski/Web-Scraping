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

function Metric(props: { label: string; value: string }) {
  return (
    <article className="metric-card">
      <span>{props.label}</span>
      <b>{props.value}</b>
    </article>
  );
}

function BarChart(props: { rows: Json[]; valueKey: string }) {
  const max = Math.max(...props.rows.map((r) => toNumber(r[props.valueKey])), 1);

  return (
    <div style={{ display: "flex", gap: 10, alignItems: "end", minHeight: 160 }}>
      {props.rows.map((row, index) => {
        const value = toNumber(row[props.valueKey]);
        const height = Math.max(6, (value / max) * 120);

        return (
          <div
            key={`${row.period ?? index}`}
            style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}
          >
            <div
              style={{
                height: 120,
                border: "1px solid currentColor",
                borderRadius: 8,
                display: "flex",
                alignItems: "end",
                overflow: "hidden",
                opacity: 0.75,
              }}
            >
              <span
                style={{
                  display: "block",
                  width: "100%",
                  height,
                  background: "currentColor",
                }}
              />
            </div>
            <small style={{ textAlign: "center" }}>{String(row.period ?? "")}</small>
          </div>
        );
      })}
    </div>
  );
}

function LineChart(props: { rows: Json[]; valueKey: string; label: string }) {
  const values = props.rows.map((r) => toNumber(r[props.valueKey]));
  if (values.length === 0) return <p className="hint">データがありません。</p>;

  const width = 360;
  const height = 160;
  const pad = 18;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = values
    .map((value, index) => {
      const x = pad + ((width - pad * 2) * index) / Math.max(values.length - 1, 1);
      const y = height - pad - ((value - min) / range) * (height - pad * 2);
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={props.label}>
      <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="currentColor" opacity="0.25" />
      <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="currentColor" opacity="0.25" />
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="3" />
      {points.split(" ").map((point, index) => {
        const [x, y] = point.split(",");
        return <circle key={`${point}-${index}`} cx={x} cy={y} r="3" fill="currentColor" />;
      })}
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

  useEffect(() => {
    void load();
  }, []);

  const dividendSeries: Json[] = Array.isArray(dividends?.series) ? dividends.series : [];
  const performanceSeries: Json[] = Array.isArray(performance?.series) ? performance.series : [];

  return (
    <section className="tool-section">
      <div className="section-head">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h2>配当・運用グラフ</h2>
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
        <Metric label="年間配当" value={yen(dividends?.latest_annual)} />
        <Metric label="平均利回り" value={pct(dividends?.avg_yield_pct)} />
        <Metric label="増配継続" value={`${Math.round(toNumber(dividends?.increase_streak))}期`} />
        <Metric label="評価額" value={yen(performance?.market_value)} />
        <Metric label="損益" value={yen(performance?.pnl)} />
        <Metric label="最大DD" value={pct(performance?.max_drawdown_pct)} />
      </section>

      <section className="guide-grid">
        <article className="guide-card">
          <b>年間配当</b>
          <BarChart rows={dividendSeries} valueKey="dividend_received" />
        </article>

        <article className="guide-card">
          <b>評価額推移</b>
          <LineChart rows={performanceSeries} valueKey="market_value" label="評価額推移" />
        </article>

        <article className="guide-card">
          <b>損益率</b>
          <LineChart rows={performanceSeries} valueKey="pnl_pct" label="損益率" />
        </article>
      </section>

      {(dividends?.disclaimer || performance?.disclaimer) && (
        <p className="hint">{String(dividends?.disclaimer ?? performance?.disclaimer)}</p>
      )}
    </section>
  );
}
