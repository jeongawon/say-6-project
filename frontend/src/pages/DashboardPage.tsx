import { useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { DemoPatient, PredictResponse } from "../types/ecg";
import { predict } from "../lib/api";
import { DEMO_PATIENTS } from "../lib/demo-patients";

import PatientBanner from "../components/PatientBanner";
import RiskBanner from "../components/RiskBanner";
import ECGWaveform from "../components/ECGWaveform";
import RhythmStrip from "../components/RhythmStrip";
import VitalsPanel from "../components/VitalsPanel";
import FindingsPanel from "../components/FindingsPanel";
import ProbabilityChart from "../components/ProbabilityChart";
import NextModalHint from "../components/NextModalHint";
import PatientQueue from "../components/PatientQueue";

const S3_WAVEFORM = "s3://say2-6team/mimic/ecg/waveforms/files";

function makeRecordPath(subjectId: string, studyId: string): string {
  return `${S3_WAVEFORM}/p${subjectId.slice(0, 4)}/p${subjectId}/s${studyId}/${studyId}`;
}

export default function DashboardPage() {
  const location = useLocation();
  const navigate = useNavigate();

  const state = location.state as { patient?: DemoPatient; patientIdx?: number } | null;
  const [patient, setPatient] = useState<DemoPatient | null>(state?.patient ?? null);
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-run analysis when patient is set from navigation
  useEffect(() => {
    if (state?.patient && !result && !loading) {
      runAnalysis(state.patient);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runAnalysis(p: DemoPatient = patient!) {
    if (!p) return;
    setPatient(p);
    setLoading(true);
    setError(null);
    setResult(null);

    try {
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
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis request failed");
    } finally {
      setLoading(false);
    }
  }

  function handleSelectPatient(p: DemoPatient) {
    setPatient(p);
    setResult(null);
    setError(null);
    runAnalysis(p);
  }

  if (!patient) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-center h-64">
          <div className="text-center text-on-surface-variant">
            <span className="material-symbols-outlined text-5xl mb-3 block opacity-30">monitor_heart</span>
            <p className="text-sm">환자를 선택하면 ECG AI 분석이 시작됩니다</p>
            <button
              onClick={() => navigate("/")}
              className="mt-4 px-6 py-2 bg-primary text-white rounded-lg text-sm font-bold hover:bg-blue-800 transition-colors"
            >
              실시간 모니터로 이동
            </button>
          </div>
        </div>

        {/* Show patient queue here as well */}
        <PatientQueue onSelect={handleSelectPatient} />
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-20 md:pb-6">
      {/* Patient Info Banner & Severity */}
      <PatientBanner patient={patient} />

      {/* Patient Queue - Horizontal */}
      <PatientQueue activeStudyId={patient.study_id} onSelect={handleSelectPatient} />

      {/* Loading / Error */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="flex items-center gap-3 text-primary">
            <svg className="animate-spin h-6 w-6" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" fill="none" strokeDasharray="62" strokeDashoffset="15" />
            </svg>
            <span className="text-sm font-bold">ECG AI 분석 중...</span>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-error-container border border-error/20 rounded-xl px-6 py-4 text-sm text-on-surface">
          <span className="font-bold text-error">오류:</span> {error}
          <button
            onClick={() => runAnalysis()}
            className="ml-4 text-primary font-bold text-xs hover:underline"
          >
            재시도
          </button>
        </div>
      )}

      {/* Results */}
      {result && (
        <>
          {/* Risk Banner */}
          <RiskBanner level={result.risk_level} summary={result.summary} />

          {/* 12-Lead ECG */}
          <ECGWaveform signal={result.waveform} findings={result.findings} />

          {/* Metric Cards */}
          <VitalsPanel
            vitals={result.ecg_vitals}
            latencyMs={result.metadata.latency_ms}
            numDetected={result.metadata.num_detected ?? result.findings.length}
          />

          {/* Lead II Rhythm Strip */}
          <RhythmStrip
            signal={result.waveform}
            heartRate={result.ecg_vitals?.heart_rate ?? null}
            irregular={result.ecg_vitals?.irregular_rhythm ?? false}
          />

          {/* Findings Table */}
          <FindingsPanel findings={result.findings} />

          {/* AI Probability Distribution */}
          <ProbabilityChart allProbs={result.all_probs} findings={result.findings} />

          {/* Next Modal Hint / Protocol */}
          <NextModalHint findings={result.findings} />

          {/* AI Diagnostic Summary + Physician Notes */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-primary-fixed/20 rounded-xl p-6 relative overflow-hidden">
              <div className="absolute top-0 right-0 p-4 opacity-10">
                <span className="material-symbols-outlined text-6xl">psychology</span>
              </div>
              <h3 className="text-xs font-bold uppercase tracking-widest text-primary mb-4 flex items-center gap-2">
                <span className="material-symbols-outlined text-sm">auto_awesome</span>
                AI Diagnostic Summary
              </h3>
              <div className="text-sm text-on-surface-variant leading-relaxed space-y-3 font-medium">
                <p>{result.summary}</p>
                <p>
                  검출된 질환 <span className="text-primary font-bold">{result.findings.length}건</span>,
                  위험도 <span className={`font-bold ${
                    result.risk_level === "critical" ? "text-error" :
                    result.risk_level === "urgent" ? "text-amber-600" : "text-secondary"
                  }`}>{result.risk_level.toUpperCase()}</span>.
                  {result.ecg_vitals?.tachycardia && " 빈맥 감지 — 지속적 모니터링 권장."}
                  {result.ecg_vitals?.irregular_rhythm && " 불규칙 리듬 확인 — 항응고 요법 검토 필요."}
                </p>
              </div>
            </div>
            <div className="bg-surface-container-lowest rounded-xl p-6 shadow-sm border border-outline-variant/10">
              <h3 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-4 flex items-center gap-2">
                <span className="material-symbols-outlined text-sm">history_edu</span>
                Physician Clinical Notes
              </h3>
              <textarea
                className="w-full h-28 bg-surface-container-low border-none rounded-lg p-3 text-sm focus:ring-2 focus:ring-primary placeholder:text-on-surface-variant/50"
                placeholder="임상 소견, 감별 진단, 치료 계획을 기록하세요..."
              />
              <div className="mt-3 flex justify-end">
                <button className="text-xs font-bold text-primary px-4 py-2 hover:bg-primary-fixed/30 rounded transition-all">
                  Save Annotation
                </button>
              </div>
            </div>
          </div>

          {/* Action Footer */}
          <footer className="bg-surface border-t border-outline-variant/10 rounded-xl px-6 py-5">
            <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
              <div className="flex items-center gap-3">
                <span className="w-2 h-2 rounded-full bg-error animate-pulse" />
                <p className="text-xs font-bold text-on-surface-variant uppercase tracking-wider">
                  System Status: Active Monitoring
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-3">
                <button className="px-5 py-2.5 bg-surface-container text-on-surface font-bold text-xs rounded-md hover:bg-surface-container-high transition-colors flex items-center gap-2">
                  추가 검사 주문
                </button>
                <button className="px-5 py-2.5 bg-surface-container text-on-surface font-bold text-xs rounded-md hover:bg-surface-container-high transition-colors flex items-center gap-2">
                  임상 보고서 생성
                </button>
                <button className="px-6 py-2.5 bg-primary text-on-primary font-bold text-xs rounded-md shadow-lg shadow-primary/20 hover:opacity-90 transition-all flex items-center gap-2">
                  전문의 협진 요청
                </button>
              </div>
            </div>
          </footer>
        </>
      )}
    </div>
  );
}
