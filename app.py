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

ADMIN_PASSWORD = "yonsei1234"

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

# 💡 수정: 승인 시 코드를 확정하고 검증 상태를 업데이트하는 함수
def approve_and_update_row(row_index_str, final_code, status_text, result_text):
    try:
        creds = get_google_creds()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.sheet1
        
        # A열(1) = 코드, L열(12) = 검증상태, M열(13) = 검증결과
        # row_index_str은 엑셀 기준 실제 행 번호
        worksheet.update_acell(f'A{row_index_str}', final_code)
        worksheet.update_acell(f'L{row_index_str}', status_text)
        worksheet.update_acell(f'M{row_index_str}', result_text)
        return True
    except Exception as e:
        return str(e)

def load_sheet_data():
    try:
        creds = get_google_creds()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.sheet1
        # 행 번호 추적을 위해 enumerate 사용하지 않고 원본 데이터 로드
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
# 3. AI 교차 검증 및 코드 추천 로직
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
        components.iframe(iframe_src, height=600, scrolling=True)
    else:
        st.markdown(f"[링크 직접 열기]({img_url})")

# ==========================================
# 4. 화면 라우팅 (관리자 vs 협력업체)
# ==========================================
with st.sidebar:
    st.markdown("### 🔐 식품안전팀 관리자 로그인")
    user_pw = st.text_input("접속 암호를 입력하세요:", type="password")
    
is_admin = (user_pw == ADMIN_PASSWORD)

if not is_admin:
    # ----------------------------------------------------
    # [프론트엔드] 협력업체용 라벨 등록 폼 (코드 입력란 제거)
    # ----------------------------------------------------
    st.title("🤝 원자재 라벨 및 정보 등록 시스템")
    st.info("정확한 품질관리를 위해 사업자등록증 상의 정보와 라벨 원본 내용을 똑같이 기재해 주십시오.")
    
    with st.form("vendor_form"):
        col1, col2 = st.columns(2)
        with col1:
            # 💡 수정: 원자재 코드 입력란 제거
            v_name = st.text_input("🏷️ 제품명 (라벨 표기 기준, 필수)")
            v_type = st.text_input("분류 식품유형 (필수)")
            v_maker = st.text_input("🏭 제조원 또는 판매원 (필수)")
        with col2:
            v_origin = st.text_input("🌍 원산지")
            v_old_allergy = st.text_input("⚠️ 기존 알레르기 물질 (없으면 '해당없음')")
            
            st.markdown("🚨 **신규 알레르기 유발물질 포함 여부 (필수 체크)**")
            v_new_allergy = st.multiselect(
                "해당되는 물질을 모두 선택하세요:", 
                ["참깨", "들깨", "아몬드", "캐슈넛", "해당없음"]
            )
            
        v_ingredients = st.text_area("📝 원재료명 및 함량 (라벨에 적힌 모든 성분을 쉼표로 구분하여 기재)")
        
        st.markdown("---")
        uploaded_file = st.file_uploader("📸 원본 라벨 첨부 (JPG, PNG, PDF 필수)", type=['jpg', 'jpeg', 'png', 'pdf'])
        
        submit_btn = st.form_submit_button("📤 데이터 제출하기", type="primary")
        
        if submit_btn:
            if not v_name or not v_type or not v_ingredients or not uploaded_file or not v_maker:
                st.error("❌ 필수 항목(제품명, 제조원, 식품유형, 원재료명, 파일 첨부)을 모두 입력해 주세요.")
            elif not v_new_allergy:
                st.error("❌ 신규 알레르기 물질 포함 여부를 반드시 체크해 주세요. (없을 경우 '해당없음' 선택)")
            elif "해당없음" in v_new_allergy and len(v_new_allergy) > 1:
                st.error("❌ '해당없음'과 다른 물질을 동시에 선택할 수 없습니다.")
            else:
                with st.spinner("서버에 안전하게 전송 중입니다..."):
                    file_bytes = uploaded_file.getvalue()
                    file_mime_type = uploaded_file.type
                    current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    ext = ".pdf" if "pdf" in file_mime_type.lower() else ".jpg"
                    file_name = f"업체제출_{v_name}_{current_time}{ext}"
                    
                    drive_link, file_id = upload_file_to_drive(file_bytes, file_name, file_mime_type)
                    
                    if drive_link and file_id:
                        # 💡 코드는 비워둔 채("") DB 저장
                        row_data = [
                            "", v_name, v_type, v_ingredients, v_origin, v_maker, 
                            v_old_allergy, ", ".join(v_new_allergy), current_time, 
                            drive_link, file_id, "대기중", "검증전"
                        ]
                        res = append_data_to_sheet(row_data)
                        if res == True:
                            st.success(f"🎉 제출이 완료되었습니다! (제품명: {v_name}) 감사합니다.")
                        else:
                            st.error(f"저장 중 에러가 발생했습니다: {res}")
                    else:
                        st.error("파일 업로드에 실패했습니다. 관리자에게 문의하세요.")

