import json
import os
import re
import urllib.parse
import google.generativeai as genai
import requests
import streamlit as st

st.set_page_config(page_title="Quiz Solver with Cookies", page_icon="🍪", layout="centered")

st.title("🍪 Quiz Solver (Link + Cookies)")
st.caption("Solusi Bypass Proteksi Live: Masukkan Link Kuis & Cookies Sesi Browser.")

with st.sidebar:
    st.header("⚙️ Pengaturan")
    api_key_input = st.text_input(
        "Gemini API Key",
        value=os.getenv("GEMINI_API_KEY", ""),
        type="password",
        help="Masukkan Google Gemini API Key Anda.",
    )


def clean_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    return re.sub(r"<.*?>", "", str(raw_html)).strip()


def parse_clean_code(raw_input: str) -> str:
    text = raw_input.strip()
    while "%" in text:
        new_text = urllib.parse.unquote(text)
        if new_text == text:
            break
        text = new_text

    # 1. Hash 24 karakter hex dari URL rejoin / games
    match_hex = re.search(r"/games/([a-f0-9]{24})", text)
    if match_hex:
        return match_hex.group(1)

    # 2. Parameter gc= (Game Code)
    match_gc = re.search(r"gc=([0-9a-zA-Z]+)", text)
    if match_gc:
        return match_gc.group(1)

    # 3. PIN angka murni 6-8 digit
    match_pin = re.search(r"\b(\d{6,8})\b", text)
    if match_pin:
        return match_pin.group(1)

    # 4. Token U2Fsd (AES Encrypted)
    match_salted = re.search(r"(U2FsdGVkX1[A-Za-z0-9+/=]+)", text)
    if match_salted:
        return match_salted.group(1)

    # 5. Path join game
    match_game = re.search(r"/join/game/([^?&#]+)", text)
    if match_game:
        return match_game.group(1)

    return text


