import streamlit as st
import google.generativeai as genai
import gspread
import pandas as pd
import datetime
import io
import json
import re
from PIL import Image
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# 1. 시스템 및 API 설정
# ==========================================
st.set_page_config(page_title="원자재 표시사항 DB 시스템", layout="wide")

GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
SHEET_ID = st.secrets["GOOGLE_SHEET_ID"]
FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]

genai.configure(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-1.5-flash" # 빠르고 비전 처리에 능한 플래시 모델

def get_google_creds():
    scopes = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    creds_dict = dict(st.secrets["google_oauth"])
    return Credentials.from_service_account_info(creds_dict, scopes=scopes)

# ==========================================
# 2. 구글 드라이브 & 시트 통신 함수
# ==========================================
def upload_image_to_drive(image_bytes, file_name):
    try:
        creds = get_google_creds()
        service = build('drive', 'v3', credentials=creds)
        file_metadata = {'name': file_name, 'parents': [FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/jpeg', resumable=True)
        uploaded_file = service.files().create(
            body=file_metadata, media_body=media, fields='id, webViewLink'
        ).execute()
        return uploaded_file.get('webViewLink')
    except Exception as e:
        return f"드라이브 업로드 에러: {e}"

def append_data_to_sheet(row_data):
    try:
        creds = get_google_creds()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.sheet1
        worksheet.append_row(row_data)
        return True
    except Exception as e:
        return str(e)

def load_sheet_data():
    try:
        creds = get_google_creds()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.sheet1
        return pd.DataFrame(worksheet.get_all_records())
    except Exception as e:
        st.error(f"데이터베이스 로드 실패: {e}")
        return pd.DataFrame()

# ==========================================
# 3. Gemini Vision API 데이터 파싱
# ==========================================
def extract_label_data(image):
    prompt = """
    당신은 원부자재 한글표시사항(라벨) 데이터 추출 전문가입니다.
    첨부된 이미지를 정밀하게 분석하여 아래 항목들을 추출하고, **반드시 순수한 JSON 형식으로만** 반환하십시오.
    코드 번호나 특정 항목이 이미지에 안 보이면 빈 문자열("")로 두십시오.
    마크다운 기호(```json 등)는 절대 포함하지 마십시오.

    {
        "코드": "고유 식별 번호가 있다면 숫자만 추출",
        "식품유형": "식품의 유형 기재",
        "원재료의 제품명": "제품명 기재",
        "원재료의 한글표시사항": "원재료명 및 함량 등 전체 텍스트 쉼표로 연결",
        "원산지": "주요 원산지 국가명",
        "(국내)제조원(판매원)": "제조사명",
        "수입원(판매원)": "수입사명",
        "알러지유발물질": "우유, 대두, 밀, 참깨, 토마토, 복숭아 등 식약처 규정 알레르기 물질이 포함되어 있으면 모두 기재 (없으면 '해당없음')",
        "수정일(한글라벨 제조일)": "제조일자, 유통기한 또는 라벨 스티커 발급일자"
    }
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content([prompt, image])
        
        # JSON 텍스트 정제 (마크다운 백틱 제거)
        clean_json_str = re.sub(r'```json\n|\n```|```', '', response.text).strip()
        parsed_data = json.loads(clean_json_str)
        return parsed_data, None
    except json.JSONDecodeError:
        return None, "JSON 파싱 에러: AI가 지정된 형식을 벗어났습니다. 다시 시도해주세요."
    except Exception as e:
        return None, f"AI 분석 에러: {e}"

# ==========================================
# 4. Streamlit UI 렌더링
# ==========================================
st.title("원자재 표시사항 라벨 통합 관리 시스템")

tab1, tab2 = st.tabs(["📸 한글라벨 스캔 및 DB 저장", "🔍 원자재 DB 검색 대시보드"])

# [탭 1] 한글라벨 스캔 및 저장
with tab1:
    st.markdown("### 신규 원자재 라벨 업로드")
    uploaded_file = st.file_uploader("한글표시사항 라벨 사진을 업로드하세요 (JPG, PNG)", type=['jpg', 'jpeg', 'png'])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption='업로드된 라벨 이미지', width=400)
        
        if st.button("이미지 분석 및 스프레드시트 저장", type="primary"):
            with st.spinner("AI가 라벨을 판독 중입니다..."):
                # 1. Gemini 데이터 추출
                parsed_data, error = extract_label_data(image)
                
                if error:
                    st.error(error)
                else:
                    st.success("데이터 추출 성공! 드라이브 및 시트에 저장을 시작합니다.")
                    st.json(parsed_data) # 추출된 데이터 미리보기
                    
                    # 2. 이미지를 구글 드라이브에 저장
                    current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    file_name = f"원자재라벨_{parsed_data.get('원재료의 제품명', '미상')}_{current_time}.jpg"
                    image_bytes = uploaded_file.getvalue()
                    
                    drive_link = upload_image_to_drive(image_bytes, file_name)
                    
                    # 3. 추출된 데이터와 링크를 구글 시트에 행 추가
                    row_data = [
                        parsed_data.get("코드", ""),
                        parsed_data.get("식품유형", ""),
                        parsed_data.get("원재료의 제품명", ""),
                        parsed_data.get("원재료의 한글표시사항", ""),
                        parsed_data.get("원산지", ""),
                        parsed_data.get("(국내)제조원(판매원)", ""),
                        parsed_data.get("수입원(판매원)", ""),
                        parsed_data.get("알러지유발물질", ""),
                        parsed_data.get("수정일(한글라벨 제조일)", ""),
                        drive_link
                    ]
                    
                    result = append_data_to_sheet(row_data)
                    if result == True:
                        st.success("✅ 구글 스프레드시트에 성공적으로 저장되었습니다.")
                    else:
                        st.error(f"시트 저장 실패: {result}")

# [탭 2] 데이터베이스 검색 대시보드
with tab2:
    st.markdown("### 등록된 원자재 목록 검색")
    if st.button("🔄 데이터베이스 새로고침"):
        st.rerun()

    df = load_sheet_data()
    
    if not df.empty:
        col1, col2 = st.columns(2)
        with col1:
            search_name = st.text_input("원재료 제품명 또는 코드로 검색:")
        with col2:
            # 알레르기 25종 중 주요 성분 필터 (추가 가능)
            allergen_filter = st.multiselect("알레르기 유발물질 포함 여부 필터링:", 
                                             ["우유", "대두", "밀", "참깨", "계란", "토마토", "복숭아", "아황산류"])
        
        filtered_df = df
        
        if search_name:
            filtered_df = filtered_df[
                filtered_df['원재료의 제품명'].astype(str).str.contains(search_name, na=False) |
                filtered_df['코드'].astype(str).str.contains(search_name, na=False)
            ]
            
        if allergen_filter:
            # 선택한 알레르기 물질 중 하나라도 포함된 데이터 필터링
            pattern = '|'.join(allergen_filter)
            filtered_df = filtered_df[filtered_df['알러지유발물질'].astype(str).str.contains(pattern, regex=True, na=False)]
            
        st.markdown(f"**총 {len(filtered_df)}건의 원자재가 검색되었습니다.**")
        
        # 이미지 링크 컬럼을 제외하고 표출 (화면 가독성)
        display_cols = [c for c in filtered_df.columns if c != '이미지 링크']
        st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.markdown("### 🖼️ 선택 원자재 라벨 이미지 확인")
        st.caption("위 검색 결과에 나타난 원자재들의 원본 라벨 이미지를 확인할 수 있습니다.")
        
        for idx, row in filtered_df.iterrows():
            product_name = row.get('원재료의 제품명', '이름 없음')
            img_url = row.get('이미지 링크', '')
            
            if img_url and str(img_url).startswith('http'):
                st.markdown(f"🔗 **[{product_name}] 원본 라벨 이미지 열기** : {img_url}")

    else:
        st.info("현재 데이터베이스에 등록된 원자재가 없습니다. 탭 1에서 라벨을 스캔하여 등록해주세요.")
