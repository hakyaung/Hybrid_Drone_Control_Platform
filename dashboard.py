import streamlit as st
import pandas as pd
import sqlite3
import matplotlib.pyplot as plt
from datetime import datetime
import os

# --- 대시보드 설정 ---
st.set_page_config(page_title="하이브리드 드론 GCS 자가 평가 대시보드", page_icon="🛸", layout="wide")

st.title("🚁 하이브리드 드론 GCS 비행 성능 리포트")
st.markdown("---")

# --- 데이터 로드 함수 ---
def load_db_sessions():
    if not os.path.exists('drone_flight_GCS.db'):
        return pd.DataFrame()
    conn = sqlite3.connect('drone_flight_GCS.db')
    try:
        df_sessions = pd.read_sql_query("SELECT * FROM sessions ORDER BY session_id DESC", conn)
    except:
        df_sessions = pd.DataFrame()
    conn.close()
    return df_sessions

def load_session_logs(session_id):
    conn = sqlite3.connect('drone_flight_GCS.db')
    query = f"SELECT time_ms, command FROM flight_logs WHERE session_id = {session_id} ORDER BY time_ms"
    df_logs = pd.read_sql_query(query, conn)
    conn.close()
    return df_logs

# --- 메인 사이드바 (데이터 소스 선택) ---
data_source = st.sidebar.radio("🗂️ 데이터 가져오기 방식", ["SQLite DB 로드", "CSV 파일 업로드"])

df_logs = pd.DataFrame()
selected_session_label = ""

# 1. DB에서 가져오기
if data_source == "SQLite DB 로드":
    df_sessions = load_db_sessions()
    if df_sessions.empty:
        st.sidebar.warning("📊 아직 저장된 DB 데이터가 없습니다. CSV 업로드를 이용해주세요.")
    else:
        session_options = df_sessions['session_id'].tolist()
        session_labels = [datetime.fromtimestamp(sid/1000).strftime('%Y-%m-%d %H:%M:%S') for sid in session_options]
        
        selected_session_label = st.sidebar.selectbox("📅 비행 세션 선택", session_labels)
        selected_session_id = session_options[session_labels.index(selected_session_label)]
        df_logs = load_session_logs(selected_session_id)

# 2. CSV 업로드로 가져오기 (파이썬 없이 비행했을 때 사용)
else:
    uploaded_file = st.sidebar.file_uploader("HTML에서 다운받은 CSV 첨부", type=['csv'])
    if uploaded_file is not None:
        df_logs = pd.read_csv(uploaded_file)
        selected_session_label = "업로드된 수동 비행 로그 (CSV)"
        
        # 헤더 대소문자 예외 처리
        df_logs.columns = [col.lower() for col in df_logs.columns]

