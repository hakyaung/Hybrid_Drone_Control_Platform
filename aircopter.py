import socket
import time

# ESP32-CAM의 IP 주소를 입력하세요 (공유기 설정이나 아두이노 시리얼 모니터에서 확인 가능)
ESP32_IP = '192.168.35.93' 
PORT = 8080

# 소켓 연결
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect((ESP32_IP, PORT))

try:
    print("드론과 연결되었습니다. 조종을 시작합니다. (종료: q)")
    while True:
        cmd = input("명령 입력 (0~9 스로틀, a/d 좌우, s 수평, x 정지): ")
        
        if cmd == 'q':
            break
            
        # 입력한 명령어를 ESP32-CAM으로 전송 (utf-8 인코딩)
        client_socket.send(cmd.encode('utf-8'))
        time.sleep(0.1)

finally:
    client_socket.close()
    print("연결 종료")
