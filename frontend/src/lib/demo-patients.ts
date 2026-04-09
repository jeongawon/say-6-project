import type { DemoPatient } from "../types/ecg";

/**
 * 발표 시연용 5개 시나리오
 *
 * [ECG 단독 확정 — 4개]
 *  1. Afib 94.0%  — Golden Dx에 Afib 있음 (TP)
 *  2. 급성MI 30.2% + HF 73.3% — NSTEMI Golden Dx (TP), Tier-1 임계값 작동
 *  3. 심부전 88.7% + Afib 89.3% — ECG에서 HF 패턴 명확 검출
 *  4. 고칼륨혈증 58.8% — Golden Dx에 Hyperkalemia 있음 (TP), T파 변화
 *
 * [ECG 감지 → 다른 모달로 확정 — 1개]
 *  5. sepsis 30.1% + resp_failure 36.1% + AKI 42.8% — Tier-1 임계값으로 겨우 검출, Blood/Chest 확정 필요
 */
export const DEMO_PATIENTS: DemoPatient[] = [
  // ── Case 1: ECG 단독 — Afib 94.0% (Golden Dx 일치) ──
  {
    subject_id: "18161880",
    study_id: "40985856",
    age: 78,
    sex: "M",
    chief_complaint: "Aortic stenosis, aortic aneurysm, CAD, atrial fibrillation, CKD, DM",
    golden_dx: "Aortic Stenosis, Afib, CAD, CKD, DM",
  },
  // ── Case 2: Tier-1 임계값 작동 — acute_mi 30.2% → CRITICAL ──
  {
    subject_id: "15238548",
    study_id: "49452415",
    age: 79,
    sex: "F",
    chief_complaint: "NSTEMI, unstable angina, heart failure, hypothyroidism",
    golden_dx: "NSTEMI, Heart Failure, Hypothyroidism, DM",
  },
  // ── Case 3: ECG 단독 — HF 88.7% + Afib 89.3% 동시 검출 ──
  {
    subject_id: "14112944",
    study_id: "42710306",
    age: 88,
    sex: "M",
    chief_complaint: "Progressive left shoulder pain, multiple cardiac comorbidities",
    golden_dx: "Left shoulder osteoarthritis (Afib, HF, CKD 동반)",
  },
  // ── Case 4: ECG 단독 — Hyperkalemia 58.8% + CKD 89.4% (Golden Dx 일치) ──
  {
    subject_id: "14866589",
    study_id: "40812977",
    age: 41,
    sex: "F",
    chief_complaint: "T1DM, NSTEMI history, AKI, hyperkalemia, hyponatremia",
    golden_dx: "AKI, Hyperkalemia, Hyponatremia, DM1",
  },
  // ── Case 5: ECG 감지 → Blood/Chest 확정 필요 — sepsis 30.1% (Tier-1 경계) ──
  {
    subject_id: "15968916",
    study_id: "44082311",
    age: 83,
    sex: "M",
    chief_complaint: "High-grade small bowel obstruction, incarcerated hernia, fever",
    golden_dx: "Small bowel obstruction, Sepsis complication",
  },
];
