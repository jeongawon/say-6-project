import { useNavigate } from "react-router-dom";
import { DEMO_PATIENTS } from "../lib/demo-patients";
import type { DemoPatient } from "../types/ecg";

const STATUS_TAGS: Record<number, { label: string; style: string }> = {
  0: { label: "Active", style: "bg-white/20 text-white" },
  1: { label: "Waiting", style: "bg-surface-container-high text-on-surface-variant" },
  2: { label: "Reviewing", style: "bg-surface-container-high text-on-surface-variant" },
  3: { label: "Stable", style: "bg-surface-container-high text-on-surface-variant" },
  4: { label: "Pending", style: "bg-surface-container-high text-on-surface-variant" },
};

const SEVERITY_TAGS: Record<number, { label: string; style: string }> = {
  0: { label: "Critical", style: "bg-tertiary-container text-white" },
  1: { label: "Urgent", style: "bg-amber-500 text-white" },
  2: { label: "Moderate", style: "bg-yellow-500 text-white" },
  3: { label: "Stable", style: "bg-emerald-500 text-white" },
  4: { label: "Pending", style: "bg-gray-400 text-white" },
};

export default function MonitorPage() {
  const navigate = useNavigate();

  function handleSelect(p: DemoPatient, idx: number) {
    navigate("/dashboard", { state: { patient: p, patientIdx: idx } });
  }

  return (
    <div className="space-y-8">
      {/* Title */}
      <div>
        <h2 className="text-2xl font-extrabold tracking-tight text-on-surface">Live Patient Monitor</h2>
        <p className="text-sm text-on-surface-variant mt-1">
          실시간 환자 큐 — 환자를 선택하면 ECG AI 분석 대시보드로 이동합니다
        </p>
      </div>

      {/* Summary Cards */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border-b-2 border-primary">
          <p className="text-on-surface-variant text-[10px] font-bold tracking-widest uppercase mb-1">Total Queue</p>
          <span className="text-4xl font-black text-on-surface">{DEMO_PATIENTS.length}</span>
          <span className="text-xs text-on-surface-variant font-bold ml-2">Patients</span>
        </div>
        <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border-b-2 border-tertiary">
          <p className="text-on-surface-variant text-[10px] font-bold tracking-widest uppercase mb-1">Critical</p>
          <span className="text-4xl font-black text-tertiary">2</span>
          <span className="text-xs text-on-surface-variant font-bold ml-2">Cases</span>
        </div>
        <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border-b-2 border-secondary">
          <p className="text-on-surface-variant text-[10px] font-bold tracking-widest uppercase mb-1">Analyzed</p>
          <span className="text-4xl font-black text-secondary">0</span>
          <span className="text-xs text-on-surface-variant font-bold ml-2">Complete</span>
        </div>
        <div className="bg-surface-container-lowest p-6 rounded-xl shadow-sm border-b-2 border-primary">
          <p className="text-on-surface-variant text-[10px] font-bold tracking-widest uppercase mb-1">System</p>
          <span className="text-2xl font-black text-on-surface">Ready</span>
        </div>
      </section>

      {/* Patient Queue - Horizontal Scroll */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Live Patient Queue</h3>
          <span className="text-primary text-xs font-bold">View All ({DEMO_PATIENTS.length})</span>
        </div>
        <div className="flex overflow-x-auto gap-4 pb-4 snap-x no-scrollbar">
          {DEMO_PATIENTS.map((p, idx) => {
            const isFirst = idx === 0;
            const status = STATUS_TAGS[idx] ?? STATUS_TAGS[4];
            const sev = SEVERITY_TAGS[idx] ?? SEVERITY_TAGS[4];
            return (
              <button
                key={p.study_id}
                onClick={() => handleSelect(p, idx)}
                className={`flex-shrink-0 w-72 snap-start p-5 rounded-xl text-left transition-all hover:scale-[1.02] hover:shadow-lg ${
                  isFirst
                    ? "bg-primary text-white shadow-lg relative overflow-hidden"
                    : "bg-surface-container-lowest hover:bg-surface-container-low"
                }`}
              >
                {isFirst && (
                  <div className="absolute top-0 right-0 w-24 h-24 bg-white/10 rounded-full -mr-12 -mt-12" />
                )}
                <p className={`text-[10px] font-bold uppercase mb-1 ${isFirst ? "opacity-80" : "text-on-surface-variant"}`}>
                  Study ID: {p.study_id.slice(0, 2)}-{p.study_id.slice(2, 6)}
                </p>
                <h4 className={`font-bold text-lg mb-1 ${isFirst ? "" : "text-on-surface"}`}>
                  Case {idx + 1}
                </h4>
                <p className={`text-xs mb-3 truncate ${isFirst ? "opacity-90" : "text-on-surface-variant"}`}>
                  {p.chief_complaint.split(",")[0]}
                </p>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] px-2 py-0.5 rounded font-medium ${status.style}`}>
                    {status.label}
                  </span>
                  {idx < 2 && (
                    <span className={`text-[10px] px-2 py-0.5 rounded font-medium ${sev.style}`}>
                      {sev.label}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* Patient Table */}
      <section className="bg-surface-container-lowest rounded-xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 bg-surface-container-high border-b border-outline-variant/30">
          <h3 className="font-bold text-on-surface tracking-tight">Patient Registry</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="text-[10px] font-black uppercase tracking-widest text-on-surface-variant border-b border-surface-container">
                <th className="px-6 py-4">Case</th>
                <th className="px-6 py-4">Study ID</th>
                <th className="px-6 py-4">Age/Sex</th>
                <th className="px-6 py-4">Chief Complaint</th>
                <th className="px-6 py-4">Golden Dx</th>
                <th className="px-6 py-4">Action</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {DEMO_PATIENTS.map((p, idx) => (
                <tr
                  key={p.study_id}
                  className="border-b border-surface-container hover:bg-surface transition-colors cursor-pointer"
                  onClick={() => handleSelect(p, idx)}
                >
                  <td className="px-6 py-4 font-bold text-on-surface">Case {idx + 1}</td>
                  <td className="px-6 py-4 font-mono text-xs text-on-surface-variant">{p.study_id}</td>
                  <td className="px-6 py-4 text-on-surface">{p.age}yrs / {p.sex}</td>
                  <td className="px-6 py-4 text-on-surface-variant text-xs max-w-[200px] truncate">{p.chief_complaint}</td>
                  <td className="px-6 py-4 text-on-surface-variant text-xs max-w-[180px] truncate">{p.golden_dx}</td>
                  <td className="px-6 py-4">
                    <span className="text-primary text-xs font-bold hover:underline">Analyze →</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
