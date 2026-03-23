"""
Layer 3 Clinical Logic Lambda — 개별 엔드포인트
GPU 불필요. 순수 Python Rule Engine.

입력 모드:
  1) "scenario" → 내장 mock 시나리오 (chf/pneumonia/tension_pneumo/normal)
  2) "custom"   → 사용자가 Layer 1/2 출력을 직접 전달
  3) "random"   → Layer 1/2 출력을 랜덤 생성하여 엔진 검증

출력: 14개 질환 판정 + 교차검증 + 감별진단 + 위험도

GET  → 테스트 페이지 (index.html)
POST → Clinical Logic API
"""
import os
import json
import time
import random

# ================================================================
# Layer 3 엔진 (Lambda 패키지 내에 포함)
# ================================================================
from layer3_clinical_logic.engine import run_clinical_logic
from layer3_clinical_logic.models import (
    AnatomyMeasurements,
    DenseNetPredictions,
    YoloDetection,
    PatientInfo,
    PriorResult,
    ClinicalLogicInput,
)
from layer3_clinical_logic.mock_data import (
    mock_chf_patient,
    mock_pneumonia_patient,
    mock_tension_pneumo,
    mock_normal,
)

# ================================================================
# Mock 시나리오 매핑
# ================================================================
SCENARIOS = {
    "chf": {
        "name": "심부전 (CHF)",
        "description": "72세 남성, 심비대 + 양측 흉수 + 폐부종, 심방세동",
        "input": mock_chf_patient,
    },
    "pneumonia": {
        "name": "폐렴 (Pneumonia)",
        "description": "67세 남성, 좌하엽 경화 + 발열 38.2°C + 기침, ECG 정상",
        "input": mock_pneumonia_patient,
    },
    "tension_pneumo": {
        "name": "긴장성 기흉 (Tension Pneumothorax)",
        "description": "25세 남성, 교통사고 후 좌측 기흉, 기관 우측 편위, SpO2 82%",
        "input": mock_tension_pneumo,
    },
    "normal": {
        "name": "정상 (Normal)",
        "description": "모든 지표 정상 범위, 질환 미감지",
        "input": mock_normal,
    },
}


# ================================================================
# 랜덤 입력 생성
# ================================================================
def generate_random_input():
    """Layer 1/2 출력을 랜덤으로 생성하여 엔진 검증"""
    ctr = round(random.uniform(0.35, 0.70), 4)
    if ctr >= 0.60:
        ctr_status = "severe"
    elif ctr >= 0.50:
        ctr_status = "enlarged"
    else:
        ctr_status = "normal"

    thorax_w = random.randint(2000, 2800)
    heart_w = int(thorax_w * ctr)

    r_lung = random.randint(600000, 1100000)
    l_lung = int(r_lung * random.uniform(0.40, 1.05))
    ratio = round(l_lung / r_lung, 4) if r_lung > 0 else 0.9

    # 종격동
    med_status = random.choice(["normal", "normal", "normal", "enlarged"])
    med_width = random.randint(150, 400) if med_status == "enlarged" else random.randint(100, 200)

    # 기관
    trachea_midline = random.choice([True, True, True, False])
    trachea_dir = "none" if trachea_midline else random.choice(["right", "left"])

    # CP angle
    r_cp = random.choice(["sharp", "sharp", "sharp", "blunted"])
    l_cp = random.choice(["sharp", "sharp", "sharp", "blunted"])
    r_cp_angle = round(random.uniform(30, 60), 1) if r_cp == "sharp" else round(random.uniform(75, 130), 1)
    l_cp_angle = round(random.uniform(30, 60), 1) if l_cp == "sharp" else round(random.uniform(75, 130), 1)

    # 횡격막
    dia_status = random.choice(["normal", "normal", "normal", "elevated_right", "elevated_left"])

    anatomy = AnatomyMeasurements(
        ctr=ctr, ctr_status=ctr_status,
        heart_width_px=heart_w, thorax_width_px=thorax_w,
        heart_area_px2=heart_w * random.randint(600, 900),
        right_lung_area_px2=r_lung, left_lung_area_px2=l_lung,
        lung_area_ratio=ratio, total_lung_area_px2=r_lung + l_lung,
        mediastinum_width_px=med_width, mediastinum_status=med_status,
        trachea_midline=trachea_midline,
        trachea_deviation_direction=trachea_dir,
        trachea_deviation_ratio=0.0 if trachea_midline else round(random.uniform(0.03, 0.12), 3),
        right_cp_angle_degrees=r_cp_angle, right_cp_status=r_cp,
        left_cp_angle_degrees=l_cp_angle, left_cp_status=l_cp,
        diaphragm_status=dia_status,
        view=random.choice(["PA", "PA", "PA", "AP"]),
        predicted_age=round(random.uniform(20, 85), 1),
        predicted_sex=random.choice(["M", "F"]),
    )

    # DenseNet 확률 랜덤 (대부분 낮고, 1~3개 높게)
    densenet = DenseNetPredictions()
    diseases = [
        "Atelectasis", "Cardiomegaly", "Consolidation", "Edema",
        "Enlarged_Cardiomediastinum", "Fracture", "Lung_Lesion", "Lung_Opacity",
        "Pleural_Effusion", "Pleural_Other", "Pneumonia",
        "Pneumothorax", "Support_Devices",
    ]
    hot_count = random.randint(0, 3)
    hot_diseases = random.sample(diseases, hot_count)
    for d in diseases:
        if d in hot_diseases:
            setattr(densenet, d, round(random.uniform(0.50, 0.98), 4))
        else:
            setattr(densenet, d, round(random.uniform(0.01, 0.30), 4))
    # No_Finding은 다른 질환 없으면 높게
    densenet.No_Finding = round(random.uniform(0.70, 0.95), 4) if hot_count == 0 else round(random.uniform(0.05, 0.30), 4)

    # YOLO (간혹 bbox 생성)
    yolo_detections = []
    if hot_count > 0 and random.random() > 0.5:
        yolo_d = random.choice(hot_diseases)
        x1 = random.randint(50, 300)
        y1 = random.randint(100, 400)
        yolo_detections.append(YoloDetection(
            class_name=yolo_d,
            bbox=[x1, y1, x1 + random.randint(80, 200), y1 + random.randint(80, 200)],
            confidence=round(random.uniform(0.50, 0.95), 2),
            lobe=random.choice([None, "RUL", "RLL", "LUL", "LLL"]),
        ))

    # 환자 정보 (50% 확률로 포함)
    patient_info = None
    if random.random() > 0.5:
        complaints = ["흉통", "호흡곤란", "기침", "발열", "교통사고", "하지부종"]
        patient_info = PatientInfo(
            age=random.randint(20, 85),
            sex=random.choice(["M", "F"]),
            chief_complaint=", ".join(random.sample(complaints, random.randint(1, 3))),
            temperature=round(random.uniform(36.0, 39.5), 1) if random.random() > 0.5 else None,
            respiratory_rate=random.randint(12, 35) if random.random() > 0.5 else None,
            spo2=random.randint(80, 100) if random.random() > 0.5 else None,
        )

    return ClinicalLogicInput(
        anatomy=anatomy,
        densenet=densenet,
        yolo_detections=yolo_detections,
        patient_info=patient_info,
    )


