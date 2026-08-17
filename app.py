import json
import os
import re
import google.generativeai as genai
import requests
import streamlit as st

st.set_page_config(page_title="Quiz Solver App", page_icon="📝", layout="centered")

st.title("📝 Quiz Solver")
st.caption(
    "Masukkan Link Join, Game PIN (misal: 052116), atau Room Hash untuk mendapatkan jawaban."
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


def extract_game_code(input_str: str) -> str:
    """Mengekstrak PIN/Game Code dari teks atau URL"""
    input_str = input_str.strip()
    match = re.search(r"gc=([0-9a-zA-Z]+)", input_str)
    if match:
        return match.group(1)
    return input_str


def get_quiz_data(raw_input: str) -> dict:
    """Mengambil soal kuis baik lewat Game PIN maupun Room ID"""
    clean_id = extract_game_code(raw_input)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json",
    }

    # 1. Coba ambil langsung jika formatnya Room Hash
    try:
        url = f"https://wayground.com/_gameapi/main/public/v1/students/games/{clean_id}"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            quizzes = data.get("data", {}).get("quizzes", {})
            if quizzes:
                first_key = next(iter(quizzes))
                return quizzes[first_key].get("questions", {})
    except Exception:
        pass

    # 2. Coba endpoint checkRoom jika input berupa Game PIN (6 digit)
    try:
        check_url = "https://wayground.com/play-api/v5/checkRoom"
        payload = {"roomCode": clean_id}
        res = requests.post(check_url, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            room_data = res.json()
            # Cek struktur questions di response checkRoom
            questions = room_data.get("room", {}).get(
                "questions"
            ) or room_data.get("questions")
            if questions:
                return questions

            # Jika mengembalikan hash room
            room_hash = room_data.get("room", {}).get("hash")
            if room_hash:
                game_url = f"https://wayground.com/_gameapi/main/public/v1/students/games/{room_hash}"
                res_game = requests.get(game_url, headers=headers, timeout=10)
                quizzes = res_game.json().get("data", {}).get("quizzes", {})
                first_key = next(iter(quizzes))
                return quizzes[first_key].get("questions", {})
    except Exception:
        pass

    raise ValueError(
        "Kuis tidak ditemukan. Pastikan Game PIN / Room Hash aktif dan benar."
    )


def solve_quiz(questions: dict, key: str) -> list:
    genai.configure(api_key=key)

    cleaned_payload = []
    for q_id, q_data in questions.items():
        structure = q_data.get("structure", {})
        query_text = clean_text(structure.get("query", {}).get("text", ""))
        raw_options = structure.get("options", [])
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
    Analisis setiap pertanyaan dan tentukan jawaban yang paling benar.
    Kembalikan HANYA JSON murni berupa list objek dengan format:
    [{"question": "teks pertanyaan", "answer": "jawaban yang benar"}]
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
    "Game PIN / Room Code / Join URL:",
    placeholder="Contoh: 052116 atau https://wayground.com/join?gc=052116",
)

if st.button("Dapatkan Jawaban", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di menu sebelah kiri.")
    elif not user_input:
        st.warning("⚠️ Masukkan Game PIN atau URL kuis.")
    else:
        with st.spinner("Mengambil soal & meminta jawaban AI..."):
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
