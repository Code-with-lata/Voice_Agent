import streamlit as st
import os
import re
import base64
import tempfile
import time
from faster_whisper import WhisperModel
from groq import Groq
import asyncio  
import edge_tts
# from gtts import gTTS
from docx import Document
import PyPDF2
from dotenv import load_dotenv
from docx.shared import pt
from audio_recorder_streamlit import audio_recorder


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

# ================== FILE PARSING ==================
def extract_questions_from_file(uploaded_file):
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
                questions.extend([line.strip() for line in text.split('\n') if line.strip()])
    
    return questions


# ================== VOICE FUNCTIONS ==================
@st.cache_resource
def load_agent_engines():
    stt = WhisperModel("base", device="cpu", compute_type="int8")
    
    client = Groq(api_key=GROQ_API_KEY)
    return stt, client


def generate_greeting(client, history):
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=history + [{"role": "user", "content": "Start the interview."}],
        temperature=0.7
    )
    return response.choices[0].message.content


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


async def generate_edge_voice(text, output_path):
    """Edge-TTS se high quality audio generate karne wala function"""
    # Aap 'en-IN-PrabhatNeural' (Male) ya 'en-IN-NeerjaNeural' (Female) use kar sakte hain
    communicate = edge_tts.Communicate(text, "en-IN-PrabhatNeural")
    await communicate.save(output_path)


def ai_voice_output(text):
    if not text:
        return
        
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
            temp_name = fp.name
            
        asyncio.run(generate_edge_voice(text, temp_name))
        
        with open(temp_name, "rb") as f:
            data = f.read()
            b64 = base64.b64encode(data).decode()
        
        unique_id = f"audio_{int(time.time() * 1000)}"
        
        audio_html = f"""
            <div id="status_{unique_id}" style="color: #764ba2; font-size: 14px; font-weight: bold;">
                🔊 AI is speaking... (Try interrupting me)
            </div>
            <audio id="{unique_id}">
                <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
            </audio>
            
            <script>
                (function() {{
                    const audio = document.getElementById('{unique_id}');
                    const status = document.getElementById('status_{unique_id}');
                    
                    let playbackStarted = false;
                    let echoGuardTime = Date.now() + 600; // 600ms ka buffer

                    audio.play().then(() => {{
                        playbackStarted = true;
                    }}).catch(e => console.log("Autoplay blocked"));

                    async function startInterruptionDetection() {{
                        try {{
                            const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                            const audioContext = new AudioContext();
                            const source = audioContext.createMediaStreamSource(stream);
                            const analyser = audioContext.createAnalyser();
                            analyser.fftSize = 256;
                            source.connect(analyser);

                            const bufferLength = analyser.frequencyBinCount;
                            const dataArray = new Uint8Array(bufferLength);

                            function checkVolume() {{
                                analyser.getByteFrequencyData(dataArray);
                                let values = 0;
                                for (let i = 0; i < bufferLength; i++) {{
                                    values += dataArray[i];
                                }}
                                let average = values / bufferLength;

                                
                                if (playbackStarted && Date.now() > echoGuardTime && average > 75) {{ 
                                    console.log("True User Interruption Detected!");
                                    audio.pause();
                                    status.innerHTML = "⏹️ Bot stopped (Interrupted)";
                                    status.style.color = "red";
                                }}
                                
                                if (!audio.paused && !audio.ended) {{
                                    requestAnimationFrame(checkVolume);
                                }} else if (audio.ended) {{
                                    status.innerHTML = "✅ Finished speaking";
                                }}
                            }}
                            checkVolume();
                        }} catch (err) {{
                            console.error("Mic error:", err);
                        }}
                    }}
                    
                    startInterruptionDetection();
                }})();
            </script>
        """
        st.components.v1.html(audio_html, height=60)
        
        if os.path.exists(temp_name):
            os.remove(temp_name)
            
    except Exception as e:
        st.error(f"Edge-Voice Error: {e}")

