import json
import os
import re
import google.generativeai as genai
import streamlit as st

st.set_page_config(page_title="Quiz JSON Solver", page_icon="🧩", layout="centered")

st.title("🧩 Quiz JSON Parser & AI Solver")
st.caption(
    "Metode 100% tembus: Paste langsung respons JSON dari Tab Network (F12)."
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
  return text.strip()


def extract_questions_from_json(data: dict) -> list:
  """Mengekstrak list pertanyaan dari berbagai format payload respons Quizizz."""
  raw_questions = None

  # 1. Format Room / Join endpoint (data.room.questions atau data.questions)
  if "room" in data and isinstance(data["room"], dict):
    raw_questions = data["room"].get("questions")
  elif "questions" in data:
    raw_questions = data["questions"]
  # 2. Format _gameapi (data.data.quizzes)
  elif "data" in data and isinstance(data["data"], dict):
    quizzes = data["data"].get("quizzes", {})
    if quizzes:
      first_key = next(iter(quizzes))
      raw_questions = quizzes[first_key].get("questions")
    elif "quiz" in data["data"]:
      raw_questions = (
          data["data"].get("quiz", {}).get("info", {}).get("questions")
      )

  if not raw_questions:
    # Cek jika input langsung berupa list soal
    if isinstance(data, list):
      raw_questions = data
    else:
      raise ValueError(
          "Struktur pertanyaan tidak ditemukan dalam JSON. Pastikan Anda"
          " meng-copy response dari request 'join', 'checkRoom', atau"
          " '_gameapi'."
      )

  # Standarisasi format list payload untuk AI
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

  return cleaned_payload


def solve_quiz_with_ai(payload: list, key: str) -> list:
  genai.configure(api_key=key)

  system_instruction = """
    Kamu adalah asisten penjawab kuis dan ujian.
    Analisis setiap pertanyaan dan pilih jawaban yang paling tepat dari pilihan opsi yang tersedia.
    Kembalikan HANYA format JSON valid list of objects murni:
    [{"question": "teks pertanyaan", "answer": "jawaban yang benar"}]
    """

  model = genai.GenerativeModel(
      model_name="gemini-1.5-flash",
      system_instruction=system_instruction,
      generation_config={"response_mime_type": "application/json"},
  )

  response = model.generate_content(json.dumps(payload))
  return json.loads(response.text)


# ==========================================
# Input Area
# ==========================================
raw_json_input = st.text_area(
    "Paste Raw JSON Response di sini:",
    placeholder="Contoh: {'room': {'questions': {...}}}",
    height=250,
)

if st.button("Proses & Jawab Soal", type="primary", use_container_width=True):
  api_key = api_key_input.strip()

  if not api_key:
    st.error("⚠️ Masukkan Gemini API Key di sidebar.")
  elif not raw_json_input.strip():
    st.warning("⚠️ Masukkan teks JSON terlebih dahulu.")
  else:
    with st.spinner("Mengekstrak soal & meminta jawaban AI..."):
      try:
        parsed_data = json.loads(raw_json_input)
        questions_payload = extract_questions_from_json(parsed_data)

        if not questions_payload:
          st.error("Gagal mendeteksi teks pertanyaan dari JSON yang diberikan.")
        else:
          results = solve_quiz_with_ai(questions_payload, api_key)
          st.success(f"Berhasil menjawab {len(results)} soal!")
          st.divider()

          for idx, item in enumerate(results, 1):
            with st.expander(
                f"**{idx}. {item.get('question')}**", expanded=True
            ):
              st.markdown(f"**Jawaban:** :green[{item.get('answer')}]")

      except json.JSONDecodeError:
        st.error(
            "Teks yang ditempel bukan format JSON yang valid. Pastikan Anda"
            " menyalin seluruh teks dari tab Response."
        )
      except Exception as e:
        st.error(f"Terjadi kesalahan: {e}")
