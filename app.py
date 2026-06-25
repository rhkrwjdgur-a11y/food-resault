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

st.title("🥛 식약처 행정처분 및 원산지 위반 통합 모니터링")

# 2. 식약처 행정처분 데이터 로드 (개별 업체 데이터)
def get_data_public():
    try:
        api_key = st.secrets["DATA_GO_KR_API_KEY"]
    except KeyError:
        return [], "Secrets에 'DATA_GO_KR_API_KEY'가 없습니다."
    
    url = "https://apis.data.go.kr/1471000/AdmmRsltFoodMnftPrcsService/getAdmmRsltFoodMnftPrcsBssh"
    params = {"ServiceKey": api_key, "type": "json", "numOfRows": "500", "pageNo": "1"}
    
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if 'body' in data and 'items' in data['body']:
                return data['body'].get('items', []), None
        return [], "식약처 데이터 서버 응답 오류"
    except Exception as e:
        return [], f"식약처 데이터 통신 에러: {e}"

# 3. 농관원 원산지 적발현황 데이터 로드 (통계 데이터)
def get_data_origin():
    try:
        api_key = st.secrets["MAFRA_API_KEY"]
    except KeyError:
        return [], "Secrets에 'MAFRA_API_KEY'가 등록되지 않았습니다."
    
    url = f"http://211.237.50.150:7080/openapi/{api_key}/json/Grid_20151027000000000243_1/1/5000"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            try:
                data = response.json()
                grid_key = 'Grid_20151027000000000243_1'
                if grid_key in data and 'row' in data[grid_key]:
                    return data[grid_key]['row'], None
                else:
                    return [], f"원산지 API 데이터 불일치: {str(data)[:150]}"
            except ValueError:
                return [], f"원산지 API 파싱 실패 (키 동기화 대기 중일 수 있습니다). 응답: {response.text[:100]}"
        else:
            return [], f"원산지 API 상태 코드 에러: {response.status_code}"
    except Exception as e:
        return [], f"원산지 API 통신 에러: {e}"

# 4. 데이터 수집 및 전처리
with st.spinner("식약처 및 원산지 데이터를 실시간으로 수집 중입니다..."):
    items_public, err_public = get_data_public()
    items_origin, err_origin = get_data_origin()

# 식약처 데이터 전처리
public_list = []
for item in items_public:
    public_list.append({
        '업체명': item.get('PRCSCITYPOINT_BSSHNM', '내용 없음'),
        '위반법령': item.get('LAWORD_CD_NM', '내용 없음'),
        '위반내용': item.get('VILTCN', '내용 없음'),
        '행정처분명': item.get('DSPSCN', '내용 없음'),
        '처분확정일': str(item.get('DSPS_DCSNDT', '내용 없음')),
        '소재지': item.get('ADDR', '내용 없음'),
        '출처': '식약처'
    })
df_public = pd.DataFrame(public_list)
if not df_public.empty:
    df_public = df_public.drop_duplicates(subset=['업체명', '처분확정일'], keep='first')
    df_public = df_public.sort_values(by='처분확정일', ascending=False).reset_index(drop=True)

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
    # 📌 팩트 지정 품목 필터링 키워드 셋업 (우유, 두유, 음료, 환자식, 가공유, 유제품류 일체)
    target_keywords = ['우유', '두유', '음료', '환자', '가공유', '발효유', '원유', '유가공', '요거트', '치즈', '주스', '즙', '유제품', '분유', '유조리']
    origin_pattern = '|'.join(target_keywords)
    
    # 해당 품목군만 정확하게 필터링
    df_origin_filtered = df_origin_raw[df_origin_raw['위반품목'].str.contains(origin_pattern, na=False, regex=True)].copy()
    
    if not df_origin_filtered.empty:
        # 연도 컬럼 생성 (YYYYMM -> YYYY)
        df_origin_filtered['연도'] = df_origin_filtered['처분년월'].str[:4]
        # 최신 연도 및 월 순으로 정렬
        df_origin = df_origin_filtered.sort_values(by='처분년월', ascending=False).reset_index(drop=True)

# 에러 메시지 알림
if err_public:
    st.warning(f"식약처 연동 중 알림: {err_public}")
if err_origin:
    st.error(f"원산지 연동 중 알림: {err_origin}")

# 전체 현황판 출력
st.markdown(f"""
<div class="info-box">
    <strong>💡 실시간 수집 현황</strong>: 식약처 행정처분 <strong>{len(df_public)}건</strong> / 취급 품목 지정 농관원 원산지 통계 <strong>{len(df_origin)}건</strong> 연동 완료
</div>
""", unsafe_allow_html=True)

