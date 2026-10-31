import { useEffect, useRef } from "react";
import { ColorType, createChart, type IChartApi } from "lightweight-charts";

interface Series {
  date: string[];
  open: (number | null)[];
  high: (number | null)[];
  low: (number | null)[];
  close: (number | null)[];
  volume: (number | null)[];
  ma5?: (number | null)[];
  ma20?: (number | null)[];
  ma60?: (number | null)[];
}

const MA_COLORS: Record<string, string> = { ma5: "#f5c542", ma20: "#4f8cff", ma60: "#c084fc" };

/** Candlestick + volume + MA5/20/60 drawn with lightweight-charts; Taiwanese colours (red up, green down). */
export function CandleChart({ series }: { series: Series | null }) {
  const el = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const chart = createChart(el.current, {
      layout: { background: { type: ColorType.Solid, color: "#171d26" }, textColor: "#8b97a8" },
      grid: { vertLines: { color: "#232c38" }, horzLines: { color: "#232c38" } },
      rightPriceScale: { borderColor: "#2a3441" },
      timeScale: { borderColor: "#2a3441" },
      crosshair: { mode: 0 },
      autoSize: true,
    });
    chartRef.current = chart;
    const candle = chart.addCandlestickSeries({
      upColor: "#ef5350", downColor: "#26a69a", borderVisible: false, wickUpColor: "#ef5350", wickDownColor: "#26a69a",
    });
    const vol = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol" });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    const mas = Object.fromEntries(
      Object.entries(MA_COLORS).map(([k, color]) => [
        k,
        chart.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false }),
      ]),
    );

    if (series) {
      const candles: any[] = [];
      const vols: any[] = [];
      const ma: Record<string, any[]> = { ma5: [], ma20: [], ma60: [] };
      series.date.forEach((t, i) => {
        const o = series.open[i], c = series.close[i];
        if (o == null || c == null) return;
        candles.push({ time: t, open: o, high: series.high[i], low: series.low[i], close: c });
        vols.push({ time: t, value: (series.volume[i] || 0) / 1000, color: c >= o ? "rgba(239,83,80,.45)" : "rgba(38,166,154,.45)" });
        for (const k of Object.keys(ma)) {
          const v = (series as any)[k]?.[i];
          if (v != null) ma[k].push({ time: t, value: v });
        }
      });
      candle.setData(candles);
      vol.setData(vols);
      for (const k of Object.keys(ma)) mas[k].setData(ma[k]);
    }
    // autoSize measures the container asynchronously; fit once now and again after the first resize
    // so the whole history is visible instead of being squeezed to the right edge.
    const fit = () => chart.timeScale().fitContent();
    fit();
    const raf = requestAnimationFrame(fit);
    const ro = new ResizeObserver(() => fit());
    ro.observe(el.current);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [series]);

  return (
    <div>
      <div ref={el} className="chart" />
      <div className="legend">
        <span style={{ color: MA_COLORS.ma5 }}>MA5</span>
        <span style={{ color: MA_COLORS.ma20 }}>MA20</span>
        <span style={{ color: MA_COLORS.ma60 }}>MA60</span>
      </div>
    </div>
  );
}
