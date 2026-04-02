import cv2
import mediapipe as mp
import asyncio
import websockets
import json
import sqlite3
import time
import math
import threading

# --- 스레드 공유 변수 ---
shared_cmd = 'h'
shared_throttle = 0
app_running = True

# ==========================================
# 0. SQLite 데이터베이스 초기화 함수
# ==========================================
def init_db():
    conn = sqlite3.connect('drone_flight_GCS.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY,
            start_time TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flight_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            time_ms INTEGER,
            command TEXT,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id)
        )
    ''')
    conn.commit()
    conn.close()
    print("✅ SQLite 데이터베이스 초기화 완료 (drone_flight_GCS.db)")

# ==========================================
# 1. 로컬 웹소켓 서버 (데이터 양방향 송수신 및 DB 적재)
# ==========================================
async def ws_handler(websocket):
    global shared_cmd, shared_throttle, app_running
    print("🌐 웹 브라우저(HTML)와 연결되었습니다! 데이터 송수신을 시작합니다.")
    
    last_cmd = None
    last_throttle = None
    
    try:
        async def send_loop():
            nonlocal last_cmd, last_throttle
            while app_running:
                if shared_throttle != last_throttle:
                    await websocket.send(f"THR:{shared_throttle}")
                    last_throttle = shared_throttle
                if shared_cmd != last_cmd:
                    await websocket.send(f"CMD:{shared_cmd}")
                    last_cmd = shared_cmd
                await asyncio.sleep(0.05)

        async def recv_loop():
            async for message in websocket:
                try:
                    data = json.loads(message)
                    
                    if data.get('type') == 'LOG_DATA':
                        session_id = data.get('sessionId')
                        logs = data.get('logs')
                        
                        print(f"💾 {len(logs)}개의 비행 로그 수신 중... DB 적재 시작")
                        
                        conn = sqlite3.connect('drone_flight_GCS.db')
                        cursor = conn.cursor()
                        
                        cursor.execute('INSERT OR IGNORE INTO sessions (session_id) VALUES (?)', (session_id,))
                        
                        log_values = [(session_id, log['time'], log['command']) for log in logs]
                        cursor.executemany('INSERT INTO flight_logs (session_id, time_ms, command) VALUES (?, ?, ?)', log_values)
                        
                        conn.commit()
                        conn.close()
                        print(f"✅ DB 적재 완료! (Session ID: {session_id})")
                
                except json.JSONDecodeError:
                    pass

        await asyncio.gather(send_loop(), recv_loop())

    except websockets.exceptions.ConnectionClosed:
        print("🌐 웹 브라우저와의 연결이 끊어졌습니다.")

async def ws_server_main():
    async with websockets.serve(ws_handler, "localhost", 8765):
        await asyncio.Future()

def start_ws_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ws_server_main())

# ==========================================
# 💡 버퍼 딜레이 방지용 실시간 카메라 리더 클래스
# ==========================================
class CameraReader:
    def __init__(self, src=0, width=640, height=480):
        self.cap = cv2.VideoCapture(src)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.ret, self.frame = self.cap.read()
        self.running = True
        
        # 백그라운드 스레드를 열어 프레임을 미친 듯이 읽어들임 (버퍼 비우기)
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while self.running:
            # OpenCV 내부 버퍼에 쌓일 틈 없이 계속 뽑아내어 최신 상태 유지
            ret, frame = self.cap.read()
            if ret:
                self.ret = ret
                self.frame = frame

    def read(self):
        # AI(MediaPipe)가 호출할 때는 무조건 가장 마지막(최신) 프레임 1장만 전달
        return self.ret, self.frame

    def release(self):
        self.running = False
        self.cap.release()

    def isOpened(self):
        return self.cap.isOpened()

# ==========================================
# 2. 비전 인식 (메인 스레드)
# ==========================================
if __name__ == "__main__":
    init_db()

    threading.Thread(target=start_ws_thread, daemon=True).start()

    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles
    hands = mp_hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.7)
    
    WIDTH, HEIGHT = 640, 480
    
    # 기존 cv2.VideoCapture 대신 최신 프레임 강제 추출 클래스 사용
    cap = CameraReader(0, WIDTH, HEIGHT)

    drone_state = 'GROUNDED' 
    current_throttle = 0
    current_cmd = 'h'
    last_state_time = 0
    last_throttle_time = 0

    print("📷 캠 구동 완료. HTML 웹페이지를 열고 'AI 비전 모드'를 켜주세요!")
    font = cv2.FONT_HERSHEY_SIMPLEX

    while cap.isOpened() and app_running:
        success, frame = cap.read()
        if not success: continue
        
        frame = cv2.flip(frame, 1) 
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb_frame)

        left_side_hand = None
        right_side_hand = None

        if results.multi_hand_landmarks:
            valid_hands = []
            for hand_landmarks in results.multi_hand_landmarks:
                mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS,
                                          mp_drawing_styles.get_default_hand_landmarks_style(),
                                          mp_drawing_styles.get_default_hand_connections_style())
                valid_hands.append(hand_landmarks)

            # 중복 인식(고스트 현상) 방지
            if len(valid_hands) == 2:
                h1, h2 = valid_hands[0], valid_hands[1]
                dist = math.hypot(h1.landmark[0].x - h2.landmark[0].x, h1.landmark[0].y - h2.landmark[0].y)
                if dist < 0.05:  
                    valid_hands = [h1]

            # 좌/우 손 확실히 할당
            if len(valid_hands) == 2:
                if valid_hands[0].landmark[8].x < valid_hands[1].landmark[8].x:
                    left_side_hand = valid_hands[0]
                    right_side_hand = valid_hands[1]
                else:
                    left_side_hand = valid_hands[1]
                    right_side_hand = valid_hands[0]
            elif len(valid_hands) == 1:
                if valid_hands[0].landmark[8].x < 0.5:
                    left_side_hand = valid_hands[0]
                else:
                    right_side_hand = valid_hands[0]

        # --- 상태 전환 (왼손/오른손 검지&엄지 완전히 맞대기) ---
        if left_side_hand and right_side_hand:
            # 💡 양손 검지(8번)와 엄지(4번) 사이의 거리 측정
            index_dist = math.hypot(left_side_hand.landmark[8].x - right_side_hand.landmark[8].x,
                                    left_side_hand.landmark[8].y - right_side_hand.landmark[8].y)
            thumb_dist = math.hypot(left_side_hand.landmark[4].x - right_side_hand.landmark[4].x,
                                    left_side_hand.landmark[4].y - right_side_hand.landmark[4].y)

            # 💡 두 손가락이 모두 완전히 맞닿았을 때 (거리 0.05 이하)
            if index_dist < 0.05 and thumb_dist < 0.05 and (time.time() - last_state_time > 2.0):
                if drone_state == 'GROUNDED':
                    drone_state = 'FLYING'
                    current_throttle = 4
                    current_cmd = 'h'
                    last_state_time = time.time()
                elif drone_state == 'FLYING':
                    drone_state = 'LANDING'
                    last_state_time = time.time()

        # --- 비행 제어 로직 ---
        if drone_state == 'LANDING':
            if time.time() - last_throttle_time > 0.5:
                current_throttle -= 1
                if current_throttle <= 0:
                    current_throttle = 0
                    drone_state = 'GROUNDED'
                last_throttle_time = time.time()

        elif drone_state == 'FLYING':
            cv2.line(frame, (320, 0), (320, 480), (255, 255, 255), 2)
            cv2.rectangle(frame, (100, 180), (220, 300), (0, 255, 0), 2)
            cv2.rectangle(frame, (420, 180), (540, 300), (0, 255, 0), 2)
            
            new_cmd = 'h'
            
            # 방향 (왼손)
            if left_side_hand:
                ix = int(left_side_hand.landmark[8].x * WIDTH)
                iy = int(left_side_hand.landmark[8].y * HEIGHT)
                cv2.circle(frame, (ix, iy), 20, (255, 0, 0), -1)

                dx = ix - 160 
                dy = iy - 240 
                if abs(dx) < 60 and abs(dy) < 60: new_cmd = 'h'
                elif abs(dx) > abs(dy):
                    if dx < 0: new_cmd = 'a'
                    else: new_cmd = 'd'     
                else:
                    if dy < 0: new_cmd = 'w'
                    else: new_cmd = 's'     
            current_cmd = new_cmd

            # 스로틀 (오른손)
            if right_side_hand:
                ix = int(right_side_hand.landmark[8].x * WIDTH)
                iy = int(right_side_hand.landmark[8].y * HEIGHT)
                cv2.circle(frame, (ix, iy), 20, (0, 0, 255), -1)

                dy = iy - 240 
                if abs(dy) > 60 and (time.time() - last_throttle_time > 0.4):
                    if dy < 0: current_throttle = min(9, current_throttle + 1)
                    else: current_throttle = max(0, current_throttle - 1)
                    last_throttle_time = time.time()

        shared_cmd = current_cmd
        shared_throttle = current_throttle

        cv2.putText(frame, f"STATE: {drone_state}", (20, 40), font, 1.0, (0, 255, 255), 3)
        if drone_state == 'FLYING':
            cv2.putText(frame, f"CMD: {current_cmd}", (20, 80), font, 1.0, (255, 0, 0), 3)
            cv2.putText(frame, f"THR: {current_throttle}", (500, 80), font, 1.0, (0, 0, 255), 3)

        cv2.imshow('Drone Virtual Joypad', frame)
        if cv2.waitKey(1) & 0xFF == 27: 
            app_running = False
            break

    cap.release()
    cv2.destroyAllWindows()
    hands.close()
