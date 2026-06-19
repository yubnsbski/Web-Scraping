import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { api } from "./api";

type Json = Record<string, unknown>;
type RefreshMode = "auto" | "custom";
type DatasetStatus = {
  key?: unknown;
  label?: unknown;
  status?: unknown;
  path?: unknown;
  row_count?: unknown;
  ticker_count?: unknown;
  modified_at?: unknown;
};

const AUTO_ON_LOAD_KEY = "investment_assistant.yahoo.auto_on_load.v1";

function readAutoOnLoad(): boolean {
  try {
    return window.localStorage.getItem(AUTO_ON_LOAD_KEY) === "true";
  } catch {
    return false;
  }
}

function writeAutoOnLoad(value: boolean): void {
  try {
    window.localStorage.setItem(AUTO_ON_LOAD_KEY, String(value));
  } catch {
    // Browser storage is optional; the current session still works.
  }
}

function text(value: unknown, fallback = "-"): string {
  const rendered = String(value ?? "").trim();
  return rendered || fallback;
}

function numberText(value: unknown): string {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("ja-JP") : "-";
}

function rows(value: unknown): Json[] {
  return Array.isArray(value)
    ? value.filter((item): item is Json => Boolean(item) && typeof item === "object")
    : [];
}

function asRecord(value: unknown): Json {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : {};
}

