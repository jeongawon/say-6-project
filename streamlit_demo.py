"""
ECG 임상 의사결정 지원 시스템 — 데모
EMR 스타일 임상 대시보드
"""

import json
import csv
import time
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from collections import defaultdict
from datetime import datetime

# ── 페이지 설정 ───────────────────────────────────────────────
st.set_page_config(
    page_title="ECG-AI | 임상 의사결정 지원",
    page_icon="🫀",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── 글로벌 스타일 ─────────────────────────────────────────────
st.markdown("""
<style>
  /* 전체 배경 */
  .stApp { background-color: #0f1117; color: #e8eaf0; }

  /* 헤더 바 */
  .emr-header {
    background: linear-gradient(90deg, #1a1f2e 0%, #0d1b2a 100%);
    border-bottom: 2px solid #2196f3;
    padding: 10px 20px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .emr-logo { font-size: 1.4em; font-weight: 700; color: #2196f3; letter-spacing: 2px; }
  .emr-subtitle { font-size: 0.75em; color: #78909c; }

  /* 환자 배너 */
  .patient-banner {
    background: #1a1f2e;
    border: 1px solid #263238;
    border-left: 4px solid #2196f3;
    padding: 12px 20px;
    border-radius: 4px;
    margin-bottom: 12px;
  }
  .patient-name { font-size: 1.3em; font-weight: 700; color: #e8eaf0; }
  .patient-meta { font-size: 0.85em; color: #90a4ae; margin-top: 2px; }

  /* 알림 배너 */
  .alert-critical {
    background: #2d0a0a; border: 1px solid #ef5350;
    border-left: 5px solid #ef5350;
    padding: 12px 18px; border-radius: 4px; margin: 8px 0;
    animation: pulse 2s infinite;
  }
  .alert-urgent {
    background: #1f1600; border: 1px solid #ffa726;
    border-left: 5px solid #ffa726;
    padding: 12px 18px; border-radius: 4px; margin: 8px 0;
  }
  .alert-routine {
    background: #141820; border: 1px solid #546e7a;
    border-left: 5px solid #546e7a;
    padding: 12px 18px; border-radius: 4px; margin: 8px 0;
  }
  @keyframes pulse {
    0%,100% { border-left-color: #ef5350; }
    50%      { border-left-color: #ff8a80; }
  }

  /* 소견 카드 */
  .finding-critical {
    background: #1a0808; border: 1px solid #ef5350;
    padding: 10px 14px; border-radius: 4px; margin: 4px 0;
  }
  .finding-severe {
    background: #1a1008; border: 1px solid #ffa726;
    padding: 10px 14px; border-radius: 4px; margin: 4px 0;
  }
  .finding-moderate {
    background: #131a08; border: 1px solid #ffee58;
    padding: 10px 14px; border-radius: 4px; margin: 4px 0;
  }
  .finding-mild {
    background: #081a0a; border: 1px solid #66bb6a;
    padding: 10px 14px; border-radius: 4px; margin: 4px 0;
  }

  /* 지표 카드 */
  .metric-card {
    background: #1a1f2e; border: 1px solid #263238;
    padding: 14px 18px; border-radius: 6px; text-align: center;
  }
  .metric-value { font-size: 1.8em; font-weight: 700; color: #2196f3; }
  .metric-label { font-size: 0.78em; color: #78909c; margin-top: 2px; }

  /* 섹션 타이틀 */
  .section-title {
    font-size: 0.8em; font-weight: 600; color: #546e7a;
    letter-spacing: 1.5px; text-transform: uppercase;
    border-bottom: 1px solid #1e2a38; padding-bottom: 6px; margin-bottom: 10px;
  }

  /* 버튼 */
  .stButton > button {
    background: #1565c0; color: white; border: none;
    font-weight: 600; letter-spacing: 0.5px;
    padding: 10px 0; border-radius: 4px;
  }
  .stButton > button:hover { background: #1976d2; }

  /* 테이블 */
  .stDataFrame { border: 1px solid #263238 !important; }

  /* 사이드바 */
  section[data-testid="stSidebar"] { background: #0d1117; }

  /* selectbox */
  .stSelectbox > div > div { background: #1a1f2e; border-color: #263238; }
  div[data-baseweb="select"] { background: #1a1f2e; }
</style>
""", unsafe_allow_html=True)

# ── 상수 ─────────────────────────────────────────────────────
ECG_SVC_URL   = "http://13.124.117.190:8000"
GOLDEN_PATH   = "sampled_200_goldendataset.jsonl"
MANIFEST_PATH = "processed/manifest.csv"
S3_WAVEFORM   = "s3://say2-6team/mimic/ecg/waveforms/files"

LEAD_NAMES = ['I','II','V1','V2','V3','V4','V5','V6','III','aVR','aVL','aVF']

LABEL_KO = {
    'afib_flutter':'심방세동/조동','heart_failure':'심부전','hypertension':'고혈압',
    'chronic_ihd':'만성 허혈성 심질환','acute_mi':'급성 심근경색',
    'paroxysmal_tachycardia':'발작성 빈맥','av_block_lbbb':'방실차단/좌각차단',
    'other_conduction':'기타 전도장애','pulmonary_embolism':'폐색전증',
    'cardiac_arrest':'심정지','angina':'협심증','pericardial_disease':'심낭질환',
    'afib_detail':'심방세동(세부)','hf_detail':'심부전(세부)','dm2':'제2형 당뇨병',
    'acute_kidney_failure':'급성 신부전','hypothyroidism':'갑상선기능저하증',
    'copd':'COPD','chronic_kidney':'만성 신장질환','hyperkalemia':'고칼륨혈증',
    'hypokalemia':'저칼륨혈증','respiratory_failure':'호흡부전','sepsis':'패혈증',
    'calcium_disorder':'칼슘 대사 이상',
}

TARGET_LABELS = list(LABEL_KO.keys())

SEV_BADGE = {
    'critical': '<span style="background:#ef5350;color:#fff;padding:2px 8px;border-radius:3px;font-size:0.75em;font-weight:700">CRITICAL</span>',
    'severe':   '<span style="background:#ffa726;color:#000;padding:2px 8px;border-radius:3px;font-size:0.75em;font-weight:700">SEVERE</span>',
    'moderate': '<span style="background:#ffee58;color:#000;padding:2px 8px;border-radius:3px;font-size:0.75em;font-weight:700">MODERATE</span>',
    'mild':     '<span style="background:#66bb6a;color:#000;padding:2px 8px;border-radius:3px;font-size:0.75em;font-weight:700">MILD</span>',
}


# ── 데이터 로딩 ───────────────────────────────────────────────
@st.cache_data
def load_patients():
    golden = {}
    for line in open(GOLDEN_PATH):
        rec = json.loads(line)
        golden[rec['join_keys']['subject_id']] = rec

    by_subject = defaultdict(list)
    with open(MANIFEST_PATH) as f:
        for row in csv.DictReader(f):
            if row['subject_id'] in golden:
                by_subject[row['subject_id']].append(row)

    patients = []
    for sid, rows in by_subject.items():
        rows.sort(key=lambda r: int(r['study_id']))
        r   = rows[0]
        g   = golden[sid]
        age = round(float(r['age_norm']) * 83 + 18, 1)
        sex = 'M' if float(r['gender_enc']) == 1.0 else 'F' if float(r['gender_enc']) == 0.0 else 'Unknown'
        ml  = g['ml_features']
        patients.append({
            'subject_id':      sid,
            'study_id':        r['study_id'],
            'age':             age,
            'sex':             sex,
            'chief_complaint': ml.get('1_symptoms_and_history', '')[:150],
            'golden_dx':       (ml.get('3_diagnosis', {}) or {}).get('primary', '') if isinstance(ml.get('3_diagnosis'), dict) else str(ml.get('3_diagnosis', '') or ''),
            'npy_file':        r['npy_file'],
            **{k: int(r[k]) for k in TARGET_LABELS},
        })
    return pd.DataFrame(patients)


def make_record_path(subject_id: str, study_id: str) -> str:
    return f"{S3_WAVEFORM}/p{subject_id[:4]}/p{subject_id}/s{study_id}/{study_id}"


def load_ecg_signal(npy_file: str) -> np.ndarray | None:
    """로컬 processed/ 에서 ECG 파형 로드 (시각화용)"""
    try:
        sig = np.load(f"processed/{npy_file}")  # (1000, 12)
        return sig
    except Exception:
        return None


# ── ECG 12리드 파형 플롯 ──────────────────────────────────────
def plot_12lead(sig: np.ndarray) -> go.Figure:
    """12리드 ECG 파형 — 임상 표준 3열×4행 레이아웃"""
    # 3컬럼 × 4행 배치
    layout = [
        ['I',   'aVR', 'V1', 'V4'],
        ['II',  'aVL', 'V2', 'V5'],
        ['III', 'aVF', 'V3', 'V6'],
    ]
    rows, cols = 3, 4
    fig = make_subplots(
        rows=rows, cols=cols,
        shared_xaxes=False,
        vertical_spacing=0.04,
        horizontal_spacing=0.04,
        subplot_titles=[lead for row in layout for lead in row],
    )

    t = np.arange(sig.shape[0]) / 100  # 초 단위

    for r_idx, row in enumerate(layout):
        for c_idx, lead in enumerate(row):
            lead_idx = LEAD_NAMES.index(lead)
            signal   = sig[:, lead_idx]

            fig.add_trace(
                go.Scatter(
                    x=t, y=signal,
                    mode='lines',
                    line=dict(color='#00e676', width=0.9),
                    name=lead,
                    showlegend=False,
                    hovertemplate=f'{lead}: %{{y:.3f}} mV<extra></extra>',
                ),
                row=r_idx + 1, col=c_idx + 1,
            )

    # 격자 스타일 (임상용 밀리미터 격자 느낌)
    fig.update_xaxes(
        showgrid=True, gridcolor='#1a2a1a', gridwidth=1,
        zeroline=False, showticklabels=False,
        tickmode='linear', dtick=0.2,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor='#1a2a1a', gridwidth=1,
        zeroline=True, zerolinecolor='#2a3a2a', zerolinewidth=1,
        showticklabels=False,
        tickmode='linear', dtick=0.5,
    )
    fig.update_layout(
        height=380,
        paper_bgcolor='#0a1a0a',
        plot_bgcolor='#0a1a0a',
        margin=dict(l=10, r=10, t=30, b=10),
        font=dict(color='#90a4ae', size=11),
    )
    # subplot 타이틀 스타일
    for ann in fig.layout.annotations:
        ann.font.color = '#80cbc4'
        ann.font.size  = 11

    return fig


# ── API 호출 ──────────────────────────────────────────────────
def call_predict(patient: dict) -> dict:
    payload = {
        'patient_id': patient['study_id'],
        'patient_info': {
            'age':             patient['age'],
            'sex':             patient['sex'],
            'chief_complaint': patient['chief_complaint'],
            'history':         [],
        },
        'data': {
            'record_path': make_record_path(patient['subject_id'], patient['study_id']),
            'leads': 12,
        },
        'context': {'subject_id': patient['subject_id']},
    }
    resp = requests.post(f"{ECG_SVC_URL}/predict", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ════════════════════════════════════════════════════════════
# 헤더
# ════════════════════════════════════════════════════════════
st.markdown("""
<div class="emr-header">
  <div>
    <div class="emr-logo">⚡ ECG-AI</div>
    <div class="emr-subtitle">응급실 임상 의사결정 지원 시스템 | MIMIC-IV S6 모델</div>
  </div>
  <div style="font-size:0.8em;color:#546e7a">
    AI 보조 진단 도구 — 최종 판단은 담당 의사의 책임하에 수행됩니다
  </div>
</div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════
# 사이드바: 서비스 상태 + 환자 검색
# ════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div class="section-title">서비스 상태</div>', unsafe_allow_html=True)
    try:
        r = requests.get(f"{ECG_SVC_URL}/ready", timeout=2)
        if r.status_code == 200:
            st.success("ECG-AI 서비스 정상")
        else:
            st.warning("모델 로딩 중...")
    except Exception:
        st.error("서비스 오프라인")

    st.divider()
    st.markdown('<div class="section-title">환자 필터</div>', unsafe_allow_html=True)
    search     = st.text_input("증상 / 진단 검색", placeholder="chest pain, sepsis...")
    sex_filter = st.radio("성별", ["전체", "M", "F"], horizontal=True)

df = load_patients()

filtered = df.copy()
if search:
    mask = (
        filtered['chief_complaint'].str.contains(search, case=False, na=False) |
        filtered['golden_dx'].str.contains(search, case=False, na=False)
    )
    filtered = filtered[mask]
if sex_filter != '전체':
    filtered = filtered[filtered['sex'] == sex_filter]

# ════════════════════════════════════════════════════════════
# 메인 레이아웃: 환자 목록 | 분석 결과
# ════════════════════════════════════════════════════════════
list_col, result_col = st.columns([1, 2], gap="medium")

with list_col:
    st.markdown('<div class="section-title">환자 목록</div>', unsafe_allow_html=True)
    st.caption(f"총 {len(filtered)}명")

    # 환자 선택 버튼 목록
    for _, row in filtered.head(50).iterrows():
        label = f"**{row['study_id']}** · {row['age']}세 {row['sex']}  \n{row['golden_dx'][:50] or row['chief_complaint'][:50]}"
        if st.button(label, key=f"btn_{row['study_id']}", use_container_width=True):
            st.session_state['selected_patient'] = row.to_dict()
            st.session_state.pop('result', None)

with result_col:
    patient = st.session_state.get('selected_patient')

    if patient is None:
        st.markdown("""
        <div style="height:400px;display:flex;align-items:center;justify-content:center;
                    color:#37474f;font-size:1.1em;border:1px dashed #263238;border-radius:8px">
          ← 좌측에서 환자를 선택하세요
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    # ── 환자 배너 ─────────────────────────────────────────
    st.markdown(f"""
    <div class="patient-banner">
      <div class="patient-name">
        ID {patient['subject_id']} &nbsp;|&nbsp; Study {patient['study_id']}
      </div>
      <div class="patient-meta">
        {patient['age']}세 &nbsp;·&nbsp; {patient['sex']} &nbsp;·&nbsp;
        주 증상: {patient['chief_complaint'][:100] or '—'}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 12리드 ECG 파형 ───────────────────────────────────
    st.markdown('<div class="section-title">12-Lead ECG</div>', unsafe_allow_html=True)
    sig = load_ecg_signal(patient['npy_file'])
    if sig is not None:
        st.plotly_chart(plot_12lead(sig), use_container_width=True, config={'displayModeBar': False})
        st.caption(f"100Hz · 10초 · 12리드  |  Record: {patient['study_id']}")
    else:
        st.info("파형 파일 없음 (processed/ 디렉토리 확인)")

    # ── 분석 실행 버튼 ────────────────────────────────────
    st.markdown('<div class="section-title">AI 분석</div>', unsafe_allow_html=True)

    if st.button("▶  ECG AI 분석 실행", type="primary", use_container_width=True):
        with st.spinner("분석 중..."):
            try:
                t0     = time.perf_counter()
                result = call_predict(patient)
                elapsed = round((time.perf_counter() - t0) * 1000, 1)
                result['_client_latency'] = elapsed
                st.session_state['result'] = result
            except requests.exceptions.ConnectionError:
                st.error("서비스 연결 실패 — run_local.sh 실행 후 재시도")
            except Exception as e:
                st.error(f"오류: {e}")

    result = st.session_state.get('result')
    if result is None:
        st.stop()

    # ════════════════════════════════════════════════════
    # 분석 결과
    # ════════════════════════════════════════════════════
    findings = result.get('findings', [])
    risk     = result.get('risk_level', 'routine')
    summary  = result.get('summary', '')
    meta     = result.get('metadata', {})

    # 위험도 알림 배너
    risk_cls  = {'critical': 'alert-critical', 'urgent': 'alert-urgent', 'routine': 'alert-routine'}
    risk_icon = {'critical': '🚨 CRITICAL', 'urgent': '⚠️ URGENT', 'routine': '— ROUTINE'}
    st.markdown(f"""
    <div class="{risk_cls.get(risk, 'alert-routine')}">
      <b style="font-size:1.05em">{risk_icon.get(risk, risk.upper())}</b>
      &nbsp;&nbsp; {summary}
    </div>
    """, unsafe_allow_html=True)

    # 지표 4개
    n_det = meta.get("num_detected", len(findings))
    lat   = meta.get("latency_ms", "—")
    det_color = '#ef5350' if n_det >= 3 else ('#ffa726' if n_det >= 1 else '#90a4ae')

    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f'<div class="metric-card"><div class="metric-value" style="color:{det_color}">{n_det}</div><div class="metric-label">검출 질환</div></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card"><div class="metric-value">{lat}</div><div class="metric-label">Latency (ms)</div></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card"><div class="metric-value">{patient["age"]:.0f}</div><div class="metric-label">Age</div></div>', unsafe_allow_html=True)
    m4.markdown(f'<div class="metric-card"><div class="metric-value">{patient["sex"]}</div><div class="metric-label">Sex</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 검출 소견 ─────────────────────────────────────────
    st.markdown('<div class="section-title">검출 소견</div>', unsafe_allow_html=True)

    if not findings:
        st.markdown('<div class="alert-routine">유의한 이상 소견 없음</div>', unsafe_allow_html=True)
    else:
        # severity 순서 정렬: critical > severe > moderate > mild
        sev_order = {'critical': 0, 'severe': 1, 'moderate': 2, 'mild': 3}
        sorted_findings = sorted(
            findings,
            key=lambda f: (sev_order.get(f.get('severity', 'mild'), 4), -f['confidence'])
        )
        for f in sorted_findings:
            sev   = f.get('severity', 'mild')
            badge = SEV_BADGE.get(sev, '')
            rec   = f.get('recommendation', '')
            ko    = LABEL_KO.get(f['name'], f['name'])
            conf  = f['confidence']

            # confidence 바
            bar_color = {'critical':'#ef5350','severe':'#ffa726','moderate':'#ffee58','mild':'#66bb6a'}.get(sev,'#90a4ae')
            bar_width = int(conf * 100)

            st.markdown(f"""
            <div class="finding-{sev}">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-weight:700;font-size:1.0em">{ko}</span>
                <span>{badge} &nbsp; <span style="font-size:1.1em;font-weight:700;color:{bar_color}">{conf:.1%}</span></span>
              </div>
              <div style="background:#1e1e1e;border-radius:3px;height:5px;margin:6px 0">
                <div style="background:{bar_color};width:{bar_width}%;height:5px;border-radius:3px"></div>
              </div>
              {'<div style="font-size:0.82em;color:#90a4ae;margin-top:4px">💊 ' + rec + '</div>' if rec else ''}
            </div>
            """, unsafe_allow_html=True)

    # ── ECG Vitals ────────────────────────────────────────
    vitals = result.get('ecg_vitals')
    if vitals:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-title">ECG Vital Signs</div>', unsafe_allow_html=True)

        hr    = vitals.get('heart_rate')
        brady = vitals.get('bradycardia', False)
        tachy = vitals.get('tachycardia', False)
        irreg = vitals.get('irregular_rhythm', False)

        # HR 게이지 색상 로직
        if hr is None:
            hr_display = "N/A"
            hr_color   = '#546e7a'
            hr_status  = '측정 불가'
        elif brady:
            hr_display = f"{hr:.0f}"
            hr_color   = '#42a5f5'
            hr_status  = 'Bradycardia (< 50 bpm)'
        elif tachy:
            hr_display = f"{hr:.0f}"
            hr_color   = '#ef5350'
            hr_status  = 'Tachycardia (> 100 bpm)'
        else:
            hr_display = f"{hr:.0f}"
            hr_color   = '#90a4ae'
            hr_status  = '50 – 100 bpm 범위'

        irr_color  = '#ffa726' if irreg else '#90a4ae'
        irr_label  = 'Irregular' if irreg else 'Regular'

        v1, v2 = st.columns(2)
        v1.markdown(f"""
        <div class="metric-card" style="position:relative;overflow:hidden">
          <div style="font-size:0.7em;color:#546e7a;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Heart Rate</div>
          <div style="display:flex;align-items:baseline;justify-content:center;gap:6px">
            <span style="font-size:2.8em;font-weight:800;color:{hr_color};line-height:1">{hr_display}</span>
            <span style="font-size:0.9em;color:#78909c">bpm</span>
          </div>
          <div style="font-size:0.75em;color:{hr_color};margin-top:4px;font-weight:600">{hr_status}</div>
          {'<div style="position:absolute;top:6px;right:10px;font-size:0.65em;background:'+hr_color+';color:#000;padding:1px 6px;border-radius:3px;font-weight:700">⚠</div>' if (brady or tachy) else ''}
        </div>
        """, unsafe_allow_html=True)

        v2.markdown(f"""
        <div class="metric-card">
          <div style="font-size:0.7em;color:#546e7a;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Rhythm</div>
          <div style="font-size:1.1em;font-weight:700;color:{irr_color};margin-top:12px">{irr_label}</div>
        </div>
        """, unsafe_allow_html=True)

    # ── 확률 전체 차트 ────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">24개 질환 전체 확률</div>', unsafe_allow_html=True)

    finding_map = {f['name']: f for f in findings}
    all_probs = []
    for lbl in TARGET_LABELS:
        f = finding_map.get(lbl)
        all_probs.append({
            'label':      LABEL_KO.get(lbl, lbl),
            'name':       lbl,
            'prob':       f['confidence'] if f else 0.0,
            'detected':   lbl in finding_map,
        })

    prob_df = pd.DataFrame(all_probs).sort_values('prob', ascending=True)
    colors  = ['#ef5350' if r['detected'] else '#37474f' for _, r in prob_df.iterrows()]

    fig_bar = go.Figure(go.Bar(
        x=prob_df['prob'],
        y=prob_df['label'],
        orientation='h',
        marker_color=colors,
        text=[f"{p:.1%}" for p in prob_df['prob']],
        textposition='outside',
        textfont=dict(size=10, color='#90a4ae'),
        hovertemplate='%{y}: %{x:.1%}<extra></extra>',
    ))
    fig_bar.update_layout(
        height=520,
        paper_bgcolor='#0f1117',
        plot_bgcolor='#0f1117',
        xaxis=dict(
            range=[0, 1.05], tickformat='.0%',
            gridcolor='#1e2a38', color='#546e7a',
        ),
        yaxis=dict(color='#90a4ae', tickfont=dict(size=11)),
        margin=dict(l=10, r=60, t=10, b=10),
        shapes=[dict(
            type='line', x0=0.5, x1=0.5, y0=-0.5, y1=len(prob_df)-0.5,
            line=dict(color='#546e7a', width=1, dash='dot'),
        )],
    )
    st.plotly_chart(fig_bar, use_container_width=True, config={'displayModeBar': False})

    # ── Ground Truth 비교 (데모 전용) ─────────────────────
    with st.expander("📊 Ground Truth 비교 (데모 전용)"):
        detected_set = set(finding_map.keys())
        gt_set       = {lbl for lbl in TARGET_LABELS if patient.get(lbl, 0) == 1}

        tp = detected_set & gt_set
        fp = detected_set - gt_set
        fn = gt_set - detected_set

        c1, c2, c3 = st.columns(3)
        with c1:
            st.success(f"**TP ({len(tp)})**")
            for x in sorted(tp): st.write(f"· {LABEL_KO.get(x, x)}")
        with c2:
            st.error(f"**FP ({len(fp)})**")
            for x in sorted(fp): st.write(f"· {LABEL_KO.get(x, x)}")
        with c3:
            st.warning(f"**FN ({len(fn)})**")
            for x in sorted(fn): st.write(f"· {LABEL_KO.get(x, x)}")

        st.caption(f"Golden Dx: {patient['golden_dx']}")
