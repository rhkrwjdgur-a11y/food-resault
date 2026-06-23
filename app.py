import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import dateutil.relativedelta

# 1. 기본 페이지 설정
st.set_page_config(page_title="식약처 행정처분 결과", layout="wide")

# CSS를 이용해 디자인을 깔끔하게 잡습니다.
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 5px; background-color: #007bff; color: white; }
    .penalty-card { border: 1px solid #ddd; padding: 15px; border-radius: 10px; background-color: white; margin-bottom: 10px; }
    .info-box { background-color: #e9ecef; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🥛 연세유업 식약처 데이터 행정처분 결과")

# 2. 월 선택 UI 자동 생성 (오늘 날짜 기준 과거 12개월 리스트)
today = datetime.now()
month_list = []
for i in range(12):
    d = today - dateutil.relativedelta.relativedelta(months=i)
    month_list.append(d.strftime("%Y.%m"))

selected_month = st.selectbox("조회하고 싶은 달을 선택하세요", month_list)

# 3. 데이터 가져오기 함수 (서버 최대 허용치인 500으로 설정)
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

# 4. 화면 출력 및 필터링 로직
items, error_msg = get_data()

if error_msg:
    st.error(f"데이터 호출 오류 발생: {error_msg}")
elif not items:
    st.info("API 호출은 정상적이나, 식약처 서버에서 넘겨준 데이터가 0건입니다.")
else:
    # 팩트 체크: 현재 식약처에서 제공 중인 데이터가 어느 달에 분포해 있는지 추출합니다.
    available_months = set()
    for item in items:
        date_val = str(item.get('PUBLIC_DT', item.get('DSPS_DCSNDT', '')))
        if len(date_val) >= 6:
            formatted_month = f"{date_val[:4]}.{date_val[4:6]}"
            available_months.add(formatted_month)
            
    sorted_available_months = sorted(list(available_months), reverse=True)
    
    # 상단에 데이터 현황을 박스 형태로 알려줍니다.
    st.markdown(f"""
    <div class="info-box">
        <strong>💡 현재 식약처 서버 실시간 데이터 현황 (총 {len(items)}건)</strong><br>
        실제 행정처분 공표 데이터가 존재하는 달: {', '.join(sorted_available_months)}<br>
        <span style="color: #666; font-size: 12px;">※ 법적 공표 기간이 만료된 과거 데이터는 식약처 정책에 따라 서버에서 자동 삭제되어 조회되지 않습니다.</span>
    </div>
    """, unsafe_allow_html=True)

    # 선택된 달을 날짜 형식에 맞춰 변환 ("202606")
    selected_year_month = selected_month.replace(".", "")
    filtered_items = []
    
    for item in items:
        date_val = str(item.get('PUBLIC_DT', item.get('DSPS_DCSNDT', '')))
        
        if date_val.startswith(selected_year_month):
            filtered_items.append(item)

    if not filtered_items:
        st.info(f"식약처 데이터센터 기준 {selected_month}에 공표(등록)된 행정처분 데이터가 존재하지 않습니다.")
    else:
        df = pd.DataFrame(filtered_items)
        st.subheader(f"📊 {selected_month} 행정처분 신규 공표 리스트")
        
        company_names = list(set([item.get('PRCSCITYPOINT_BSSHNM', '알 수 없음') for item in filtered_items]))
        selected_company = st.selectbox("자세한 내용을 확인하려면 업체를 선택하세요", ["업체를 선택하세요"] + company_names)

        if selected_company != "업체를 선택하세요":
            detail = next((item for item in filtered_items if item.get('PRCSCITYPOINT_BSSHNM') == selected_company), None)
            
            if detail:
                st.markdown(f"""
                <div class="penalty-card">
                    <h3>🏢 업체명: {detail.get('PRCSCITYPOINT_BSSHNM', '내용 없음')}</h3>
                    <p><strong>⚠️ 위반법령:</strong> {detail.get('LAWORD_CD_NM', '내용 없음')}</p>
                    <p><strong>📝 위반내용:</strong> {detail.get('VILTCN', '내용 없음')}</p>
                    <p><strong>⚖️ 행정처분명:</strong> {detail.get('DSPSCN', '내용 없음')}</p>
                    <p><strong>📅 처분시작일:</strong> {detail.get('DSPS_BGNDT', '내용 없음')}</p>
                    <p><strong>📢 공표일자:</strong> {detail.get('PUBLIC_DT', '내용 없음')}</p>
                    <p><strong>📍 소재지:</strong> {detail.get('ADDR', '내용 없음')}</p>
                </div>
                """, unsafe_allow_html=True)
        
        with st.expander("전체 데이터 표 보기"):
            display_df = df[['PRCSCITYPOINT_BSSHNM', 'LAWORD_CD_NM', 'DSPSCN', 'PUBLIC_DT', 'DSPS_BGNDT']].rename(
                columns={
                    'PRCSCITYPOINT_BSSHNM': '업체명',
                    'LAWORD_CD_NM': '위반법령',
                    'DSPSCN': '행정처분명',
                    'PUBLIC_DT': '공표일자',
                    'DSPS_BGNDT': '처분시작일'
                }
            )
            st.dataframe(display_df)
