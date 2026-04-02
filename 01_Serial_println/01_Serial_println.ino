#include <Wire.h>

void setup(){
  Serial1.begin(115200);
  Serial.begin(115200);

  Wire.begin();
  Wire.setClock(400000);

  Wire.beginTransmission(0x68);
  Wire.write(0x6b);
  Wire.write(0x0);
  Wire.endTransmission(true);
}

int throttle = 0; 
const unsigned long STICK_RELEASE_TIMEOUT = 1000; 
static unsigned long lastCommandTime = 0;

void loop(){
  // --- [센서 데이터 읽기 및 캘리브레이션] ---
  Wire.beginTransmission(0x68);
  Wire.write(0x3B); 
  Wire.endTransmission(false);
  Wire.requestFrom(0x68, 14, true);
  
  int16_t rawAccX = (int16_t)(Wire.read() << 8 | Wire.read());
  int16_t rawAccY = (int16_t)(Wire.read() << 8 | Wire.read());
  int16_t rawAccZ = (int16_t)(Wire.read() << 8 | Wire.read());
  Wire.read(); Wire.read(); 
  int16_t rawGyX = (int16_t)(Wire.read() << 8 | Wire.read());
  int16_t rawGyY = (int16_t)(Wire.read() << 8 | Wire.read());
  int16_t rawGyZ = (int16_t)(Wire.read() << 8 | Wire.read());

  static int32_t GyXSum = 0, GyYSum = 0, GyZSum=0;
  static int32_t AccXSum = 0, AccYSum = 0, AccZSum=0;
  static double GyXoff = 0.0, GyYoff = 0.0, GyZoff = 0.0;
  static double AccXoff = 0.0, AccYoff = 0.0, AccZoff = 0.0;
  static int cnt_sample = 1000;

  if(cnt_sample > 0){
    GyXSum += rawGyX; GyYSum += rawGyY; GyZSum += rawGyZ;
    AccXSum += rawAccX; AccYSum += rawAccY; AccZSum += rawAccZ;
    cnt_sample--;
    if(cnt_sample == 0){
      GyXoff = GyXSum / 1000.0; GyYoff = GyYSum / 1000.0; GyZoff = GyZSum / 1000.0;
      AccXoff = AccXSum / 1000.0; AccYoff = AccYSum / 1000.0;
      AccZoff = (AccZSum / 1000.0) - 16384.0;
      int readyPins[] = {6, 10, 9, 5};
      for(int i = 0; i < 4; i++) {
        analogWrite(readyPins[i], 25); delay(150); analogWrite(readyPins[i], 0); delay(50);                    
      }
    }
    delay(1); return;
  }

  // --- [각도 계산 및 상보 필터] ---
  double GyXD = rawGyX - GyXoff;
  double GyYD = rawGyY - GyYoff;
  double GyZD = rawGyZ - GyZoff;
  double GyXR = GyXD / 131.0;
  double GyYR = GyYD / 131.0;
  double GyZR = GyZD / 131.0;
  double accAngleX = atan2(rawAccY - AccYoff, rawAccZ - AccZoff) * 180.0 / PI;
  double accAngleY = atan2(-(rawAccX - AccXoff), rawAccZ - AccZoff) * 180.0 / PI;

  static unsigned long t_prev = 0;
  unsigned long t_now = micros();
  if(t_prev == 0) t_prev = t_now; 
  double dt = (t_now - t_prev)/1000000.0;
  t_prev = t_now;
  if (dt <= 0.0 || dt > 0.02) dt = 0.004; 

  static double AngleX = 0.0, AngleY = 0.0, AngleZ = 0.0;
  AngleX = 0.98 * (AngleX + GyXR * dt) + 0.02 * accAngleX;
  AngleY = 0.98 * (AngleY + GyYR * dt) + 0.02 * accAngleY;
  AngleZ += GyZR * dt;

  if(throttle == 0) AngleX = AngleY = AngleZ = 0.0;

  static double tAngleX = 0.0, tAngleY = 0.0, tAngleZ = 0.0;
  double trimX = +8.0; 
  double trimY = -3.0; 

  if(throttle > 0 && (millis() - lastCommandTime > STICK_RELEASE_TIMEOUT)){
    tAngleX = 0.0; tAngleY = 0.0;
  }

  // --- [입력 처리] ---
  auto handleInput = [&](char userInput) {
    if(userInput == '0'){ throttle = 0; }
    else if(userInput >= '1' && userInput <= '9'){ throttle = (userInput - '0') * 25; }
    else if(userInput == 'u'){ throttle = constrain(throttle + 2, 0, 250); }
    else if(userInput == 'j'){ throttle = constrain(throttle - 2, 0, 250); }
    else {
      lastCommandTime = millis(); 
      if(userInput == 'w'){ tAngleY = 15.0; } 
      else if(userInput == 's'){ tAngleY = -30.0; } 
      else if(userInput == 'a'){ tAngleX = -15.0; } 
      else if(userInput == 'd'){ tAngleX = 20.0; } 
      else if(userInput == 'q'){ tAngleZ -= 10.0; } 
      else if(userInput == 'e'){ tAngleZ += 10.0; } 
      else if(userInput == 'h'){ 
        // 💡 [핵심 수정] 조종기에서 손을 떼었을 때 목표 각도만 0으로 되돌립니다.
        // 현재 센서 각도(AngleX, Y, Z)는 강제 초기화하지 않아 물리적인 쏠림(Drift)을 방지합니다.
        tAngleX = 0.0; tAngleY = 0.0; tAngleZ = 0.0; 
      }
    }
  };

  if(Serial1.available() > 0) { while(Serial1.available() > 0) handleInput(Serial1.read()); }
  if(Serial.available() > 0) { while(Serial.available() > 0) handleInput(Serial.read()); }

  // --- [핵심 수정: 구간별 스로틀 펌핑 로직] ---
  int activeThrottle = throttle;
  if (throttle >= 150) { 
    if ((millis() / 1500) % 2 == 0) activeThrottle = throttle;
    else activeThrottle = throttle - 5; 
  } 
  else if (throttle >= 75) { 
    if ((millis() / 1500) % 2 == 0) activeThrottle = throttle;
    else activeThrottle = throttle + 25; 
  }

  // --- [PID 제어 및 출력] ---
  double kp = 1.8; double kd = 1.2; 
  double eAngleX = (tAngleX + trimX) - AngleX;
  double eAngleY = (tAngleY + trimY) - AngleY;
  double eAngleZ = tAngleZ - AngleZ;
  double BalX = (kp * eAngleX) + (kd * -GyXR);
  double BalY = (kp * eAngleY) + (kd * -GyYR);
  double BalZ = (kp * eAngleZ) + (kd * -GyZR);
  if(throttle == 0) BalX = BalY = BalZ = 0.0;

  double speedA = activeThrottle + BalY + BalX + BalZ;
  double speedB = activeThrottle - BalY + BalX - BalZ;
  double speedC = activeThrottle - BalY - BalX + BalZ;
  double speedD = activeThrottle + BalY - BalX - BalZ;

  analogWrite(6,  constrain((int)speedA, 0, 250));
  analogWrite(10, constrain((int)speedB, 0, 250));
  analogWrite(9,  constrain((int)speedC, 0, 250));
  analogWrite(5,  constrain((int)speedD, 0, 250));
}