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

  let hrColor = "text-gray-400";
  let hrStatus = "—";
  if (hr != null) {
    if (brady) {
      hrColor = "text-blue-600";
      hrStatus = "Bradycardia";
    } else if (tachy) {
      hrColor = "text-red-600";
      hrStatus = "Tachycardia";
    } else {
      hrColor = "text-emerald-600";
      hrStatus = "Normal Sinus";
    }
  } else if (irreg) {
    hrColor = "text-amber-600";
    hrStatus = "측정 불가 — 불규칙 리듬(Afib)";
  } else {
    hrStatus = "측정 불가";
  }

  return (
    <div className="grid grid-cols-2 gap-2.5">
      {/* 심박수 */}
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center relative shadow-sm">
        <p className="text-[10px] text-gray-400 tracking-widest uppercase mb-1">Heart Rate</p>
        <p className={`text-3xl font-extrabold tabular-nums ${hrColor}`}>
          {hr != null ? Math.round(hr) : "—"}
        </p>
        <p className="text-[10px] text-gray-400 mt-0.5">bpm</p>
        <p className={`text-[9px] font-semibold mt-0.5 ${hrColor}`}>{hrStatus}</p>
        {(brady || tachy) && (
          <span className="absolute top-1.5 right-1.5 text-[8px] bg-red-100 text-red-600 px-1 py-0.5 rounded font-bold">
            ALERT
          </span>
        )}
      </div>

      {/* 리듬 */}
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center shadow-sm">
        <p className="text-[10px] text-gray-400 tracking-widest uppercase mb-1">Rhythm</p>
        <p className={`text-xl font-bold mt-1.5 ${irreg ? "text-amber-600" : "text-emerald-600"}`}>
          {irreg ? "Irregular" : "Regular"}
        </p>
        <p className="text-[9px] text-gray-400 mt-1">
          {irreg ? "RR interval variability" : "Consistent RR intervals"}
        </p>
      </div>

      {/* 검출 질환 수 */}
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center shadow-sm">
        <p className="text-[10px] text-gray-400 tracking-widest uppercase mb-1">Detected</p>
        <p
          className={`text-2xl font-extrabold ${
            (numDetected ?? 0) >= 3
              ? "text-red-600"
              : (numDetected ?? 0) >= 1
              ? "text-amber-600"
              : "text-gray-400"
          }`}
        >
          {numDetected ?? 0}
        </p>
        <p className="text-[9px] text-gray-400 mt-0.5">findings</p>
      </div>

      {/* 응답 시간 */}
      <div className="bg-white border border-gray-200 rounded-lg p-3 text-center shadow-sm">
        <p className="text-[10px] text-gray-400 tracking-widest uppercase mb-1">Latency</p>
        <p className="text-2xl font-extrabold text-blue-600 tabular-nums">
          {latencyMs != null ? Math.round(latencyMs) : "—"}
        </p>
        <p className="text-[9px] text-gray-400 mt-0.5">ms</p>
      </div>
    </div>
  );
}
