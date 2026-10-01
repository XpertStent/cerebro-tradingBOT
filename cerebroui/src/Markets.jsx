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

  const [suggestions, setSuggestions] =
    useState([]);

  const [searching, setSearching] =
    useState(false);

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


  async function runSearch(value) {

    const q = value.trim();

    if (!q) {
      setSuggestions([]);
      return;
    }

    if (!selectedMarkets.length) {
      setSuggestions([]);
      return;
    }

    setSearching(true);

    try {

      const marketParam =
        selectedMarkets.join(",");

      const r = await fetch(
        `/api/market/search?q=${encodeURIComponent(q)}&markets=${encodeURIComponent(marketParam)}&limit=20`,
        { cache: "no-store" }
      );

      if (!r.ok)
        throw new Error("Search failed");

      const d =
        await r.json();

      setSuggestions(
        d.results || []
      );

    } catch (_) {

      setSuggestions([]);

    } finally {

      setSearching(false);
    }
  }


  const chartRequestId = useRef(0);

  async function loadSymbol(target) {

    if (!target)
      return;

    const requestId = ++chartRequestId.current;
    setLoading(true);
    setError(null);

    try {

      const [
        quoteResponse,
        candleResponse
      ] = await Promise.all([

        fetch(
          `/api/market/${encodeURIComponent(target)}`,
          { cache: "no-store" }
        ),

        fetch(
          `/api/market/${encodeURIComponent(target)}/candles?timeframe=${timeframe}&count=250`,
          { cache: "no-store" }
        )
      ]);

      if (!quoteResponse.ok)
        throw new Error("Unable to load quote");

      if (!candleResponse.ok)
        throw new Error("Unable to load chart");

      const q =
        await quoteResponse.json();

      const c =
        await candleResponse.json();

      if (requestId !== chartRequestId.current) return;
      if (c.symbol !== target || c.timeframe !== timeframe) throw new Error("Chart response does not match the selected security and interval");
      setQuote(q);
      setCandles(c.candles || []);

    } catch (e) {
      if (requestId !== chartRequestId.current) return;
      setQuote(null);
      setCandles([]);
      setError(e.message);

    } finally {

      if (requestId === chartRequestId.current) setLoading(false);
    }
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

    setSearch(
      `${item.ticker} — ${item.name}`
    );

    setSymbol(item.symbol);

    setSuggestions([]);
    setShowMarketFilter(false);

    setQuote(null);
    setCandles([]);
  }


  function clearSecurity() {
    ++chartRequestId.current;

    setSearch("");
    setSymbol(null);
    setQuote(null);
    setCandles([]);
    setSuggestions([]);
    setError(null);
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


  function submitSearch(e) {

    e.preventDefault();

    if (suggestions.length) {
      chooseSuggestion(
        suggestions[0]
      );
      return;
    }

    runSearch(search);
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

      const ticker =
        pendingSymbol.split(".").pop();

      setSymbol(pendingSymbol);

      setSearch(
        pendingName
          ? `${ticker} — ${pendingName}`
          : ticker
      );

      sessionStorage.removeItem(
        "cerebro.market.symbol"
      );

      sessionStorage.removeItem(
        "cerebro.market.name"
      );
    }

  }, []);


  useEffect(() => {

    if (symbol)
      loadSymbol(symbol);

  }, [
    symbol,
    timeframe
  ]);


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

              clearTimeout(
                window.__cerebroSearchTimer
              );

              window.__cerebroSearchTimer =
                setTimeout(
                  () => runSearch(value),
                  250
                );
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

      </div>


      {symbol && quote && (

        <>

          <section className="marketQuotePanel">

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

          </section>


          <section className="chartPanel">
            <p>Regular-session candles · New York time (US) · Unadjusted prices. Interval buttons select candle duration, not date range.</p>

            <div className="chartToolbar">

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


            {error ? (

              <div className="chartError">
                {error}
              </div>

            ) : (

              <PriceChart
                candles={candles}
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


function PriceChart({
  candles,
  timeframe,
  chartType,
  showVolume
}) {

  const containerRef =
    useRef(null);


  useEffect(() => {

    if (
      !containerRef.current ||
      !candles.length
    )
      return;


    const chart = createChart(
      containerRef.current,
      {
        autoSize: true,

        layout: {
          background: {
            color: "#ffffff"
          },

          textColor: "#64748b"
        },

        localization: {
          timeFormatter: time => typeof time === "number"
            ? new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(time * 1000))
            : `${time.year}-${time.month}-${time.day}`
        },
        grid: {
          vertLines: {
            color: "#f1f5f9"
          },

          horzLines: {
            color: "#f1f5f9"
          }
        },

        rightPriceScale: {
          borderColor: "#e2e8f0"
        },

        timeScale: {
          borderColor: "#e2e8f0",
          tickMarkFormatter: time => typeof time === "number"
            ? new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(time * 1000))
            : `${time.year}-${time.month}-${time.day}`,
          timeVisible:
            !["1d", "1w"].includes(
              timeframe
            )
        }
      }
    );


    const priceData =
      candles.map(c => ({
        time: chartTime(
          c.time,
          timeframe,
          c.timestamp
        ),
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close)
      }));


    if (chartType === "candles") {

      const series =
        chart.addSeries(
          CandlestickSeries,
          {}
        );

      series.setData(
        priceData
      );

    } else {

      const series =
        chart.addSeries(
          LineSeries,
          {
            lineWidth: 2
          }
        );

      series.setData(
        candles.map(c => ({
          time: chartTime(
            c.time,
            timeframe,
            c.timestamp
          ),
          value: Number(
            c.close
          )
        }))
      );
    }


    if (showVolume) {

      const volumeSeries =
        chart.addSeries(
          HistogramSeries,
          {
            priceFormat: {
              type: "volume"
            },

            priceScaleId: ""
          }
        );


      volumeSeries
        .priceScale()
        .applyOptions({
          scaleMargins: {
            top: 0.78,
            bottom: 0
          }
        });


      volumeSeries.setData(

        candles.map(c => ({

          time: chartTime(
            c.time,
            timeframe,
            c.timestamp
          ),

          value: Number(
            c.volume || 0
          )

        }))

      );
    }


    chart
      .timeScale()
      .fitContent();


    return () => {
      chart.remove();
    };

  }, [
    candles,
    timeframe,
    chartType,
    showVolume
  ]);


  return (
    <div
      ref={containerRef}
      className="priceChart"
    />
  );
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
