import json
import re
import urllib.parse
import requests
import streamlit as st


def parse_clean_code(raw_input: str) -> str:
    text = raw_input.strip()

    # 1. Lakukan unquote berkali-kali sampai bersih dari %25, %2F, %3D, dll.
    while "%" in text:
        new_text = urllib.parse.unquote(text)
        if new_text == text:
            break
        text = new_text

    # 2. Tangkap token U2Fsd (bisa panjang dan mengandung karakter base64 +, /, =)
    match_salted = re.search(r"(U2FsdGVkX1[A-Za-z0-9+/=]+)", text)
    if match_salted:
        return match_salted.group(1)

    # 3. Tangkap format parameter URL lainnya
    match_gc = re.search(r"gc=([0-9a-zA-Z]+)", text)
    if match_gc:
        return match_gc.group(1)

    match_game = re.search(r"/join/game/([^?&#]+)", text)
    if match_game:
        return match_game.group(1)

    match_pin = re.search(r"\b(\d{6,8})\b", text)
    if match_pin:
        return match_pin.group(1)

    return text


def get_quiz_questions(raw_input: str) -> dict:
    code = parse_clean_code(raw_input)

    session = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://wayground.com",
        "Referer": "https://wayground.com/join",
    }

    domains = ["https://wayground.com", "https://quizizz.com"]

    # =========================================================
    # JALUR 1: Jika Token adalah U2Fsd (Enkripsi Solo/Assigned/Live Link)
    # =========================================================
    if code.startswith("U2Fsd"):
        for domain in domains:
            # 1. Coba via soloJoin
            try:
                res = session.post(
                    f"{domain}/play-api/v4/soloJoin",
                    json={"game": code},
                    headers=headers,
                    timeout=10,
                )
                if res.status_code == 200:
                    data = res.json()
                    quiz_id = (
                        data.get("quizId")
                        or data.get("data", {}).get("quizId")
                        or data.get("room", {}).get("quizId")
                    )

                    # Cek jika soal langsung ada di response
                    if "questions" in data:
                        return data["questions"]

                    if quiz_id:
                        q_res = session.get(
                            f"{domain}/api/main/quiz/{quiz_id}",
                            headers=headers,
                            timeout=10,
                        )
                        if q_res.status_code == 200:
                            q_list = (
                                q_res.json()
                                .get("data", {})
                                .get("quiz", {})
                                .get("info", {})
                                .get("questions", [])
                            )
                            if q_list:
                                return {
                                    q.get("_id", str(i)): q
                                    for i, q in enumerate(q_list)
                                }
            except Exception:
                pass

            # 2. Coba via checkRoom menggunakan hash code
            try:
                res = session.post(
                    f"{domain}/play-api/v5/checkRoom",
                    json={"roomHash": code},
                    headers=headers,
                    timeout=10,
                )
                if res.status_code == 200:
                    data = res.json()
                    questions = data.get("room", {}).get("questions")
                    if questions:
                        return questions
            except Exception:
                pass

    # =========================================================
    # JALUR 2: Jika PIN 6-8 Digit Biasa
    # =========================================================
    for domain in domains:
        try:
            res = session.post(
                f"{domain}/play-api/v5/checkRoom",
                json={"roomCode": code},
                headers=headers,
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                questions = data.get("room", {}).get("questions")
                if questions:
                    return questions

                room_hash = data.get("room", {}).get("hash")
                if room_hash:
                    url = f"{domain}/_gameapi/main/public/v1/students/games/{room_hash}"
                    g_res = session.get(url, headers=headers, timeout=10)
                    if g_res.status_code == 200:
                        g_data = g_res.json()
                        quizzes = g_data.get("data", {}).get("quizzes", {})
                        if quizzes:
                            first_key = next(iter(quizzes))
                            return quizzes[first_key].get("questions", {})
        except Exception:
            continue

    raise ValueError(
        "Kuis tidak ditemukan. Sesi live mungkin sudah ditutup atau memerlukan"
        " login student."
    )
