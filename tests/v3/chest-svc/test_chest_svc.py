"""
chest-svc 테스트 스크립트
━━━━━━━━━━━━━━━━━━━━━━━━
사용법:
  1) chest-svc 서버를 먼저 띄운다:
     cd v3/services/chest-svc
     PYTHONPATH="../../shared:$PYTHONPATH" uvicorn main:app --port 8001

  2) 이 스크립트를 실행한다:
     cd v3
     source venv/bin/activate
     python tests/chest-svc/test_chest_svc.py

  3) 또는 특정 테스트만:
     python tests/chest-svc/test_chest_svc.py --test healthz
     python tests/chest-svc/test_chest_svc.py --test predict
"""

import httpx
import base64
import json
import sys
import os
import time

# ── 설정 ──────────────────────────────────────────────────────
BASE_URL = os.getenv("CHEST_SVC_URL", "http://localhost:8001")
TEST_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
TIMEOUT = 120.0  # 추론 시간 포함


def load_image_base64(filename: str) -> str:
    """테스트 이미지를 base64로 인코딩"""
    path = os.path.join(TEST_IMAGE_DIR, filename)
    if not os.path.exists(path):
        print(f"  [ERROR] 이미지 없음: {path}")
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def test_healthz():
    """1. Liveness 프로브 테스트 — Pod이 살아있는지 확인"""
    print("\n[TEST 1] GET /healthz (liveness probe)")
    resp = httpx.get(f"{BASE_URL}/healthz", timeout=5.0)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert data["status"] == "ok"
    print(f"  PASS — {data}")


def test_readyz():
    """2. Readiness 프로브 테스트 — 모델 3개 로딩 완료 확인"""
    print("\n[TEST 2] GET /readyz (readiness probe)")
    resp = httpx.get(f"{BASE_URL}/readyz", timeout=5.0)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert data["status"] == "ready"
    assert "unet" in data.get("models", [])
    assert "densenet" in data.get("models", [])
    assert "yolo" in data.get("models", [])
    print(f"  PASS — models: {data.get('models')}")


