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
    "Mendukung Link Live (`?gc=...`), Link Solo (`/join/game/U2Fsd...`), atau 6 Digit Game PIN."
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


def parse_input_target(raw_input: str) -> dict:
    """Mendeteksi apakah input berupa Game Code (GC) atau Token Solo (AES)."""
    decoded = urllib.parse.unquote(urllib.parse.unquote(raw_input.strip()))

    # 1. Cek Game Code (?gc=052116 atau 6 digit angka murni)
    match_gc = re.search(r"gc=([0-9a-zA-Z]+)", decoded)
    if match_gc:
        return {"type": "gc", "value": match_gc.group(1)}

    if decoded.isdigit() and len(decoded) in [6, 7, 8]:
        return {"type": "gc", "value": decoded}

    # 2. Cek Token Solo /join/game/U2Fsd...
    match_solo = re.search(r"/join/game/([^?&#]+)", decoded)
    if match_solo:
        return {"type": "solo", "value": match_solo.group(1)}

    if decoded.startswith("U2Fsd"):
        return {"type": "solo", "value": decoded}

    # 3. Fallback sebagai string biasa
    return {"type": "raw", "value": decoded}


def get_quiz_questions(raw_input: str) -> dict:
    target = parse_input_target(raw_input)
    val = target["value"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Content-Type": "application/json",
        "Origin": "https://wayground.com",
        "Referer": "https://wayground.com/",
    }

    # Jalur 1: Sesi Solo Mode (U2Fsd...)
    if target["type"] == "solo":
        # Coba endpoint soloJoin
        try:
            res = requests.post(
                "https://wayground.com/play-api/v4/soloJoin",
                json={"game": val},
                headers=headers,
                timeout=10,
            )
            if res.status_code == 200:
                quiz_id = res.json().get("quizId") or res.json().get("data", {}).get("quizId")
                if quiz_id:
                    q_res = requests.get(
                        f"https://wayground.com/api/main/quiz/{quiz_id}",
                        headers=headers,
                        timeout=10,
                    )
                    questions = q_res.json().get("data", {}).get("quiz", {}).get("info", {}).get("questions")
                    if questions:
                        return {q.get("_id", str(i)): q for i, q in enumerate(questions)}
        except Exception:
            pass

    # Jalur 2: Sesi Live Game / PIN / checkRoom
    try:
        payloads = [{"roomCode": val}, {"roomHash": val}]
        for payload in payloads:
            res = requests.post(
                "https://wayground.com/play-api/v5/checkRoom",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if res.status_code == 200:
                body = res.json()
                questions = body.get("room", {}).get("questions")
                if questions:
                    return questions

                r_hash = body.get("room", {}).get("hash")
                if r_hash:
                    res_game = requests.get(
                        f"https://wayground.com/_gameapi/main/public/v1/students/games/{r_hash}",
                        headers=headers,
                        timeout=10,
                    )
                    quizzes = res_game.json().get("data", {}).get("quizzes", {})
                    first_key = next(iter(quizzes))
                    return quizzes[first_key].get("questions", {})
    except Exception:
        pass

    # Jalur 3: Direct Game API
    try:
        res = requests.get(
            f"https://wayground.com/_gameapi/main/public/v1/students/games/{val}",
            headers=headers,
            timeout=10,
        )
        if res.status_code == 200:
            quizzes = res.json().get("data", {}).get("quizzes", {})
            if quizzes:
                first_key = next(iter(quizzes))
                return quizzes[first_key].get("questions", {})
    except Exception:
        pass

    raise ValueError("Kuis tidak ditemukan. Pastikan kuis/ruangan game masih aktif berjalan.")


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
    Analisis setiap pertanyaan dan tentukan opsi jawaban yang benar.
    Kembalikan HANYA JSON murni berupa list objek:
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
    "Game PIN / Join URL / Solo Link:",
    placeholder="Contoh: 052116 atau paste link join kuis...",
)

if st.button("Dapatkan Jawaban", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di sidebar.")
    elif not user_input:
        st.warning("⚠️ Masukkan link atau PIN kuis.")
    else:
        with st.spinner("Mengambil soal & memproses ke AI..."):
            try:
                questions = get_quiz_questions(user_input)
                results = solve_quiz(questions, api_key)

                st.success(f"Berhasil memuat {len(results)} soal!")
                st.divider()

                for idx, item in enumerate(results, 1):
                    with st.expander(f"**{idx}. {item.get('question')}**", expanded=True):
                        st.markdown(f"**Jawaban:** :green[{item.get('answer')}]")

            except Exception as e:
                st.error(f"Gagal memproses kuis: {e}")
