import type { DemoPatient } from "../types/ecg";

/**
 * 발표 시연용 5개 시나리오
 * 108개 ECG 추론 결과(ecg_results_200_final.jsonl) 기준 자동 선별
 *
 * [ECG 단독 확정 — 2개]
 *  1. Afib 90.7% + HF 78.4% — Golden Dx에 Afib, CHF, CKD 모두 일치
 *  2. HF 74.1% + Afib 47.5% — Golden Dx Primary가 Heart Failure (TP)
 *
 * [ECG 한계 → Lab 필수 — 2개]
 *  3. acute_mi 45.1% — Golden Dx는 NSTEMI 확진, Troponin으로 확정 필요
 *  4. hyperkalemia 8.7% — Golden Dx에 Hyperkalemia 있으나 ECG로 감지 불가, K+ 필요
 *
 * [ECG 경고 → 멀티모달 확정 — 1개]
 *  5. sepsis 30.1% + resp_failure 36.1% — 외과 환자에서 경계 감지, Blood/CXR 확정 필요
 */
export const DEMO_PATIENTS: DemoPatient[] = [
  // ── Case 1: ECG 확정 — Afib 90.7% + HF 78.4% (Golden Dx 일치) ──
  {
    subject_id: "18161880",
    study_id: "40985856",
    age: 78,
    sex: "M",
    chief_complaint: "Aortic stenosis, aortic aneurysm, CAD, atrial fibrillation, CKD, DM",
    golden_dx: "Aortic Stenosis, Afib, CAD, CKD, CHF systolic, DM",
  },
  // ── Case 2: ECG 확정 — HF 74.1% (Golden Dx Primary = Heart Failure) ──
  {
    subject_id: "10299107",
    study_id: "41498883",
    age: 88,
    sex: "M",
    chief_complaint: "HFpEF (TTR amyloidosis), paroxysmal atrial fibrillation, hypertension, dyspnea",
    golden_dx: "Acute on chronic diastolic heart failure, TTR amyloidosis, Afib with RVR",
  },
  // ── Case 3: ECG 한계 → Lab 필수 — acute_mi 45.1% → Troponin 확정 필요 ──
  {
    subject_id: "15238548",
    study_id: "49452415",
    age: 79,
    sex: "F",
    chief_complaint: "NSTEMI, unstable angina, heart failure, hypothyroidism, COPD",
    golden_dx: "NSTEMI, CHF, Hypothyroidism, DM2",
  },
  // ── Case 4: ECG 한계 → Lab 필수 — hyperkalemia 8.7% → K+ 수치 확정 필요 ──
  {
    subject_id: "14866589",
    study_id: "40812977",
    age: 41,
    sex: "F",
    chief_complaint: "T1DM, NSTEMI history, AKI, hyperkalemia, hyponatremia",
    golden_dx: "AKI, Hyperkalemia (K+=5.3), Hyponatremia, DM1",
  },
  // ── Case 5: ECG 경고 → 멀티모달 확정 — sepsis 30.1% + resp_failure 36.1% ──
  {
    subject_id: "15968916",
    study_id: "44082311",
    age: 83,
    sex: "M",
    chief_complaint: "High-grade small bowel obstruction, incarcerated hernia, fever, COPD",
    golden_dx: "Small bowel obstruction, Sepsis complication, Post-op atrial tachycardia",
  },
];