def parse_cookie_string(cookie_raw: str) -> dict:
    """Mengubah format string cookie mentah menjadi dictionary requests."""
    cookies = {}
    if not cookie_raw:
        return cookies

    for item in cookie_raw.split(";"):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def fetch_quiz_with_cookies(raw_link: str, raw_cookies: str) -> tuple:
    code = parse_clean_code(raw_link)
    cookies_dict = parse_cookie_string(raw_cookies)
    
    session = requests.Session()
    
    # Ambil nilai csrf & uid dari cookie jika ada
    csrf_token = cookies_dict.get("_csrf") or cookies_dict.get("x-csrf-token", "")
    uid = cookies_dict.get("quizizz_uid") or cookies_dict.get("suid", "")
    auth_cookie = cookies_dict.get("_sid", "")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://wayground.com",
        "Referer": "https://wayground.com/join",
    }
    if csrf_token:
        headers["x-csrf-token"] = csrf_token
    if uid:
        headers["x-quizizz-uid"] = uid

    domains = ["https://wayground.com", "https://quizizz.com"]

    for domain in domains:
        # Jalur 1: Jika code adalah 24-hex hash (Rejoin Endpoint)
        if len(code) == 24 and re.match(r"^[a-f0-9]{24}$", code):
            rejoin_url = f"{domain}/_gameapi/main/public/v1/games/{code}/rejoin"
            payload = {
                "roomHash": code,
                "type": "live",
                "authCookie": auth_cookie
            }
            try:
                res = session.post(rejoin_url, headers=headers, cookies=cookies_dict, json=payload, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    room = data.get("data", {}).get("room", {})
                    if "questions" in room and room["questions"]:
                        return room.get("name", "Kuis Live"), room["questions"]
            except Exception:
                pass

            # Cek endpoint games/{hash}
            try:
                g_res = session.get(f"{domain}/_gameapi/main/public/v1/students/games/{code}", headers=headers, cookies=cookies_dict, timeout=10)
                if g_res.status_code == 200:
                    g_data = g_res.json().get("data", {})
                    quizzes = g_data.get("quizzes", {})
                    if quizzes:
                        first_key = next(iter(quizzes))
                        return quizzes[first_key].get("info", {}).get("name", "Kuis Live"), quizzes[first_key].get("questions", {})
            except Exception:
                pass

        # Jalur 2: Jika menggunakan PIN / Room Code biasa
        try:
            res = session.post(f"{domain}/play-api/v5/checkRoom", json={"roomCode": code}, headers=headers, cookies=cookies_dict, timeout=10)
            if res.status_code == 200:
                data = res.json()
                room = data.get("room", {})
                if "questions" in room and room["questions"]:
                    return room.get("name", "Kuis Live"), room["questions"]
                
                room_hash = room.get("hash")
                if room_hash:
                    # Ambil via games/{hash} dengan cookies
                    g_res = session.get(f"{domain}/_gameapi/main/public/v1/students/games/{room_hash}", headers=headers, cookies=cookies_dict, timeout=10)
                    if g_res.status_code == 200:
                        g_data = g_res.json().get("data", {})
                        quizzes = g_data.get("quizzes", {})
                        if quizzes:
                            first_key = next(iter(quizzes))
                            return quizzes[first_key].get("info", {}).get("name", "Kuis Live"), quizzes[first_key].get("questions", {})
        except Exception:
            pass

    raise ValueError(f"Tidak dapat menemukan kuis dengan kode '{code}'. Pastikan cookie sesi masih aktif dan tidak expired.")


def parse_questions_dict(raw_questions: dict, quiz_name: str = "Kuis") -> list:
    cleaned_payload = []
    iterator = raw_questions.items() if isinstance(raw_questions, dict) else enumerate(raw_questions)

    for q_id, q_data in iterator:
        structure = q_data.get("structure", {})
        query_text = clean_text(structure.get("query", {}).get("text", "") or q_data.get("question", ""))
        raw_options = structure.get("options", []) or q_data.get("options", [])

        options = []
        for idx, opt in enumerate(raw_options, 1):
            opt_id = opt.get("id") or opt.get("_id") or str(idx)
            opt_text = clean_text(opt.get("text", ""))
            if not opt_text and opt.get("media"):
                media_url = opt.get("media", [{}])[0].get("url", "")
                opt_text = f"[Opsi Gambar: {media_url}]"

            if opt_text:
                options.append({"id": opt_id, "text": opt_text})

        if query_text:
            cleaned_payload.append({
                "id": str(q_id),
                "question": query_text,
                "options": options
            })

    return cleaned_payload


def solve_quiz_with_ai(payload: list, key: str) -> list:
    genai.configure(api_key=key)

    system_instruction = """
    Kamu adalah asisten penjawab kuis dan ujian.
    Analisis setiap pertanyaan dan pilih opsi jawaban yang paling tepat dari pilihan yang tersedia.
    Kembalikan HANYA format JSON valid list objek murni:
    [{"question": "teks pertanyaan", "answer": "jawaban yang benar"}]
    """

    candidate_models = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-pro"]
    last_err = None

    for model_name in candidate_models:
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_instruction,
                generation_config={"response_mime_type": "application/json"},
            )
            response = model.generate_content(json.dumps(payload))
            return json.loads(response.text)
        except Exception as e:
            last_err = e
            continue

    raise last_err


# ==========================================
# UI Form Input
# ==========================================
st.subheader("📋 Masukkan Detail Sesi Kuis")

user_link = st.text_input(
    "1. Link Kuis / PIN / URL Rejoin:",
    placeholder="Contoh: https://wayground.com/join?gc=20115513 atau URL rejoin..."
)

user_cookies = st.text_area(
    "2. String Cookies dari Browser (Request Headers):",
    placeholder="quizizz_uid=4465...; _sid=FC8j...; _csrf=sHV-...",
    height=120,
    help="Salin isi header 'Cookie' dari DevTools (F12) -> Network pada request kuis."
)

if st.button("Dapatkan Jawaban Sekarang", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di sidebar sebelah kiri.")
    elif not user_link.strip():
        st.warning("⚠️ Masukkan link kuis atau PIN terlebih dahulu.")
    elif not user_cookies.strip():
        st.warning("⚠️ Masukkan string cookies browser.")
    else:
        with st.spinner("Mengakses kuis via session cookies & memproses AI..."):
            try:
                q_name, raw_q = fetch_quiz_with_cookies(user_link, user_cookies)
                payload = parse_questions_dict(raw_q, q_name)

                if not payload:
                    st.error("Daftar pertanyaan tidak ditemukan di dalam sesi kuis.")
                else:
                    results = solve_quiz_with_ai(payload, api_key)
                    st.success(f"📌 **{q_name}** ({len(results)} Soal Berhasil Dijawab)")
                    st.divider()

                    for idx, item in enumerate(results, 1):
                        with st.expander(f"**{idx}. {item.get('question')}**", expanded=True):
                            st.markdown(f"**Jawaban:** :green[**{item.get('answer')}**]")
            except Exception as e:
                st.error(f"Gagal memproses kuis: {e}")
