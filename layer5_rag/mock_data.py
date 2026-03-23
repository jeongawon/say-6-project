"""
Layer 5 RAG Mock 데이터.
실제 FAISS 인덱스 구축 전에도 Lambda 테스트가 가능하도록
가상의 판독문 + 임베딩으로 미니 인덱스를 생성.
"""
import numpy as np

# ============================================================
# Mock 판독문 메타데이터 (실제 MIMIC-CXR 스타일)
# ============================================================
MOCK_REPORTS = [
    {
        "note_id": "MOCK-CHF-001",
        "subject_id": "10000001",
        "hadm_id": "20000001",
        "charttime": "2180-03-15 14:30:00",
        "examination": "CHEST (PA AND LATERAL)",
        "indication": "72-year-old male with shortness of breath and lower extremity edema.",
        "comparison": "Prior chest radiograph dated 2180-01-10.",
        "findings": "The heart is significantly enlarged. There are bilateral pleural effusions, right greater than left. Bilateral pulmonary vascular congestion and interstitial edema are noted. No focal consolidation. No pneumothorax. The mediastinal contour is normal. Osseous structures are unremarkable.",
        "impression": "Cardiomegaly with bilateral pleural effusions and pulmonary edema, consistent with CHF. No focal consolidation to suggest pneumonia.",
    },
    {
        "note_id": "MOCK-CHF-002",
        "subject_id": "10000002",
        "hadm_id": "20000002",
        "charttime": "2179-11-20 09:15:00",
        "examination": "CHEST (PA AND LATERAL)",
        "indication": "68-year-old female with worsening dyspnea.",
        "comparison": "None.",
        "findings": "Marked cardiomegaly. Bilateral effusions, left greater than right. Cephalization of pulmonary vessels. Kerley B lines noted. No consolidation. No pneumothorax.",
        "impression": "Severe cardiomegaly with bilateral effusions and pulmonary edema. Findings consistent with decompensated heart failure.",
    },
    {
        "note_id": "MOCK-CHF-003",
        "subject_id": "10000003",
        "hadm_id": "20000003",
        "charttime": "2180-06-05 16:45:00",
        "examination": "CHEST (PORTABLE AP)",
        "indication": "75-year-old male with history of CHF, presenting with dyspnea.",
        "comparison": "Chest radiograph from 2180-05-01.",
        "findings": "Enlarged cardiac silhouette. Small bilateral pleural effusions. Pulmonary vascular congestion. No focal airspace disease. Stable chronic deformity of the mid-thoracic spine.",
        "impression": "Cardiomegaly with pulmonary vascular congestion and small bilateral effusions, likely CHF exacerbation.",
    },
    {
        "note_id": "MOCK-PNA-001",
        "subject_id": "10000004",
        "hadm_id": "20000004",
        "charttime": "2180-02-10 11:00:00",
        "examination": "CHEST (PA AND LATERAL)",
        "indication": "67-year-old male with fever and productive cough.",
        "comparison": "None.",
        "findings": "Consolidation in the left lower lobe. Air bronchograms are noted. No pleural effusion. Heart size is normal. Mediastinal contours are unremarkable. No pneumothorax.",
        "impression": "Left lower lobe consolidation consistent with pneumonia. No pleural effusion.",
    },
    {
        "note_id": "MOCK-PNA-002",
        "subject_id": "10000005",
        "hadm_id": "20000005",
        "charttime": "2179-08-22 07:30:00",
        "examination": "CHEST (PA AND LATERAL)",
        "indication": "55-year-old female with cough, fever, and leukocytosis.",
        "comparison": "Chest radiograph from one week prior.",
        "findings": "New right lower lobe opacity with air bronchograms. Small right pleural effusion. Heart size is within normal limits. No pneumothorax. Mild bibasilar atelectasis.",
        "impression": "Right lower lobe pneumonia with small parapneumonic effusion. Mild bibasilar atelectasis.",
    },
    {
        "note_id": "MOCK-PTX-001",
        "subject_id": "10000006",
        "hadm_id": "20000006",
        "charttime": "2180-01-03 22:15:00",
        "examination": "CHEST (PORTABLE AP)",
        "indication": "25-year-old male s/p motor vehicle accident.",
        "comparison": "None.",
        "findings": "Large left pneumothorax with near-complete collapse of the left lung. Tracheal and mediastinal shift to the right, concerning for tension physiology. Left rib fractures involving the 4th through 7th ribs. No right-sided pneumothorax. Heart size cannot be assessed due to mediastinal shift.",
        "impression": "1. Large left tension pneumothorax with mediastinal shift — emergent decompression recommended. 2. Left-sided rib fractures (4th-7th).",
    },
    {
        "note_id": "MOCK-PTX-002",
        "subject_id": "10000007",
        "hadm_id": "20000007",
        "charttime": "2180-04-18 03:45:00",
        "examination": "CHEST (PORTABLE AP)",
        "indication": "30-year-old male with acute chest pain and dyspnea. Tall, thin habitus.",
        "comparison": "None.",
        "findings": "Small right apical pneumothorax measuring approximately 2 cm from the apex. No mediastinal shift. Heart size and mediastinal contours are normal. Lungs are otherwise clear. No effusion.",
        "impression": "Small right apical pneumothorax. No tension physiology. Recommend follow-up imaging.",
    },
    {
        "note_id": "MOCK-NORMAL-001",
        "subject_id": "10000008",
        "hadm_id": "20000008",
        "charttime": "2180-07-01 10:00:00",
        "examination": "CHEST (PA AND LATERAL)",
        "indication": "45-year-old female, preoperative evaluation.",
        "comparison": "None.",
        "findings": "The lungs are clear bilaterally. No consolidation, effusion, or pneumothorax. Heart size is normal. Mediastinal contours are unremarkable. Osseous structures are intact.",
        "impression": "No acute cardiopulmonary abnormality.",
    },
    {
        "note_id": "MOCK-NORMAL-002",
        "subject_id": "10000009",
        "hadm_id": "20000009",
        "charttime": "2180-09-15 14:00:00",
        "examination": "CHEST (PA AND LATERAL)",
        "indication": "Routine physical examination.",
        "comparison": "Chest radiograph from 2179-09-20.",
        "findings": "Clear lungs without focal opacity. No pleural effusion or pneumothorax. Normal cardiac silhouette. Unremarkable mediastinum. No acute bony abnormality.",
        "impression": "Normal chest radiograph. No interval change.",
    },
    {
        "note_id": "MOCK-EDEMA-001",
        "subject_id": "10000010",
        "hadm_id": "20000010",
        "charttime": "2180-05-20 08:00:00",
        "examination": "CHEST (PORTABLE AP)",
        "indication": "80-year-old female with acute respiratory distress.",
        "comparison": "Chest radiograph from 2180-05-18.",
        "findings": "Diffuse bilateral alveolar opacities in a perihilar butterfly pattern. Cephalization of pulmonary vessels. Moderate cardiomegaly. Small bilateral pleural effusions. No pneumothorax.",
        "impression": "Severe pulmonary edema with bilateral effusions, likely cardiogenic given cardiomegaly. Cannot exclude superimposed infection.",
    },
]


