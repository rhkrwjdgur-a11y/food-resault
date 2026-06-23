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

# 3. 데이터 가져오기 함수 (식품제조가공업 전용 API로 수정)
def get_data():
    try:
        api_key = st.secrets["DATA_GO_KR_API_KEY"]
    except KeyError:
        return None, "Streamlit Settings의 Secrets에 'DATA_GO_KR_API_KEY'가 입력되지 않았습니다."
    
    # 사진에 올려주신 End Point + 세부 호출 오퍼레이션 명칭 결합
    url = "https://apis.data.go.kr/1471000/AdmmRsltFoodMnftPrcsService/getAdmmRsltFoodMnftPrcsBssh"
    
    params = {
        "ServiceKey": api_key,
        "type": "json",  # 데이터포맷 JSON 요청
        "numOfRows": "100",
        "pageNo": "1"
    }
    
    try:
        # 인증키 보안 이슈를 방지하기 위해 verify=False 옵션을 넣거나 http를 사용하기도 하지만, 
        # 공공데이터포털 권장에 따라 기본 https 요청을 진행합니다.
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
            return None, f"상태 코드 {response.status_code}. 식약처 서버 원본 에러 내용: {response.text[:1000]}"
    except Exception as e:
        return None, f"서버 요청 중 시스템 에러 발생: {e}"

# 4. 화면 출력 및 월별 필터링 로직
items, error_msg = get_data()

if error_msg:
    st.error(f"데이터 호출 오류 발생: {error_msg}")
elif not items:
    st.info("API 호출은 정상적이나, 식약처 서버에서 넘겨준 데이터가 0건입니다.")
else:
    # 선택된 달(예: "2026.06")을 날짜 형식에 맞춰 변환 ("202606")
    selected_year_month = selected_month.replace(".", "")
    filtered_items = []
    
    # 식품제조가공업 API의 처분일자 컬럼명은 주로 'ADMDSP_DT'를 사용합니다.
    for item in items:
        # 혹시 모를 다른 날짜 컬럼명에 대비한 다중 체크
        date_val = str(item.get('ADMDSP_DT', item.get('DISPOS_DATE', item.get('EXAATHR_PD', ''))))
        
        # '20260615' 처럼 날짜가 연월로 시작하는지 체크
        if date_val.startswith(selected_year_month):
            filtered_items.append(item)

    if not filtered_items:
        st.info(f"{selected_month}에 해당하는 행정처분 데이터가 없습니다.")
    else:
        df = pd.DataFrame(filtered_items)
        st.subheader(f"📊 {selected_month} 행정처분 업체 리스트")
        
        # 업소명 추출 (BSSH_NM 컬럼)
        company_names = list(set([item.get('BSSH_NM', item.get('ENTP_NAME', '알 수 없음')) for item in filtered_items]))
        selected_company = st.selectbox("상세 정보를 보려면 업체를 선택하세요", ["업체를 선택하세요"] + company_names)

        if selected_company != "업체를 선택하세요":
            detail = next((item for item in filtered_items if item.get('BSSH_NM', item.get('ENTP_NAME')) == selected_company), None)
            
            if detail:
                st.markdown(f"""
                <div class="penalty-card">
                    <h3>🏢 업체명: {detail.get('BSSH_NM', detail.get('ENTP_NAME', '내용 없음'))}</h3>
                    <p><strong>⚠️ 위반법령:</strong> {detail.get('LGL_CD_NM', detail.get('VIOLT_NM', '내용 없음'))}</p>
                    <p><strong>📝 위반내용:</strong> {detail.get('VIOLT_CN', '내용 없음')}</p>
                    <p><strong>⚖️ 행정처분명:</strong> {detail.get('ADMDSP_NM', detail.get('EXAATHR_NM', '내용 없음'))}</p>
                    <p><strong>📅 처분일자:</strong> {detail.get('ADMDSP_DT', detail.get('EXAATHR_PD', '내용 없음'))}</p>
                </div>
                """, unsafe_allow_html=True)
        
        with st.expander("전체 데이터 표 보기"):
            st.dataframe(df)
