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

# 3. 데이터 가져오기 함수 및 서버 에러 내용 추출 로직
def get_data():
    try:
        api_key = st.secrets["DATA_GO_KR_API_KEY"]
    except KeyError:
        return None, "Streamlit Settings의 Secrets에 'DATA_GO_KR_API_KEY'가 입력되지 않았습니다."
    
    # 식약처 식품위생법 위반업체 행정처분 API 주소
    url = "http://apis.data.go.kr/1471000/FoodFlwOrdrInfoService/getFoodFlwOrdrItem"
    
    params = {
        "ServiceKey": api_key,
        "type": "json",  # JSON 요청
        "numOfRows": "100",
        "pageNo": "1"
    }
    
    try:
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            try:
                data = response.json()
                if 'response' in data and 'body' in data['response']:
                    items = data['response']['body'].get('items', [])
                    return items, None
                else:
                    return None, f"API 응답 데이터 형식이 맞지 않습니다. 원본 데이터: {data}"
            except Exception:
                return None, f"JSON 데이터 파싱 실패. 식약처 서버 응답: {response.text[:500]}"
        else:
            # 500 에러를 포함한 모든 통신 실패 시, 식약처 서버가 뱉어낸 에러 원본 텍스트를 함께 출력합니다.
            return None, f"상태 코드 {response.status_code}. 식약처 서버 원본 에러 내용: {response.text[:1000]}"
    except Exception as e:
        return None, f"서버 요청 중 시스템 에러 발생: {e}"

# 4. 화면 출력 및 월별 필터링 로직
items, error_msg = get_data()

if error_msg:
    # 에러 내용을 화면에 붉은색 박스로 출력
    st.error(f"데이터 호출 오류 발생: {error_msg}")
elif not items:
    st.info("API 호출은 정상적이나, 식약처 서버에서 넘겨준 데이터가 0건입니다.")
else:
    selected_year_month = selected_month.replace(".", "")
    filtered_items = []
    date_column_name = ""
    
    sample_item = items[0]
    if 'ADMDSP_DT' in sample_item:
        date_column_name = 'ADMDSP_DT'
    elif 'EXAATHR_PD' in sample_item:
        date_column_name = 'EXAATHR_PD'
    elif 'DISPOS_DATE' in sample_item:
        date_column_name = 'DISPOS_DATE'

    if date_column_name:
        for item in items:
            date_val = str(item.get(date_column_name, ""))
            if date_val.startswith(selected_year_month):
                filtered_items.append(item)
    else:
        filtered_items = items
        st.warning("응답 데이터에 날짜 컬럼이 존재하지 않아 해당 호출의 전체 데이터를 표시합니다.")

    if not filtered_items:
        st.info(f"{selected_month}에 해당하는 행정처분 데이터가 없습니다.")
    else:
        df = pd.DataFrame(filtered_items)
        st.subheader(f"📊 {selected_month} 행정처분 업체 리스트")
        
        company_names = list(set([item.get('ENTP_NAME', item.get('BSSH_NM', '알 수 없음')) for item in filtered_items]))
        selected_company = st.selectbox("상세 정보를 보려면 업체를 선택하세요", ["업체를 선택하세요"] + company_names)

        if selected_company != "업체를 선택하세요":
            detail = next((item for item in filtered_items if item.get('ENTP_NAME', item.get('BSSH_NM')) == selected_company), None)
            
            if detail:
                st.markdown(f"""
                <div class="penalty-card">
                    <h3>🏢 업체명: {detail.get('ENTP_NAME', detail.get('BSSH_NM', '내용 없음'))}</h3>
                    <p><strong>⚠️ 위반법령:</strong> {detail.get('VIOLT_NM', detail.get('LGL_CD_NM', '내용 없음'))}</p>
                    <p><strong>📝 위반내용:</strong> {detail.get('VIOLT_CN', detail.get('VIOLT_CN', '내용 없음'))}</p>
                    <p><strong>⚖️ 행정처분명:</strong> {detail.get('EXAATHR_NM', detail.get('ADMDSP_NM', '내용 없음'))}</p>
                    <p><strong>📅 처분일자:</strong> {detail.get('EXAATHR_PD', detail.get('ADMDSP_DT', '내용 없음'))}</p>
                </div>
                """, unsafe_allow_html=True)
        
        with st.expander("전체 데이터 표 보기"):
            st.dataframe(df)
