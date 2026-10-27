import { useEffect, useRef } from "react";
import type { Bag, Price } from "./types";
import type * as PlotlyTypes from "plotly.js";
let plotlyPromise: Promise<any> | undefined;
const loadPlotly = () =>
  (plotlyPromise ??= import("plotly.js-dist-min").then((x) => x.default));
const colors = ["#c8ee9b", "#7c9fea", "#f2bd71", "#bc9de8", "#68c5bb"];
export default function Chart({
  prices,
  technical,
  plan,
  indicators,
  height = 390,
}: {
  prices: Price[];
  technical?: Bag;
  plan?: Bag;
  indicators: string[];
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let dead = false;
    const target = ref.current;
    if (!target || !prices.length) return;
    loadPlotly()
      .then((Plotly) => {
        if (dead) return;
        const date = prices.map((x) => x.date),
          series = technical?.series || [];
        const traces: any[] = [
          {
            type: "candlestick",
            x: date,
            open: prices.map((x) => x.open),
            high: prices.map((x) => x.high),
            low: prices.map((x) => x.low),
            close: prices.map((x) => x.close),
            name: "Price",
            increasing: {
              line: { color: "#b4d996", width: 1 },
              fillcolor: "#b4d996",
            },
            decreasing: {
              line: { color: "#d77880", width: 1 },
              fillcolor: "#d77880",
            },
            yaxis: "y",
            hoverlabel: { namelength: 12 },
          },
          {
            type: "bar",
            x: date,
            y: prices.map((x) => x.volume),
            name: "Volume",
            yaxis: "y2",
            marker: {
              color: prices.map((x) =>
                x.close >= x.open
                  ? "rgba(180,217,150,.28)"
                  : "rgba(215,120,128,.25)",
              ),
            },
            hoverinfo: "skip",
          },
        ];
        const indicatorAliases: Record<string, string[]> = {
          sma20: ["sma_20", "sma20", "SMA_20"],
          sma50: ["sma_50", "sma50", "SMA_50"],
          sma200: ["sma_200", "sma200", "SMA_200"],
          ema21: ["ema_21", "ema21", "EMA_21"],
          bb_upper: ["bb_upper", "bollinger_upper", "BB_upper"],
          bb_lower: ["bb_lower", "bollinger_lower", "BB_lower"],
        };
        indicators.forEach((key, i) => {
          const aliases = indicatorAliases[key] || [key],
            matching = aliases.find((k) =>
              series.some((r: Bag) => r[k] != null),
            );
          if (matching)
            traces.push({
              type: "scatter",
              mode: "lines",
              x: series.map((r: Bag) => r.date),
              y: series.map((r: Bag) => r[matching]),
              name: key.replace("_", " ").toUpperCase(),
              line: { color: colors[i % colors.length], width: 1.4 },
              connectgaps: false,
            });
        });
        const shapes: any[] = [];
        const annotations: any[] = [];
        const line = (
          value: number,
          color: string,
          label: string,
          dash = "dot",
        ) => {
          if (Number.isFinite(value)) {
            shapes.push({
              type: "line",
              xref: "paper",
              x0: 0,
              x1: 1,
              y0: value,
              y1: value,
              line: { color, width: 1, dash },
            });
            annotations.push({
              xref: "paper",
              x: 1,
              y: value,
              text: label,
              showarrow: false,
              xanchor: "right",
              yshift: 9,
              font: { size: 10, color },
              bgcolor: "#11181d",
            });
          }
        };
        if (indicators.includes("levels")) {
          (technical?.structure?.support || [])
            .slice(0, 2)
            .forEach((v: number) => line(v, "#587d64", "Support"));
          (technical?.structure?.resistance || [])
            .slice(0, 2)
            .forEach((v: number) => line(v, "#856b62", "Resistance"));
          if (plan?.entry_zone?.length === 2)
            shapes.push({
              type: "rect",
              xref: "paper",
              x0: 0,
              x1: 1,
              y0: plan.entry_zone[0],
              y1: plan.entry_zone[1],
              fillcolor: "rgba(199,239,144,.08)",
              line: { width: 0 },
              layer: "below",
            });
          if (plan?.stop != null) line(plan.stop, "#d77880", "Invalidation");
          (plan?.targets || []).forEach((v: number, i: number) =>
            line(v, "#b4d996", `Target ${i + 1}`),
          );
        }
        const layout: Partial<PlotlyTypes.Layout> = {
          height,
          autosize: true,
          margin: { l: 7, r: 65, t: 10, b: 25 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          font: { family: "DM Sans, sans-serif", color: "#829099", size: 11 },
          showlegend: false,
          dragmode: "pan",
          hovermode: "x unified",
          hoverlabel: {
            bgcolor: "#202a30",
            bordercolor: "#354047",
            font: { color: "#e6edec" },
          },
          xaxis: {
            rangeslider: { visible: false },
            showgrid: false,
            zeroline: false,
            type: "date",
            tickformat: "%b %d",
            showspikes: true,
            spikecolor: "#6b7980",
            spikethickness: 1,
            rangebreaks: [{ bounds: ["sat", "mon"] }],
            anchor: "y2",
          },
          yaxis: {
            domain: [0.22, 1],
            side: "right",
            gridcolor: "#20292e",
            zeroline: false,
            tickprefix: "",
            fixedrange: false,
          },
          yaxis2: {
            domain: [0, 0.15],
            side: "right",
            showgrid: false,
            zeroline: false,
            tickformat: ".2s",
          },
          shapes,
          annotations,
        };
        Plotly.react(target, traces, layout, {
          responsive: true,
          displayModeBar: false,
          scrollZoom: false,
        });
      })
      .catch(() => {
        if (target)
          target.textContent =
            "Chart could not load. Price data is still available in the analysis.";
      });
    const observer = new ResizeObserver(() => {
      loadPlotly()
        .then((p) => {
          if (!dead && target) p.Plots.resize(target);
        })
        .catch(() => {});
    });
    observer.observe(target);
    return () => {
      dead = true;
      observer.disconnect();
      loadPlotly()
        .then((p) => {
          if (target) p.purge(target);
        })
        .catch(() => {});
    };
  }, [prices, technical, plan, indicators, height]);
  return (
    <div
      ref={ref}
      className="plot"
      style={{ minHeight: height }}
      role="img"
      aria-label="Interactive stock candlestick chart with daily volume and selected indicators"
    />
  );
}
export function EquityChart({ rows }: { rows: Bag[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const target = ref.current;
    if (!target || !rows.length) return;
    let dead = false;
    loadPlotly()
      .then((p) => {
        if (dead) return;
        const traces: any[] = [
          {
            x: rows.map((r) => r.date),
            y: rows.map((r) => r.equity),
            type: "scatter",
            mode: "lines",
            name: "Strategy",
            fill: "tozeroy",
            fillcolor: "rgba(199,239,144,.06)",
            line: { color: "#c7ef90", width: 2 },
          },
        ];
        for (const [key, label, color] of [
          ["buy_and_hold", "Buy & hold", "#8296b5"],
          ["benchmark", "Index benchmark", "#a68ec0"],
        ]) {
          if (rows.some((r) => r[key] != null))
            traces.push({
              x: rows.map((r) => r.date),
              y: rows.map((r) => r[key]),
              type: "scatter",
              mode: "lines",
              name: label,
              line: { color, width: 1.5 },
            });
        }
        p.react(
          target,
          traces,
          {
            height: 330,
            margin: { l: 30, r: 55, t: 15, b: 35 },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: { family: "DM Sans", color: "#8b989f" },
            xaxis: { showgrid: false },
            yaxis: { gridcolor: "#243038", side: "right", tickprefix: "" },
            legend: { orientation: "h", y: 1.12 },
            hovermode: "x unified",
          },
          { responsive: true, displayModeBar: false },
        );
      })
      .catch(() => {});
    const observer = new ResizeObserver(() =>
      loadPlotly().then((p) => {
        if (!dead) p.Plots.resize(target);
      }),
    );
    observer.observe(target);
    return () => {
      dead = true;
      observer.disconnect();
      loadPlotly().then((p) => p.purge(target));
    };
  }, [rows]);
  return (
    <div
      ref={ref}
      role="img"
      aria-label="Historical strategy and benchmark equity curves"
    />
  );
}
