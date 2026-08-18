import json
import os
import re
import urllib.parse
import google.generativeai as genai
import requests
import streamlit as st

st.set_page_config(page_title="Quiz Solver App", page_icon="📝", layout="centered")

st.title("📝 Quiz Solver (PIN, Link & JSON)")
st.caption(
    "Mendukung Input Game PIN / Link Kuis langsung & Mode Cadangan Paste JSON."
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


def parse_clean_code(raw_input: str) -> str:
  text = raw_input.strip()
  while "%" in text:
    new_text = urllib.parse.unquote(text)
    if new_text == text:
      break
    text = new_text

  # Tangkap parameter gc= (Game Code)
  match_gc = re.search(r"gc=([0-9a-zA-Z]+)", text)
  if match_gc:
    return match_gc.group(1)

  # Tangkap 6-8 digit angka PIN murni
  match_pin = re.search(r"\b(\d{6,8})\b", text)
  if match_pin:
    return match_pin.group(1)

  # Tangkap link join path
  match_game = re.search(r"/join/game/([^?&#]+)", text)
  if match_game:
    return match_game.group(1)

  return text


def fetch_questions_from_api(raw_input: str) -> tuple:
  code = parse_clean_code(raw_input)
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/124.0.0.0 Safari/537.36"
      ),
      "Content-Type": "application/json",
      "Accept": "application/json, text/plain, */*",
      "Origin": "https://wayground.com",
      "Referer": "https://wayground.com/join",
  }

  domains = ["https://wayground.com", "https://quizizz.com"]

  # 1. Cek Room via checkRoom menggunakan Game PIN / Code
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
        room = data.get("room", {})
        quiz_name = room.get("name", "Kuis Live")

        # Jika questions langsung tersedia di room
        if "questions" in room and room["questions"]:
          return quiz_name, room["questions"]

        # Jika ada hash room, ambil via _gameapi
        room_hash = room.get("hash")
        if room_hash:
          g_res = requests.get(
              f"{domain}/_gameapi/main/public/v1/students/games/{room_hash}",
              headers=headers,
              timeout=10,
          )
          if g_res.status_code == 200:
            g_data = g_res.json()
            quizzes = g_data.get("data", {}).get("quizzes", {})
            if quizzes:
              first_key = next(iter(quizzes))
              return (
                  quizzes[first_key].get("info", {}).get("name", quiz_name),
                  quizzes[first_key].get("questions", {}),
              )
    except Exception:
      continue

  raise ValueError(
      f"Kuis dengan PIN '{code}' tidak ditemukan atau sesi room belum dimulai"
      " oleh host."
  )


def parse_questions_dict(raw_questions: dict, quiz_name: str = "Kuis") -> list:
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
      opt_id = opt.get("id") or opt.get("_id") or str(idx)
      opt_text = clean_text(opt.get("text", ""))

      if not opt_text and opt.get("media"):
        media_url = opt.get("media", [{}])[0].get("url", "")
        opt_text = f"[Opsi Gambar: {media_url}]"

      if opt_text:
        options.append({"id": opt_id, "text": opt_text})

    if query_text:
      cleaned_payload.append(
          {"id": str(q_id), "question": query_text, "options": options}
      )

  return cleaned_payload


def solve_quiz_with_ai(payload: list, key: str) -> list:
  genai.configure(api_key=key)

  system_instruction = """
    Kamu adalah asisten penjawab kuis dan ujian.
    Analisis setiap pertanyaan dan pilih opsi jawaban yang paling tepat.
    Kembalikan HANYA format JSON valid list objek murni:
    [{"question": "teks pertanyaan", "answer": "jawaban yang benar"}]
    """

  # Fallback model jika versi API berbeda
  candidate_models = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-pro"]
  last_err = None

  for model_name in candidate_models:
    try:
      model = genai.GenerativeModel(
          model_name=model_name,
          system_instruction=system_instruction,
          generation_config={"response_mime_type": "application/json"},
      )
      response = model.generate_content(json.dumps(payload))
      return json.loads(response.text)
    except Exception as e:
      last_err = e
      continue

  raise last_err


# ==========================================
# UI Streamlit (Tab Pilihan Input)
# ==========================================
tab1, tab2 = st.tabs(["🔗 Input PIN / Link Kuis", "📋 Paste JSON (Cadangan)"])

with tab1:
  user_input_link = st.text_input(
      "Game PIN atau Link Join:",
      value="https://wayground.com/join?gc=052116&source=liveDashboard",
      placeholder="Masukkan PIN (contoh: 052116) atau link join...",
  )
  btn_link = st.button(
      "Dapatkan Jawaban (By Link/PIN)",
      type="primary",
      use_container_width=True,
      key="btn_link",
  )

with tab2:
  user_input_json = st.text_area(
      "Paste Respon JSON DevTools:",
      placeholder='{"data": {"room": {"questions": {...}}}}',
      height=200,
  )
  btn_json = st.button(
      "Proses JSON", type="primary", use_container_width=True, key="btn_json"
  )

# Eksekusi Tab 1 (Link/PIN)
if btn_link:
  api_key = api_key_input.strip()
  if not api_key:
    st.error("⚠️ Masukkan Gemini API Key di sidebar.")
  elif not user_input_link.strip():
    st.warning("⚠️ Masukkan PIN atau Link terlebih dahulu.")
  else:
    with st.spinner("Mengambil bank soal dari server & memproses jawaban..."):
      try:
        q_name, raw_q = fetch_questions_from_api(user_input_link)
        payload = parse_questions_dict(raw_q, q_name)

        results = solve_quiz_with_ai(payload, api_key)
        st.success(f"📌 **{q_name}** ({len(results)} Soal Ditemukan)")
        st.divider()

        for idx, item in enumerate(results, 1):
          with st.expander(
              f"**{idx}. {item.get('question')}**", expanded=True
          ):
            st.markdown(f"**Jawaban:** :green[**{item.get('answer')}**]")
      except Exception as e:
        st.error(f"Gagal mengambil kuis via link/PIN: {e}")
        st.info(
            "💡 Jika sesi live dikunci host sebelum mulai, gunakan Tab 'Paste"
            " JSON (Cadangan)'."
        )

# Eksekusi Tab 2 (JSON Paste)
if btn_json:
  api_key = api_key_input.strip()
  if not api_key:
    st.error("⚠️ Masukkan Gemini API Key di sidebar.")
  elif not user_input_json.strip():
    st.warning("⚠️ Paste data JSON terlebih dahulu.")
  else:
    with st.spinner("Mengekstrak JSON & memproses jawaban..."):
      try:
        data = json.loads(user_input_json)
        # Ekstrak questions dari struktur data
        raw_q = (
            data.get("data", {}).get("room", {}).get("questions")
            or data.get("room", {}).get("questions")
            or data.get("questions")
        )
        q_name = (
            data.get("data", {}).get("room", {}).get("name")
            or data.get("room", {}).get("name")
            or "Kuis"
        )

        if not raw_q:
          st.error("Struktur 'questions' tidak ditemukan dalam JSON.")
        else:
          payload = parse_questions_dict(raw_q, q_name)
          results = solve_quiz_with_ai(payload, api_key)

          st.success(f"📌 **{q_name}** ({len(results)} Soal Ditemukan)")
          st.divider()

          for idx, item in enumerate(results, 1):
            with st.expander(
                f"**{idx}. {item.get('question')}**", expanded=True
            ):
              st.markdown(f"**Jawaban:** :green[**{item.get('answer')}**]")
      except Exception as e:
        st.error(f"Gagal memproses JSON: {e}")
