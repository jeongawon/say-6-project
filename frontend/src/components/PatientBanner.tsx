import type { DemoPatient } from "../types/ecg";

interface Props {
  patient: DemoPatient;
}

export default function PatientBanner({ patient }: Props) {
  return (
    <div className="bg-[#111827] border border-[#1e2d3d] border-l-4 border-l-blue-500 rounded px-5 py-3">
      <div className="flex items-baseline gap-3">
        <span className="text-base font-bold text-gray-100">
          ID {patient.subject_id}
        </span>
        <span className="text-sm text-slate-500">
          Study {patient.study_id}
        </span>
      </div>
      <div className="mt-1 flex gap-4 text-sm text-slate-400">
        <span>{patient.age}세</span>
        <span>{patient.sex === "M" ? "남성" : "여성"}</span>
        <span className="text-slate-500">|</span>
        <span className="truncate max-w-md">
          주 증상: {patient.chief_complaint || "—"}
        </span>
      </div>
    </div>
  );
}
