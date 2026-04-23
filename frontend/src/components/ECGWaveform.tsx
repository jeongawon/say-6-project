/**
 * 12-Lead ECG 파형 시각화 — 병원 모니터 스타일
 * 3행 x 4열 임상 표준 레이아웃
 * 검정 배경 + 녹색 파형 + 밀리미터 격자
 * 이상 소견 발견 리드 강조 표시
 */

import type { Finding } from "../types/ecg";
import { LABEL_KO } from "../types/ecg";

const LEAD_LAYOUT: string[][] = [
  ["I", "aVR", "V1", "V4"],
  ["II", "aVL", "V2", "V5"],
  ["III", "aVF", "V3", "V6"],
];

const LEAD_INDEX: Record<string, number> = {
  I: 0, II: 1, V1: 2, V2: 3, V3: 4, V4: 5, V5: 6, V6: 7,
  III: 8, aVR: 9, aVL: 10, aVF: 11,
};

/**
 * 질환별 이상이 주로 관찰되는 리드 매핑
 * 해당 리드에 빨간색 테두리 + 라벨 표시
 */
const DISEASE_LEAD_MAP: Record<string, string[]> = {
  acute_mi:               ["II", "III", "aVF", "V1", "V2", "V3", "V4"],
  afib_flutter:           ["II", "V1"],
  afib_detail:            ["II", "V1"],
  heart_failure:          ["V5", "V6", "I", "aVL"],
  hf_detail:              ["V5", "V6", "I", "aVL"],
  av_block_lbbb:          ["II", "V1", "V6"],
  hypertension:           ["I", "aVL", "V5", "V6"],
  paroxysmal_tachycardia: ["II", "V1"],
  other_conduction:       ["V1", "V2", "II"],
  hyperkalemia:           ["II", "V2", "V3", "V4"],
  hypokalemia:            ["II", "V3", "V4"],
  pulmonary_embolism:     ["III", "aVF", "V1"],
  cardiac_arrest:         ["II"],
  angina:                 ["V3", "V4", "V5"],
  pericardial_disease:    ["II", "V5", "V6"],
  chronic_ihd:            ["V4", "V5", "V6", "I", "aVL"],
};

interface Props {
  signal: number[][] | null;
  findings?: Finding[];
}

function LeadTrace({
  name,
  data,
  alert,
  alertLabels,
}: {
  name: string;
  data: number[];
  alert: boolean;
  alertLabels: string[];
}) {
  const W = 240;
  const H = 80;
  const padY = 8;
  const yMin = -1.5;
  const yMax = 1.5;
  const step = W / (data.length - 1);

  const points = data
    .map((v, i) => {
      const x = i * step;
      const clamped = Math.max(yMin, Math.min(yMax, v));
      const y = padY + ((yMax - clamped) / (yMax - yMin)) * (H - 2 * padY);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={`w-full h-full rounded ${
          alert
            ? "bg-[#120808] ring-1 ring-red-500/60"
            : "bg-[#0a0f0a]"
        }`}
      >
        {/* 밀리미터 격자 */}
        {Array.from({ length: 25 }, (_, i) => (
          <line
            key={`vg${i}`}
            x1={(i * W) / 24} y1={0}
            x2={(i * W) / 24} y2={H}
            stroke={alert ? "#2a1616" : "#162016"}
            strokeWidth={i % 5 === 0 ? 0.8 : 0.3}
          />
        ))}
        {Array.from({ length: 9 }, (_, i) => (
          <line
            key={`hg${i}`}
            x1={0} y1={(i * H) / 8}
            x2={W} y2={(i * H) / 8}
            stroke={alert ? "#2a1616" : "#162016"}
            strokeWidth={i % 4 === 0 ? 0.8 : 0.3}
          />
        ))}
        {/* 기준선 */}
        <line
          x1={0} y1={H / 2} x2={W} y2={H / 2}
          stroke={alert ? "#3a1e1e" : "#1e3a1e"}
          strokeWidth={0.5}
        />
        {/* 파형 */}
        <polyline
          points={points}
          fill="none"
          stroke={alert ? "#ff5252" : "#00e676"}
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {/* 리드 라벨 */}
      <span
        className={`absolute top-1 left-2 text-[10px] font-bold ${
          alert ? "text-red-400" : "text-teal-300/80"
        }`}
      >
        {name}
      </span>
      {/* 이상 소견 라벨 */}
      {alert && alertLabels.length > 0 && (
        <div className="absolute bottom-0.5 right-1 flex gap-0.5">
          {alertLabels.slice(0, 2).map((label) => (
            <span
              key={label}
              className="text-[7px] bg-red-500/80 text-white px-1 py-px rounded font-bold leading-tight"
            >
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ECGWaveform({ signal, findings = [] }: Props) {
  if (!signal || signal.length === 0) {
    return (
      <div className="bg-[#0a0f0a] rounded-lg border border-[#1a2a1a] p-8 text-center text-slate-600">
        <svg viewBox="0 0 120 40" className="h-8 w-auto mx-auto mb-2 opacity-30">
          <polyline
            points="0,20 20,20 30,5 40,35 50,10 60,30 70,20 120,20"
            fill="none"
            stroke="#4b5563"
            strokeWidth="2"
          />
        </svg>
        <p className="text-sm">분석 실행 후 ECG 파형이 표시됩니다</p>
      </div>
    );
  }

  // 이상 소견이 관찰되는 리드 매핑
  const alertLeads = new Map<string, string[]>();
  for (const f of findings) {
    const leads = DISEASE_LEAD_MAP[f.name];
    if (leads) {
      for (const lead of leads) {
        const existing = alertLeads.get(lead) || [];
        const koName = LABEL_KO[f.name] ?? f.name;
        if (!existing.includes(koName)) {
          existing.push(koName);
        }
        alertLeads.set(lead, existing);
      }
    }
  }

  return (
    <div className="bg-[#060d06] rounded-lg border border-[#1a2a1a] p-3">
      <div className="flex items-center justify-between mb-2 px-1">
        <span className="text-[10px] font-semibold tracking-widest text-teal-400/60 uppercase">
          12-Lead ECG
        </span>
        <div className="flex items-center gap-4">
          {alertLeads.size > 0 && (
            <span className="text-[10px] text-red-400 font-semibold flex items-center gap-1">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              {alertLeads.size} leads with abnormality
            </span>
          )}
          <span className="text-[10px] text-slate-600">
            100Hz &middot; 10s &middot; 25mm/s &middot; 10mm/mV
          </span>
        </div>
      </div>
      <div className="grid grid-cols-4 gap-1">
        {LEAD_LAYOUT.flat().map((lead) => {
          const idx = LEAD_INDEX[lead];
          const data = signal.map((row) => row[idx]);
          const isAlert = alertLeads.has(lead);
          const labels = alertLeads.get(lead) || [];
          return (
            <LeadTrace
              key={lead}
              name={lead}
              data={data}
              alert={isAlert}
              alertLabels={labels}
            />
          );
        })}
      </div>
      {/* 범례 */}
      {alertLeads.size > 0 && (
        <div className="flex gap-4 mt-2 px-1 text-[9px] text-slate-500">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-[#00e676] rounded" /> Normal
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-red-500 rounded" /> Abnormality detected
          </span>
        </div>
      )}
    </div>
  );
}
