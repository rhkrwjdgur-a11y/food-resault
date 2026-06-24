import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import dateutil.relativedelta

# 1. 기본 페이지 설정
st.set_page_config(page_title="식약처 통합 행정처분 모니터링", layout="wide")

# CSS 디자인
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .penalty-card { border: 1px solid #ddd; padding: 15px; border-radius: 10px; background-color: white; margin-top: 20px; margin-bottom: 20px; border-left: 5px solid #e74c3c; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    .info-box { background-color: #e9ecef; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; }
    .dairy-box { background-color: #e3f2fd; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; border: 1px solid #90caf9;}
    .guide-text { color: #2980b9; font-weight: bold; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🥛 식약처 일반식품 및 축산물 통합 모니터링")

# 2. 데이터 가져오기 함수 1 (공공데이터포털 - 기존 일반식품)
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
        return [], "공공데이터포털 응답 오류"
    except Exception as e:
        return [], f"공공데이터포털 통신 에러: {e}"

# 3. 데이터 가져오기 함수 2 (식품안전나라 - 축산물 포함)
def get_data_foodsafety():
    try:
        api_key = st.secrets.get("FOOD_SAFETY_API_KEY", "")
        if not api_key:
            return [], "식품안전나라 키가 아직 입력되지 않았습니다. (입력 전까지는 기존 데이터만 나옵니다)"
    except KeyError:
        return [], "Secrets에 'FOOD_SAFETY_API_KEY'가 없습니다."
    
    # 식품안전나라 API 주소 구조 (서비스ID(예: I1250)는 명세서 확인 후 교체 필요)
    service_id = "I1250" # 예시 ID
    url = f"http://openapi.foodsafetykorea.go.kr/api/{api_key}/{service_id}/json/1/500"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # 식품안전나라 JSON 구조 반영 (서비스ID로 키가 들어옴)
            if service_id in data and 'row' in data[service_id]:
                return data[service_id]['row'], None
        return [], "식품안전나라 응답 오류"
    except Exception as e:
        return [], f"식품안전나라 통신 에러: {e}"

# 4. 데이터 로드 및 두 데이터 병합
with st.spinner("양쪽 서버(일반식품 + 축산물)에서 실시간 데이터를 불러오는 중입니다..."):
    items_public, err_public = get_data_public()
    items_food, err_food = get_data_foodsafety()

# 두 API의 데이터 항목명이 다를 수 있으므로, 우리 시스템에 맞게 이름을 통일(정규화)합니다.
combined_items = []

# 공공데이터포털 데이터 추가
for item in items_public:
    combined_items.append({
        '업체명': item.get('PRCSCITYPOINT_BSSHNM', '내용 없음'),
        '위반법령': item.get('LAWORD_CD_NM', '내용 없음'),
        '위반내용': item.get('VILTCN', '내용 없음'),
        '행정처분명': item.get('DSPSCN', '내용 없음'),
        '처분확정일': item.get('DSPS_DCSNDT', '내용 없음'),
        '처분시작일': item.get('DSPS_BGNDT', '내용 없음'),
        '공표만료일': item.get('PUBLIC_DT', '내용 없음'),
        '소재지': item.get('ADDR', '내용 없음'),
        '출처': '공공데이터포털(일반식품)'
    })

# 식품안전나라 데이터 추가 (항목명은 실제 API 명세서에 맞춰 수정 필요)
for item in items_food:
    combined_items.append({
        '업체명': item.get('BSSH_NM', item.get('ENTP_NM', '내용 없음')), 
        '위반법령': item.get('VIOLT_NM', '내용 없음'),
        '위반내용': item.get('VIOLT_CN', '내용 없음'),
        '행정처분명': item.get('DISPOS_CN', item.get('DISPOS_NM', '내용 없음')),
        '처분확정일': item.get('DISPOS_DT', '내용 없음'),
        '처분시작일': item.get('DISPOS_BGNDT', '-'),
        '공표만료일': item.get('PUBLIC_DT', '-'),
        '소재지': item.get('ADDR', '내용 없음'),
        '출처': '식품안전나라(축산물/통합)'
    })

# 에러 메시지 알림 (둘 중 하나라도 실패하면 알림, 하나만 성공해도 화면은 뜸)
if err_public and err_public != "Secrets에 'DATA_GO_KR_API_KEY'가 없습니다.":
    st.warning(f"일반식품 연동 중 알림: {err_public}")
if err_food and err_food != "식품안전나라 키가 아직 입력되지 않았습니다. (입력 전까지는 기존 데이터만 나옵니다)":
    st.warning(f"축산물 연동 중 알림: {err_food}")

if not combined_items:
    st.info("현재 양쪽 서버에서 가져올 수 있는 데이터가 0건입니다.")
else:
    df_all = pd.DataFrame(combined_items)

    st.markdown(f"""
    <div class="info-box">
        <strong>💡 실시간 데이터 통합 수집 현황</strong>: 일반 식품 및 축산물 행정처분 총 <strong>{len(combined_items)}건</strong> 연동 완료<br>
        <span style="color: #666; font-size: 12px;">※ 공표만료일이 지나 삭제된 데이터는 조회되지 않습니다. (데이터 출처: 공공데이터포털 + 식품안전나라)</span>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["🔍 전체 업체 통합 검색", "🥛 유가공·유제품 동향", "📅 월별 신규 등록 내역"])

    # ==========================================
    # 탭 1: 전체 업체 통합 검색
    # ==========================================
    with tab1:
        st.subheader("🔍 특정 업체 행정처분 이력 검색")
        search_keyword = st.text_input("검색할 업체명을 입력하세요 (예: 매일, 남양, 삼성 등)", key="search_input")
        
        if search_keyword:
            search_df = df_all[df_all['업체명'].str.contains(search_keyword, na=False)].reset_index(drop=True)
            
            if search_df.empty:
                st.success(f"'{search_keyword}'(으)로 검색된 내역이 없습니다. (클린 사업장)")
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
                        <p><strong>📅 처분확정일:</strong> {detail['처분확정일']} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>📢 공표만료일:</strong> {detail['공표만료일']}</p>
                        <p><strong>📍 소재지:</strong> {detail['소재지']}</p>
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
            ✔️ <strong>적용된 필터링 키워드:</strong> {', '.join(dairy_keywords)}
        </div>
        """, unsafe_allow_html=True)

        dairy_pattern = '|'.join(dairy_keywords)
        dairy_df = df_all[df_all['업체명'].str.contains(dairy_pattern, na=False, regex=True)].reset_index(drop=True)

        if dairy_df.empty:
            st.info("현재 공표된 행정처분 내역 중 유가공/유제품 관련 업체의 적발 건은 없습니다.")
        else:
            st.error(f"동종업계 행정처분 총 {len(dairy_df)}건이 조회되었습니다.")
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
                    <p><strong>📅 처분확정일:</strong> {detail['처분확정일']} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>📢 공표만료일:</strong> {detail['공표만료일']}</p>
                    <p><strong>📍 소재지:</strong> {detail['소재지']}</p>
                </div>
                """, unsafe_allow_html=True)

    # ==========================================
    # 탭 3: 월별 신규 등록 내역
    # ==========================================
    with tab3:
        st.subheader("📅 월별 행정처분 등록 리스트")
        
        available_months = set()
        for d in df_all['처분확정일']:
            date_val = str(d).replace('-', '')
            if len(date_val) >= 6 and date_val.isdigit():
                available_months.add(f"{date_val[:4]}.{date_val[4:6]}")
                
        month_list = sorted(list(available_months), reverse=True)
        
        if month_list:
            selected_month = st.selectbox("조회할 처분 확정 월을 선택하세요", month_list)
            selected_year_month = selected_month.replace(".", "")
            
            month_df = df_all[df_all['처분확정일'].str.replace('-', '').str.startswith(selected_year_month, na=False)].reset_index(drop=True)
            
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
                        <p><strong>📅 처분확정일:</strong> {detail['처분확정일']} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>📢 공표만료일:</strong> {detail['공표만료일']}</p>
                        <p><strong>📍 소재지:</strong> {detail['소재지']}</p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("표시할 수 있는 월별 데이터가 없습니다.")
