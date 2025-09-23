import os, json, uuid
from datetime import datetime
import streamlit as st
from streamlit_cookies_manager import EncryptedCookieManager

# --- Add Supabase Setup Here ---
from supabase import create_client

# Load secrets
SUPABASE_URL = st.secrets["SUPABASE_URL"].strip()
SUPABASE_SERVICE_KEY = st.secrets["SUPABASE_SERVICE_KEY"].strip()

# Create Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Table name
TABLE_NAME = "Memories"  # Supabase table where we'll store user memories

# ---------- Helpers: load/save memories (Supabase) ----------

def load_memories_from_db(user_id: str, search_term: str = ""):
    # If we somehow got here without a user_id, don't query the database
    if not user_id:
        return []

    try:
        q = (
            supabase
            .table(TABLE_NAME)
            .select("id, created_at, memory_text, importance")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
        )

        if search_term.strip():
            # Case-insensitive search on memory_text
            q = q.ilike("memory_text", f"%{search_term.strip()}%")

        resp = q.execute()
        return resp.data or []

    except Exception as e:
        # Optional: Log the error for debugging
        st.error(f"Error loading memories: {str(e)}")
        return []
            {
                "id": row.get("id"),
                "created_at": row.get("created_at"),
                "text": row.get("memory_text", ""),
                "importance": row.get("importance", 3),
            }
            for row in data
        ]
    except Exception as e:
        st.error(f"Couldn't load memories: {e}")
        return []


def save_memory_to_db(user_id: str, text: str, importance: int = 3):
    try:
        payload = {
            "user_id": user_id,
            "memory_text": text.strip(),
            "importance": int(importance),
        }
        _ = supabase.table(TABLE_NAME).insert(payload).execute()
        return True
    except Exception as e:
        st.error(f"Couldn't save memory: {e}")
        return False

# --- Per-user ID via encrypted cookies ---
# (Set a password in Streamlit secrets on the cloud; local dev uses fallback.)
COOKIE_PASSWORD = st.secrets.get("COOKIE_PASSWORD", "dev-not-secret")

cookies = EncryptedCookieManager(
    prefix="pickle_",
    password=COOKIE_PASSWORD,
)

# Wait until cookies are ready (first run); then continue.
if not cookies.ready():
    st.stop()

# FIXED: Always get or create a permanent user_id cookie
user_id = cookies.get("user_id")   # safer than cookies["user_id"]
if not user_id:
    user_id = str(uuid.uuid4())    # generate a unique UUID
    cookies["user_id"] = user_id
    cookies.save()

