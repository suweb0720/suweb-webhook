"""
슈엡 X 비트코인 시그널 2.0
텔레그램 채널 자동 정보 발송 서버
- 신호방: 트레이딩뷰 신호만
- 정보방: 비트코인 시황 리포트만
"""
from flask import Flask, request, jsonify
import requests
import json
import logging
import os
import threading
import time
import schedule
from datetime import datetime
import pytz

# ===== 설정 =====
BOT_TOKEN  = os.environ.get("BOT_TOKEN",  "8257197393:AAGmbYncgT0eGNQ-4vX7dI8A2EMbQEMhyVA")

# 채널 분리
SIGNAL_CHANNEL_ID = os.environ.get("SIGNAL_CHANNEL_ID", "-1003953608688")  # 신호 전용
INFO_CHANNEL_ID   = os.environ.get("INFO_CHANNEL_ID",   "-1003913017251")  # 정보 전용

SECRET_KEY = os.environ.get("SECRET_KEY", "suweb2024")
PORT       = int(os.environ.get("PORT", 5000))
KST        = pytz.timezone("Asia/Seoul")
# ================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def now_kst():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

def send_telegram(msg: str, channel_id: str) -> bool:
    """텔레그램 메시지 발송 (채널 ID 지정)"""
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": channel_id, "text": msg, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        log.error(f"텔레그램 발송 오류: {e}")
        return False

# ==========================================
# 1. BTC 시세 (CoinGecko)
# ==========================================
def get_btc_price():
    try:
        r    = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true&include_24hr_vol=true", timeout=10)
        data = r.json()["bitcoin"]
        price      = data["usd"]
        change_pct = data["usd_24h_change"]
        volume     = data.get("usd_24h_vol", 0) / 1e9
        arrow = "📈" if change_pct >= 0 else "📉"
        sign  = "+" if change_pct >= 0 else ""
        return (f"{arrow} <b>BTC 시세</b>: ${price:,.0f}\n"
                f"   24H 변동: {sign}{change_pct:.2f}%\n"
                f"   24H 거래량: ${volume:.2f}B")
    except Exception as e:
        log.error(f"BTC 시세 오류: {e}")
        return "💰 BTC 시세: 조회 실패"

# ==========================================
# 2. 공포탐욕 지수 (alternative.me)
# ==========================================
def get_fear_greed():
    try:
        r     = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        data  = r.json()["data"][0]
        value = int(data["value"])
        if value <= 25:
            emoji, kor, hint = "😱", "극단적 공포", "→ 매수 기회일 수 있음"
        elif value <= 45:
            emoji, kor, hint = "😨", "공포", "→ 신중한 매수 구간"
        elif value <= 55:
            emoji, kor, hint = "😐", "중립", "→ 관망 구간"
        elif value <= 75:
            emoji, kor, hint = "😏", "탐욕", "→ 과열 주의"
        else:
            emoji, kor, hint = "🤑", "극단적 탐욕", "→ 조정 가능성 높음"
        return (f"{emoji} <b>공포탐욕 지수</b>: {value}/100  ({kor})\n"
                f"   {hint}")
    except Exception as e:
        log.error(f"공포탐욕 오류: {e}")
        return "😶 공포탐욕 지수: 조회 실패"

# ==========================================
# 3. 펀딩비 (CoinGlass API - 무료)
# ==========================================
def get_funding_rate():
    try:
        # CoinGlass 무료 API 사용
        r    = requests.get("https://open-api.coinglass.com/public/v2/funding", 
                           params={"symbol": "BTC"}, timeout=10)
        data = r.json()
        
        if data.get("code") == "0" and data.get("data"):
            # 바이낸스 펀딩비 찾기
            for exchange in data["data"]:
                if exchange.get("exchangeName") == "Binance":
                    rate = float(exchange.get("rate", 0)) * 100
                    break
            else:
                rate = 0.0
        else:
            rate = 0.0
            
        if rate >= 0.03:
            judge = "🔴 롱 극단 과열 — 숏 전환 주의"
        elif rate >= 0.01:
            judge = "🟠 롱 과열 — 진입 신중히"
        elif rate >= -0.01:
            judge = "🟡 중립 — 정상 구간"
        elif rate >= -0.03:
            judge = "🟢 숏 과열 — 롱 유리"
        else:
            judge = "🔵 숏 극단 과열 — 롱 전환 주의"
        sign = "+" if rate >= 0 else ""
        return (f"💰 <b>펀딩비 (바이낸스)</b>: {sign}{rate:.4f}%\n"
                f"   {judge}")
    except Exception as e:
        log.error(f"펀딩비 오류: {e}")
        return "💰 <b>펀딩비</b>: 데이터 수집 중"

