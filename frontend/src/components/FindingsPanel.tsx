import type { Finding } from "../types/ecg";
import { LABEL_KO } from "../types/ecg";

interface Props {
  findings: Finding[];
}

const SEV_STYLE: Record<string, { bg: string; border: string; bar: string; badge: string }> = {
  critical: {
    bg: "bg-red-50",
    border: "border-red-300",
    bar: "bg-red-500",
    badge: "bg-red-500 text-white",
  },
  severe: {
    bg: "bg-amber-50",
    border: "border-amber-300",
    bar: "bg-amber-500",
    badge: "bg-amber-500 text-white",
  },
  moderate: {
    bg: "bg-yellow-50",
    border: "border-yellow-300",
    bar: "bg-yellow-500",
    badge: "bg-yellow-500 text-white",
  },
  mild: {
    bg: "bg-emerald-50",
    border: "border-emerald-300",
    bar: "bg-emerald-500",
    badge: "bg-emerald-500 text-white",
  },
};

export default function FindingsPanel({ findings }: Props) {
  if (findings.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg px-5 py-4 text-sm text-gray-400 shadow-sm">
        유의한 이상 소견 없음
      </div>
    );
  }

  // 상위 코드가 있으면 세부 라벨(detail) 숨김
  const DETAIL_PARENT: Record<string, string> = {
    afib_detail: "afib_flutter",
    hf_detail: "heart_failure",
  };
  const nameSet = new Set(findings.map((f) => f.name));
  const deduped = findings.filter((f) => {
    const parent = DETAIL_PARENT[f.name];
    return !parent || !nameSet.has(parent);
  });

  const sevOrder = { critical: 0, severe: 1, moderate: 2, mild: 3 };
  const sorted = [...deduped].sort(
    (a, b) =>
      (sevOrder[a.severity] ?? 4) - (sevOrder[b.severity] ?? 4) ||
      b.confidence - a.confidence
  );

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
      {/* 테이블 헤더 */}
      <div className="grid grid-cols-12 gap-2 px-4 py-2 bg-gray-50 border-b border-gray-200 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
        <div className="col-span-4">질환명</div>
        <div className="col-span-3">신뢰도</div>
        <div className="col-span-2 text-center">중증도</div>
        <div className="col-span-3">권고사항</div>
      </div>
      {/* 데이터 행 */}
      {sorted.map((f) => {
        const s = SEV_STYLE[f.severity] ?? SEV_STYLE.mild;
        const pct = Math.round(f.confidence * 100);
        return (
          <div
            key={f.name}
            className={`grid grid-cols-12 gap-2 px-4 py-2.5 border-b border-gray-100 items-center ${s.bg} hover:brightness-95 transition-colors`}
          >
            <div className="col-span-4">
              <span className="font-bold text-xs text-gray-800">
                {LABEL_KO[f.name] ?? f.name}
              </span>
            </div>
            <div className="col-span-3 flex items-center gap-2">
              <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${s.bar}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs font-bold text-gray-700 tabular-nums w-10 text-right">
                {pct}%
              </span>
            </div>
            <div className="col-span-2 text-center">
              <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${s.badge}`}>
                {f.severity.toUpperCase()}
              </span>
            </div>
            <div className="col-span-3">
              <span className="text-[10px] text-gray-500">
                {f.recommendation || "—"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