# ============================================================
# Layer 3 Mock 결과 (4개 시나리오)
# ============================================================
MOCK_L3_SCENARIOS = {
    "chf": {
        "findings": {
            "Cardiomegaly": {"detected": True, "severity": "severe", "location": "bilateral"},
            "Pleural_Effusion": {"detected": True, "severity": "moderate", "location": "bilateral"},
            "Edema": {"detected": True, "severity": "severe", "location": "bilateral"},
            "Pneumothorax": {"detected": False},
            "Consolidation": {"detected": False},
            "No_Finding": {"detected": False},
        },
        "differential_diagnosis": [
            {"diagnosis": "CHF", "probability": "high"},
        ],
        "risk_level": "urgent",
    },
    "pneumonia": {
        "findings": {
            "Consolidation": {"detected": True, "severity": "moderate", "location": "left lower lobe"},
            "Pneumonia": {"detected": True, "severity": "moderate", "location": "left lower lobe"},
            "Lung_Opacity": {"detected": True, "severity": "moderate", "location": "left lower lobe"},
            "Cardiomegaly": {"detected": False},
            "No_Finding": {"detected": False},
        },
        "differential_diagnosis": [
            {"diagnosis": "Pneumonia", "probability": "high"},
        ],
        "risk_level": "routine",
    },
    "tension_pneumo": {
        "findings": {
            "Pneumothorax": {"detected": True, "severity": "severe", "location": "left", "alert": True},
            "Fracture": {"detected": True, "severity": "moderate", "location": "left 4th-7th ribs"},
            "Cardiomegaly": {"detected": False},
            "No_Finding": {"detected": False},
        },
        "differential_diagnosis": [
            {"diagnosis": "Tension Pneumothorax", "probability": "critical"},
        ],
        "risk_level": "critical",
        "alert_flags": ["Pneumothorax"],
    },
    "normal": {
        "findings": {
            "No_Finding": {"detected": True},
            "Cardiomegaly": {"detected": False},
            "Pleural_Effusion": {"detected": False},
            "Pneumothorax": {"detected": False},
            "Consolidation": {"detected": False},
            "Edema": {"detected": False},
        },
        "differential_diagnosis": [],
        "risk_level": "routine",
    },
}
