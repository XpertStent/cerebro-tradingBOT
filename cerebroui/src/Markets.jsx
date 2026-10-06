import { mergeCandles, prependedCount } from "./candleData";
import useSymbolSearch from "./useSymbolSearch";
import { fetchJson } from "./fetchJson";
import { securityLabel, selectedSecurityForQuery } from "./marketSelection";
import { historyQuotaFailure, candleFailureMessage } from "./candleErrors";
import React, {
  useEffect,
  useRef,
  useState
} from "react";

import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries
} from "lightweight-charts";

import {
  Search,
  SlidersHorizontal,
  X,
  CandlestickChart,
  ChartNoAxesCombined
} from "lucide-react";


const TIMEFRAMES = [
  ["1m", "1M"],
  ["5m", "5M"],
  ["15m", "15M"],
  ["30m", "30M"],
  ["60m", "1H"],
  ["1d", "1D"],
  ["1w", "1W"]
];


const MARKET_OPTIONS = [
  ["US", "United States"],
  ["HK", "Hong Kong"],
  ["SH", "Shanghai"],
  ["SZ", "Shenzhen"],
  ["SG", "Singapore"],
  ["MY", "Malaysia"],
  ["JP", "Japan"]
];


function formatPrice(value) {
  if (value === null || value === undefined)
    return "—";

  return Number(value).toLocaleString(
    undefined,
    {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4
    }
  );
}


function chartTime(value, timeframe, timestamp) {

  if (!value)
    return null;

  if (
    timeframe === "1d" ||
    timeframe === "1w"
  ) {
    return value.slice(0, 10);
  }

  if (Number.isFinite(timestamp)) return timestamp;

  const [
    datePart,
    timePart = "00:00:00"
  ] = value.split(" ");

  const [year, month, day] =
    datePart.split("-").map(Number);

  const [hour, minute, second] =
    timePart.split(":").map(Number);

  return Math.floor(
    new Date(
      year,
      month - 1,
      day,
      hour,
      minute,
      second || 0
    ).getTime() / 1000
  );
}


function humanState(state) {

  if (!state)
    return "UNKNOWN";

  return String(state)
    .replaceAll("_", " ");
}


