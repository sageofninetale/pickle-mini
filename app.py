# Pickle Mini – Save, Search, and Ask (Local Q&A, no API)
# Football analogy:
# - JSON file = your scouting binder
# - Search = analyst filters reports
# - Local Q&A = simple coach logic that answers from the reports

import json, os, re
from datetime import datetime
import streamlit as st

MEMORY_FILE = "memories.json"

# ---------- Helpers: load/save memories ----------
def load_memories():
    if not os.path.exists(MEMORY_FILE):
        return []
    with open(MEMORY_FILE, "r") as f:
        return json.load(f)

def save_memories(memories):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memories, f, indent=2)

# ---------- App ----------
st.title("🟢 Pickle Mini – Personal Memories")

# ---- Search bar ----
st.subheader("🔍 Search memories")
search_term = st.text_input(
    "Type a word to find specific memories",
    placeholder="e.g., Arsenal, Mum, Physio"
)

all_memories = load_memories()

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
            new_mem = {
                "text": mem_text.strip(),
                "importance": int(importance),
                "ts": datetime.now().isoformat()
            }
            all_memories.append(new_mem)
            save_memories(all_memories)
            st.success("✅ Memory saved.")
        else:
            st.warning("Please type something before saving.")

# ---- Right: Results (filtered or all) ----
with col_right:
    st.subheader("📁 Results")

    if not all_memories:
        st.info("No memories yet. Add one on the left.")
        filtered = []
    else:
        if search_term.strip():
            filtered = [m for m in all_memories if search_term.lower() in m["text"].lower()]
        else:
            filtered = all_memories

        if not filtered:
            st.warning("No matches found.")
        else:
            for m in reversed(filtered):
                st.markdown(
                    f"**{m['text']}**  \n"
                    f"_Saved: {m['ts'][:16].replace('T',' ')} • Importance {m['importance']}_"
                )
                st.divider()

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
