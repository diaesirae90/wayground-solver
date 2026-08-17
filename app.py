import json
import os
import re
import urllib.parse
import google.generativeai as genai
import requests
import streamlit as st

st.set_page_config(page_title="Quiz Solver App", page_icon="📝", layout="centered")

st.title("📝 Quiz Solver")
st.caption("Mendukung Game PIN (contoh: 285477), Link Live, dan Solo Game.")

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


def parse_clean_code(raw_input: str) -> str:
    decoded = urllib.parse.unquote(urllib.parse.unquote(raw_input.strip()))
    match_gc = re.search(r"gc=([0-9a-zA-Z]+)", decoded)
    if match_gc:
        return match_gc.group(1)
    match_game = re.search(r"/join/game/([^?&#]+)", decoded)
    if match_game:
        return match_game.group(1)
    match_pin = re.search(r"\b(\d{6,8})\b", decoded)
    if match_pin:
        return match_pin.group(1)
    return decoded


def get_quiz_questions(raw_input: str) -> dict:
    code = parse_clean_code(raw_input)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "Origin": "https://wayground.com",
        "Referer": "https://wayground.com/",
    }

    domains = ["https://wayground.com", "https://quizizz.com"]

    # 1. Cek Room lewat checkRoom (Game PIN / Room Code)
    room_hash = None
    for domain in domains:
        try:
            res = requests.post(
                f"{domain}/play-api/v5/checkRoom",
                json={"roomCode": code},
                headers=headers,
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                questions = data.get("room", {}).get("questions")
                if questions:
                    return questions
                room_hash = data.get("room", {}).get("hash")
                if room_hash:
                    break
        except Exception:
            continue

    target_hash = room_hash or code

    # 2. Ambil data dari _gameapi dengan hash ruangan
    for domain in domains:
        try:
            url = f"{domain}/_gameapi/main/public/v1/students/games/{target_hash}"
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                quizzes = data.get("data", {}).get("quizzes", {})
                if quizzes:
                    first_key = next(iter(quizzes))
                    questions = quizzes[first_key].get("questions", {})
                    if questions:
                        return questions

                # Format items array
                items = data.get("data", {}).get("items", [])
                if items and "quizId" in items[0]:
                    quiz_id = items[0]["quizId"]
                    q_res = requests.get(
                        f"{domain}/api/main/quiz/{quiz_id}",
                        headers=headers,
                        timeout=10,
                    )
                    if q_res.status_code == 200:
                        q_data = q_res.json().get("data", {}).get("quiz", {}).get("info", {}).get("questions", [])
                        if q_data:
                            return {q.get("_id", str(i)): q for i, q in enumerate(q_data)}
        except Exception:
            continue

    # 3. Cek Solo Join jika menggunakan token U2Fsd
    if code.startswith("U2Fsd"):
        for domain in domains:
            try:
                res = requests.post(
                    f"{domain}/play-api/v4/soloJoin",
                    json={"game": code},
                    headers=headers,
                    timeout=10,
                )
                if res.status_code == 200:
                    quiz_id = res.json().get("quizId") or res.json().get("data", {}).get("quizId")
                    if quiz_id:
                        q_res = requests.get(
                            f"{domain}/api/main/quiz/{quiz_id}",
                            headers=headers,
                            timeout=10,
                        )
                        q_list = q_res.json().get("data", {}).get("quiz", {}).get("info", {}).get("questions", [])
                        if q_list:
                            return {q.get("_id", str(i)): q for i, q in enumerate(q_list)}
            except Exception:
                continue

    raise ValueError("Kuis tidak ditemukan. Pastikan sesi live masih aktif di lobi.")


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
    Analisis setiap pertanyaan dan pilih jawaban yang paling tepat.
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
    "Game PIN / Room Code:",
    placeholder="Masukkan 6 digit PIN (contoh: 285477)...",
)

if st.button("Dapatkan Jawaban", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di sidebar.")
    elif not user_input:
        st.warning("⚠️ Masukkan Game PIN.")
    else:
        with st.spinner("Mengambil soal dari live room & memproses ke AI..."):
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
