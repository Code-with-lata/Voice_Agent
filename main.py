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
from fpdf import FPDF


load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

LLM_MODEL = "llama-3.1-8b-instant"

# ================== SMART PROMPT ==================
SYSTEM_PROMPT = (
    "You are a friendly and professional AI Technical Interviewer.\n\n"
    
    "STRICT FLOW:\n"
    
    "1. FIRST MESSAGE (VERY IMPORTANT):\n"
    "- Start with a warm human-like greeting.\n"
    "- Briefly introduce the interview process.\n"
    "- Ask if the candidate is ready.\n"
    "- DO NOT ask any technical question yet.\n\n"

    "2. AFTER USER SAYS YES:\n"
    "- Ask the candidate to briefly introduce themselves.\n"
    "- Do NOT start technical questions yet.\n\n"
    
    "3. AFTER USER RESPONDS:\n"
    "- Give a short acknowledgment (2-5 words).\n"
    "- If user confirms (yes/ready), start interview with first question.\n"
    
    "4. DURING INTERVIEW:\n"
    "- Evaluate answers internally.\n"
    "- Give short feedback (2-5 words).\n"
    "- Then ask next question OR follow-up.\n\n"
    
    "5. STYLE:\n"
    "- Keep responses under 20 words.\n"
    "- Be natural and human-like.\n"
    "- Avoid repetition.\n"
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
    prompt = f"""
                Candidate said: "{user_text}". If follow-up is needed, ask it. Otherwise, ask the 
                next question: "{next_q}"

                INSTRUCTION: 
                - Briefly validate if the answer is correct (DON'T repeat it).
                - If the answer is good, ask the Next Scheduled Question.
                - If the answer is technically flawed or too short, ask a specific follow-up about that topic.
                """
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=history + [{"role": "system", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content

def generate_greeting(client, history):
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=history + [{"role": "user", "content": "Start the interview."}],
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

# ---------------- PDF ---------------- #
def generate_pdf():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    total_score = sum(st.session_state.scores)

    pdf.cell(0, 10, "Interview Report", ln=True)
    pdf.cell(0, 10, f"Total Score: {total_score}", ln=True)

    pdf.ln(5)

    for i, ans in enumerate(st.session_state.answers):
        pdf.multi_cell(0, 8, f"Q{i+1}: {ans['question']}")
        pdf.multi_cell(0, 8, f"Answer: {ans['answer']}")
        pdf.multi_cell(0, 8, f"Score: {ans['score']}")
        pdf.ln(3)

    file_path = "report.pdf"
    pdf.output(file_path)
    return file_path

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
    if "awaiting_intro" not in st.session_state:
        st.session_state.awaiting_intro = False  
    if "answers" not in st.session_state:
        st.session_state.answers = []
    if "scores" not in st.session_state:
        st.session_state.scores = []  
    if "report_ready" not in st.session_state:
        st.session_state.report_ready = False
    if "report_file" not in st.session_state:
        st.session_state.report_file = None
    if "force_end" not in st.session_state:
        st.session_state.force_end = False  
    if "followup_count" not in st.session_state:
        st.session_state.followup_count = 0          

def render_upload_screen(groq_client):
    """Shuruat ki screen jahan file mangi jati hai"""
    st.info("Please upload your interview questions to start.")
    file = st.file_uploader("Upload PDF or DOCX", type=['pdf', 'docx'])
    
    if file and st.button("Begin Interview", use_container_width=True):
        questions = extract_questions_from_file(file)
        
        if questions:
            greeting = generate_greeting(groq_client, st.session_state.chat_history)

            st.session_state.q_bank = questions
            st.session_state.is_started = True
            st.session_state.chat_history.append({"role": "assistant", "content": greeting})
            st.session_state.pending_voice = greeting
            # first question store karo
            st.session_state.first_question = questions[0]

            st.rerun()  


def render_interview_ui():
    """Active interview ki screen"""
    
    user_audio = st.audio_input("Speak your answer...")
    
    return user_audio  

def process_answer(audio_input, stt_model, groq_client):
    if not audio_input or audio_input == st.session_state.get("last_id"):
        return
    
    st.session_state.last_id = audio_input 

    with st.spinner("AI is thinking..."):
        user_text = transcribe_voice(stt_model, audio_input)
    
        if not user_text:
            return
        
        st.session_state.chat_history.append({"role": "user", "content": user_text})
    
    
       # ===== FIRST GREETING / INTRO FLOW =====
        if "first_question" in st.session_state and not st.session_state.awaiting_intro:
            if any(word in user_text.lower() for word in ["yes", "ready", "start", "ok"]):
                reply = "Great! Please introduce yourself briefly."
                st.session_state.awaiting_intro = True
            else:
                reply = "No problem. Let me know when you're ready."

        elif st.session_state.get("awaiting_intro"):
            reply = f"Thanks for the introduction. Let's get started. {st.session_state.first_question}"
            st.session_state.q_index = 1
            st.session_state.awaiting_intro = False
            del st.session_state.first_question        
     

        # INTERVIEW FLOW
        else:
            idx = st.session_state.q_index
            q_bank = st.session_state.q_bank
    
            if idx >= len(q_bank):
                reply = "Interview complete. Generating report..."
                pdf = generate_pdf()
                st.session_state.report_ready = True
                st.session_state.report_file = pdf

            else:
                current_q = q_bank[idx-1]
                next_q = q_bank[idx] if idx < len(q_bank) else "Done"
    
                score_prompt = f"""
                Answer: {user_text}
                Give score 0 to 5 based on correctness.
                Only return number.
                """
                
                score_res = groq_client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[{"role": "user", "content": score_prompt}]
                )
                
                try:
                    score = int(score_res.choices[0].message.content.strip())
                except:
                    score = 3

                st.session_state.answers.append({
                    "question": current_q,
                    "answer": user_text,
                    "score": score
                })
    
                st.session_state.scores.append(score)
    
                ai_reply = get_ai_decision(
                    groq_client,
                    user_text,
                    next_q,
                    st.session_state.chat_history
                )
                
                reply = ai_reply

                if next_q.lower() in reply.lower():
                    st.session_state.q_index += 1
                    st.session_state.followup_count = 0 

                # follow-up detect
                elif any(word in reply.lower() for word in ["why", "how", "example", "explain", "difference"]):
                    st.session_state.followup_count += 1
                 

                if st.session_state.followup_count >= 2:
                    reply = f"Alright. {next_q}"
                    st.session_state.q_index += 1
                    st.session_state.followup_count = 0       
    
        st.session_state.chat_history.append({"role":"assistant","content":reply})
        st.session_state.pending_voice = reply
    
        st.rerun()                  

def main():
    st.set_page_config(page_title="Voice Agent", layout="centered")

    st.title("🎙️ AI-Powered Voice-Based Interview Assistant")
    
    # State Init
    init_session()

    stt_model, groq_client = load_agent_engines()

    

    #  Screens
    if not st.session_state.is_started:
        render_upload_screen(groq_client)
    else:
        # Voice Trigger
        if st.session_state.get("pending_voice"):
            ai_voice_output(st.session_state.pending_voice)
            st.session_state.pending_voice = None
        
        if st.button("🛑 End Interview"):
            st.session_state.force_end = True
            st.rerun()
        # 🛑 FORCE END HANDLE (FIXED)
        if st.session_state.force_end:
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": "Interview ended. Generating report..."
            })
        
            pdf = generate_pdf()
            st.session_state.report_ready = True
            st.session_state.report_file = pdf
            st.session_state.pending_voice = "Interview ended. Generating report..."
        
            st.session_state.force_end = False
            st.rerun()

        # UI & Input
        audio_input = render_interview_ui() 
 

        #  Processing Logic
        process_answer(audio_input, stt_model, groq_client)

        # 📄 Download report
        if st.session_state.report_ready:
            with open(st.session_state.report_file, "rb") as f:
                st.download_button("📄 Download Report", f, file_name="report.pdf")

if __name__ == "__main__":
    main()   


