export interface PatientInfo {
  age: number;
  sex: string;
  chief_complaint: string;
  history?: string[];
}

export interface PredictRequest {
  patient_id: string;
  patient_info: PatientInfo;
  data: {
    record_path: string;
    leads: number;
  };
  context: Record<string, string>;
}

export interface Finding {
  name: string;
  confidence: number;
  detail: string;
  severity: "critical" | "severe" | "moderate" | "mild";
  recommendation: string;
}

export interface ECGVitals {
  heart_rate: number | null;
  bradycardia: boolean;
  tachycardia: boolean;
  irregular_rhythm: boolean;
}

export interface PredictResponse {
  status: string;
  modal: string;
  findings: Finding[];
  summary: string;
  risk_level: "critical" | "urgent" | "routine";
  ecg_vitals: ECGVitals | null;
  all_probs: Record<string, number>;
  waveform: number[][] | null;
  metadata: {
    patient_id?: string;
    latency_ms?: number;
    model?: string;
    timestamp?: string;
    num_detected?: number;
  };
  error?: string;
}

export interface DemoPatient {
  subject_id: string;
  study_id: string;
  age: number;
  sex: string;
  chief_complaint: string;
  golden_dx: string;
}

export const LABEL_KO: Record<string, string> = {
  afib_flutter: "심방세동/조동",
  heart_failure: "심부전",
  hypertension: "고혈압",
  chronic_ihd: "만성 허혈성 심질환",
  acute_mi: "급성 심근경색",
  paroxysmal_tachycardia: "발작성 빈맥",
  av_block_lbbb: "방실차단/좌각차단",
  other_conduction: "기타 전도장애",
  pulmonary_embolism: "폐색전증",
  cardiac_arrest: "심정지",
  angina: "협심증",
  pericardial_disease: "심낭질환",
  afib_detail: "심방세동(세부)",
  hf_detail: "심부전(세부)",
  dm2: "제2형 당뇨병",
  acute_kidney_failure: "급성 신부전",
  hypothyroidism: "갑상선기능저하증",
  copd: "COPD",
  chronic_kidney: "만성 신장질환",
  hyperkalemia: "고칼륨혈증",
  hypokalemia: "저칼륨혈증",
  respiratory_failure: "호흡부전",
  sepsis: "패혈증",
  calcium_disorder: "칼슘 대사 이상",
};

export const CARDIAC_LABELS = [
  "afib_flutter", "heart_failure", "hypertension", "chronic_ihd",
  "acute_mi", "paroxysmal_tachycardia", "av_block_lbbb",
  "other_conduction", "pulmonary_embolism", "cardiac_arrest",
  "angina", "pericardial_disease", "afib_detail", "hf_detail",
];

export const NONCARDIAC_LABELS = [
  "dm2", "acute_kidney_failure", "hypothyroidism", "copd",
  "chronic_kidney", "hyperkalemia", "hypokalemia",
  "respiratory_failure", "sepsis", "calcium_disorder",
];

export const NEXT_MODAL_HINT: Record<string, { modal: string; action: string }> = {
  acute_mi:           { modal: "Blood", action: "Troponin I/T" },
  heart_failure:      { modal: "Blood", action: "BNP/NT-proBNP" },
  hf_detail:          { modal: "Blood", action: "BNP/NT-proBNP" },
  sepsis:             { modal: "Blood", action: "혈액배양 + 젖산" },
  hyperkalemia:       { modal: "Blood", action: "K+ 확인" },
  hypokalemia:        { modal: "Blood", action: "K+ 확인" },
  pulmonary_embolism: { modal: "Chest", action: "CTPA 영상" },
};
