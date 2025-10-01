# ─────────────────────────────────────────────────────────
# 0. Page config  (MUST be the first Streamlit command)
# ─────────────────────────────────────────────────────────
import streamlit as st  # ensure streamlit is imported before using it

st.set_page_config(
    page_title="Pickle Mini",
    page_icon="🧠",
    layout="wide",                    # use "wide" or "centered"
    initial_sidebar_state="collapsed"
)

# =========================
# 1) IMPORTS & THEME SETUP
# =========================

import os                                  # misc utilities
import re                                  # regex for extraction
import uuid                                # to generate per-user IDs
from datetime import datetime              # timestamps if you need them
from streamlit_cookies_manager import EncryptedCookieManager  # per-user cookie IDs
from supabase import create_client         # Supabase client

# ---- Theme / CSS (lightweight) ----
st.markdown("""                               
<style>
/* container width + paddings */
.block-container {max-width: 980px; padding-top: 1.4rem; padding-bottom: 2rem;}
/* compact, readable headings */
h1, h2, h3 { letter-spacing:.3px; }
/* subtle small text */
.small-muted { color:#9aa0a6; font-size:.92rem; }
/* soft panel for debug */
.debug-box { background:#12141a; border:1px solid #23262f; padding:.8rem 1rem; border-radius:10px; }
</style>
""", unsafe_allow_html=True)               # inject small CSS


# ===============================
# 2) SUPABASE CLIENT & CONSTANTS
# ===============================

SUPABASE_URL = st.secrets["SUPABASE_URL"].strip()                  # Supabase URL
SUPABASE_SERVICE_KEY = st.secrets["SUPABASE_SERVICE_KEY"].strip()  # Service key (server-side)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)       # Supabase client

TABLE_NAME = "Memories"                                            # table name


# =======================================
# 3) PER-USER ID (ENCRYPTED COOKIE SETUP)
# =======================================

cookies = EncryptedCookieManager(                                  # create encrypted cookie bucket
    prefix="pickle_",                                             # isolate cookies per app
    password=st.secrets["COOKIE_PASSWORD"]                        # encryption key
)

if not cookies.ready():                                           # on first run cookies may not be ready
    st.stop()                                                     # rerun until ready

user_id = cookies.get("user_id")                                  # read user_id if present
if not user_id:                                                   # if missing, create one
    user_id = str(uuid.uuid4())                                   # generate UUID
    cookies["user_id"] = user_id                                  # store it
    cookies.save()                                                # persist the cookie


# ======================================
# 4) DB HELPERS: LOAD & SAVE MEMORIES
# ======================================

def load_memories_from_db(user_id: str, search_term: str = "") -> list[dict]:
    """Return a list of memories for this user, optionally filtered by a search term."""
    if not user_id:                                               # guard
        return []                                                 # nothing to query
    try:                                                          # handle DB errors cleanly
        q = (supabase.table(TABLE_NAME)                           # base query
                     .select("id, created_at, memory_text, importance")
                     .eq("user_id", user_id)
                     .order("created_at", desc=True))
        if search_term.strip():                                   # case-insensitive contains
            q = q.ilike("memory_text", f"%{search_term.strip()}%")
        resp = q.execute()                                        # run
        return resp.data or []                                    # normalize
    except Exception as e:                                        # show error but don't crash UI
        st.error(f"Error loading memories: {e}")
        return []                                                 # safe fallback


def save_memory_to_db(user_id: str, text: str, importance: int = 3) -> bool:
    """Insert a memory row for this user."""
    try:
        payload = {                                               # row payload
            "user_id": user_id,
            "memory_text": text.strip(),
            "importance": int(importance),
        }
        _ = supabase.table(TABLE_NAME).insert(payload).execute()  # insert
        return True                                               # success
    except Exception as e:
        st.error(f"Couldn't save memory: {e}")                    # surface error
        return False                                              # failure
# ==============================================================
# ================================================================
# 5) Q&A MATCHER — clean, second-person answers with personality
#    (Drop-in replacement; safe to paste as a whole block)
# ================================================================
# line-tag:QAMATCHER-SECTION-START

# 5.1 Imports / stopwords ----------------------------------------
import re  # keep near top if you already import re elsewhere

STOPWORDS = {
    "a","an","the","is","are","to","of","and","on","at","by","for","in","with",
    "this","that","today","tonight","sunday","monday","tuesday","wednesday",
    "thursday","friday","saturday","my","me"
}

