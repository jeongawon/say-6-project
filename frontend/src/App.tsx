import { useState } from "react";
import type { DemoPatient, PredictResponse } from "./types/ecg";
import { predict } from "./lib/api";
import { DEMO_PATIENTS } from "./lib/demo-patients";

import Header from "./components/Header";
import PatientSelector from "./components/PatientSelector";
import PatientBanner from "./components/PatientBanner";
import RiskBanner from "./components/RiskBanner";
import ECGWaveform from "./components/ECGWaveform";
import RhythmStrip from "./components/RhythmStrip";
import VitalsPanel from "./components/VitalsPanel";
import FindingsPanel from "./components/FindingsPanel";
import ProbabilityChart from "./components/ProbabilityChart";
import NextModalHint from "./components/NextModalHint";

const S3_WAVEFORM = "s3://say2-6team/mimic/ecg/waveforms/files";

function makeRecordPath(subjectId: string, studyId: string): string {
  return `${S3_WAVEFORM}/p${subjectId.slice(0, 4)}/p${subjectId}/s${studyId}/${studyId}`;
}

export default function App() {
  const [patient, setPatient] = useState<DemoPatient | null>(null);
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runAnalysis() {
    if (!patient) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await predict({
        patient_id: patient.study_id,
        patient_info: {
          age: patient.age,
          sex: patient.sex,
          chief_complaint: patient.chief_complaint,
        },
        data: {
          record_path: makeRecordPath(patient.subject_id, patient.study_id),
          leads: 12,
        },
        context: { subject_id: patient.subject_id },
      });
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "분석 요청 실패");
    } finally {
      setLoading(false);
    }
  }

  function handleSelectPatient(p: DemoPatient) {
    setPatient(p);
    setResult(null);
    setError(null);
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#0b1120]">
      <Header />

      <div className="flex flex-1 overflow-hidden">
        {/* ── 좌측 사이드바: 환자 목록 ── */}
        <aside className="w-64 shrink-0 border-r border-[#1e2d3d] bg-[#0d1117] p-4 overflow-y-auto">
          <PatientSelector
            patients={DEMO_PATIENTS}
            selected={patient}
            onSelect={handleSelectPatient}
          />
        </aside>

        {/* ── 메인 영역 ── */}
        <main className="flex-1 overflow-y-auto p-5 space-y-4">
          {!patient ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center text-slate-600">
                <svg viewBox="0 0 120 40" className="h-10 w-auto mx-auto mb-3 opacity-20">
                  <polyline
                    points="0,20 20,20 30,5 40,35 50,10 60,30 70,20 120,20"
                    fill="none"
                    stroke="#4b5563"
                    strokeWidth="2"
                  />
                </svg>
                <p className="text-sm">좌측에서 환자를 선택하세요</p>
              </div>
            </div>
          ) : (
            <>
              {/* 환자 배너 */}
              <PatientBanner patient={patient} />

              {/* 분석 실행 */}
              <button
                onClick={runAnalysis}
                disabled={loading}
                className={`w-full py-3 rounded-lg font-bold text-sm tracking-wide transition-all ${
                  loading
                    ? "bg-slate-700 text-slate-400 cursor-wait"
                    : "bg-blue-600 hover:bg-blue-500 text-white"
                }`}
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle
                        cx="12" cy="12" r="10"
                        stroke="currentColor" strokeWidth="3" fill="none"
                        strokeDasharray="62" strokeDashoffset="15"
                      />
                    </svg>
                    분석 중...
                  </span>
                ) : (
                  "ECG AI 분석 실행"
                )}
              </button>

              {/* 에러 */}
              {error && (
                <div className="bg-red-950/40 border border-red-500/50 rounded-lg px-4 py-3 text-sm text-red-300">
                  {error}
                </div>
              )}

              {/* ── 결과 영역 ── */}
              {result && (
                <>
                  {/* 리스크 배너 */}
                  <RiskBanner level={result.risk_level} summary={result.summary} />

                  {/* 2컬럼: ECG 파형 | 바이탈 + 소견 */}
                  <div className="grid grid-cols-3 gap-4">
                    {/* 좌측: 12-Lead ECG */}
                    <div className="col-span-2">
                      <ECGWaveform signal={result.waveform} findings={result.findings} />
                    </div>

                    {/* 우측: 바이탈 패널 */}
                    <div>
                      <VitalsPanel
                        vitals={result.ecg_vitals}
                        latencyMs={result.metadata.latency_ms}
                        numDetected={result.metadata.num_detected ?? result.findings.length}
                      />
                    </div>
                  </div>

                  {/* Lead II 리듬 스트립 */}
                  <RhythmStrip
                    signal={result.waveform}
                    heartRate={result.ecg_vitals?.heart_rate ?? null}
                    irregular={result.ecg_vitals?.irregular_rhythm ?? false}
                  />

                  {/* 검출 소견 */}
                  <div>
                    <p className="text-[10px] font-semibold tracking-widest text-slate-500 uppercase mb-2">
                      Detected Findings
                    </p>
                    <FindingsPanel findings={result.findings} />
                  </div>

                  {/* 24개 질환 확률 차트 */}
                  <ProbabilityChart
                    allProbs={result.all_probs}
                    findings={result.findings}
                  />

                  {/* 다음 모달 힌트 (간단 표시) */}
                  <NextModalHint findings={result.findings} />
                </>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
