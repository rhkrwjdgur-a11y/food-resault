import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import dateutil.relativedelta

# 1. 기본 페이지 설정
st.set_page_config(page_title="식품안전 및 원산지 통합 모니터링", layout="wide")

# CSS 디자인
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .penalty-card { border: 1px solid #ddd; padding: 15px; border-radius: 10px; background-color: white; margin-top: 20px; margin-bottom: 20px; border-left: 5px solid #e74c3c; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    .origin-card { border: 1px solid #ddd; padding: 15px; border-radius: 10px; background-color: white; margin-top: 20px; margin-bottom: 20px; border-left: 5px solid #27ae60; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    .info-box { background-color: #e9ecef; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; }
    .dairy-box { background-color: #e3f2fd; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; border: 1px solid #90caf9;}
    .guide-text { color: #2980b9; font-weight: bold; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🥛 일반식품·축산물 행정처분 및 원산지 통합 모니터링")

# 2. 통합 행정처분 데이터 로드 (5000건 확보로 확장)
def get_data_integrated():
    try:
        api_key = st.secrets["FOOD_SAFETY_API_KEY"]
    except KeyError:
        return [], "Secrets에 'FOOD_SAFETY_API_KEY'가 없습니다. 식품안전나라 키를 확인해 주십시오."
    
    service_id = "I0470"
    all_items = []
    
    try:
        # 식당 데이터에 밀리지 않도록 5페이지(5000건) 자동 연속 호출
        for i in range(5):
            start = i * 1000 + 1
            end = (i + 1) * 1000
            url = f"http://openapi.foodsafetykorea.go.kr/api/{api_key}/{service_id}/json/{start}/{end}"
            response = requests.get(url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if service_id in data and 'row' in data[service_id]:
                    all_items.extend(data[service_id]['row'])
    except Exception as e:
        return all_items, f"통합망 API 통신 장애: {e}"
        
    return all_items, None

# 3. 농관원 원산지 적발현황 데이터 로드 (통계 데이터)
def get_data_origin():
    try:
        api_key = st.secrets["MAFRA_API_KEY"]
    except KeyError:
        return [], "Secrets에 'MAFRA_API_KEY'가 등록되지 않았습니다."
    
    all_items = []
    try:
        for i in range(3):
            start = i * 1000 + 1
            end = (i + 1) * 1000
            url = f"http://211.237.50.150:7080/openapi/{api_key}/json/Grid_20151027000000000243_1/{start}/{end}"
            response = requests.get(url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                grid_key = 'Grid_20151027000000000243_1'
                if grid_key in data and 'row' in data[grid_key]:
                    all_items.extend(data[grid_key]['row'])
    except Exception as e:
        return all_items, f"원산지 API 통신 장애: {e}"
        
    return all_items, None

# 4. 데이터 수집 및 전처리
with st.spinner("통합망(5,000건) 및 원산지(3,000건) 데이터를 딥서치 수집 중입니다..."):
    items_integrated, err_integrated = get_data_integrated()
    items_origin, err_origin = get_data_origin()

# 통합 행정처분 데이터 전처리
integrated_list = []
for item in items_integrated:
    comp_name = item.get('BSSH_NM') or item.get('PRCSCITYPOINT_BSSHNM') or item.get('ENTP_NM') or item.get('CMPNY_NM') or '확인불가'
    law_name = item.get('VIOLT_NM') or item.get('LAWORD_CD_NM') or '내용 없음'
    viol_content = item.get('VIOLT_CN') or item.get('VILTCN') or '내용 없음'
    disp_name = item.get('DISPOS_CN') or item.get('DISPOS_NM') or item.get('DSPSCN') or '내용 없음'
    disp_date = str(item.get('DISPOS_DT') or item.get('DSPS_DCSNDT') or item.get('ADM_DISP_DT') or '내용 없음')
    address = item.get('ADDR') or item.get('SITE_ADDR_RD') or '내용 없음'

    integrated_list.append({
        '업체명': comp_name,
        '위반법령': law_name,
        '위반내용': viol_content,
        '행정처분명': disp_name,
        '처분확정일': disp_date,
        '소재지': address,
        '출처': '식품안전나라(토탈)'
    })

df_integrated_raw = pd.DataFrame(integrated_list)
df_integrated = pd.DataFrame()

if not df_integrated_raw.empty:
    # 📌 팩트 로직: 불필요한 접객업(식당, 카페 등) 키워드 원천 차단 블랙리스트
    exclude_keywords = ['카페', '치킨', '피자', '호프', '포차', '식당', '반점', '다방', '음식점', '제과점', '버거', '김밥', '떡볶이', '갈비', '국밥', '가든', '분식']
    exclude_pattern = '|'.join(exclude_keywords)
    
    # 블랙리스트 단어가 업체명에 포함되지 않은(~) 데이터만 살림
    df_integrated = df_integrated_raw[~df_integrated_raw['업체명'].str.contains(exclude_pattern, na=False, regex=True)].copy()
    
    # 중복 제거 후 무조건 가장 최신 날짜순으로 정렬
    df_integrated = df_integrated.drop_duplicates(subset=['업체명', '위반내용', '처분확정일'], keep='first')
    df_integrated = df_integrated.sort_values(by='처분확정일', ascending=False).reset_index(drop=True)

# 원산지 통계 데이터 전처리 및 요청 품목 필터링
origin_list = []
for item in items_origin:
    origin_list.append({
        '처분년월': str(item.get('DSPS_YM', '내용 없음')),
        '시도명': item.get('CTY_DO_NM', '내용 없음'),
        '업무구분': item.get('JOB_SE_NM', '내용 없음'),
        '위반품목': item.get('VIOLT_PRDLST', '내용 없음'),
        '위반유형': item.get('VIOLT_TY', '내용 없음'),
        '위반건수': int(item.get('VIOLT_CO', 0)) if str(item.get('VIOLT_CO', 0)).isdigit() else 0,
        '위반물량': str(item.get('VIOLT_VOLM', '0'))
    })
df_origin_raw = pd.DataFrame(origin_list)

df_origin = pd.DataFrame()
if not df_origin_raw.empty:
    target_keywords = ['우유', '두유', '음료', '환자', '가공유', '발효유', '원유', '유가공', '요거트', '치즈', '주스', '즙', '유제품', '분유', '유조리']
    origin_pattern = '|'.join(target_keywords)
    
    df_origin_filtered = df_origin_raw[df_origin_raw['위반품목'].str.contains(origin_pattern, na=False, regex=True)].copy()
    
    if not df_origin_filtered.empty:
        df_origin_filtered['연도'] = df_origin_filtered['처분년월'].str[:4]
        df_origin = df_origin_filtered.sort_values(by='처분년월', ascending=False).reset_index(drop=True)

# 에러 메시지 알림
if err_integrated:
    st.warning(f"통합 행정처분 연동 알림: {err_integrated}")
if err_origin:
    st.error(f"원산지 연동 알림: {err_origin}")

# 전체 현황판 출력
st.markdown(f"""
<div class="info-box">
    <strong>💡 실시간 딥서치 수집 현황</strong>: 통합 행정처분망 <strong>{len(df_integrated)}건</strong> (접객업 필터링 완료) / 취급 품목 지정 원산지 통계 <strong>{len(df_origin)}건</strong> 연동 완료
</div>
""", unsafe_allow_html=True)

# 5. 5개의 독립된 탭 구성
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔍 전체 업체 통합 검색", 
    "🥛 유가공·유제품 동향", 
    "📅 월별 신규 등록 내역", 
    "🌾 원산지 위반 통계",
    "📊 행정처분 통계 분석"
])

# ==========================================
# 탭 1: 전체 업체 통합 검색
# ==========================================
with tab1:
    st.subheader("🔍 특정 업체 행정처분 이력 검색")
    search_keyword = st.text_input("검색할 업체명을 입력하세요", key="search_input")
    
    if search_keyword:
        search_df = df_integrated[df_integrated['업체명'].str.contains(search_keyword, na=False)].reset_index(drop=True)
        
        if search_df.empty:
            st.success(f"'{search_keyword}'(으)로 검색된 내역이 없습니다.")
        else:
            st.warning(f"총 {len(search_df)}건의 내역이 발견되었습니다.")
            
            search_display = search_df[['업체명', '위반법령', '행정처분명', '처분확정일', '출처']].copy()
            st.markdown('<p class="guide-text">👇 표에서 원하는 업체를 클릭하면 상세 정보가 나타납니다.</p>', unsafe_allow_html=True)
            
            event_search = st.dataframe(search_display, use_container_width=True, on_select="rerun", selection_mode="single-row")
            
            if len(event_search.selection.rows) > 0:
                detail = search_df.iloc[event_search.selection.rows[0]]
                st.markdown(f"""
                <div class="penalty-card">
                    <h3>🏢 {detail['업체명']} <span style="font-size:12px; color:gray;">({detail['출처']})</span></h3>
                    <p><strong>⚠️ 위반법령:</strong> {detail['위반법령']}</p>
                    <p><strong>📝 위반내용:</strong> {detail['위반내용']}</p>
                    <p><strong>⚖️ 행정처분명:</strong> {detail['행정처분명']}</p>
                    <p><strong>📅 처분확정일:</strong> {detail['처분확정일']}</p>
                    <p><strong>📍 소재지:</strong> {detail['소재지']}</p>
                </div>
                """, unsafe_allow_html=True)

# ==========================================
# 탭 2: 유가공·유제품 동향
# ==========================================
with tab2:
    st.subheader("🥛 동종업계(유제품/유가공) 처분 동향")
    dairy_keywords = ['유업', '우유', '치즈', '요거트', '목장', '유가공', '밀크', '다논', '푸르밀', '매일', '남양', '서울우유', '빙그레', '연세', '파스퇴르']
    
    st.markdown(f"""
    <div class="dairy-box">
        ✔️ <strong>적용된 필터링 키워드:</strong> {', '.join(dairy_keywords)}
    </div>
    """, unsafe_allow_html=True)

    dairy_pattern = '|'.join(dairy_keywords)
    dairy_df = df_integrated[df_integrated['업체명'].str.contains(dairy_pattern, na=False, regex=True)].reset_index(drop=True)

    if dairy_df.empty:
        st.info("현재 공표된 내역 중 유가공/유제품 관련 업체의 적발 건은 없습니다.")
    else:
        st.error(f"동종업계 위반 내역 총 {len(dairy_df)}건이 조회되었습니다.")
        dairy_display = dairy_df[['업체명', '위반법령', '행정처분명', '처분확정일', '출처']].copy()
        st.markdown('<p class="guide-text">👇 표에서 원하는 업체를 클릭하면 상세 정보가 나타납니다.</p>', unsafe_allow_html=True)
        
        event_dairy = st.dataframe(dairy_display, use_container_width=True, on_select="rerun", selection_mode="single-row")
        
        if len(event_dairy.selection.rows) > 0:
            detail = dairy_df.iloc[event_dairy.selection.rows[0]]
            st.markdown(f"""
            <div class="penalty-card">
                <h3>🏢 {detail['업체명']} <span style="font-size:12px; color:gray;">({detail['출처']})</span></h3>
                <p><strong>⚠️ 위반법령:</strong> {detail['위반법령']}</p>
                <p><strong>📝 위반내용:</strong> {detail['위반내용']}</p>
                <p><strong>⚖️ 행정처분명:</strong> {detail['행정처분명']}</p>
                <p><strong>📅 처분확정일:</strong> {detail['처분확정일']}</p>
                <p><strong>📍 소재지:</strong> {detail['소재지']}</p>
            </div>
            """, unsafe_allow_html=True)

# ==========================================
# 탭 3: 월별 신규 등록 내역
# ==========================================
with tab3:
    st.subheader("📅 월별 제조가공업 행정처분 리스트")
    
    available_months = set()
    for d in df_integrated['처분확정일']:
        date_val = str(d).replace('-', '')
        if len(date_val) >= 6 and date_val.isdigit():
            available_months.add(f"{date_val[:4]}.{date_val[4:6]}")
            
    month_list = sorted(list(available_months), reverse=True)
    
    if month_list:
        selected_month = st.selectbox("조회할 처분 월을 선택하세요", month_list)
        selected_year_month = selected_month.replace(".", "")
        
        month_df = df_integrated[df_integrated['처분확정일'].str.replace('-', '').str.startswith(selected_year_month, na=False)].reset_index(drop=True)
        
        if not month_df.empty:
            month_display = month_df[['업체명', '위반법령', '행정처분명', '처분확정일', '출처']].copy()
            st.markdown('<p class="guide-text">👇 표에서 원하는 업체를 클릭하면 상세 정보가 나타납니다.</p>', unsafe_allow_html=True)
            
            event_month = st.dataframe(month_display, use_container_width=True, on_select="rerun", selection_mode="single-row")
            
            if len(event_month.selection.rows) > 0:
                detail = month_df.iloc[event_month.selection.rows[0]]
                st.markdown(f"""
                <div class="penalty-card">
                    <h3>🏢 {detail['업체명']} <span style="font-size:12px; color:gray;">({detail['출처']})</span></h3>
                    <p><strong>⚠️ 위반법령:</strong> {detail['위반법령']}</p>
                    <p><strong>📝 위반내용:</strong> {detail['위반내용']}</p>
                    <p><strong>⚖️ 행정처분명:</strong> {detail['행정처분명']}</p>
                    <p><strong>📅 처분확정일:</strong> {detail['처분확정일']}</p>
                    <p><strong>📍 소재지:</strong> {detail['소재지']}</p>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("표시할 수 있는 월별 데이터가 없습니다.")

# ==========================================
# 탭 4: 원산지 위반 통계
# ==========================================
with tab4:
    st.subheader("🌾 지정 품목 원산지 표시 적발 현황")
    
    if df_origin.empty:
        st.info("해당 취급 품목군에 대입되는 최신 3000건 내 원산지 위반 통계 데이터가 없습니다.")
    else:
        unique_years = sorted(list(df_origin['연도'].unique()), reverse=True)
        selected_year = st.selectbox("조회할 원산지 적발 연도를 선택하세요", unique_years, key="origin_year_select")
        
        yearly_origin_df = df_origin[df_origin['연도'] == selected_year].reset_index(drop=True)
        
        st.markdown(f"""
        <div class="dairy-box">
            🎯 <strong>{selected_year}년도 취급 품목 모니터링 범위:</strong> 우유, 두유, 음료, 환자식, 가공유 관련 적발 총 <strong>{len(yearly_origin_df)}건</strong> 조회됨
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown('<p class="guide-text">👇 내역을 클릭하면 하단에 상세 누적 적발 건수와 물량이 표시됩니다.</p>', unsafe_allow_html=True)
        
        origin_display = yearly_origin_df[['처분년월', '시도명', '위반품목', '위반유형', '위반건수']].copy()
        event_origin = st.dataframe(origin_display, use_container_width=True, on_select="rerun", selection_mode="single-row")
        
        if len(event_origin.selection.rows) > 0:
            detail = yearly_origin_df.iloc[event_origin.selection.rows[0]]
            st.markdown(f"""
            <div class="origin-card">
                <h3>📍 {detail['시도명']} 지역 세부 데이터 <span style="font-size:12px; color:gray;">(적발년월: {detail['처분년월']})</span></h3>
                <p><strong>🔍 업무구분:</strong> {detail['업무구분']}</p>
                <p><strong>⚠️ 위반품목:</strong> {detail['위반품목']}</p>
                <p><strong>❌ 위반유형:</strong> {detail['위반유형']}</p>
                <p><strong>📊 해당 월 적발건수:</strong> {detail['위반건수']} 건</p>
                <p><strong>📦 해당 월 적발물량:</strong> {detail['위반물량']}</p>
            </div>
            """, unsafe_allow_html=True)

# ==========================================
# 탭 5: 행정처분 통계 분석
# ==========================================
with tab5:
    st.subheader("📊 통합 행정처분 통계 현황 및 원인 분석")
    
    if df_integrated.empty:
        st.info("통계를 생성할 행정처분 기본 데이터가 존재하지 않습니다.")
    else:
        df_stats = df_integrated.copy()
        df_stats['연도'] = df_stats['처분확정일'].str.replace('-', '').str[:4]
        
        unique_years_stat = sorted(list(df_stats['연도'].unique()), reverse=True)
        selected_stat_year = st.selectbox("📊 조회할 기준 연도를 선택하세요", ["전체"] + unique_years_stat)
        
        if selected_stat_year != "전체":
            df_stats_filtered = df_stats[df_stats['연도'] == selected_stat_year].reset_index(drop=True)
        else:
            df_stats_filtered = df_stats.copy()

        st.markdown(f"""
        <div class="info-box">
            <strong>{selected_stat_year}년도 행정처분 총 {len(df_stats_filtered)}건 집계 완료 (접객업 제외)</strong>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 📅 연도별 행정처분 발생 추이")
            if selected_stat_year == "전체":
                yearly_counts = df_stats_filtered.groupby('연도').size().reset_index(name='처분건수')
                yearly_counts = yearly_counts.sort_values(by='연도')
                chart_data_year = yearly_counts.set_index('연도')
                st.bar_chart(chart_data_year, color="#e74c3c")
            else:
                st.info(f"{selected_stat_year}년 단일 연도가 선택되어 추이 그래프가 생략되었습니다. '전체'를 선택하면 추이를 볼 수 있습니다.")
            
        with col2:
            st.markdown("### ⚖️ 가장 많이 발생하는 위반 법령 TOP 10")
            law_counts = df_stats_filtered.groupby('위반법령').size().reset_index(name='적발건수')
            law_counts = law_counts.sort_values(by='적발건수', ascending=False).head(10).reset_index(drop=True)
            chart_data_law = law_counts.set_index('위반법령')
            st.bar_chart(chart_data_law, color="#2980b9")
            
        st.markdown("---")
        st.markdown("### 🔍 위반법령별 구체적 적발 사유 (심층 분석)")
        st.markdown('<p class="guide-text">👇 아래 표에서 특정 위반법령을 클릭하면, 해당 법령으로 적발된 실제 위반 내용과 사유를 상세하게 파악할 수 있습니다.</p>', unsafe_allow_html=True)
        
        event_law = st.dataframe(law_counts, use_container_width=True, on_select="rerun", selection_mode="single-row")
        
        if len(event_law.selection.rows) > 0:
            selected_law = law_counts.iloc[event_law.selection.rows[0]]['위반법령']
            st.markdown(f"#### 🚨 '{selected_law}' 실제 위반 상세 사례")
            
            detail_df = df_stats_filtered[df_stats_filtered['위반법령'] == selected_law][['업체명', '위반내용', '행정처분명', '처분확정일']].reset_index(drop=True)
            st.dataframe(detail_df, use_container_width=True, hide_index=True)
        else:
            st.info("👆 위 표에서 현장 점검의 기준을 세우고 싶은 위반법령 항목을 클릭해 보세요.")
