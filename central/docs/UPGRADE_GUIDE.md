# Upgrade Guide - 하드코딩에서 ML 모델로 전환

## 개요

현재 시스템은 하드코딩된 규칙 기반으로 작동하지만, 각 컴포넌트가 모듈화되어 있어 학습된 모델로 쉽게 교체할 수 있습니다.

## 교체 가능한 컴포넌트

```
┌─────────────────────────────────────────────────────────────┐
│                    현재 (하드코딩)                           │
├─────────────────────────────────────────────────────────────┤
│ 1. Fusion Decision Engine (규칙 기반)                       │
│    → ML 기반 의사결정 모델로 교체                           │
│                                                              │
│ 2. Modal Connectors (Mock 응답)                             │
│    → 실제 학습된 모달 모델로 교체                           │
│                                                              │
│ 3. RAG System (MIMIC 데이터)                                │
│    → 더 큰 데이터셋, 더 나은 임베딩 모델로 교체             │
│                                                              │
│ 4. Bedrock Reasoning (Claude)                               │
│    → Fine-tuned 모델 또는 다른 LLM으로 교체                 │
└─────────────────────────────────────────────────────────────┘
```

## 1. Fusion Decision Engine 업그레이드

### 현재 구조
```python
# deploy/orchestrator/fusion_decision/decision_engine.py
class FusionDecisionEngine:
    def decide(self):
        # 하드코딩된 if-else 규칙
        if self._has_high_risk_pattern():
            return {'decision': 'NEED_REASONING'}
        # ...
```

### Option A: ML 분류 모델로 교체

```python
# deploy/orchestrator/fusion_decision/ml_decision_engine.py
import joblib
import numpy as np

class MLDecisionEngine:
    """ML 기반 의사결정 엔진"""
    
    def __init__(self, model_path='s3://bucket/models/decision_model.pkl'):
        self.model = self._load_model(model_path)
        self.feature_extractor = FeatureExtractor()
    
    def _load_model(self, model_path):
        """S3에서 학습된 모델 로드"""
        # Download from S3
        local_path = '/tmp/decision_model.pkl'
        s3.download_file(bucket, key, local_path)
        return joblib.load(local_path)
    
    def decide(self):
        """ML 모델 기반 의사결정"""
        # 특징 추출
        features = self.feature_extractor.extract(
            patient=self.patient,
            modalities_completed=self.modalities_completed,
            inference_results=self.inference_results,
            iteration=self.iteration
        )
        
        # 모델 예측
        decision_probs = self.model.predict_proba([features])[0]
        decision_idx = np.argmax(decision_probs)
        
        decisions = ['CALL_NEXT_MODALITY', 'NEED_REASONING', 'GENERATE_REPORT']
        decision = decisions[decision_idx]
        confidence = decision_probs[decision_idx]
        
        # 다음 모달 예측 (별도 모델)
        if decision == 'CALL_NEXT_MODALITY':
            next_modalities = self._predict_next_modalities(features)
        else:
            next_modalities = []
        
        return {
            'decision': decision,
            'next_modalities': next_modalities,
            'confidence': float(confidence),
            'rationale': self._generate_rationale(decision, features),
            'risk_level': self._assess_risk(features)
        }
    
    def _predict_next_modalities(self, features):
        """다음 호출할 모달 예측 (Multi-label classification)"""
        modality_probs = self.modality_model.predict_proba([features])[0]
        
        # 임계값 이상인 모달 선택
        threshold = 0.5
        modalities = ['CXR', 'ECG', 'LAB']
        selected = [m for m, p in zip(modalities, modality_probs) if p > threshold]
        
        return selected if selected else [modalities[np.argmax(modality_probs)]]


class FeatureExtractor:
    """의사결정을 위한 특징 추출"""
    
    def extract(self, patient, modalities_completed, inference_results, iteration):
        """특징 벡터 생성"""
        features = []
        
        # 1. 환자 특징
        features.extend(self._extract_patient_features(patient))
        
        # 2. 모달 완료 상태 (one-hot)
        features.extend([
            1 if 'CXR' in modalities_completed else 0,
            1 if 'ECG' in modalities_completed else 0,
            1 if 'LAB' in modalities_completed else 0
        ])
        
        # 3. 결과 특징
        features.extend(self._extract_result_features(inference_results))
        
        # 4. 반복 횟수
        features.append(iteration)
        
        return np.array(features)
    
    def _extract_patient_features(self, patient):
        """환자 정보에서 특징 추출"""
        # Chief complaint 임베딩 (사전 학습된 임베딩 사용)
        cc_embedding = self._embed_chief_complaint(patient.get('chief_complaint', ''))
        
        # 바이탈 정규화
        vitals = patient.get('vitals', {})
        hr = self._normalize_hr(vitals.get('HR', '0'))
        bp_sys = self._normalize_bp(vitals.get('BP', '0/0'), 'systolic')
        
        return list(cc_embedding) + [hr, bp_sys]
    
    def _extract_result_features(self, inference_results):
        """모달 결과에서 특징 추출"""
        if not inference_results:
            return [0] * 10  # 빈 특징
        
        features = []
        
        # 평균 신뢰도
        avg_confidence = np.mean([r.get('confidence', 0) for r in inference_results])
        features.append(avg_confidence)
        
        # 최소 신뢰도
        min_confidence = np.min([r.get('confidence', 1) for r in inference_results])
        features.append(min_confidence)
        
        # Finding 텍스트 임베딩 (평균)
        finding_embeddings = [
            self._embed_finding(r.get('finding', ''))
            for r in inference_results
        ]
        avg_embedding = np.mean(finding_embeddings, axis=0)
        features.extend(avg_embedding)
        
        return features
```