def input_to_dict(cli_input: ClinicalLogicInput) -> dict:
    """ClinicalLogicInput → JSON-serializable dict"""
    from dataclasses import asdict
    d = asdict(cli_input)
    return d


# ================================================================
# Custom 입력 파싱
# ================================================================
def parse_custom_input(body: dict) -> ClinicalLogicInput:
    """사용자가 전달한 JSON을 ClinicalLogicInput으로 변환"""
    anat_raw = body.get("anatomy", {})
    anatomy = AnatomyMeasurements(
        ctr=anat_raw.get("ctr", 0.45),
        ctr_status=anat_raw.get("ctr_status", "normal"),
        heart_width_px=anat_raw.get("heart_width_px", 1100),
        thorax_width_px=anat_raw.get("thorax_width_px", 2400),
        heart_area_px2=anat_raw.get("heart_area_px2", 900000),
        right_lung_area_px2=anat_raw.get("right_lung_area_px2", 950000),
        left_lung_area_px2=anat_raw.get("left_lung_area_px2", 870000),
        lung_area_ratio=anat_raw.get("lung_area_ratio", 0.916),
        total_lung_area_px2=anat_raw.get("total_lung_area_px2", 1820000),
        mediastinum_width_px=anat_raw.get("mediastinum_width_px"),
        mediastinum_status=anat_raw.get("mediastinum_status"),
        trachea_midline=anat_raw.get("trachea_midline"),
        trachea_deviation_direction=anat_raw.get("trachea_deviation_direction"),
        trachea_deviation_ratio=anat_raw.get("trachea_deviation_ratio"),
        right_cp_angle_degrees=anat_raw.get("right_cp_angle_degrees"),
        right_cp_status=anat_raw.get("right_cp_status"),
        left_cp_angle_degrees=anat_raw.get("left_cp_angle_degrees"),
        left_cp_status=anat_raw.get("left_cp_status"),
        diaphragm_status=anat_raw.get("diaphragm_status"),
        view=anat_raw.get("view", "PA"),
        predicted_age=anat_raw.get("predicted_age"),
        predicted_sex=anat_raw.get("predicted_sex"),
    )

    dn_raw = body.get("densenet", {})
    densenet = DenseNetPredictions(**{k: float(v) for k, v in dn_raw.items()
                                      if hasattr(DenseNetPredictions, k)})

    yolo_list = []
    for det in body.get("yolo_detections", []):
        yolo_list.append(YoloDetection(
            class_name=det.get("class_name", ""),
            bbox=det.get("bbox", [0, 0, 0, 0]),
            confidence=det.get("confidence", 0.0),
            lobe=det.get("lobe"),
        ))

    pi = None
    pi_raw = body.get("patient_info")
    if pi_raw:
        pi = PatientInfo(**{k: v for k, v in pi_raw.items()
                            if k in PatientInfo.__dataclass_fields__})

    pr_list = []
    for pr in body.get("prior_results", []):
        pr_list.append(PriorResult(
            modal=pr.get("modal", ""),
            summary=pr.get("summary", ""),
            findings=pr.get("findings", {}),
        ))

    return ClinicalLogicInput(
        anatomy=anatomy,
        densenet=densenet,
        yolo_detections=yolo_list,
        patient_info=pi,
        prior_results=pr_list,
    )