# --- 메인 대시보드 로직 ---
if not df_logs.empty:
    df_logs['time_s'] = df_logs['time_ms'] / 1000.0

    # 💡 신규 기능: u, j를 포함한 명령어 카테고리화
    def categorize_command(cmd):
        cmd = str(cmd).lower()
        if cmd.isdigit() or cmd in ['u', 'j']: return 'Throttle'
        elif cmd in ['w', 's']: return 'Pitch'
        elif cmd in ['a', 'd']: return 'Roll'
        elif cmd in ['q', 'e']: return 'Yaw'
        elif cmd == 'h': return 'Hover'
        else: return 'System'

    df_logs['Category'] = df_logs['command'].apply(categorize_command)

    # --- GCS 자가 평가 지표 계산 ---
    st.subheader(f"📊 {selected_session_label} 평가 지표")
    col1, col2, col3, col4 = st.columns(4)
    
    total_time = (df_logs['time_s'].iloc[-1] - df_logs['time_s'].iloc[0]) if len(df_logs) > 1 else 0
    total_cmds = len(df_logs)
    cmd_per_sec = total_cmds / total_time if total_time > 0 else 0
    
    col1.metric("⏱️ 총 비행 시간", f"{total_time:.1f} 초")
    col2.metric("🔢 총 명령 발생 수", f"{total_cmds} 개")
    col3.metric("📈 초당 명령 수 (포화도)", f"{cmd_per_sec:.2f} cmd/s")

    # 💡 신규 기능: 스로틀(u, j) 누적 계산 처리
    throttle_logs = df_logs[df_logs['Category'] == 'Throttle'].copy()
    avg_throttle = "N/A"
    
    if not throttle_logs.empty:
        current_thr = 0
        abs_throttle_list = []
        
        for c in throttle_logs['command']:
            c = str(c).lower()
            if c.isdigit():
                current_thr = int(c)
            elif c == 'u':
                current_thr = min(9, current_thr + 1)
            elif c == 'j':
                current_thr = max(0, current_thr - 1)
            abs_throttle_list.append(current_thr)
            
        throttle_logs['abs_throttle'] = abs_throttle_list
        avg_throttle = sum(abs_throttle_list) / len(abs_throttle_list)
        col4.metric("⚙️ 평균 스로틀 파워", f"{avg_throttle:.1f}")
    else:
        col4.metric("⚙️ 평균 스로틀 파워", "N/A")

    st.markdown("---")

    # 1. 조종 패턴 타임라인 시각화
    st.subheader("🎵 비행 조종 패턴 타임라인 분석")
    
    plt.style.use('dark_background')
    plt.rcParams['font.family'] = 'Malgun Gothic'
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, ax = plt.subplots(figsize=(12, 5))
    colors = {'Throttle': 'cyan', 'Pitch': 'lime', 'Roll': 'magenta', 'Yaw': 'orange', 'Hover': 'yellow', 'System': 'white'}
    categories = ['Throttle', 'Pitch', 'Roll', 'Yaw', 'Hover'] 

    for cat in categories:
        subset = df_logs[df_logs['Category'] == cat]
        if not subset.empty:
            ax.scatter(subset['time_s'], subset['Category'], label=cat, color=colors[cat], s=100, alpha=0.8, edgecolors='w')

    ax.set_title('🚁 비행 축별 조종 로그 타임라인', fontsize=16, fontweight='bold', pad=20)
    ax.set_xlabel('시간 경과 (초)', fontsize=12)
    ax.set_ylabel('조종 명령 카테고리', fontsize=12)
    ax.grid(True, axis='x', linestyle='--', alpha=0.3)
    ax.set_yticks(categories)
    fig.tight_layout()
    st.pyplot(fig)

    # 2. 하단 상세 분석
    col5, col6 = st.columns([1, 2])
    
    with col5:
        st.subheader("📊 조종 축별 빈도 비율")
        cmd_counts = df_logs['Category'].value_counts()
        flight_cmds = cmd_counts.reindex(['Throttle', 'Pitch', 'Roll', 'Yaw', 'Hover']).dropna()
        
        if not flight_cmds.empty:
            fig2, ax2 = plt.subplots(figsize=(6, 6))
            ax2.pie(flight_cmds, labels=flight_cmds.index, autopct='%1.1f%%', 
                    startangle=140, colors=[colors[c] for c in flight_cmds.index],
                    wedgeprops={'edgecolor': 'w'}, textprops={'color': 'w'})
            ax2.axis('equal')  
            fig2.tight_layout()
            st.pyplot(fig2)

    with col6:
        st.subheader("⚙️ 스로틀 고도 변동 추이 (U/J 반영)")
        if not throttle_logs.empty:
            # 시간순으로 정렬된 절대 스로틀 값 꺾은선 그래프
            st.line_chart(throttle_logs.set_index('time_s')['abs_throttle'], height=300)
        else:
            st.warning("스로틀 조작 데이터가 없습니다.")
else:
    st.info("👈 좌측 사이드바에서 분석할 비행 데이터를 선택하거나 업로드해주세요.")

st.markdown("---")
st.caption("Drone Hybrid GCS - Self-Evaluation Dashboard v1.1 (Supports CSV & Pro Control)")
