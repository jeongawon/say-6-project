import type { DemoPatient } from "../types/ecg";

interface Props {
  patients: DemoPatient[];
  selected: DemoPatient | null;
  onSelect: (p: DemoPatient) => void;
}

export default function PatientSelector({ patients, selected, onSelect }: Props) {
  return (
    <div>
      <p className="text-[11px] font-semibold tracking-wider text-gray-400 uppercase px-1 mb-2">
        Patient List
      </p>
      <div className="space-y-1">
        {patients.map((p, i) => {
          const active = selected?.study_id === p.study_id;
          return (
            <button
              key={p.study_id}
              onClick={() => onSelect(p)}
              className={`w-full text-left px-3 py-2.5 rounded border transition-all text-xs ${
                active
                  ? "bg-blue-50 border-blue-400 text-blue-800"
                  : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-bold text-[11px]">
                  <span className="text-gray-400 mr-1">Case {i + 1}</span>
                  {p.study_id}
                </span>
                <span className="text-[10px] text-gray-400">
                  {p.age}세 {p.sex}
                </span>
              </div>
              <p className="text-[10px] text-gray-400 mt-0.5 truncate">
                {p.golden_dx || p.chief_complaint}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
