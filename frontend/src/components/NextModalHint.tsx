import type { Finding } from "../types/ecg";
import { NEXT_MODAL_HINT, LABEL_KO } from "../types/ecg";

interface Props {
  findings: Finding[];
}

export default function NextModalHint({ findings }: Props) {
  const hints = findings
    .filter((f) => NEXT_MODAL_HINT[f.name])
    .map((f) => ({
      disease: LABEL_KO[f.name] ?? f.name,
      ...NEXT_MODAL_HINT[f.name],
    }));

  if (hints.length === 0) return null;

  return (
    <div className="bg-[#111827] border border-[#1e2d3d] rounded-lg p-4">
      <p className="text-[10px] font-semibold tracking-widest text-slate-500 uppercase mb-3">
        Bedrock Agent &mdash; Next Modal Routing
      </p>
      <div className="space-y-2">
        {hints.map((h, i) => (
          <div
            key={i}
            className="flex items-center gap-3 bg-slate-800/50 rounded px-3 py-2 text-sm"
          >
            <span className="text-slate-400 font-medium shrink-0">{h.disease}</span>
            <svg viewBox="0 0 24 24" className="w-4 h-4 text-blue-500 shrink-0" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M5 12h14M12 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="px-2 py-0.5 bg-blue-900/40 text-blue-300 text-xs rounded font-semibold">
              {h.modal} Modal
            </span>
            <span className="text-slate-500 text-xs">{h.action}</span>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-slate-600 mt-2">
        * 실제 라우팅은 중앙 Bedrock Agent가 all_probs + 환자 컨텍스트 기반으로 수행
      </p>
    </div>
  );
}