### Option B: 강화학습 모델로 교체

```python
# deploy/orchestrator/fusion_decision/rl_decision_engine.py
import torch
import torch.nn as nn

class RLDecisionEngine:
    """강화학습 기반 의사결정 엔진"""
    
    def __init__(self, model_path='s3://bucket/models/rl_policy.pth'):
        self.policy_net = self._load_policy_network(model_path)
        self.state_encoder = StateEncoder()
    
    def decide(self):
        """RL 정책 네트워크 기반 의사결정"""
        # 현재 상태 인코딩
        state = self.state_encoder.encode(
            patient=self.patient,
            modalities_completed=self.modalities_completed,
            inference_results=self.inference_results,
            iteration=self.iteration
        )
        
        # 정책 네트워크로 액션 선택
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            action_probs = self.policy_net(state_tensor)
            action = torch.argmax(action_probs).item()
        
        # 액션을 의사결정으로 변환
        return self._action_to_decision(action, action_probs)
    
    def _action_to_decision(self, action, probs):
        """액션 인덱스를 의사결정으로 변환"""
        # Action space: [CALL_CXR, CALL_ECG, CALL_LAB, REASONING, REPORT]
        action_map = {
            0: {'decision': 'CALL_NEXT_MODALITY', 'next_modalities': ['CXR']},
            1: {'decision': 'CALL_NEXT_MODALITY', 'next_modalities': ['ECG']},
            2: {'decision': 'CALL_NEXT_MODALITY', 'next_modalities': ['LAB']},
            3: {'decision': 'NEED_REASONING', 'next_modalities': []},
            4: {'decision': 'GENERATE_REPORT', 'next_modalities': []}
        }
        
        decision = action_map[action]
        decision['confidence'] = float(probs[0][action])
        decision['rationale'] = f"RL policy selected action {action} with confidence {decision['confidence']:.2f}"
        
        return decision


class PolicyNetwork(nn.Module):
    """정책 네트워크"""
    
    def __init__(self, state_dim, action_dim):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, action_dim),
            nn.Softmax(dim=-1)
        )
    
    def forward(self, state):
        return self.network(state)
```

### Lambda 함수 수정 (교체)

