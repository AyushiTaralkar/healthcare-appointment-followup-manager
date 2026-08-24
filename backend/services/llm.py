import os
import json
import logging
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    logger.info("Gemini API configured successfully.")
else:
    logger.warning("Gemini API key (GEMINI_API_KEY / GOOGLE_API_KEY) not found. Fallback mode will be used.")


def generate_pre_visit_summary(symptoms: str) -> dict:
    """
    Generate pre-visit summary using LLM.
    Returns a dict with fields: urgency_level, chief_complaint, suggested_questions, and summary_text.
    """
    prompt = (
        "Analyse these symptoms and return: urgency level (Low / Medium / High), chief complaint, "
        "and three suggested questions for the doctor. Symptoms: " + symptoms
    )
    
    # Structure we expect
    result = {
        "urgency_level": "Low",
        "chief_complaint": symptoms[:100] + ("..." if len(symptoms) > 100 else ""),
        "suggested_questions": [
            "How long have you been experiencing these symptoms?",
            "Have you noticed any triggers for these symptoms?",
            "Are you taking any over-the-counter medications for relief?"
        ],
        "summary_text": f"Patient reported symptoms: {symptoms}"
    }

    if not api_key:
        logger.info("Using fallback engine for pre-visit summary.")
        return run_pre_visit_fallback(symptoms, result)

    try:
        # We request structured output or JSON if possible, but standard prompt to be safe.
        # Let's instruct the model to output a JSON string matching our fields.
        json_prompt = (
            f"{prompt}\n\n"
            "Provide your response EXACTLY as a JSON object with these keys: "
            "\"urgency_level\" (must be exactly 'Low', 'Medium', or 'High'), "
            "\"chief_complaint\" (a brief sentence), "
            "\"suggested_questions\" (a list of 3 questions), "
            "\"summary_text\" (a paragraph describing the symptoms and context).\n"
            "Do not include any markdown format tags like ```json or ```, just return the raw JSON string."
        )
        
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(json_prompt)
        text = response.text.strip()
        
        # Clean markdown codeblocks if LLM included them anyway
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
            
        data = json.loads(text)
        
        # Validate values
        urgency = data.get("urgency_level", "Low")
        if urgency not in ["Low", "Medium", "High"]:
            # Normalise
            if "high" in urgency.lower():
                urgency = "High"
            elif "medium" in urgency.lower():
                urgency = "Medium"
            else:
                urgency = "Low"
                
        result["urgency_level"] = urgency
        result["chief_complaint"] = data.get("chief_complaint", result["chief_complaint"])
        result["suggested_questions"] = data.get("suggested_questions", result["suggested_questions"])[:3]
        result["summary_text"] = data.get("summary_text", result["summary_text"])
        
        logger.info("Successfully generated pre-visit summary from LLM.")
        return result
        
    except Exception as e:
        logger.error(f"Error calling Gemini for pre-visit summary: {str(e)}. Falling back.")
        return run_pre_visit_fallback(symptoms, result)


def run_pre_visit_fallback(symptoms: str, default_data: dict) -> dict:
    """Local rule-based fallback analyzer for symptoms."""
    symptoms_lower = symptoms.lower()
    
    # Rule-based urgency assessment
    high_urgency_words = ["chest pain", "breathing", "severe", "bleeding", "unconscious", "stroke", "heart", "choking", "seizure", "suicidal"]
    medium_urgency_words = ["fever", "vomit", "cough", "infection", "dizzy", "pain", "swelling", "migraine", "rash", "nausea"]
    
    urgency = "Low"
    if any(word in symptoms_lower for word in high_urgency_words):
        urgency = "High"
    elif any(word in symptoms_lower for word in medium_urgency_words):
        urgency = "Medium"
        
    # Chief complaint: extract first sentence or first 60 characters
    chief = symptoms.split(".")[0].strip()
    if len(chief) > 80:
        chief = chief[:77] + "..."
    if not chief:
        chief = "Symptom check requested"

    # Contextual questions
    questions = []
    if urgency == "High":
        questions = [
            "When did this severe onset begin, and is it worsening?",
            "Are you experiencing any radiating pain or numbness?",
            "Do you have a companion or transport to an emergency clinic if needed?"
        ]
    elif urgency == "Medium":
        questions = [
            "Have you measured your temperature (if feverish) or other vitals?",
            "Does resting or taking any over-the-counter medicine reduce the symptoms?",
            "How does this affect your appetite and sleep?"
        ]
    else:
        questions = [
            "How long have you noticed these mild symptoms?",
            "Do they occur at specific times of the day or after certain activities?",
            "Is there a history of these symptoms in your family or past medical files?"
        ]
        
    return {
        "urgency_level": urgency,
        "chief_complaint": chief,
        "suggested_questions": questions,
        "summary_text": f"[AI Fallback Summary] Patient presented with symptoms: '{symptoms}'. Overall assessment suggests a {urgency} urgency level."
    }


def generate_post_visit_summary(notes: str) -> str:
    """
    Generate patient-friendly post-visit summary from doctor notes.
    """
    prompt = (
        "Convert these clinical notes into a patient-friendly summary with medication schedule "
        "and follow-up steps: " + notes
    )
    
    if not api_key:
        logger.info("Using fallback engine for post-visit summary.")
        return run_post_visit_fallback(notes)
        
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        logger.info("Successfully generated post-visit summary from LLM.")
        return response.text.strip()
    except Exception as e:
        logger.error(f"Error calling Gemini for post-visit summary: {str(e)}. Falling back.")
        return run_post_visit_fallback(notes)


def run_post_visit_fallback(notes: str) -> str:
    """Local fallback to format clinical notes into patient-friendly text."""
    lines = [line.strip() for line in notes.split("\n") if line.strip()]
    formatted_notes = "\n".join([f"- {line}" for line in lines])
    
    fallback_text = (
        "### Patient-Friendly Visit Summary\n\n"
        "Thank you for visiting today. Here is a summary of your consultation and care steps:\n\n"
        f"**Consultation Notes Overview:**\n{formatted_notes}\n\n"
        "**General Recommendations:**\n"
        "- Follow all prescription instructions closely.\n"
        "- Keep yourself well-hydrated and rest as advised.\n"
        "- Please monitor your symptoms. If they worsen or you experience new complications, contact the clinic immediately."
    )
    return fallback_text
