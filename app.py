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
    # Hapus tag HTML & format teks
    text = re.sub(r"<.*?>", "", str(raw_html))
    return text.strip()


def parse_clean_code(raw_input: str) -> str:
    text = raw_input.strip()

    # 1. Decode berkali-kali sampai bebas dari URL Encoding bertingkat (%25, %2F, %3D)
    while "%" in text:
        new_text = urllib.parse.unquote(text)
        if new_text == text:
            break
        text = new_text

    # 2. Tangkap token U2Fsd (AES Encrypted String)
    match_salted = re.search(r"(U2FsdGVkX1[A-Za-z0-9+/=]+)", text)
    if match_salted:
        return match_salted.group(1)

    # 3. Tangkap format parameter URL lainnya
    match_gc = re.search(r"gc=([0-9a-zA-Z]+)", text)
    if match_gc:
        return match_gc.group(1)

    match_game = re.search(r"/join/game/([^?&#]+)", text)
    if match_game:
        return match_game.group(1)

    match_pin = re.search(r"\b(\d{6,8})\b", text)
    if match_pin:
        return match_pin.group(1)

    return text


def get_quiz_questions(raw_input: str) -> dict:
    code = parse_clean_code(raw_input)

    session = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://wayground.com",
        "Referer": "https://wayground.com/join",
    }

    domains = ["https://wayground.com", "https://quizizz.com"]

    # =========================================================
    # JALUR 1: Jika Token adalah U2Fsd (Solo / Live Link)
    # =========================================================
    if code.startswith("U2Fsd"):
        for domain in domains:
            # 1. Cek via soloJoin
            try:
                res = session.post(
                    f"{domain}/play-api/v4/soloJoin",
                    json={"game": code},
                    headers=headers,
                    timeout=10,
                )
                if res.status_code == 200:
                    data = res.json()
                    
                    if "questions" in data and data["questions"]:
                        return data["questions"]

                    quiz_id = (
                        data.get("quizId")
                        or data.get("data", {}).get("quizId")
                        or data.get("room", {}).get("quizId")
                    )

                    if quiz_id:
                        q_res = session.get(
                            f"{domain}/api/main/quiz/{quiz_id}",
                            headers=headers,
                            timeout=10,
                        )
                        if q_res.status_code == 200:
                            q_list = (
                                q_res.json()
                                .get("data", {})
                                .get("quiz", {})
                                .get("info", {})
                                .get("questions", [])
                            )
                            if q_list:
                                return {
                                    q.get("_id", str(i)): q
                                    for i, q in enumerate(q_list)
                                }
            except Exception:
                pass

            # 2. Cek via checkRoom dengan hash
            try:
                res = session.post(
                    f"{domain}/play-api/v5/checkRoom",
                    json={"roomHash": code},
                    headers=headers,
                    timeout=10,
                )
                if res.status_code == 200:
                    data = res.json()
                    questions = data.get("room", {}).get("questions")
                    if questions:
                        return questions
            except Exception:
                pass

    # =========================================================
    # JALUR 2: Jika PIN Room (6-8 digit) atau Game ID biasa
    # =========================================================
    for domain in domains:
        room_hash = None
        try:
            res = session.post(
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
        except Exception:
            pass

        target_hash = room_hash or code

        try:
            url = f"{domain}/_gameapi/main/public/v1/students/games/{target_hash}"
            res = session.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                quizzes = data.get("data", {}).get("quizzes", {})
                if quizzes:
                    first_key = next(iter(quizzes))
                    questions = quizzes[first_key].get("questions", {})
                    if questions:
                        return questions

                items = data.get("data", {}).get("items", [])
                if items and "quizId" in items[0]:
                    quiz_id = items[0]["quizId"]
                    q_res = session.get(
                        f"{domain}/api/main/quiz/{quiz_id}",
                        headers=headers,
                        timeout=10,
                    )
                    if q_res.status_code == 200:
                        q_data = (
                            q_res.json()
                            .get("data", {})
                            .get("quiz", {})
                            .get("info", {})
                            .get("questions", [])
                        )
                        if q_data:
                            return {
                                q.get("_id", str(i)): q
                                for i, q in enumerate(q_data)
                            }
        except Exception:
            continue

    raise ValueError(
        f"Kuis dengan kode '{code[:15]}...' tidak ditemukan atau sesi telah berakhir."
    )


def solve_quiz(questions: dict, key: str) -> list:
    genai.configure(api_key=key)

    cleaned_payload = []
    
    # Menangani format dict maupun list dari respons API
    iterator = questions.items() if isinstance(questions, dict) else enumerate(questions)

    for q_id, q_data in iterator:
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
            if clean_text(opt.get("text", ""))
        ]

        if query_text:
            cleaned_payload.append(
                {"id": str(q_id), "question": query_text, "options": options}
            )

    if not cleaned_payload:
        raise ValueError("Gagal memformat daftar pertanyaan.")

    system_instruction = """
    Kamu adalah asisten penjawab kuis.
    Analisis setiap pertanyaan beserta pilihan opsi yang disediakan, lalu tentukan jawaban yang paling benar.
    Kembalikan HANYA format JSON list:
    [{"question": "teks pertanyaan", "answer": "jawaban yang benar"}]
    """

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=system_instruction,
        generation_config={"response_mime_type": "application/json"},
    )

    response = model.generate_content(json.dumps(cleaned_payload))
    return json.loads(response.text)


# ==========================================
# Antarmuka Pengguna (Streamlit UI)
# ==========================================
user_input = st.text_input(
    "Game PIN / Link Kuis:",
    placeholder="Tempel Game PIN atau Link Live di sini...",
)

if st.button("Dapatkan Jawaban", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di sidebar terlebih dahulu.")
    elif not user_input:
        st.warning("⚠️ Masukkan Game PIN atau Link kuis.")
    else:
        with st.spinner("Mengambil data kuis & memproses jawaban dengan AI..."):
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
