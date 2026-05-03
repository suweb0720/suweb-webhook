"""
슈엡 X 비트코인 시그널 2.0
트레이딩뷰 웹훅 → 텔레그램 채널 자동 발송 서버
"""
from flask import Flask, request, jsonify
import requests
import json
import logging
from datetime import datetime
import pytz
import os

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
    data = {
        "chat_id":    CHANNEL_ID,
        "text":       msg,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            log.info("텔레그램 발송 성공")
            return True
        else:
            log.error(f"텔레그램 발송 실패: {r.status_code} {r.text}")
            return False
    except Exception as e:
        log.error(f"텔레그램 발송 오류: {e}")
        return False

@app.route("/webhook/<key>", methods=["POST"])
def webhook(key):
    if key != SECRET_KEY:
        log.warning(f"잘못된 시크릿 키: {key}")
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    try:
        raw = request.data.decode("utf-8")
        log.info(f"웹훅 수신: {raw[:200]}")
        try:
            data = json.loads(raw)
            msg  = data.get("message", raw)
        except:
            msg = raw
        if not msg:
            return jsonify({"status": "error", "message": "빈 메시지"}), 400
        success = send_telegram(msg)
        return (jsonify({"status": "ok"}), 200) if success else (jsonify({"status": "error"}), 500)
    except Exception as e:
        log.error(f"웹훅 처리 오류: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "running",
        "time":   now_kst() + " (KST)",
    }), 200

@app.route("/test", methods=["GET"])
def test():
    msg = (
        "✅ 슈엡 X 비트코인 시그널 2.0\n"
        "━━━━━━━━━━━━━━━━\n"
        "웹훅 서버 연결 테스트\n"
        f"서버 시간: {now_kst()} (KST)\n"
        "상태: 정상 작동 중 🟢"
    )
    success = send_telegram(msg)
    return (jsonify({"status": "ok", "message": "테스트 발송 완료"}), 200) if success else (jsonify({"status": "error"}), 500)

if __name__ == "__main__":
    log.info(f"슈엡 X 비트코인 시그널 2.0 웹훅 서버 시작 — 포트: {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
