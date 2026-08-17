import json
import os
import re
import urllib.parse
import google.generativeai as genai
import requests
import streamlit as st

st.set_page_config(page_title="Quiz Solver App", page_icon="📝", layout="centered")

st.title("📝 Quiz Solver")
st.caption(
    "Mendukung Link Join (`/join/game/...`), Game PIN (misal: 052116), dan Room Hash."
)

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
    return re.sub(r"<.*?>", "", raw_html).strip()


def parse_raw_input(raw_input: str) -> str:
    """Mengekstrak room hash, token, atau game code dari input/URL."""
    decoded = urllib.parse.unquote(urllib.parse.unquote(raw_input.strip()))

    # Format 1: ?gc=123456
    match_gc = re.search(r"gc=([0-9a-zA-Z]+)", decoded)
    if match_gc:
        return match_gc.group(1)

    # Format 2: /join/game/TOKEN_ATAU_HASH
    match_join = re.search(r"/join/game/([^?&#/]+)", decoded)
    if match_join:
        return match_join.group(1)

    # Format 3: URL langsung dengan ID 24 hex di path
    match_hex = re.search(r"([a-f0-9]{24})", decoded)
    if match_hex:
        return match_hex.group(1)

    return decoded


def get_quiz_data(raw_input: str) -> dict:
    """Mengambil soal kuis dari berbagai endpoint Wayground/Quizizz."""
    token_or_code = parse_raw_input(raw_input)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json",
    }

    # 1. Coba endpoint Game API langsung
    try:
        url = f"https://wayground.com/_gameapi/main/public/v1/students/games/{token_or_code}"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            quizzes = data.get("data", {}).get("quizzes", {})
            if quizzes:
                first_key = next(iter(quizzes))
                return quizzes[first_key].get("questions", {})
    except Exception:
        pass

    # 2. Coba endpoint checkRoom (jika input Game PIN atau roomHash)
    try:
        check_url = "https://wayground.com/play-api/v5/checkRoom"
        for key in ["roomCode", "roomHash"]:
            payload = {key: token_or_code}
            res = requests.post(
                check_url, json=payload, headers=headers, timeout=10
            )
            if res.status_code == 200:
                room_data = res.json()
                questions = room_data.get("room", {}).get(
                    "questions"
                ) or room_data.get("questions")
                if questions:
                    return questions

                room_hash = room_data.get("room", {}).get("hash")
                if room_hash:
                    game_url = f"https://wayground.com/_gameapi/main/public/v1/students/games/{room_hash}"
                    res_game = requests.get(
                        game_url, headers=headers, timeout=10
                    )
                    quizzes = res_game.json().get("data", {}).get(
                        "quizzes", {}
                    )
                    first_key = next(iter(quizzes))
                    return quizzes[first_key].get("questions", {})
    except Exception:
        pass

    # 3. Coba endpoint Quiz ID langsung (jika input 24 hex)
    try:
        url_quiz = f"https://wayground.com/api/main/quiz/{token_or_code}"
        res = requests.get(url_quiz, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            questions = (
                data.get("data", {}).get("quiz", {}).get("info", {}).get("questions")
            )
            if questions:
                return {
                    q.get("_id", str(i)): q for i, q in enumerate(questions)
                }
    except Exception:
        pass

    raise ValueError(
        "Kuis tidak ditemukan. Pastikan sesi kuis masih aktif atau gunakan Game PIN angka (misal: 6 digit PIN lobi)."
    )


def solve_quiz(questions: dict, key: str) -> list:
    genai.configure(api_key=key)

    cleaned_payload = []
    for q_id, q_data in questions.items():
        structure = q_data.get("structure", {})
        query_text = clean_text(
            structure.get("query", {}).get("text", "")
            or q_data.get("question", "")
        )
        raw_options = structure.get("options", []) or q_data.get("options", [])
        options = [
            {
                "id": opt.get("id") or opt.get("_id"),
                "text": clean_text(opt.get("text", "")),
            }
            for opt in raw_options
        ]
        cleaned_payload.append(
            {"id": q_id, "question": query_text, "options": options}
        )

    system_instruction = """
    Kamu adalah asisten analisis kuis.
    Analisis setiap pertanyaan dan opsi jawaban yang tersedia.
    Kembalikan HANYA JSON murni berupa list objek:
    [{"question": "teks pertanyaan", "answer": "jawaban yang paling benar"}]
    """

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=system_instruction,
        generation_config={"response_mime_type": "application/json"},
    )

    response = model.generate_content(json.dumps(cleaned_payload))
    return json.loads(response.text)


# Form Input
user_input = st.text_input(
    "Game PIN / Join URL / Room Hash:",
    placeholder="Paste URL kuis atau 6 digit Game PIN...",
)

if st.button("Dapatkan Jawaban", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di menu sebelah kiri.")
    elif not user_input:
        st.warning("⚠️ Masukkan link atau PIN kuis terlebih dahulu.")
    else:
        with st.spinner("Mengambil data kuis & memproses AI..."):
            try:
                questions = get_quiz_data(user_input)
                results = solve_quiz(questions, api_key)

                st.success(f"Berhasil memuat {len(results)} soal!")
                st.divider()

                for idx, item in enumerate(results, 1):
                    with st.expander(
                        f"**{idx}. {item.get('question')}**", expanded=True
                    ):
                        st.markdown(
                            f"**Jawaban:** :green[{item.get('answer')}]"
                        )

            except Exception as e:
                st.error(f"Gagal memproses kuis: {e}")
