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

  for domain in domains:
    # 1. Jalur Utama: _gameapi room-codes check
    try:
      r_url = f"{domain}/_gameapi/main/public/v1/room-codes/{code}/check"
      res = session.post(r_url, json={"roomCode": code}, headers=headers, timeout=10)
      if res.status_code == 200:
        data = res.json().get("data", {})
        room = data.get("room", {})
        quiz_name = room.get("name", "Kuis Wayground")

        if "questions" in room and room["questions"]:
          return quiz_name, room["questions"]

        # Jika ada data quizzes
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

    # 3. Jalur Ketiga: play-api/v5/checkAssignment (Mode Tugas)
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
              return q_name, {q.get("_id", str(i)): q for i, q in enumerate(q_list)}
    except Exception:
      pass

  raise ValueError(
      f"Kuis dengan PIN '{code}' tidak dapat diambil langsung oleh server. Gunakan tab 'Paste JSON (Cadangan)' jika kuis dilindungi."
  )
