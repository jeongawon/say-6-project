import { DEMO_PATIENTS } from "../lib/demo-patients";
import type { DemoPatient } from "../types/ecg";

interface Props {
  activeStudyId?: string;
  onSelect: (p: DemoPatient) => void;
}

export default function PatientQueue({ activeStudyId, onSelect }: Props) {
  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Live Patient Queue</h3>
        <span className="text-primary text-xs font-bold">View All ({DEMO_PATIENTS.length})</span>
      </div>
      <div className="flex overflow-x-auto gap-4 pb-4 snap-x no-scrollbar">
        {DEMO_PATIENTS.map((p, idx) => {
          const isActive = p.study_id === activeStudyId;
          return (
            <button
              key={p.study_id}
              onClick={() => onSelect(p)}
              className={`flex-shrink-0 w-64 snap-start p-4 rounded-xl text-left transition-all hover:scale-[1.02] ${
                isActive
                  ? "bg-primary text-white shadow-lg relative overflow-hidden"
                  : "bg-surface-container-lowest hover:bg-surface-container-low"
              }`}
            >
              {isActive && (
                <div className="absolute top-0 right-0 w-24 h-24 bg-white/10 rounded-full -mr-12 -mt-12" />
              )}
              <p className={`text-[10px] font-bold uppercase mb-1 ${isActive ? "opacity-80" : "text-on-surface-variant"}`}>
                Study ID: {p.study_id.slice(0, 2)}-{p.study_id.slice(2, 6)}
              </p>
              <h4 className={`font-bold text-lg mb-1 ${isActive ? "" : "text-on-surface"}`}>
                Case {idx + 1}
              </h4>
              <p className={`text-xs mb-3 truncate ${isActive ? "opacity-90" : "text-on-surface-variant"}`}>
                {p.chief_complaint.split(",")[0]}
              </p>
              <div className="flex items-center gap-2">
                <span className={`text-[10px] px-2 py-0.5 rounded font-medium ${
                  isActive ? "bg-white/20" : "bg-surface-container-high text-on-surface-variant"
                }`}>
                  {isActive ? "Active" : idx < 2 ? "Waiting" : "Queued"}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
