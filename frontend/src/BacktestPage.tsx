import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  FlaskConical,
  LoaderCircle,
  LineChart,
  ShieldCheck,
} from "lucide-react";
import { post } from "./api";
import type { Bag } from "./types";
import { EquityChart } from "./Chart";
import {
  PageIntro,
  Empty,
  ErrorBox,
  Badge,
  SectionHeading,
  MetricGrid,
  Limitations,
  Evidence,
  DataTable,
  dateOnly,
  strings,
} from "./ui";
export default function BacktestPage({
  initialTicker,
}: {
  initialTicker: string;
}) {
  const [symbol, setSymbol] = useState(initialTicker),
    [capital, setCapital] = useState(10000),
    [period, setPeriod] = useState("5y"),
    [fast, setFast] = useState(20),
    [slow, setSlow] = useState(50),
    [commission, setCommission] = useState(5),
    [slippage, setSlippage] = useState(5),
    [risk, setRisk] = useState(1);
  const test = useMutation({
    mutationFn: () =>
      post<Bag>("/backtest", {
        ticker: symbol.toUpperCase(),
        period,
        starting_capital: capital,
        commission_bps: commission,
        slippage_bps: slippage,
        risk_per_trade: risk / 100,
        fast_period: fast,
        slow_period: slow,
      }),
  });
  const result = test.data;
  return (
    <>
      <PageIntro
        eyebrow="TEST THE RULES, CHALLENGE THE STORY"
        title="Strategy lab"
        subtitle="Explore historical behavior with explicit execution costs and no future information."
      />
      <div className="backtest-grid">
        <section className="panel backtest-form">
          <SectionHeading title="Configure a backtest">
            <FlaskConical size={18} />
          </SectionHeading>
          <p className="panel-footnote">
            Moving average crossover · Signals at close, execution at the next
            available open.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              test.mutate();
            }}
          >
            <div className="form-grid">
              <label>
                Ticker
                <input
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                  required
                  maxLength={32}
                />
              </label>
              <label>
                History window
                <select
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                >
                  <option value="1y">1 year</option>
                  <option value="5y">5 years</option>
                  <option value="max">Maximum available</option>
                </select>
              </label>
              <label>
                Starting capital (quote currency)
                <input
                  type="number"
                  min="100"
                  max="1000000000"
                  value={capital}
                  required
                  onChange={(e) => setCapital(Number(e.target.value))}
                />
              </label>
              <label>
                Risk per trade (%)
                <input
                  type="number"
                  min="0.01"
                  max="5"
                  step="0.01"
                  value={risk}
                  required
                  onChange={(e) => setRisk(Number(e.target.value))}
                />
              </label>
              <label>
                Fast average (days)
                <input
                  type="number"
                  min="2"
                  max="199"
                  value={fast}
                  required
                  onChange={(e) => setFast(Number(e.target.value))}
                />
              </label>
              <label>
                Slow average (days)
                <input
                  type="number"
                  min={fast + 1}
                  max="250"
                  value={slow}
                  required
                  onChange={(e) => setSlow(Number(e.target.value))}
                />
              </label>
              <label>
                Commission (bps)
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={commission}
                  required
                  onChange={(e) => setCommission(Number(e.target.value))}
                />
              </label>
              <label>
                Slippage (bps)
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={slippage}
                  required
                  onChange={(e) => setSlippage(Number(e.target.value))}
                />
              </label>
            </div>
            <button
              className="button primary full-width"
              disabled={test.isPending || fast >= slow}
            >
              {test.isPending ? (
                <LoaderCircle size={15} className="spin" />
              ) : (
                <FlaskConical size={15} />
              )}
              Run historical test
            </button>
          </form>
          <div className="notice compact-notice">
            <ShieldCheck size={16} />
            <p>
              Current financial statements, news and revised economic actuals
              are excluded without reliable point-in-time history.
            </p>
          </div>
        </section>
        <section className="panel backtest-results">
          <SectionHeading title="Historical performance">
            <Badge>Not a forecast</Badge>
          </SectionHeading>
          {test.isError ? (
            <ErrorBox error={test.error} />
          ) : test.isPending ? (
            <Empty
              title="Running the historical simulation"
              icon={<LoaderCircle size={28} className="spin" />}
            >
              Retrieving prices and applying next-bar execution, trading costs
              and position-size rules.
            </Empty>
          ) : result ? (
            <>
              <MetricGrid metrics={result.metrics || {}} />
              {result.equity_curve?.length > 0 && (
                <EquityChart rows={result.equity_curve} />
              )}
              <Limitations items={result.limitations} />
            </>
          ) : (
            <Empty
              title="Put your assumptions to the test"
              icon={<LineChart size={32} />}
            >
              Choose a stock, history window and execution assumptions to
              compare a systematic rule with buy-and-hold and the available
              index benchmark.
            </Empty>
          )}
        </section>
      </div>
      {result && (
        <>
          <section className="panel validation-panel">
            <SectionHeading title="Out-of-sample & validation" />
            {result.validation ? (
              <>
                <Evidence
                  items={[
                    result.validation.signal_timing,
                    result.validation.stop_timing,
                    result.validation.point_in_time,
                    ...strings(result.validation.notes),
                  ].filter(Boolean)}
                />
                {result.validation.out_of_sample && (
                  <>
                    <h3 className="subsection-title">
                      Holdout period from{" "}
                      {dateOnly(result.validation.out_of_sample.start)}
                    </h3>
                    <p className="panel-footnote">
                      {result.validation.out_of_sample.method}
                    </p>
                    <MetricGrid
                      metrics={result.validation.out_of_sample.metrics || {}}
                    />
                  </>
                )}
                {result.validation.walk_forward?.length > 0 && (
                  <>
                    <h3 className="subsection-title">
                      Chronological walk-forward windows
                    </h3>
                    <p className="panel-footnote">
                      Each window uses fixed parameters and fresh capital.
                      Earlier prices supply indicator warmup; no parameter
                      optimization is performed.
                    </p>
                    <DataTable
                      rows={result.validation.walk_forward.map((fold: Bag) => ({
                        start: dateOnly(fold.start),
                        end: dateOnly(fold.end),
                        total_return: fold.metrics?.total_return,
                        maximum_drawdown: fold.metrics?.maximum_drawdown,
                        sharpe_ratio: fold.metrics?.sharpe_ratio,
                        number_of_trades: fold.metrics?.number_of_trades,
                        win_rate: fold.metrics?.win_rate,
                      }))}
                    />
                  </>
                )}
              </>
            ) : (
              <p className="muted">
                No out-of-sample validation was returned for this run.
              </p>
            )}
          </section>
          <section className="panel trades-panel">
            <SectionHeading title="Trade ledger">
              <Badge>{result.trades?.length || 0} completed trades</Badge>
            </SectionHeading>
            {result.trades?.length ? (
              <DataTable rows={result.trades} />
            ) : (
              <p className="muted">
                No completed trades under these rules and history window.
              </p>
            )}
          </section>
        </>
      )}
    </>
  );
}
