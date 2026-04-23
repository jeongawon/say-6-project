import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { DEMO_PATIENTS } from "../lib/demo-patients";
import type { DemoPatient, PredictResponse } from "../types/ecg";
import { predict } from "../lib/api";
import { LABEL_KO } from "../types/ecg";

const S3_WAVEFORM = "s3://say2-6team/mimic/ecg/waveforms/files";

function makeRecordPath(subjectId: string, studyId: string): string {
  return `${S3_WAVEFORM}/p${subjectId.slice(0, 4)}/p${subjectId}/s${studyId}/${studyId}`;
}

interface PatientRecord {
  patient: DemoPatient;
  result: PredictResponse | null;
  analyzedAt: string | null;
  status: "pending" | "analyzing" | "complete" | "error";
  error?: string;
}

export default function ArchivePage() {
  const navigate = useNavigate();
  const [records, setRecords] = useState<PatientRecord[]>(
    DEMO_PATIENTS.map((p) => ({
      patient: p,
      result: null,
      analyzedAt: null,
      status: "pending",
    }))
  );
  const [expanded, setExpanded] = useState<string | null>(null);

  async function analyzePatient(idx: number) {
    const rec = records[idx];
    if (rec.status === "analyzing") return;

    setRecords((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], status: "analyzing", error: undefined };
      return next;
    });

    try {
      const p = rec.patient;
      const res = await predict({
        patient_id: p.study_id,
        patient_info: {
          age: p.age,
          sex: p.sex,
          chief_complaint: p.chief_complaint,
        },
        data: {
          record_path: makeRecordPath(p.subject_id, p.study_id),
          leads: 12,
        },
        context: { subject_id: p.subject_id },
      });
      setRecords((prev) => {
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          result: res,
          analyzedAt: new Date().toLocaleString("ko-KR"),
          status: "complete",
        };
        return next;
      });
    } catch (e: unknown) {
      setRecords((prev) => {
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          status: "error",
          error: e instanceof Error ? e.message : "분석 실패",
        };
        return next;
      });
    }
  }

  async function analyzeAll() {
    for (let i = 0; i < records.length; i++) {
      if (records[i].status !== "complete") {
        await analyzePatient(i);
      }
    }
  }

  const completedCount = records.filter((r) => r.status === "complete").length;

  return (
    <div className="space-y-6 pb-8">
      {/* 헤더 */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div>
          <h2 className="text-2xl font-extrabold tracking-tight text-on-surface">
            환자 분석 기록
          </h2>
          <p className="text-sm text-on-surface-variant mt-1">
            각 환자의 ECG AI 분석 결과가 기록됩니다
          </p>
        </div>
        <div className="flex gap-2">
          <span className="px-3 py-1.5 bg-surface-container rounded-lg text-xs font-bold text-on-surface-variant">
            분석 완료 {completedCount} / {records.length}
          </span>
          <button
            onClick={analyzeAll}
            className="px-5 py-2 bg-primary text-white rounded-lg text-xs font-bold hover:bg-blue-800 transition-colors"
          >
            전체 분석 실행
          </button>
        </div>
      </div>

      {/* 환자 카드 리스트 */}
      <div className="space-y-3">
        {records.map((rec, idx) => {
          const p = rec.patient;
          const isExpanded = expanded === p.study_id;
          const r = rec.result;

          return (
            <div
              key={p.study_id}
              className="bg-surface-container-lowest rounded-xl shadow-sm border border-outline-variant/10 overflow-hidden"
            >
              {/* 환자 행 */}
              <div className="flex items-center gap-4 px-6 py-4">
                {/* 상태 표시 */}
                <div className="shrink-0">
                  {rec.status === "complete" && (
                    <span className="w-3 h-3 rounded-full bg-emerald-500 block" />
                  )}
                  {rec.status === "analyzing" && (
                    <svg className="animate-spin h-3 w-3 text-primary" viewBox="0 0 24 24">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" fill="none" strokeDasharray="62" strokeDashoffset="15" />
                    </svg>
                  )}
                  {rec.status === "pending" && (
                    <span className="w-3 h-3 rounded-full bg-gray-300 block" />
                  )}
                  {rec.status === "error" && (
                    <span className="w-3 h-3 rounded-full bg-red-500 block" />
                  )}
                </div>

                {/* 환자 정보 */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className="font-bold text-sm text-on-surface">
                      Case {idx + 1}
                    </span>
                    <span className="text-xs text-on-surface-variant">
                      ID {p.subject_id} · Study {p.study_id}
                    </span>
                  </div>
                  <p className="text-xs text-on-surface-variant truncate mt-0.5">
                    {p.age}세 {p.sex === "M" ? "남" : "여"} · {p.chief_complaint}
                  </p>
                </div>

                {/* Risk Level 뱃지 */}
                {r && (
                  <span
                    className={`px-2.5 py-1 text-[10px] font-bold rounded ${
                      r.risk_level === "critical"
                        ? "bg-red-500 text-white"
                        : r.risk_level === "urgent"
                        ? "bg-amber-500 text-white"
                        : "bg-gray-200 text-gray-600"
                    }`}
                  >
                    {r.risk_level.toUpperCase()}
                  </span>
                )}

                {/* 검출 수 */}
                {r && (
                  <span className="text-xs font-bold text-on-surface-variant">
                    {r.findings.length}건 검출
                  </span>
                )}

                {/* 분석 시간 */}
                {rec.analyzedAt && (
                  <span className="text-[10px] text-on-surface-variant hidden lg:block">
                    {rec.analyzedAt}
                  </span>
                )}

                {/* 버튼들 */}
                <div className="flex gap-2 shrink-0">
                  {rec.status !== "complete" && (
                    <button
                      onClick={() => analyzePatient(idx)}
                      disabled={rec.status === "analyzing"}
                      className={`px-3 py-1.5 text-xs font-bold rounded transition-colors ${
                        rec.status === "analyzing"
                          ? "bg-gray-200 text-gray-400"
                          : "bg-primary text-white hover:bg-blue-800"
                      }`}
                    >
                      {rec.status === "analyzing" ? "분석 중..." : "분석 실행"}
                    </button>
                  )}
                  {rec.status === "complete" && (
                    <>
                      <button
                        onClick={() =>
                          setExpanded(isExpanded ? null : p.study_id)
                        }
                        className="px-3 py-1.5 text-xs font-bold rounded bg-surface-container text-on-surface hover:bg-surface-container-high transition-colors"
                      >
                        {isExpanded ? "접기" : "상세 보기"}
                      </button>
                      <button
                        onClick={() =>
                          navigate("/dashboard", {
                            state: { patient: p },
                          })
                        }
                        className="px-3 py-1.5 text-xs font-bold rounded bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                      >
                        대시보드
                      </button>
                    </>
                  )}
                </div>
              </div>

              {/* 에러 메시지 */}
              {rec.status === "error" && (
                <div className="px-6 pb-4 text-xs text-red-600">
                  오류: {rec.error}
                </div>
              )}

              {/* 상세 결과 (펼침) */}
              {isExpanded && r && (
                <div className="border-t border-outline-variant/10 px-6 py-5 bg-surface-container-low space-y-4">
                  {/* 요약 */}
                  <div className="flex gap-4 flex-wrap">
                    <div className="bg-surface-container-lowest rounded-lg px-4 py-3 shadow-sm">
                      <p className="text-[10px] text-on-surface-variant font-bold uppercase mb-0.5">위험도</p>
                      <p className={`text-lg font-black ${
                        r.risk_level === "critical" ? "text-red-600" :
                        r.risk_level === "urgent" ? "text-amber-600" : "text-emerald-600"
                      }`}>{r.risk_level.toUpperCase()}</p>
                    </div>
                    <div className="bg-surface-container-lowest rounded-lg px-4 py-3 shadow-sm">
                      <p className="text-[10px] text-on-surface-variant font-bold uppercase mb-0.5">심박수</p>
                      <p className="text-lg font-black text-on-surface">
                        {r.ecg_vitals?.heart_rate != null
                          ? `${Math.round(r.ecg_vitals.heart_rate)} bpm`
                          : "측정 불가"}
                      </p>
                    </div>
                    <div className="bg-surface-container-lowest rounded-lg px-4 py-3 shadow-sm">
                      <p className="text-[10px] text-on-surface-variant font-bold uppercase mb-0.5">리듬</p>
                      <p className={`text-lg font-black ${
                        r.ecg_vitals?.irregular_rhythm ? "text-amber-600" : "text-on-surface"
                      }`}>
                        {r.ecg_vitals?.irregular_rhythm ? "불규칙" : "정상"}
                      </p>
                    </div>
                    <div className="bg-surface-container-lowest rounded-lg px-4 py-3 shadow-sm">
                      <p className="text-[10px] text-on-surface-variant font-bold uppercase mb-0.5">응답 시간</p>
                      <p className="text-lg font-black text-on-surface">
                        {r.metadata.latency_ms ? `${Math.round(r.metadata.latency_ms)}ms` : "—"}
                      </p>
                    </div>
                  </div>

                  {/* AI 요약 */}
                  <div className="bg-primary/5 rounded-lg p-4">
                    <p className="text-[10px] font-bold text-primary uppercase mb-1">AI 소견</p>
                    <p className="text-sm text-on-surface">{r.summary}</p>
                  </div>

                  {/* 검출 소견 테이블 */}
                  {r.findings.length > 0 && (
                    <div>
                      <p className="text-[10px] font-bold text-on-surface-variant uppercase mb-2">검출 소견</p>
                      <div className="bg-surface-container-lowest rounded-lg overflow-hidden shadow-sm">
                        <table className="w-full text-left text-xs">
                          <thead>
                            <tr className="border-b border-outline-variant/20 text-[10px] font-bold text-on-surface-variant uppercase">
                              <th className="px-4 py-2">질환명</th>
                              <th className="px-4 py-2">신뢰도</th>
                              <th className="px-4 py-2">중증도</th>
                              <th className="px-4 py-2">권고사항</th>
                            </tr>
                          </thead>
                          <tbody>
                            {r.findings
                              .filter((f) => f.name !== "afib_detail" && f.name !== "hf_detail")
                              .map((f) => (
                                <tr key={f.name} className="border-b border-outline-variant/10">
                                  <td className="px-4 py-2 font-bold text-on-surface">
                                    {LABEL_KO[f.name] ?? f.name}
                                  </td>
                                  <td className="px-4 py-2">
                                    <div className="flex items-center gap-2">
                                      <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                                        <div
                                          className={`h-full rounded-full ${
                                            f.severity === "critical" ? "bg-red-500" :
                                            f.severity === "severe" ? "bg-amber-500" :
                                            f.severity === "moderate" ? "bg-yellow-500" : "bg-emerald-500"
                                          }`}
                                          style={{ width: `${Math.round(f.confidence * 100)}%` }}
                                        />
                                      </div>
                                      <span className="font-bold">{Math.round(f.confidence * 100)}%</span>
                                    </div>
                                  </td>
                                  <td className="px-4 py-2">
                                    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                                      f.severity === "critical" ? "bg-red-500 text-white" :
                                      f.severity === "severe" ? "bg-amber-500 text-white" :
                                      f.severity === "moderate" ? "bg-yellow-100 text-yellow-800" :
                                      "bg-emerald-100 text-emerald-800"
                                    }`}>
                                      {f.severity.toUpperCase()}
                                    </span>
                                  </td>
                                  <td className="px-4 py-2 text-on-surface-variant">
                                    {f.recommendation || "—"}
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* 실제 진단 비교 */}
                  <div className="bg-surface-container-lowest rounded-lg p-4 shadow-sm">
                    <p className="text-[10px] font-bold text-on-surface-variant uppercase mb-1">
                      실제 진단 (MIMIC-IV 퇴원요약)
                    </p>
                    <p className="text-sm text-on-surface font-medium">{p.golden_dx}</p>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
