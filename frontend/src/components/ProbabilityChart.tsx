import { useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import {
  LABEL_KO,
  CARDIAC_LABELS,
  NONCARDIAC_LABELS,
} from "../types/ecg";
import type { Finding } from "../types/ecg";

interface Props {
  allProbs: Record<string, number>;
  findings: Finding[];
}

type Tab = "all" | "cardiac" | "noncardiac";

export default function ProbabilityChart({ allProbs, findings }: Props) {
  const [tab, setTab] = useState<Tab>("all");

  const detectedSet = new Set(findings.map((f) => f.name));

  const filterLabels =
    tab === "cardiac"
      ? CARDIAC_LABELS
      : tab === "noncardiac"
      ? NONCARDIAC_LABELS
      : [...CARDIAC_LABELS, ...NONCARDIAC_LABELS];

  const data = filterLabels
    .map((key) => ({
      key,
      name: LABEL_KO[key] ?? key,
      prob: allProbs[key] ?? 0,
      detected: detectedSet.has(key),
    }))
    .sort((a, b) => b.prob - a.prob);

  const tabs: { key: Tab; label: string }[] = [
    { key: "all", label: "전체 24" },
    { key: "cardiac", label: "심혈관 14" },
    { key: "noncardiac", label: "비심혈관 10" },
  ];

  return (
    <div className="bg-[#111827] border border-[#1e2d3d] rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-semibold tracking-widest text-slate-500 uppercase">
          Disease Probability Distribution
        </span>
        <div className="flex gap-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1 text-[10px] font-semibold rounded transition-colors ${
                tab === t.key
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:bg-slate-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={Math.max(data.length * 26, 200)}>
        <BarChart data={data} layout="vertical" margin={{ left: 120, right: 40, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2d3d" horizontal={false} />
          <XAxis
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            tick={{ fill: "#64748b", fontSize: 10 }}
            axisLine={{ stroke: "#1e2d3d" }}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fill: "#94a3b8", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={115}
          />
          <Tooltip
            formatter={(value: number) => [`${(value * 100).toFixed(1)}%`, "Probability"]}
            contentStyle={{
              background: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelStyle={{ color: "#94a3b8" }}
          />
          <Bar dataKey="prob" radius={[0, 3, 3, 0]} barSize={16}>
            {data.map((d) => (
              <Cell
                key={d.key}
                fill={
                  d.detected
                    ? "#ef4444"
                    : d.prob >= 0.15
                    ? "#f59e0b"
                    : "#334155"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <div className="flex gap-4 mt-3 px-2 text-[10px] text-slate-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-red-500" /> Detected
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-amber-500" /> Sub-threshold (&ge;15%)
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-slate-700" /> Low
        </span>
      </div>
    </div>
  );
}
