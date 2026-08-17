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
    "Mendukung Link Solo (`/join/game/U2Fsd...`), Live Game PIN, dan URL kuis."
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
    """Mengekstrak token/kode dari URL atau teks input."""
    decoded = urllib.parse.unquote(urllib.parse.unquote(raw_input.strip()))

    # Pola 1: /join/game/U2Fsd...
    match_game = re.search(r"/join/game/([^?&#]+)", decoded)
    if match_game:
        return match_game.group(1)

    # Pola 2: gc=123456
    match_gc = re.search(r"gc=([0-9a-zA-Z]+)", decoded)
    if match_gc:
        return match_gc.group(1)

    return decoded


def fetch_questions_by_quiz_id(quiz_id: str, headers: dict) -> dict:
    """Mengambil detail soal berdasarkan Quiz ID."""
    url = f"https://wayground.com/api/main/quiz/{quiz_id}"
    res = requests.get(url, headers=headers, timeout=10)
    if res.status_code == 200:
        data = res.json()
        questions = (
            data.get("data", {})
            .get("quiz", {})
            .get("info", {})
            .get("questions", [])
        )
        if questions:
            return {
                q.get("_id", str(i)): q
                for i, q in enumerate(questions)
            }
    return {}


def get_quiz_data(raw_input: str) -> dict:
    """Mengekstrak kuis dari token solo join, game code, atau hash."""
    token_or_code = parse_raw_input(raw_input)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json",
        "Origin": "https://wayground.com",
        "Referer": "https://wayground.com/",
    }

    # 1. Jika token adalah enkripsi solo join (U2Fsd...)
    if token_or_code.startswith("U2Fsd"):
        # Coba endpoint soloJoin
        try:
            solo_url = "https://wayground.com/play-api/v4/soloJoin"
            payload = {"game": token_or_code}
            res = requests.post(solo_url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                body = res.json()
                quiz_id = body.get("quizId") or body.get("data", {}).get("quizId")
                if quiz_id:
                    questions = fetch_questions_by_quiz_id(quiz_id, headers)
                    if questions:
                        return questions
        except Exception:
            pass

        # Coba endpoint join v5
        try:
            join_url = "https://wayground.com/play-api/v5/join"
            payload = {"roomHash": token_or_code}
            res = requests.post(join_url, json=payload, headers=headers, timeout=10)
            if res.status_code == 200:
                body = res.json()
                questions = body.get("room", {}).get("questions")
                if questions:
                    return questions
        except Exception:
            pass

    # 2. Coba endpoint checkRoom (Game PIN / Room Hash standar)
    try:
        check_url = "https://wayground.com/play-api/v5/checkRoom"
        for key in ["roomCode", "roomHash"]:
            res = requests.post(check_url, json={key: token_or_code}, headers=headers, timeout=10)
            if res.status_code == 200:
                body = res.json()
                questions = body.get("room", {}).get("questions")
                if questions:
                    return questions

                r_hash = body.get("room", {}).get("hash")
                if r_hash:
                    game_url = f"https://wayground.com/_gameapi/main/public/v1/students/games/{r_hash}"
                    res_game = requests.get(game_url, headers=headers, timeout=10)
                    quizzes = res_game.json().get("data", {}).get("quizzes", {})
                    first_key = next(iter(quizzes))
                    return quizzes[first_key].get("questions", {})
    except Exception:
        pass

    # 3. Coba endpoint student game langsung
    try:
        url = f"https://wayground.com/_gameapi/main/public/v1/students/games/{token_or_code}"
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            quizzes = res.json().get("data", {}).get("quizzes", {})
            if quizzes:
                first_key = next(iter(quizzes))
                return quizzes[first_key].get("questions", {})
    except Exception:
        pass

    raise ValueError(
        "Kuis tidak ditemukan atau sesi sudah kadaluarsa. Pastikan room masih aktif."
    )


def solve_quiz(questions: dict, key: str) -> list:
    genai.configure(api_key=key)

    cleaned_payload = []
    for q_id, q_data in questions.items():
        structure = q_data.get("structure", {})
        query_text = clean_text(
            structure.get("query", {}).get("text", "") or q_data.get("question", "")
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
    "Game PIN / Join URL / Solo Link:",
    placeholder="Paste URL kuis atau 6 digit Game PIN...",
)

if st.button("Dapatkan Jawaban", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di menu sebelah kiri.")
    elif not user_input:
        st.warning("⚠️ Masukkan link atau PIN kuis terlebih dahulu.")
    else:
        with st.spinner("Membaca data kuis & memproses AI..."):
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
