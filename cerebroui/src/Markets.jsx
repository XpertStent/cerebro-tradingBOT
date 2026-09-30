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


function chartTime(value, timeframe) {

  if (!value)
    return null;

  if (
    timeframe === "1d" ||
    timeframe === "1w"
  ) {
    return value.slice(0, 10);
  }

  return Math.floor(
    new Date(
      value.replace(" ", "T") + "Z"
    ).getTime() / 1000
  );
}


export default function Markets() {

  const [search, setSearch] =
    useState("AAPL");

  const [suggestions, setSuggestions] =
    useState([]);

  const [searching, setSearching] =
    useState(false);

  const [symbol, setSymbol] =
    useState("AAPL");

  const [quote, setQuote] =
    useState(null);

  const [candles, setCandles] =
    useState([]);

  const [markets, setMarkets] =
    useState([]);

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


  async function loadSymbol(target = symbol) {

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

      setQuote(q);
      setCandles(c.candles || []);

    } catch (e) {

      setQuote(null);
      setCandles([]);
      setError(e.message);

    } finally {

      setLoading(false);
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

      const d = await r.json();

      setMarkets(d.markets || []);

    } catch (_) {}
  }


  async function runSearch(value) {

    const q = value.trim();

    if (!q) {
      setSuggestions([]);
      return;
    }

    setSearching(true);

    try {

      const r = await fetch(
        `/api/market/search?q=${encodeURIComponent(q)}&limit=8`,
        { cache: "no-store" }
      );

      if (!r.ok)
        throw new Error("Search failed");

      const d = await r.json();

      setSuggestions(d.results || []);

    } catch (_) {

      setSuggestions([]);

    } finally {

      setSearching(false);
    }
  }


  function submitSearch(e) {

    e.preventDefault();

    const value =
      search.trim().toUpperCase();

    if (!value)
      return;

    if (suggestions.length > 0) {
      chooseSuggestion(
        suggestions[0]
      );
      return;
    }

    setSymbol(value);
    setQuote(null);
    setCandles([]);
  }


  function chooseSuggestion(item) {

    setSearch(item.ticker);
    setSymbol(item.symbol);

    setQuote(null);
    setCandles([]);
    setSuggestions([]);
  }


  useEffect(() => {
    loadSymbol(symbol);
  }, [symbol, timeframe]);


  useEffect(() => {

    loadMarkets();

    const timer =
      setInterval(loadMarkets, 10000);

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

          <Search size={18} />

          <input
            value={search}
            onChange={e => {
              const value = e.target.value;
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
            placeholder="Search symbol e.g. AAPL"
          />

          <button type="submit">
            Search
          </button>

        </form>

        {suggestions.length > 0 && (
          <div className="searchSuggestions">
            {suggestions.map(item => (
              <button
                key={item.symbol}
                onClick={() =>
                  chooseSuggestion(item)
                }
              >
                <div>
                  <strong>{item.ticker}</strong>
                  <span>{item.name}</span>
                </div>

                <small>{item.symbol}</small>
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


      <section className="marketQuotePanel">

        <div>

          <div className="quoteIdentity">

            <h2>
              {quote?.symbol || symbol}
            </h2>

            <span>
              {quote?.name || ""}
            </span>

          </div>


          <div className="quotePrice">

            ${formatPrice(quote?.price)}

            {changePct !== null && (

              <span
                className={
                  changePct >= 0
                    ? "positive"
                    : "negative"
                }
              >
                {changePct >= 0 ? "+" : ""}
                {changePct.toFixed(2)}%
              </span>

            )}

          </div>

        </div>


        <div className="quoteStats">

          <QuoteStat
            label="Open"
            value={formatPrice(quote?.open)}
          />

          <QuoteStat
            label="High"
            value={formatPrice(quote?.high)}
          />

          <QuoteStat
            label="Low"
            value={formatPrice(quote?.low)}
          />

          <QuoteStat
            label="Prev close"
            value={formatPrice(
              quote?.previous_close
            )}
          />

          <QuoteStat
            label="Volume"
            value={
              quote?.volume
                ? Number(
                    quote.volume
                  ).toLocaleString()
                : "—"
            }
          />

        </div>

      </section>


      <section className="chartPanel">

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
                setChartType("candles")
              }
              title="Candlestick chart"
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
                setChartType("line")
              }
              title="Line chart"
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


      <section className="marketSessionsPanel">

        <div className="sectionHeading">

          <div>
            <h2>Market Sessions</h2>
            <p>
              Live session state reported by OpenD
            </p>
          </div>

        </div>


        <div className="sessionGrid">

          {markets.map(market => (

            <div
              className="sessionCard"
              key={market.opend_key}
            >

              <div className="sessionTop">

                <div>
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
          timeframe
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

      series.setData(priceData);

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
            timeframe
          ),
          value: Number(c.close)
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


      volumeSeries.priceScale()
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
            timeframe
          ),

          value: Number(
            c.volume || 0
          )

        }))

      );
    }


    chart.timeScale()
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

      <span>{label}</span>
      <strong>{value}</strong>

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
    normalized.includes("MORNING") ||
    normalized.includes("AFTERNOON") ||
    normalized.includes("OPEN");


  return (
    <div
      className={
        open
          ? "marketState open"
          : "marketState closed"
      }
    >

      <span className="dot"></span>

      {state || "UNKNOWN"}

    </div>
  );
}
