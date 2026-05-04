"""
슈엡 X 비트코인 시그널 2.0
텔레그램 채널 자동 정보 발송 서버
- 매일 오전 9시 KST: 일일 시황 리포트
- 8시간마다: 펀딩비 극단적일 때만 경고
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
CHANNEL_ID = os.environ.get("CHANNEL_ID", "-1003953608688")
SECRET_KEY = os.environ.get("SECRET_KEY", "suweb2024")
PORT       = int(os.environ.get("PORT", 5000))
KST        = pytz.timezone("Asia/Seoul")
# ================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def now_kst():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

def send_telegram(msg: str) -> bool:
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHANNEL_ID, "text": msg, "parse_mode": "HTML"}
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        log.error(f"텔레그램 발송 오류: {e}")
        return False

# ==========================================
# 1. BTC 시세 (Binance)
# ==========================================
def get_btc_price():
    try:
        r    = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT", timeout=10)
        data = r.json()
        price      = float(data["lastPrice"])
        change_pct = float(data["priceChangePercent"])
        high       = float(data["highPrice"])
        low        = float(data["lowPrice"])
        volume     = float(data["quoteVolume"]) / 1e9
        arrow = "📈" if change_pct >= 0 else "📉"
        sign  = "+" if change_pct >= 0 else ""
        return (f"{arrow} <b>BTC 시세</b>: ${price:,.0f}\n"
                f"   전일 대비: {sign}{change_pct:.2f}%\n"
                f"   24H 고가: ${high:,.0f}  저가: ${low:,.0f}\n"
                f"   24H 거래량: ${volume:.2f}B")
    except Exception as e:
        log.error(f"BTC 시세 오류: {e}")
        return "💰 BTC 시세: 조회 실패"

# ==========================================
# 2. 공포탐욕 지수 (alternative.me 무료)
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
# 3. 펀딩비 (Binance)
# ==========================================
def get_funding_rate():
    try:
        r    = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT", timeout=10)
        data = r.json()
        rate = float(data["lastFundingRate"]) * 100
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
        return "💰 펀딩비: 조회 실패"

# ==========================================
# 4. BTC 도미넌스 (CoinGecko 무료)
# ==========================================
def get_dominance():
    try:
        r   = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        dom = r.json()["data"]["market_cap_percentage"]["btc"]
        if dom >= 60:
            hint = "→ 알트 약세 구간"
        elif dom >= 55:
            hint = "→ 알트 중립 구간"
        else:
            hint = "→ 알트 강세 가능성"
        return (f"👑 <b>BTC 도미넌스</b>: {dom:.1f}%\n"
                f"   {hint}")
    except Exception as e:
        log.error(f"도미넌스 오류: {e}")
        return "👑 BTC 도미넌스: 조회 실패"

# ==========================================
# 5. 미국 시장 (Yahoo Finance)
# ==========================================
def get_market_index():
    try:
        symbols = {"^GSPC": "S&P500", "^IXIC": "나스닥", "^VIX": "VIX"}
        results = []
        for sym, name in symbols.items():
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=2d",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10
            )
            data   = r.json()["chart"]["result"][0]
            closes = data["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if len(closes) >= 2:
                prev  = closes[-2]
                curr  = closes[-1]
                chg   = (curr - prev) / prev * 100
                sign  = "+" if chg >= 0 else ""
                arrow = "📈" if chg >= 0 else "📉"
                results.append(f"   {arrow} {name}: {curr:,.2f}  ({sign}{chg:.2f}%)")
        return "🌍 <b>미국 시장</b>\n" + "\n".join(results)
    except Exception as e:
        log.error(f"시장 지수 오류: {e}")
        return "🌍 미국 시장: 조회 실패"

# ==========================================
# 6. 오늘의 주요 경제 일정
# ==========================================
def get_schedule_notice():
    weekday  = datetime.now(KST).weekday()
    notices  = []
    if weekday == 1:
        notices.append("📋 CPI 발표 가능성 — 변동성 주의")
    if weekday == 2:
        notices.append("📋 FOMC 의사록 발표 가능 — 변동성 주의")
    if weekday == 3:
        notices.append("📋 신규 실업수당 청구건수 발표일")
    if not notices:
        return "📅 <b>오늘 주요 일정</b>: 특이사항 없음"
    return "📅 <b>오늘 주요 일정</b>\n" + "\n".join(notices)

# ==========================================
# 일일 리포트 통합 발송
# ==========================================
def send_daily_report():
    log.info("일일 리포트 발송 시작...")
    now = datetime.now(KST).strftime("%Y년 %m월 %d일 %H:%M")
    sections = [
        get_btc_price(),
        get_fear_greed(),
        get_funding_rate(),
        get_dominance(),
        get_market_index(),
        get_schedule_notice(),
    ]
    msg = (
        f"📊 <b>슈엡 X 비트코인 시그널 2.0</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🕘 {now} (KST)\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(sections) +
        "\n\n━━━━━━━━━━━━━━━━\n"
        "⚠ 본 정보는 참고용이며 투자 결정의 책임은 본인에게 있습니다."
    )
    success = send_telegram(msg)
    log.info(f"일일 리포트 발송 {'성공' if success else '실패'}")

# ==========================================
# 펀딩비 극단 경고
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
            send_telegram(msg)
        elif rate <= -0.05:
            msg = (f"🚨 <b>펀딩비 경고!</b>\n"
                   f"━━━━━━━━━━━━━━━━\n"
                   f"현재 펀딩비: {rate:.4f}%\n"
                   f"🔵 숏 극단 과열 상태\n"
                   f"롱 포지션이 유리할 수 있습니다.\n"
                   f"━━━━━━━━━━━━━━━━")
            send_telegram(msg)
    except Exception as e:
        log.error(f"펀딩비 체크 오류: {e}")

# ==========================================
# 스케줄러
# ==========================================
def run_scheduler():
    schedule.every().day.at("00:00").do(send_daily_report)  # UTC 00:00 = KST 09:00
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
        success = send_telegram(msg)
        return (jsonify({"status": "ok"}), 200) if success else (jsonify({"status": "error"}), 500)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running", "time": now_kst() + " (KST)"}), 200

@app.route("/test", methods=["GET"])
def test():
    msg = (f"✅ 슈엡 X 비트코인 시그널 2.0\n"
           f"━━━━━━━━━━━━━━━━\n"
           f"웹훅 서버 연결 테스트\n"
           f"서버 시간: {now_kst()} (KST)\n"
           f"상태: 정상 작동 중 🟢")
    success = send_telegram(msg)
    return (jsonify({"status": "ok"}), 200) if success else (jsonify({"status": "error"}), 500)

@app.route("/report", methods=["GET"])
def manual_report():
    threading.Thread(target=send_daily_report, daemon=True).start()
    return jsonify({"status": "ok", "message": "리포트 발송 시작"}), 200

if __name__ == "__main__":
    threading.Thread(target=run_scheduler, daemon=True).start()
    log.info(f"서버 시작 — 포트: {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
