/**
 * Lead II 리듬 스트립 — 병원 베드사이드 모니터 스타일
 * 왼쪽에서 오른쪽으로 파형이 그려나가는 실시간 애니메이션
 * 10초 파형을 반복 재생
 */

import { useEffect, useRef, useState } from "react";

const LEAD_II_INDEX = 1;

interface Props {
  signal: number[][] | null;
  heartRate: number | null;
  irregular: boolean;
}

export default function RhythmStrip({ signal, heartRate, irregular }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const [drawing, setDrawing] = useState(false);

  const waveColor = irregular ? "#ffa726" : "#00e676";
  const gridColor = irregular ? "#2a1a08" : "#1a2a1a";
  const bgColor = irregular ? "#120d06" : "#060d06";
  const sweepColor = irregular ? "#3d2a0a" : "#0a200a";

  useEffect(() => {
    if (!signal || signal.length === 0) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const data = signal.map((row) => row[LEAD_II_INDEX]);
    const W = canvas.width;
    const H = canvas.height;
    const padY = 8;
    const yMin = -1.5;
    const yMax = 1.5;

    // 초당 픽셀 (10초 데이터를 W 픽셀에 표시, 실시간은 3초에 한 바퀴)
    const totalDuration = 4000; // 4초에 전체 파형 한 바퀴
    const pxPerMs = W / totalDuration;

    let startTime: number | null = null;
    setDrawing(true);

    function yPos(v: number) {
      const clamped = Math.max(yMin, Math.min(yMax, v));
      return padY + ((yMax - clamped) / (yMax - yMin)) * (H - 2 * padY);
    }

    function drawGrid() {
      ctx!.fillStyle = bgColor;
      ctx!.fillRect(0, 0, W, H);

      // 수평 격자
      ctx!.strokeStyle = gridColor;
      for (let i = 0; i <= 8; i++) {
        ctx!.lineWidth = i % 4 === 0 ? 0.6 : 0.2;
        ctx!.beginPath();
        ctx!.moveTo(0, (i * H) / 8);
        ctx!.lineTo(W, (i * H) / 8);
        ctx!.stroke();
      }

      // 1초 간격 수직선
      for (let i = 0; i <= 10; i++) {
        const x = (i * W) / 10;
        ctx!.lineWidth = i % 5 === 0 ? 0.6 : 0.2;
        ctx!.beginPath();
        ctx!.moveTo(x, 0);
        ctx!.lineTo(x, H);
        ctx!.stroke();

        // 초 라벨
        if (i > 0 && i < 10) {
          ctx!.fillStyle = "#374151";
          ctx!.font = "8px monospace";
          ctx!.textAlign = "center";
          ctx!.fillText(`${i}s`, x, H - 2);
        }
      }

      // 기준선
      ctx!.strokeStyle = gridColor;
      ctx!.lineWidth = 0.5;
      ctx!.beginPath();
      ctx!.moveTo(0, H / 2);
      ctx!.lineTo(W, H / 2);
      ctx!.stroke();
    }

    function animate(timestamp: number) {
      if (!startTime) startTime = timestamp;
      const elapsed = (timestamp - startTime) % totalDuration;
      const drawUpto = Math.floor((elapsed * data.length) / totalDuration);

      drawGrid();

      // 스윕 바 (현재 위치 뒤에 어두운 영역)
      const curX = (drawUpto / data.length) * W;
      const sweepW = W * 0.06;
      const grad = ctx!.createLinearGradient(curX, 0, curX + sweepW, 0);
      grad.addColorStop(0, "transparent");
      grad.addColorStop(0.5, sweepColor);
      grad.addColorStop(1, "transparent");
      ctx!.fillStyle = grad;
      ctx!.fillRect(curX, 0, sweepW, H);

      // 파형 그리기
      if (drawUpto > 1) {
        ctx!.strokeStyle = waveColor;
        ctx!.lineWidth = 1.8;
        ctx!.lineJoin = "round";
        ctx!.lineCap = "round";
        ctx!.beginPath();
        const step = W / (data.length - 1);
        ctx!.moveTo(0, yPos(data[0]));
        for (let i = 1; i <= drawUpto; i++) {
          ctx!.lineTo(i * step, yPos(data[i]));
        }
        ctx!.stroke();

        // 현재 포인트에 글로우 효과
        const tipX = drawUpto * step;
        const tipY = yPos(data[drawUpto]);
        ctx!.beginPath();
        ctx!.arc(tipX, tipY, 3, 0, Math.PI * 2);
        ctx!.fillStyle = waveColor;
        ctx!.fill();

        // 글로우
        ctx!.beginPath();
        ctx!.arc(tipX, tipY, 6, 0, Math.PI * 2);
        ctx!.fillStyle = waveColor + "40";
        ctx!.fill();
      }

      animRef.current = requestAnimationFrame(animate);
    }

    animRef.current = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(animRef.current);
      setDrawing(false);
    };
  }, [signal, irregular, waveColor, gridColor, bgColor, sweepColor]);

  if (!signal || signal.length === 0) return null;

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
          <span
            className="text-[10px] font-semibold tracking-widest uppercase"
            style={{ color: irregular ? "#ffa726" : "#80cbc4", opacity: 0.7 }}
          >
            Lead II — Rhythm Strip
          </span>
          {irregular && (
            <span className="text-[9px] bg-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded font-bold">
              IRREGULAR
            </span>
          )}
          {drawing && (
            <span className="flex items-center gap-1 text-[9px] text-slate-600">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              LIVE
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[10px] text-slate-600">
          {heartRate != null && (
            <span>
              HR:{" "}
              <span className="text-slate-400 font-bold">
                {Math.round(heartRate)} bpm
              </span>
            </span>
          )}
          <span>10s &middot; 25mm/s</span>
        </div>
      </div>

      <canvas
        ref={canvasRef}
        width={1000}
        height={80}
        className="w-full rounded"
        style={{ height: 70 }}
      />
    </div>
  );
}
