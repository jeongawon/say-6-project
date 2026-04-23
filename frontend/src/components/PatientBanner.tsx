import type { DemoPatient } from "../types/ecg";

interface Props {
  patient: DemoPatient;
}

export default function PatientBanner({ patient }: Props) {
  return (
    <div className="bg-white border border-gray-200 border-l-4 border-l-blue-500 rounded px-5 py-3 shadow-sm">
      <div className="flex items-baseline gap-3">
        <span className="text-sm font-bold text-gray-800">
          ID {patient.subject_id}
        </span>
        <span className="text-xs text-gray-400">
          Study {patient.study_id}
        </span>
      </div>
      <div className="mt-1 flex gap-4 text-xs text-gray-500">
        <span className="font-medium text-gray-700">{patient.age}세</span>
        <span className="font-medium text-gray-700">{patient.sex === "M" ? "남성" : "여성"}</span>
        <span className="text-gray-300">|</span>
        <span className="truncate max-w-md">
          주 증상: {patient.chief_complaint || "—"}
        </span>
      </div>
    </div>
  );
}
