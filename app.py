import streamlit as st
import google.generativeai as genai
import gspread
import pandas as pd
import datetime
import io
import json
import re
from PIL import Image
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# 1. 시스템 및 API 설정
# ==========================================
st.set_page_config(page_title="원자재 표시사항 DB 시스템", layout="wide")

try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    SHEET_ID = st.secrets["GOOGLE_SHEET_ID"]
    FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
except KeyError as e:
    st.error(f"⚠️ 시스템 설정 오류: Streamlit Secrets에 {e} 값이 설정되지 않았습니다.")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-3.6-flash"

def get_google_creds():
    try:
        creds = Credentials(
            token=None,
            refresh_token=st.secrets["google_oauth"]["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=st.secrets["google_oauth"]["client_id"],
            client_secret=st.secrets["google_oauth"]["client_secret"]
        )
        return creds
    except Exception as e:
        st.error(f"구글 인증 로드 실패: {e}")
        return None

# ==========================================
# 2. 구글 드라이브 & 시트 통신 함수
# ==========================================
# 💡 수정: PDF 등 다양한 파일 형식을 지원하도록 mime_type 변수 추가
def upload_file_to_drive(file_bytes, file_name, mime_type):
    try:
        creds = get_google_creds()
        service = build('drive', 'v3', credentials=creds)
        file_metadata = {'name': file_name, 'parents': [FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
        uploaded_file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink',
            supportsAllDrives=True
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
# 💡 수정: PDF 및 이미지 바이너리 데이터를 직접 받아 처리하도록 변경
def extract_label_data(file_bytes, mime_type):
    prompt = """
    당신은 원부자재 한글표시사항(라벨) 데이터 추출 전문가입니다.
    첨부된 문서(PDF 또는 이미지)를 정밀하게 분석하여 아래 항목들을 추출하고, **반드시 순수한 JSON 형식으로만** 반환하십시오.
    코드 번호나 특정 항목이 안 보이면 빈 문자열("")로 두십시오.
    마크다운 기호(```json 등)는 절대 포함하지 마십시오.

    {
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
        
        # 바이너리 데이터와 MIME 타입을 AI 모델 규격에 맞춰 결합
        file_part = {
            "mime_type": mime_type,
            "data": file_bytes
        }
        
        response = model.generate_content([prompt, file_part])
        
        clean_json_str = re.sub(r'```json\n|\n```|```', '', response.text).strip()
        parsed_data = json.loads(clean_json_str)
        return parsed_data, None
    except json.JSONDecodeError:
        return None, "JSON 파싱 에러: 파일 인식이 불완전합니다. 문서가 암호화되어 있거나 너무 흐린지 확인해주세요."
    except Exception as e:
        return None, f"AI 분석 에러: {e}"

# ==========================================
# 4. Streamlit UI 렌더링
# ==========================================
st.title("원자재 표시사항 라벨 통합 관리 시스템")

tab1, tab2 = st.tabs(["📸 라벨 스캔 및 DB 저장 (PDF 지원)", "🔍 원자재 DB 검색 대시보드"])

# [탭 1] 한글라벨 스캔 및 저장
with tab1:
    st.markdown("### 신규 원자재 라벨 업로드")
    # 💡 수정: 확장자에 'pdf' 추가
    uploaded_file = st.file_uploader("한글표시사항 라벨 사진 또는 PDF를 업로드하세요 (JPG, PNG, PDF)", type=['jpg', 'jpeg', 'png', 'pdf'])

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        file_mime_type = uploaded_file.type
        
        # 💡 수정: 파일 형식에 따라 미리보기 방식 및 확장자 분리
        if "pdf" in file_mime_type.lower():
            st.info(f"📄 PDF 파일이 정상적으로 업로드되었습니다: `{uploaded_file.name}`")
            ext = ".pdf"
        else:
            image = Image.open(io.BytesIO(file_bytes))
            st.image(image, caption='업로드된 라벨 이미지', width=400)
            ext = ".jpg"
        
        manual_code = st.text_input("📦 원자재 코드 번호를 입력하세요 (예: 10356):", help="사진/문서에 코드가 없는 경우 직접 입력해야 DB에 반영됩니다.")
        
        if st.button("파일 분석 및 스프레드시트 저장", type="primary"):
            if not manual_code:
                st.warning("⚠️ 원자재 코드 번호를 먼저 입력해 주세요!")
            else:
                with st.spinner("AI가 파일을 판독 중입니다..."):
                    # 💡 수정: 파일 바이너리와 MIME 타입을 AI에 넘김
                    parsed_data, error = extract_label_data(file_bytes, file_mime_type)
                    
                    if error:
                        st.error(error)
                    else:
                        st.success("데이터 추출 성공! 드라이브 및 시트에 저장을 시작합니다.")
                        st.json(parsed_data)
                        
                        current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        file_name = f"원자재라벨_{parsed_data.get('원재료의 제품명', '미상')}_{current_time}{ext}"
                        
                        # 💡 수정: PDF/이미지 여부에 맞춰 드라이브 업로드
                        drive_link = upload_file_to_drive(file_bytes, file_name, file_mime_type)
                        
                        row_data = [
                            manual_code,
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
                            st.success(f"✅ 구글 스프레드시트에 저장 완료 (등록 코드: {manual_code})")
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
            allergen_filter = st.multiselect("알레르기 유발물질 포함 여부 필터링:", 
                                             ["우유", "대두", "밀", "참깨", "계란", "토마토", "복숭아", "아황산류", "돼지고기"])
        
        filtered_df = df
        
        if search_name:
            filtered_df = filtered_df[
                filtered_df['원재료의 제품명'].astype(str).str.contains(search_name, na=False) |
                filtered_df['코드'].astype(str).str.contains(search_name, na=False)
            ]
            
        if allergen_filter:
            pattern = '|'.join(allergen_filter)
            filtered_df = filtered_df[filtered_df['알러지유발물질'].astype(str).str.contains(pattern, regex=True, na=False)]
            
        st.markdown(f"**총 {len(filtered_df)}건의 원자재가 검색되었습니다.**")
        
        display_cols = [c for c in filtered_df.columns if c != '이미지 링크']
        st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.markdown("### 🖼️ 선택 원자재 라벨(원본) 확인")
        st.caption("위 검색 결과에 나타난 원자재들의 원본 파일(이미지/PDF)을 확인할 수 있습니다.")
        
        for idx, row in filtered_df.iterrows():
            product_name = row.get('원재료의 제품명', '이름 없음')
            img_url = row.get('이미지 링크', '')
            
            if img_url and str(img_url).startswith('http'):
                st.markdown(f"🔗 **[{product_name}] 원본 파일 열기** : {img_url}")

    else:
        st.info("현재 데이터베이스에 등록된 원자재가 없습니다. 탭 1에서 라벨을 스캔하여 등록해주세요.")
