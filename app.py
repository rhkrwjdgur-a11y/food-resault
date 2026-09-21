import streamlit as st
import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image

def analyze_soybeans(image_bytes, pixels_per_5mm=50):
    """
    OpenCV를 사용하여 콩의 개수, 크기(mm), 색상, 모양을 분석하는 함수입니다.
    pixels_per_5mm: 5mm 격자가 이미지 상에서 차지하는 픽셀 수 (초기 캘리브레이션 값)
    """
    # 1. 이미지 로드 및 전처리
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 가우시안 블러 및 이진화 (배경과 콩 분리)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 100, 255, cv2.THRESH_BINARY_INV)
    
    # 노이즈 제거 (모폴로지 연산)
    kernel = np.ones((3,3), np.uint8)
    opening = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)
    
    # 2. 외곽선(Contour) 추출
    contours, _ = cv2.findContours(opening, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    mm_per_pixel = 5.0 / pixels_per_5mm
    
    total_count = 0
    sizes_mm = []
    off_color_count = 0
    broken_count = 0
    
    # 3. 개별 콩 데이터 분석
    for cnt in contours:
        area = cv2.contourArea(cnt)
        
        # 너무 작은 노이즈 픽셀은 콩으로 인식하지 않음
        if area > 100:
            total_count += 1
            
            # 크기 계산 (mm) - 최소 외접원의 지름 사용
            (x, y), radius = cv2.minEnclosingCircle(cnt)
            diameter_mm = (radius * 2) * mm_per_pixel
            sizes_mm.append(diameter_mm)
            
            # 모양 계산 (원형도: 1에 가까울수록 원형)
            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * (area / (perimeter * perimeter))
            
            if circularity < 0.75: # 기준치 이하면 깨진 콩(파쇄립)으로 간주
                broken_count += 1
                
            # 색상 계산 (마스크 생성 후 평균 색상 추출)
            mask = np.zeros(gray.shape, dtype=np.uint8)
            cv2.drawContours(mask, [cnt], -1, 255, -1)
            mean_val = cv2.mean(img_rgb, mask=mask)
            
            # 검은콩 기준: R, G, B 채널 값이 비정상적으로 높으면(밝으면) 껍질이 벗겨진 것으로 간주
            if mean_val[0] > 80 and mean_val[1] > 80: # 임계값은 환경에 따라 조절 필요
                off_color_count += 1

    # 4. 통계 산출
    if total_count > 0:
        avg_size = np.mean(sizes_mm)
        min_size = np.min(sizes_mm)
        max_size = np.max(sizes_mm)
        off_color_ratio = (off_color_count / total_count) * 100
        broken_ratio = (broken_count / total_count) * 100
    else:
        avg_size = min_size = max_size = off_color_ratio = broken_ratio = 0.0

    return {
        "total_count": total_count,
        "sizes_mm": sizes_mm,
        "avg_size": avg_size,
        "min_size": min_size,
        "max_size": max_size,
        "off_color_ratio": off_color_ratio,
        "broken_count": broken_count
    }

# 5. Streamlit 웹 인터페이스 구성
st.set_page_config(page_title="대두(콩) 특등 자동 분석기", layout="wide")
st.title("대두 비전 검사 대시보드")

uploaded_file = st.file_uploader("5mm 격자 콩 이미지를 업로드하세요", type=["jpg", "png", "jpeg"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="업로드된 원본 이미지", width=500)
    
    if st.button("분석 실행"):
        with st.spinner("이미지를 분석하고 있습니다..."):
            image_bytes = uploaded_file.getvalue()
            results = analyze_soybeans(image_bytes, pixels_per_5mm=65) # 65는 예시 캘리브레이션 픽셀
            
            st.subheader("📊 검사 결과 요약")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric(label="1. 총 개수", value=f"{results['total_count']} 개")
            col2.metric(label="2. 평균 크기", value=f"{results['avg_size']:.2f} mm")
            col3.metric(label="3. 색상 불량률", value=f"{results['off_color_ratio']:.1f} %")
            col4.metric(label="4. 깨진 콩 개수", value=f"{results['broken_count']} 개")
            
            st.subheader("📏 크기 상세 정보")
            col5, col6 = st.columns(2)
            col5.metric(label="2-1. 최소 크기", value=f"{results['min_size']:.2f} mm")
            col6.metric(label="2-2. 최대 크기", value=f"{results['max_size']:.2f} mm")
            
            # 2-3. 사이즈 분포 그래프 그리기 (Matplotlib)
            st.subheader("📈 2-3. 크기 분포 그래프")
            if results['total_count'] > 0:
                fig, ax = plt.subplots(figsize=(8, 4))
                ax.hist(results['sizes_mm'], bins=10, color='skyblue', edgecolor='black')
                ax.axvline(results['avg_size'], color='red', linestyle='dashed', linewidth=2, label=f'Average: {results["avg_size"]:.2f}mm')
                ax.axvline(7.1, color='green', linestyle='dashed', linewidth=2, label='Target (7.1mm)')
                ax.set_title("Soybean Size Distribution")
                ax.set_xlabel("Size (mm)")
                ax.set_ylabel("Frequency (Count)")
                ax.legend()
                st.pyplot(fig)
