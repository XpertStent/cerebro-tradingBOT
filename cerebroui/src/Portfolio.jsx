import React, { useEffect, useState } from "react";
import {
  RefreshCw,
  Wallet,
  CircleDollarSign,
  TrendingUp,
  Landmark
} from "lucide-react";


function money(value) {
  if (
    value === null ||
    value === undefined
  ) {
    return "—";
  }

  return new Intl.NumberFormat(
    "en-US",
    {
      style: "currency",
      currency: "USD"
    }
  ).format(Number(value));
}


function percent(value) {
  if (
    value === null ||
    value === undefined
  ) {
    return "—";
  }

  return `${Number(value).toFixed(2)}%`;
}


export default function Portfolio() {

  const [portfolio, setPortfolio] =
    useState(null);

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState(null);


  async function loadPortfolio(force = false) {

    try {
      setError(null);

      const r = await fetch(
        force
          ? "/api/portfolio/?refresh=true"
          : "/api/portfolio/",
        {
          cache: "no-store"
        }
      );

      const d = await r.json();

      if (!r.ok) {
        throw new Error(
          d.detail ||
          "Unable to load portfolio"
        );
      }

      setPortfolio(d);

    } catch (e) {

      setError(e.message);

    } finally {

      setLoading(false);
    }
  }


  useEffect(() => {

    loadPortfolio();

    const timer =
      setInterval(
        loadPortfolio,
        10000
      );

    return () =>
      clearInterval(timer);

  }, []);


  const account =
    portfolio?.account;

  const positions =
    portfolio?.positions || [];


  const unrealized =
    account?.unrealized_pnl;

  const realized =
    account?.realized_pnl;


  return (
    <div className="portfolioPage">

      <div className="portfolioTopbar">

        <div>
          <h2>Portfolio Overview</h2>

          <p>
            Live account state reported through Cerebro.
          </p>
        </div>


        <div className="portfolioActions">

          <span className="portfolioMode">
            {account?.mode || "PAPER"}
          </span>


          <button
            className="portfolioRefresh"
            onClick={() => loadPortfolio(true)}
          >
            <RefreshCw size={16}/>
            Refresh
          </button>

        </div>

      </div>


      {error && (

        <div className="portfolioError">
          {error}
        </div>

      )}


      <section className="portfolioMetrics">

        <MetricCard
          icon={<Landmark size={20}/>}
          label="Total Value"
          value={money(
            account?.total_value
          )}
        />

        <MetricCard
          icon={<Wallet size={20}/>}
          label="Cash"
          value={money(
            account?.cash
          )}
        />

        <MetricCard
          icon={<CircleDollarSign size={20}/>}
          label="Market Value"
          value={money(
            account?.market_value
          )}
        />

        <MetricCard
          icon={<TrendingUp size={20}/>}
          label="Open Positions"
          value={positions.length}
        />

      </section>


      <section className="pnlGrid">

        <div className="pnlCard">

          <span>
            Unrealized P&L
          </span>

          <strong
            className={
              unrealized > 0
                ? "positive"
                : unrealized < 0
                  ? "negative"
                  : ""
            }
          >
            {money(unrealized)}
          </strong>

        </div>


        <div className="pnlCard">

          <span>
            Realized P&L
          </span>

          <strong
            className={
              realized > 0
                ? "positive"
                : realized < 0
                  ? "negative"
                  : ""
            }
          >
            {money(realized)}
          </strong>

        </div>

      </section>


      <section className="positionsPanel">

        <div className="positionsHeader">

          <div>
            <h2>Positions</h2>

            <p>
              Current holdings in the selected account.
            </p>
          </div>


          <span className="positionCount">
            {positions.length}
          </span>

        </div>


        <div className="positionsTableWrap">

          <table className="positionsTable">

            <thead>

              <tr>
                <th>Security</th>
                <th>Qty</th>
                <th>Available</th>
                <th>Avg Cost</th>
                <th>Current</th>
                <th>Market Value</th>
                <th>P&L</th>
                <th>P&L %</th>
              </tr>

            </thead>


            <tbody>

              {loading ? (

                <tr>
                  <td
                    colSpan="8"
                    className="positionsEmpty"
                  >
                    Loading portfolio…
                  </td>
                </tr>

              ) : positions.length === 0 ? (

                <tr>
                  <td
                    colSpan="8"
                    className="positionsEmpty"
                  >
                    No open positions
                  </td>
                </tr>

              ) : (

                positions.map(position => (

                  <tr
                    key={position.symbol}
                    className="clickablePosition"
                    title={`Open ${position.symbol} in Markets`}
                    onClick={() => {
                      window.dispatchEvent(
                        new CustomEvent(
                          "cerebro-open-market",
                          {
                            detail: {
                              symbol: position.symbol,
                              name: position.name
                            }
                          }
                        )
                      );
                    }}
                  >

                    <td>

                      <strong>
                        {position.symbol}
                      </strong>

                      <span>
                        {position.name}
                      </span>

                    </td>


                    <td>
                      {position.quantity}
                    </td>


                    <td>
                      {position.available_quantity}
                    </td>


                    <td>
                      {money(
                        position.average_cost
                      )}
                    </td>


                    <td>
                      {money(
                        position.current_price
                      )}
                    </td>


                    <td>
                      {money(
                        position.market_value
                      )}
                    </td>


                    <td
                      className={
                        position.profit_loss > 0
                          ? "positive"
                          : position.profit_loss < 0
                            ? "negative"
                            : ""
                      }
                    >
                      {money(
                        position.profit_loss
                      )}
                    </td>


                    <td
                      className={
                        position.profit_loss_percent > 0
                          ? "positive"
                          : position.profit_loss_percent < 0
                            ? "negative"
                            : ""
                      }
                    >
                      {percent(
                        position.profit_loss_percent
                      )}
                    </td>

                  </tr>

                ))

              )}

            </tbody>

          </table>

        </div>

      </section>

    </div>
  );
}


function MetricCard({
  icon,
  label,
  value
}) {

  return (
    <div className="portfolioMetric">

      <div className="portfolioMetricIcon">
        {icon}
      </div>

      <div>

        <span>
          {label}
        </span>

        <strong>
          {value}
        </strong>

      </div>

    </div>
  );
}
