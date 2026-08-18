import json
import os
import re
import google.generativeai as genai
import streamlit as st

st.set_page_config(page_title="Quiz Solver Kilat", page_icon="⚡", layout="centered")

st.title("⚡ Quiz Solver (Super Cepat)")
st.caption("Optimasi Latensi Rendah: Mampu memproses 50+ soal dalam hitungan detik.")

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
    # Hapus tag HTML & spasi berlebih
    text = re.sub(r"<.*?>", "", str(raw_html))
    return " ".join(text.split()).strip()


def extract_questions_from_json(data: dict) -> tuple:
  """Mengekstrak list pertanyaan dari berbagai format JSON Quizizz / Wayground."""
  raw_questions = None
  quiz_name = "Kuis Wayground / Quizizz"

  # 1. Format Rejoin / Check: data.data.room
  if "data" in data and isinstance(data["data"], dict):
    d_room = data["data"].get("room", {})
    if "questions" in d_room:
      raw_questions = d_room.get("questions")
      quiz_name = d_room.get("name", quiz_name)
    elif "quizzes" in data["data"] and data["data"]["quizzes"]:
      first_key = next(iter(data["data"]["quizzes"]))
      raw_questions = data["data"]["quizzes"][first_key].get("questions")
      quiz_name = data["data"]["quizzes"][first_key].get(
          "info", {}
      ).get("name", quiz_name)
    elif "quiz" in data["data"]:
      raw_questions = (
          data["data"].get("quiz", {}).get("info", {}).get("questions")
      )
      quiz_name = (
          data["data"].get("quiz", {}).get("info", {}).get("name", quiz_name)
      )

  # 2. Format Join Standar: data.room
  elif "room" in data and isinstance(data["room"], dict):
    raw_questions = data["room"].get("questions")
    quiz_name = data["room"].get("name", quiz_name)

  # 3. Format langsung data.questions
  elif "questions" in data and data["questions"]:
    raw_questions = data["questions"]

  # 4. Format List Array Attempt (Otomatis Ambil via Game ID)
  if not raw_questions:
    game_id = None
    if isinstance(data, dict):
      game_id = data.get("gameId") or data.get("data", {}).get("gameId")
    elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
      game_id = data[0].get("gameId")

    if game_id:
      try:
        g_res = requests.get(
            f"https://wayground.com/_gameapi/main/public/v1/students/games/{game_id}",
            timeout=10,
        )
        if g_res.status_code == 200:
          g_data = g_res.json().get("data", {})
          quizzes = g_data.get("quizzes", {})
          if quizzes:
            first_key = next(iter(quizzes))
            quiz_name = quizzes[first_key].get("info", {}).get("name", quiz_name)
            raw_questions = quizzes[first_key].get("questions", {})
      except Exception:
        pass

  if not raw_questions:
    raise ValueError(
        "Struktur 'questions' tidak ditemukan dalam JSON. Pastikan menyalin"
        " respon dari request 'rejoin' atau 'join'."
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
      if not opt_text and opt.get("media"):
        media_url = opt.get("media", [{}])[0].get("url", "")
        opt_text = f"[Gambar: {media_url}]"

      if opt_text:
        options.append(opt_text)

    if query_text:
      cleaned_payload.append({"question": query_text, "options": options})

  return quiz_name, cleaned_payload


def solve_quiz_fast(payload: list, key: str) -> list:
    """Menggunakan format prompt teks ringkas agar inferensi AI berlangsung sangat cepat."""
    genai.configure(api_key=key)

    # Format teks super padat agar token hemat & respons instan
    prompt_lines = ["Jawab kuis pilihan ganda berikut secara singkat dan tepat:\n"]
    for idx, item in enumerate(payload, 1):
        opts_str = " | ".join(item["options"]) if item["options"] else "Tanpa Opsi"
        prompt_lines.append(f"{idx}. {item['question']}\nPilihan: {opts_str}\n")

    full_prompt = "\n".join(prompt_lines)

    system_instruction = """
    Kamu adalah asisten penjawab ujian kilat.
    Tentukan jawaban yang paling benar dari pilihan yang diberikan.
    Format respon WAJIB HANYA berupa JSON valid list:
    [{"question": "teks pertanyaan", "answer": "jawaban yang benar"}]
    """

    # Menggunakan model tercepat
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
    placeholder='{"room": {"name": "...", "questions": { ... }}}',
    height=250,
)

if st.button("⚡ Proses Jawaban Kilat", type="primary", use_container_width=True):
    api_key = api_key_input.strip()

    if not api_key:
        st.error("⚠️ Masukkan Gemini API Key di sidebar sebelah kiri.")
    elif not raw_json_input.strip():
        st.warning("⚠️ Silakan tempelkan data JSON kuis terlebih dahulu.")
    else:
        with st.spinner("Menganalisis soal & memproses kunci jawaban..."):
            try:
                parsed_data = json.loads(raw_json_input)
                quiz_name, questions_payload = extract_questions_from_json(parsed_data)

                if not questions_payload:
                    st.error("Daftar pertanyaan tidak ditemukan dalam JSON.")
                else:
                    results = solve_quiz_fast(questions_payload, api_key)
                    
                    st.success(f"📌 **{quiz_name}** — {len(results)} Soal Berhasil Dijawab!")
                    st.divider()

                    for idx, item in enumerate(results, 1):
                        with st.expander(f"**{idx}. {item.get('question')}**", expanded=True):
                            st.markdown(f"**Jawaban:** :green[**{item.get('answer')}**]")

            except json.JSONDecodeError:
                st.error("Format teks bukan JSON yang valid. Pastikan semua teks tersalin utuh.")
            except Exception as e:
                st.error(f"Gagal memproses kuis: {e}")
