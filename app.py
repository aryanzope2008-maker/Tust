# Name: Aryan Zope
# PRN: 26070122053
"""TrustLearn prototype: a privacy-first AI learning layer for colleges.

Run:
    pip install -r requirements.txt
    cp .env.example .env      # fill in real values, this file is gitignored
    python app.py
    open http://127.0.0.1:5000

All student/activity data is synthetic and kept in memory only (resets on restart).
The AI tutor and summarizer call a real external AI API, configured entirely through
environment variables below -- no key ever lives in this source file.
"""
import hashlib
import hmac
import os
import random
import statistics
from datetime import datetime

import requests
from cryptography.fernet import Fernet
from flask import Flask, flash, redirect, render_template, request, session, url_for

try:
    from dotenv import load_dotenv
    load_dotenv()  # loads .env if present; harmless if the file doesn't exist
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get("TRUSTLEARN_SECRET", "dev-only-secret")
SALT = os.environ.get("TRUSTLEARN_SALT", "dev-only-salt").encode()

# ---------------------------------------------------------------------------
# Encryption at rest for anything a student typed (AI chat, free-text notes).
# Key comes from the environment so it is never checked into source control.
# ---------------------------------------------------------------------------
_fernet_key = os.environ.get("TRUSTLEARN_FERNET_KEY")
if not _fernet_key:
    _fernet_key = Fernet.generate_key().decode()
    print("[TrustLearn] No TRUSTLEARN_FERNET_KEY set -- generated a temporary one for this run.\n"
          "[TrustLearn] Encrypted data will not survive a restart until you set it. Add this to .env:\n"
          f"[TrustLearn] TRUSTLEARN_FERNET_KEY={_fernet_key}")
FERNET = Fernet(_fernet_key.encode() if isinstance(_fernet_key, str) else _fernet_key)


def encrypt_text(plain):
    return FERNET.encrypt(plain.encode()).decode()


def decrypt_text(token):
    try:
        return FERNET.decrypt(token.encode()).decode()
    except Exception:
        return "[could not decrypt]"


# ---------------------------------------------------------------------------
# AI API integration. Written against the common OpenAI-style chat-completions
# shape {"messages": [...]} -> {"choices": [{"message": {"content": ...}}]}.
# Swap TRUSTLEARN_AI_BASE_URL / the request+response handling below if your
# provider uses a different schema (Anthropic and Gemini both do).
# ---------------------------------------------------------------------------
AI_API_KEY = os.environ.get("TRUSTLEARN_AI_API_KEY", "")
AI_BASE_URL = os.environ.get("TRUSTLEARN_AI_BASE_URL", "https://api.openai.com/v1/chat/completions")
AI_MODEL = os.environ.get("TRUSTLEARN_AI_MODEL", "gpt-4o-mini")


