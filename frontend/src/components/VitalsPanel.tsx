import type { ECGVitals } from "../types/ecg";

interface Props {
  vitals: ECGVitals | null;
  latencyMs?: number;
  numDetected?: number;
}

export default function VitalsPanel({ vitals, latencyMs, numDetected }: Props) {
  const hr = vitals?.heart_rate;
  const brady = vitals?.bradycardia ?? false;
  const tachy = vitals?.tachycardia ?? false;
  const irreg = vitals?.irregular_rhythm ?? false;

  let hrColor = "text-slate-400";
  let hrStatus = "—";
  if (hr != null) {
    if (brady) {
      hrColor = "text-blue-400";
      hrStatus = "Bradycardia";
    } else if (tachy) {
      hrColor = "text-red-400";
      hrStatus = "Tachycardia";
    } else {
      hrColor = "text-emerald-400";
      hrStatus = "Normal Sinus";
    }
  } else if (irreg) {
    hrColor = "text-amber-400";
    hrStatus = "측정 불가 — 불규칙 리듬(Afib)";
  } else {
    hrStatus = "측정 불가";
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* 심박수 */}
      <div className="bg-[#111827] border border-[#1e2d3d] rounded-lg p-4 text-center relative overflow-hidden">
        <p className="text-[10px] text-slate-500 tracking-widest uppercase mb-1">Heart Rate</p>
        <p className={`text-4xl font-extrabold tabular-nums ${hrColor}`}>
          {hr != null ? Math.round(hr) : "—"}
        </p>
        <p className="text-xs text-slate-500 mt-1">bpm</p>
        <p className={`text-[10px] font-semibold mt-1 ${hrColor}`}>{hrStatus}</p>
        {(brady || tachy) && (
          <span className="absolute top-2 right-2 text-[9px] bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded font-bold">
            ALERT
          </span>
        )}
      </div>

      {/* 리듬 */}
      <div className="bg-[#111827] border border-[#1e2d3d] rounded-lg p-4 text-center">
        <p className="text-[10px] text-slate-500 tracking-widest uppercase mb-1">Rhythm</p>
        <p className={`text-2xl font-bold mt-2 ${irreg ? "text-amber-400" : "text-emerald-400"}`}>
          {irreg ? "Irregular" : "Regular"}
        </p>
        <p className="text-[10px] text-slate-500 mt-2">
          {irreg ? "RR interval variability detected" : "Consistent RR intervals"}
        </p>
      </div>

      {/* 검출 질환 수 */}
      <div className="bg-[#111827] border border-[#1e2d3d] rounded-lg p-4 text-center">
        <p className="text-[10px] text-slate-500 tracking-widest uppercase mb-1">Detected</p>
        <p
          className={`text-3xl font-extrabold ${
            (numDetected ?? 0) >= 3
              ? "text-red-400"
              : (numDetected ?? 0) >= 1
              ? "text-amber-400"
              : "text-slate-500"
          }`}
        >
          {numDetected ?? 0}
        </p>
        <p className="text-[10px] text-slate-500 mt-1">findings</p>
      </div>

      {/* 응답 시간 */}
      <div className="bg-[#111827] border border-[#1e2d3d] rounded-lg p-4 text-center">
        <p className="text-[10px] text-slate-500 tracking-widest uppercase mb-1">Latency</p>
        <p className="text-3xl font-extrabold text-blue-400 tabular-nums">
          {latencyMs != null ? Math.round(latencyMs) : "—"}
        </p>
        <p className="text-[10px] text-slate-500 mt-1">ms</p>
      </div>
    </div>
  );
}
