/**
 * Lead II 리듬 스트립 — 병원 모니터 하단에 항상 표시되는 10초 연속 파형
 * 12-Lead 아래에 배치, Afib 불규칙/빈맥 등 리듬이 한눈에 보임
 */

const LEAD_II_INDEX = 1;

interface Props {
  signal: number[][] | null;
  heartRate: number | null;
  irregular: boolean;
}

export default function RhythmStrip({ signal, heartRate, irregular }: Props) {
  if (!signal || signal.length === 0) return null;

  const W = 1000;
  const H = 80;
  const padY = 10;
  const yMin = -1.5;
  const yMax = 1.5;

  const data = signal.map((row) => row[LEAD_II_INDEX]);
  const step = W / (data.length - 1);

  const points = data
    .map((v, i) => {
      const x = i * step;
      const clamped = Math.max(yMin, Math.min(yMax, v));
      const y = padY + ((yMax - clamped) / (yMax - yMin)) * (H - 2 * padY);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const waveColor = irregular ? "#ffa726" : "#00e676";
  const bgColor = irregular ? "#120d06" : "#060d06";

  // 1초 간격 마커 (100Hz → 100샘플 = 1초)
  const secMarkers = Array.from({ length: 11 }, (_, i) => i * (W / 10));

  return (
    <div
      className="rounded-lg border p-2"
      style={{
        background: bgColor,
        borderColor: irregular ? "#3d2a0a" : "#1a2a1a",
      }}
    >
      <div className="flex items-center justify-between mb-1 px-1">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold tracking-widest uppercase"
            style={{ color: irregular ? "#ffa726" : "#80cbc4", opacity: 0.7 }}>
            Lead II — Rhythm Strip
          </span>
          {irregular && (
            <span className="text-[9px] bg-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded font-bold">
              IRREGULAR
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[10px] text-slate-600">
          {heartRate != null && (
            <span>
              HR: <span className="text-slate-400 font-bold">{Math.round(heartRate)} bpm</span>
            </span>
          )}
          <span>10s &middot; 25mm/s</span>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 70 }}>
        {/* 1초 간격 마커 */}
        {secMarkers.map((x, i) => (
          <g key={i}>
            <line
              x1={x} y1={0} x2={x} y2={H}
              stroke={irregular ? "#2a1a08" : "#1a2a1a"}
              strokeWidth={i % 5 === 0 ? 0.8 : 0.3}
            />
            {i > 0 && i < 10 && (
              <text x={x} y={H - 2} textAnchor="middle" fontSize="7"
                fill="#374151">
                {i}s
              </text>
            )}
          </g>
        ))}
        {/* 기준선 */}
        <line
          x1={0} y1={H / 2} x2={W} y2={H / 2}
          stroke={irregular ? "#2a1a08" : "#1a2a1a"}
          strokeWidth={0.5}
        />
        {/* 파형 */}
        <polyline
          points={points}
          fill="none"
          stroke={waveColor}
          strokeWidth="1.3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}