def call_ai_api(system_prompt, user_text):
    """Call the configured AI API. Always returns text -- a clear fallback message on any failure."""
    if not AI_API_KEY:
        return ("The AI tutor isn't configured yet. Set TRUSTLEARN_AI_API_KEY in your .env file "
                "(see .env.example), then restart the app.")
    try:
        resp = requests.post(
            AI_BASE_URL,
            headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "max_tokens": 400,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log("system", "AI API call failed", str(exc))
        return "The AI tutor couldn't be reached just now. Please try again in a moment."


# ---------------------------------------------------------------------------
# Subjects: 10 questions each. Practice mechanics (hints gated behind one
# attempt, reveal gated behind two) are unchanged from the original prototype.
# ---------------------------------------------------------------------------
SUBJECTS = {
    "python": {"label": "Python basics", "short": "Py", "questions": {
        1: {"q": "What does len([1, 2, 3] * 2) return?", "ans": "6",
            "hints": ["Multiplying a list repeats its items.", "[1, 2, 3] * 2 becomes [1, 2, 3, 1, 2, 3]."]},
        2: {"q": "What is the value of 7 // 2 ?", "ans": "3",
            "hints": ["// is floor division.", "7 / 2 is 3.5. Floor means round down."]},
        3: {"q": "How many numbers does range(2, 10, 3) produce?", "ans": "3",
            "hints": ["The third argument is the step.", "List them: 2, 5, 8. What would come next?"]},
        4: {"q": "What type does 3 / 2 produce in Python 3?", "ans": "float",
            "hints": ["/ is true division, not floor division.", "True division always keeps the decimal part."]},
        5: {"q": "What is list(range(5))[-1] ?", "ans": "4",
            "hints": ["range(5) counts 0, 1, 2, 3, 4.", "-1 means the last item in the list."]},
        6: {"q": "What is \"abc\"[1] ?", "ans": "b",
            "hints": ["String indexing starts at 0.", "Index 0 is 'a', index 1 is..."]},
        7: {"q": "What is bool([]) ?", "ans": "false",
            "hints": ["An empty container is falsy in Python.", "[] has no items, so it behaves like False."]},
        8: {"q": "What does sum([1, 2, 3]) return?", "ans": "6",
            "hints": ["sum() adds every item in the list.", "1 + 2 + 3 = ?"]},
        9: {"q": "What is 2 ** 5 ?", "ans": "32",
            "hints": ["** is exponentiation.", "2*2*2*2*2 = ?"]},
        10: {"q": "What is len(\"Hello\") ?", "ans": "5",
             "hints": ["len() counts characters in a string.", "Count the letters in Hello."]},
    }},
    "maths": {"label": "Maths", "short": "Mx", "questions": {
        1: {"q": "What is the derivative of x^2 with respect to x?", "ans": "2x",
            "hints": ["Use the power rule: d/dx(x^n) = n*x^(n-1).", "Here n = 2, so it becomes 2 * x^1."]},
        2: {"q": "What is the square root of 144?", "ans": "12",
            "hints": ["Think of a number multiplied by itself.", "12 * 12 = 144."]},
        3: {"q": "What is 5! (5 factorial)?", "ans": "120",
            "hints": ["Factorial multiplies all whole numbers up to it.", "5 x 4 x 3 x 2 x 1 = ?"]},
        4: {"q": "What is sin(90 degrees)?", "ans": "1",
            "hints": ["Think of the sine curve's peak value.", "sin(90 deg) is the maximum value sine reaches."]},
        5: {"q": "For x^2 - 5x + 6 = 0, what is the sum of the two roots?", "ans": "5",
            "hints": ["For ax^2+bx+c=0, the sum of roots is -b/a.", "Here b = -5 and a = 1."]},
        6: {"q": "What is log base 10 of 1000?", "ans": "3",
            "hints": ["Ask: 10 to what power gives 1000?", "10^3 = 1000."]},
        7: {"q": "Area of a circle with radius 7 (use pi = 22/7)?", "ans": "154",
            "hints": ["Area = pi * r^2.", "22/7 * 7 * 7 = 22 * 7."]},
        8: {"q": "What is 15% of 200?", "ans": "30",
            "hints": ["15% means 15/100.", "200 * 0.15 = ?"]},
        9: {"q": "What is the GCD of 12 and 18?", "ans": "6",
            "hints": ["List the factors of each number.", "Both divide evenly by 6."]},
        10: {"q": "What is pi to two decimal places?", "ans": "3.14",
             "hints": ["It's a famous irrational number.", "It starts 3.14159..."]},
    }},
    "physics": {"label": "Physics", "short": "Ph", "questions": {
        1: {"q": "What is the SI unit of force?", "ans": "newton",
            "hints": ["It's named after a famous physicist.", "F = ma is measured in this unit."]},
        2: {"q": "An object travels 100 m in 20 s. What is its speed in m/s?", "ans": "5",
            "hints": ["Speed = distance / time.", "100 / 20 = ?"]},
        3: {"q": "What is the approximate value of g near Earth's surface, in m/s^2?", "ans": "9.8",
            "hints": ["It's the acceleration due to gravity.", "It's close to 9.8, not 10 exactly."]},
        4: {"q": "Using F = ma, with mass = 2 kg and acceleration = 3 m/s^2, what is F?", "ans": "6",
            "hints": ["Multiply mass by acceleration.", "2 * 3 = ?"]},
        5: {"q": "What is the SI unit of power?", "ans": "watt",
            "hints": ["It's named after an engineer who improved the steam engine.", "Power = energy per second, in this unit."]},
        6: {"q": "Using Ohm's law V = IR, with I = 2 A and R = 5 ohm, what is V?", "ans": "10",
            "hints": ["Multiply current by resistance.", "2 * 5 = ?"]},
        7: {"q": "The speed of light is about 3 x 10^? m/s. What is the exponent?", "ans": "8",
            "hints": ["It's roughly 300,000,000 m/s.", "300,000,000 is 3 followed by 8 zeros."]},
        8: {"q": "Newton's first law is about an object's resistance to change in motion -- what is this property called?", "ans": "inertia",
            "hints": ["It starts with 'in'.", "It's why you lurch forward when a bus brakes suddenly."]},
        9: {"q": "What is the SI unit of energy?", "ans": "joule",
            "hints": ["It's named after a 19th-century physicist.", "Work and energy share this unit."]},
        10: {"q": "Kinetic energy = 1/2 * m * v^2. With m = 2 kg and v = 3 m/s, what is KE?", "ans": "9",
             "hints": ["First square the velocity: 3^2 = 9.", "0.5 * 2 * 9 = ?"]},
    }},
}
STUDENTS, AUDIT, DECISIONS, CHATS = {}, [], {}, {}
ATTRS = {"Department": "dept", "Gender": "gender", "Language background": "lang", "Rural or urban": "area"}


def pseudonymize(student_id):
    """One-way keyed hash: the real ID never enters the learning data."""
    return hmac.new(SALT, student_id.encode(), hashlib.sha256).hexdigest()[:10]


def log(actor, action, detail=""):
    AUDIT.insert(0, {"time": datetime.now().strftime("%d %b %H:%M:%S"),
                     "actor": actor, "action": action, "detail": detail})


def make_event(subject, qid, hints, revealed, days_ago):
    score = 0 if revealed else max(0, 1 - 0.35 * hints)  # fewer hints = more self-reliant
    return {"subject": subject, "qid": qid, "hints": hints, "revealed": revealed,
            "days_ago": days_ago, "score": round(score, 2)}


def seed():
    """Create one demo student plus 60 synthetic students (rural students get less steady activity)."""
    rnd = random.Random(42)
    demo = pseudonymize("DEMO-001")
    STUDENTS[demo] = {"dept": "CSE", "gender": "Female", "lang": "English-medium", "area": "Urban",
                      "track": True, "share": True, "events": []}
    subj_keys = list(SUBJECTS)
    for i in range(1, 61):
        rural, track = rnd.random() < 0.4, rnd.random() < 0.9
        s = {"dept": rnd.choice(["CSE", "ENTC", "Mechanical"]),
             "gender": rnd.choices(["Female", "Male", "Non-binary"], [45, 45, 10])[0],
             "lang": rnd.choice(["English-medium", "Marathi-medium", "Hindi-medium"]),
             "area": "Rural" if rural else "Urban",
             "track": track, "share": track and rnd.random() < 0.85, "events": []}
        if track:
            last = rnd.randint(0, 12 if rural else 8)
            days = [last] + [last + rnd.randint(1, 10) for _ in range(rnd.randint(2, 7))]
            for d in days:
                s["events"].append(make_event(rnd.choice(subj_keys), rnd.randint(1, 10),
                                               rnd.choice([0, 0, 1, 2]), rnd.random() < 0.1, d))
        STUDENTS[pseudonymize(f"STU-{i:03d}")] = s
    return demo


DEMO_PID = seed()


def reliance_score(s):
    """Self-reliance score (0-100): average of per-question scores, None if nothing recorded."""
    return round(100 * statistics.mean(e["score"] for e in s["events"])) if s["events"] else None


def subject_scores(s):
    """Self-reliance score broken down per subject, for subjects with at least one event."""
    out = {}
    for key in SUBJECTS:
        evs = [e for e in s["events"] if e["subject"] == key]
        if evs:
            out[key] = round(100 * statistics.mean(e["score"] for e in evs))
    return out


def alert_reasons(s):
    """Plain-language reasons for a support alert. Only students who opted in to sharing are checked."""
    if not s["share"] or not s["events"]:
        return []
    ev, reasons = s["events"], []
    idle = min(e["days_ago"] for e in ev)
    if idle >= 7:
        reasons.append(f"No practice for {idle} days")
    if len(ev) >= 3:
        if reliance_score(s) < 50:
            reasons.append(f"Self-reliance score is {reliance_score(s)}, below 50")
        shown = sum(e["revealed"] for e in ev)
        if shown / len(ev) >= 0.3:
            reasons.append(f"Answer revealed on {shown} of {len(ev)} questions")
    return reasons


def fairness():
    """Alert rate per group. A group is flagged when it has 5+ students and its rate is over 1.25x overall."""
    pool = [s for s in STUDENTS.values() if s["share"] and s["events"]]
    flagged = lambda grp: sum(bool(alert_reasons(s)) for s in grp) / len(grp)
    overall = flagged(pool) if pool else 0
    report = {}
    for label, key in ATTRS.items():
        rows = []
        for g in sorted({s[key] for s in pool}):
            grp = [s for s in pool if s[key] == g]
            rate = flagged(grp)
            rows.append({"group": g, "n": len(grp), "rate": round(rate * 100),
                         "flag": len(grp) >= 5 and overall > 0 and rate > 1.25 * overall})
        report[label] = rows
    return round(overall * 100), report


def finish(s, subject, qid, st, revealed):
    st["done"], st["revealed"] = True, revealed
    if s["track"]:  # with tracking off, nothing is stored
        s["events"].append(make_event(subject, qid, st["hints"], revealed, 0))


@app.route("/")
def home():
    return redirect(url_for("student"))


@app.route("/student")
def student():
    subject = request.args.get("subject", "python")
    if subject not in SUBJECTS:
        subject = "python"
    s, states = STUDENTS[DEMO_PID], session.get("st", {})
    blank = {"tries": 0, "hints": 0, "done": False, "revealed": False}
    cards = [{"id": i, **q, "st": states.get(f"{subject}-{i}", blank)}
             for i, q in SUBJECTS[subject]["questions"].items()]
    chat = [{"q": decrypt_text(c["q"]), "a": decrypt_text(c["a"]), "time": c["time"]}
            for c in CHATS.get(DEMO_PID, [])]
    return render_template("student.html", s=s, pid=DEMO_PID, subject=subject, subjects=SUBJECTS,
                            cards=cards, score=reliance_score(s), subj_scores=subject_scores(s), chat=chat)


@app.post("/student/consent")
def consent():
    s = STUDENTS[DEMO_PID]
    s["track"] = "track" in request.form
    s["share"] = s["track"] and "share" in request.form
    log(f"student {DEMO_PID}", "consent updated", f"tracking={s['track']}, share with faculty={s['share']}")
    flash("Your privacy choices are saved.")
    return redirect(url_for("student", subject=request.form.get("subject", "python")))


@app.post("/student/delete")
def delete_data():
    STUDENTS[DEMO_PID]["events"].clear()
    log(f"student {DEMO_PID}", "deleted own activity data")
    flash("All your recorded activity is deleted.")
    return redirect(url_for("student", subject=request.form.get("subject", "python")))


@app.post("/student/chat/clear")
def clear_chat():
    CHATS.pop(DEMO_PID, None)
    log(f"student {DEMO_PID}", "cleared AI chat history")
    flash("Your AI chat history is deleted.")
    return redirect(url_for("student", subject=request.form.get("subject", "python")))


@app.post("/practice/<subject>/<int:qid>/<action>")
def practice(subject, qid, action):
    subj = SUBJECTS.get(subject)
    q = subj["questions"].get(qid) if subj else None
    s = STUDENTS[DEMO_PID]
    if not q or action not in ("attempt", "hint", "reveal"):
        return redirect(url_for("student", subject=subject if subj else "python"))
    key = f"{subject}-{qid}"
    st = session.setdefault("st", {}).setdefault(key, {"tries": 0, "hints": 0, "done": False, "revealed": False})
    if not st["done"]:
        if action == "attempt":
            if request.form.get("answer", "").strip().lower() == q["ans"]:
                finish(s, subject, qid, st, False)
                flash("Correct. You solved it yourself.")
            else:
                st["tries"] += 1
                flash("Not quite. Rethink your approach and try once more.")
        elif action == "hint":
            if st["tries"] < 1:
                flash("Attempt the question first. Hints unlock after one try.")
            elif st["hints"] >= len(q["hints"]):
                flash("No hints left. Try again, or reveal the answer after 2 attempts.")
            else:
                st["hints"] += 1
        elif st["tries"] < 2:
            flash("The answer unlocks after 2 attempts.")
        else:
            finish(s, subject, qid, st, True)
    session.modified = True
    return redirect(url_for("student", subject=subject))


@app.post("/api/ask")
def api_ask():
    pid = DEMO_PID
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return {"error": "Type a question first."}, 400
    if len(question) > 2000:
        question = question[:2000]
    system = ("You are TrustLearn's study tutor for a first-year engineering student covering Python, "
               "maths and physics basics. Explain concepts clearly and briefly, and nudge the student "
               "to reason it out rather than just handing over final answers to graded questions.")
    answer = call_ai_api(system, question)
    CHATS.setdefault(pid, []).append({
        "q": encrypt_text(question), "a": encrypt_text(answer),
        "time": datetime.now().strftime("%d %b %H:%M:%S"),
    })
    log(f"student {pid}", "asked the AI tutor")  # question content is never written to the audit log
    return {"answer": answer}


@app.post("/api/summarize")
def api_summarize():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return {"error": "Paste some text first."}, 400
    if len(text) > 6000:
        text = text[:6000]
    system = "Summarize the student's pasted text in 3 to 5 plain-language sentences. Stay neutral and factual."
    summary = call_ai_api(system, text)
    log(f"student {DEMO_PID}", "used the summarizer", f"{len(text)} characters in")
    return {"summary": summary}


@app.route("/faculty")
def faculty():
    def decision_for(pid):
        d = DECISIONS.get(pid)
        return {"decision": d["decision"], "note": decrypt_text(d["note"])} if d else None

    alerts = [{"pid": p, "dept": s["dept"], "reasons": alert_reasons(s), "decision": decision_for(p)}
              for p, s in STUDENTS.items() if alert_reasons(s)]
    alerts.sort(key=lambda a: -len(a["reasons"]))
    return render_template("faculty.html", alerts=alerts)


@app.post("/faculty/decide")
def decide():
    pid, choice = request.form.get("pid", ""), request.form.get("decision", "")
    note = request.form.get("note", "").strip()
    if pid not in STUDENTS or choice not in ("Reach out", "Keep monitoring", "Dismiss alert") or not note:
        flash("Choose a decision and add a short note. The AI only suggests; a person decides.")
    else:
        DECISIONS[pid] = {"decision": choice, "note": encrypt_text(note)}
        log("faculty", f"decision: {choice}", f"student {pid}")  # note text stays encrypted, off the audit log
    return redirect(url_for("faculty"))


@app.route("/admin")
def admin():
    overall, report = fairness()
    return render_template("admin.html", overall=overall, report=report, audit=AUDIT)


if __name__ == "__main__":
    app.run(debug=True)  # local demo only; use a production server and real auth for deployment
