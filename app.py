import json
import os
import re
import google.generativeai as genai
import requests
import streamlit as st

# ==========================================
# KONFIGURASI API KEY
# ==========================================
# Pilihan 1: Mengambil dari Streamlit Secrets / Environment Variable (Direkomendasikan)
# Pilihan 2: Mengganti string di bawah jika ingin hardcode langsung (Kurang aman jika repo Public)
DEFAULT_API_KEY = os.getenv("GEMINI_API_KEY", "")

st.set_page_config(page_title="Quiz Solver App", page_icon="📝", layout="centered")

st.title("📝 Quiz Solver")
st.caption("Masukkan Room Hash / Kode Kuis untuk memproses jawaban via AI.")

# Sidebar Pengaturan
with st.sidebar:
    st.header("⚙️ Pengaturan")
    api_key_input = st.text_input(
        "Gemini API Key",
        value=DEFAULT_API_KEY,
        type="password",
        help="API Key yang digunakan untuk memproses soal.",
    )


def clean_text(raw_html: str) -> str:
    """Menghapus tag HTML dari teks."""
    if not raw_html:
        return ""
    return re.sub(r"<.*?>", "", raw_html).strip()


def fetch_quiz_data(room_hash: str) -> dict:
    """Mengambil struktur soal dari endpoint kuis."""
    clean_id = room_hash.strip()
    url = f"https://wayground.com/_gameapi/main/public/v1/students/games/{clean_id}"
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()

    quizzes = data.get("data", {}).get("quizzes", {})
    if not quizzes:
        raise ValueError(
            "Data kuis tidak ditemukan. Pastikan Room Hash/Kode valid."
        )

    first_key = next(iter(quizzes))
    return quizzes[first_key].get("questions", {})


def solve_quiz(questions: dict, key: str) -> list:
    """Meminta Gemini menyelesaikan soal dan mengembalikan jawaban."""
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
    Analisis setiap pertanyaan beserta pilihan opsi yang tersedia.
    Tentukan jawaban yang paling tepat.
    Kembalikan HANYA JSON murni berupa list objek dengan format:
    [{"question": "teks pertanyaan", "answer": "teks jawaban yang benar"}]
    """

    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=system_instruction,
        generation_config={"response_mime_type": "application/json"},
    )

    response = model.generate_content(json.dumps(cleaned_payload))
    return json.loads(response.text)


# Form Input Utama
room_hash = st.text_input(
    "Room Hash / Code:", placeholder="Masukkan hash ruangan kuis..."
)

if st.button("Dapatkan Jawaban", type="primary", use_container_width=True):
    active_key = api_key_input.strip() or DEFAULT_API_KEY

    if not active_key:
        st.error("⚠️ API Key tidak boleh kosong.")
    elif not room_hash:
        st.warning("⚠️ Masukkan Room Hash terlebih dahulu.")
    else:
        with st.spinner("Mengambil data kuis & memproses ke Gemini..."):
            try:
                questions = fetch_quiz_data(room_hash)
                results = solve_quiz(questions, active_key)

                st.success(f"Berhasil memproses {len(results)} soal!")
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