```python
# deploy/orchestrator/fusion_decision/lambda_function.py
import os

# 환경변수로 엔진 선택
ENGINE_TYPE = os.environ.get('DECISION_ENGINE_TYPE', 'rule_based')

if ENGINE_TYPE == 'ml':
    from ml_decision_engine import MLDecisionEngine as DecisionEngine
elif ENGINE_TYPE == 'rl':
    from rl_decision_engine import RLDecisionEngine as DecisionEngine
else:
    from decision_engine import FusionDecisionEngine as DecisionEngine


def handler(event, context):
    """변경 없음 - 엔진만 교체"""
    engine = DecisionEngine(
        patient=patient,
        modalities_completed=modalities_completed,
        inference_results=inference_results,
        iteration=iteration
    )
    
    decision_result = engine.decide()
    return decision_result
```

### 배포 시 환경변수 설정

```yaml
# template.yaml
FusionDecisionFunction:
  Properties:
    Environment:
      Variables:
        DECISION_ENGINE_TYPE: ml  # 'rule_based' | 'ml' | 'rl'
        MODEL_BUCKET: !Ref ModelBucket
        MODEL_KEY: models/decision_model.pkl
```

## 2. Modal Connector 업그레이드

### CXR Modal - 실제 모델로 교체

```python
# deploy/modal_connectors/cxr_connector/lambda_function.py

def handler(event, context):
    """CXR 모달 - 실제 모델 또는 외부 API 호출"""
    
    # Option 1: 외부 API 호출 (이미 구현됨)
    if CXR_API_ENDPOINT:
        return call_cxr_api(case_id, cxr_image_url, cxr_data)
    
    # Option 2: Lambda 내 모델 추론 (경량 모델)
    elif USE_LOCAL_MODEL:
        return run_local_inference(cxr_image_url)
    
    # Option 3: SageMaker 엔드포인트 호출
    elif SAGEMAKER_ENDPOINT:
        return call_sagemaker_endpoint(cxr_image_url)
    
    # Fallback: Mock
    else:
        return generate_mock_response(case_id, patient)


def call_sagemaker_endpoint(image_url):
    """SageMaker 엔드포인트로 추론 요청"""
    import boto3
    
    sagemaker = boto3.client('sagemaker-runtime')
    
    # 이미지 다운로드 및 전처리
    image_data = download_and_preprocess(image_url)
    
    # SageMaker 호출
    response = sagemaker.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType='application/x-image',
        Body=image_data
    )
    
    result = json.loads(response['Body'].read())
    
    # 표준 형식으로 변환
    return {
        "modality": "CXR",
        "finding": result['diagnosis'],
        "confidence": result['confidence'],
        "details": result['details'],
        "rationale": result['explanation'],
        "timestamp": datetime.utcnow().isoformat()
    }


def run_local_inference(image_url):
    """Lambda 내에서 경량 모델 실행"""
    import onnxruntime as ort
    
    # ONNX 모델 로드 (첫 실행 시 S3에서 다운로드)
    if not hasattr(run_local_inference, 'session'):
        model_path = download_model_from_s3()
        run_local_inference.session = ort.InferenceSession(model_path)
    
    # 이미지 전처리
    image = preprocess_image(image_url)
    
    # 추론
    outputs = run_local_inference.session.run(None, {'input': image})
    
    # 후처리
    return postprocess_outputs(outputs)
```

### ECG/LAB Modal - 실제 시스템 연동

```python
# deploy/modal_connectors/ecg_connector/lambda_function.py

def handler(event, context):
    """ECG 모달 - 실제 ECG 분석 시스템 연동"""
    
    ecg_data = patient.get('ecg_data')
    
    if not ecg_data:
        return generate_mock_response(case_id, patient)
    
    # Option 1: 외부 ECG 분석 API
    if ECG_API_ENDPOINT:
        return call_ecg_api(ecg_data)
    
    # Option 2: 자체 ECG 분석 모델
    elif ECG_MODEL_ENDPOINT:
        return analyze_ecg_with_model(ecg_data)
    
    # Fallback
    else:
        return generate_mock_response(case_id, patient)


def analyze_ecg_with_model(ecg_data):
    """ECG 신호 분석 모델"""
    # ECG 신호 전처리
    signal = preprocess_ecg_signal(ecg_data)
    
    # 모델 추론 (예: 1D CNN)
    result = ecg_model.predict(signal)
    
    return {
        "modality": "ECG",
        "finding": result['interpretation'],
        "confidence": result['confidence'],
        "details": {
            "rhythm": result['rhythm'],
            "rate": result['rate'],
            "intervals": result['intervals'],
            "abnormalities": result['abnormalities']
        },
        "rationale": result['explanation']
    }
```