def transcribe_audio(stt_model, audio_bytes):
    """Audio bytes ko text me convert karo"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            
            segments, _ = stt_model.transcribe(tmp.name)
            text = " ".join([s.text for s in segments])
            
        os.remove(tmp.name)
        return text.strip()
    except Exception as e:
        return ""
#
# -------------------- Report Generation Logic --------------------
def generate_report():
    doc = Document()
    doc.add_heading('AI Interview: Final Performance Report', 0)

    client = Groq(api_key=GROQ_API_KEY)
    
    # ---  CHAT CONVERSATION ---
    doc.add_heading('Interview Conversation:', level=1)
    transcript_text = ""
    for message in st.session_state.chat_history:
        
        if message['role'] == "system": 
            continue
        p = doc.add_paragraph()
        role_label = "Interviewer (Bot): " if message['role'] == "assistant" else "Candidate (User): "
        transcript_text += f"{role_label}{message['content']}\n"
        run = p.add_run(f"{role_label}{message['content']}")
    
        if message['role'] == "assistant": 
            run.bold = True
        else:
            run.bold = False

    doc.add_page_break() 


    # ---  TECHNICAL SCORING (Performing Scoring Here) ---
    doc.add_heading('Technical Performance Evaluation', level=1)
    table = doc.add_table(rows=1, cols=3)
    table.style = 'Light Grid Accent 1'
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Question'; hdr_cells[1].text = 'Evaluation'; hdr_cells[2].text = 'Score'

    calculated_scores = []

    for q in st.session_state.q_bank:
        item = next((a for a in st.session_state.answers if a["question"] == q), None)
        
        answer_text = item['answer'] if item else ""

        if answer_text in ["...", ".", ""] or len(answer_text.split()) < 3:
            q_score = 0.0
            
        else:
            score_prompt = f"""
                As a Senior Technical Lead, strictly evaluate this candidate's response.
                
                Question: {q}
                Answer: {answer_text}
            
                Evaluate the answer on a scale of 0-5 for each of these categories:
                1. Technical Correctness: Give 5 only if the answer is 100% accurate and covers core concepts. Give 0-1 for vague or "I don't know" type answers.
                2. Depth & Details: Did they explain 'why' and 'how', or just gave a surface-level definition?
                3. Professional Terminology: Did they use correct industry keywords?
                4. Communication & Confidence: Clarity and professional delivery.
            
                PENALTY RULES:
                - Deduct 2 points if the answer is too short (under 10 words) even if correct.
                - Give 0 for technically wrong facts, no partial marks for "trying".
            
                Return ONLY in this exact format:
                Correctness: [score], Depth: [score], Keywords: [score], Communication: [score]
            """
    
            try:
                res = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[{"role": "system", "content": "You are a strict technical interviewer. Return only numeric scores."},
                              {"role": "user", "content": score_prompt}],
                    temperature=0.1
                )
                res_text = res.choices[0].message.content
                digits = [int(s) for s in re.findall(r'\d+', res_text)]
                
                if len(digits) >= 4:
                    q_score = round(sum(digits[:4]) / 4, 1)
                elif len(digits) > 0:
                    q_score = round(sum(digits) / len(digits), 1)
                else:
                    q_score = 0.0
            except Exception as e:
                print(f"Error scoring: {e}")
                q_score = 0.0
    
            calculated_scores.append(q_score)
    
            row_cells = table.add_row().cells
            row_cells[0].text = q
            row_cells[1].text = "Technical assessment completed"
            row_cells[2].text = f"{q_score} / 5"

    st.session_state.scores = calculated_scores    

    # --- CONVERSATION SKILLS SCORING ---
    doc.add_heading('2. Communication & Soft Skills Analysis', level=1)
    
    conv_prompt = f"""
    Analyze the following interview transcript and provide a score (0-10) for Communication Skills, 
    Professionalism, and Confidence. Also provide a 2-line summary of their soft skills.
    
    Transcript:
    {transcript_text}
    
    Format:
    Score: [Total out of 10]
    Feedback: [Your analysis]
    """
    
    try:
        res = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": "You are a senior HR manager."},
                      {"role": "user", "content": conv_prompt}],
            temperature=0.3
        )
        conv_analysis = res.choices[0].message.content
        doc.add_paragraph(conv_analysis)
        comm = re.search(r'Communication.*?(\d+)/10', conv_analysis, re.IGNORECASE)
        prof = re.search(r'Professionalism.*?(\d+)/10', conv_analysis, re.IGNORECASE)
        conf = re.search(r'Confidence.*?(\d+)/10', conv_analysis, re.IGNORECASE)
    
        scores = []
    
        if comm:
            scores.append(int(comm.group(1)))
        if prof:
            scores.append(int(prof.group(1)))
        if conf:
            scores.append(int(conf.group(1)))
    
        
        if scores:
            conv_score = sum(scores) / len(scores)   # out of 10
        else:
            conv_score = 7  
    except Exception as e:
        conv_score = 7 
        doc.add_paragraph("Soft skills evaluation: Professional and clear communication observed.")

    
    # --- COMPLETE SUMMARY & FINAL TOTAL SCORE ---
    doc.add_heading(' Executive Summary:', level=1)
    total_obtained = sum(calculated_scores)
    total_questions = len(st.session_state.q_bank)
    max_possible = total_questions * 5  #len(calculated_scores) * 5

    percentage = (total_obtained / max_possible * 100) if max_possible > 0 else 0
    conv_percent = (conv_score / 10 * 100)
    final_weighted_score = (percentage * 0.7) + (conv_percent * 0.3)

    # # Summary Logic based on score
    # if percentage >= 80:
    #     performance_level = "EXCELLENT"
    #     remarks = "The candidate shows strong technical command and clear communication. Highly recommended."
    # elif percentage >= 60:
    #     performance_level = "GOOD"
    #     remarks = "The candidate has a solid foundation but could improve on technical depth in certain areas."
    # else:
    #     performance_level = "NEEDS IMPROVEMENT"
    #     remarks = "The candidate struggled with core concepts. Further training or review is suggested."
    # doc.add_paragraph("\n") # Space

    summary_p = doc.add_paragraph()
    summary_p.add_run(f"FINAL INTERVIEW SCORE: {total_obtained} / {max_possible}").bold = True
    summary_p.add_run(f"\nPERCENTAGE: {percentage:.1f}%").bold = True
    summary_p.add_run(f"\nCommunication Score: {conv_percent:.1f}%").bold = True
    summary_p.add_run(f"\n\nOVERALL INTERVIEW RATING: {final_weighted_score:.1f}%").bold = True
    # summary_p.add_run(f"\nPERFORMANCE STATUS: {performance_level}").bold = True
    
    status = "SELECTED" if final_weighted_score >= 75 else "RE-EVALUATE" if final_weighted_score >= 50 else "REJECTED"
    summary_p.add_run(f"\nRESULT: {status}").bold = True

    # Feedback basis on percentage
    # doc.add_heading('Interviewer Remarks:', level=2)
    # doc.add_paragraph(remarks)

    file_path = "interview_report.docx"
    doc.save(file_path)
    return file_path


# ================== SESSION MANAGEMENT ==================
def init_session():
    defaults = {
        "chat_history": [{"role": "system", "content": SYSTEM_PROMPT}],
        "q_bank": [],
        "q_index": 0,
        "mic_counter": 0,
        "is_started": False,
        "awaiting_intro": False,
        "answers": [],
        "scores": [],
        "report_ready": False,
        "report_file": None,
        "force_end": False,
        "followup_count": 0,
        "pending_voice": None,
        "last_audio_id": None,
        "pause_count": 0,  
        "is_paused_state": False,
        "current_question": "",
        "last_response_time": time.time()
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ================== UI SCREENS ==================
def render_upload_screen(groq_client):
    st.markdown("""
    <div style="text-align: center; padding: 30px;">
        <h2>🎯 AI-Powered Voice Interview</h2>
        <p style="font-size: 18px; color: #666;">Real-time conversation with AI Interviewer</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.info("📋 Upload your interview questions (PDF or DOCX)")
    file = st.file_uploader("", type=['pdf', 'docx'], label_visibility="collapsed")
    
    if file:
        if st.button("🚀 Start Interview", use_container_width=True, type="primary"):
            questions = extract_questions_from_file(file)
            
            if questions:
                greeting = generate_greeting(groq_client, st.session_state.chat_history)
                st.session_state.q_bank = questions
                st.session_state.is_started = True
                st.session_state.chat_history.append({"role": "assistant", "content": greeting})
                st.session_state.pending_voice = greeting
                st.session_state.first_question = questions[0]
                st.rerun()
            else:
                st.error("❌ No questions found in file!")



