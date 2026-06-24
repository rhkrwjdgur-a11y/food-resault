import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import dateutil.relativedelta

# 1. 기본 페이지 설정
st.set_page_config(page_title="식품안전 및 원산지 위반 통합 모니터링", layout="wide")

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

st.title("🥛 식약처 행정처분 및 원산지 위반 통합 모니터링")

# 2. 데이터 가져오기 함수 1 (식약처 - 기존 식품제조가공업)
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

# 3. 데이터 가져오기 함수 2 (농축산물 원산지 표시 적발현황)
def get_data_origin():
    try:
        # 우선 기존에 발급받은 공공데이터포털 키를 사용합니다.
        api_key = st.secrets["DATA_GO_KR_API_KEY"]
    except KeyError:
        return [], "Secrets에 'DATA_GO_KR_API_KEY'가 없습니다."
    
    # 캡처해주신 명세서의 샘플 URL 구조를 기반으로 동적 URL을 생성합니다.
    # xml 대신 json 포맷으로, 5건(1/5) 대신 500건(1/500)을 요청하도록 최적화했습니다.
    url = f"http://211.237.50.150:7080/openapi/{api_key}/json/Grid_20151027000000000243_1/1/500"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            try:
                data = response.json()
                grid_key = 'Grid_20151027000000000243_1'
                if grid_key in data and 'row' in data[grid_key]:
                    return data[grid_key]['row'], None
                else:
                    return [], f"원산지 API 데이터 형식 불일치. 서버 원본 응답: {str(data)[:150]}"
            except ValueError:
                error_text = response.text[:200].replace('\n', ' ')
                return [], f"원산지 API JSON 파싱 실패 (키 오류 가능성). 서버 응답: {error_text}"
        else:
            return [], f"원산지 API 상태 코드 에러: {response.status_code}"
    except Exception as e:
        return [], f"원산지 API 통신 에러: {e}"

# 4. 데이터 로드 및 두 데이터 병합
with st.spinner("식약처 및 원산지 적발 실시간 데이터를 불러오는 중입니다..."):
    items_public, err_public = get_data_public()
    items_origin, err_origin = get_data_origin()

combined_items = []

# 식약처 데이터 추가
for item in items_public:
    combined_items.append({
        '업체명': item.get('PRCSCITYPOINT_BSSHNM', '내용 없음'),
        '위반법령': item.get('LAWORD_CD_NM', '내용 없음'),
        '위반내용': item.get('VILTCN', '내용 없음'),
        '행정처분명': item.get('DSPSCN', '내용 없음'),
        '처분확정일': str(item.get('DSPS_DCSNDT', '내용 없음')),
        '처분시작일': str(item.get('DSPS_BGNDT', '내용 없음')),
        '공표만료일': str(item.get('PUBLIC_DT', '내용 없음')),
        '소재지': item.get('ADDR', '내용 없음'),
        '출처': '식약처(행정처분)'
    })

# 원산지 적발 데이터 추가 
for item in items_origin:
    combined_items.append({
        # 🚨 주의: 명세서의 '출력결과' 탭을 확인하신 후, 아래 '영문키_수정필요' 부분을 실제 영문 항목명으로 꼭 수정해 주십시오.
        '업체명': item.get('업체명_영문키_수정필요', '업체명 확인불가 (명세서 키 변경 필요)'), 
        '위반법령': item.get('품목명_영문키_수정필요', '농축산물 원산지 표시 위반'),
        '위반내용': item.get('위반내용_영문키_수정필요', '원산지 거짓표시 또는 미표시'),
        '행정처분명': item.get('처분명_영문키_수정필요', '적발 및 조치'),
        '처분확정일': str(item.get('적발일자_영문키_수정필요', '내용 없음')),
        '처분시작일': '-',
        '공표만료일': '-',
        '소재지': item.get('주소_영문키_수정필요', '내용 없음'),
        '출처': '농관원(원산지 위반)'
    })

# 에러 메시지 알림
if err_public:
    st.warning(f"식약처 연동 중 알림: {err_public}")
if err_origin:
    st.error(f"원산지 연동 중 알림: {err_origin}")

if not combined_items:
    st.info("현재 수집할 수 있는 유효한 데이터가 0건입니다.")
