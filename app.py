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
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

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

ADMIN_PASSWORD = "2082"

FOOD_TYPES = [
    "선택하세요 (검색 가능)", "과자류", "빵류 또는 떡류", "코코아가공품류 또는 초콜릿류", "당류", "잼류", "두부류 또는 묵류", 
    "식용유지류", "면류", "음료류", "특수용도식품", "장류", "조미식품", "절임류 또는 조림류", "농산가공품류", 
    "두류가공품", "서류가공품", "과채가공품", "곡류가공품", "식육가공품", "알가공품", "유가공품", "수산가공품", 
    "식품첨가물(혼합제제)", "식품첨가물(화학적합성품)", "천연향료", "합성향료", "기타가공품"
]

OLD_ALLERGENS = [
    "🟩 해당없음 (안전)", "난류(가금류)", "우유", "메밀", "땅콩", "대두", "밀", "고등어", "게", "새우", 
    "돼지고기", "복숭아", "토마토", "아황산류", "호두", "닭고기", "쇠고기", "오징어", "조개류(굴, 전복, 홍합 포함)", "잣"
]

NEW_ALLERGENS = [
    "🟩 해당없음 (안전)", "참깨", "들깨", "아몬드", "캐슈넛"
]

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
            fields='id, webViewLink'
        ).execute()
        return uploaded_file.get('webViewLink'), uploaded_file.get('id')
    except Exception as e:
        st.error(f"드라이브 업로드 에러: {e}")
        return None, None

def download_file_from_drive(file_id):
    try:
        creds = get_google_creds()
        service = build('drive', 'v3', credentials=creds)
        request = service.files().get_media(fileId=file_id)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        file_metadata = service.files().get(fileId=file_id, fields='mimeType').execute()
        return file_stream.getvalue(), file_metadata.get('mimeType')
    except Exception as e:
        return None, None

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

def update_row_data(row_index_str, update_dict):
    try:
        creds = get_google_creds()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.sheet1
        
        col_map = {
            '코드': 'A', '제품명': 'B', '식품유형': 'C', '원재료명(한글표시사항)': 'D',
            '원산지': 'E', '제조원': 'F', '기존알레르기': 'G', '신규알레르기': 'H',
            '검증상태': 'L', '검증결과': 'M'
        }
        
        for key, val in update_dict.items():
            if key in col_map:
                worksheet.update_acell(f'{col_map[key]}{row_index_str}', str(val))
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
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_bom_data():
    try:
        creds = get_google_creds()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.worksheet("배합비 DB")
        return pd.DataFrame(worksheet.get_all_records())
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_master_data():
    try:
        creds = get_google_creds()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.worksheet("전체 원재료 명단")
        return pd.DataFrame(worksheet.get_all_records())
    except Exception:
        return pd.DataFrame()