# 5.2 Tiny tokenizer ---------------------------------------------
def _tokens(text: str) -> list[str]:
    """Lowercase, alnum tokens minus stopwords."""
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return [w for w in words if w not in STOPWORDS]

# --- Multi-task detection + scoring helpers (NEW) ----------------
MULTI_Q_HINTS = (
    "today", "tonight", "this evening", "this afternoon", "this morning",
    "to do", "todo", "tasks", "things", "everything", "all the things",
    "what are all", "what do i have", "what should i do"
)

def _wants_multi(question: str) -> bool:
    q = (question or "").lower()
    return any(h in q for h in MULTI_Q_HINTS)

def _score_overlap(q_tokens: set[str], text: str) -> int:
    m_tokens = set(_tokens(text))
    return len(q_tokens & m_tokens)

# 5.3 Convert first-person → second-person ------------------------
def _to_second_person(text: str) -> str:
    """
    Very light rewrite so answers speak to the user.
    Handles common cases: I/my/me → you/your/you; we/our → you/your.
    """
    if not text:
        return ""

    # order matters; do longest first
    repl = [
        (r"\bI am\b", "You are"),
        (r"\bI'm\b", "You're"),
        (r"\bI’ve\b", "You’ve"),
        (r"\bI’d\b", "You’d"),
        (r"\bI’ll\b", "You’ll"),
        (r"\bI\b", "You"),
        (r"\bmy\b", "your"),
        (r"\bme\b", "you"),
        (r"\bour\b", "your"),
        (r"\bours\b", "yours"),
        (r"\bwe\b", "you"),
        (r"\bus\b", "you"),
    ]
    out = " " + text + " "
    for pat, sub in repl:
        out = re.sub(pat, sub, out, flags=re.IGNORECASE)
    return out.strip().rstrip(".")  # keep it tidy

# 5.4 Pickle’s personality tag (domain-aware) --------------------
import random

def personality_response(memory_text, question):
    """
    Generate a second-person, personality-rich response without using an LLM.
    This uses predefined templates and adds subtle humor or warmth.
    """

    templates = [
        f"Here's what you've got: {memory_text}. Go get it done! 💪",
        f"Don't forget — {memory_text}. You're going to rock it! 🌟",
        f"You've got this coming up: {memory_text}. Stay sharp! ⚡",
        f"Hey, just a heads up — {memory_text}. Make it count! ✨",
        f"Mark your calendar: {memory_text}. And don't be late! ⏰",
        f"Get ready! {memory_text}. You're unstoppable. 🚀",
        f"Friendly reminder: {memory_text}. You’ll handle it like a pro. 😎"
    ]

    # Pick a random template
    response = random.choice(templates)

    # Add extra flair for certain keywords
    lower_text = memory_text.lower()
    if "birthday" in lower_text:
        response += " 🎂 Don't forget to wish them from me too!"
    elif "interview" in lower_text:
        response += " 🤝 Go crush it, you've got this!"
    elif "football" in lower_text or "game" in lower_text:
        response += " ⚽ Bring your A-game and have fun!"
    
    return response

# 5.5 Choose best memory for a question --------------------------
def _pick_best_memory(question: str, memories: list[dict]) -> dict | None:
    """
    Score each memory by token overlap + small importance boost; return best.
    Memory shape assumed: { 'memory_text': str, 'importance': int, ... }
    """
    if not memories:
        return None

    q_tokens = set(_tokens(question))
    if not q_tokens:
        return None

    best = None
    best_score = -1
    for m in memories:
        text = m.get("memory_text", "") or m.get("text", "")
        m_tokens = set(_tokens(text))
        overlap = len(q_tokens & m_tokens)
        score = overlap * 10 + int(m.get("importance", 3))  # overlap dominates; importance nudges
        if score > best_score:
            best, best_score = m, score

    return best if best_score > 0 else None

# 5.6 Public API used by the UI
def answer_question_from_memories(question: str, memories: list[dict]) -> str:
    """
    Returns a short second-person answer with personality.
    - Normal questions  -> best single memory
    - Multi-task questions (today/to-do/etc.) -> top few memories as a bullet list
    """
    if not memories:
        return "I don't know."

    q_tokens = set(_tokens(question))
    if not q_tokens:
        return "I don't know."

    # Rank memories by simple token overlap
    ranked = []
    for m in memories:
        text = m.get("memory_text", "") or m.get("text", "")
        if not text:
            continue
        score = _score_overlap(q_tokens, text)
        if score > 0:
            # slight importance boost if present
            score = score * 10 + int(m.get("importance", 3))
            ranked.append((score, text))

    if not ranked:
        return "I don't know."

    ranked.sort(key=lambda t: t[0], reverse=True)

    # If the question sounds like a list/today/todo → combine several
    if _wants_multi(question):
        top_texts = [t for _, t in ranked[:5]]  # show up to 5 items
        if not top_texts:
            return "I don't know."
        bullets = ["• " + _to_second_person(txt) for txt in top_texts]
        body = "\n".join(bullets)  # personality_response will add a nice opener
        return personality_response(body, question)

    # Otherwise return the best single match
    best_text = ranked[0][1]
    body = _to_second_person(best_text)
    return personality_response(body, question)  # keep your personality/emoji system

