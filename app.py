# [탭 1] 한글라벨 스캔 및 저장
with tab1:
    st.markdown("### 신규 원자재 라벨 업로드")
    uploaded_file = st.file_uploader("한글표시사항 라벨 사진을 업로드하세요 (JPG, PNG)", type=['jpg', 'jpeg', 'png'])

    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption='업로드된 라벨 이미지', width=400)
        
        # 💡 신규 추가: 코드 수동 입력란
        manual_code = st.text_input("📦 원자재 코드 번호를 입력하세요 (예: 10356):", help="라벨 사진에 코드가 없는 경우 직접 입력해야 DB에 반영됩니다.")
        
        if st.button("이미지 분석 및 스프레드시트 저장", type="primary"):
            if not manual_code:
                st.warning("⚠️ 원자재 코드 번호를 먼저 입력해 주세요!")
            else:
                with st.spinner("AI가 라벨을 판독 중입니다..."):
                    parsed_data, error = extract_label_data(image)
                    
                    if error:
                        st.error(error)
                    else:
                        st.success("데이터 추출 성공! 드라이브 및 시트에 저장을 시작합니다.")
                        st.json(parsed_data)
                        
                        current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        file_name = f"원자재라벨_{parsed_data.get('원재료의 제품명', '미상')}_{current_time}.jpg"
                        image_bytes = uploaded_file.getvalue()
                        
                        drive_link = upload_image_to_drive(image_bytes, file_name)
                        
                        # 💡 수정: AI 추출 코드 대신 '수동 입력한 코드(manual_code)'를 맨 앞에 강제 삽입
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