## 3. 모델 학습 파이프라인

### 데이터 수집

```python
# training/data_collection.py
"""
실제 운영 데이터로부터 학습 데이터 수집
"""

def collect_training_data():
    """S3에서 완료된 케이스 데이터 수집"""
    
    cases = []
    
    # S3에서 모든 케이스 로드
    for case_file in list_s3_cases():
        case_data = load_case_from_s3(case_file)
        
        # 학습 샘플 생성
        samples = extract_training_samples(case_data)
        cases.extend(samples)
    
    return cases


def extract_training_samples(case_data):
    """케이스에서 학습 샘플 추출"""
    samples = []
    
    workflow_history = case_data['workflow_history']
    
    for i, decision in enumerate(workflow_history):
        # 상태 (입력)
        state = {
            'patient': case_data['patient'],
            'modalities_completed': get_modalities_at_step(case_data, i),
            'inference_results': get_results_at_step(case_data, i),
            'iteration': i + 1
        }
        
        # 액션 (레이블)
        action = decision['decision']
        next_modalities = decision.get('next_modalities', [])
        
        # 보상 (최종 결과 기반)
        reward = calculate_reward(case_data, i)
        
        samples.append({
            'state': state,
            'action': action,
            'next_modalities': next_modalities,
            'reward': reward
        })
    
    return samples


def calculate_reward(case_data, step):
    """보상 계산"""
    # 요소들:
    # 1. 진단 정확도 (의료진 피드백)
    # 2. 검사 비용 (모달 수)
    # 3. 시간 (반복 횟수)
    # 4. 위험도 적절성
    
    accuracy_score = case_data.get('accuracy_feedback', 0.5)
    num_modalities = len(case_data['modalities_used'])
    num_iterations = len(case_data['workflow_history'])
    
    # 보상 = 정확도 - 비용 페널티
    reward = accuracy_score - 0.1 * num_modalities - 0.05 * num_iterations
    
    return reward
```

### 모델 학습

```python
# training/train_decision_model.py
"""
의사결정 모델 학습
"""
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
import joblib

def train_decision_model(training_data):
    """의사결정 분류 모델 학습"""
    
    # 특징 추출
    X = []
    y_decision = []
    y_modalities = []
    
    feature_extractor = FeatureExtractor()
    
    for sample in training_data:
        features = feature_extractor.extract(**sample['state'])
        X.append(features)
        y_decision.append(sample['action'])
        y_modalities.append(sample['next_modalities'])
    
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y_decision, test_size=0.2, random_state=42
    )
    
    # 모델 학습
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    # 평가
    accuracy = model.score(X_test, y_test)
    print(f"Test accuracy: {accuracy:.3f}")
    
    # 저장
    joblib.dump(model, 'decision_model.pkl')
    
    # S3 업로드
    upload_to_s3('decision_model.pkl', MODEL_BUCKET, 'models/decision_model.pkl')
    
    return model
```

### 강화학습 학습

```python
# training/train_rl_policy.py
"""
강화학습 정책 학습
"""
import torch
import torch.optim as optim

def train_rl_policy(training_data, num_epochs=100):
    """PPO 알고리즘으로 정책 학습"""
    
    policy_net = PolicyNetwork(state_dim=50, action_dim=5)
    optimizer = optim.Adam(policy_net.parameters(), lr=0.001)
    
    for epoch in range(num_epochs):
        epoch_loss = 0
        
        for batch in create_batches(training_data, batch_size=32):
            # 상태, 액션, 보상 추출
            states = torch.FloatTensor([b['state_vector'] for b in batch])
            actions = torch.LongTensor([b['action_idx'] for b in batch])
            rewards = torch.FloatTensor([b['reward'] for b in batch])
            
            # 정책 네트워크 출력
            action_probs = policy_net(states)
            
            # 손실 계산 (Policy Gradient)
            log_probs = torch.log(action_probs.gather(1, actions.unsqueeze(1)))
            loss = -(log_probs * rewards.unsqueeze(1)).mean()
            
            # 역전파
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item()
        
        print(f"Epoch {epoch+1}/{num_epochs}, Loss: {epoch_loss:.4f}")
    
    # 저장
    torch.save(policy_net.state_dict(), 'rl_policy.pth')
    upload_to_s3('rl_policy.pth', MODEL_BUCKET, 'models/rl_policy.pth')
    
    return policy_net
```