# ---------- Helpers: load/save memories ----------
def load_memories():
    # If no file exists yet, return an empty list
    if not os.path.exists(USER_MEMORY_FILE):
        return []
    try:
        with open(USER_MEMORY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        # In case of JSON errors or corrupted file
        return []

def save_memories(memories):
    # Save memories to the user's specific JSON file
    with open(USER_MEMORY_FILE, "w") as f:
        json.dump(memories, f, indent=2)

# ---------- App ----------
st.title("🟢 Pickle Mini – Personal Memories")

# ---- Search bar ----
st.subheader("🔍 Search memories")
search_term = st.text_input(
    "Type a word to find specific memories",
    placeholder="e.g., Arsenal, Mum, Physio"
)

# Load from Supabase for this user (and optional search)
all_memories = load_memories_from_db(user_id, search_term)

# Two columns: add + results
col_left, col_right = st.columns(2)

# ---- Left: Add memory ----
with col_left:
    st.subheader("➕ Save a new memory")
    mem_text = st.text_area(
        "What should Pickle remember?",
        placeholder="e.g., Arsenal vs Man City at the Emirates, Sunday 4:30pm"
    )
    importance = st.slider("Importance (1 = low, 5 = high)", 1, 5, 3)

if st.button("Save memory", type="primary"):
    if mem_text.strip():
        ok = save_memory_to_db(user_id, mem_text, importance)
        if ok:
            st.success("✅ Memory saved.")
            st.rerun()  # reload list from DB
    else:
        st.warning("Please enter some text before saving.")

# ---- Results (from DB) ----
with col_right:
    st.subheader("📁 Results")
    if not all_memories:
        st.info("No memories yet. Add one on the left.")
    else:
        for m in all_memories:
            # Be tolerant of old local keys: 'text'/'ts' vs new DB keys: 'memory_text'/'created_at'
            text = m.get("memory_text") or m.get("text") or ""
            created = (m.get("created_at") or m.get("ts") or "")
            created_display = created.replace("T", " ")[:16] if isinstance(created, str) else ""
            imp = m.get("importance", "")

            st.markdown(
                f"**{text}**  \n"
                f"<span style='color:#999'>Saved: {created_display} • Importance {imp}</span>",
                unsafe_allow_html=True,
            )
import os, requests

# ----------- Groq Q&A (API) -----------
def ask_groq(question, memories):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None  # No key -> fall back to local

    # Build compact evidence from memories
    lines = []
    for m in memories:
        when = m.get("ts", "")[:16].replace("T", " ")
        lines.append(f"- ({when}, importance {m.get('importance', 3)}): {m.get('text', '')}")
    evidence = "\n".join(lines) if lines else "(no memories yet)"

    # What we want the AI to do (more natural wording)
    system_msg = (
        "You are Pickle Mini, a helpful assistant that recalls personal memories like a human would. "
        "Use natural, conversational language. Always include the subject so the sentence feels complete. "
        "Examples:\n"
        "- If asked 'Who are Arsenal playing?', reply: 'Arsenal are playing Manchester City.'\n"
        "- If asked 'Where are Arsenal playing?', reply: 'Arsenal are playing at their home stadium, the Emirates, in London.'\n"
        "Answer ONLY using the provided memories. "
        "If the information is not in the memories, say 'I don't know.' "
        "Be clear and helpful."
    )

    # What the user is asking (clean multi-line string)
    user_msg = (
        f"Memories:\n{evidence}\n\n"
        f"Question: {question}\n"
        "Answer in complete sentences."
    )

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.2
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        if r.status_code != 200:
            return f"❌ Groq API error: {r.status_code} - {r.text}"
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"❌ Groq request failed: {e}"

# ---------- Local Q&A (no API) ----------
def answer_locally(question, memories):
    """
    Super-simple rule-based answerer.
    Looks at the most recent relevant memory and crafts a direct reply.
    """
    if not memories:
        return "I don't have any memories yet."

    # Use the newest of the currently relevant memories
    mem = memories[-1]  # since Results display reversed order
    text = mem["text"]
    q = question.lower()

    # WHEN / TIME
    if any(w in q for w in ["when", "what time", "time", "date", "day"]):
        return f"According to your memory: {text}"

    # WHERE / VENUE
    if any(w in q for w in ["where", "venue", "stadium"]):
        m = re.search(r"\b(?:at|in)\s+([A-Z][A-Za-z0-9&\-\s']+)", text)
        venue = m.group(1).strip() if m else None
        return f"At {venue}." if venue else f"According to your memory: {text}"

    # WHO / OPPONENT
    if any(w in q for w in ["who", "opponent", "playing", "versus", "vs"]):
        m = re.search(r"\b(?:vs\.?|v\.?)\s+([A-Z][A-Za-z0-9&\-\s']+)", text, flags=re.I)
        opp = m.group(1).strip() if m else None
        return f"{opp}." if opp else f"According to your memory: {text}"

    # Default: just echo the most relevant memory
    return f"According to your memory: {text}"

st.subheader("🗣️ Ask Pickle (natural question)")
st.caption("Uses Groq AI if available; falls back to local demo mode if not.")

question = st.text_input("Your question", placeholder="e.g., When is Arsenal playing?")

if question.strip():
    # Show relevant memories to Groq
    context_memories = filtered if search_term.strip() else all_memories

    # Try Groq first
    groq_answer = ask_groq(question, context_memories)

    if groq_answer is None:
        # No API key detected
        st.warning("⚠️ No Groq API key found — running in local mode.")
        reply = answer_locally(question, context_memories)
        st.success(reply)

    elif groq_answer.startswith("❌"):
        # Groq returned an error
        st.warning(groq_answer)
        reply = answer_locally(question, context_memories)
        st.success(reply)

    else:
        # Groq successfully answered
        st.success(groq_answer)