# ==========================================
# 4. 바이낸스 상위 트레이더 롱/숏 비율 (CoinGlass)
# ==========================================
def get_hl_whale_ratio():
    try:
        r = requests.get(
            "https://open-api.coinglass.com/public/v2/long_short_ratio",
            params={"symbol": "BTC", "interval": "1h"},
            timeout=10
        )
        data = r.json()
        
        if data.get("code") == "0" and data.get("data"):
            # 바이낸스 데이터 찾기
            for exchange in data["data"]:
                if exchange.get("exchangeName") == "Binance":
                    long_pct  = float(exchange.get("longRate", 50))
                    short_pct = float(exchange.get("shortRate", 50))
                    break
            else:
                long_pct = short_pct = 50.0
        else:
            long_pct = short_pct = 50.0

        if long_pct >= 65:
            sentiment = "🔴 롱 쏠림 — 역추세 주의"
        elif long_pct >= 55:
            sentiment = "🟠 롱 우세 — 추세 확인 필요"
        elif short_pct >= 65:
            sentiment = "🔵 숏 쏠림 — 역추세 주의"
        elif short_pct >= 55:
            sentiment = "🟢 숏 우세 — 추세 확인 필요"
        else:
            sentiment = "🟡 균형 — 방향성 불명확"

        return (f"🐋 <b>바이낸스 상위 트레이더 롱/숏 비율</b>\n"
                f"   롱: {long_pct:.1f}%  숏: {short_pct:.1f}%\n"
                f"   {sentiment}")
    except Exception as e:
        log.error(f"롱숏비율 오류: {e}")
        return "🐋 <b>상위 트레이더 롱/숏 비율</b>: 데이터 수집 중"

# ==========================================
# 5. BTC 미결제약정 (CoinGlass)
# ==========================================
def get_open_interest():
    try:
        r = requests.get(
            "https://open-api.coinglass.com/public/v2/open_interest",
            params={"symbol": "BTC"},
            timeout=10
        )
        data = r.json()
        
        if data.get("code") == "0" and data.get("data"):
            oi_usd = float(data["data"].get("totalOpenInterest", 0)) / 1e9
            
            # 변화율 계산 (임시로 0으로 설정)
            chg_pct = 0.0  # CoinGlass 무료 API는 변화율 미제공
            
            judge = "🟡 보합 — 방향성 대기"
        else:
            oi_usd = 0.0
            chg_pct = 0.0
            judge = "🟡 보합 — 방향성 대기"

        return (f"📌 <b>BTC 미결제약정 (전체)</b>: ${oi_usd:.2f}B\n"
                f"   {judge}")
    except Exception as e:
        log.error(f"미결제약정 오류: {e}")
        return "📌 <b>BTC 미결제약정</b>: 데이터 수집 중"

# ==========================================
# 6. BTC 도미넌스 (CoinLore)
# ==========================================
def get_dominance():
    try:
        r   = requests.get("https://api.coinlore.net/api/global/", timeout=10)
        dom = float(r.json()[0]["btc_d"])
        if dom >= 60:
            hint = "→ 비트코인 강세 구간"
        elif dom >= 55:
            hint = "→ 비트코인 중립 구간"
        else:
            hint = "→ 비트코인 약세 구간"
        return (f"👑 <b>BTC 도미넌스</b>: {dom:.1f}%\n"
                f"   {hint}")
    except Exception as e:
        log.error(f"도미넌스 오류: {e}")
        return "👑 BTC 도미넌스: 조회 실패"

# ==========================================
# 일일 리포트 통합 발송 (정보방 전용)
# ==========================================
def send_daily_report():
    log.info("일일 리포트 발송 시작 (정보방)...")
    now = datetime.now(KST).strftime("%Y년 %m월 %d일 %H:%M")
    sections = [
        get_btc_price(),
        get_fear_greed(),
        get_funding_rate(),
        get_hl_whale_ratio(),
        get_open_interest(),
        get_dominance(),
    ]
    msg = (
        f"📊 <b>슈엡 X 비트코인 시황 리포트</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🕘 {now} (KST)\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(sections) +
        "\n\n━━━━━━━━━━━━━━━━\n"
        "⚠ 본 정보는 참고용이며 투자 결정의 책임은 본인에게 있습니다."
    )
    success = send_telegram(msg, INFO_CHANNEL_ID)
    log.info(f"일일 리포트 발송 {'성공' if success else '실패'}")

