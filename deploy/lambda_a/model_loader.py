"""
S3 Lazy Load + /tmp cache for ONNX models.

Lambda 콜드 스타트 시 S3에서 모델을 다운로드하고, 이후 호출에서는
/tmp 파일 캐시 + 메모리 세션 캐시를 재사용.
"""

import os
import boto3
import onnxruntime as ort

# 글로벌 세션 캐시 — Lambda 컨테이너 수명 동안 유지
_sessions: dict[str, ort.InferenceSession] = {}

_s3 = boto3.client("s3")


def get_model(task: str, config) -> ort.InferenceSession:
    """
    task 에 해당하는 ONNX InferenceSession 을 반환.

    1) 메모리 캐시(_sessions)에 있으면 즉시 반환
    2) /tmp 에 파일이 있으면 세션만 생성
    3) 둘 다 없으면 S3에서 다운로드 후 세션 생성

    Args:
        task: "seg" | "densenet" | "yolo"
        config: Config 인스턴스 (S3_BUCKET, MODELS, TMP_DIR 포함)

    Returns:
        ort.InferenceSession
    """
    global _sessions

    # 1) 메모리 캐시 확인
    if task in _sessions:
        print(f"[ModelLoader] 캐시 히트: {task}")
        return _sessions[task]

    # 2) S3 키 / 로컬 경로 결정
    s3_key = config.MODELS[task]
    local_path = os.path.join(config.TMP_DIR, os.path.basename(s3_key))

    # 3) /tmp 에 파일이 없으면 S3 다운로드
    if not os.path.exists(local_path):
        print(f"[ModelLoader] S3 다운로드: s3://{config.S3_BUCKET}/{s3_key} -> {local_path}")
        _s3.download_file(config.S3_BUCKET, s3_key, local_path)
        file_size_mb = os.path.getsize(local_path) / (1024 * 1024)
        print(f"[ModelLoader] 다운로드 완료: {file_size_mb:.1f}MB")

        # 외부 데이터 파일(.onnx.data)도 다운로드 (있으면)
        data_s3_key = s3_key + ".data"
        data_local = local_path + ".data"
        try:
            _s3.head_object(Bucket=config.S3_BUCKET, Key=data_s3_key)
            print(f"[ModelLoader] 외부 데이터 다운로드: {data_s3_key}")
            _s3.download_file(config.S3_BUCKET, data_s3_key, data_local)
            data_mb = os.path.getsize(data_local) / (1024 * 1024)
            print(f"[ModelLoader] 외부 데이터 완료: {data_mb:.1f}MB")
        except Exception:
            pass  # .data 파일 없으면 무시
    else:
        print(f"[ModelLoader] /tmp 캐시 히트: {local_path}")

    # 4) InferenceSession 생성 (CPU only — Lambda 환경)
    sess_options = ort.SessionOptions()
    sess_options.inter_op_num_threads = 1
    sess_options.intra_op_num_threads = 4
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    session = ort.InferenceSession(
        local_path,
        sess_options=sess_options,
        providers=["CPUExecutionProvider"],
    )
    print(f"[ModelLoader] 세션 생성 완료: {task} (inputs={[i.name for i in session.get_inputs()]})")

    # 5) 캐시 저장
    _sessions[task] = session
    return session
