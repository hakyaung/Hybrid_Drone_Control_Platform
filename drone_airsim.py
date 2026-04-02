import airsim
import numpy as np
import cv2
import mediapipe as mp
import time
import math
import threading

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


def main():
    # ==========================================
    # 1. AirSim 시뮬레이터 초기화
    # ==========================================
    client = airsim.MultirotorClient()
    client.confirmConnection()
    client.enableApiControl(True)
    client.armDisarm(True)
    
    # ==========================================
    # 2. MediaPipe 비전 및 카메라 초기화
    # ==========================================
    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles
    hands = mp_hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.7)
    
    WIDTH, HEIGHT = 640, 480
    # 기존 cv2.VideoCapture 대신 최신 프레임 강제 추출 클래스 사용
    cap = CameraReader(0, WIDTH, HEIGHT)

    # ==========================================
    # 3. 상태 및 제어 변수
    # ==========================================
    control_mode = 'MANUAL'  # 'MANUAL' 또는 'VISION'
    drone_state = 'GROUNDED' 
    
    # 조종 명령 변수
    current_cmd = 'h'
    current_throttle = 0  # 0 ~ 9
    
    last_state_time = time.time()
    last_throttle_time = time.time()

    # 드론 물리 제어 기본값
    SPEED_MAX = 3.0       # 최대 이동 속도 (m/s)
    YAW_RATE_MAX = 40.0   # 최대 회전 속도 (deg/s)

    print("📷 카메라 및 AirSim 연동 완료!")
    print("⌨️ 조종창(OpenCV 창)을 클릭하고 키보드를 입력하세요.")
    print("   - [M] 키: 수동(MANUAL) / 비전(VISION) 모드 전환")
    print("   - [ESC] 키: 프로그램 종료")
    
    font = cv2.FONT_HERSHEY_SIMPLEX

    while cap.isOpened():
        success, frame = cap.read()
        if not success: continue
        
        frame = cv2.flip(frame, 1) 
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb_frame)

        # ------------------------------------------
        # [A] 키보드 입력 처리 (수동 모드 / 모드 전환)
        # ------------------------------------------
        key = cv2.waitKey(1) & 0xFF
        if key == 27: # ESC 키
            break
        elif key == ord('m'): # 모드 전환
            control_mode = 'VISION' if control_mode == 'MANUAL' else 'MANUAL'
            print(f"🔄 제어 모드 변경: {control_mode}")

        if control_mode == 'MANUAL':
            # 1~9 숫자키 (스로틀 베이스 설정)
            if ord('0') <= key <= ord('9'):
                current_throttle = key - ord('0')
            # 방향 및 미세 스로틀 (w, a, s, d, q, e, u, j, h)
            elif key in [ord('w'), ord('a'), ord('s'), ord('d'), ord('q'), ord('e'), ord('h')]:
                current_cmd = chr(key)
            elif key == ord('u'):
                current_throttle = min(9, current_throttle + 1)
            elif key == ord('j'):
                current_throttle = max(0, current_throttle - 1)
            
            # 이륙/착륙 임시 처리 (수동 모드용)
            if drone_state == 'GROUNDED' and current_throttle > 0:
                drone_state = 'FLYING'
                client.takeoffAsync().join()
            elif drone_state == 'FLYING' and current_throttle == 0:
                drone_state = 'LANDING'

        # ------------------------------------------
        # [B] AI 비전 인식 처리 및 화면 분할 UI
        # ------------------------------------------
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

        if control_mode == 'VISION':
            # 1. 상태 전환 (양손 검지와 엄지 완전히 맞대기)
            if left_side_hand and right_side_hand:
                index_dist = math.hypot(left_side_hand.landmark[8].x - right_side_hand.landmark[8].x,
                                        left_side_hand.landmark[8].y - right_side_hand.landmark[8].y)
                thumb_dist = math.hypot(left_side_hand.landmark[4].x - right_side_hand.landmark[4].x,
                                        left_side_hand.landmark[4].y - right_side_hand.landmark[4].y)

                if index_dist < 0.05 and thumb_dist < 0.05 and (time.time() - last_state_time > 2.0):
                    if drone_state == 'GROUNDED':
                        drone_state = 'FLYING'
                        current_throttle = 4
                        current_cmd = 'h'
                        client.takeoffAsync().join() # AirSim 이륙
                        last_state_time = time.time()
                    
                    elif drone_state == 'FLYING':
                        drone_state = 'LANDING'
                        last_state_time = time.time()

            # 2. 비행 제어 로직 (방향 및 스로틀)
            if drone_state == 'LANDING':
                if time.time() - last_throttle_time > 0.5:
                    current_throttle -= 1
                    if current_throttle <= 0:
                        current_throttle = 0
                        drone_state = 'GROUNDED'
                    last_throttle_time = time.time()

            elif drone_state == 'FLYING':
                # 비전 모드 + 비행 중일 때 화면 분할 및 제어 영역 표시
                cv2.line(frame, (320, 0), (320, 480), (255, 255, 255), 2)
                cv2.rectangle(frame, (100, 180), (220, 300), (0, 255, 0), 2)
                cv2.rectangle(frame, (420, 180), (540, 300), (0, 255, 0), 2)
                
                new_cmd = 'h'
                
                # 왼쪽 손 (방향 제어)
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

                # 오른쪽 손 (스로틀 제어)
                if right_side_hand:
                    ix = int(right_side_hand.landmark[8].x * WIDTH)
                    iy = int(right_side_hand.landmark[8].y * HEIGHT)
                    cv2.circle(frame, (ix, iy), 20, (0, 0, 255), -1)

                    dy = iy - 240 
                    if abs(dy) > 60 and (time.time() - last_throttle_time > 0.4):
                        if dy < 0: current_throttle = min(9, current_throttle + 1)
                        else: current_throttle = max(0, current_throttle - 1)
                        last_throttle_time = time.time()

        # ------------------------------------------
        # [C] AirSim 드론 이동 명령 적용 (모드 공통)
        # ------------------------------------------
        if drone_state == 'LANDING':
            client.landAsync()
                
        elif drone_state == 'FLYING':
            vx, vy, vz, yaw = 0.0, 0.0, 0.0, 0.0
            
            # 스로틀 변환 (AirSim Z축은 아래가 양수이므로, 위로 가려면 음수)
            vz = -1.0 * (current_throttle - 4)

            # 방향 변환
            if current_cmd == 'w': vx = SPEED_MAX
            elif current_cmd == 's': vx = -SPEED_MAX
            elif current_cmd == 'a': vy = -SPEED_MAX
            elif current_cmd == 'd': vy = SPEED_MAX
            elif current_cmd == 'q': yaw = -YAW_RATE_MAX
            elif current_cmd == 'e': yaw = YAW_RATE_MAX
            elif current_cmd == 'h': 
                vx, vy, yaw = 0.0, 0.0, 0.0
                if current_throttle == 4:
                    client.hoverAsync()

            # 물리 엔진에 속도 명령 전달 (0.1초 동안 유지)
            yaw_mode = airsim.YawMode(is_rate=True, yaw_or_rate=yaw)
            client.moveByVelocityBodyFrameAsync(vx, vy, vz, duration=0.1, yaw_mode=yaw_mode)

        # ------------------------------------------
        # [D] 화면 UI 출력
        # ------------------------------------------
        cv2.putText(frame, f"MODE: {control_mode}", (20, 40), font, 1.0, (255, 0, 255), 3)
        cv2.putText(frame, f"STATE: {drone_state}", (20, 80), font, 1.0, (0, 255, 255), 3)
        if drone_state == 'FLYING':
            cv2.putText(frame, f"CMD: {current_cmd.upper()}", (20, 120), font, 1.0, (255, 0, 0), 3)
            cv2.putText(frame, f"THR: {current_throttle}", (500, 120), font, 1.0, (0, 0, 255), 3)

        cv2.imshow('AirSim Hybrid Control Pro', frame)

    # 종료 시 정리
    print("착륙 및 시스템 종료 중...")
    client.landAsync().join()
    client.armDisarm(False)
    client.enableApiControl(False)
    cap.release()
    cv2.destroyAllWindows()
    hands.close()

if __name__ == "__main__":
    main()
