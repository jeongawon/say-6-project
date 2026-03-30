import numpy as np
import pytest
from unittest.mock import MagicMock

from app.inference import run_inference
from app.schemas import PredictRequest, ECGData


def make_dummy_signal():
    return np.random.randn(12, 5000).astype(np.float32)


def make_mock_session(probs=None):
    """ONNX 세션 모킹"""
    if probs is None:
        probs = np.full(13, 0.3, dtype=np.float32)
    logits = np.log(probs / (1 - probs + 1e-7))

    session = MagicMock()
    session.run.return_value = [logits[np.newaxis, :]]
    return session


def make_request(prev=""):
    return PredictRequest(
        patient_id="TEST-001",
        data=ECGData(signal_path="s3://dummy/path", leads=12),
        context={"previous_findings": prev} if prev else {},
    )


def test_normal_response_structure():
    signal  = make_dummy_signal()
    session = make_mock_session()
    request = make_request()
    result  = run_inference(signal, request, session)

    assert result.status == "success"
    assert result.modal == "ecg"
    assert len(result.findings) == 13
    assert result.summary is not None
    assert result.metadata is not None


def test_findings_count():
    signal  = make_dummy_signal()
    session = make_mock_session()
    result  = run_inference(signal, make_request(), session)
    assert len(result.findings) == 13


def test_context_reflected_in_summary():
    signal  = make_dummy_signal()
    session = make_mock_session(np.full(13, 0.1))  # 전부 음성
    result  = run_inference(signal, make_request(prev="Chest: Cardiomegaly"), session)
    assert "Chest: Cardiomegaly" in result.summary


def test_error_handling():
    bad_signal = np.array([])   # 잘못된 입력
    session    = make_mock_session()
    result     = run_inference(bad_signal, make_request(), session)
    assert result.status == "error"
    assert result.error is not None
