import pandas as pd
import matplotlib.pyplot as plt

# 1. 데이터 로드 및 전처리
# HTML 파일에서 다운로드한 CSV 파일과 같은 폴더에 이 파이썬 파일을 두고 실행하세요.
df = pd.read_csv('flight_log.csv')

# Time_ms를 초(s) 단위로 변환
df['Time_s'] = df['Time_ms'] / 1000.0

# 💡 명령어 그룹화 (새로 추가된 q, e 반영)
def categorize_command(cmd):
    if str(cmd).isdigit():
        return 'Throttle (Altitude)'
    elif cmd in ['w', 's']:
        return 'Pitch (Forward/Backward)'
    elif cmd in ['a', 'd']:
        return 'Roll (Left/Right)'
    elif cmd in ['q', 'e']:
        return 'Yaw (Rotate Left/Right)' # 제자리 회전 추가
    elif cmd == 'h':
        return 'Hover / Balance'
    else:
        return 'System'

df['Category'] = df['Command'].apply(categorize_command)

# 2. 그래프 시각화 설정
plt.style.use('dark_background') # 다크 테마 적용
plt.rcParams['font.family'] = 'Malgun Gothic' # Windows 한글 폰트 (맥은 'AppleGothic')
plt.rcParams['axes.unicode_minus'] = False
plt.figure(figsize=(12, 6))

# 3. 산점도(Scatter plot) 형태로 타임라인 시각화
# Yaw 명령어를 위한 주황색(orange) 추가
colors = {
    'Throttle (Altitude)': 'cyan', 
    'Pitch (Forward/Backward)': 'lime', 
    'Roll (Left/Right)': 'magenta', 
    'Yaw (Rotate Left/Right)': 'orange',
    'Hover / Balance': 'yellow', 
    'System': 'white'
}

for category, color in colors.items():
    # 해당 카테고리의 데이터가 있을 때만 그리기
    subset = df[df['Category'] == category]
    if not subset.empty:
        plt.scatter(subset['Time_s'], subset['Category'], 
                    label=category, color=color, s=100, alpha=0.8, edgecolors='w')
        
        # 명령어 텍스트 마커 추가 (어떤 키를 눌렀는지 표시)
        for idx, row in subset.iterrows():
            plt.text(row['Time_s'], row['Category'], f" {row['Command']}", 
                     fontsize=9, verticalalignment='bottom', horizontalalignment='left')

plt.title('🚁 하이브리드 드론 비행 조종 로그 분석', fontsize=16, fontweight='bold', pad=20)
plt.xlabel('시간 경과 (초)', fontsize=12)
plt.ylabel('조종 명령 종류', fontsize=12)
plt.grid(True, axis='x', linestyle='--', alpha=0.3)
plt.tight_layout()

# 그래프 출력
plt.show()