# ==========================================
# 3. 공용 헬퍼 함수
# ==========================================
def verify_with_ai(file_bytes, mime_type, vendor_data, master_data_json):
    prompt = f"""
    당신은 식품안전팀의 엄격한 품질관리(QC) AI 검수자입니다.
    두 가지 작업을 수행하십시오.

    [작업 1: 교차 검증]
    업체가 입력한 데이터와 첨부된 라벨 문서(이미지/PDF)를 정밀하게 비교하세요.
    - 업체 데이터: 제품명({vendor_data['제품명']}), 원재료명({vendor_data['원재료명(한글표시사항)']}), 기존알레르기({vendor_data['기존알레르기']}), 신규알레르기({vendor_data['신규알레르기']})
    - 라벨 원본에 숨어있는 알레르기 성분(특히 신규 알레르기: 참깨, 들깨, 아몬드, 캐슈넛) 누락 여부를 집중 점검하세요.

    [작업 2: 마스터 코드 매칭]
    아래 제공된 '사내 전체 원자재 명단'을 바탕으로, 업체가 제출한 [제품명({vendor_data['제품명']})] 및 [제조원({vendor_data['제조원']})]과 텍스트 유사도(띄어쓰기, 축약어, 공장명 포함)가 가장 높은 원자재 코드를 하나 찾아 추천하세요.
    - 사내 원자재 명단(JSON): {master_data_json}

    [출력 형식] (반드시 아래 양식을 지켜 순수 텍스트로만 출력하세요)
    판정: [합격] 또는 [불합격] (사유: ~)
    상세코멘트: (검증 결과 상세 작성)
    추천매칭코드: (찾아낸 원자재코드 숫자만 적으세요. 명단에 없거나 불확실하면 '없음'으로 기재)
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        file_part = {"mime_type": mime_type, "data": file_bytes}
        response = model.generate_content([prompt, file_part])
        return response.text
    except Exception as e:
        return f"AI 분석 에러: {e}"

def render_inline_viewer(img_url):
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', str(img_url))
    if match:
        file_id = match.group(1)
        iframe_src = f"https://drive.google.com/file/d/{file_id}/preview"
        components.iframe(iframe_src, height=800, scrolling=True)
    else:
        st.markdown(f"[링크 직접 열기]({img_url})")

def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8-sig')

def format_audit_result(text):
    text_str = str(text)
    if "[합격]" in text_str:
        return "🟢 합격"
    elif "[불합격]" in text_str:
        return "🔴 불합격"
    return text_str

def clean_allergen_text(text):
    text = str(text).replace("🟩 해당없음 (안전)", "-").strip()
    text = re.sub(r'[⚠️🚨]', '', text).strip()
    if not text:
        return "-"
    return text

def highlight_new_allergens(text):
    text = str(text)
    targets = ["참깨", "들깨", "아몬드", "캐슈넛"]
    has_target = any(t in text for t in targets)
    
    if has_target:
        return f'<span style="background-color: #ffcccc; color: #cc0000; padding: 2px 6px; border-radius: 4px; font-weight: bold;">{text}</span>'
    return text

# ==========================================
# 4. 화면 라우팅 (관리자 vs 협력업체)
# ==========================================
with st.sidebar:
    st.markdown("### 🔐 식품안전팀 관리자 로그인")
    user_pw = st.text_input("접속 암호를 입력하세요:", type="password")
    
is_admin = (user_pw == ADMIN_PASSWORD)

if not is_admin:
    # ----------------------------------------------------
    # [프론트엔드] 협력업체 다중 등록 폼
    # ----------------------------------------------------
    st.title("🤝 원자재 라벨 및 표시사항 다중 등록 시스템")
    
    st.markdown("""
    <div style="background-color: #f0f7ff; padding: 15px; border-radius: 8px; border-left: 5px solid #0056b3; margin-bottom: 20px;">
    <strong>📢 [안내] 원자재 알레르기 유발물질 선제적 전수조사 및 DB화</strong><br>
    식약처 법규 개정에 따라 향후 <strong>알레르기 유발물질 의무 표시 대상 확대(참깨, 들깨, 아몬드, 캐슈넛 추가)가 시행될 예정</strong>입니다. <br>
    연세유업은 제도 시행 전 <strong>선제적인 파악 및 대응</strong>을 통해 완벽한 법규 준수와 소비자 안전을 확보하고자, 협력업체에서 납품하시는 모든 원료의 <strong>'원본 라벨(한글표시사항)' 및 '성분 정보'</strong>를 전수조사 중입니다. 정확한 품질관리를 위해 사업자등록증 상의 정보와 라벨 원본 내용을 똑같이 기재해 주시기를 당부드립니다.
    </div>
    """, unsafe_allow_html=True)
    
    if "item_count" not in st.session_state:
        st.session_state.item_count = 1
        
    st.markdown("### 📝 제출 품목 개수 설정")
    col_num1, col_num2, col_num3 = st.columns([3, 2, 5])
    with col_num1:
        new_count = st.number_input("연세유업 납품 품목 개수를 적으세요 (제한 없음)", min_value=1, value=st.session_state.item_count, step=1)
    with col_num2:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        if st.button("입력칸 개수 적용 / 추가하기", type="secondary"):
            st.session_state.item_count = new_count
            st.rerun()
            
    st.markdown("<hr style='border:2px solid #ddd'>", unsafe_allow_html=True)
    
    with st.form("vendor_bulk_form"):
        st.markdown("### 🏢 납품업체(제조원) 정보")
        v_maker_global = st.text_input("납품하시는 업체명(제조원 또는 판매원)을 적어주세요 (사업자등록증 기준 필수 기재)")
        
        st.markdown("---")
        
        items_data = []
        for i in range(int(st.session_state.item_count)):
            st.markdown(f"#### 📌 제출 품목 {i+1}")
            
            col1, col2, col3 = st.columns([1.5, 1.5, 1])
            with col1:
                v_name = st.text_input("🏷️ 제품명 (라벨 표기 기준, 필수)", key=f"name_{i}")
            with col2:
                v_type = st.selectbox("분류 식품유형 (타이핑하여 검색 가능, 필수)", options=FOOD_TYPES, key=f"type_{i}")
            with col3:
                v_origin = st.text_input("🌍 원산지", key=f"origin_{i}")
                
            col4, col5 = st.columns([2, 2])
            with col4:
                v_old_allergy = st.multiselect("⚠️ 기존 알레르기 물질 (필수 체크)", options=OLD_ALLERGENS, key=f"oa_{i}")
                v_new_allergy = st.multiselect("🚨 신규 알레르기 물질 (필수 체크)", options=NEW_ALLERGENS, key=f"na_{i}")
            with col5:
                v_ingredients = st.text_area("📝 원재료명 및 함량 (쉼표로 구분하여 전부 기재)", height=120, key=f"ing_{i}")
            
            uploaded_file = st.file_uploader("📸 원본 라벨 첨부 (PDF/JPG 필수)", type=['jpg', 'jpeg', 'png', 'pdf'], key=f"file_{i}")
            
            items_data.append({
                "name": v_name, "type": v_type, "maker": v_maker_global, "origin": v_origin,
                "old_allergy": v_old_allergy, "new_allergy": v_new_allergy,
                "ingredients": v_ingredients, "file": uploaded_file
            })
            
            st.markdown("<hr style='border:1px dashed #ccc'>", unsafe_allow_html=True)
            
        submit_btn = st.form_submit_button("📤 작성한 품목 모두 제출하기", type="primary", use_container_width=True)
        
        if submit_btn:
            error_found = False
            
            if not v_maker_global:
                st.error("❌ 상단에 [납품업체명(제조원)]을 반드시 입력해 주세요.")
                error_found = True
            
            for idx, item in enumerate(items_data):
                if not item['name'] or item['type'] == "선택하세요 (검색 가능)" or not item['ingredients'] or not item['file']:
                    st.error(f"❌ [품목 {idx+1}] 필수 항목(제품명, 식품유형, 원재료명, 파일 첨부)이 누락되었습니다.")
                    error_found = True
                
                if not item['old_allergy']:
                    st.error(f"❌ [품목 {idx+1}] 기존 알레르기 포함 여부를 체크해 주세요. (없으면 '해당없음')")
                    error_found = True
                elif "🟩 해당없음 (안전)" in item['old_allergy'] and len(item['old_allergy']) > 1:
                    st.error(f"❌ [품목 {idx+1}] 기존 알레르기에서 '해당없음'과 다른 물질을 중복 선택할 수 없습니다.")
                    error_found = True
                    
                if not item['new_allergy']:
                    st.error(f"❌ [품목 {idx+1}] 신규 알레르기 포함 여부를 체크해 주세요. (없으면 '해당없음')")
                    error_found = True
                elif "🟩 해당없음 (안전)" in item['new_allergy'] and len(item['new_allergy']) > 1:
                    st.error(f"❌ [품목 {idx+1}] 신규 알레르기에서 '해당없음'과 다른 물질을 중복 선택할 수 없습니다.")
                    error_found = True
                    
            if not error_found:
                with st.spinner(f"총 {st.session_state.item_count}건의 품목 데이터를 서버로 안전하게 전송 중입니다..."):
                    success_count = 0
                    current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    for idx, item in enumerate(items_data):
                        file_bytes = item['file'].getvalue()
                        file_mime_type = item['file'].type
                        ext = ".pdf" if "pdf" in file_mime_type.lower() else ".jpg"
                        file_name = f"업체제출_{item['name']}_{current_time}_{idx+1}{ext}"
                        
                        drive_link, file_id = upload_file_to_drive(file_bytes, file_name, file_mime_type)
                        
                        if drive_link and file_id:
                            row_data = [
                                "", item['name'], item['type'], item['ingredients'], item['origin'], item['maker'], 
                                ", ".join(item['old_allergy']), ", ".join(item['new_allergy']), current_time, 
                                drive_link, file_id, "대기중", "검증전"
                            ]
                            res = append_data_to_sheet(row_data)
                            if res == True:
                                success_count += 1
                            else:
                                st.error(f"[품목 {idx+1}] 저장 중 에러가 발생했습니다: {res}")
                        else:
                            st.error(f"[품목 {idx+1}] 파일 업로드에 실패했습니다.")
                    
                    if success_count == st.session_state.item_count:
                        st.success(f"🎉 총 {success_count}건의 품목 전체가 성공적으로 제출되었습니다! 협조해 주셔서 감사합니다.")
                    elif success_count > 0:
                        st.warning(f"일부 품목만 제출되었습니다. ({success_count}/{st.session_state.item_count}건 성공)")

else:
    # ----------------------------------------------------
    # [백엔드] 식품안전팀 관리자 대시보드
    # ----------------------------------------------------
    st.title("🛡️ 식품안전팀 품질관리 통합 대시보드")
    
    admin_tab1, admin_tab2, admin_tab3, admin_tab4, admin_tab5 = st.tabs([
        "📊 제출 현황판", "🤖 AI 교차 검증 및 코드 승인", "🔍 등록 DB 검색", "🚨 배합비 역추적", "📋 완제품 알레르기 마스터"
    ])
    
    df = load_sheet_data()
    master_df = load_master_data()
    master_json = master_df.to_json(orient='records', force_ascii=False) if not master_df.empty else "[]"
    
    # ------------------ [탭 1: 수취 현황판] ------------------
    with admin_tab1:
        st.markdown("### 📈 협력업체 라벨 제출 진척도")
        if st.button("🔄 최신 데이터 불러오기"):
            st.cache_data.clear()
            st.rerun()
            
        if not master_df.empty and not df.empty:
            total_items = len(master_df)
            submitted_codes = df[df['코드'] != '']['코드'].astype(str).tolist()
            master_df['제출여부'] = master_df['원자재코드'].astype(str).isin(submitted_codes)
            
            submitted_count = master_df['제출여부'].sum()
            progress_pct = int((submitted_count / total_items) * 100) if total_items > 0 else 0
            
            st.progress(progress_pct / 100.0)
            st.markdown(f"**전체 {total_items}건 중 {submitted_count}건 코드 맵핑 완료 (진행률: {progress_pct}%)**")
            
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                st.error(f"🔴 미제출/미승인 업체 리스트 ({total_items - submitted_count}건)")
                missing_df = master_df[master_df['제출여부'] == False]
                st.dataframe(missing_df[['원자재코드', '원자재명']], use_container_width=True, hide_index=True)
            with col_m2:
                st.success(f"🟢 승인 완료 리스트 ({submitted_count}건)")
                completed_df = master_df[master_df['제출여부'] == True]
                st.dataframe(completed_df[['원자재코드', '원자재명']], use_container_width=True, hide_index=True)
        else:
            st.info("구글 시트에 '전체 원재료 명단' 또는 제출된 데이터가 없습니다.")

    # ------------------ [탭 2: AI 검증 및 승인] ------------------
    with admin_tab2:
        st.markdown("### 🤖 대기열 검증 및 마스터 코드 확정 (인라인 수정 모드)")
        st.caption("좌측의 폼에서 오타를 직접 수정한 후 승인할 수 있으며, 우측의 라벨 이미지와 실시간으로 대조 가능합니다.")
        
        if not df.empty:
            pending_df = df[df['검증상태'] == '대기중'].reset_index()
            
            if pending_df.empty:
                st.success("🎉 현재 대기 중인 검증 건이 없습니다. 모두 승인되었습니다.")
            else:
                st.warning(f"⚠️ 현재 {len(pending_df)}건의 라벨이 검증 및 승인 대기 중입니다.")
                
                for _, row in pending_df.iterrows():
                    excel_row_idx = row['index'] + 2 
                    name = row.get('제품명', '')
                    file_id = row.get('파일ID', '')
                    submit_time = row.get('제출일시', '')
                    img_url = row.get('이미지링크', '')
                    
                    with st.expander(f"📦 [대기중] {name} - ({submit_time})", expanded=False):
                        col_left, col_right = st.columns([4, 6])
                        
                        with col_left:
                            st.markdown("#### 📝 제출 데이터 (수정 가능)")
                            
                            edit_maker = st.text_input("제조원", value=row.get('제조원'), key=f"e_maker_{excel_row_idx}")
                            edit_name = st.text_input("제품명", value=row.get('제품명'), key=f"e_name_{excel_row_idx}")
                            edit_type = st.text_input("식품유형", value=row.get('식품유형'), key=f"e_type_{excel_row_idx}")
                            edit_origin = st.text_input("원산지", value=row.get('원산지'), key=f"e_origin_{excel_row_idx}")
                            edit_old = st.text_input("기존 알레르기", value=row.get('기존알레르기'), key=f"e_old_{excel_row_idx}")
                            edit_new = st.text_input("신규 알레르기", value=row.get('신규알레르기'), key=f"e_new_{excel_row_idx}")
                            edit_ing = st.text_area("원재료명(한글표시사항)", value=row.get('원재료명(한글표시사항)'), height=150, key=f"e_ing_{excel_row_idx}")
                            
                            if st.button(f"🔍 AI 교차검증 및 매칭 분석", key=f"btn_ai_{excel_row_idx}"):
                                if file_id:
                                    with st.spinner("드라이브 라벨 분석 및 마스터 코드 매칭 중..."):
                                        f_bytes, mime = download_file_from_drive(file_id)
                                        if f_bytes:
                                            updated_vendor_data = {
                                                '제품명': edit_name,
                                                '원재료명(한글표시사항)': edit_ing,
                                                '제조원': edit_maker,
                                                '기존알레르기': edit_old,
                                                '신규알레르기': edit_new
                                            }
                                            result = verify_with_ai(f_bytes, mime, updated_vendor_data, master_json)
                                            
                                            match_code = "없음"
                                            for line in result.split('\n'):
                                                if "추천매칭코드:" in line:
                                                    match_code = line.split("추천매칭코드:")[1].strip()
                                                    break
                                            
                                            st.session_state[f"ai_result_{excel_row_idx}"] = result
                                            st.session_state[f"rec_code_{excel_row_idx}"] = match_code
                                        else:
                                            st.error("라벨 파일 다운로드 실패")
                                else:
                                    st.error("파일 ID가 존재하지 않습니다.")
                            
                            if f"ai_result_{excel_row_idx}" in st.session_state:
                                st.markdown("### 📋 AI 판독 및 매칭 결과")
                                ai_result_text = st.session_state[f"ai_result_{excel_row_idx}"]
                                
                                if "[불합격]" in ai_result_text:
                                    st.markdown(f'<div style="background-color: #ffcccc; padding: 10px; border-radius: 5px; color: #cc0000; font-weight: bold;">{ai_result_text}</div>', unsafe_allow_html=True)
                                else:
                                    st.info(ai_result_text)
                                
                                st.markdown("---")
                                final_code = st.text_input(
                                    "최종 매핑할 '원자재 코드' 입력:", 
                                    value=st.session_state[f"rec_code_{excel_row_idx}"], 
                                    key=f"final_code_{excel_row_idx}"
                                )
                                
                                if st.button(f"✅ 코드 '{final_code}' 승인 및 수정사항 전체 DB 저장", type="primary", key=f"btn_approve_{excel_row_idx}"):
                                    if final_code and final_code != "없음":
                                        ai_full_text = st.session_state[f"ai_result_{excel_row_idx}"]
                                        update_dict = {
                                            '코드': final_code,
                                            '제품명': edit_name,
                                            '식품유형': edit_type,
                                            '원재료명(한글표시사항)': edit_ing,
                                            '원산지': edit_origin,
                                            '제조원': edit_maker,
                                            '기존알레르기': edit_old,
                                            '신규알레르기': edit_new,
                                            '검증상태': '승인완료',
                                            '검증결과': ai_full_text
                                        }
                                        res = update_row_data(excel_row_idx, update_dict)
                                        
                                        if res == True:
                                            st.success("데이터베이스에 코드 및 수정 내용이 정상 확정되었습니다! (새로고침 요망)")
                                        else:
                                            st.error(f"저장 에러: {res}")
                                    else:
                                        st.error("유효한 원자재 코드를 입력해야 승인할 수 있습니다.")
                        
                        with col_right:
                            st.markdown("#### 🖼️ 첨부 라벨 원본 뷰어")
                            if img_url and str(img_url).startswith('http'):
                                render_inline_viewer(img_url)
                            else:
                                st.warning("라벨 이미지가 없습니다.")
        else:
            st.info("등록된 데이터가 없습니다.")

    # ------------------ [탭 3: 기존 DB 검색 및 다운로드] ------------------
    with admin_tab3:
        st.markdown("### 🔍 승인된 원자재 DB 다중 검색 및 다운로드")
        if not df.empty:
            approved_df = df[df['검증상태'] == '승인완료'].copy()
            
            search_query = st.text_input("🔍 제품명 또는 코드 검색 (쉼표로 구분하여 여러 개 동시 검색 가능, 예: 20014, 참깨):")
            
            if search_query:
                queries = [q.strip() for q in search_query.split(',') if q.strip()]
                pattern = '|'.join(queries)
                
                approved_df = approved_df[
                    approved_df['제품명'].astype(str).str.contains(pattern, regex=True, na=False) |
                    approved_df['코드'].astype(str).str.contains(pattern, regex=True, na=False)
                ]
            
            approved_df['기존알레르기'] = approved_df['기존알레르기'].apply(clean_allergen_text)
            approved_df['신규알레르기'] = approved_df['신규알레르기'].apply(clean_allergen_text).apply(highlight_new_allergens)
            
            # 원산지 추가 및 검증결과 제거
            display_cols = ['코드', '제품명', '식품유형', '원산지', '원재료명(한글표시사항)', '제조원', '기존알레르기', '신규알레르기']
            
            st.markdown(
                """
                <style>
                .custom-table {
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 14px;
                    margin-bottom: 20px;
                }
                .custom-table th, .custom-table td {
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: left;
                    vertical-align: top;
                }
                .custom-table th {
                    background-color: #f2f2f2;
                    font-weight: bold;
                }
                </style>
                """, unsafe_allow_html=True
            )
            html_table = approved_df[display_cols].to_html(classes="custom-table", index=False, escape=False)
            st.markdown(html_table, unsafe_allow_html=True)
            
            if not approved_df.empty:
                raw_df = df[df['검증상태'] == '승인완료'].copy()
                if search_query:
                    raw_df = raw_df[raw_df['제품명'].astype(str).str.contains(pattern, regex=True, na=False) | raw_df['코드'].astype(str).str.contains(pattern, regex=True, na=False)]
                
                csv = convert_df_to_csv(raw_df[display_cols])
                st.download_button(
                    label="📥 검색 결과 엑셀(CSV) 다운로드",
                    data=csv,
                    file_name="원자재_DB_검색결과.csv",
                    mime="text/csv",
                )
                
                st.markdown("---")
                st.markdown("#### 🖼️ 선택 원자재 라벨 직접 확인 및 원본 다운로드")
                
                # 리스트가 길어질 경우를 대비한 드롭다운(Selectbox) 방식 적용
                selected_product = st.selectbox(
                    "확인할 원자재를 선택하세요:",
                    options=approved_df['제품명'].tolist(),
                    format_func=lambda x: f"{x} (라벨 원본 뷰어 열기)"
                )
                
                if selected_product:
                    selected_row = approved_df[approved_df['제품명'] == selected_product].iloc[0]
                    img_url = selected_row.get('이미지링크', '')
                    file_id = selected_row.get('파일ID', '')
                    
                    if img_url and str(img_url).startswith('http'):
                        render_inline_viewer(img_url)
                        if file_id:
                            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                            st.markdown(f"[💾 라벨 원본 파일 다운로드 (클릭 시 새 창에서 다운로드)]({download_url})")
        else:
            st.info("데이터가 없습니다.")

    # ------------------ [탭 4: 배합비 역추적기] ------------------
    with admin_tab4:
        st.markdown("### 🚨 잠복 알레르기 및 완제품(BOM) 역추적")
        bom_df = load_bom_data()
        
        if not df.empty:
            valid_df = df[df['코드'] != '']
            target_allergen = st.text_input("🔍 추적할 숨은 성분 키워드 (예: 참깨, 아몬드):")
            
            if target_allergen:
                mask_name = valid_df['제품명'].astype(str).str.contains(target_allergen, regex=False, na=False)
                mask_detail = valid_df['원재료명(한글표시사항)'].astype(str).str.contains(target_allergen, regex=False, na=False)
                
                tracked_df = valid_df[mask_name | mask_detail].copy()
                
                if tracked_df.empty:
                    st.success("🎉 해당 물질이 포함된 원료가 없습니다!")
                else:
                    st.error(f"🚨 타겟 물질('{target_allergen}')이 포함된 원자재 {len(tracked_df)}건 적발.")
                    st.dataframe(tracked_df[['코드', '제품명', '원재료명(한글표시사항)', '신규알레르기']], use_container_width=True, hide_index=True)
                    
                    csv_mat = convert_df_to_csv(tracked_df[['코드', '제품명', '원재료명(한글표시사항)', '신규알레르기']])
                    st.download_button("📥 적발된 원자재 리스트 다운로드", data=csv_mat, file_name=f"{target_allergen}_포함_원자재.csv", mime="text/csv")
                    
                    st.markdown("---")
                    
                    if not bom_df.empty:
                        st.markdown(f"#### 🏭 '{target_allergen}' 유입 완제품 리스트 (다계층 무한 추적)")
                        flagged_codes = tracked_df['코드'].astype(str).tolist()
                        affected_products_list = []
                        
                        code_cols = [c for c in bom_df.columns if str(c).startswith('Code') and c != 'Code1']
                        if not code_cols and '원자재코드' in bom_df.columns:
                            code_cols = ['원자재코드']
                        
                        for code_col in code_cols:
                            matches = bom_df[bom_df[code_col].astype(str).isin(flagged_codes)]
                            name_col = code_col.replace('Code', 'Name')
                            if name_col not in bom_df.columns:
                                name_col = '원자재명' if '원자재명' in bom_df.columns else code_col
                            
                            for _, row in matches.iterrows():
                                affected_products_list.append({
                                    '완제품코드': str(row.get('Code1', row.get('완제품코드', ''))),
                                    '완제품명': str(row.get('Name1', row.get('완제품명', ''))),
                                    '적발된 원료코드': str(row.get(code_col, '')),
                                    '적발된 원료명': str(row.get(name_col, '')),
                                })
                        
                        if not affected_products_list:
                            st.success("✅ 적발 원료가 투입된 완제품이 없습니다.")
                        else:
                            affected_df = pd.DataFrame(affected_products_list).drop_duplicates()
                            st.warning(f"⚠️ 총 {len(affected_df['완제품코드'].unique())}종의 완제품에 투입되고 있습니다.")
                            st.dataframe(affected_df, use_container_width=True, hide_index=True)
                            
                            csv_prod = convert_df_to_csv(affected_df)
                            st.download_button("📥 유입 위험 완제품 리스트 다운로드", data=csv_prod, file_name=f"{target_allergen}_유입_완제품.csv", mime="text/csv")
                    else:
                        st.info("BOM 데이터가 없습니다.")

    # ------------------ [탭 5: 완제품 알레르기 마스터] ------------------
    with admin_tab5:
        st.markdown("### 📋 완제품 알레르기 통합 마스터 테이블")
        
        WARNING_MSG = "알레르기 유발물질 혼입 가능성 있음"
        st.markdown(f"""
        <div style="background-color: #ffe6e6; padding: 15px; border-radius: 8px; border-left: 5px solid #ff4d4d; margin-bottom: 20px;">
        <strong>⚠️ [주의] 알레르기 교차 혼입 방지</strong><br>
        당사는 알레르기 교차 혼입 방지 문구로 『<strong>{WARNING_MSG}</strong>』을(를) 사용하고 있으므로, 표시사항 스티커 및 패키지 후면 인쇄 시 반드시 해당 문구를 포함하여야 합니다.
        </div>
        """, unsafe_allow_html=True)
        
        bom_df = load_bom_data()
        
        if df.empty or bom_df.empty:
            st.info("원자재 DB(승인 완료건) 또는 배합비 DB가 필요합니다.")
        else:
            with st.spinner("BOM 데이터와 원자재 DB를 스캔하여 완제품별 알레르기 테이블을 구성 중입니다..."):
                valid_df = df[df['코드'] != '']
                
                prod_col = 'Name1' if 'Name1' in bom_df.columns else '완제품명'
                prod_code_col = 'Code1' if 'Code1' in bom_df.columns else '완제품코드'
                
                unique_products = bom_df[[prod_code_col, prod_col]].drop_duplicates().dropna(subset=[prod_code_col])
                
                master_table_data = []
                
                code_cols = [c for c in bom_df.columns if str(c).startswith('Code') and c != 'Code1']
                if not code_cols and '원자재코드' in bom_df.columns:
                    code_cols = ['원자재코드']
                
                for _, p_row in unique_products.iterrows():
                    p_code = p_row[prod_code_col]
                    p_name = p_row[prod_col]
                    
                    if not str(p_code).strip(): continue
                    
                    p_bom_rows = bom_df[bom_df[prod_code_col] == p_code]
                    
                    used_rm_codes = set()
                    for code_col in code_cols:
                        used_rm_codes.update(p_bom_rows[code_col].dropna().astype(str).tolist())
                    
                    used_rm_df = valid_df[valid_df['코드'].astype(str).isin(used_rm_codes)]
                    
                    if used_rm_df.empty: continue
                    
                    all_old_allergies = set()
                    all_new_allergies = set()
                    
                    for _, rm_row in used_rm_df.iterrows():
                        old_str = str(rm_row.get('기존알레르기', ''))
                        new_str = str(rm_row.get('신규알레르기', ''))
                        
                        for item in old_str.split(','):
                            clean_item = item.strip()
                            if clean_item and "해당없음" not in clean_item:
                                all_old_allergies.add(clean_item)
                                
                        for item in new_str.split(','):
                            clean_item = item.strip()
                            if clean_item and "해당없음" not in clean_item:
                                all_new_allergies.add(clean_item)
                    
                    final_old = ", ".join(sorted(list(all_old_allergies))) if all_old_allergies else "해당없음"
                    final_new = ", ".join(sorted(list(all_new_allergies))) if all_new_allergies else "해당없음"
                    
                    master_table_data.append({
                        "완제품코드": p_code,
                        "완제품명": p_name,
                        "기존 알레르기 요약": final_old,
                        "신규 알레르기 요약": final_new
                    })
                
                if master_table_data:
                    master_res_df = pd.DataFrame(master_table_data)
                    st.dataframe(master_res_df, use_container_width=True, hide_index=True)
                    
                    csv_master = convert_df_to_csv(master_res_df)
                    st.download_button("📥 완제품 알레르기 마스터 테이블 다운로드", data=csv_master, file_name="완제품_알레르기_마스터.csv", mime="text/csv")
                else:
                    st.warning("매칭되는 완제품 데이터가 없습니다. 원자재 코드와 BOM 코드가 일치하는지 확인해주세요.")