else:
    # ----------------------------------------------------
    # [백엔드] 식품안전팀 관리자 대시보드
    # ----------------------------------------------------
    st.title("🛡️ 식품안전팀 품질관리 통합 대시보드")
    
    admin_tab1, admin_tab2, admin_tab3, admin_tab4 = st.tabs([
        "📊 제출 현황판", "🤖 AI 교차 검증 및 코드 승인", "🔍 등록 DB 검색", "🚨 배합비 역추적"
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
            # 승인되어 코드가 확정된 건들만 추림
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
        st.markdown("### 🤖 대기열 검증 및 마스터 코드 확정")
        st.caption("AI가 원본 라벨을 대조하고, 사내 마스터 명단에서 가장 일치하는 원자재 코드를 추천합니다. 관리자가 최종 승인하면 DB에 코드가 부여됩니다.")
        
        if not df.empty:
            # 상태가 '대기중'인 행의 원본 엑셀 인덱스를 유지하기 위해 reset_index 적용
            pending_df = df[df['검증상태'] == '대기중'].reset_index()
            
            if pending_df.empty:
                st.success("🎉 현재 대기 중인 검증 건이 없습니다. 모두 승인되었습니다.")
            else:
                st.warning(f"⚠️ 현재 {len(pending_df)}건의 라벨이 검증 및 승인 대기 중입니다.")
                
                for _, row in pending_df.iterrows():
                    # 엑셀은 1부터 시작하므로 index + 2 (헤더 포함)
                    excel_row_idx = row['index'] + 2 
                    name = row.get('제품명', '')
                    file_id = row.get('파일ID', '')
                    submit_time = row.get('제출일시', '')
                    
                    with st.expander(f"📦 [대기중] {name} - ({submit_time})"):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown("**[업체 제출 정보]**")
                            st.write(f"- **제품명**: {row.get('제품명')}")
                            st.write(f"- **제조원**: {row.get('제조원')}")
                            st.write(f"- **원재료명**: {row.get('원재료명(한글표시사항)')}")
                            st.write(f"- **기존/신규 알레르기**: {row.get('기존알레르기')} / {row.get('신규알레르기')}")
                            
                        with col_b:
                            # 💡 1단계: AI 분석 버튼
                            if st.button(f"🔍 AI 교차검증 및 매칭 분석", key=f"btn_ai_{excel_row_idx}"):
                                if file_id:
                                    with st.spinner("드라이브 라벨 분석 및 마스터 코드 매칭 중..."):
                                        f_bytes, mime = download_file_from_drive(file_id)
                                        if f_bytes:
                                            result = verify_with_ai(f_bytes, mime, row.to_dict(), master_json)
                                            
                                            # 결과에서 추천 코드 파싱
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
                            
                            # AI 분석 결과가 세션에 있으면 표시 및 승인 폼 렌더링
                            if f"ai_result_{excel_row_idx}" in st.session_state:
                                st.markdown("### 📋 AI 판독 및 매칭 결과")
                                st.info(st.session_state[f"ai_result_{excel_row_idx}"])
                                
                                # 💡 2단계: 관리자 최종 승인 폼
                                st.markdown("---")
                                final_code = st.text_input(
                                    "최종 매핑할 '원자재 코드' 입력 (AI 추천 코드가 자동 기입됨):", 
                                    value=st.session_state[f"rec_code_{excel_row_idx}"], 
                                    key=f"final_code_{excel_row_idx}"
                                )
                                
                                if st.button(f"✅ 코드 '{final_code}'로 최종 승인 및 DB 저장", type="primary", key=f"btn_approve_{excel_row_idx}"):
                                    if final_code and final_code != "없음":
                                        ai_full_text = st.session_state[f"ai_result_{excel_row_idx}"]
                                        res = approve_and_update_row(excel_row_idx, final_code, "승인완료", ai_full_text)
                                        
                                        if res == True:
                                            st.success("데이터베이스에 코드가 정상 확정되었습니다! (새로고침 시 대기열에서 사라집니다)")
                                        else:
                                            st.error(f"저장 에러: {res}")
                                    else:
                                        st.error("유효한 원자재 코드를 입력해야 승인할 수 있습니다.")
                        
                        st.markdown("---")
                        img_url = row.get('이미지링크', '')
                        if img_url:
                            render_inline_viewer(img_url)
        else:
            st.info("등록된 데이터가 없습니다.")

    # ------------------ [탭 3: 기존 DB 검색] ------------------
    with admin_tab3:
        st.markdown("### 🔍 승인된 원자재 DB 검색")
        if not df.empty:
            approved_df = df[df['검증상태'] == '승인완료']
            search_name = st.text_input("🔍 제품명 또는 코드 검색:")
            
            if search_name:
                approved_df = approved_df[
                    approved_df['제품명'].astype(str).str.contains(search_name, na=False) |
                    approved_df['코드'].astype(str).str.contains(search_name, na=False)
                ]
            
            display_cols = ['코드', '제품명', '원재료명(한글표시사항)', '제조원', '신규알레르기', '검증결과']
            st.dataframe(approved_df[display_cols], use_container_width=True, hide_index=True)
        else:
            st.info("데이터가 없습니다.")

    # ------------------ [탭 4: 배합비 역추적기] ------------------
    with admin_tab4:
        st.markdown("### 🚨 잠복 알레르기 및 완제품(BOM) 역추적")
        bom_df = load_bom_data()
        
        if not df.empty:
            # 확정된 코드만 역추적 가능
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
                    else:
                        st.info("BOM 데이터가 없습니다.")
