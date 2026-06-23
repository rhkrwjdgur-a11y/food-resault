import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import dateutil.relativedelta

# 1. 기본 페이지 설정
st.set_page_config(page_title="식약처 행정처분 결과", layout="wide")

# CSS를 이용해 디자인을 조금 더 깔끔하게 잡습니다.
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stButton>button { width: 100%; border-radius: 5px; background-color: #007bff; color: white; }
    .penalty-card { border: 1px solid #ddd; padding: 15px; border-radius: 10px; background-color: white; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🥛 연세유업 식약처 데이터 행정처분 결과")

# 2. 월 선택 UI 자동 생성 (현재 날짜 기준 과거 12개월 리스트)
# 달이 바뀌면 자동으로 새로운 달이 리스트에 추가됩니다.
today = datetime.now()
month_list = []
for i in range(12):
    d = today - dateutil.relativedelta.relativedelta(months=i)
    month_list.append(d.strftime("%Y.%m"))

selected_month = st.selectbox("조회하고 싶은 달을 선택하세요", month_list)

# 3. 데이터 가져오기 함수 (Secrets 사용)
def get_data(month_str):
    # Streamlit Secrets에서 키를 가져옵니다.
    api_key = st.secrets["DATA_GO_KR_API_KEY"]
    
    # 식약처 의약품/식품 행정처분 API 주소 (필요에 따라 엔드포인트 수정 가능)
    url = "http://apis.data.go.kr/1471000/MdcinExaathrService04/getMdcinExaathrList04"
    
    # API 요청 (해당 월의 데이터를 필터링하기 위해 보통 전체를 가져온 후 파이썬으로 거릅니다)
    params = {
        "ServiceKey": api_key,
        "type": "json",
        "numOfRows": "100",
        "pageNo": "1"
    }
    
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            items = data.get('response', {}).get('body', {}).get('items', [])
            return items
        return []
    except:
        return []

# 4. 화면 출력 로직
items = get_data(selected_month)

if not items:
    st.info(f"{selected_month}에 해당하는 행정처분 데이터가 없습니다.")
else:
    # 데이터를 보기 좋게 표로 정리
    df = pd.DataFrame(items)
    
    # 실제 데이터의 '처분일자' 컬럼명이 API마다 다를 수 있으니 확인이 필요합니다 (예: PRN_DT 또는 DISPOS_DATE)
    # 여기서는 예시로 전체 리스트를 보여주고 클릭 시 상세 정보를 보여주는 방식을 구현합니다.
    
    st.subheader(f"📊 {selected_month} 행정처분 업체 리스트")
    
    # 표에서 업체명만 추출해서 선택 박스 만들기
    company_names = [item.get('ENTP_NAME', '알 수 없음') for item in items]
    selected_company = st.selectbox("상세 정보를 보려면 업체를 선택하세요", ["업체를 선택하세요"] + company_names)

    if selected_company != "업체를 선택하세요":
        # 선택한 업체의 데이터만 찾기
        detail = next((item for item in items if item.get('ENTP_NAME') == selected_company), None)
        
        if detail:
            st.markdown(f"""
            <div class="penalty-card">
                <h3>🏢 업체명: {detail.get('ENTP_NAME')}</h3>
                <p><strong>⚠️ 위반법령:</strong> {detail.get('VIOLT_NM', '내용 없음')}</p>
                <p><strong>📝 위반내용:</strong> {detail.get('VIOLT_CN', '내용 없음')}</p>
                <p><strong>⚖️ 행정처분명:</strong> {detail.get('EXAATHR_NM', '내용 없음')}</p>
                <p><strong>📅 처분기간:</strong> {detail.get('EXAATHR_PD', '내용 없음')}</p>
                <p><strong>📌 기타참조:</strong> {detail.get('REMARK', '-')}</p>
            </div>
            """, unsafe_allow_html=True)
    
    # 전체 표도 아래에 참고용으로 표시
    with st.expander("전체 데이터 표 보기"):
        st.table(df[['ENTP_NAME', 'VIOLT_NM', 'EXAATHR_NM']])
