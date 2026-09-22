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
    MODEL_NAME = "gemini-3.6-flash"
else:
    st.error("🚨 [시스템 오류]: .streamlit/secrets.toml 파일에 GOOGLE_API_KEY를 설정해주세요.")

# ==========================================
# [발표용 고대비 커스텀 CSS]
# ==========================================
custom_theme_css = """
<style>
@media screen {
    html, body, [class*="css"] { color: #1e293b !important; font-family: 'Pretendard', -apple-system, sans-serif !important; }
    [data-testid="stSidebar"] { background-color: #f8fafc !important; border-right: 1px solid #e2e8f0 !important; }
    .stTabs [data-baseweb="tab-list"] { border-bottom: 2px solid #e2e8f0 !important; gap: 8px; }
    .stTabs [data-baseweb="tab"] { background-color: transparent !important; border: none !important; border-bottom: 3px solid transparent !important; border-radius: 0 !important; padding: 12px 16px !important; color: #64748b !important; font-weight: 600 !important; }
    .stTabs [aria-selected="true"] { border-bottom: 3px solid #0f172a !important; color: #0f172a !important; }
    table { border-collapse: collapse !important; width: 100% !important; margin: 1.5rem 0 !important; border: 2px solid #0f172a !important; border-radius: 8px !important; overflow: hidden !important; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1) !important; }
    thead tr { background-color: #f8fafc !important; color: #0f172a !important; border-bottom: 2px solid #0f172a !important; }
    th { font-weight: 700 !important; padding: 12px 16px !important; text-align: left !important; border-right: 1px solid #cbd5e1 !important; }
    td { padding: 12px 16px !important; border-right: 1px solid #cbd5e1 !important; border-bottom: 1px solid #e2e8f0 !important; }
    th:last-child, td:last-child { border-right: none !important; }
    tbody tr:hover { background-color: #f1f5f9 !important; }
    .stButton>button { background-color: #0f172a !important; color: white !important; font-size: 15px !important; font-weight: bold !important; border-radius: 8px !important; border: none !important; padding: 12px 24px !important; transition: all 0.2s ease-in-out; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1) !important; }
    .stButton>button:hover { background-color: #334155 !important; transform: translateY(-1px); }
    hr { border-top: 2px solid #cbd5e1 !important; margin: 1.5em 0 !important; }
}
</style>
"""
st.markdown(custom_theme_css, unsafe_allow_html=True)