# ==========================================
# 펀딩비 극단 경고 (정보방 전용)
# ==========================================
def check_funding_alert():
    try:
        r    = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT", timeout=10)
        rate = float(r.json()["lastFundingRate"]) * 100
        if rate >= 0.05:
            msg = (f"🚨 <b>펀딩비 경고!</b>\n"
                   f"━━━━━━━━━━━━━━━━\n"
                   f"현재 펀딩비: +{rate:.4f}%\n"
                   f"🔴 롱 극단 과열 상태\n"
                   f"숏 포지션이 유리할 수 있습니다.\n"
                   f"━━━━━━━━━━━━━━━━")
            send_telegram(msg, INFO_CHANNEL_ID)
        elif rate <= -0.05:
            msg = (f"🚨 <b>펀딩비 경고!</b>\n"
                   f"━━━━━━━━━━━━━━━━\n"
                   f"현재 펀딩비: {rate:.4f}%\n"
                   f"🔵 숏 극단 과열 상태\n"
                   f"롱 포지션이 유리할 수 있습니다.\n"
                   f"━━━━━━━━━━━━━━━━")
            send_telegram(msg, INFO_CHANNEL_ID)
    except Exception as e:
        log.error(f"펀딩비 체크 오류: {e}")

# ==========================================
# 스케줄러 (백업용)
# ==========================================
def run_scheduler():
    schedule.every(8).hours.do(check_funding_alert)
    log.info("스케줄러 시작!")
    while True:
        schedule.run_pending()
        time.sleep(60)

# ==========================================
# Flask 라우트
# ==========================================
@app.route("/webhook/<key>", methods=["POST"])
def webhook(key):
    """트레이딩뷰 신호 수신 → 신호방으로 발송"""
    if key != SECRET_KEY:
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    try:
        raw = request.data.decode("utf-8")
        try:
            data = json.loads(raw)
            msg  = data.get("message", raw)
        except:
            msg = raw
        if not msg:
            return jsonify({"status": "error"}), 400
        
        # 신호방으로 발송
        success = send_telegram(msg, SIGNAL_CHANNEL_ID)
        log.info(f"신호방 발송 {'성공' if success else '실패'}: {msg[:50]}...")
        return (jsonify({"status": "ok"}), 200) if success else (jsonify({"status": "error"}), 500)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running", "time": now_kst() + " (KST)"}), 200

@app.route("/test", methods=["GET"])
def test():
    """신호방 테스트"""
    msg = (f"✅ 슈엡 X 비트코인 시그널 2.0\n"
           f"━━━━━━━━━━━━━━━━\n"
           f"신호방 연결 테스트\n"
           f"서버 시간: {now_kst()} (KST)\n"
           f"상태: 정상 작동 중 🟢")
    success = send_telegram(msg, SIGNAL_CHANNEL_ID)
    return (jsonify({"status": "ok"}), 200) if success else (jsonify({"status": "error"}), 500)

@app.route("/test-info", methods=["GET"])
def test_info():
    """정보방 테스트"""
    msg = (f"✅ 슈엡 X 비트코인 정보방\n"
           f"━━━━━━━━━━━━━━━━\n"
           f"정보방 연결 테스트\n"
           f"서버 시간: {now_kst()} (KST)\n"
           f"상태: 정상 작동 중 🟢")
    success = send_telegram(msg, INFO_CHANNEL_ID)
    return (jsonify({"status": "ok"}), 200) if success else (jsonify({"status": "error"}), 500)

@app.route("/report", methods=["GET"])
def manual_report():
    """정보방 리포트 수동 발송"""
    threading.Thread(target=send_daily_report, daemon=True).start()
    return jsonify({"status": "ok", "message": "정보방 리포트 발송 시작"}), 200

if __name__ == "__main__":
    threading.Thread(target=run_scheduler, daemon=True).start()
    log.info(f"서버 시작 — 포트: {PORT}")
    log.info(f"신호방: {SIGNAL_CHANNEL_ID}")
    log.info(f"정보방: {INFO_CHANNEL_ID}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
