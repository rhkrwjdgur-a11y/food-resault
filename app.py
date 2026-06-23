import streamlit as st
import requests
import pandas as pd

# 웹 브라우저 탭의 제목과 화면 넓이를 설정합니다.
st.set_page_config(page_title="행정처분 검색 시스템", layout="wide")

# 화면 상단의 메인 제목을 출력합니다.
st.title("식약처 행정처분 실시간 검색 시스템")
st.write("업체명을 입력하여 실시간 행정처분 내역 및 형량을 조회합니다.")

# 보안을 위해 API 키를 화면에 직접 입력받는 칸을 만듭니다. 
# (코드에 키를 직접 적어서 깃허브에 올리면 다른 사람이 도용할 수 있기 때문입니다.)
api_key_input = st.text_input("공공데이터포털 API 인증키(Decoding)를 입력하세요", type="password")

# 사용자가 업체명을 검색할 수 있는 입력 칸을 만듭니다.
search_keyword = st.text_input("검색할 업체명을 입력하세요 (예: 연세)")

# 검색 버튼을 만듭니다. 버튼을 누르면 아래의 코드들이 실행됩니다.
if st.button("검색 실행"):
    # API 키와 검색어가 모두 입력되었는지 확인합니다.
    if not api_key_input:
        st.warning("상단에 API 인증키를 먼저 입력해주세요.")
    elif not search_keyword:
        st.warning("검색할 업체명을 입력해주세요.")
    else:
        # 진행 중이라는 회전하는 아이콘을 보여줍니다.
        with st.spinner("공공데이터포털에서 데이터를 실시간으로 가져오는 중입니다..."):
            
            # 식약처 공공데이터 API 주소입니다. (사용하시는 API에 따라 주소가 다를 수 있습니다.)
            url = "http://apis.data.go.kr/1471000/FoodFlwOrdrInfoService/getFoodFlwOrdrItem"
            
            # API에 전달할 요청 조건들입니다.
            params = {
                "ServiceKey": api_key_input,
                "pageNo": "1",
                "numOfRows": "100",  # 한 번에 가져올 데이터 개수
                "type": "json",      # 데이터를 JSON 형태로 받겠다고 요청
                "entp_name": search_keyword  # 업체명 검색 조건
            }

            try:
                # requests 라이브러리를 사용해 식약처 서버에 데이터를 요청합니다.
                response = requests.get(url, params=params)
                
                # 서버가 정상적으로 응답(상태 코드 200)했는지 확인합니다.
                if response.status_code == 200:
                    try:
                        # 받아온 데이터를 파이썬이 읽을 수 있는 딕셔너리 형태로 변환합니다.
                        data = response.json()
                        
                        # 데이터 중에서 실제 목록(items) 부분만 찾아냅니다. (API 응답 구조에 따라 키 이름이 다를 수 있습니다.)
                        # 공공데이터포털의 일반적인 JSON 응답 구조: response -> body -> items
                        items = data.get('response', {}).get('body', {}).get('items', [])
                        
                        # 검색된 데이터가 있을 경우 표(데이터프레임) 형태로 화면에 그려줍니다.
                        if items:
                            df = pd.DataFrame(items)
                            st.success(f"총 {len(df)}건의 행정처분 데이터를 찾았습니다.")
                            st.dataframe(df)
                        else:
                            st.info("검색된 업체의 행정처분 내역이 없습니다.")
                    except Exception as parse_error:
                        st.error("데이터를 표로 변환하는 데 실패했습니다. 발급받은 API의 데이터 구조가 다를 수 있습니다.")
                        st.write("오류 상세 내용:", parse_error)
                        st.write("식약처 서버가 보낸 원본 데이터:", response.text)
                else:
                    st.error(f"식약처 서버 호출에 실패했습니다. (상태 코드: {response.status_code})")
                    
            # 인터넷 연결 문제 등으로 아예 요청이 실패했을 때의 처리입니다.
            except Exception as e:
                st.error("데이터를 요청하는 중 시스템 오류가 발생했습니다.")
                st.write("오류 상세 내용:", e)