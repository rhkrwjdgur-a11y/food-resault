import streamlit as st
import streamlit.components.v1 as components
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

if "pending_overwrite_code" not in st.session_state:
    st.session_state.pending_overwrite_code = None

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

def update_row_in_sheet(row_data, code):
    try:
        creds = get_google_creds()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.sheet1
        
        codes = worksheet.col_values(1)
        code_str = str(code)
        
        if code_str in codes:
            row_index = codes.index(code_str) + 1
            cell_range = f'A{row_index}:J{row_index}'
            try:
                worksheet.update(range_name=cell_range, values=[row_data])
            except TypeError:
                worksheet.update(cell_range, [row_data])
            return True
        else:
            return "코드를 찾을 수 없습니다."
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
def extract_label_data(file_bytes, mime_type):
    prompt = """
    당신은 원부자재 한글표시사항(라벨) 데이터 추출 전문가입니다.
    첨부된 문서(PDF 또는 이미지)를 정밀하게 분석하여 아래 항목들을 추출하고, **반드시 순수한 JSON 형식으로만** 반환하십시오.
    특정 항목이 안 보이면 빈 문자열("")로 두십시오. 마크다운 기호(```json 등)는 절대 포함하지 마십시오.

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
        file_part = {"mime_type": mime_type, "data": file_bytes}
        response = model.generate_content([prompt, file_part])
        
        clean_json_str = re.sub(r'```json\n|\n```|```', '', response.text).strip()
        parsed_data = json.loads(clean_json_str)
        return parsed_data, None
    except json.JSONDecodeError:
        return None, "JSON 파싱 에러: 파일 인식이 불완전합니다. 문서가 암호화되어 있거나 너무 흐린지 확인해주세요."
    except Exception as e:
        return None, f"AI 분석 에러: {e}"

# ==========================================
# 4. 화면 내 인라인 뷰어 함수 (구글 드라이브 iframe 변환)
# ==========================================
def render_inline_viewer(img_url):
    # 구글 드라이브 URL에서 파일 ID를 추출하여 미리보기(preview) 링크로 변환
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', str(img_url))
    if match:
        file_id = match.group(1)
        iframe_src = f"https://drive.google.com/file/d/{file_id}/preview"
        components.iframe(iframe_src, height=600, scrolling=True)
    else:
        st.markdown(f"[링크 직접 열기 (새 창)]({img_url})")

# ==========================================
# 5. Streamlit UI 렌더링
# ==========================================
st.title("원자재 표시사항 라벨 통합 관리 시스템")

# 💡 탭 3개로 확장
tab1, tab2, tab3 = st.tabs(["📸 라벨 스캔 및 등록", "🔍 원자재 DB 검색 대시보드", "🚨 잠복 알레르기/신규성분 추적기"])

# ----------------------------------------------------
# [탭 1] 라벨 스캔 및 등록
# ----------------------------------------------------
with tab1:
    st.markdown("### 신규 원자재 라벨 업로드")
    uploaded_file = st.file_uploader("한글표시사항 라벨 사진 또는 PDF를 업로드하세요 (JPG, PNG, PDF)", type=['jpg', 'jpeg', 'png', 'pdf'])

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        file_mime_type = uploaded_file.type
        
        if "pdf" in file_mime_type.lower():
            st.info(f"📄 PDF 파일 업로드됨: `{uploaded_file.name}`")
            ext = ".pdf"
        else:
            image = Image.open(io.BytesIO(file_bytes))
            st.image(image, caption='업로드된 라벨 이미지', width=400)
            ext = ".jpg"
        
        manual_code = st.text_input("📦 원자재 코드 번호를 입력하세요 (예: 10356):")
        
        if st.button("파일 분석 및 스프레드시트 저장", type="primary"):
            if not manual_code:
                st.warning("⚠️ 원자재 코드 번호를 먼저 입력해 주세요!")
            else:
                df = load_sheet_data()
                code_exists = str(manual_code) in df['코드'].astype(str).values
                
                if code_exists and st.session_state.pending_overwrite_code != manual_code:
                    st.warning(f"⚠️ 이미 등록된 코드({manual_code})입니다! 기존 데이터를 지우고 최신 내용으로 덮어쓰시려면 버튼을 한 번 더 눌러주세요.")
                    st.session_state.pending_overwrite_code = manual_code
                else:
                    with st.spinner("AI가 파일을 판독 중입니다..."):
                        parsed_data, error = extract_label_data(file_bytes, file_mime_type)
                        
                        if error:
                            st.error(error)
                        else:
                            st.success("데이터 추출 성공! 드라이브 및 시트에 저장을 시작합니다.")
                            st.json(parsed_data)
                            
                            current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                            file_name = f"원자재라벨_{parsed_data.get('원재료의 제품명', '미상')}_{current_time}{ext}"
                            
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
                            
                            if code_exists:
                                result = update_row_in_sheet(row_data, manual_code)
                                action_text = "기존 데이터 덮어쓰기(업데이트)"
                            else:
                                result = append_data_to_sheet(row_data)
                                action_text = "신규 등록"
                                
                            if result == True:
                                st.success(f"✅ 구글 스프레드시트에 {action_text} 완료 (코드: {manual_code})")
                                st.session_state.pending_overwrite_code = None 
                            else:
                                st.error(f"시트 저장 실패: {result}")

# ----------------------------------------------------
# [탭 2] 데이터베이스 검색 대시보드
# ----------------------------------------------------
with tab2:
    st.markdown("### 등록된 원자재 목록 검색")
    if st.button("🔄 데이터베이스 새로고침", key="refresh_tab2"):
        st.rerun()

    df = load_sheet_data()
    
    if not df.empty:
        col1, col2 = st.columns(2)
        with col1:
            search_name = st.text_input("🔍 원재료 제품명 또는 코드로 검색:")
        with col2:
            allergen_filter = st.multiselect("⚠️ 공식 알레르기 표기란 기준 필터링:", 
                                             ["우유", "대두", "밀", "참깨", "계란", "토마토", "복숭아", "아황산류", "돼지고기"])
        
        if not search_name and not allergen_filter:
            st.info("👆 원하시는 원재료의 '제품명', '코드'를 검색하시거나 '알레르기 필터'를 선택하시면 목록이 나타납니다.")
        else:
            filtered_df = df
            
            if search_name:
                filtered_df = filtered_df[
                    filtered_df['원재료의 제품명'].astype(str).str.contains(search_name, na=False) |
                    filtered_df['코드'].astype(str).str.contains(search_name, na=False)
                ]
                
            if allergen_filter:
                pattern = '|'.join(allergen_filter)
                filtered_df = filtered_df[filtered_df['알러지유발물질'].astype(str).str.contains(pattern, regex=True, na=False)]
                
            if filtered_df.empty:
                st.warning("조건에 맞는 원자재가 없습니다.")
            else:
                st.markdown(f"**총 {len(filtered_df)}건의 원자재가 검색되었습니다.**")
                display_cols = [c for c in filtered_df.columns if c != '이미지 링크']
                st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True)
                
                st.markdown("---")
                st.markdown("### 🖼️ 선택 원자재 원본 라벨 확인")
                st.caption("아래 목록을 클릭하면 새 창으로 나가지 않고 화면 내부에서 바로 문서를 확인할 수 있습니다.")
                
                # 💡 인라인 뷰어로 교체
                for idx, row in filtered_df.iterrows():
                    product_name = row.get('원재료의 제품명', '이름 없음')
                    img_url = row.get('이미지 링크', '')
                    
                    if img_url and str(img_url).startswith('http'):
                        with st.expander(f"📄 [{product_name}] 원본 라벨/스펙 문서 보기"):
                            render_inline_viewer(img_url)
    else:
        st.info("현재 데이터베이스에 등록된 원자재가 없습니다.")

# ----------------------------------------------------
# [탭 3] 잠복 알레르기 / 신규 성분 추적기 (핵심 기능)
# ----------------------------------------------------
with tab3:
    st.markdown("### 🚨 신규/잠복 알레르기 유발물질 전수조사")
    st.caption("공식 '알러지유발물질' 란에 기재되지 않았더라도, **'원재료의 한글표시사항(전체 성분 리스트)'** 속에 숨어있는 타겟 물질(예: 참깨, 마카다미아 등 새로 추가된 성분)을 샅샅이 찾아냅니다.")
    
    df_track = load_sheet_data()
    
    if not df_track.empty:
        target_allergen = st.text_input("🔍 추적할 숨은 성분 키워드를 입력하세요 (예: 참깨, 호두, 잣):")
        
        if target_allergen:
            # 💡 '원재료의 한글표시사항' 전체 텍스트에서 키워드 검색
            mask = df_track['원재료의 한글표시사항'].astype(str).str.contains(target_allergen, regex=False, na=False)
            tracked_df = df_track[mask]
            
            if tracked_df.empty:
                st.success(f"🎉 현재 DB의 모든 원자재 성분 중에 '{target_allergen}'이(가) 포함된 원료는 없습니다!")
            else:
                st.error(f"🚨 주의! 전체 성분 목록 중에 '{target_allergen}'이(가) 포함된 원자재를 {len(tracked_df)}건 발견했습니다.")
                
                # 확인을 돕기 위해 필요한 컬럼만 추출하여 노출
                view_cols = ['코드', '원재료의 제품명', '원재료의 한글표시사항', '알러지유발물질', '이미지 링크']
                st.dataframe(tracked_df[view_cols[:-1]], use_container_width=True, hide_index=True)
                
                st.markdown("---")
                st.markdown("#### 🖼️ 적발된 원자재 라벨 직접 확인")
                for idx, row in tracked_df.iterrows():
                    product_name = row.get('원재료의 제품명', '이름 없음')
                    img_url = row.get('이미지 링크', '')
                    
                    if img_url and str(img_url).startswith('http'):
                        with st.expander(f"⚠️ [{product_name}] 원본 라벨에서 '{target_allergen}' 표기 직접 확인하기"):
                            render_inline_viewer(img_url)
    else:
        st.info("데이터베이스를 먼저 등록해 주세요.")
