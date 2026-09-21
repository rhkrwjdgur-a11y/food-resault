import streamlit as st
import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import google.generativeai as genai
import time
import os
import json
from PIL import Image

# ==========================================
# [UI 레이아웃 픽스 & 페이지 설정]
# ==========================================
st.set_page_config(page_title="Soybean Guard AI", layout="wide")

# ==========================================
# [API 보안 연동 및 모델 설정 (Streamlit Secrets)]
# ==========================================
if "GOOGLE_API_KEY" in st.secrets:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    API_KEY = os.environ.get("GOOGLE_API_KEY")

if API_KEY:
    genai.configure(api_key=API_KEY)
    # 최신 제미나이 모델 라인업 적용
    MODEL_NAME = "gemini-3.6-flash"
    MODEL_NAME_FLASH = "gemini-3.5-flash-lite"
else:
    st.error("🚨 [시스템 오류]: .streamlit/secrets.toml 파일에 GOOGLE_API_KEY를 설정해주세요.")

# ==========================================
# [발표용 고대비 커스텀 CSS (Label Guard AI 테마 이식)]
# ==========================================
custom_theme_css = """
<style>
@media screen {
    html, body, [class*="css"] { color: #1e293b !important; font-family: 'Pretendard', -apple-system, sans-serif !important; }
    [data-testid="stSidebar"] { background-color: #f8fafc !important; border-right: 1px solid #e2e8f0 !important; }
    
    /* 탭(Tab) 모던 스타일 */
    .stTabs [data-baseweb="tab-list"] { border-bottom: 2px solid #e2e8f0 !important; gap: 8px; }
    .stTabs [data-baseweb="tab"] { background-color: transparent !important; border: none !important; border-bottom: 3px solid transparent !important; border-radius: 0 !important; padding: 12px 16px !important; color: #64748b !important; font-weight: 600 !important; }
    .stTabs [aria-selected="true"] { border-bottom: 3px solid #0f172a !important; color: #0f172a !important; }
    
    /* 마크다운 표(Table) 고도화 */
    table { border-collapse: collapse !important; width: 100% !important; margin: 1.5rem 0 !important; border: 2px solid #0f172a !important; border-radius: 8px !important; overflow: hidden !important; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1) !important; }
    thead tr { background-color: #f8fafc !important; color: #0f172a !important; border-bottom: 2px solid #0f172a !important; }
    th { font-weight: 700 !important; padding: 12px 16px !important; text-align: left !important; border-right: 1px solid #cbd5e1 !important; }
    td { padding: 12px 16px !important; border-right: 1px solid #cbd5e1 !important; border-bottom: 1px solid #e2e8f0 !important; }
    th:last-child, td:last-child { border-right: none !important; }
    tbody tr:hover { background-color: #f1f5f9 !important; }
    
    /* 액션 버튼 */
    .stButton>button { background-color: #0f172a !important; color: white !important; font-size: 15px !important; font-weight: bold !important; border-radius: 8px !important; border: none !important; padding: 12px 24px !important; transition: all 0.2s ease-in-out; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1) !important; }
    .stButton>button:hover { background-color: #334155 !important; transform: translateY(-1px); }
    hr { border-top: 2px solid #cbd5e1 !important; margin: 1.5em 0 !important; }
}
</style>
"""
st.markdown(custom_theme_css, unsafe_allow_html=True)

