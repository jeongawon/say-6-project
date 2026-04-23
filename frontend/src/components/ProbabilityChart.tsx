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
  DETAIL_LABELS,
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
  const detailSet = new Set(DETAIL_LABELS);

  const filterLabels = (
    tab === "cardiac"
      ? CARDIAC_LABELS
      : tab === "noncardiac"
      ? NONCARDIAC_LABELS
      : [...CARDIAC_LABELS, ...NONCARDIAC_LABELS]
  ).filter((l) => !detailSet.has(l));

  const data = filterLabels
    .map((key) => ({
      key,
      name: LABEL_KO[key] ?? key,
      prob: allProbs[key] ?? 0,
      detected: detectedSet.has(key),
    }))
    .sort((a, b) => b.prob - a.prob);

  const tabs: { key: Tab; label: string }[] = [
    { key: "all", label: "전체 22" },
    { key: "cardiac", label: "심혈관 12" },
    { key: "noncardiac", label: "비심혈관 10" },
  ];

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] font-semibold tracking-wider text-gray-500 uppercase">
          Disease Probability Distribution
        </span>
        <div className="flex gap-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1 text-[10px] font-semibold rounded border transition-colors ${
                tab === t.key
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-gray-500 border-gray-300 hover:bg-gray-50"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={Math.max(data.length * 26, 200)}>
        <BarChart data={data} layout="vertical" margin={{ left: 120, right: 40, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
          <XAxis
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            tick={{ fill: "#9ca3af", fontSize: 10 }}
            axisLine={{ stroke: "#e5e7eb" }}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fill: "#4b5563", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={115}
          />
          <Tooltip
            formatter={(value: number) => [`${(value * 100).toFixed(1)}%`, "Probability"]}
            contentStyle={{
              background: "#fff",
              border: "1px solid #e5e7eb",
              borderRadius: 6,
              fontSize: 12,
            }}
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
                    : "#d1d5db"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <div className="flex gap-4 mt-3 px-2 text-[10px] text-gray-400">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-red-500" /> Detected
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-amber-500" /> Sub-threshold (&ge;15%)
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-sm bg-gray-300" /> Low
        </span>
      </div>
    </div>
  );
}
