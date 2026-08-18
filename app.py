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

  # 1. Hash dari URL Rejoin / Game API (24 karakter hex)
  match_rejoin = re.search(r"/games/([a-f0-9]{24})", text)
  if match_rejoin:
    return match_rejoin.group(1)

  # 2. Parameter gc= (Game Code)
  match_gc = re.search(r"gc=([0-9a-zA-Z]+)", text)
  if match_gc:
    return match_gc.group(1)

  # 3. 6-8 digit angka PIN murni
  match_pin = re.search(r"\b(\d{6,8})\b", text)
  if match_pin:
    return match_pin.group(1)

  # 4. Token U2Fsd (AES Encrypted)
  match_salted = re.search(r"(U2FsdGVkX1[A-Za-z0-9+/=]+)", text)
  if match_salted:
    return match_salted.group(1)

  # 5. Link join path biasa
  match_game = re.search(r"/join/game/([^?&#]+)", text)
  if match_game:
    return match_game.group(1)

  return text


def fetch_questions_from_api(raw_input: str) -> tuple:
  code = parse_clean_code(raw_input)
  session = requests.Session()

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

  # Kasus A: Jika input berupa Quiz ID langsung (24 karakter hex)
  if len(code) == 24 and re.match(r"^[a-f0-9]{24}$", code):
    for domain in domains:
      try:
        res = session.get(
            f"{domain}/api/main/quiz/{code}", headers=headers, timeout=10
        )
        if res.status_code == 200:
          data = res.json().get("data", {}).get("quiz", {})
          q_list = data.get("info", {}).get("questions", [])
          q_name = data.get("info", {}).get("name", "Kuis Quizizz")
          if q_list:
            return q_name, {
                q.get("_id", str(i)): q for i, q in enumerate(q_list)
            }
      except Exception:
        pass

  # Kasus B: Pencarian bertingkat via PIN / Room Code
  for domain in domains:
    # 1. Jalur Utama: _gameapi room-codes check
    try:
      r_url = f"{domain}/_gameapi/main/public/v1/room-codes/{code}/check"
      res = session.post(
          r_url, json={"roomCode": code}, headers=headers, timeout=10
      )
      if res.status_code == 200:
        data = res.json().get("data", {})
        room = data.get("room", {})
        quiz_name = room.get("name", "Kuis Wayground")

        if "questions" in room and room["questions"]:
          return quiz_name, room["questions"]

        quizzes = data.get("quizzes", {})
        if quizzes:
          first_key = next(iter(quizzes))
          return (
              quizzes[first_key].get("info", {}).get("name", quiz_name),
              quizzes[first_key].get("questions", {}),
          )
    except Exception:
      pass

    # 2. Jalur Kedua: play-api/v5/checkRoom
    try:
      res = session.post(
          f"{domain}/play-api/v5/checkRoom",
          json={"roomCode": code},
          headers=headers,
          timeout=10,
      )
      if res.status_code == 200:
        data = res.json()
        room = data.get("room", {})
        quiz_name = room.get("name", "Kuis Live")

        if "questions" in room and room["questions"]:
          return quiz_name, room["questions"]

        room_hash = room.get("hash")
        if room_hash:
          g_res = session.get(
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
      pass

    # 3. Jalur Ketiga: play-api/v5/checkAssignment (Mode Tugas/Homework)
    try:
      res = session.post(
          f"{domain}/play-api/v5/checkAssignment",
          json={"roomCode": code},
          headers=headers,
          timeout=10,
      )
      if res.status_code == 200:
        data = res.json()
        room = data.get("room", {})
        quiz_id = room.get("quizId")
        if quiz_id:
          q_res = session.get(
              f"{domain}/api/main/quiz/{quiz_id}", headers=headers, timeout=10
          )
          if q_res.status_code == 200:
            q_data = q_res.json().get("data", {}).get("quiz", {})
            q_list = q_data.get("info", {}).get("questions", [])
            q_name = q_data.get("info", {}).get("name", "Kuis Tugas")
            if q_list:
              return q_name, {
                  q.get("_id", str(i)): q for i, q in enumerate(q_list)
              }
    except Exception:
      pass

    # 4. Jalur Keempat: play-api/v4/soloJoin (Jika token U2Fsd)
    if code.startswith("U2Fsd"):
      try:
        res = session.post(
            f"{domain}/play-api/v4/soloJoin",
            json={"game": code},
            headers=headers,
            timeout=10,
        )
        if res.status_code == 200:
          data = res.json()
          quiz_id = data.get("quizId") or data.get("data", {}).get("quizId")
          if quiz_id:
            q_res = session.get(
                f"{domain}/api/main/quiz/{quiz_id}", headers=headers, timeout=10
            )
            if q_res.status_code == 200:
              q_data = q_res.json().get("data", {}).get("quiz", {})
              q_list = q_data.get("info", {}).get("questions", [])
              q_name = q_data.get("info", {}).get("name", "Kuis Solo")
              if q_list:
                return q_name, {
                    q.get("_id", str(i)): q for i, q in enumerate(q_list)
                }
      except Exception:
        pass

  raise ValueError(
      f"Kuis dengan kode '{code}' tidak dapat diambil langsung oleh server."
      " Jika kuis dilindungi, silakan gunakan tab 'Paste JSON (Cadangan)'."
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

      # Tangani jika opsi berupa media/gambar
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
    Analisis setiap pertanyaan dan pilih opsi jawaban yang paling tepat dari pilihan yang tersedia.
    Kembalikan HANYA format JSON valid list objek murni:
    [{"question": "teks pertanyaan", "answer": "jawaban yang benar"}]
    """

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
# UI Streamlit
# ==========================================
tab1, tab2 = st.tabs(["🔗 Input PIN / Link Kuis", "📋 Paste JSON (Cadangan)"])

with tab1:
  user_input_link = st.text_input(
      "Game PIN atau Link Join:",
      placeholder="Masukkan PIN (contoh: 20115513) atau link kuis...",
  )
  btn_link = st.button(
      "Dapatkan Jawaban (By Link/PIN)",
      type="primary",
      use_container_width=True,
      key="btn_link",
  )

with tab2:
  user_input_json = st.text_area(
      "Paste Respon JSON DevTools (Network):",
      placeholder='{"data": {"room": {"questions": {...}}}}',
      height=220,
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
    with st.spinner("Menghubungkan ke API & menganalisis bank soal..."):
      try:
        q_name, raw_q = fetch_questions_from_api(user_input_link)
        payload = parse_questions_dict(raw_q, q_name)

        if not payload:
          st.error("Daftar pertanyaan kosong atau tidak dapat diuraikan.")
        else:
          results = solve_quiz_with_ai(payload, api_key)
          st.success(f"📌 **{q_name}** ({len(results)} Soal Berhasil Dijawab)")
          st.divider()

          for idx, item in enumerate(results, 1):
            with st.expander(
                f"**{idx}. {item.get('question')}**", expanded=True
            ):
              st.markdown(f"**Jawaban:** :green[**{item.get('answer')}**]")
      except Exception as e:
        st.error(f"Gagal mengambil kuis via link/PIN: {e}")
        st.info(
            "💡 Jika sesi live dilindungi Cloudflare / terkunci sebelum mulai,"
            " gunakan Tab 'Paste JSON (Cadangan)'."
        )

# Eksekusi Tab 2 (JSON Paste)
if btn_json:
  api_key = api_key_input.strip()
  if not api_key:
    st.error("⚠️ Masukkan Gemini API Key di sidebar.")
  elif not user_input_json.strip():
    st.warning("⚠️ Paste data JSON terlebih dahulu.")
  else:
    with st.spinner("Mengekstrak JSON & memproses jawaban AI..."):
      try:
        data = json.loads(user_input_json)
        # Ekstrak data questions dari berbagai format respon
        raw_q = (
            data.get("data", {}).get("room", {}).get("questions")
            or data.get("data", {}).get("quizzes", {})
            or data.get("room", {}).get("questions")
            or data.get("questions")
        )

        q_name = (
            data.get("data", {}).get("room", {}).get("name")
            or data.get("room", {}).get("name")
            or "Kuis Wayground"
        )

        # Jika format _gameapi quizzes
        if (
            isinstance(raw_q, dict)
            and raw_q
            and "questions" not in raw_q
            and any("questions" in v for v in raw_q.values() if isinstance(v, dict))
        ):
          first_key = next(iter(raw_q))
          q_name = raw_q[first_key].get("info", {}).get("name", q_name)
          raw_q = raw_q[first_key].get("questions", {})

        if not raw_q:
          st.error("Struktur 'questions' tidak ditemukan dalam JSON.")
        else:
          payload = parse_questions_dict(raw_q, q_name)
          results = solve_quiz_with_ai(payload, api_key)

          st.success(f"📌 **{q_name}** ({len(results)} Soal Berhasil Dijawab)")
          st.divider()

          for idx, item in enumerate(results, 1):
            with st.expander(
                f"**{idx}. {item.get('question')}**", expanded=True
            ):
              st.markdown(f"**Jawaban:** :green[**{item.get('answer')}**]")
      except json.JSONDecodeError:
        st.error(
            "Teks yang ditempel bukan JSON yang valid. Pastikan menyalin"
            " seluruh teks respon."
        )
      except Exception as e:
        st.error(f"Gagal memproses JSON: {e}")
