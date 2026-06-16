import { useState } from "react";
import type { ReactNode } from "react";

import { api } from "./api";

// Self-contained so the Yahoo!ファイナンス panel lives outside the App.tsx monolith.
type Json = Record<string, any>;

type MarketDataPanelProps = {
  // Apply imported/looked-up prices (ticker -> price) to the caller's holdings.
  onApplyPrices?: (prices: Record<string, number>) => void;
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function asPriceMap(prices: unknown): Record<string, number> {
  const out: Record<string, number> = {};
  if (prices && typeof prices === "object") {
    for (const [ticker, value] of Object.entries(prices as Record<string, unknown>)) {
      const num = Number(value);
      if (Number.isFinite(num) && num > 0) out[ticker] = num;
    }
  }
  return out;
}

// --- File inbox: a manually exported CSV, no scraping (the 7:00 auto-check path) ---
function InboxSection({ onApplyPrices }: MarketDataPanelProps) {
  const [status, setStatus] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const check = async () => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await api<Json>("/api/market/inbox", {}));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const apply = () => {
    const prices = asPriceMap(status?.prices);
    if (onApplyPrices) onApplyPrices(prices);
  };

  const present = status?.status === "present";
  const tickers = Number(status?.tickers ?? 0);

  return (
    <div className="subpanel">
      <div className="section-head">
        <h4>ファイルから反映</h4>
        {status && (
          <span className={`badge ${present ? "" : "warn"}`}>
            状態: {present ? `present（${tickers}銘柄）` : "missing"}
          </span>
        )}
      </div>
      <p className="hint">
        Yahoo!ファイナンス等で確認した個人利用のCSVを下記パスに置くと、ここからも毎日7時の自動チェックでも同じ取り込みが使えます（スクレイピング不要・429回避）。
      </p>
      {status?.path && <p className="mono">入力: {String(status.path)}</p>}
      <div className="form">
        <button onClick={() => void check()} disabled={busy}>
          {busy ? "確認中…" : "状態を確認"}
        </button>
        <button className="primary" onClick={apply} disabled={!present || tickers === 0}>
          ファイルから反映
        </button>
      </div>
      {error && <p className="status error">確認に失敗しました: {error}</p>}
    </div>
  );
}

