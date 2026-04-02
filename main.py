import streamlit as st
import os
import base64
import tempfile
import time
from faster_whisper import WhisperModel
from groq import Groq
from gtts import gTTS
from docx import Document
import PyPDF2
from dotenv import load_dotenv


load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

LLM_MODEL = "llama-3.1-8b-instant"

SYSTEM_PROMPT = (
    "You are an expert AI Technical Interviewer. Your goal is to critically analyze the candidate's answer. "
    "Follow these steps for every response: "
    "1. Internal Analysis: Check if the candidate's answer is technically correct and complete. "
    "2. VARIATION: Never use the same phrase twice for feedback. Use a wide range of synonyms for 'Correct' "
    "   (e.g., 'Spot on', 'I agree with that logic', 'Exactly', 'Perfectly explained', 'That makes sense'). "
    "   - If partially correct/wrong: Gently correct them or ask for more detail. "
    "3. FEEDBACK: Give a very brief (2-5 words) natural acknowledgment before moving to the next part. "
    "4. Decision: If the answer is satisfactory, move to the next question from the list. "
    "   - If the answer is vague, ask a deep-dive follow-up. "
    "Keep your total speech under 20 words to maintain a fast voice-agent flow."
)

# FILE PARSING FUNCTIONS

def extract_questions_from_file(uploaded_file):
    """Word ya PDF se questions nikalne ka function"""
    questions = []
    file_type = uploaded_file.name.split('.')[-1].lower()

    if file_type == 'docx':
        doc = Document(uploaded_file)
        questions = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    
    elif file_type == 'pdf':
        reader = PyPDF2.PdfReader(uploaded_file)
        for page in reader.pages:
            text = page.extract_text()
            if text:
                # Basic splitting by new lines
                questions.extend([line.strip() for line in text.split('\n') if line.strip()])
    
    return questions


# VOICE CORE

@st.cache_resource
def load_agent_engines():
    stt = WhisperModel("base", device="cpu", compute_type="int8")
    client = Groq(api_key=GROQ_API_KEY)
    return stt, client

def get_ai_decision(client, user_text, next_q, history):
    """AI Brain: Follow-up ya Next Question ka faisla"""
    decision_prompt = f"""
                Candidate said: "{user_text}". If follow-up is needed, ask it. Otherwise, ask the 
                next question: "{next_q}"

                INSTRUCTION: 
                - Briefly validate if the answer is correct (DON'T repeat it).
                - If the answer is good, ask the Next Scheduled Question.
                - If the answer is technically flawed or too short, ask a specific follow-up about that topic.
                """
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=history + [{"role": "system", "content": decision_prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content

def ai_voice_output(text):
    """Audio play karne ka sabse reliable tarika"""
    if not text:
        return
        
    try:
        tts = gTTS(text=text, lang='en')
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            tts.save(fp.name)
            with open(fp.name, "rb") as f:
                data = f.read()
                b64 = base64.b64encode(data).decode()
            
            # Unique ID taaki browser har baar naya audio pehchane
            unique_id = f"audio_{int(time.time())}"
            
            audio_html = f"""
                <audio id="{unique_id}" autoplay="true">
                    <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
                </audio>
                <script>
                    var audio = document.getElementById('{unique_id}');
                    audio.play().catch(function(error) {{
                        console.log("Autoplay was prevented. Click anywhere on the page.");
                    }});
                </script>
            """
            st.components.v1.html(audio_html, height=0) # height=0 se ye invisible rahega
        os.remove(fp.name)
    except Exception as e:
        st.error(f"Voice Error: {e}")

def transcribe_voice(stt_model, audio_file):
    """Voice to Text conversion"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(audio_file.read())

        segments, _ = stt_model.transcribe(tmp.name)
        text = " ".join([s.text for s in segments])
    os.remove(tmp.name)
    return text.strip()        


# --------------------- streamlit UI INTERFACE ---------------------


def init_session():
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [{"role": "system", "content": SYSTEM_PROMPT}]
    if "q_bank" not in st.session_state:
        st.session_state.q_bank = []
    if "q_index" not in st.session_state:
        st.session_state.q_index = 0
    if "is_started" not in st.session_state:
        st.session_state.is_started = False

def render_upload_screen():
    """Shuruat ki screen jahan file mangi jati hai"""
    st.info("Please upload your interview questions to start.")
    file = st.file_uploader("Upload PDF or DOCX", type=['pdf', 'docx'])
    if file and st.button("Begin Interview", use_container_width=True):
        questions = extract_questions_from_file(file)
        
        if questions:
            st.session_state.q_bank = questions
            st.session_state.q_index = 1
            st.session_state.is_started = True
            st.session_state.chat_history.append({"role": "assistant", "content": questions[0]})
            st.session_state.pending_voice = questions[0]
            
            st.rerun()  

def render_chat_history():
    """Chatbot ki tarah history dikhane ke liye function"""
    st.markdown("---")
    st.subheader("💬 Interview Conversation")
    for message in st.session_state.chat_history:
        if message["role"] == "system":
            continue
        
        with st.chat_message(message["role"]):
            st.write(message["content"])

def render_interview_ui():
    """Active interview ki screen"""
    current_q = st.session_state.chat_history[-1]['content']
    st.info(f"🎙️ **Current Question:** {current_q}")
    
    user_audio = st.audio_input("Speak your answer...")

    # Chat Display Call
    render_chat_history()
    
    return user_audio  

def process_answer(audio_input, stt_model, groq_client):
    if not audio_input or audio_input == st.session_state.get("last_id"):
        return
    
    st.session_state.last_id = audio_input 

    with st.spinner("AI is thinking..."):
        user_text = transcribe_voice(stt_model, audio_input)
    
        if not user_text:
            return
        
        st.session_state.last_user_text = user_text
        st.session_state.chat_history.append({"role": "user", "content": user_text})
    
        # Next question
        idx = st.session_state.q_index
        q_bank = st.session_state.q_bank
    
        next_q = q_bank[idx] if idx < len(q_bank) else "End of interview."
    
        ai_reply = get_ai_decision(groq_client, user_text, next_q, st.session_state.chat_history)
    
        if next_q.lower() in ai_reply.lower():
            st.session_state.q_index += 1
    
        st.session_state.chat_history.append({"role": "assistant", "content": ai_reply})
        st.session_state.pending_voice = ai_reply
    
        st.rerun()                    

def main():
    st.set_page_config(page_title="Voice Agent", layout="centered")

    st.title("🎙️ AI-Powered Voice-Based Interview Assistant")
    
    # State Init
    init_session()

    stt_model, groq_client = load_agent_engines()


    #  Screens
    if not st.session_state.is_started:
        render_upload_screen()
    else:
        # Voice Trigger
        if st.session_state.get("pending_voice"):
            ai_voice_output(st.session_state.pending_voice)
            st.session_state.pending_voice = None

        # UI & Input
        audio_input = render_interview_ui()  

        # Processing Logic
        process_answer(audio_input, stt_model, groq_client)

if __name__ == "__main__":
    main()   