def process_user_audio(audio_bytes, stt_model, groq_client):
    """Process user's audio: Distinguish between technical answers and interruptions"""
    
    # Unique ID for session management
    audio_id = hash(audio_bytes)
    if audio_id == st.session_state.last_audio_id:
        return
    st.session_state.last_audio_id = audio_id
    
    with st.spinner("🎯 Processing your response..."):
        user_text = transcribe_audio(stt_model, audio_bytes)

        if not user_text or len(user_text.strip()) == 0:
            user_text = "..."

        st.session_state.chat_history.append({"role": "user", "content": user_text})
        
        # Current Question tracker
        idx = st.session_state.q_index
        q_bank = st.session_state.q_bank
        # current_q = q_bank[idx-1] if idx > 0 else (st.session_state.first_question if "first_question" in st.session_state else "")
        current_q = st.session_state.get("current_question", "")
        
        # --------------------- PAUSE LOGIC -----------------------
    
        if user_text == "..." or len(user_text.split()) < 3:
            st.session_state.pause_count += 1
            if st.session_state.pause_count == 1:
                reply = "I noticed a silence. Do you need a moment to think, or should we move to the next question?"
                
            elif st.session_state.pause_count == 2:
                reply = "I again noticed a silence. No problem, take your time to collect your thoughts. I'm still listening."
                

            elif st.session_state.pause_count >= 3:
                next_q = q_bank[idx] if idx < len(q_bank) else "the end of our interview"
                reply = f"I'm sorry, but we have already spent quite some time here. To ensure we cover everything, I'm moving to the next question. {next_q}"
                st.session_state.q_index += 1
                st.session_state.pause_count = 0 
                st.session_state.current_question = next_q
                if st.session_state.q_index < len(q_bank):
                    st.session_state.current_question = q_bank[st.session_state.q_index]
                
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
            st.session_state.pending_voice = reply
            
            st.rerun()

        st.session_state.pause_count = 0    

        
        # ----------------- FLOW CONTROL: GREETING & INTRO -----------------
       
        is_greeting_reply = any(word in user_text.lower() for word in ["yes", "ready", "ok", "sure", "start"])

        if "first_question" in st.session_state and not st.session_state.awaiting_intro:
            if is_greeting_reply:
                reply = "Perfect! Please introduce yourself briefly."
                st.session_state.awaiting_intro = True
            else:
                reply = "No worries. Take your time. Tell me when you're ready to start!"
            
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
            st.session_state.pending_voice = reply
            st.rerun()

        if st.session_state.get("awaiting_intro"):
            q = st.session_state.first_question
            st.session_state.current_question = q
            reply = f"Great to meet you! Let's jump into the first question. {q}"
            st.session_state.q_index = 1
            st.session_state.awaiting_intro = False
            del st.session_state.first_question
            
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
            st.session_state.pending_voice = reply
            st.rerun()

        
        # ------------------- INTERRUPTION DETECTION (Crucial Part) --------------------
        
        word_count = len(user_text.split())
        interruption_keywords = ["repeat", "wait", "pardon", "sorry", "minute", "slow", "understand", "again", "kya"]
        
        is_interruption = word_count <= 2 or any(kw in user_text.lower() for kw in interruption_keywords)

        if is_interruption:
            interruption_prompt = f"""
            The user interrupted with: "{user_text}". 
            Context: We are currently on this interview question: "{current_q}".
            
            INSTRUCTION:
            - Give a very short, human-like response to their interruption (under 10 words).
            - Then, politely ask them to continue with the current question.
            - DO NOT evaluate this as a technical answer.
            """
            
            response = groq_client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "system", "content": interruption_prompt}],
                temperature=0.6
            )
            reply = response.choices[0].message.content
            
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
            st.session_state.pending_voice = reply
            st.rerun()

        # ==========================================
        #  TECHNICAL ANSWER PROCESSING (Report Impact)
        # ==========================================
        # else:
        # Check if interview complete
        if idx > len(q_bank):
            reply = "Interview is already complete. Generating your report..."
            st.session_state.report_ready = True
        
        else:
            clean_answer = user_text.strip()

            if clean_answer not in ["...", ".", ""] and len(clean_answer.split()) >= 3:
                existing_q_index = next((i for i, a in enumerate(st.session_state.answers) if a["question"] == current_q), None)
    
                if existing_q_index is not None:
                    st.session_state.answers[existing_q_index]["answer"] += f" | Follow-up: {clean_answer}"
                
                else:
                    st.session_state.answers.append({
                        "question": current_q,
                        "answer": clean_answer,
                        "final_score": 0.0  
                    })
           
            # --- NEXT STEP DECISION ---
            next_q = q_bank[idx] if idx < len(q_bank) else "End"
            ai_reply = get_ai_decision(groq_client, user_text, next_q, st.session_state.chat_history)
            
            # Check if moving forward
            
            if st.session_state.followup_count >= 1:    
                st.session_state.q_index += 1
                st.session_state.followup_count = 0
                
                if st.session_state.q_index < len(q_bank):
                    st.session_state.current_question = q_bank[st.session_state.q_index]
            else:
                st.session_state.followup_count += 1
            
            # Force next question if stuck in follow-ups
            if st.session_state.followup_count >= 2:
                ai_reply = f"I see. Let's move to the next one to stay on track. {next_q}"
                st.session_state.q_index += 1
                st.session_state.followup_count = 0

                if st.session_state.q_index < len(q_bank):
                    st.session_state.current_question = q_bank[st.session_state.q_index]
            
            reply = ai_reply
        st.session_state.chat_history.append({"role": "assistant", "content": reply})
        st.session_state.pending_voice = reply
        st.rerun()