// --- Live scrape: daily OHLCV or today's minute bars from Yahoo!ファイナンス ---
function ScrapeSection() {
  const [tickers, setTickers] = useState("");
  const [mode, setMode] = useState<"ohlcv" | "intraday">("ohlcv");
  const [range, setRange] = useState("1mo");
  const [viewTicker, setViewTicker] = useState("");
  const [data, setData] = useState<Json | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tickerList = tickers
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  const seriesKey = mode === "ohlcv" ? "ohlcv" : "intraday";

  const fetchMarket = async () => {
    setLoading(true);
    setError(null);
    try {
      const path = mode === "ohlcv" ? "/api/market/ohlcv" : "/api/market/intraday";
      const body: Json = { tickers: tickerList };
      if (mode === "ohlcv") body.range = range;
      const r = await api<Json>(path, body);
      setData(r);
      const fetched = (r?.[seriesKey] ?? {}) as Record<string, unknown>;
      setViewTicker(Object.keys(fetched)[0] ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const series = (data?.[seriesKey] ?? {}) as Record<string, Array<Record<string, unknown>>>;
  const counts = (data?.counts ?? {}) as Record<string, number>;
  const notes = (data?.notes ?? {}) as Record<string, string>;
  const tickerKeys = Object.keys(series);
  const rows: Array<Record<string, unknown>> = viewTicker ? series[viewTicker] ?? [] : [];
  const cols =
    mode === "ohlcv"
      ? ["date", "open", "high", "low", "close", "volume"]
      : ["time", "close", "volume"];

  return (
    <div className="subpanel">
      <div className="section-head">
        <h4>ライブ取得</h4>
        <span className="badge">{mode === "ohlcv" ? "日足OHLCV" : "当日分足"}</span>
      </div>
      <p className="hint">
        日足OHLCVまたは当日分足を取得します。分足はその日のうちのみ取得可・個人利用限定で、robotsとレート制限を尊重します。
      </p>
      <div className="form">
        <Field label="銘柄（カンマ区切り・最大50）">
          <input
            value={tickers}
            onChange={(e) => setTickers(e.target.value)}
            placeholder="8306,7203,2914"
          />
        </Field>
        <Field label="種別">
          <select value={mode} onChange={(e) => setMode(e.target.value as "ohlcv" | "intraday")}>
            <option value="ohlcv">日足 OHLCV</option>
            <option value="intraday">当日分足</option>
          </select>
        </Field>
        {mode === "ohlcv" && (
          <Field label="期間">
            <select value={range} onChange={(e) => setRange(e.target.value)}>
              <option value="5d">5日</option>
              <option value="1mo">1ヶ月</option>
              <option value="3mo">3ヶ月</option>
              <option value="1y">1年</option>
            </select>
          </Field>
        )}
        <button
          className="primary"
          onClick={() => void fetchMarket()}
          disabled={loading || tickerList.length === 0}
        >
          {loading ? "取得中…" : "取得"}
        </button>
      </div>

      {error && <p className="status error">取得に失敗しました: {error}</p>}

      {data && !loading && (
        <div className="market-result">
          <p className="status">
            取得件数:{" "}
            {tickerKeys.length > 0
              ? tickerKeys.map((t) => `${t} ${counts[t] ?? 0}件`).join(" / ")
              : "（対象なし）"}
          </p>
          {Object.keys(notes).length > 0 && (
            <p className="callout">
              取得できなかった銘柄:{" "}
              {Object.entries(notes)
                .map(([t, e]) => `${t} (${e})`)
                .join(", ")}
            </p>
          )}
          {tickerKeys.length > 1 && (
            <Field label="表示する銘柄">
              <select value={viewTicker} onChange={(e) => setViewTicker(e.target.value)}>
                {tickerKeys.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {rows.length === 0 ? (
            <p className="hint">
              表示できるデータがありません。分足は当日の取引終了後にのみ取得でき、robotsやレート制限で空になる場合があります。
            </p>
          ) : (
            <>
              <table className="grid">
                <thead>
                  <tr>
                    {cols.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 100).map((bar, i) => (
                    <tr key={i}>
                      {cols.map((c) => (
                        <td key={c} className="mono">
                          {String(bar[c] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length > 100 && <p className="hint">先頭100件を表示（全 {rows.length} 件）。</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// --- Fundamentals: PER / PBR / yield / EPS / DPS / market cap (one batched call) ---
const FIN_COLS: Array<[string, string]> = [
  ["name", "名称"],
  ["price", "株価"],
  ["per", "PER"],
  ["pbr", "PBR"],
  ["dividend_yield", "配当利回り"],
  ["eps", "EPS"],
  ["dps", "DPS"],
  ["market_cap", "時価総額"],
];

function fmtMetric(key: string, value: unknown): string {
  if (value == null || value === "") return "";
  if (key === "dividend_yield") {
    const n = Number(value);
    return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : String(value);
  }
  if (key === "market_cap") {
    const n = Number(value);
    return Number.isFinite(n) ? `${(n / 1e8).toLocaleString()}億円` : String(value);
  }
  return String(value);
}

function FinancialsSection() {
  const [tickers, setTickers] = useState("");
  const [data, setData] = useState<Json | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tickerList = tickers
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);

  const fetchFinancials = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api<Json>("/api/market/financials", { tickers: tickerList }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const financials = (data?.financials ?? {}) as Record<string, Record<string, unknown>>;
  const notes = (data?.notes ?? {}) as Record<string, string>;
  const rows = Object.entries(financials);

  return (
    <div className="subpanel">
      <div className="section-head">
        <h4>財務情報</h4>
        <span className="badge">PER/PBR/利回り</span>
      </div>
      <p className="hint">
        Yahoo!ファイナンスの株価指標（PER・PBR・配当利回り・EPS・DPS・時価総額）を取得します。EDINETの財務数値を補完する市場指標です。
      </p>
      <div className="form">
        <Field label="銘柄（カンマ区切り・最大50）">
          <input
            value={tickers}
            onChange={(e) => setTickers(e.target.value)}
            placeholder="8306,7203,2914"
          />
        </Field>
        <button
          className="primary"
          onClick={() => void fetchFinancials()}
          disabled={loading || tickerList.length === 0}
        >
          {loading ? "取得中…" : "取得"}
        </button>
      </div>

      {error && <p className="status error">取得に失敗しました: {error}</p>}

      {data && !loading && (
        <>
          {Object.keys(notes).length > 0 && (
            <p className="callout">
              取得できなかった銘柄: {Object.keys(notes).join(", ")}
            </p>
          )}
          {rows.length === 0 ? (
            <p className="hint">表示できる財務情報がありません。</p>
          ) : (
            <table className="grid">
              <thead>
                <tr>
                  <th>ticker</th>
                  {FIN_COLS.map(([, label]) => (
                    <th key={label}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(([ticker, m]) => (
                  <tr key={ticker}>
                    <td className="mono">{ticker}</td>
                    {FIN_COLS.map(([key]) => (
                      <td key={key} className={key === "name" ? "" : "mono"}>
                        {fmtMetric(key, m[key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

export function MarketDataPanel({ onApplyPrices }: MarketDataPanelProps) {
  return (
    <section className="tool-section">
      <div className="section-head">
        <h3>市場データ（Yahoo!ファイナンス）</h3>
      </div>
      <InboxSection onApplyPrices={onApplyPrices} />
      <ScrapeSection />
      <FinancialsSection />
    </section>
  );
}
