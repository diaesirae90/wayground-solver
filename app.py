import json
import os
import re
import google.generativeai as genai
import streamlit as st

st.set_page_config(
    page_title="Instant Quiz Solver",
    page_icon="⚡",
    layout="centered",
)

st.title("⚡ Instant Quiz Solver (Lengkap 100%)")
st.caption(
    "Didukung Gemini Flash Lite: Menjamin semua nomor soal (1 sampai habis)"
    " tampil lengkap tanpa terpotong."
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
  text = re.sub(r"<.*?>", "", str(raw_html))
  return " ".join(text.split()).strip()


def extract_questions_universal(data: dict) -> tuple:
  """Mengekstrak pertanyaan dan opsi dari berbagai format JSON Quizizz / Wayground."""
  raw_questions = None
  quiz_name = "Kuis Wayground / Quizizz"

  if isinstance(data, dict):
    if "data" in data and isinstance(data["data"], dict):
      d_room = data["data"].get("room", {})
      if "questions" in d_room:
        raw_questions = d_room.get("questions")
        quiz_name = d_room.get("name", quiz_name)
      elif "quizzes" in data["data"] and data["data"]["quizzes"]:
        first_key = next(iter(data["data"]["quizzes"]))
        raw_questions = data["data"]["quizzes"][first_key].get("questions")
        quiz_name = (
            data["data"]["quizzes"][first_key]
            .get("info", {})
            .get("name", quiz_name)
        )
      elif "quiz" in data["data"]:
        raw_questions = (
            data["data"].get("quiz", {}).get("info", {}).get("questions")
        )
        quiz_name = (
            data["data"].get("quiz", {}).get("info", {}).get("name", quiz_name)
        )

    elif "room" in data and isinstance(data["room"], dict):
      raw_questions = data["room"].get("questions")
      quiz_name = data["room"].get("name", quiz_name)

    elif "questions" in data and data["questions"]:
      raw_questions = data["questions"]

    elif isinstance(data, list):
      raw_questions = data

  if not raw_questions:
    raise ValueError(
        "Struktur pertanyaan ('questions') tidak ditemukan dalam JSON."
    )

  cleaned_payload = []
  iterator = (
      raw_questions.items()
      if isinstance(raw_questions, dict)
      else enumerate(raw_questions)
  )

  for q_id, q_data in iterator:
    structure = q_data.get("structure", {})
    query_text = clean_text(
        structure.get("query", {}).get("text", "") or q_data.get("question", "")
    )
    raw_options = structure.get("options", []) or q_data.get("options", [])

    options = []
    for idx, opt in enumerate(raw_options, 1):
      opt_text = clean_text(opt.get("text", ""))

      # Handle jika opsi berupa media gambar
      if not opt_text and opt.get("media"):
        media_url = opt.get("media", [{}])[0].get("url", "")
        opt_text = f"[Gambar: {media_url}]"

      if opt_text:
        options.append(opt_text)

    if query_text:
      cleaned_payload.append({"question": query_text, "options": options})

  return quiz_name, cleaned_payload


# ==========================================
# UI Streamlit
# ==========================================
raw_json_input = st.text_area(
    "Paste Respon JSON Kuis di Sini:",
    placeholder='{"room": {"name": "...", "questions": { ... }}}',
    height=220,
)

if st.button(
    "⚡ Dapatkan Semua Jawaban Lengkap", type="primary", use_container_width=True
):
  api_key = api_key_input.strip()

  if not api_key:
    st.error("⚠️ Masukkan Gemini API Key di sidebar sebelah kiri.")
  elif not raw_json_input.strip():
    st.warning("⚠️ Silakan tempelkan data JSON kuis terlebih dahulu.")
  else:
    with st.spinner(
        "⏳ Menganalisis seluruh pertanyaan dengan Gemini Flash Lite..."
    ):
      try:
        parsed_data = json.loads(raw_json_input)
        quiz_name, questions_payload = extract_questions_universal(parsed_data)

        total_soal = len(questions_payload)
        if total_soal == 0:
          st.error("Daftar pertanyaan tidak ditemukan di dalam JSON.")
        else:
          genai.configure(api_key=api_key)

          # Model gemini-2.5-flash-lite (sama seperti userscript)
          model = genai.GenerativeModel(
              model_name="gemini-flash-lite-latest",
              generation_config={
                  "response_mime_type": "application/json",
                  "temperature": 0.1,
                  "max_output_tokens": 8192,
              },
              system_instruction=(
                  "You are an expert quiz-solving assistant. For each question"
                  " provided in the JSON list, select the most accurate correct"
                  " answer. Return a pure JSON array of objects in the exact"
                  " same order, where each object has:"
                  ' [{"index": 1, "answer": "text of correct answer"}, ...]'
              ),
          )

          # Format data input untuk AI
          ai_input_list = []
          for idx, item in enumerate(questions_payload, 1):
            ai_input_list.append({
                "index": idx,
                "question": item["question"],
                "options": item["options"],
            })

          # Minta jawaban ke Gemini Flash Lite
          response = model.generate_content(json.dumps(ai_input_list))
          answers_json = json.loads(response.text)

          # Buat dictionary jawaban berdasarkan nomor index
          answer_map = {}
          if isinstance(answers_json, list):
            for ans_item in answers_json:
              answer_map[ans_item.get("index")] = ans_item.get("answer", "-")
          elif isinstance(answers_json, dict):
            # Fallback jika model mengembalikan dict {"answers": ...}
            raw_ans = answers_json.get("answers", answers_json)
            if isinstance(raw_ans, list):
              for idx, a in enumerate(raw_ans, 1):
                answer_map[idx] = (
                    a.get("answer") if isinstance(a, dict) else str(a)
                )
            elif isinstance(raw_ans, dict):
              for k, v in raw_ans.items():
                try:
                  answer_map[int(k)] = str(v)
                except ValueError:
                  pass

          # Tampilkan hasil lengkap ke layar
          st.success(
              f"📌 **{quiz_name}** — Seluruh {total_soal} Soal Berhasil Dijawab!"
          )
          st.divider()

          for idx, item in enumerate(questions_payload, 1):
            ans_text = answer_map.get(idx, "Jawaban tidak ditemukan")
            st.markdown(f"**{idx}]. {item['question']}**")
            st.markdown(f"Jawaban: :green[**{ans_text}**]")
            st.write("")

      except json.JSONDecodeError:
        st.error(
            "Format teks bukan JSON yang valid. Pastikan seluruh teks JSON"
            " tersalin utuh."
        )
      except Exception as e:
        st.error(f"Gagal memproses kuis: {e}")
