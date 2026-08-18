import json
import os
import re
import time
import google.generativeai as genai
import streamlit as st

st.set_page_config(
    page_title="Instant Quiz Solver",
    page_icon="⚡",
    layout="centered"
)

st.title("⚡ Instant Quiz Solver (Live Progress)")
st.caption("Solusi Cepat dengan Pemantauan Proses Nyata & Real-Time Streaming.")

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
    """Mengekstrak pertanyaan dan opsi dari berbagai macam format JSON Quizizz / Wayground."""
    raw_questions = None
    quiz_name = "Kuis Wayground / Quizizz"

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

        elif isinstance(data, list):
            raw_questions = data

    if not raw_questions:
        raise ValueError("Struktur pertanyaan ('questions') tidak ditemukan dalam JSON.")

    cleaned_payload = []
    iterator = raw_questions.items() if isinstance(raw_questions, dict) else enumerate(raw_questions)

    for q_id, q_data in iterator:
        structure = q_data.get("structure", {})
        query_text = clean_text(structure.get("query", {}).get("text", "") or q_data.get("question", ""))
        raw_options = structure.get("options", []) or q_data.get("options", [])

        options = []
        for idx, opt in enumerate(raw_options, 1):
            opt_text = clean_text(opt.get("text", ""))

            # Tangani jika opsi berupa media gambar
            if not opt_text and opt.get("media"):
                media_url = opt.get("media", [{}])[0].get("url", "")
                opt_text = f"[Gambar: {media_url}]"

            if opt_text:
                options.append(opt_text)

        if query_text:
            cleaned_payload.append({
                "question": query_text,
                "options": options
            })

    return quiz_name, cleaned_payload


# ==========================================
# UI Streamlit
# ==========================================
raw_json_input = st.text_area(
    "Paste Respon JSON Kuis di Sini:",
    placeholder='{"room": {"name": "...", "questions": { ... }}}',
    height=240,
)

if st.button("⚡ Dapatkan Jawaban Instan (Live Progress)", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di sidebar sebelah kiri.")
    elif not raw_json_input.strip():
        st.warning("⚠️ Silakan tempelkan data JSON kuis terlebih dahulu.")
    else:
        # Container indikator progress visual
        progress_bar = st.progress(0)
        status_box = st.status("🚀 Memulai proses penjawab kuis...", expanded=True)

        try:
            # Langkah 1: Parsing JSON
            status_box.write("🔍 **Langkah 1/4:** Membaca & memvalidasi struktur JSON...")
            progress_bar.progress(15)
            parsed_data = json.loads(raw_json_input)

            # Langkah 2: Ekstraksi Soal & Opsi
            status_box.write("📦 **Langkah 2/4:** Mengekstrak seluruh daftar soal & pilihan jawaban...")
            progress_bar.progress(35)
            quiz_name, questions_payload = extract_questions_universal(parsed_data)

            if not questions_payload:
                progress_bar.empty()
                status_box.update(label="❌ Gagal mengekstrak soal", state="error")
                st.error("Daftar pertanyaan tidak ditemukan di dalam JSON.")
            else:
                total_soal = len(questions_payload)
                status_box.write(f"✅ Berhasil mengekstrak **{total_soal} soal** dari kuis *'{quiz_name}'*.")
                progress_bar.progress(55)

                # Langkah 3: Menyiapkan Prompt & Konfigurasi AI
                status_box.write("🧠 **Langkah 3/4:** Menghubungkan ke Gemini 2.5 Flash API...")
                prompt_lines = [
                    "Jawab kuis berikut dengan format nomor urut, tuliskan pertanyaan ringkas dan kunci jawaban yang paling tepat secara langsung.\n"
                ]
                for idx, item in enumerate(questions_payload, 1):
                    opts_str = " | ".join(item["options"]) if item["options"] else "Isian Singkat"
                    prompt_lines.append(f"{idx}. {item['question']}\nPilihan: {opts_str}\n")

                full_prompt = "\n".join(prompt_lines)

                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    model_name="gemini-2.5-flash",
                    system_instruction="Kamu adalah asisten penjawab ujian kilat. Berikan format jawaban langsung per nomor dengan jelas dan tegas."
                )

                progress_bar.progress(75)
                status_box.write("⚡ **Langkah 4/4:** AI sedang menganalisis soal & menyusun kunci jawaban...")

                # Mulai streaming ke response
                response = model.generate_content(full_prompt, stream=True)

                progress_bar.progress(100)
                status_box.update(label=f"✅ Selesai! Menampilkan {total_soal} Jawaban", state="complete", expanded=False)

                st.success(f"📌 **{quiz_name}** — {total_soal} Soal Terjawab")
                st.divider()

                # Stream jawaban mengalir langsung ke layar per chunk
                def stream_chunks():
                    for chunk in response:
                        if chunk.text:
                            yield chunk.text

                st.write_stream(stream_chunks())

        except json.JSONDecodeError:
            progress_bar.empty()
            status_box.update(label="❌ Format JSON Tidak Valid", state="error")
            st.error("Format teks bukan JSON yang valid. Pastikan seluruh teks JSON tersalin utuh.")
        except Exception as e:
            progress_bar.empty()
            status_box.update(label="❌ Terjadi Kesalahan", state="error")
            st.error(f"Gagal memproses kuis: {e}")
