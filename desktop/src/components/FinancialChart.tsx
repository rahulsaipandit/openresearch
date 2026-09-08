import { useRef } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";

// Frontend Component Requirement #1 (requirements.md): a multi-series chart
// supporting line/bar/area/scatter against a typed series schema, with PNG
// export. Backs both the trend view (#7) and comparison view (#3).

export type ChartType = "line" | "bar" | "area" | "scatter";

export interface SeriesPoint {
  x: string | number;
  y: number;
  size?: number;
  label?: string;
}

export interface DataSeries {
  name: string;
  color?: string;
  data: SeriesPoint[];
}

interface FinancialChartProps {
  type: ChartType;
  series: DataSeries[];
  height?: number;
  yLabel?: string;
}

const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed"];

/** Merge multiple series sharing an x-axis into one row-per-x array for Recharts. */
function mergeSeries(series: DataSeries[]) {
  const byX = new Map<string | number, Record<string, unknown>>();
  for (const s of series) {
    for (const point of s.data) {
      const row = byX.get(point.x) ?? { x: point.x };
      row[s.name] = point.y;
      byX.set(point.x, row);
    }
  }
  return Array.from(byX.values());
}

export function FinancialChart({ type, series, height = 320, yLabel }: FinancialChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const merged = mergeSeries(series);
  const chartProps = { data: merged, margin: { top: 8, right: 16, left: 0, bottom: 0 } };

  async function exportPng() {
    const svg = containerRef.current?.querySelector("svg");
    if (!svg) return;

    const xml = new XMLSerializer().serializeToString(svg);
    const svgBlob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);

    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = svg.clientWidth;
      canvas.height = svg.clientHeight;
      const ctx = canvas.getContext("2d");
      URL.revokeObjectURL(url);
      if (!ctx) return;

      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);

      const a = document.createElement("a");
      a.href = canvas.toDataURL("image/png");
      a.download = `chart-${series.map((s) => s.name).join("-")}.png`;
      a.click();
    };
    img.src = url;
  }

  return (
    <div className="financial-chart">
      <div ref={containerRef} style={{ width: "100%", height }}>
        <ResponsiveContainer width="100%" height="100%">
          {type === "line" ? (
            <LineChart {...chartProps}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="x" />
              <YAxis label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft" } : undefined} />
              <Tooltip />
              <Legend />
              {series.map((s, i) => (
                <Line
                  key={s.name}
                  type="monotone"
                  dataKey={s.name}
                  stroke={s.color ?? PALETTE[i % PALETTE.length]}
                  dot={false}
                />
              ))}
            </LineChart>
          ) : type === "bar" ? (
            <BarChart {...chartProps}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="x" />
              <YAxis label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft" } : undefined} />
              <Tooltip />
              <Legend />
              {series.map((s, i) => (
                <Bar key={s.name} dataKey={s.name} fill={s.color ?? PALETTE[i % PALETTE.length]} />
              ))}
            </BarChart>
          ) : type === "area" ? (
            <AreaChart {...chartProps}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="x" />
              <YAxis label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft" } : undefined} />
              <Tooltip />
              <Legend />
              {series.map((s, i) => (
                <Area
                  key={s.name}
                  type="monotone"
                  dataKey={s.name}
                  stroke={s.color ?? PALETTE[i % PALETTE.length]}
                  fill={s.color ?? PALETTE[i % PALETTE.length]}
                  fillOpacity={0.2}
                />
              ))}
            </AreaChart>
          ) : (
            <ScatterChart {...chartProps}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="x" />
              <YAxis label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft" } : undefined} />
              <Tooltip />
              <Legend />
              {series.map((s, i) => (
                <Scatter key={s.name} name={s.name} data={s.data} fill={s.color ?? PALETTE[i % PALETTE.length]} />
              ))}
            </ScatterChart>
          )}
        </ResponsiveContainer>
      </div>
      <button type="button" className="chart-export-btn" onClick={exportPng}>
        Export PNG
      </button>
    </div>
  );
}
