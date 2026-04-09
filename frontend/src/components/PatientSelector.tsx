import type { DemoPatient } from "../types/ecg";

interface Props {
  patients: DemoPatient[];
  selected: DemoPatient | null;
  onSelect: (p: DemoPatient) => void;
}

export default function PatientSelector({ patients, selected, onSelect }: Props) {
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-semibold tracking-widest text-slate-500 uppercase px-1">
        Patient List
      </p>
      {patients.map((p) => {
        const active = selected?.study_id === p.study_id;
        return (
          <button
            key={p.study_id}
            onClick={() => onSelect(p)}
            className={`w-full text-left px-3 py-2.5 rounded-lg border transition-all ${
              active
                ? "bg-blue-900/30 border-blue-500/50 text-gray-100"
                : "bg-[#111827] border-[#1e2d3d] text-slate-400 hover:bg-slate-800 hover:border-slate-600"
            }`}
          >
            <div className="flex items-baseline justify-between">
              <span className="text-xs font-bold">{p.study_id}</span>
              <span className="text-[10px] text-slate-500">
                {p.age}세 {p.sex}
              </span>
            </div>
            <p className="text-[10px] text-slate-500 mt-0.5 truncate">
              {p.golden_dx || p.chief_complaint}
            </p>
          </button>
        );
      })}
    </div>
  );
}
