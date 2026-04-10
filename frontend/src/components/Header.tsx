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
    <header className="flex items-center justify-between px-5 py-2 bg-white border-b border-gray-200 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 bg-blue-600 text-white px-3 py-1.5 rounded text-sm font-bold">
          <svg viewBox="0 0 120 40" className="h-4 w-auto">
            <polyline
              points="0,20 20,20 30,5 40,35 50,10 60,30 70,20 120,20"
              fill="none"
              stroke="white"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          ECG-AI Platform
        </div>
        <nav className="flex items-center gap-1 ml-2 text-sm">
          <span className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded font-medium">
            환자 관리
          </span>
          <span className="px-3 py-1.5 bg-blue-50 text-blue-700 rounded font-semibold border border-blue-200">
            대시보드
          </span>
        </nav>
      </div>

      <div className="flex items-center gap-4 text-xs text-gray-500">
        <span className="hidden lg:inline">AI 보조 진단 도구 — 최종 판단은 담당 의사 책임</span>
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded border border-gray-200">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              online === null
                ? "bg-gray-400"
                : online
                ? "bg-emerald-500"
                : "bg-red-500 animate-pulse"
            }`}
          />
          <span className="font-medium">
            {online === null ? "확인 중" : online ? "정상" : "오프라인"}
          </span>
        </div>
      </div>
    </header>
  );
}