# ========================== END MATCHER ==========================
# ===================
# 6) PAGE STRUCTURE
# ===================

st.title("🧠 Pickle Mini — Personal Memory Assistant")            # title
st.markdown('<div class="small-muted">Save memories. Search them. Ask natural questions (private to you).</div>',
            unsafe_allow_html=True)                               # subtitle
st.divider()                                                      # separator

# ---- two columns: save (left) / search (right) ----
left, right = st.columns([1, 1])                                  # create columns

with left:                                                        # LEFT: save memory:
    st.subheader("📝 Save a new memory")

    # ----------------------------
    # 1) Keep widget state in SS
    # ----------------------------
    if "memory_input" not in st.session_state:
        st.session_state.memory_input = ""          # textarea content
    if "importance_val" not in st.session_state:
        st.session_state.importance_val = 3         # slider value
    if "last_save_ok" not in st.session_state:
        st.session_state.last_save_ok = None        # last save result

    # ----------------------------
    # 2) Define a single callback
    #    (runs when the Save button is clicked)
    # ----------------------------
    def handle_save():
        text = st.session_state.memory_input.strip()
        imp  = int(st.session_state.importance_val)
        if text:
            ok = save_memory_to_db(user_id, text, imp)
            st.session_state.last_save_ok = ok
            # SAFE reset inside callback
            st.session_state.memory_input = ""
        else:
            st.session_state.last_save_ok = None

    # ----------------------------
    # 3) Render widgets
    # ----------------------------
    st.text_area(
        "What should I remember?",
        key="memory_input",
        height=120,
        placeholder="E.g., Arsenal are playing Newcastle this Sunday at 4:30 PM"
    )

    st.slider(
        "Importance (1 low → 5 high)",
        1, 5, key="importance_val"
    )

    st.button("Save memory", type="primary", on_click=handle_save)

    # ----------------------------
    # 4) Feedback from last action
    # ----------------------------
    if st.session_state.last_save_ok is True:
        st.success("Memory saved!")
        # reset the flag so the message doesn’t re-appear after reruns
        st.session_state.last_save_ok = None
    elif st.session_state.last_save_ok is False:
        st.error("Couldn't save. Try again.")
        st.session_state.last_save_ok = None
    elif st.session_state.last_save_ok is None:
        # do nothing (covers first load or empty input case)
        pass
  
with right:                                                       # RIGHT: search + results
    st.subheader("🔎 Search memories")
    search_term = st.text_input("Type a word to filter", placeholder="e.g., Arsenal, physio, mum")
    filtered = load_memories_from_db(user_id, search_term)       # filtered list
    st.write(f"Results: {len(filtered)}")
    for m in filtered:
        st.markdown(
            f"- {m['memory_text']}  \n"
            f"<span class='small-muted'>(saved {m['created_at']}, importance {m['importance']})</span>",
            unsafe_allow_html=True
        )

st.divider()                                                      # separator below columns

# ---- Q&A block ----
# ---- Q&A block ----
st.subheader("🧠 Ask Pickle (natural question)")
user_q = st.text_input("Your question", placeholder="e.g., What time are Arsenal playing?")

if user_q.strip():
    # Load all user memories
    full_memories = load_memories_from_db(user_id, "")

    # Compute the base answer
    ans = answer_question_from_memories(user_q, full_memories)

    # If no match found
    if ans == "I don't know.":
        st.warning(ans)
    else:
        # Add personality to the answer
        st.success(ans)

    # Debugging info
    with st.expander("🧳 Debug (optional)"):
        st.markdown("<div class='debug-box'>", unsafe_allow_html=True)
        st.write({"question": user_q})
        st.write({"matched_from": (full_memories[0] if full_memories else None)})
        st.markdown("</div>", unsafe_allow_html=True)

else:
    st.info("Ask about something you've saved, e.g., 'Who are Arsenal playing?'")