def test_predict_normal():
    """3. /predict 테스트 — 정상 흉부 X-Ray 이미지"""
    print("\n[TEST 3] POST /predict (정상 흉부 X-Ray)")
    image_b64 = load_image_base64("dummy/sample_chest_xray.png")
    if not image_b64:
        print("  SKIP — 테스트 이미지 없음")
        return

    payload = {
        "patient_id": "TEST-001",
        "patient_info": {
            "age": 45,
            "sex": "M",
            "chief_complaint": "건강검진",
            "history": []
        },
        "data": {
            "image_base64": image_b64
        },
        "context": {}
    }

    start = time.time()
    resp = httpx.post(f"{BASE_URL}/predict", json=payload, timeout=TIMEOUT)
    elapsed = time.time() - start

    print(f"  응답 시간: {elapsed:.2f}초")
    print(f"  상태 코드: {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        print(f"  modal: {data.get('modal')}")
        print(f"  findings 수: {len(data.get('findings', []))}")
        for f in data.get("findings", [])[:5]:
            print(f"    - {f['name']}: detected={f['detected']}, confidence={f.get('confidence', 'N/A')}")
        print(f"  summary: {data.get('summary', '')[:100]}...")
        if data.get("report"):
            print(f"  report: {data['report'][:100]}...")
        print(f"  metadata: {data.get('metadata', {})}")
        print("  PASS")
    else:
        print(f"  FAIL — {resp.text[:500]}")


def test_predict_cardiomegaly():
    """4. /predict 테스트 — 심비대 시뮬레이션 이미지"""
    print("\n[TEST 4] POST /predict (심비대 시뮬레이션)")
    image_b64 = load_image_base64("dummy/sample_cardiomegaly.png")
    if not image_b64:
        print("  SKIP — 테스트 이미지 없음")
        return

    payload = {
        "patient_id": "TEST-002",
        "patient_info": {
            "age": 67,
            "sex": "M",
            "chief_complaint": "호흡곤란",
            "history": ["고혈압", "당뇨"]
        },
        "data": {
            "image_base64": image_b64
        },
        "context": {}
    }

    start = time.time()
    resp = httpx.post(f"{BASE_URL}/predict", json=payload, timeout=TIMEOUT)
    elapsed = time.time() - start

    print(f"  응답 시간: {elapsed:.2f}초")
    print(f"  상태 코드: {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        print(f"  findings 수: {len(data.get('findings', []))}")
        for f in data.get("findings", [])[:5]:
            print(f"    - {f['name']}: detected={f['detected']}, confidence={f.get('confidence', 'N/A')}")
        print(f"  summary: {data.get('summary', '')[:100]}...")
        print("  PASS")
    else:
        print(f"  FAIL — {resp.text[:500]}")


def test_predict_with_context():
    """5. /predict 테스트 — 이전 모달 결과 context 포함"""
    print("\n[TEST 5] POST /predict (이전 모달 context 포함)")
    image_b64 = load_image_base64("dummy/sample_chest_xray.png")
    if not image_b64:
        print("  SKIP — 테스트 이미지 없음")
        return

    payload = {
        "patient_id": "TEST-003",
        "patient_info": {
            "age": 55,
            "sex": "F",
            "chief_complaint": "흉통",
            "history": ["협심증"]
        },
        "data": {
            "image_base64": image_b64
        },
        "context": {
            "ecg": {
                "findings": [
                    {"name": "st_elevation", "detected": True, "confidence": 0.88}
                ],
                "summary": "V1-V4 ST 상승 소견"
            }
        }
    }

    start = time.time()
    resp = httpx.post(f"{BASE_URL}/predict", json=payload, timeout=TIMEOUT)
    elapsed = time.time() - start

    print(f"  응답 시간: {elapsed:.2f}초")
    print(f"  상태 코드: {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        print(f"  findings 수: {len(data.get('findings', []))}")
        print(f"  summary: {data.get('summary', '')[:100]}...")
        print("  PASS")
    else:
        print(f"  FAIL — {resp.text[:500]}")


def test_predict_invalid():
    """6. /predict 에러 핸들링 — 잘못된 요청"""
    print("\n[TEST 6] POST /predict (잘못된 요청 — 이미지 없음)")
    payload = {
        "patient_id": "TEST-ERR",
        "patient_info": {
            "age": 30,
            "sex": "M",
            "chief_complaint": "test",
            "history": []
        },
        "data": {},
        "context": {}
    }

    resp = httpx.post(f"{BASE_URL}/predict", json=payload, timeout=30.0)
    print(f"  상태 코드: {resp.status_code}")
    if resp.status_code >= 400:
        print(f"  에러 응답: {resp.text[:200]}")
        print("  PASS — 에러를 올바르게 반환")
    else:
        print("  WARN — 에러가 예상되었으나 200 반환")


# ── 메인 실행 ──────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  chest-svc 통합 테스트")
    print(f"  서버: {BASE_URL}")
    print("=" * 60)

    # 서버 연결 확인
    try:
        httpx.get(f"{BASE_URL}/healthz", timeout=3.0)
    except Exception:
        print(f"\n[ERROR] 서버에 연결할 수 없습니다: {BASE_URL}")
        print("chest-svc를 먼저 실행하세요:")
        print("  cd v3/services/chest-svc")
        print('  PYTHONPATH="../../shared:$PYTHONPATH" uvicorn main:app --port 8001')
        sys.exit(1)

    # 특정 테스트만 실행
    target = None
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        target = sys.argv[2]

    tests = {
        "healthz": test_healthz,
        "readyz": test_readyz,
        "predict": test_predict_normal,
        "cardiomegaly": test_predict_cardiomegaly,
        "context": test_predict_with_context,
        "invalid": test_predict_invalid,
    }

    if target:
        if target in tests:
            tests[target]()
        else:
            print(f"알 수 없는 테스트: {target}")
            print(f"가능한 테스트: {', '.join(tests.keys())}")
    else:
        for test_fn in tests.values():
            try:
                test_fn()
            except AssertionError as e:
                print(f"  FAIL — {e}")
            except Exception as e:
                print(f"  ERROR — {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print("  테스트 완료")
    print("=" * 60)