# ==========================================
# [OpenCV 핵심 엔진: 픽셀 수학 연산 및 번호 렌더링]
# ==========================================
@st.cache_data(show_spinner=False)
def process_soybean_vision(image_bytes, pixels_per_5mm=50):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    annotated_img = img_rgb.copy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 이진화 및 노이즈 제거
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 100, 255, cv2.THRESH_BINARY_INV)
    kernel = np.ones((3,3), np.uint8)
    opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)
    
    contours, _ = cv2.findContours(opening, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    mm_per_pixel = 5.0 / pixels_per_5mm
    stats = {
        "total": 0, "sizes_mm": [], "broken": 0, "off_color": 0, "details": []
    }
    
    count = 1
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > 100: # 미세 노이즈 제외
            stats["total"] += 1
            
            # 크기 측정
            (x, y), radius = cv2.minEnclosingCircle(cnt)
            diameter_mm = (radius * 2) * mm_per_pixel
            stats["sizes_mm"].append(diameter_mm)
            
            # 모양 측정 (원형도)
            perimeter = cv2.arcLength(cnt, True)
            circularity = 4 * np.pi * (area / (perimeter * perimeter)) if perimeter > 0 else 0
            is_broken = circularity < 0.75
            
            # 색상 측정
            mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.drawContours(mask, [cnt], -1, 255, -1)
            mean_color = cv2.mean(img_rgb, mask=mask)
            is_off_color = mean_color[0] > 80 and mean_color[1] > 80 # 임계값
            
            if is_broken: stats["broken"] += 1
            if is_off_color: stats["off_color"] += 1
            
            # 시각화 렌더링 (번호 및 테두리 마킹)
            color = (0, 255, 0) # 정상: 초록
            if is_broken: color = (255, 0, 0) # 깨짐: 파랑
            if is_off_color: color = (255, 0, 0) # 타색립/피해립: 빨강
            
            cv2.drawContours(annotated_img, [cnt], -1, color, 2)
            M = cv2.moments(cnt)
            if M['m00'] != 0:
                cx = int(M['m10'] / M['m00'])
                cy = int(M['m01'] / M['m00'])
                cv2.putText(annotated_img, str(count), (cx - 15, cy + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            
            stats["details"].append({"id": count, "size": round(diameter_mm, 2), "broken": is_broken, "off_color": is_off_color})
            count += 1

    # 최종 통계 요약
    if stats["total"] > 0:
        stats["avg_size"] = round(np.mean(stats["sizes_mm"]), 2)
        stats["min_size"] = round(np.min(stats["sizes_mm"]), 2)
        stats["max_size"] = round(np.max(stats["sizes_mm"]), 2)
        
        # 7.1mm 이상(특등 규격) 비율 계산
        premium_count = sum(1 for size in stats["sizes_mm"] if size >= 7.1)
        stats["premium_size_ratio"] = round((premium_count / stats["total"]) * 100, 1)
        stats["off_color_ratio"] = round((stats["off_color"] / stats["total"]) * 100, 1)
        stats["broken_ratio"] = round((stats["broken"] / stats["total"]) * 100, 1)
    else:
        stats["avg_size"] = stats["min_size"] = stats["max_size"] = stats["premium_size_ratio"] = stats["off_color_ratio"] = stats["broken_ratio"] = 0

    return stats, annotated_img

# ==========================================
# [앱 메인 렌더링]
# ==========================================
st.markdown("<h1>Soybean Guard AI <span style='font-size:0.5em; color:#64748b;'>대두 특등 비전 판독 및 법무 시스템 (V2.0)</span></h1>", unsafe_allow_html=True)
st.markdown("<hr>", unsafe_allow_html=True)

with st.sidebar:
    st.header("검토 설정 및 라인 연동")
    st.markdown("### 1. 비전 센서 설정")
    pixels_per_5mm = st.number_input("5mm 격자 픽셀 캘리브레이션 값", min_value=10, max_value=200, value=65, step=1)
    
    st.markdown("### 2. 샘플 이미지 업로드")
    uploaded_file = st.file_uploader("검사용 콩 이미지를 업로드하세요", type=["jpg", "png", "jpeg"])

if uploaded_file is not None:
    # 탭 구성
    tab1, tab2 = st.tabs(["1. 비전 검사 대시보드 (OpenCV 팩트 추출)", "2. AI 종합 품질 성적서 (Gemini 규격 판정)"])
    
    # 데이터 사전 연산
    image_bytes = uploaded_file.getvalue()
    stats, annotated_img = process_soybean_vision(image_bytes, pixels_per_5mm)
    
    with tab1:
        st.markdown("### 📊 실시간 광학 선별(Optical Sorter) 분석 데이터")
        
        col1, col2 = st.columns([1.5, 1])
        with col1:
            st.image(annotated_img, caption="AI 렌더링 이미지 (초록: 정상, 빨강: 타색/피해, 파랑: 파쇄립)", use_column_width=True)
        
        with col2:
            st.markdown("#### 팩트 추출 요약")
            st.metric(label="총 검사 개수", value=f"{stats['total']} 개")
            st.metric(label="대립종(7.1mm 이상) 비율", value=f"{stats['premium_size_ratio']} %")
            st.metric(label="평균 크기", value=f"{stats['avg_size']} mm")
            st.metric(label="타색/피해립 발견율", value=f"{stats['off_color_ratio']} %", delta=f"{stats['off_color']}개 적발", delta_color="inverse")
            st.metric(label="파쇄립(깨짐) 발견율", value=f"{stats['broken_ratio']} %", delta=f"{stats['broken']}개 적발", delta_color="inverse")
            
            if stats["total"] > 0:
                fig, ax = plt.subplots(figsize=(5, 3))
                ax.hist(stats['sizes_mm'], bins=8, color='#0f172a', edgecolor='white')
                ax.axvline(7.1, color='#ef4444', linestyle='dashed', linewidth=2, label='Target (7.1mm)')
                ax.set_title("Size Distribution")
                ax.legend()
                st.pyplot(fig)

    with tab2:
        st.markdown("### ⚖️ 국가 농산물 표준규격 대조 결과")
        if st.button("AI 법무 엔진 가동 (성적서 발행)", key="btn_report"):
            with st.spinner(f"[{MODEL_NAME}] OpenCV 실측 데이터를 기반으로 '농산물 표준규격 고시' 특등 기준과 대조 중입니다..."):
                try:
                    # 메인 판독에는 무거운 연산을 담당하는 3.6-flash 적용
                    model = genai.GenerativeModel(MODEL_NAME)
                    qc_prompt = f"""
                    <pre_calc>
                    [시스템 입력 데이터 (OpenCV 실측 수치 팩트)]
                    - 총 개수: {stats['total']}
                    - 7.1mm 이상 콩 비율: {stats['premium_size_ratio']}%
                    - 타색립(다른 색) 및 피해립 혼입률: {stats['off_color_ratio']}%
                    - 파쇄립(깨진 콩) 혼입률: {stats['broken_ratio']}%
                    
                    [국가 농산물 표준규격(콩) 특등 합격 커트라인]
                    - 낟알의 굵기(대립종): 7.10mm 체 잔량 비율 80% 이상
                    - 타색립/이종피색립: 0.0% 이하 (절대 혼입 불가)
                    - 파쇄립/피해립 총합: 5.0% 이하
                    </pre_calc>
                    
                    당신은 대한민국 최고 수준의 농산물 품질관리 수석 검사관입니다. 
                    위 사전 연산에 입력된 [OpenCV 실측 수치]와 [표준규격 합격 커트라인]을 1:1로 엄격하게 대조하여 아래 마크다운 표 양식으로 공식 품질 검사 성적서를 출력하십시오. (자유 서술형 문장 절대 금지, 뼈대 유지)

                    ### [대두(콩) 특등급 비전 검사 성적서]
                    | 검사 항목 | 특등 법정 커트라인 | 시스템 실측 수치 | 상세 판정 사유 | 최종 판정 (✅ 합격 / 🚨 불합격 / ⚠️ 공정 조정 요망) |
                    |---|---|---|---|---|
                    | **굵기 (7.1mm 이상 대립종)** | 80.0% 이상 | {stats['premium_size_ratio']}% | (수치 비교하여 사유 명시) | |
                    | **타색립 혼입 여부** | 0.0% (혼입불가) | {stats['off_color_ratio']}% | (수치 비교하여 사유 명시) | |
                    | **결점립 (파쇄/피해)** | 5.0% 이하 | {stats['broken_ratio']}% | (수치 비교하여 사유 명시) | |
                    
                    <br>
                    
                    #### 💡 [수석 검사관의 공정 개선 권고사항]
                    (실측 데이터를 바탕으로, 에어 젝터를 어떻게 조정해야 특등 수율을 높일 수 있을지 현장 실무자에게 2~3줄의 핵심 조언을 볼드체 섞어 작성하십시오.)
                    """
                    
                    response = model.generate_content(qc_prompt)
                    st.markdown(response.text, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"🚨 API 연결 오류: {e}")