# ================================================================
# Lambda 핸들러
# ================================================================
def serve_html():
    """테스트 페이지 HTML 반환"""
    html_path = os.path.join(os.path.dirname(__file__), 'index.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'text/html; charset=utf-8'},
        'body': html,
    }


def handler(event, context):
    """Lambda 핸들러 — GET: 테스트 페이지, POST: Clinical Logic API"""
    method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')

    if method == 'GET':
        return serve_html()

    try:
        body = event
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        elif isinstance(event.get('body'), dict):
            body = event['body']

        action = body.get('action', 'scenario')
        start = time.time()

        # ---- 시나리오 목록 ----
        if action == 'list_scenarios':
            scenarios = {k: {"name": v["name"], "description": v["description"]}
                         for k, v in SCENARIOS.items()}
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'scenarios': scenarios}, ensure_ascii=False),
            }

        # ---- 시나리오 실행 ----
        if action == 'scenario':
            scenario_id = body.get('scenario', 'chf')
            if scenario_id not in SCENARIOS:
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({
                        'error': f'Unknown scenario: {scenario_id}',
                        'available': list(SCENARIOS.keys()),
                    }),
                }
            cli_input = SCENARIOS[scenario_id]["input"]
            mode = f'scenario:{scenario_id}'

        # ---- 랜덤 생성 ----
        elif action == 'random':
            cli_input = generate_random_input()
            mode = 'random'

        # ---- 사용자 직접 입력 ----
        elif action == 'custom':
            cli_input = parse_custom_input(body)
            mode = 'custom'

        else:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({
                    'error': f'Unknown action: {action}',
                    'available': ['list_scenarios', 'scenario', 'random', 'custom'],
                }),
            }

        # ---- Clinical Logic 실행 ----
        result = run_clinical_logic(cli_input)
        elapsed = round(time.time() - start, 4)

        # 결과를 JSON-safe로 변환
        output = {
            'mode': mode,
            'input_summary': _summarize_input(cli_input),
            'input_data': input_to_dict(cli_input),
            'result': {
                'findings': result['findings'],
                'cross_validation': result['cross_validation'],
                'differential_diagnosis': result['differential_diagnosis'],
                'risk_level': result['risk_level'],
                'alert_flags': result['alert_flags'],
                'detected_count': result['detected_count'],
            },
            'processing_time_sec': elapsed,
        }

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps(output, ensure_ascii=False, default=str),
        }

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)}),
        }


def _summarize_input(cli_input: ClinicalLogicInput) -> dict:
    """입력 데이터의 핵심만 요약"""
    a = cli_input.anatomy
    d = cli_input.densenet

    # DenseNet에서 높은 확률 질환
    high_probs = {}
    for attr in [
        "Atelectasis", "Cardiomegaly", "Consolidation", "Edema",
        "Enlarged_Cardiomediastinum", "Fracture", "Lung_Lesion", "Lung_Opacity",
        "Pleural_Effusion", "Pleural_Other", "Pneumonia",
        "Pneumothorax", "Support_Devices",
    ]:
        p = getattr(d, attr, 0.0)
        if p > 0.3:
            high_probs[attr] = round(p, 4)

    summary = {
        "anatomy": {
            "ctr": a.ctr,
            "ctr_status": a.ctr_status,
            "view": a.view,
            "lung_area_ratio": a.lung_area_ratio,
            "trachea_midline": a.trachea_midline,
            "right_cp_status": a.right_cp_status,
            "left_cp_status": a.left_cp_status,
            "diaphragm_status": a.diaphragm_status,
        },
        "densenet_high_probs": high_probs,
        "yolo_count": len(cli_input.yolo_detections),
        "has_patient_info": cli_input.patient_info is not None,
        "prior_results_count": len(cli_input.prior_results),
    }
    return summary