else:
    df_raw = pd.DataFrame(combined_items)
    
    # 업체명과 처분확정일이 일치하는 중복 데이터 제거
    df_all = df_raw.drop_duplicates(subset=['업체명', '처분확정일'], keep='first').reset_index(drop=True)

    st.markdown(f"""
    <div class="info-box">
        <strong>💡 실시간 데이터 통합 수집 현황</strong>: 행정처분 및 원산지 적발 내역 총 <strong>{len(df_all)}건</strong> 연동 완료<br>
        <span style="color: #666; font-size: 12px;">※ 공표만료일이 지나 삭제된 과거 데이터는 조회되지 않습니다.</span>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["🔍 전체 업체 통합 검색", "🥛 유가공·유제품 동향", "📅 월별 신규 등록 내역"])

    # ==========================================
    # 탭 1: 전체 업체 통합 검색
    # ==========================================
    with tab1:
        st.subheader("🔍 특정 업체 위반 이력 통합 검색")
        search_keyword = st.text_input("검색할 업체명을 입력하세요", key="search_input")
        
        if search_keyword:
            search_df = df_all[df_all['업체명'].str.contains(search_keyword, na=False)].reset_index(drop=True)
            
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
                        <p><strong>⚠️ 위반법령/품목:</strong> {detail['위반법령']}</p>
                        <p><strong>📝 위반/적발내용:</strong> {detail['위반내용']}</p>
                        <p><strong>⚖️ 행정처분명:</strong> {detail['행정처분명']}</p>
                        <p><strong>📅 처분/적발확정일:</strong> {detail['처분확정일']} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>📢 공표만료일:</strong> {detail['공표만료일']}</p>
                        <p><strong>📍 소재지:</strong> {detail['소재지']}</p>
                    </div>
                    """, unsafe_allow_html=True)

    # ==========================================
    # 탭 2: 유가공·유제품 동향 필터링
    # ==========================================
    with tab2:
        st.subheader("🥛 동종업계(유제품/유가공) 위반 모아보기")
        dairy_keywords = ['유업', '우유', '치즈', '요거트', '목장', '유가공', '밀크', '다논', '푸르밀', '매일', '남양', '서울우유', '빙그레', '연세', '파스퇴르']
        
        st.markdown(f"""
        <div class="dairy-box">
            ✔️ <strong>적용된 필터링 키워드:</strong> {', '.join(dairy_keywords)}
        </div>
        """, unsafe_allow_html=True)

        dairy_pattern = '|'.join(dairy_keywords)
        dairy_df = df_all[df_all['업체명'].str.contains(dairy_pattern, na=False, regex=True)].reset_index(drop=True)

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
                    <p><strong>⚠️ 위반법령/품목:</strong> {detail['위반법령']}</p>
                    <p><strong>📝 위반/적발내용:</strong> {detail['위반내용']}</p>
                    <p><strong>⚖️ 행정처분명:</strong> {detail['행정처분명']}</p>
                    <p><strong>📅 처분/적발확정일:</strong> {detail['처분확정일']} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>📢 공표만료일:</strong> {detail['공표만료일']}</p>
                    <p><strong>📍 소재지:</strong> {detail['소재지']}</p>
                </div>
                """, unsafe_allow_html=True)

    # ==========================================
    # 탭 3: 월별 신규 등록 내역
    # ==========================================
    with tab3:
        st.subheader("📅 월별 위반/적발 등록 리스트")
        
        available_months = set()
        for d in df_all['처분확정일']:
            date_val = str(d).replace('-', '')
            if len(date_val) >= 6 and date_val.isdigit():
                available_months.add(f"{date_val[:4]}.{date_val[4:6]}")
                
        month_list = sorted(list(available_months), reverse=True)
        
        if month_list:
            selected_month = st.selectbox("조회할 처분/적발 월을 선택하세요", month_list)
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
                        <p><strong>⚠️ 위반법령/품목:</strong> {detail['위반법령']}</p>
                        <p><strong>📝 위반/적발내용:</strong> {detail['위반내용']}</p>
                        <p><strong>⚖️ 행정처분명:</strong> {detail['행정처분명']}</p>
                        <p><strong>📅 처분/적발확정일:</strong> {detail['처분확정일']} &nbsp;&nbsp;|&nbsp;&nbsp; <strong>📢 공표만료일:</strong> {detail['공표만료일']}</p>
                        <p><strong>📍 소재지:</strong> {detail['소재지']}</p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("표시할 수 있는 월별 데이터가 없습니다.")
