import type { Finding } from "../types/ecg";
import { LABEL_KO } from "../types/ecg";

interface Props {
  findings: Finding[];
}

const SEV_STYLE: Record<string, { bg: string; border: string; bar: string; badge: string; badgeBg: string }> = {
  critical: {
    bg: "bg-red-950/30",
    border: "border-red-500/60",
    bar: "bg-red-500",
    badge: "text-white",
    badgeBg: "bg-red-500",
  },
  severe: {
    bg: "bg-amber-950/20",
    border: "border-amber-500/50",
    bar: "bg-amber-500",
    badge: "text-black",
    badgeBg: "bg-amber-500",
  },
  moderate: {
    bg: "bg-yellow-950/15",
    border: "border-yellow-500/40",
    bar: "bg-yellow-400",
    badge: "text-black",
    badgeBg: "bg-yellow-400",
  },
  mild: {
    bg: "bg-emerald-950/15",
    border: "border-emerald-500/30",
    bar: "bg-emerald-500",
    badge: "text-black",
    badgeBg: "bg-emerald-500",
  },
};

export default function FindingsPanel({ findings }: Props) {
  if (findings.length === 0) {
    return (
      <div className="bg-slate-800/30 border border-slate-700 rounded-lg px-5 py-4 text-sm text-slate-500">
        유의한 이상 소견 없음
      </div>
    );
  }

  const sevOrder = { critical: 0, severe: 1, moderate: 2, mild: 3 };
  const sorted = [...findings].sort(
    (a, b) =>
      (sevOrder[a.severity] ?? 4) - (sevOrder[b.severity] ?? 4) ||
      b.confidence - a.confidence
  );

  return (
    <div className="space-y-2">
      {sorted.map((f) => {
        const s = SEV_STYLE[f.severity] ?? SEV_STYLE.mild;
        const pct = Math.round(f.confidence * 100);
        return (
          <div
            key={f.name}
            className={`${s.bg} border ${s.border} rounded-lg px-4 py-3`}
          >
            <div className="flex items-center justify-between">
              <span className="font-bold text-sm text-gray-100">
                {LABEL_KO[f.name] ?? f.name}
              </span>
              <div className="flex items-center gap-2">
                <span
                  className={`text-[10px] font-bold px-2 py-0.5 rounded ${s.badge} ${s.badgeBg}`}
                >
                  {f.severity.toUpperCase()}
                </span>
                <span className={`text-sm font-bold tabular-nums ${s.bar.replace("bg-", "text-")}`}>
                  {pct}%
                </span>
              </div>
            </div>
            {/* confidence bar */}
            <div className="mt-2 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${s.bar}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            {f.recommendation && (
              <p className="mt-2 text-xs text-slate-400">
                <span className="text-slate-600 mr-1">Rx</span>
                {f.recommendation}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