# 5. 5개의 독립된 탭 구성 (통계 분석 탭 신설)
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔍 전체 업체 통합 검색", 
    "🥛 유가공·유제품 동향", 
    "📅 월별 신규 등록 내역", 
    "🌾 원산지 위반 통계",
    "📊 행정처분 통계 분석"
])

# ==========================================
# 탭 1: 전체 업체 통합 검색 (식약처)
# ==========================================
with tab1:
    st.subheader("🔍 특정 업체 행정처분 이력 검색")
    search_keyword = st.text_input("검색할 업체명을 입력하세요", key="search_input")
    
    if search_keyword:
        search_df = df_public[df_public['업체명'].str.contains(search_keyword, na=False)].reset_index(drop=True)
        
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
# 탭 2: 유가공·유제품 동향 (식약처)
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
    dairy_df = df_public[df_public['업체명'].str.contains(dairy_pattern, na=False, regex=True)].reset_index(drop=True)

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
# 탭 3: 월별 신규 등록 내역 (식약처)
# ==========================================
with tab3:
    st.subheader("📅 월별 행정처분 등록 리스트")
    
    available_months = set()
    for d in df_public['처분확정일']:
        date_val = str(d).replace('-', '')
        if len(date_val) >= 6 and date_val.isdigit():
            available_months.add(f"{date_val[:4]}.{date_val[4:6]}")
            
    month_list = sorted(list(available_months), reverse=True)
    
    if month_list:
        selected_month = st.selectbox("조회할 처분 월을 선택하세요", month_list)
        selected_year_month = selected_month.replace(".", "")
        
        month_df = df_public[df_public['처분확정일'].str.replace('-', '').str.startswith(selected_year_month, na=False)].reset_index(drop=True)
        
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
# 탭 4: 원산지 위반 통계 (농관원 - 지정 품목 및 연도별 그룹화)
# ==========================================
with tab4:
    st.subheader("🌾 지정 품목 원산지 표시 적발 현황")
    
    if df_origin.empty:
        st.info("해당 취급 품목군(우유/두유/음료/환자식/가공유)에 대입되는 원산지 위반 통계 데이터가 없습니다.")
    else:
        # 연도별 선택 박스 구성
        unique_years = sorted(list(df_origin['연도'].unique()), reverse=True)
        selected_year = st.selectbox("조회할 원산지 적발 연도를 선택하세요", unique_years, key="origin_year_select")
        
        # 선택된 연도 데이터 필터링
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
# 탭 5: 행정처분 통계 분석 (식약처 데이터 시각화 탭 - 신설)
# ==========================================
with tab5:
    st.subheader("📊 식약처 행정처분 통계 현황판")
    
    if df_public.empty:
        st.info("통계를 생성할 행정처분 기본 데이터가 존재하지 않습니다.")
    else:
        # 데이터프레임 복사 후 연도 가공
        df_stats = df_public.copy()
        df_stats['연도'] = df_stats['처분확정일'].str.replace('-', '').str[:4]
        df_stats['월'] = df_stats['처분확정일'].str.replace('-', '').str[4:6]
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 📅 연도별 행정처분 발생 추이")
            # 연도별 카운트 계산
            yearly_counts = df_stats.groupby('연도').size().reset_index(name='처분건수')
            yearly_counts = yearly_counts.sort_values(by='연도')
            
            # 차트 출력을 위해 인덱스 지정
            chart_data_year = yearly_counts.set_index('연도')
            st.bar_chart(chart_data_year, color="#e74c3c")
            st.dataframe(yearly_counts, use_container_width=True, hide_index=True)
            
        with col2:
            st.markdown("### ⚖️ 가장 많이 발생하는 위반 법령 TOP 10")
            # 위반법령별 카운트 계산
            law_counts = df_stats.groupby('위반법령').size().reset_index(name='적발건수')
            law_counts = law_counts.sort_values(by='적발건수', ascending=False).head(10).reset_index(drop=True)
            
            chart_data_law = law_counts.set_index('위반법령')
            st.bar_chart(chart_data_law, color="#2980b9")
            st.dataframe(law_counts, use_container_width=True, hide_index=True)
            
        st.markdown("---")
        st.markdown("### 📝 확정된 행정처분 유형 종류별 통계")
        
        # 실제 처분 내용 종류별 통계 리스트화
        disposal_counts = df_stats.groupby('행정처분명').size().reset_index(name='처분건수')
        disposal_counts = disposal_counts.sort_values(by='처분건수', ascending=False).reset_index(drop=True)
        
        st.dataframe(disposal_counts, use_container_width=True, hide_index=True)