function splitTickers(value: string): string[] {
  return value
    .split(/[\s,、，]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function dateTime(value: unknown): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "-";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString("ja-JP");
}

export function YahooMarketPanel() {
  const [mode, setMode] = useState<RefreshMode>("auto");
  const [scope, setScope] = useState("nikkei225");
  const [tickers, setTickers] = useState("7203,8306,9432");
  const [maxTickers, setMaxTickers] = useState(20);
  const [range, setRange] = useState("1mo");
  const [interval, setInterval] = useState("1d");
  const [fetchOhlcv, setFetchOhlcv] = useState(true);
  const [fetchFundamentals, setFetchFundamentals] = useState(true);
  const [dailyBarsPath, setDailyBarsPath] = useState("local_docs/market/daily_bars.csv");
  const [currentPricesPath, setCurrentPricesPath] = useState(
    "local_docs/market/current_prices.csv",
  );
  const [fundamentalsPath, setFundamentalsPath] = useState(
    "local_docs/market/yahoo_financials.csv",
  );
  const [autoOnLoad, setAutoOnLoad] = useState(readAutoOnLoad);
  const [loading, setLoading] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Json | null>(null);
  const [status, setStatus] = useState<Json | null>(null);
  const autoStarted = useRef(false);

  const tickerList = useMemo(() => splitTickers(tickers), [tickers]);

  async function loadStatus(): Promise<void> {
    setStatusLoading(true);
    try {
      const next = await api<Json>("/api/market/yahoo/status", {
        daily_bars_path: dailyBarsPath,
        current_prices_path: currentPricesPath,
        fundamentals_path: fundamentalsPath,
      });
      setStatus(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setStatusLoading(false);
    }
  }

  async function refresh(): Promise<void> {
    if (!fetchOhlcv && !fetchFundamentals) {
      setError("四本値・出来高または市場財務指標を1つ以上選択してください。");
      return;
    }
    if (mode === "custom" && tickerList.length === 0) {
      setError("任意取得では証券コードを入力してください。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const next = await api<Json>("/api/market/yahoo/refresh", {
        mode,
        scope,
        tickers: tickerList,
        max_tickers: maxTickers,
        range,
        interval,
        fetch_ohlcv: fetchOhlcv,
        fetch_fundamentals: fetchFundamentals,
        daily_bars_path: dailyBarsPath,
        current_prices_path: currentPricesPath,
        fundamentals_path: fundamentalsPath,
      });
      setResult(next);
      await loadStatus();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStatus();
  }, []);

  useEffect(() => {
    writeAutoOnLoad(autoOnLoad);
    if (!autoOnLoad || mode !== "auto" || autoStarted.current) return;
    autoStarted.current = true;
    void refresh();
  }, [autoOnLoad, mode]);

  const datasets = rows(status?.datasets) as DatasetStatus[];
  const latestBars = rows(result?.latest_bars);
  const fundamentals = rows(result?.fundamentals);
  const saved = asRecord(result?.saved);
  const selection = asRecord(result?.selection);
  const errors = asRecord(result?.errors);
  const errorEntries = Object.entries(errors);
  const policy = asRecord(result?.policy ?? status?.policy);

  return (
    <div className="app">
      <section className="tool-section" aria-label="Yahoo!ファイナンス市場データ更新">
        <div className="section-head">
          <div>
            <p className="eyebrow">Yahoo!ファイナンス</p>
            <h2>株価四本値・出来高 / 市場財務指標</h2>
            <p className="hint">
              自動取得は市場区分・日経225・財務取得済み銘柄から対象を解決します。任意取得では証券コード、期間、保存先を変更できます。
            </p>
          </div>
          <span className="badge">取得元を明示 / 自動売買なし</span>
        </div>

        <div className="form">
          <label className="field">
            <span>取得方法</span>
            <select
              value={mode}
              onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                setMode(event.target.value as RefreshMode)
              }
            >
              <option value="auto">自動取得</option>
              <option value="custom">任意取得</option>
            </select>
          </label>

          {mode === "auto" ? (
            <>
              <label className="field">
                <span>自動対象</span>
                <select
                  value={scope}
                  onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                    setScope(event.target.value)
                  }
                >
                  <option value="nikkei225">日経225</option>
                  <option value="prime">東証プライム</option>
                  <option value="financials">財務データあり</option>
                  <option value="all">登録済み全件</option>
                </select>
              </label>
              <label className="field">
                <span>最大銘柄数</span>
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={maxTickers}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setMaxTickers(Number(event.target.value) || 1)
                  }
                />
              </label>
            </>
          ) : (
            <label className="field">
              <span>証券コード（最大50・区切り入力）</span>
              <input
                value={tickers}
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  setTickers(event.target.value)
                }
                placeholder="7203,8306,9432"
              />
            </label>
          )}

          <label className="field">
            <span>期間</span>
            <select
              value={range}
              onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                setRange(event.target.value)
              }
            >
              <option value="5d">5日</option>
              <option value="1mo">1か月</option>
              <option value="3mo">3か月</option>
              <option value="6mo">6か月</option>
              <option value="1y">1年</option>
              <option value="2y">2年</option>
              <option value="5y">5年</option>
            </select>
          </label>

          <label className="field">
            <span>足種</span>
            <select
              value={interval}
              onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                setInterval(event.target.value)
              }
            >
              <option value="1d">日足</option>
              <option value="1wk">週足</option>
              <option value="1mo">月足</option>
            </select>
          </label>
        </div>

        <div className="form">
          <label className="field check-field">
            <input
              type="checkbox"
              checked={fetchOhlcv}
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                setFetchOhlcv(event.target.checked)
              }
            />
            <span>株価四本値・出来高</span>
          </label>
          <label className="field check-field">
            <input
              type="checkbox"
              checked={fetchFundamentals}
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                setFetchFundamentals(event.target.checked)
              }
            />
            <span>市場財務指標（PER/PBR/EPS/DPS/利回り/時価総額）</span>
          </label>
          <label className="field check-field">
            <input
              type="checkbox"
              checked={autoOnLoad}
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                setAutoOnLoad(event.target.checked)
              }
            />
            <span>画面起動時に自動取得（自動モードのみ）</span>
          </label>
        </div>

        <details className="advanced-settings">
          <summary>保存先をカスタマイズ</summary>
          <div className="form">
            <label className="field">
              <span>四本値・出来高CSV</span>
              <input
                value={dailyBarsPath}
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  setDailyBarsPath(event.target.value)
                }
              />
            </label>
            <label className="field">
              <span>現在価格CSV</span>
              <input
                value={currentPricesPath}
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  setCurrentPricesPath(event.target.value)
                }
              />
            </label>
            <label className="field">
              <span>市場財務指標CSV</span>
              <input
                value={fundamentalsPath}
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  setFundamentalsPath(event.target.value)
                }
              />
            </label>
          </div>
        </details>

        <div className="form">
          <button className="primary" onClick={() => void refresh()} disabled={loading}>
            {loading ? "取得中…" : mode === "auto" ? "自動取得を実行" : "任意取得を実行"}
          </button>
          <button onClick={() => void loadStatus()} disabled={statusLoading}>
            {statusLoading ? "確認中…" : "保存状態を確認"}
          </button>
        </div>

        {error && <p className="status error">Yahoo取得エラー: {error}</p>}

        {datasets.length > 0 && (
          <div className="data-status-grid">
            {datasets.map((dataset) => (
              <article className="guide-card data-status-card" key={text(dataset.key)}>
                <b>{text(dataset.label)}</b>
                <span className={`badge ${dataset.status === "ready" ? "ok" : "warn"}`}>
                  {text(dataset.status)}
                </span>
                <p className="mono">{text(dataset.path)}</p>
                <p className="hint">
                  {numberText(dataset.ticker_count)}銘柄 / {numberText(dataset.row_count)}件 / 更新{" "}
                  {dateTime(dataset.modified_at)}
                </p>
              </article>
            ))}
          </div>
        )}

        {result && (
          <>
            <p className="callout">
              結果: <b>{text(result.status)}</b> / 対象 {numberText(result.requested_count)}銘柄 /
              四本値 {numberText(result.ohlcv_ticker_count)}銘柄・{numberText(result.ohlcv_row_count)}件 /
              市場財務指標 {numberText(result.fundamentals_ticker_count)}銘柄
              <br />
              選択: {text(selection.scope ?? selection.mode)} / 保存: {text(saved.daily_bars_path)}, {text(saved.fundamentals_path)}
            </p>

            {latestBars.length > 0 && (
              <div className="subpanel">
                <h3>最新の株価四本値・出来高</h3>
                <table className="grid">
                  <thead>
                    <tr>
                      <th>コード</th>
                      <th>日付</th>
                      <th>始値</th>
                      <th>高値</th>
                      <th>安値</th>
                      <th>終値</th>
                      <th>出来高</th>
                      <th>履歴件数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {latestBars.slice(0, 50).map((row) => (
                      <tr key={text(row.ticker)}>
                        <td className="mono">{text(row.ticker)}</td>
                        <td>{text(row.date)}</td>
                        <td>{numberText(row.open)}</td>
                        <td>{numberText(row.high)}</td>
                        <td>{numberText(row.low)}</td>
                        <td>{numberText(row.adjusted_close ?? row.close)}</td>
                        <td>{numberText(row.volume)}</td>
                        <td>{numberText(row.bar_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {fundamentals.length > 0 && (
              <div className="subpanel">
                <h3>市場財務指標</h3>
                <table className="grid">
                  <thead>
                    <tr>
                      <th>コード</th>
                      <th>名称</th>
                      <th>価格</th>
                      <th>PER</th>
                      <th>PBR</th>
                      <th>EPS</th>
                      <th>DPS</th>
                      <th>配当利回り</th>
                      <th>時価総額</th>
                      <th>取得元</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fundamentals.slice(0, 50).map((row) => (
                      <tr key={text(row.ticker)}>
                        <td className="mono">{text(row.ticker)}</td>
                        <td>{text(row.name)}</td>
                        <td>{numberText(row.price)}</td>
                        <td>{numberText(row.per)}</td>
                        <td>{numberText(row.pbr)}</td>
                        <td>{numberText(row.eps)}</td>
                        <td>{numberText(row.dps)}</td>
                        <td>{numberText(row.dividend_yield_percent)}%</td>
                        <td>{numberText(row.market_cap)}</td>
                        <td className="mono">{text(row.source_ref)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {errorEntries.length > 0 && (
              <div className="callout warn-callout">
                <b>取得できなかった項目</b>
                <ul>
                  {errorEntries.slice(0, 50).map(([ticker, messages]) => (
                    <li key={ticker}>
                      <span className="mono">{ticker}</span>:{" "}
                      {Array.isArray(messages) ? messages.join(", ") : text(messages)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}

        <p className="hint">
          利用条件: 個人利用限定={text(policy.personal_use_only)} / robots確認={text(policy.robots_checked)} /
          レート制限={text(policy.rate_limited)} / 再配布={policy.redistribution === false ? "不可" : text(policy.redistribution)}
        </p>
      </section>
    </div>
  );
}
