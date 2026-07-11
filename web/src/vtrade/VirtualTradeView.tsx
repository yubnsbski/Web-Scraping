// 仮想取引 (virtual trading) tab: Minkabu-style paper trading against the
// user's own book, plus a fully autonomous AI account that trades itself
// (stock selection is automatic — this view only visualizes + controls the
// autopilot cadence, it never picks stocks itself). All money here is
// simulated; no real orders are ever placed.
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  TouchEvent as ReactTouchEvent,
} from "react";
import { api } from "../api";
import "./vtrade.css";

// ---- API contract types -----------------------------------------------

type Position = {
  ticker: string;
  name: string;
  sector: string;
  shares: number;
  avg_cost: number;
  price: number;
  price_date: string;
  value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
};

type PortfolioBase = {
  as_of: string;
  initial_cash: number;
  cash: number;
  equity: number;
  invested_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  tax_withheld: number;
  total_return_pct: number;
  positions: Position[];
  trade_count: number;
  disclaimer: string;
};

type AiPortfolio = PortfolioBase & {
  preset: "balanced" | "defensive" | "momentum";
  last_run_date: string | null;
  auto: boolean;
};

type CurvePoint = { date: string; equity: number; cash: number };

type PerformanceResp = {
  curve: CurvePoint[];
  initial_cash: number;
  total_return_pct: number;
  max_drawdown: number;
  realized_pnl: number;
  unrealized_pnl: number;
  as_of: string;
  disclaimer: string;
};

type Trade = {
  id: string | number;
  ts: string;
  trade_date: string;
  ticker: string;
  name: string;
  side: "buy" | "sell";
  shares: number;
  price: number;
  commission: number;
  realized_pnl: number | null;
  tax_delta: number;
  cash_after: number;
  account?: "user" | "ai";
  source?: "user" | "ai";
};

type HistoryResp = { trades: Trade[]; count: number };

type QuoteOk = {
  ok: true;
  ticker: string;
  name: string;
  sector: string;
  price: number;
  date: string;
  lot: number;
  min_cost: number;
};
type QuoteFail = { ok: false; reason: string; message: string };
type QuoteResp = QuoteOk | QuoteFail;

type OrderFill = {
  ticker: string;
  name: string;
  side: "buy" | "sell";
  shares: number;
  price: number;
  commission: number;
  trade_date: string;
  settlement_date: string;
  realized_pnl: number;
  tax_delta: number;
};
type OrderResp =
  | { ok: true; fill: OrderFill; cash: number; equity: number }
  | { ok: false; reason: string; message: string };

type ResetResp = { ok: true; initial_cash: number };

type RunEntry = { date: string; buys: number; sells: number };
type AutopilotRunResp = { ok: boolean; ran: RunEntry[]; last_run_date: string };
type AutopilotConfigResp = { ok: boolean; preset: string; auto: boolean };

type Bar = { date: string; open: number; high: number; low: number; close: number; volume: number };
type BarSeries = {
  ticker: string;
  name: string;
  sector: string;
  bars: Bar[];
  last_close: number;
  prev_close: number;
  day_change_pct: number;
  period_change_pct: number;
};
type BarsResp = { as_of: string; series: BarSeries[]; missing: string[] };

// ---- constants -----------------------------------------------------------

const WATCH_TICKERS_KEY = "ia.vtrade.watchTickers";

const PERIOD_OPTIONS: Array<{ label: string; days: number }> = [
  { label: "1ヶ月", days: 22 },
  { label: "3ヶ月", days: 66 },
  { label: "全期間", days: 400 },
];

const PRESET_OPTIONS: Array<{ label: string; value: "balanced" | "defensive" | "momentum" }> = [
  { label: "バランス", value: "balanced" },
  { label: "ディフェンシブ", value: "defensive" },
  { label: "モメンタム", value: "momentum" },
];

// ---- formatting helpers ----------------------------------------------

function formatYen(n: number): string {
  return `¥${Math.round(n).toLocaleString("ja-JP")}`;
}

function formatPct(n: number, digits = 2): string {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

function formatManCompact(n: number, decimals = 0): string {
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(abs >= 1e9 ? 0 : 1)}億`;
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(decimals)}万`;
  return `${sign}${Math.round(abs).toLocaleString("ja-JP")}`;
}

// Picks enough decimal digits that adjacent axis ticks don't collapse to the
// same "X万" label when the plotted range is small relative to 10,000.
function manDecimalsForStep(step: number): number {
  const stepIn10k = Math.abs(step) / 1e4;
  if (stepIn10k >= 1) return 0;
  if (stepIn10k >= 0.1) return 1;
  return 2;
}

function formatDateShort(d: string): string {
  const parts = d.split("-");
  if (parts.length === 3) return `${parts[1]}/${parts[2]}`;
  return d;
}

function pnlClass(n: number): string {
  return n >= 0 ? "vt-pos" : "vt-neg";
}

function loadWatchTickers(): string[] {
  try {
    const raw = localStorage.getItem(WATCH_TICKERS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.filter((x): x is string => typeof x === "string");
  } catch {
    // localStorage unavailable or corrupt: fall back to empty.
  }
  return [];
}

// ---- shared chart pointer/touch hook ----------------------------------
// Converts a pointer (mouse or touch) clientX into an x coordinate in the
// SVG's own viewBox units. Each chart still owns its own padding-aware
// "nearest index" math since paddings differ between the big equity chart
// and the small price panels.

function useChartHover() {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);
  function vbXFromClientX(clientX: number, vbWidth: number): number | null {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0) return null;
    return ((clientX - rect.left) / rect.width) * vbWidth;
  }
  return { svgRef, hoverX, setHoverX, vbXFromClientX };
}