export default function Markets() {

  const [search, setSearch] =
    useState("");

  const [symbol, setSymbol] =
    useState(null);

  const [selection, setSelection] = useState(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [searchSubmitted, setSearchSubmitted] = useState(false);

  const [quote, setQuote] =
    useState(null);

  const [candles, setCandles] =
    useState([]);

  const [markets, setMarkets] =
    useState([]);

  const [selectedMarkets, setSelectedMarkets] =
    useState([
      "US",
      "HK",
      "SH",
      "SZ",
      "SG",
      "MY",
      "JP"
    ]);

  const [showMarketFilter, setShowMarketFilter] =
    useState(false);

  const symbolLookup = useSymbolSearch(selectedMarkets, 20, 1);
  const { results: suggestions, searching } = symbolLookup;

  const [timeframe, setTimeframe] =
    useState("1d");

  const [chartType, setChartType] =
    useState("candles");

  const [showVolume, setShowVolume] =
    useState(true);

  const [loading, setLoading] =
    useState(false);

  const [error, setError] =
    useState(null);
  const [quoteError, setQuoteError] = useState(null);
  const candleQuotaBlocked = useRef(false);


  const chartRequestId = useRef(0);
  const chartGeneration = useRef(0);
  const olderRequest = useRef(null);
  const historyEnded = useRef(false);
  const [historyStatus, setHistoryStatus] = useState("");
  const [followLatest, setFollowLatest] = useState(true);
  const [latestJump, setLatestJump] = useState(0);
  const [chartInfo, setChartInfo] = useState(null);

  async function loadSymbol(target, quiet = false) {

    if (!target)
      return;

    const requestId = ++chartRequestId.current;
    if (!quiet) setLoading(true);
    setQuoteError(null);
    const jobs = [
      fetchJson(`/api/market/${encodeURIComponent(target)}`, { cache: "no-store", timeoutMs: 45000 })
        .then(q => {
          if (requestId === chartRequestId.current) setQuote(q);
        })
        .catch(failure => {
          if (requestId !== chartRequestId.current) return;
          if (!quiet) setQuote(null);
          setQuoteError(failure.message);
        })
    ];
    // A broker quota failure must not hide a quote or hammer history every 30s.
    // Explicit Search or a new symbol/interval permits a fresh candle attempt.
    if (!quiet || !candleQuotaBlocked.current) {
      setError(null);
      jobs.push(fetchJson(`/api/market/${encodeURIComponent(target)}/candles?timeframe=${timeframe}&count=250`,
        { cache: "no-store", timeoutMs: 45000 })
        .then(c => {
          if (requestId !== chartRequestId.current) return;
          if (c.symbol !== target || c.timeframe !== timeframe) throw new Error("Chart response does not match the selected security and interval");
          candleQuotaBlocked.current = false;
          setCandles(previous => quiet ? mergeCandles(previous, c.candles || []) : (c.candles || []));
          setChartInfo(c);
        })
        .catch(failure => {
          if (requestId !== chartRequestId.current) return;
          candleQuotaBlocked.current = historyQuotaFailure(failure);
          if (!quiet) setCandles([]);
          setError(candleFailureMessage(failure));
        }));
    }
    await Promise.all(jobs);
    if (requestId === chartRequestId.current) setLoading(false);
  }


  async function loadMarkets() {

    try {

      const r = await fetch(
        "/api/markets/status",
        { cache: "no-store" }
      );

      if (!r.ok)
        return;

      const d =
        await r.json();

      setMarkets(
        d.markets || []
      );

    } catch (_) {}
  }


  function chooseSuggestion(item) {
    ++chartRequestId.current;
    setSelection(item);
    setSearch(securityLabel(item));
    setSymbol(item.symbol);
    setRefreshVersion(value => value + 1);
    symbolLookup.clear();
    setSearchSubmitted(false);
    setShowMarketFilter(false);
    setLoading(true);
    setError(null);
    setQuoteError(null);
    setQuote(null);
    setCandles([]);
  }


  function clearSecurity() {
    ++chartRequestId.current;

    setSearch("");
    setSymbol(null);
    setSelection(null);
    setSearchSubmitted(false);
    setLoading(false);
    setQuote(null);
    setCandles([]);
    symbolLookup.clear();
    setError(null);
    setQuoteError(null);
  }


  function toggleMarket(id) {

    setSelectedMarkets(current => {

      if (current.includes(id)) {

        return current.filter(
          item => item !== id
        );
      }

      return [
        ...current,
        id
      ];
    });
  }


  async function submitSearch(e) {
    e.preventDefault();
    setSearchSubmitted(true);
    const selected = selectedSecurityForQuery(selection, search);
    if (selected) {
      chooseSuggestion(selected);
      return;
    }
    if (suggestions.length) {
      chooseSuggestion(suggestions[0]);
      return;
    }
    const results = await symbolLookup.run(search);
    if (results?.length) chooseSuggestion(results[0]);
  }


  useEffect(() => {

    const pendingSymbol =
      sessionStorage.getItem(
        "cerebro.market.symbol"
      );

    const pendingName =
      sessionStorage.getItem(
        "cerebro.market.name"
      );

    if (pendingSymbol) {

      chooseSuggestion({ symbol: pendingSymbol, name: pendingName || "" });

      sessionStorage.removeItem(
        "cerebro.market.symbol"
      );

      sessionStorage.removeItem(
        "cerebro.market.name"
      );
    }

  }, []);


  async function loadOlder() {
    if (!symbol || !candles.length || olderRequest.current || historyEnded.current || candleQuotaBlocked.current) return;
    const generation = chartGeneration.current;
    const token = {};
    olderRequest.current = token;
    setHistoryStatus("Loading earlier candles…");
    try {
      const data = await fetchJson(`/api/market/${encodeURIComponent(symbol)}/candles?timeframe=${timeframe}&count=250&before=${encodeURIComponent(candles[0].time)}`, { cache: "no-store", timeoutMs: 45000 });
      if (generation !== chartGeneration.current) return;
      if (data.symbol !== symbol || data.timeframe !== timeframe) throw new Error("Earlier chart response does not match the selected security");
      const earlier = (data.candles || []).filter(candle => candle.time < candles[0].time);
      historyEnded.current = earlier.length === 0;
      setCandles(previous => mergeCandles(previous, earlier));
      setHistoryStatus(earlier.length ? "" : "No earlier candles returned by OpenD for this range.");
    } catch (failure) {
      if (generation === chartGeneration.current) {
        candleQuotaBlocked.current = historyQuotaFailure(failure);
        setHistoryStatus(candleFailureMessage(failure));
      }
    } finally {
      if (olderRequest.current === token) olderRequest.current = null;
    }
  }

  useEffect(() => {
    ++chartGeneration.current;
    historyEnded.current = false;
    candleQuotaBlocked.current = false;
    olderRequest.current = null;
    setHistoryStatus("");
    setChartInfo(null);
    setCandles([]);
    setFollowLatest(true);
    if (symbol) loadSymbol(symbol);
    return () => { ++chartGeneration.current; ++chartRequestId.current; };
  }, [symbol, timeframe, refreshVersion]);

  useEffect(() => {
    if (!symbol || !followLatest || loading) return;
    let cancelled = false;
    let timer;
    const refresh = async () => {
      await loadSymbol(symbol, true);
      if (!cancelled) timer = setTimeout(refresh, 30000);
    };
    timer = setTimeout(refresh, 30000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [symbol, timeframe, followLatest, loading]);


  useEffect(() => {

    loadMarkets();

    const timer =
      setInterval(
        loadMarkets,
        10000
      );

    return () =>
      clearInterval(timer);

  }, []);


  const previous =
    Number(quote?.previous_close);

  const current =
    Number(quote?.price);

  const change =
    previous
      ? current - previous
      : null;

  const changePct =
    previous
      ? (change / previous) * 100
      : null;


  return (
    <div className="marketsPage">

      <div className="marketToolbar">

        <form
          className="symbolSearch"
          onSubmit={submitSearch}
        >

          <Search size={18}/>

          <input
            value={search}
            onChange={e => {

              const value =
                e.target.value;

              setSearch(value);
              setSearchSubmitted(false);
              symbolLookup.schedule(value);
            }}
            placeholder="Search ticker or company name"
          />


          {symbol && (

            <button
              type="button"
              className="clearSearchButton"
              onClick={clearSecurity}
              title="Clear search"
            >
              <X size={17}/>
            </button>

          )}


          <button
            type="button"
            className="filterButton"
            onClick={() =>
              setShowMarketFilter(
                !showMarketFilter
              )
            }
          >
            <SlidersHorizontal size={17}/>
            Markets
          </button>


          <button
            type="submit"
            className="searchButton"
          >
            Search
          </button>

        </form>


        {showMarketFilter && (

          <div className="marketFilterPanel">

            <div className="marketFilterTitle">
              Search markets
            </div>

            {MARKET_OPTIONS.map(
              ([id, name]) => (

                <label
                  key={id}
                  className="marketFilterOption"
                >

                  <input
                    type="checkbox"
                    checked={
                      selectedMarkets.includes(id)
                    }
                    onChange={() =>
                      toggleMarket(id)
                    }
                  />

                  <span>
                    <strong>{id}</strong>
                    {name}
                  </span>

                </label>

              )
            )}

            <div className="marketFilterActions">

              <button
                type="button"
                onClick={() =>
                  setSelectedMarkets(
                    MARKET_OPTIONS.map(
                      item => item[0]
                    )
                  )
                }
              >
                Select all
              </button>

              <button
                type="button"
                onClick={() =>
                  setSelectedMarkets([])
                }
              >
                Clear
              </button>

            </div>

          </div>

        )}


        {suggestions.length > 0 && (

          <div className="searchSuggestions">

            {suggestions.map(item => (

              <button
                key={item.symbol}
                onClick={() =>
                  chooseSuggestion(item)
                }
              >

                <div className="suggestionMain">

                  <strong>
                    {item.ticker}
                  </strong>

                  <span>
                    {item.name}
                  </span>

                </div>


                <div className="suggestionMarket">

                  <span>
                    {item.market}
                  </span>

                  <small>
                    {item.symbol}
                  </small>

                </div>

              </button>

            ))}

          </div>

        )}


        {searching && (

          <div className="searchingText">
            Searching…
          </div>

        )}

        {symbolLookup.error && <div className="chartError" role="alert">{symbolLookup.error}</div>}
        {searchSubmitted && !searching && !suggestions.length && !symbolLookup.error && !selectedSecurityForQuery(selection, search) && (
          <div className="searchingText" role="status">{selectedMarkets.length ? "No matching securities found. Try a ticker or change the Markets filter." : "Select at least one market to search."}</div>
        )}
      </div>

      {loading && !quote && <div className="searchingText" role="status">Loading {symbol} quote and candles…</div>}
      {quoteError && <div className="chartError" role="alert">Quote unavailable: {quoteError} Press Search to retry the selected security.</div>}

      {symbol && (

        <>

          {quote && <section className="marketQuotePanel">

            <div>

              <div className="quoteIdentity">

                <h2>
                  {quote.symbol}
                </h2>

                <span>
                  {quote.name}
                </span>

              </div>


              <div className="quotePrice">

                ${formatPrice(
                  quote.price
                )}

                {changePct !== null && (

                  <span
                    className={
                      changePct >= 0
                        ? "positive"
                        : "negative"
                    }
                  >
                    {changePct >= 0
                      ? "+"
                      : ""}

                    {changePct.toFixed(2)}%
                  </span>

                )}

              </div>

            </div>


            <div className="quoteStats">

              <QuoteStat
                label="Open"
                value={formatPrice(
                  quote.open
                )}
              />

              <QuoteStat
                label="High"
                value={formatPrice(
                  quote.high
                )}
              />

              <QuoteStat
                label="Low"
                value={formatPrice(
                  quote.low
                )}
              />

              <QuoteStat
                label="Prev close"
                value={formatPrice(
                  quote.previous_close
                )}
              />

              <QuoteStat
                label="Volume"
                value={
                  quote.volume
                    ? Number(
                        quote.volume
                      ).toLocaleString()
                    : "—"
                }
              />

            </div>

          </section>}


          <section className="chartPanel">
            <p>Regular-session candles · New York time (US) · Unadjusted prices. Interval buttons select candle duration, not date range.</p>

            <div className="chartToolbar">
              <label><input type="checkbox" checked={followLatest} onChange={event => setFollowLatest(event.target.checked)}/> Follow latest (refresh every 30s)</label>
              <button onClick={() => { setFollowLatest(true); setLatestJump(value => value + 1); }}>Latest</button>
              <span>Last candle: {chartInfo?.latest_candle_time || (loading ? "Loading…" : "Unavailable")} {chartInfo?.timezone || ""}</span>

              <div className="timeframeButtons">

                {TIMEFRAMES.map(
                  ([value, label]) => (

                    <button
                      key={value}
                      className={
                        timeframe === value
                          ? "selected"
                          : ""
                      }
                      onClick={() =>
                        setTimeframe(value)
                      }
                    >
                      {label}
                    </button>

                  )
                )}

              </div>


              <div className="chartControls">

                <button
                  className={
                    chartType === "candles"
                      ? "selected"
                      : ""
                  }
                  onClick={() =>
                    setChartType(
                      "candles"
                    )
                  }
                >
                  <CandlestickChart size={17}/>
                  Candles
                </button>


                <button
                  className={
                    chartType === "line"
                      ? "selected"
                      : ""
                  }
                  onClick={() =>
                    setChartType(
                      "line"
                    )
                  }
                >
                  <ChartNoAxesCombined size={17}/>
                  Line
                </button>


                <label className="volumeToggle">

                  <input
                    type="checkbox"
                    checked={showVolume}
                    onChange={e =>
                      setShowVolume(
                        e.target.checked
                      )
                    }
                  />

                  Volume

                </label>

              </div>

            </div>


            {error && <div className="chartError" role="alert">{error}</div>}
            {historyStatus && <p role="status">{historyStatus}</p>}
            {(

              <PriceChart
                key={`${symbol}:${timeframe}`}
                candles={candles}
                onLoadOlder={loadOlder}
                onBrowseHistory={() => setFollowLatest(false)}
                followLatest={followLatest}
                latestJump={latestJump}
                timeframe={timeframe}
                chartType={chartType}
                showVolume={showVolume}
              />

            )}


            {loading && (

              <div className="chartLoading">
                Loading market data…
              </div>

            )}

          </section>

        </>

      )}


      {!symbol && (

        <div className="marketLanding">

          <h2>
            Market Sessions
          </h2>

          <p>
            Search for a security above to open
            quote details and charts.
          </p>

        </div>

      )}


      <section className="marketSessionsPanel">

        {symbol && (

          <div className="sectionHeading">

            <div>
              <h2>
                Market Sessions
              </h2>

              <p>
                Live session state reported by OpenD
              </p>
            </div>

          </div>

        )}


        <div className="sessionGrid">

          {markets.map(market => (

            <div
              className="sessionCard"
              key={market.opend_key}
            >

              <div className="sessionTop">

                <div className="sessionName">

                  <strong>
                    {market.name}
                  </strong>

                  <span>
                    {market.id}
                  </span>

                </div>


                <MarketState
                  state={market.state}
                />

              </div>


              {market.regular_session && (

                <div className="sessionSchedule">

                  <span>
                    Regular session
                  </span>

                  <strong>
                    {market.regular_session}
                  </strong>

                </div>

              )}


              {market.timezone && (

                <div className="sessionTimezone">
                  {market.timezone}
                </div>

              )}

            </div>

          ))}

        </div>

      </section>

    </div>
  );
}


function PriceChart({ candles, followLatest, latestJump, timeframe, chartType, showVolume, onLoadOlder, onBrowseHistory }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const previousData = useRef([]);
  const savedRange = useRef(null);
  const latestProps = useRef({});
  latestProps.current = { onLoadOlder, candles, followLatest };

  useEffect(() => {
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { color: "#ffffff" }, textColor: "#64748b" },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      rightPriceScale: { borderColor: "#e2e8f0" },
      localization: { timeFormatter: time => typeof time === "number"
        ? new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(time * 1000))
        : `${time.year}-${time.month}-${time.day}` },
      timeScale: { borderColor: "#e2e8f0", timeVisible: !["1d", "1w"].includes(timeframe),
        tickMarkFormatter: time => typeof time === "number"
          ? new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(time * 1000))
          : `${time.year}-${time.month}-${time.day}` }
    });
    const price = chart.addSeries(chartType === "candles" ? CandlestickSeries : LineSeries, chartType === "line" ? { lineWidth: 2 } : {});
    const volume = showVolume ? chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "" }) : null;
    volume?.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    const state = { chart, price, volume, updating: false };
    chartRef.current = state;
    const rangeChanged = range => {
      if (!state.updating && range && range.from < 30 && latestProps.current.candles.length && !latestProps.current.followLatest) latestProps.current.onLoadOlder();
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(rangeChanged);
    previousData.current = [];
    return () => {
      savedRange.current = chart.timeScale().getVisibleLogicalRange();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(rangeChanged);
      chartRef.current = null;
      chart.remove();
    };
  }, [timeframe, chartType, showVolume]);

  useEffect(() => {
    const state = chartRef.current;
    if (!state || !candles.length) return;
    const { chart, price, volume } = state;
    const previous = previousData.current;
    const range = chart.timeScale().getVisibleLogicalRange() || savedRange.current;
    const added = prependedCount(previous, candles);
    state.updating = true;
    const time = candle => chartTime(candle.time, timeframe, candle.timestamp);
    price.setData(candles.map(c => chartType === "candles"
      ? { time: time(c), open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close) }
      : { time: time(c), value: Number(c.close) }));
    volume?.setData(candles.map(c => ({ time: time(c), value: Number(c.volume || 0) })));
    if (!followLatest && range) {
      chart.timeScale().setVisibleLogicalRange({ from: range.from + added, to: range.to + added });
    } else if (!previous.length) {
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, candles.length - 100), to: candles.length + 3 });
    } else if (followLatest) {
      chart.timeScale().scrollToRealTime();
    }
    previousData.current = candles;
    state.updating = false;
  }, [candles, timeframe, chartType, showVolume, followLatest, latestJump]);

  return <div ref={containerRef} className="priceChart" onPointerDown={onBrowseHistory} onWheel={onBrowseHistory}/>;
}


function QuoteStat({
  label,
  value
}) {

  return (
    <div className="quoteStat">

      <span>
        {label}
      </span>

      <strong>
        {value}
      </strong>

    </div>
  );
}


function MarketState({
  state
}) {

  const normalized =
    String(state || "")
      .toUpperCase();


  const open =
    normalized.includes("OPEN") ||
    normalized.includes("MORNING") ||
    normalized.includes("AFTERNOON");


  return (
    <div
      title={humanState(state)}
      className={
        open
          ? "marketState open"
          : "marketState closed"
      }
    >

      <span className="dot"></span>

      <span className="marketStateText">
        {humanState(state)}
      </span>

    </div>
  );
}
