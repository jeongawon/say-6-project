#!/usr/bin/env python3
"""
best_model_s6.pt → ecg_s6.onnx 변환 스크립트

사용법:
  python export_onnx.py
  python export_onnx.py --model best_model_s6.pt --out ecg_s6.onnx
"""
import argparse
import sys
import torch

sys.argv = ['export']  # argparse 충돌 방지
from train_ecg_s6 import S6Backbone, ECGClassifier

def export(model_path: str, out_path: str):
    backbone = S6Backbone(in_channels=12, d_model=512, n_layers=6, dropout=0.1)
    model    = ECGClassifier(backbone)
    model.load_state_dict(torch.load(model_path, map_location='cpu'))
    model.eval()
    print(f"모델 로드 완료: {model_path}")

    dummy_ecg  = torch.randn(1, 12, 1000)
    dummy_demo = torch.tensor([[0.5, 0.0]])

    torch.onnx.export(
        model,
        (dummy_ecg, dummy_demo),
        out_path,
        input_names  = ['ecg_signal', 'demographics'],
        output_names = ['logits'],
        dynamic_axes = {
            'ecg_signal':   {0: 'batch'},
            'demographics': {0: 'batch'},
            'logits':       {0: 'batch'},
        },
        opset_version = 17,
    )
    print(f"ONNX 변환 완료: {out_path}")

    import onnxruntime as ort
    sess = ort.InferenceSession(out_path, providers=['CPUExecutionProvider'])
    out  = sess.run(None, {
        'ecg_signal':   dummy_ecg.numpy(),
        'demographics': dummy_demo.numpy(),
    })
    print(f"ONNX 추론 검증 완료 — logits shape: {out[0].shape}")  # (1, 24)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='best_model_s6.pt')
    parser.add_argument('--out',   default='ecg_s6.onnx')
    args = parser.parse_args()
    export(args.model, args.out)