// ---- 運用実績: side-by-side あなた/AI metrics dashboard -----------------

type AccountStats = {
  label: string;
  equity: number;
  totalReturnPct: number;
  realizedPnl: number;
  unrealizedPnl: number;
  maxDrawdown: number;
  tradeCount: number;
  winRate: number | null;
};

function computeWinRate(trades: Trade[], account: "user" | "ai"): number | null {
  const closed = trades.filter((t) => (t.account ?? t.source ?? "user") === account && t.realized_pnl != null);
  if (closed.length === 0) return null;
  const wins = closed.filter((t) => (t.realized_pnl as number) > 0).length;
  return (wins / closed.length) * 100;
}

function PerformanceSummaryTable({ rows }: { rows: AccountStats[] }) {
  return (
    <div className="table-wrap vt-summary-wrap">
      <table className="data-table vt-summary-table">
        <thead>
          <tr>
            <th></th>
            {rows.map((r) => (
              <th key={r.label} style={{ textAlign: "right" }}>
                {r.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>総資産</td>
            {rows.map((r) => (
              <td key={r.label} style={{ textAlign: "right" }}>
                {formatYen(r.equity)}
              </td>
            ))}
          </tr>
          <tr>
            <td>損益率</td>
            {rows.map((r) => (
              <td key={r.label} style={{ textAlign: "right" }} className={pnlClass(r.totalReturnPct)}>
                {formatPct(r.totalReturnPct)}
              </td>
            ))}
          </tr>
          <tr>
            <td>実現損益</td>
            {rows.map((r) => (
              <td key={r.label} style={{ textAlign: "right" }} className={pnlClass(r.realizedPnl)}>
                {formatYen(r.realizedPnl)}
              </td>
            ))}
          </tr>
          <tr>
            <td>評価損益</td>
            {rows.map((r) => (
              <td key={r.label} style={{ textAlign: "right" }} className={pnlClass(r.unrealizedPnl)}>
                {formatYen(r.unrealizedPnl)}
              </td>
            ))}
          </tr>
          <tr>
            <td>最大ドローダウン</td>
            {rows.map((r) => (
              <td key={r.label} style={{ textAlign: "right" }} className={r.maxDrawdown < 0 ? "vt-neg" : ""}>
                {formatPct(r.maxDrawdown)}
              </td>
            ))}
          </tr>
          <tr>
            <td>勝率（決済済）</td>
            {rows.map((r) => (
              <td key={r.label} style={{ textAlign: "right" }}>
                {r.winRate == null ? "—" : formatPct(r.winRate, 0)}
              </td>
            ))}
          </tr>
          <tr>
            <td>取引回数</td>
            {rows.map((r) => (
              <td key={r.label} style={{ textAlign: "right" }}>
                {r.tradeCount.toLocaleString("ja-JP")}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ---- 運用実績: two-series (あなた / AI) equity comparison chart --------

function EquityChart({
  userCurve,
  aiCurve,
  initialCash,
}: {
  userCurve: CurvePoint[];
  aiCurve: CurvePoint[];
  initialCash: number;
}) {
  const VB_W = 680;
  const VB_H = 280;
  const pad = { left: 58, right: 100, top: 18, bottom: 30 };
  const plotW = VB_W - pad.left - pad.right;
  const plotH = VB_H - pad.top - pad.bottom;

  const dates = useMemo(() => {
    const set = new Set<string>();
    userCurve.forEach((c) => set.add(c.date));
    aiCurve.forEach((c) => set.add(c.date));
    return Array.from(set).sort();
  }, [userCurve, aiCurve]);
  const n = dates.length;
  const userMap = useMemo(() => new Map(userCurve.map((c) => [c.date, c.equity])), [userCurve]);
  const aiMap = useMemo(() => new Map(aiCurve.map((c) => [c.date, c.equity])), [aiCurve]);

  const allValues: number[] = [initialCash];
  userCurve.forEach((c) => allValues.push(c.equity));
  aiCurve.forEach((c) => allValues.push(c.equity));
  const minRaw = Math.min(...allValues);
  const maxRaw = Math.max(...allValues);
  const span = maxRaw - minRaw || Math.max(maxRaw, 1) * 0.05;
  const minV = minRaw - span * 0.08;
  const maxV = maxRaw + span * 0.08;
  const denom = maxV - minV || 1;

  const x = (i: number) => (n <= 1 ? pad.left + plotW / 2 : pad.left + (i / (n - 1)) * plotW);
  const y = (v: number) => pad.top + (1 - (v - minV) / denom) * plotH;

  const userPoints = dates
    .map((d, i) => ({ i, v: userMap.get(d) }))
    .filter((p): p is { i: number; v: number } => p.v != null);
  const aiPoints = dates
    .map((d, i) => ({ i, v: aiMap.get(d) }))
    .filter((p): p is { i: number; v: number } => p.v != null);

  const userPath = userPoints.map((p) => `${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const aiPath = aiPoints.map((p) => `${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const userAreaPath =
    userPoints.length > 1
      ? `M ${x(userPoints[0].i).toFixed(1)},${(pad.top + plotH).toFixed(1)} L ${userPath} L ${x(
          userPoints[userPoints.length - 1].i,
        ).toFixed(1)},${(pad.top + plotH).toFixed(1)} Z`
      : "";

  const gridCount = 4;
  const gridDecimals = manDecimalsForStep(denom / gridCount);
  const gridLines = Array.from({ length: gridCount + 1 }, (_, k) => {
    const v = minV + (denom * k) / gridCount;
    return { v, y: y(v) };
  });
  const initialY = y(initialCash);

  const { svgRef, hoverX, setHoverX, vbXFromClientX } = useChartHover();
  function nearestIndex(vx: number): number {
    if (n <= 1) return 0;
    const t = (vx - pad.left) / plotW;
    return Math.min(Math.max(Math.round(t * (n - 1)), 0), n - 1);
  }
  const hoverIndex = hoverX == null ? null : nearestIndex(hoverX);
  const hoverDate = hoverIndex != null ? dates[hoverIndex] : null;
  const hoverUserV = hoverDate != null ? userMap.get(hoverDate) : undefined;
  const hoverAiV = hoverDate != null ? aiMap.get(hoverDate) : undefined;

  function handleMove(e: ReactMouseEvent<SVGRectElement>) {
    const vx = vbXFromClientX(e.clientX, VB_W);
    if (vx != null) setHoverX(vx);
  }
  function handleTouch(e: ReactTouchEvent<SVGRectElement>) {
    const t = e.touches[0];
    if (!t) return;
    const vx = vbXFromClientX(t.clientX, VB_W);
    if (vx != null) setHoverX(vx);
  }

  const lastUser = userPoints[userPoints.length - 1] as { i: number; v: number } | undefined;
  const lastAi = aiPoints[aiPoints.length - 1] as { i: number; v: number } | undefined;
  let userLabelY = lastUser ? y(lastUser.v) : 0;
  let aiLabelY = lastAi ? y(lastAi.v) : 0;
  if (lastUser && lastAi && Math.abs(userLabelY - aiLabelY) < 22) {
    if (userLabelY <= aiLabelY) {
      userLabelY -= 11;
      aiLabelY += 11;
    } else {
      userLabelY += 11;
      aiLabelY -= 11;
    }
  }

  const userOnly = aiPoints.length === 0 && userPoints.length > 0;
  const aiOnly = userPoints.length === 0 && aiPoints.length > 0 && aiPoints.length !== userPoints.length;

  return (
    <div className="vt-chart-wrap">
      <div className="vt-legend">
        <span className="vt-legend-item">
          <i style={{ background: "var(--accent)" }} />
          あなた
        </span>
        <span className="vt-legend-item">
          <i style={{ background: "#185fa5" }} />
          AI
        </span>
      </div>
      <svg ref={svgRef} viewBox={`0 0 ${VB_W} ${VB_H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {gridLines.map((g, idx) => (
          <g key={idx}>
            <line x1={pad.left} x2={VB_W - pad.right} y1={g.y} y2={g.y} stroke="var(--line)" strokeWidth={1} />
            <text x={pad.left - 8} y={g.y + 4} textAnchor="end" fontSize="11" fill="var(--muted)">
              {formatManCompact(g.v, gridDecimals)}
            </text>
          </g>
        ))}
        <line
          x1={pad.left}
          x2={VB_W - pad.right}
          y1={initialY}
          y2={initialY}
          stroke="var(--muted)"
          strokeWidth={1}
          strokeDasharray="4 4"
        />
        <text x={VB_W - pad.right + 6} y={initialY + 4} fontSize="11" fill="var(--muted)">
          元本
        </text>

        {userAreaPath && <path d={userAreaPath} fill="var(--accent)" opacity={0.08} stroke="none" />}
        {userPath && <polyline points={userPath} fill="none" stroke="var(--accent)" strokeWidth={2} />}
        {aiPath && <polyline points={aiPath} fill="none" stroke="#185fa5" strokeWidth={2} />}

        {lastUser && (
          <>
            <circle cx={x(lastUser.i)} cy={y(lastUser.v)} r={3} fill="var(--accent)" />
            <text x={x(lastUser.i) + 8} y={userLabelY + 4} fontSize="11" fontWeight={700} fill="var(--ink)">
              あなた {formatYen(lastUser.v)}
            </text>
          </>
        )}
        {lastAi && (
          <>
            <circle cx={x(lastAi.i)} cy={y(lastAi.v)} r={3} fill="#185fa5" />
            <text x={x(lastAi.i) + 8} y={aiLabelY + 4} fontSize="11" fontWeight={700} fill="var(--ink)">
              AI {formatYen(lastAi.v)}
            </text>
          </>
        )}

        {n > 0 && (
          <>
            <text x={pad.left} y={VB_H - 8} fontSize="11" fill="var(--muted)">
              {formatDateShort(dates[0])}
            </text>
            <text x={VB_W - pad.right} y={VB_H - 8} textAnchor="end" fontSize="11" fill="var(--muted)">
              {formatDateShort(dates[n - 1])}
            </text>
          </>
        )}

        {hoverIndex != null && (
          <line
            x1={x(hoverIndex)}
            x2={x(hoverIndex)}
            y1={pad.top}
            y2={pad.top + plotH}
            stroke="var(--muted)"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
        )}
        {hoverIndex != null && hoverUserV != null && (
          <circle cx={x(hoverIndex)} cy={y(hoverUserV)} r={4} fill="var(--accent)" stroke="white" strokeWidth={1.5} />
        )}
        {hoverIndex != null && hoverAiV != null && (
          <circle cx={x(hoverIndex)} cy={y(hoverAiV)} r={4} fill="#185fa5" stroke="white" strokeWidth={1.5} />
        )}

        {plotW > 0 && (
          <rect
            x={pad.left}
            y={0}
            width={plotW}
            height={VB_H}
            fill="transparent"
            onMouseMove={handleMove}
            onMouseLeave={() => setHoverX(null)}
            onTouchStart={handleTouch}
            onTouchMove={handleTouch}
            onTouchEnd={() => setHoverX(null)}
            style={{ cursor: "crosshair" }}
          />
        )}
      </svg>
      {hoverIndex != null && hoverDate != null && (hoverUserV != null || hoverAiV != null) && (
        <div className="vt-tooltip" style={{ left: `${(x(hoverIndex) / VB_W) * 100}%`, top: `${(pad.top / VB_H) * 100}%` }}>
          <b>{hoverDate}</b>
          {hoverUserV != null && (
            <div>
              あなた {formatYen(hoverUserV)}（{formatPct(((hoverUserV - initialCash) / initialCash) * 100)}）
            </div>
          )}
          {hoverAiV != null && (
            <div>
              AI {formatYen(hoverAiV)}（{formatPct(((hoverAiV - initialCash) / initialCash) * 100)}）
            </div>
          )}
        </div>
      )}
      {userOnly && <p className="vt-chart-note">AIはまだ取引していません。</p>}
      {aiOnly && <p className="vt-chart-note">あなたはまだ取引していません。</p>}
    </div>
  );
}

// ---- 値動き: small per-ticker price sparkline panel --------------------

function PriceMiniChart({
  series,
  onSelect,
  onRemove,
  removable,
}: {
  series: BarSeries;
  onSelect: () => void;
  onRemove?: () => void;
  removable: boolean;
}) {
  const VB_W = 240;
  const VB_H = 88;
  const padX = 4;
  const padY = 6;
  const bars = series.bars;
  const closes = bars.map((b) => b.close);
  const n = closes.length;
  const minV = n > 0 ? Math.min(...closes) : 0;
  const maxV = n > 0 ? Math.max(...closes) : 0;
  const span = maxV - minV || 1;
  const x = (i: number) => (n <= 1 ? VB_W / 2 : padX + (i / (n - 1)) * (VB_W - padX * 2));
  const y = (v: number) => padY + (1 - (v - minV) / span) * (VB_H - padY * 2);
  const rising = n >= 2 ? closes[n - 1] >= closes[0] : true;
  const areaColor = rising ? "#bbf7d0" : "#fecaca";
  const strokeColor = rising ? "#16a34a" : "#dc2626";
  const points = bars.map((b, i) => `${x(i).toFixed(1)},${y(b.close).toFixed(1)}`).join(" ");
  const areaPath =
    n > 1
      ? `M ${x(0).toFixed(1)},${(VB_H - padY).toFixed(1)} L ${points} L ${x(n - 1).toFixed(1)},${(VB_H - padY).toFixed(1)} Z`
      : "";

  const { svgRef, hoverX, setHoverX, vbXFromClientX } = useChartHover();
  function nearestIndex(vx: number): number {
    if (n <= 1) return 0;
    const t = (vx - padX) / (VB_W - padX * 2);
    return Math.min(Math.max(Math.round(t * (n - 1)), 0), n - 1);
  }
  const hoverIndex = hoverX == null ? null : nearestIndex(hoverX);
  const hoverBar = hoverIndex != null ? bars[hoverIndex] : null;

  const dayPos = series.day_change_pct >= 0;
  const periodPos = series.period_change_pct >= 0;

  function onKeyDown(e: ReactKeyboardEvent<HTMLDivElement>) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect();
    }
  }

  return (
    <div className="vt-panel" role="button" tabIndex={0} onClick={onSelect} onKeyDown={onKeyDown}>
      {removable && (
        <button
          type="button"
          className="vt-panel-remove"
          aria-label={`${series.ticker}を値動きボードから削除`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove?.();
          }}
        >
          ×
        </button>
      )}
      <div className="vt-panel-head">
        <span className="vt-panel-code">{series.ticker}</span>
        <span className={`vt-panel-change-badge ${dayPos ? "vt-pos-bg" : "vt-neg-bg"}`}>
          {formatPct(series.day_change_pct, 2)}
        </span>
      </div>
      <span className="vt-panel-name">{series.name}</span>
      <span className="vt-panel-price">{formatYen(series.last_close)}</span>
      <div className="vt-mini-chart-wrap">
        <svg ref={svgRef} viewBox={`0 0 ${VB_W} ${VB_H}`} style={{ width: "100%", height: "72px", display: "block" }}>
          {areaPath && <path d={areaPath} fill={areaColor} opacity={0.55} stroke="none" />}
          {points && <polyline points={points} fill="none" stroke={strokeColor} strokeWidth={2} />}
          {n > 0 && (
            <>
              <text x={2} y={11} fontSize="9" fill="var(--muted)">
                {formatManCompact(maxV, manDecimalsForStep(maxV - minV))}
              </text>
              <text x={2} y={VB_H - 3} fontSize="9" fill="var(--muted)">
                {formatManCompact(minV, manDecimalsForStep(maxV - minV))}
              </text>
            </>
          )}
          {hoverIndex != null && (
            <line x1={x(hoverIndex)} x2={x(hoverIndex)} y1={0} y2={VB_H} stroke="var(--muted)" strokeWidth={1} strokeDasharray="2 2" />
          )}
          {hoverIndex != null && hoverBar && (
            <circle cx={x(hoverIndex)} cy={y(hoverBar.close)} r={3} fill={strokeColor} stroke="white" strokeWidth={1} />
          )}
          {n > 0 && (
            <rect
              x={0}
              y={0}
              width={VB_W}
              height={VB_H}
              fill="transparent"
              onMouseMove={(e) => {
                const vx = vbXFromClientX(e.clientX, VB_W);
                if (vx != null) setHoverX(vx);
              }}
              onMouseLeave={() => setHoverX(null)}
              onTouchStart={(e) => {
                const t = e.touches[0];
                if (t) {
                  const vx = vbXFromClientX(t.clientX, VB_W);
                  if (vx != null) setHoverX(vx);
                }
              }}
              onTouchMove={(e) => {
                const t = e.touches[0];
                if (t) {
                  const vx = vbXFromClientX(t.clientX, VB_W);
                  if (vx != null) setHoverX(vx);
                }
              }}
              onTouchEnd={() => setHoverX(null)}
            />
          )}
        </svg>
        {hoverIndex != null && hoverBar && (
          <div className="vt-tooltip vt-mini-tooltip" style={{ left: `${(x(hoverIndex) / VB_W) * 100}%` }}>
            <b>{formatDateShort(hoverBar.date)}</b>
            <div>{formatYen(hoverBar.close)}</div>
          </div>
        )}
      </div>
      <span className={`vt-panel-period ${periodPos ? "vt-pos" : "vt-neg"}`}>期間 {formatPct(series.period_change_pct, 2)}</span>
    </div>
  );
}

// ---- main view -----------------------------------------------------------

export function VirtualTradeView() {
  const [portfolio, setPortfolio] = useState<PortfolioBase | null>(null);
  const [aiPortfolio, setAiPortfolio] = useState<AiPortfolio | null>(null);
  const [performance, setPerformance] = useState<PerformanceResp | null>(null);
  const [aiPerformance, setAiPerformance] = useState<PerformanceResp | null>(null);
  const [history, setHistory] = useState<HistoryResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // order form
  const [tickerInput, setTickerInput] = useState("");
  const [quote, setQuote] = useState<QuoteOk | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [shares, setShares] = useState(100);
  const [orderPending, setOrderPending] = useState(false);
  const [orderMessage, setOrderMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const orderFormRef = useRef<HTMLDivElement | null>(null);

  // reset
  const [resetArmed, setResetArmed] = useState(false);
  const [resetPending, setResetPending] = useState(false);

  // AI autopilot controls
  const [presetPending, setPresetPending] = useState(false);
  const [autoPending, setAutoPending] = useState(false);
  const [runPending, setRunPending] = useState(false);
  const [runSummary, setRunSummary] = useState<string | null>(null);

  // 値動き board
  const [watchTickers, setWatchTickers] = useState<string[]>(() => loadWatchTickers());
  const [watchInput, setWatchInput] = useState("");
  const [barsDays, setBarsDays] = useState(22);
  const [bars, setBars] = useState<BarsResp | null>(null);
  const [barsLoading, setBarsLoading] = useState(false);
  const [barsError, setBarsError] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(WATCH_TICKERS_KEY, JSON.stringify(watchTickers));
    } catch {
      // localStorage unavailable: nothing to do.
    }
  }, [watchTickers]);

  async function refreshAll() {
    setLoading(true);
    setLoadError(null);
    try {
      // Fetching the AI's own portfolio is what makes it trade (lazy
      // catch-up tick), so it must resolve before the rest so the curves
      // below include any trades it just made.
      const aiPort = await api<AiPortfolio>("/api/vtrade/ai/portfolio");
      setAiPortfolio(aiPort);
      const [p, perf, aiPerf, hist] = await Promise.all([
        api<PortfolioBase>("/api/vtrade/portfolio"),
        api<PerformanceResp>("/api/vtrade/performance"),
        api<PerformanceResp>("/api/vtrade/ai/performance"),
        api<HistoryResp>("/api/vtrade/history"),
      ]);
      setPortfolio(p);
      setPerformance(perf);
      setAiPerformance(aiPerf);
      setHistory(hist);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const holdingTickers = (portfolio?.positions ?? []).map((p) => p.ticker);
  const aiHoldingTickers = (aiPortfolio?.positions ?? []).map((p) => p.ticker);
  const effectiveTickers = useMemo(
    () => Array.from(new Set([...holdingTickers, ...aiHoldingTickers, ...watchTickers])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [portfolio, aiPortfolio, watchTickers],
  );
  const effectiveTickersKey = effectiveTickers.join(",");

  useEffect(() => {
    if (effectiveTickers.length === 0) {
      setBars(null);
      setBarsError(null);
      return;
    }
    let cancelled = false;
    setBarsLoading(true);
    setBarsError(null);
    api<BarsResp>("/api/vtrade/bars", { tickers: effectiveTickers, days: barsDays })
      .then((res) => {
        if (!cancelled) setBars(res);
      })
      .catch((err) => {
        if (!cancelled) setBarsError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setBarsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveTickersKey, barsDays]);

  async function handleQuote(codeArg?: string) {
    const code = (codeArg ?? tickerInput).trim().toUpperCase();
    if (!code) return;
    setTickerInput(code);
    setQuoteLoading(true);
    setQuoteError(null);
    setOrderMessage(null);
    try {
      const res = await api<QuoteResp>("/api/vtrade/quote", { ticker: code });
      if (res.ok) {
        setQuote(res);
        setQuoteError(null);
      } else {
        setQuote(null);
        setQuoteError(res.message);
      }
    } catch (err) {
      setQuote(null);
      setQuoteError(err instanceof Error ? err.message : String(err));
    } finally {
      setQuoteLoading(false);
    }
  }

  function prefillSell(pos: Position) {
    setSide("sell");
    setShares(pos.shares);
    setTickerInput(pos.ticker);
    void handleQuote(pos.ticker);
    orderFormRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function prefillFromPanel(ticker: string) {
    setTickerInput(ticker);
    void handleQuote(ticker);
    orderFormRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function submitOrder() {
    const code = tickerInput.trim().toUpperCase();
    if (!code || shares < 100) return;
    setOrderPending(true);
    setOrderMessage(null);
    try {
      const res = await api<OrderResp>("/api/vtrade/order", { ticker: code, side, shares });
      if (res.ok) {
        const f = res.fill;
        setOrderMessage({
          kind: "ok",
          text: `約定: ${f.ticker} ${f.name} ${f.shares.toLocaleString("ja-JP")}株 @${formatYen(f.price)} 受渡 ${f.settlement_date}`,
        });
        setQuote(null);
        setShares(100);
        await refreshAll();
      } else {
        setOrderMessage({ kind: "error", text: res.message });
      }
    } catch (err) {
      setOrderMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setOrderPending(false);
    }
  }

  async function performReset() {
    setResetPending(true);
    try {
      await api<ResetResp>("/api/vtrade/reset", { confirm: true });
      setResetArmed(false);
      setOrderMessage(null);
      setQuote(null);
      setRunSummary(null);
      await refreshAll();
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setResetPending(false);
    }
  }

  async function changePreset(preset: "balanced" | "defensive" | "momentum") {
    setPresetPending(true);
    try {
      await api<AutopilotConfigResp>("/api/vtrade/autopilot/config", { preset });
      await refreshAll();
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setPresetPending(false);
    }
  }

  async function toggleAuto() {
    const next = !(aiPortfolio?.auto ?? true);
    setAutoPending(true);
    try {
      await api<AutopilotConfigResp>("/api/vtrade/autopilot/config", { auto: next });
      await refreshAll();
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setAutoPending(false);
    }
  }

  async function runAutopilotNow() {
    setRunPending(true);
    setRunSummary(null);
    try {
      const res = await api<AutopilotRunResp>("/api/vtrade/autopilot/run", {});
      if (!res.ran || res.ran.length === 0) {
        setRunSummary("本日分は実行済みです。");
      } else {
        setRunSummary(res.ran.map((r) => `${formatDateShort(r.date)}: 買い${r.buys}件・売り${r.sells}件`).join(" / "));
      }
      await refreshAll();
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunPending(false);
    }
  }

  function addWatchTicker() {
    const code = watchInput.trim().toUpperCase();
    if (!code) return;
    setWatchTickers((prev) => (prev.includes(code) ? prev : [...prev, code]));
    setWatchInput("");
  }

  function removeWatchTicker(code: string) {
    setWatchTickers((prev) => prev.filter((t) => t !== code));
  }

  const quoteMatchesTicker = quote != null && quote.ticker === tickerInput.trim().toUpperCase();
  const estCost = quoteMatchesTicker && quote ? quote.price * shares : null;

  const bothEmpty = (portfolio?.trade_count ?? 0) === 0 && (aiPortfolio?.trade_count ?? 0) === 0;
  const trades = (history?.trades ?? []).slice(0, 50);

  return (
    <section className="screen vtrade-screen">
      <div className="screen-head">
        <div>
          <h2>仮想取引</h2>
          <p>
            初期資金1,000万円の学習用シミュレーションです。実際の資金は動きません。
            {portfolio?.as_of ? `${portfolio.as_of}現在の株価（日次終値）で評価しています。多少古い場合があります。` : ""}
          </p>
        </div>
      </div>

      {loadError && (
        <div className="notice vt-error-banner">
          <span>読み込みに失敗しました: {loadError}</span>
          <div className="actions">
            <button type="button" className="table-action" onClick={() => void refreshAll()}>
              再試行
            </button>
            <button type="button" className="table-action" onClick={() => setLoadError(null)}>
              閉じる
            </button>
          </div>
        </div>
      )}

      {loading && !portfolio && <p className="status">読み込み中...</p>}

      {portfolio && (
        <div className="kpi-grid">
          <div className="kpi">
            <span>総資産</span>
            <b>{formatYen(portfolio.equity)}</b>
          </div>
          <div className="kpi">
            <span>現金</span>
            <b>{formatYen(portfolio.cash)}</b>
          </div>
          <div className="kpi">
            <span>評価損益</span>
            <b className={pnlClass(portfolio.unrealized_pnl)}>{formatYen(portfolio.unrealized_pnl)}</b>
          </div>
          <div className="kpi">
            <span>実現損益</span>
            <b className={pnlClass(portfolio.realized_pnl)}>{formatYen(portfolio.realized_pnl)}</b>
          </div>
          <div className="kpi">
            <span>損益率</span>
            <b className={pnlClass(portfolio.total_return_pct)}>{formatPct(portfolio.total_return_pct)}</b>
          </div>
        </div>
      )}

      <div className="detail-section">
        <h4>運用実績</h4>
        {bothEmpty ? (
          <div className="vt-onboarding">
            <strong>仮想資金1,000万円からスタート</strong>
            <p>下の注文フォームから最初の仮想取引をしてみましょう。AIも自動で運用を開始します。</p>
          </div>
        ) : (
          <>
            {performance && aiPerformance && portfolio && aiPortfolio && (
              <PerformanceSummaryTable
                rows={[
                  {
                    label: "あなた",
                    equity: portfolio.equity,
                    totalReturnPct: portfolio.total_return_pct,
                    realizedPnl: portfolio.realized_pnl,
                    unrealizedPnl: portfolio.unrealized_pnl,
                    maxDrawdown: performance.max_drawdown,
                    tradeCount: portfolio.trade_count,
                    winRate: computeWinRate(history?.trades ?? [], "user"),
                  },
                  {
                    label: "AI",
                    equity: aiPortfolio.equity,
                    totalReturnPct: aiPortfolio.total_return_pct,
                    realizedPnl: aiPortfolio.realized_pnl,
                    unrealizedPnl: aiPortfolio.unrealized_pnl,
                    maxDrawdown: aiPerformance.max_drawdown,
                    tradeCount: aiPortfolio.trade_count,
                    winRate: computeWinRate(history?.trades ?? [], "ai"),
                  },
                ]}
              />
            )}
            {performance && aiPerformance && portfolio && (
              <EquityChart userCurve={performance.curve} aiCurve={aiPerformance.curve} initialCash={portfolio.initial_cash} />
            )}
          </>
        )}
      </div>

      <div className="job-card vt-ai-card">
        <div className="vt-board-head">
          <b>AI自動運用</b>
          <div className="vt-side-toggle vt-preset-toggle">
            {PRESET_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={presetPending}
                className={aiPortfolio?.preset === opt.value ? "active" : ""}
                onClick={() => void changePreset(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button type="button" className="table-action" disabled={autoPending} onClick={() => void toggleAuto()}>
            自動: {aiPortfolio?.auto ?? true ? "ON" : "OFF"}
          </button>
          <button type="button" className="primary" disabled={runPending} onClick={() => void runAutopilotNow()}>
            {runPending ? "実行中..." : "今すぐ運用実行"}
          </button>
        </div>
        {runSummary && <p className="vt-confirm-ok">{runSummary}</p>}
        {aiPortfolio && (
          <div className="kpi-grid vt-ai-kpi-grid">
            <div className="kpi">
              <span>AI総資産</span>
              <b>{formatYen(aiPortfolio.equity)}</b>
            </div>
            <div className="kpi">
              <span>損益率</span>
              <b className={pnlClass(aiPortfolio.total_return_pct)}>{formatPct(aiPortfolio.total_return_pct)}</b>
            </div>
            <div className="kpi">
              <span>実現損益</span>
              <b className={pnlClass(aiPortfolio.realized_pnl)}>{formatYen(aiPortfolio.realized_pnl)}</b>
            </div>
            <div className="kpi">
              <span>最終運用日</span>
              <b>{aiPortfolio.last_run_date ?? "—"}</b>
            </div>
          </div>
        )}
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>コード</th>
                <th>銘柄名</th>
                <th style={{ textAlign: "right" }}>株数</th>
                <th style={{ textAlign: "right" }}>平均取得単価</th>
                <th style={{ textAlign: "right" }}>現在値</th>
                <th style={{ textAlign: "right" }}>評価額</th>
                <th style={{ textAlign: "right" }}>評価損益</th>
              </tr>
            </thead>
            <tbody>
              {(aiPortfolio?.positions ?? []).length === 0 ? (
                <tr>
                  <td colSpan={7} className="vt-empty">
                    AIはまだ銘柄を保有していません。
                  </td>
                </tr>
              ) : (
                (aiPortfolio?.positions ?? []).map((pos) => (
                  <tr key={pos.ticker}>
                    <td>{pos.ticker}</td>
                    <td>{pos.name}</td>
                    <td style={{ textAlign: "right" }}>{pos.shares.toLocaleString("ja-JP")}</td>
                    <td style={{ textAlign: "right" }}>{formatYen(pos.avg_cost)}</td>
                    <td style={{ textAlign: "right" }}>{formatYen(pos.price)}</td>
                    <td style={{ textAlign: "right" }}>{formatYen(pos.value)}</td>
                    <td style={{ textAlign: "right" }} className={pnlClass(pos.unrealized_pnl)}>
                      {formatYen(pos.unrealized_pnl)}（{formatPct(pos.unrealized_pnl_pct)}）
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <p className="vt-disclaimer">
          銘柄選択は流動性フィルタ＋戦略プリセット＋業種分散ルールで全自動。仮想売買のみで実際の注文は行いません。
        </p>
      </div>

      <div className="detail-section">
        <h4>値動き</h4>
        <div className="vt-board-head">
          <div className="vt-side-toggle vt-period-toggle">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                type="button"
                className={barsDays === opt.days ? "active" : ""}
                onClick={() => setBarsDays(opt.days)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="vt-watch-add">
            <input
              value={watchInput}
              placeholder="銘柄コード追加"
              onChange={(e) => setWatchInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addWatchTicker();
              }}
            />
            <button type="button" className="table-action" onClick={addWatchTicker}>
              追加
            </button>
          </div>
        </div>
        {barsError && <p className="status error">{barsError}</p>}
        {effectiveTickers.length === 0 ? (
          <div className="vt-onboarding">
            <p>保有銘柄がありません。銘柄コードを追加して値動きを確認しましょう。</p>
          </div>
        ) : (
          <>
            {barsLoading && !bars && <p className="status">読み込み中...</p>}
            {bars && bars.missing.length > 0 && (
              <p className="notice">取得できなかった銘柄: {bars.missing.join(", ")}</p>
            )}
            <div className="vt-panel-grid">
              {(bars?.series ?? []).map((s) => (
                <PriceMiniChart
                  key={s.ticker}
                  series={s}
                  onSelect={() => prefillFromPanel(s.ticker)}
                  onRemove={() => removeWatchTicker(s.ticker)}
                  removable={watchTickers.includes(s.ticker)}
                />
              ))}
            </div>
          </>
        )}
      </div>

      <div className="job-card vt-order-card" ref={orderFormRef}>
        <b>注文フォーム</b>
        <div className="form-grid tight">
          <div className="field">
            <span>銘柄コード</span>
            <input
              value={tickerInput}
              placeholder="7203"
              maxLength={6}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleQuote();
              }}
            />
          </div>
          <div className="field">
            <span>&nbsp;</span>
            <button type="button" disabled={quoteLoading || !tickerInput.trim()} onClick={() => void handleQuote()}>
              {quoteLoading ? "確認中..." : "株価を確認"}
            </button>
          </div>
        </div>

        {quote && quoteMatchesTicker && (
          <div className="vt-order-summary">
            <div>
              <b>{quote.name}</b> <span className="muted">{quote.sector}</span>
            </div>
            <div>
              株価 {formatYen(quote.price)}（{quote.date} 終値）・単元 {quote.lot}株
            </div>
          </div>
        )}
        {quoteError && <p className="vt-confirm-error">{quoteError}</p>}

        <div className="vt-side-toggle">
          <button type="button" className={side === "buy" ? "active buy" : "buy"} onClick={() => setSide("buy")}>
            買い
          </button>
          <button type="button" className={side === "sell" ? "active sell" : "sell"} onClick={() => setSide("sell")}>
            売り
          </button>
        </div>

        <div className="form-grid tight">
          <div className="field">
            <span>株数</span>
            <input
              type="number"
              min={100}
              step={100}
              value={shares}
              onChange={(e) => {
                const num = Number(e.target.value);
                setShares(Number.isFinite(num) ? Math.max(0, Math.round(num)) : 0);
              }}
              onBlur={() => setShares((prev) => Math.max(100, Math.round(prev / 100) * 100))}
            />
          </div>
          <div className="field">
            <span>概算金額</span>
            <p className="vt-order-summary">{estCost != null ? formatYen(estCost) : "—"}</p>
          </div>
        </div>

        <div className="actions">
          <button
            type="button"
            className="primary"
            disabled={orderPending || !quoteMatchesTicker || shares < 100}
            onClick={() => void submitOrder()}
          >
            {orderPending ? "発注中..." : side === "buy" ? "買い注文" : "売り注文"}
          </button>
        </div>

        {orderMessage && (
          <p className={orderMessage.kind === "ok" ? "vt-confirm-ok" : "vt-confirm-error"}>{orderMessage.text}</p>
        )}
        {portfolio?.disclaimer && <p className="vt-disclaimer">{portfolio.disclaimer}</p>}
      </div>

      <div className="detail-section">
        <h4>保有銘柄</h4>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>コード</th>
                <th>銘柄名</th>
                <th style={{ textAlign: "right" }}>株数</th>
                <th style={{ textAlign: "right" }}>平均取得単価</th>
                <th style={{ textAlign: "right" }}>現在値</th>
                <th style={{ textAlign: "right" }}>評価額</th>
                <th style={{ textAlign: "right" }}>評価損益</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(portfolio?.positions ?? []).length === 0 ? (
                <tr>
                  <td colSpan={8} className="vt-empty">
                    保有銘柄はありません。上のフォームから最初の注文を出してみましょう。
                  </td>
                </tr>
              ) : (
                (portfolio?.positions ?? []).map((pos) => (
                  <tr key={pos.ticker}>
                    <td>{pos.ticker}</td>
                    <td>{pos.name}</td>
                    <td style={{ textAlign: "right" }}>{pos.shares.toLocaleString("ja-JP")}</td>
                    <td style={{ textAlign: "right" }}>{formatYen(pos.avg_cost)}</td>
                    <td style={{ textAlign: "right" }}>{formatYen(pos.price)}</td>
                    <td style={{ textAlign: "right" }}>{formatYen(pos.value)}</td>
                    <td style={{ textAlign: "right" }} className={pnlClass(pos.unrealized_pnl)}>
                      {formatYen(pos.unrealized_pnl)}（{formatPct(pos.unrealized_pnl_pct)}）
                    </td>
                    <td>
                      <button type="button" className="table-action" onClick={() => prefillSell(pos)}>
                        売る
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="detail-section">
        <h4>取引履歴</h4>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>日付</th>
                <th>銘柄</th>
                <th>売買</th>
                <th style={{ textAlign: "right" }}>株数</th>
                <th style={{ textAlign: "right" }}>約定単価</th>
                <th style={{ textAlign: "right" }}>実現損益</th>
                <th style={{ textAlign: "right" }}>税</th>
                <th>区分</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={8} className="vt-empty">
                    取引履歴はありません。
                  </td>
                </tr>
              ) : (
                trades.map((t) => {
                  const account = t.account ?? t.source ?? "user";
                  return (
                    <tr key={t.id}>
                      <td>{t.trade_date}</td>
                      <td>
                        {t.ticker} <span className="muted">{t.name}</span>
                      </td>
                      <td>{t.side === "buy" ? "買い" : "売り"}</td>
                      <td style={{ textAlign: "right" }}>{t.shares.toLocaleString("ja-JP")}</td>
                      <td style={{ textAlign: "right" }}>{formatYen(t.price)}</td>
                      <td style={{ textAlign: "right" }} className={t.realized_pnl != null ? pnlClass(t.realized_pnl) : ""}>
                        {t.realized_pnl != null ? formatYen(t.realized_pnl) : "-"}
                      </td>
                      <td style={{ textAlign: "right" }}>{t.tax_delta ? formatYen(t.tax_delta) : "-"}</td>
                      <td>
                        <span className={`vt-badge ${account === "ai" ? "ai" : ""}`}>{account === "ai" ? "AI" : "手動"}</span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="vt-reset-row">
        {!resetArmed ? (
          <button type="button" className="vt-reset-btn" onClick={() => setResetArmed(true)}>
            初期化
          </button>
        ) : (
          <div className="vt-reset-confirm">
            <span>本当にリセット？取引履歴がすべて消えます</span>
            <button type="button" className="primary" disabled={resetPending} onClick={() => void performReset()}>
              {resetPending ? "実行中..." : "実行"}
            </button>
            <button type="button" disabled={resetPending} onClick={() => setResetArmed(false)}>
              キャンセル
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
