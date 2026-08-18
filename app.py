import json
import os
import re
import google.generativeai as genai
import requests
import streamlit as st

st.set_page_config(page_title="Quiz Auto-Resolver", page_icon="⚡", layout="centered")

st.title("⚡ Quiz Auto-Resolver")
st.caption("Mendukung format JSON Rejoin, Join, maupun Metadata History/Items secara otomatis.")

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
    text = re.sub(r"<.*?>", "", str(raw_html))
    return " ".join(text.split()).strip()


def extract_questions_universal(data: dict) -> tuple:
    """Mengekstrak bank soal dari berbagai format struktur JSON."""
    raw_questions = None
    quiz_name = "Kuis Wayground / Quizizz"
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }

    # 1. Format Rejoin / Check / Room standar
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], dict):
            d_room = data["data"].get("room", {})
            if "questions" in d_room:
                raw_questions = d_room.get("questions")
                quiz_name = d_room.get("name", quiz_name)
            elif "quizzes" in data["data"] and data["data"]["quizzes"]:
                first_key = next(iter(data["data"]["quizzes"]))
                raw_questions = data["data"]["quizzes"][first_key].get("questions")
                quiz_name = data["data"]["quizzes"][first_key].get("info", {}).get("name", quiz_name)
            elif "quiz" in data["data"]:
                raw_questions = data["data"].get("quiz", {}).get("info", {}).get("questions")
                quiz_name = data["data"].get("quiz", {}).get("info", {}).get("name", quiz_name)

        elif "room" in data and isinstance(data["room"], dict):
            raw_questions = data["room"].get("questions")
            quiz_name = data["room"].get("name", quiz_name)

        elif "questions" in data and data["questions"]:
            raw_questions = data["questions"]

    # 2. Format Items / Attempt History: Ekstrak Quiz ID atau Game ID lalu fetch API
    if not raw_questions:
        target_quiz_id = None
        target_game_id = None

        if isinstance(data, dict):
            # Cek di dalam data.items
            items = data.get("data", {}).get("items") or data.get("items", [])
            if isinstance(items, list) and len(items) > 0:
                first_item = items[0]
                target_quiz_id = first_item.get("quizId")
                target_game_id = first_item.get("_id") or first_item.get("gameId")
            
            # Cek di dalam data.quizzes
            quizzes = data.get("data", {}).get("quizzes", {})
            if isinstance(quizzes, dict) and quizzes:
                first_q_key = next(iter(quizzes))
                quiz_name = quizzes[first_q_key].get("name", quiz_name)
                target_quiz_id = first_q_key

            if not target_quiz_id:
                target_quiz_id = data.get("quizId")
            if not target_game_id:
                target_game_id = data.get("gameId")

        # Tarik data soal via Quiz ID
        if target_quiz_id:
            for domain in ["https://wayground.com", "https://quizizz.com"]:
                try:
                    res = session.get(f"{domain}/api/main/quiz/{target_quiz_id}", headers=headers, timeout=10)
                    if res.status_code == 200:
                        q_data = res.json().get("data", {}).get("quiz", {})
                        q_list = q_data.get("info", {}).get("questions", [])
                        quiz_name = q_data.get("info", {}).get("name", quiz_name)
                        if q_list:
                            raw_questions = {q.get("_id", str(i)): q for i, q in enumerate(q_list)}
                            break
                except Exception:
                    pass

        # Jika masih belum dapat, tarik via Game ID
        if not raw_questions and target_game_id:
            for domain in ["https://wayground.com", "https://quizizz.com"]:
                try:
                    res = session.get(f"{domain}/_gameapi/main/public/v1/students/games/{target_game_id}", headers=headers, timeout=10)
                    if res.status_code == 200:
                        g_quizzes = res.json().get("data", {}).get("quizzes", {})
                        if g_quizzes:
                            f_key = next(iter(g_quizzes))
                            quiz_name = g_quizzes[f_key].get("info", {}).get("name", quiz_name)
                            raw_questions = g_quizzes[f_key].get("questions", {})
                            break
                except Exception:
                    pass

    if not raw_questions:
        raise ValueError("Struktur pertanyaan tidak ditemukan dan API Quiz tidak dapat diakses.")

    cleaned_payload = []
    iterator = raw_questions.items() if isinstance(raw_questions, dict) else enumerate(raw_questions)

    for q_id, q_data in iterator:
        structure = q_data.get("structure", {})
        query_text = clean_text(structure.get("query", {}).get("text", "") or q_data.get("question", ""))
        raw_options = structure.get("options", []) or q_data.get("options", [])

        options = []
        for idx, opt in enumerate(raw_options, 1):
            opt_text = clean_text(opt.get("text", ""))
            if not opt_text and opt.get("media"):
                media_url = opt.get("media", [{}])[0].get("url", "")
                opt_text = f"[Gambar: {media_url}]"

            if opt_text:
                options.append(opt_text)

        if query_text:
            cleaned_payload.append({"question": query_text, "options": options})

    return quiz_name, cleaned_payload


def solve_quiz_fast(payload: list, key: str) -> list:
    genai.configure(api_key=key)

    prompt_lines = ["Tentukan kunci jawaban yang paling tepat untuk kuis berikut:\n"]
    for idx, item in enumerate(payload, 1):
        opts_str = " | ".join(item["options"]) if item["options"] else "Isian Singkat"
        prompt_lines.append(f"{idx}. {item['question']}\nPilihan: {opts_str}\n")

    full_prompt = "\n".join(prompt_lines)

    system_instruction = """
    Kamu adalah asisten penjawab ujian kilat.
    Tentukan jawaban yang paling benar dari pilihan yang diberikan.
    Format respon WAJIB HANYA berupa JSON valid list objek murni:
    [{"question": "teks pertanyaan", "answer": "jawaban yang benar"}]
    """

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=system_instruction,
        generation_config={"response_mime_type": "application/json", "temperature": 0.1},
    )

    response = model.generate_content(full_prompt)
    return json.loads(response.text)


# ==========================================
# UI Streamlit
# ==========================================
raw_json_input = st.text_area(
    "Paste Respon JSON Kuis di Sini:",
    placeholder='Paste semua jenis format JSON dari Wayground/Quizizz di sini...',
    height=250,
)

if st.button("⚡ Proses Jawaban Kilat", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di sidebar.")
    elif not raw_json_input.strip():
        st.warning("⚠️ Masukkan teks JSON kuis terlebih dahulu.")
    else:
        with st.spinner("Mendeteksi format JSON & memproses kunci jawaban AI..."):
            try:
                parsed_data = json.loads(raw_json_input)
                quiz_name, questions_payload = extract_questions_universal(parsed_data)

                if not questions_payload:
                    st.error("Daftar pertanyaan kosong.")
                else:
                    results = solve_quiz_fast(questions_payload, api_key)

                    st.success(f"📌 **{quiz_name}** — {len(results)} Soal Berhasil Dijawab!")
                    st.divider()

                    for idx, item in enumerate(results, 1):
                        with st.expander(f"**{idx}. {item.get('question')}**", expanded=True):
                            st.markdown(f"**Jawaban:** :green[**{item.get('answer')}**]")

            except json.JSONDecodeError:
                st.error("Format teks bukan JSON yang valid.")
            except Exception as e:
                st.error(f"Gagal memproses kuis: {e}")