# ================== MAIN APP ==================
def main():
    st.set_page_config(
        page_title="🎙️ AI-Powered Voice-Based Interview Assistant",
        page_icon="🎤",
        layout="centered"
    )
    
    st.markdown("""
    <style>
        .main {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        }
        .stButton > button {
            border-radius: 10px;
            font-weight: 600;
        }
    </style>
    """, unsafe_allow_html=True)
    
    st.title("🎙️ AI Voice Interview")
    
    # Initialize
    init_session()
    stt_model, groq_client = load_agent_engines()
    
    # ===== UPLOAD SCREEN =====
    if not st.session_state.is_started:
        render_upload_screen(groq_client)
        return
    

    if st.session_state.pending_voice:
        ai_voice_output(st.session_state.pending_voice)
        wait_time = (len(st.session_state.pending_voice) / 10) + 2

        time.sleep(wait_time)

        st.session_state.pending_voice = None

        st.session_state.mic_counter += 1 

        st.rerun()
    
    # Control panel
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        progress = min(st.session_state.q_index, len(st.session_state.q_bank))
        total = len(st.session_state.q_bank)
        st.metric("Progress", f"{progress}/{total}")
    
    with col3:
        if st.button("🛑 End Interview", type="secondary"):
            st.session_state.force_end = True
            st.rerun()
    
    # Handle force end
    if st.session_state.force_end:
        
        st.session_state.chat_history.append({
            "role": "assistant",
            "content": "Interview ended early. Generating report..."
        })
        pdf = generate_report()
        st.session_state.report_ready = True
        st.session_state.report_file = pdf
        st.session_state.pending_voice = "Interview ended. Your report is ready."
        st.session_state.force_end = False
        st.rerun()
        
    st.markdown("---")
    
    if not st.session_state.report_ready: 
        if st.session_state.pending_voice is None:
            st.write("### 🎤 AI is listening... (Speak now)")
           
            audio_bytes = audio_recorder(
                text="Listening...",
                recording_color="#e74c3c",
                neutral_color="#3498db",
                icon_name="microphone",
                icon_size="2x",
                pause_threshold=2.5, 
                sample_rate=16000,
                auto_start=True,
                key=f"mic_{st.session_state.mic_counter}" 
            )

        if audio_bytes:
            process_user_audio(audio_bytes, stt_model, groq_client)

    
    # ===== DOWNLOAD REPORT =====
    if st.session_state.report_ready:
        
        if not st.session_state.report_file:
            with st.spinner("Calculating final scores and generating report..."):
                st.session_state.report_file = generate_report()
        
        st.success("✅ Interview Completed!")
        
        total = sum(st.session_state.scores)
        maximum = len(st.session_state.q_bank) * 5
        percentage = (total / maximum * 100) if maximum > 0 else 0
        
        st.metric("Final Score", f"{total}/{maximum}", f"{percentage:.1f}%")
        
        with open(st.session_state.report_file, "rb") as f:
            st.download_button(
                label="📄 Download Report ",
                data=f,
                file_name="interview_report.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                type="primary"
            )


if __name__ == "__main__":
    main()