## 4. 배포 전략

### A/B 테스트

```python
# deploy/orchestrator/fusion_decision/lambda_function.py

def handler(event, context):
    """A/B 테스트로 새 모델 검증"""
    
    case_id = event.get('case_id')
    
    # 케이스 ID 해시로 그룹 분할
    group = hash(case_id) % 100
    
    if group < 10:  # 10% 트래픽
        engine = MLDecisionEngine(...)  # 새 모델
        engine_version = 'ml_v1'
    else:  # 90% 트래픽
        engine = FusionDecisionEngine(...)  # 기존 규칙
        engine_version = 'rule_based'
    
    decision = engine.decide()
    decision['engine_version'] = engine_version
    
    # 메트릭 기록
    log_decision_metrics(case_id, engine_version, decision)
    
    return decision
```

### 점진적 롤아웃

```yaml
# template.yaml - Lambda Alias와 가중치 사용

FusionDecisionFunctionVersion:
  Type: AWS::Lambda::Version
  Properties:
    FunctionName: !Ref FusionDecisionFunction

FusionDecisionAlias:
  Type: AWS::Lambda::Alias
  Properties:
    FunctionName: !Ref FusionDecisionFunction
    FunctionVersion: !GetAtt FusionDecisionFunctionVersion.Version
    Name: live
    RoutingConfig:
      AdditionalVersionWeights:
        - FunctionVersion: !GetAtt NewFusionDecisionFunctionVersion.Version
          FunctionWeight: 0.1  # 10% 트래픽
```

## 5. 모니터링 및 평가

```python
# monitoring/evaluate_model.py
"""
모델 성능 모니터링
"""

def evaluate_model_performance():
    """실시간 모델 성능 평가"""
    
    metrics = {
        'accuracy': [],
        'avg_modalities': [],
        'avg_iterations': [],
        'avg_time': []
    }
    
    # 최근 케이스 분석
    recent_cases = get_recent_cases(days=7)
    
    for case in recent_cases:
        # 의료진 피드백 (정확도)
        if 'accuracy_feedback' in case:
            metrics['accuracy'].append(case['accuracy_feedback'])
        
        # 효율성 메트릭
        metrics['avg_modalities'].append(len(case['modalities_used']))
        metrics['avg_iterations'].append(len(case['workflow_history']))
        metrics['avg_time'].append(case['processing_time'])
    
    # 통계
    results = {
        'accuracy': np.mean(metrics['accuracy']),
        'avg_modalities': np.mean(metrics['avg_modalities']),
        'avg_iterations': np.mean(metrics['avg_iterations']),
        'avg_time': np.mean(metrics['avg_time'])
    }
    
    # CloudWatch에 게시
    publish_metrics_to_cloudwatch(results)
    
    return results
```

## 요약

### 교체 우선순위

1. **즉시 가능**: Modal Connectors (CXR API 연동)
2. **단기** (1-2개월): ML 기반 Fusion Decision
3. **중기** (3-6개월): 강화학습 기반 최적화
4. **장기** (6-12개월): End-to-end 학습 시스템

### 핵심 장점

✅ **모듈화**: 각 컴포넌트 독립적 교체 가능
✅ **하위 호환성**: 인터페이스 유지로 다른 부분 영향 없음
✅ **점진적 업그레이드**: A/B 테스트로 안전한 전환
✅ **확장성**: 새로운 모달, 새로운 모델 쉽게 추가

현재 구조는 프로토타입으로 빠르게 검증하고, 데이터가 쌓이면 학습된 모델로 점진적으로 업그레이드하는 전략에 최적화되어 있습니다!
