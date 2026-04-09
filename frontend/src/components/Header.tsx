import { useEffect, useState } from "react";
import { checkHealth } from "../lib/api";

export default function Header() {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth().then(setOnline);
    const id = setInterval(() => checkHealth().then(setOnline), 15_000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="flex items-center justify-between px-6 py-3 bg-gradient-to-r from-[#0d1b2a] to-[#1b263b] border-b-2 border-blue-500/60">
      <div className="flex items-center gap-4">
        {/* ECG 아이콘 — 심전도 파형 */}
        <svg viewBox="0 0 120 40" className="h-7 w-auto">
          <polyline
            points="0,20 20,20 30,5 40,35 50,10 60,30 70,20 120,20"
            fill="none"
            stroke="#3b82f6"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <div>
          <h1 className="text-lg font-bold tracking-widest text-blue-400">
            ECG-AI
          </h1>
          <p className="text-[10px] text-slate-500 tracking-wide">
            Clinical Decision Support &middot; MIMIC-IV S6 Model
          </p>
        </div>
      </div>

      <div className="flex items-center gap-6 text-xs text-slate-500">
        <span>AI 보조 진단 도구 — 최종 판단은 담당 의사의 책임하에 수행됩니다</span>
        <div className="flex items-center gap-2">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              online === null
                ? "bg-slate-600"
                : online
                ? "bg-emerald-400"
                : "bg-red-500 animate-pulse"
            }`}
          />
          <span>{online === null ? "확인 중..." : online ? "SERVICE ONLINE" : "OFFLINE"}</span>
        </div>
      </div>
    </header>
  );
}
