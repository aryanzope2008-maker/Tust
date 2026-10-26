# TrustLearn

A prototype of a privacy-first AI learning layer for colleges, built with Python (Flask) and HTML templates.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env     # fill in real values -- this file is gitignored, never commit it
python app.py
```

Open http://127.0.0.1:5000. All data is synthetic and held in memory, so it resets on restart.

## Setting up the AI tutor / summarizer

The "Ask a question" and "Summarize text" widgets on the Student page call a real AI API,
configured entirely through environment variables in `.env` -- the key is never written into
`app.py` or any other tracked file:

```
TRUSTLEARN_AI_API_KEY=your-key-here
TRUSTLEARN_AI_BASE_URL=https://api.openai.com/v1/chat/completions
TRUSTLEARN_AI_MODEL=gpt-4o-mini
```

`call_ai_api()` in `app.py` is written against the common OpenAI-style chat-completions
request/response shape. If your provider's shape differs (Anthropic's Messages API and
Google's Gemini API both use a different request and response format), edit that one
function to match -- everything else in the app calls it through the same interface.

Without a key configured, the widgets still work and clearly say the tutor isn't set up yet,
rather than failing silently.

## How it maps to the four concerns

| Concern | In this prototype |
|---|---|
| Data privacy | IDs are pseudonymized with a keyed hash. AI chat messages and faculty notes are encrypted at rest (Fernet/AES). Students control tracking and sharing, see every record collected, and can delete their activity or their AI chat history separately. |
| Over-reliance | Hints unlock only after an attempt, answers after two attempts, and a self-reliance score (overall and per subject) is shown. The AI tutor is prompted to explain rather than hand over graded answers. |
| Bias | The Ethics panel compares alert rates by department, gender, language background and rural or urban, and flags outliers. Each alert lists its reasons. Faculty must record a decision with a note. |
| Subject coverage | 10 questions each for Python basics, Maths and Physics, selectable from tabs on the Student page; each subject has its own self-reliance score and accent color. |

## Honest limits of this prototype

This is a demo, not a production system:
- Data lives in memory only; a database with real encryption-at-rest and backups would replace that.
- There's no login/roles yet -- everyone sees the same demo student.
- Flask's dev server (`app.run(debug=True)`) is for local use only; a real deployment needs a
  production WSGI server, HTTPS, and real authentication.
- The Fernet encryption protects stored chat/note text from anyone reading the raw data store,
  but it is not a substitute for proper access control, TLS in transit, and a real auth system.

## Structure

```
app.py            routes, privacy, encryption, AI tutor/summarizer, scoring, alert and fairness logic
templates/        base.html, student.html, faculty.html, admin.html
requirements.txt
.env.example       env vars to copy into your own .env (never commit the real .env)
```
