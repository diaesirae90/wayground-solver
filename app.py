import json
import os
import re
import google.generativeai as genai
import streamlit as st

st.set_page_config(page_title="Quiz JSON Solver", page_icon="📝", layout="centered")

st.title("📝 Quiz JSON Solver (Via Bookmarklet)")
st.caption("Cukup jalankan Bookmarklet di browser kuis, lalu tempel (Paste) JSON-nya di bawah ini.")

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


def extract_questions_from_json(data: dict) -> tuple:
    """Mengekstrak list pertanyaan dari berbagai format JSON hasil sadapan."""
    raw_questions = None
    quiz_name = "Kuis Wayground / Quizizz"

    # 1. Format Rejoin: data.data.room
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

    # 2. Format Join Standar: data.room
    elif "room" in data and isinstance(data["room"], dict):
        raw_questions = data["room"].get("questions")
        quiz_name = data["room"].get("name", quiz_name)

    # 3. Format langsung data.questions
    elif "questions" in data:
        raw_questions = data["questions"]

    # 4. Format list array langsung
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
            opt_id = opt.get("id") or opt.get("_id") or str(idx)
            opt_text = clean_text(opt.get("text", ""))

            # Handle pilihan gambar
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

    return quiz_name, cleaned_payload


def solve_quiz_with_ai(payload: list, key: str) -> list:
  genai.configure(api_key=key)

  model = genai.GenerativeModel(
      model_name="gemini-2.5-flash",
      system_instruction=(
          "Kamu adalah asisten penjawab kuis cepat. Jawab setiap soal dengan"
          " tepat. Kembalikan HANYA JSON list: [{\"question\": \"teks"
          " ringkas\", \"answer\": \"jawaban\"}]"
      ),
      generation_config={"response_mime_type": "application/json"},
  )

  results = []
  # Bagi soal per batch (10 soal per pemanggilan AI)
  batch_size = 10
  for i in range(0, len(payload), batch_size):
    batch = payload[i : i + batch_size]
    simplified_prompt = "Jawab soal berikut secara tepat:\n\n"
    for idx, q in enumerate(batch, 1):
      simplified_prompt += f"{idx}. {q['question']}\n"
      for opt in q["options"]:
        simplified_prompt += f"   - {opt['text']}\n"
      simplified_prompt += "\n"

    try:
      response = model.generate_content(simplified_prompt)
      parsed_batch = json.loads(response.text)
      results.extend(parsed_batch)
    except Exception:
      continue

  return results


# ==========================================
# UI Streamlit
# ==========================================
raw_json_input = st.text_area(
    "Paste JSON Hasil Bookmarklet di Sini:",
    placeholder='Tekan Ctrl + V di sini setelah menjalankan bookmarklet di kuis...',
    height=240,
)

if st.button("Proses & Dapatkan Jawaban AI", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di sidebar sebelah kiri.")
    elif not raw_json_input.strip():
        st.warning("⚠️ Silakan tempelkan (Paste) data JSON terlebih dahulu.")
    else:
        with st.spinner("Mengekstrak soal & memproses kunci jawaban AI..."):
            try:
                parsed_data = json.loads(raw_json_input)
                quiz_name, questions_payload = extract_questions_from_json(parsed_data)

                if not questions_payload:
                    st.error("Gagal mendeteksi daftar soal dari JSON.")
                else:
                    results = solve_quiz_with_ai(questions_payload, api_key)
                    
                    st.success(f"📌 **{quiz_name}** ({len(results)} Soal Berhasil Dijawab)")
                    st.divider()

                    for idx, item in enumerate(results, 1):
                        with st.expander(f"**{idx}. {item.get('question')}**", expanded=True):
                            st.markdown(f"**Jawaban:** :green[**{item.get('answer')}**]")

            except json.JSONDecodeError:
                st.error("Format teks bukan JSON yang valid. Pastikan menyalin semua teks hasil bookmarklet.")
            except Exception as e:
                st.error(f"Gagal memproses kuis: {e}")
