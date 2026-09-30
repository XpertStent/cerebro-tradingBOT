import React, {
  useEffect,
  useState
} from "react";

import {
  Plus,
  Trash2,
  RefreshCw,
  ShieldCheck
} from "lucide-react";


export default function Strategies() {

  const [strategies, setStrategies] =
    useState([]);

  const [name, setName] =
    useState("");

  const [symbol, setSymbol] =
    useState("");

  const [type, setType] =
    useState("MOVING_AVERAGE");

  const [timeframe, setTimeframe] =
    useState("1d");

  const [loading, setLoading] =
    useState(false);


  async function loadStrategies() {

    setLoading(true);

    try {

      const response = await fetch(
        "/api/strategies/",
        {
          cache: "no-store"
        }
      );

      const data =
        await response.json();

      if (response.ok) {
        setStrategies(
          data.strategies || []
        );
      }

    } finally {
      setLoading(false);
    }
  }


  async function createStrategy() {

    if (
      !name.trim() ||
      !symbol.trim()
    ) {
      return;
    }

    const response = await fetch(
      "/api/strategies/",
      {
        method: "POST",

        headers: {
          "Content-Type":
            "application/json"
        },

        body: JSON.stringify({
          name: name.trim(),
          strategy_type: type,
          symbol: symbol.trim(),
          timeframe,
          parameters: {}
        })
      }
    );

    if (response.ok) {

      setName("");
      setSymbol("");

      await loadStrategies();
    }
  }


  async function toggleStrategy(
    strategy
  ) {

    await fetch(
      `/api/strategies/${strategy.id}/enabled`,
      {
        method: "PATCH",

        headers: {
          "Content-Type":
            "application/json"
        },

        body: JSON.stringify({
          enabled:
            !strategy.enabled
        })
      }
    );

    await loadStrategies();
  }


  async function deleteStrategy(
    strategy
  ) {

    await fetch(
      `/api/strategies/${strategy.id}`,
      {
        method: "DELETE"
      }
    );

    await loadStrategies();
  }


  useEffect(() => {

    loadStrategies();

  }, []);


  return (
    <div className="strategiesPage">

      <div className="strategyTopbar">

        <div>
          <h2>Strategies</h2>

          <p>
            Configure automated trading
            logic. Execution is not yet
            connected.
          </p>
        </div>

        <button
          className="strategyRefresh"
          onClick={loadStrategies}
        >
          <RefreshCw size={15}/>
          Refresh
        </button>

      </div>


      <section className="strategyCreate">

        <h3>
          <Plus size={16}/>
          New Strategy
        </h3>


        <div className="strategyForm">

          <input
            placeholder="Strategy name"
            value={name}
            onChange={e =>
              setName(
                e.target.value
              )
            }
          />


          <input
            placeholder="Symbol e.g. US.AAPL"
            value={symbol}
            onChange={e =>
              setSymbol(
                e.target.value
              )
            }
          />


          <select
            value={type}
            onChange={e =>
              setType(
                e.target.value
              )
            }
          >

            <option value="MOVING_AVERAGE">
              Moving Average
            </option>

            <option value="RSI">
              RSI
            </option>

            <option value="BREAKOUT">
              Breakout
            </option>

            <option value="AI">
              AI Decision
            </option>

          </select>


          <select
            value={timeframe}
            onChange={e =>
              setTimeframe(
                e.target.value
              )
            }
          >

            <option value="1m">
              1 minute
            </option>

            <option value="5m">
              5 minutes
            </option>

            <option value="15m">
              15 minutes
            </option>

            <option value="1h">
              1 hour
            </option>

            <option value="1d">
              1 day
            </option>

          </select>


          <button
            className="strategyCreateButton"
            onClick={createStrategy}
          >
            <Plus size={15}/>
            Create
          </button>

        </div>

      </section>


      <section className="strategyList">

        <div className="strategyListHeader">

          <div>

            <h3>
              Configured Strategies
            </h3>

            <p>
              {strategies.length}
              {" "}
              configured
            </p>

          </div>


          <div className="strategySafety">

            <ShieldCheck size={14}/>

            Execution disconnected

          </div>

        </div>


        {strategies.length === 0 ? (

          <div className="strategyEmpty">

            No strategies configured.

          </div>

        ) : (

          strategies.map(strategy => (

            <div
              className="strategyCard"
              key={strategy.id}
            >

              <div className="strategyCardMain">

                <div>

                  <strong>
                    {strategy.name}
                  </strong>

                  <div className="strategyMeta">

                    <span>
                      {strategy.strategy_type}
                    </span>

                    <span>
                      {strategy.symbol}
                    </span>

                    <span>
                      {strategy.timeframe}
                    </span>

                  </div>

                </div>


                <span
                  className={
                    strategy.enabled
                      ? "strategyStatus enabled"
                      : "strategyStatus"
                  }
                >
                  {strategy.enabled
                    ? "Enabled"
                    : "Disabled"}
                </span>

              </div>


              <div className="strategyActions">

                <button
                  className={
                    strategy.enabled
                      ? "strategyToggle enabled"
                      : "strategyToggle"
                  }
                  onClick={() =>
                    toggleStrategy(
                      strategy
                    )
                  }
                >
                  {strategy.enabled
                    ? "Disable"
                    : "Enable"}
                </button>


                <button
                  className="strategyDelete"
                  onClick={() =>
                    deleteStrategy(
                      strategy
                    )
                  }
                >
                  <Trash2 size={14}/>
                </button>

              </div>

            </div>

          ))

        )}

      </section>

    </div>
  );
}
