import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import dateutil.relativedelta

# 1. 기본 페이지 설정
st.set_page_config(page_title="식약처 행정처분 모니터링", layout="wide")

# CSS를 이용해 디자인을 깔끔하게 잡습니다.
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .penalty-card { border: 1px solid #ddd; padding: 15px; border-radius: 10px; background-color: white; margin-top: 20px; margin-bottom: 20px; border-left: 5px solid #e74c3c; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    .info-box { background-color: #e9ecef; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; }
    .dairy-box { background-color: #e3f2fd; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; border: 1px solid #90caf9;}
    .guide-text { color: #2980b9; font-weight: bold; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🥛 식약처 행정처분 실시간 모니터링")

# 2. 데이터 가져오기 함수 
def get_data():
    try:
        api_key = st.secrets["DATA_GO_KR_API_KEY"]
    except KeyError:
        return None, "Streamlit Settings의 Secrets에 'DATA_GO_KR_API_KEY'가 입력되지 않았습니다."
    
    url = "https://apis.data.go.kr/1471000/AdmmRsltFoodMnftPrcsService/getAdmmRsltFoodMnftPrcsBssh"
    
    params = {
        "ServiceKey": api_key,
        "type": "json",  
        "numOfRows": "500",  
        "pageNo": "1"
    }
    
    try:
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            try:
                data = response.json()
                if 'body' in data and 'items' in data['body']:
                    items = data['body'].get('items', [])
                    return items, None
                else:
                    return None, f"API 응답 데이터 형식이 맞지 않습니다. 원본 데이터: {data}"
            except Exception:
                return None, f"JSON 데이터 파싱 실패. 식약처 서버 응답: {response.text[:500]}"
        else:
            return None, f"상태 코드 {response.status_code}. 식약처 서버 원본 에러 내용: {response.text[:1000]}"
    except Exception as e:
        return None, f"서버 요청 중 시스템 에러 발생: {e}"

# 3. 데이터 로드
with st.spinner("식약처 실시간 데이터를 불러오는 중입니다..."):
    items, error_msg = get_data()

if error_msg:
    st.error(f"데이터 호출 오류 발생: {error_msg}")
elif not items:
    st.info("API 호출은 정상적이나, 식약처 서버에서 넘겨준 데이터가 0건입니다.")
else:
    # 전체 데이터를 판다스 데이터프레임으로 변환
    df_all = pd.DataFrame(items)

    st.markdown(f"""
    <div class="info-box">
        <strong>💡 실시간 데이터 수집 현황</strong>: 현재 공표 중인 전체 행정처분 <strong>{len(items)}건</strong> 연동 완료
    </div>
    """, unsafe_allow_html=True)

    # UI: 3개의 탭 구성
    tab1, tab2, tab3 = st.tabs(["🔍 전체 업체 통합 검색", "🥛 유가공·유제품 동향", "📅 월별 신규 등록 내역"])

    # ==========================================
    # 탭 1: 전체 업체 통합 검색
    # ==========================================
    with tab1:
        st.subheader("🔍 특정 업체 행정처분 이력 검색")
        search_keyword = st.text_input("검색할 업체명을 입력하세요 (예: 삼성, 농업회사법인 등)", key="search_input")
        
        if search_keyword:
            # 검색어가 포함된 데이터를 찾고, 클릭 시 매칭을 위해 인덱스를 초기화합니다.
            search_df = df_all[df_all['PRCSCITYPOINT_BSSHNM'].str.contains(search_keyword, na=False)].reset_index(drop=True)
            
            if search_df.empty:
                st.success(f"'{search_keyword}'(으)로 검색된 행정처분 내역이 없습니다. (클린 사업장)")
            else:
                st.warning(f"총 {len(search_df)}건의 행정처분 내역이 발견되었습니다.")
                
                search_display = search_df[['PRCSCITYPOINT_BSSHNM', 'LAWORD_CD_NM', 'DSPSCN', 'DSPS_DCSNDT', 'PUBLIC_DT']].copy()
                search_display.columns = ['업체명', '위반법령', '행정처분명', '처분확정일', '공표만료일']
                
                st.markdown('<p class="guide-text">👇 표에서 원하는 업체를 클릭하면 상세 정보가 나타납니다.</p>', unsafe_allow_html=True)
                
                # 표를 클릭 가능하도록 on_select 옵션을 적용합니다.
                event_search = st.dataframe(
                    search_display, 
                    use_container_width=True, 
                    on_select="rerun", 
                    selection_mode="single-row"
                )
                
                # 표에서 특정 행이 클릭되었을 때의 처리
                if len(event_search.selection.rows) > 0:
                    selected_idx = event_search.selection.rows[0]
                    detail = search_df.iloc[selected_idx]
                    
                    st.markdown(f"""
                    <div class="penalty-card">
                        <h3>🏢 {detail.get('PRCSCITYPOINT_BSSHNM', '내용 없음')}</h3>
                        <p><strong>⚠️ 위반법령:</strong> {detail.get('LAWORD_CD_NM', '내용 없음')}</p>
                        <p><strong>📝 위반내용:</strong> {detail.get('VILTCN', '내용 없음')}</p>
                        <p><strong>⚖️ 행정처분명:</strong> {detail.get('DSPSCN', '내용 없음')}</p>
                        <p><strong>📅 처분확정일:</strong> {detail.get('DSPS_DCSNDT', '내용 없음')} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>📅 처분시작일:</strong> {detail.get('DSPS_BGNDT', '내용 없음')}</p>
                        <p><strong>📍 소재지:</strong> {detail.get('ADDR', '내용 없음')}</p>
                    </div>
                    """, unsafe_allow_html=True)

    # ==========================================
    # 탭 2: 유가공·유제품 동향 필터링
    # ==========================================
    with tab2:
        st.subheader("🥛 동종업계(유제품/유가공) 행정처분 모아보기")
        
        dairy_keywords = ['유업', '우유', '치즈', '요거트', '목장', '유가공', '밀크', '다논', '푸르밀', '매일', '남양', '서울우유', '빙그레', '연세', '파스퇴르']
        
        st.markdown(f"""
        <div class="dairy-box">
            ✔️ <strong>적용된 필터링 키워드:</strong> {', '.join(dairy_keywords)}<br>
            위 단어가 이름에 포함된 업체의 위반 사례만 자동으로 모아서 보여줍니다. 타사의 위반 사유(VILTCN)를 분석하여 자사 품질 관리에 참고하십시오.
        </div>
        """, unsafe_allow_html=True)

        dairy_pattern = '|'.join(dairy_keywords)
        dairy_df = df_all[df_all['PRCSCITYPOINT_BSSHNM'].str.contains(dairy_pattern, na=False, regex=True)].reset_index(drop=True)

        if dairy_df.empty:
            st.info("현재 공표된 행정처분 내역 중 유가공/유제품 관련 업체의 적발 건은 없습니다.")
        else:
            st.error(f"동종업계 행정처분 총 {len(dairy_df)}건이 조회되었습니다.")
            
            dairy_display = dairy_df[['PRCSCITYPOINT_BSSHNM', 'LAWORD_CD_NM', 'DSPSCN', 'DSPS_DCSNDT']].copy()
            dairy_display.columns = ['업체명', '위반법령', '행정처분명', '처분확정일']
            
            st.markdown('<p class="guide-text">👇 표에서 원하는 업체를 클릭하면 상세 정보가 나타납니다.</p>', unsafe_allow_html=True)
            
            event_dairy = st.dataframe(
                dairy_display, 
                use_container_width=True, 
                on_select="rerun", 
                selection_mode="single-row"
            )
            
            if len(event_dairy.selection.rows) > 0:
                selected_idx = event_dairy.selection.rows[0]
                detail = dairy_df.iloc[selected_idx]
                
                st.markdown(f"""
                <div class="penalty-card">
                    <h3>🏢 {detail.get('PRCSCITYPOINT_BSSHNM', '내용 없음')}</h3>
                    <p><strong>⚠️ 위반법령:</strong> {detail.get('LAWORD_CD_NM', '내용 없음')}</p>
                    <p><strong>📝 위반내용:</strong> {detail.get('VILTCN', '내용 없음')}</p>
                    <p><strong>⚖️ 행정처분명:</strong> {detail.get('DSPSCN', '내용 없음')}</p>
                    <p><strong>📅 처분확정일:</strong> {detail.get('DSPS_DCSNDT', '내용 없음')} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>📅 처분시작일:</strong> {detail.get('DSPS_BGNDT', '내용 없음')}</p>
                    <p><strong>📍 소재지:</strong> {detail.get('ADDR', '내용 없음')}</p>
                </div>
                """, unsafe_allow_html=True)

    # ==========================================
    # 탭 3: 월별 신규 등록 내역
    # ==========================================
    with tab3:
        st.subheader("📅 월별 행정처분 등록 리스트")
        
        available_months = set()
        for item in items:
            date_val = str(item.get('DSPS_DCSNDT', ''))
            if len(date_val) >= 6:
                formatted_month = f"{date_val[:4]}.{date_val[4:6]}"
                available_months.add(formatted_month)
                
        month_list = sorted(list(available_months), reverse=True)
        
        if month_list:
            selected_month = st.selectbox("조회할 처분 확정 월을 선택하세요", month_list)
            selected_year_month = selected_month.replace(".", "")
            
            # 선택된 달의 데이터만 필터링 후 인덱스 재정렬
            month_items = [item for item in items if str(item.get('DSPS_DCSNDT', '')).startswith(selected_year_month)]
            month_df = pd.DataFrame(month_items).reset_index(drop=True)
            
            if not month_df.empty:
                month_display = month_df[['PRCSCITYPOINT_BSSHNM', 'LAWORD_CD_NM', 'DSPSCN', 'DSPS_DCSNDT']].copy()
                month_display.columns = ['업체명', '위반법령', '행정처분명', '처분확정일']
                
                st.markdown('<p class="guide-text">👇 표에서 원하는 업체를 클릭하면 상세 정보가 나타납니다.</p>', unsafe_allow_html=True)
                
                event_month = st.dataframe(
                    month_display, 
                    use_container_width=True, 
                    on_select="rerun", 
                    selection_mode="single-row"
                )
                
                if len(event_month.selection.rows) > 0:
                    selected_idx = event_month.selection.rows[0]
                    detail = month_df.iloc[selected_idx]
                    
                    st.markdown(f"""
                    <div class="penalty-card">
                        <h3>🏢 {detail.get('PRCSCITYPOINT_BSSHNM', '내용 없음')}</h3>
                        <p><strong>⚠️ 위반법령:</strong> {detail.get('LAWORD_CD_NM', '내용 없음')}</p>
                        <p><strong>📝 위반내용:</strong> {detail.get('VILTCN', '내용 없음')}</p>
                        <p><strong>⚖️ 행정처분명:</strong> {detail.get('DSPSCN', '내용 없음')}</p>
                        <p><strong>📅 처분확정일:</strong> {detail.get('DSPS_DCSNDT', '내용 없음')} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>📅 처분시작일:</strong> {detail.get('DSPS_BGNDT', '내용 없음')}</p>
                        <p><strong>📍 소재지:</strong> {detail.get('ADDR', '내용 없음')}</p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("표시할 수 있는 월별 데이터가 없습니다.")