# ==========================================
# [OpenCV 엔진 1: 격자 자동 인식 캘리브레이션]
# ==========================================
def auto_calibrate_grid(gray_img):
    """Canny 엣지 검출을 통해 5mm 격자의 픽셀 간격을 자동으로 계산합니다."""
    blurred = cv2.GaussianBlur(gray_img, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    
    h_sum = np.sum(edges, axis=1)
    w_sum = np.sum(edges, axis=0)
    
    def get_spacing(arr):
        threshold = np.mean(arr) + 1.5 * np.std(arr)
        peaks = np.where(arr > threshold)[0]
        if len(peaks) < 2:
            return None
        diffs = np.diff(peaks)
        valid_diffs = diffs[diffs > 20]
        if len(valid_diffs) == 0:
            return None
        return int(np.median(valid_diffs))
        
    h_space = get_spacing(h_sum)
    w_space = get_spacing(w_sum)
    
    spaces = [s for s in [h_space, w_space] if s is not None]
    if spaces:
        return int(np.mean(spaces))
    return None

# ==========================================
# [OpenCV 엔진 2: 픽셀 수학 연산 및 번호 렌더링 (Watershed 분할 적용)]
# ==========================================
@st.cache_data(show_spinner=False)
def process_soybean_vision(image_bytes, auto_mode=True, manual_px=65):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    annotated_img = img_rgb.copy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 캘리브레이션 픽셀 결정
    pixels_per_5mm = manual_px
    calib_msg = "수동 셋팅값"
    if auto_mode:
        auto_px = auto_calibrate_grid(gray)
        if auto_px:
            pixels_per_5mm = auto_px
            calib_msg = "자동 인식 성공"
        else:
            calib_msg = "자동 인식 실패 (기본값 적용)"

    # 이진화 및 노이즈 제거
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 100, 255, cv2.THRESH_BINARY_INV)
    kernel = np.ones((3,3), np.uint8)
    opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)
    
    # 💡 [핵심 패치]: Watershed 알고리즘을 통한 밀집 객체 강제 분할
    sure_bg = cv2.dilate(opening, kernel, iterations=3) # 확실한 배경 영역
    dist_transform = cv2.distanceTransform(opening, cv2.DIST_L2, 5) # 거리 변환 (중심점 찾기)
    ret, sure_fg = cv2.threshold(dist_transform, 0.4 * dist_transform.max(), 255, 0) # 확실한 전경(콩의 중심) 영역
    
    sure_fg = np.uint8(sure_fg)
    unknown = cv2.subtract(sure_bg, sure_fg) # 경계가 모호한 영역
    
    ret, markers = cv2.connectedComponents(sure_fg)
    markers = markers + 1 # 배경을 0이 아닌 1로 설정
    markers[unknown == 255] = 0 # 모호한 영역을 0으로 마킹
    
    markers = cv2.watershed(img, markers) # 워터쉐드 경계선 긋기
    
    # 워터쉐드로 분리된 마스크를 기반으로 새로운 윤곽선 추출
    separated_mask = np.zeros_like(gray)
    separated_mask[markers > 1] = 255
    contours, _ = cv2.findContours(separated_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    mm_per_pixel = 5.0 / pixels_per_5mm
    stats = {
        "total": 0, "sizes_mm": [], "broken": 0, "off_color": 0, "details": [],
        "calib_px": pixels_per_5mm, "calib_msg": calib_msg
    }
    
    count = 1
    for cnt in contours:
        area = cv2.contourArea(cnt)
        
        # 텍스트 노이즈 무시 (워터쉐드로 잘린 조각을 고려해 임계값을 1000으로 조정)
        if area > 1000: 
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
            if is_broken: color = (255, 0, 0) # 파쇄립: 파랑
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
st.markdown("<h1>Soybean Guard AI <span style='font-size:0.5em; color:#64748b;'>대두 특등 비전 판독 및 법무 시스템 (V4.0 - Watershed 밀집 분할)</span></h1>", unsafe_allow_html=True)
st.markdown("<hr>", unsafe_allow_html=True)

with st.sidebar:
    st.header("검토 설정 및 라인 연동")
    st.markdown("### 1. 비전 캘리브레이션 (영점 조절)")
    calib_mode = st.radio("측정 방식", ["자동 인식 (5mm 격자 배경)", "수동 입력"])
    
    manual_px = 65
    if calib_mode == "수동 입력":
        manual_px = st.number_input("5mm 픽셀 값 입력", min_value=10, max_value=200, value=65, step=1)
    
    st.markdown("### 2. 샘플 이미지 업로드")
    uploaded_file = st.file_uploader("검사용 콩 이미지를 업로드하세요", type=["jpg", "png", "jpeg"])

if uploaded_file is not None:
    tab1, tab2 = st.tabs(["1. 비전 검사 대시보드 (OpenCV 팩트 추출)", "2. AI 종합 품질 성적서 (Gemini 규격 판정)"])
    
    image_bytes = uploaded_file.getvalue()
    is_auto = (calib_mode == "자동 인식 (5mm 격자 배경)")
    stats, annotated_img = process_soybean_vision(image_bytes, is_auto, manual_px)
    
    with tab1:
        st.markdown("### 📊 실시간 광학 선별(Optical Sorter) 분석 데이터")
        if is_auto:
            st.info(f"💡 시스템 캘리브레이션: **{stats['calib_msg']}** (5mm = {stats['calib_px']}px 기준)")
        
        col1, col2 = st.columns([1.5, 1])
        with col1:
            st.image(Image.fromarray(annotated_img), caption="AI 렌더링 이미지 (초록: 정상, 빨강/파랑: 결함)", use_container_width=True)
        
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
                st.pyplot(fig)

    with tab2:
        st.markdown("### ⚖️ 국가 농산물 표준규격 대조 결과")
        if st.button("AI 법무 엔진 가동 (성적서 발행)", key="btn_report"):
            with st.spinner(f"[{MODEL_NAME}] OpenCV 실측 데이터를 기반으로 '농산물 표준규격 고시' 특등 기준과 대조 중입니다..."):
                try:
                    model = genai.GenerativeModel(MODEL_NAME)
                    qc_prompt = f"""
                    <pre_calc>
                    [시스템 입력 데이터 (OpenCV 실측 수치 팩트)]
                    - 총 개수: {stats['total']}
                    - 7.1mm 이상 콩 비율: {stats['premium_size_ratio']}%
                    - 타색립(다른 색) 및 피해립 혼입률: {stats['off_color_ratio']}%
                    - 파쇄립(깨진 콩) 혼입률: {stats['broken_ratio']}%
                    
                    [국가 농산물 표준규격(콩) 특등 합격 커트라인]
                    - 정상립: 95.0% 이상
                    - 낟알의 고르기(대립종): 7.10mm 체 잔량 비율 80.0% 이상
                    - 타색립/이종곡립: 0.0% 미만 (혼입불가)
                    - 결점립 (파쇄립/피해립/이물 등 총합): 5.0% 미만
                    </pre_calc>
                    
                    당신은 연세유업 아산공장 식품안전팀 소속 품질관리 AI 시스템입니다. 
                    위 사전 연산에 입력된 [OpenCV 실측 수치]와 [표준규격 합격 커트라인]을 대조하여 아래 HTML 및 마크다운 양식으로 공식 품질 증명서를 출력하십시오. 
                    정상립 실측치는 100%에서 타색립과 결점립 비율을 뺀 값으로 계산하십시오.
                    절대 임의로 양식을 변경하거나 서술형 문장을 추가하지 말고, 아래 뼈대를 100% 그대로 유지하여 수치와 판정만 정확히 채워 넣으십시오.

                    <div style="text-align: center; margin-bottom: 30px;">
                      <h2 style="font-weight: bold;">국산 콩 특등급 품질 증명서</h2>
                    </div>

                    ▣ **품 목** : 국산 콩 (생산 라인 투입분)<br>
                    ▣ **작성일자** : 2026년 9월 21일
                    <br><br>

                    당사에서는 아래의 내용으로 농산물 검사기준에 따른 농산물 등급의 특등급 기준 이상으로 구분관리 및 선별 정선 가공하였음을 증명합니다.
                    <br><br>

                    | 구분 | AI 비전 실측치 | 국산 콩 표준 규격 (특등급) | 최종 판정 |
                    |:---|:---:|:---:|:---:|
                    | **정상립** | (계산값)% | 95% 이상 | |
                    | **낟알의 고르기 (7.1mm 이상)** | {stats['premium_size_ratio']}% | 80% 이상 | |
                    | **타색립 및 이종곡립** | {stats['off_color_ratio']}% | 0.0% 미만 (혼입불가) | |
                    | **결점립 (파쇄/피해립 등)** | {stats['broken_ratio']}% | 5.0% 미만 | |

                    <br>
                    
                    <div style="display: flex; justify-content: flex-end;">
                      <table border="1" style="border-collapse: collapse; text-align: center; width: 350px;">
                        <tr>
                          <td rowspan="2" style="background-color: #f1f5f9; font-weight: bold; width: 16%;">결<br>재</td>
                          <td style="background-color: #f1f5f9; font-weight: bold; width: 28%;">검사자</td>
                          <td style="background-color: #f1f5f9; font-weight: bold; width: 28%;">팀장</td>
                          <td style="background-color: #f1f5f9; font-weight: bold; width: 28%;">부문장</td>
                        </tr>
                        <tr>
                          <td style="height: 70px; vertical-align: bottom; padding: 5px;">(인)</td>
                          <td style="height: 70px; vertical-align: bottom; padding: 5px;">(인)</td>
                          <td style="height: 70px; vertical-align: bottom; padding: 5px;">(인)</td>
                        </tr>
                      </table>
                    </div>
                    """
                    
                    response = model.generate_content(qc_prompt)
                    st.markdown(response.text, unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"🚨 API 연결 오류: {e}")
