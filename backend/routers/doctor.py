import re
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import List

from database import get_db
from models import User, Appointment, MedicationReminder
from schemas import AppointmentResponse, DoctorNotesSubmit
from auth.dependencies import get_current_doctor
from services.llm import generate_post_visit_summary
from services.email import queue_and_send_email
from services.calendar import update_calendar_event

router = APIRouter(
    prefix="/doctor",
    tags=["Doctor Operations"]
)

logger = logging.getLogger(__name__)


def parse_prescription_reminders(prescription_text: str) -> List[tuple[str, str]]:
    """
    Parse medication name and frequency from prescription lines.
    Matches frequencies: 'Daily', 'Twice daily', 'Three times daily', 'Weekly'.
    """
    reminders = []
    lines = [line.strip() for line in prescription_text.split("\n") if line.strip()]
    
    for line in lines:
        freq = "Daily"
        med_name = line
        
        # Regex checks
        if re.search(r"\btwice\s+daily\b", line, re.IGNORECASE):
            freq = "Twice daily"
            med_name = re.sub(r"[-\s,:]*\btwice\s+daily\b", "", line, flags=re.IGNORECASE).strip()
        elif re.search(r"\bthree\s+times\s+daily\b", line, re.IGNORECASE):
            freq = "Three times daily"
            med_name = re.sub(r"[-\s,:]*\bthree\s+times\s+daily\b", "", line, flags=re.IGNORECASE).strip()
        elif re.search(r"\bonce\s+daily\b|\bdaily\b", line, re.IGNORECASE):
            freq = "Daily"
            med_name = re.sub(r"[-\s,:]*\b(once\s+daily|daily)\b", "", line, flags=re.IGNORECASE).strip()
        elif re.search(r"\bweekly\b", line, re.IGNORECASE):
            freq = "Weekly"
            med_name = re.sub(r"[-\s,:]*\bweekly\b", "", line, flags=re.IGNORECASE).strip()
            
        # Clean formatting characters
        med_name = re.sub(r"^[*-\s]+|[*-\s]+$", "", med_name).strip()
        if med_name:
            reminders.append((med_name, freq))
            
    return reminders


@router.get("/appointments", response_model=List[AppointmentResponse])
def get_doctor_appointments(
    db: Session = Depends(get_db),
    doctor: User = Depends(get_current_doctor)
):
    appts = (
        db.query(Appointment)
        .filter(Appointment.doctor_id == doctor.id)
        .order_by(Appointment.start_time.desc())
        .all()
    )
    
    responses = []
    for appt in appts:
        responses.append(
            AppointmentResponse(
                id=appt.id,
                patient_id=appt.patient_id,
                patient_name=appt.patient.name,
                doctor_id=appt.doctor_id,
                doctor_name=doctor.name,
                start_time=appt.start_time,
                end_time=appt.end_time,
                status=appt.status,
                symptoms=appt.symptoms,
                urgency_level=appt.urgency_level,
                chief_complaint=appt.chief_complaint,
                suggested_questions=appt.suggested_questions,
                pre_visit_summary=appt.pre_visit_summary,
                doctor_notes=appt.doctor_notes,
                prescription=appt.prescription,
                post_visit_summary=appt.post_visit_summary,
                google_calendar_event_id=appt.google_calendar_event_id
            )
        )
    return responses


@router.post("/appointments/{appointment_id}/notes", response_model=AppointmentResponse)
def submit_visit_notes(
    appointment_id: int,
    notes_data: DoctorNotesSubmit,
    db: Session = Depends(get_db),
    doctor: User = Depends(get_current_doctor)
):
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found"
        )
        
    if appt.doctor_id != doctor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This appointment is not assigned to you"
        )
        
    if appt.status == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add notes to a cancelled appointment"
        )
        
    appt.doctor_notes = notes_data.notes
    appt.prescription = notes_data.prescription
    appt.status = "COMPLETED"
    
    # 1. Generate patient friendly visit summary
    try:
        post_summary = generate_post_visit_summary(notes_data.notes)
    except Exception as e:
        logger.error(f"Post-visit LLM error: {str(e)}")
        # Simple fallback
        post_summary = (
            f"### Clinic Visit Summary\n\n"
            f"Doctor Notes:\n{notes_data.notes}\n\n"
            f"Prescription Details:\n{notes_data.prescription}\n"
        )
        
    appt.post_visit_summary = post_summary
    db.commit()
    db.refresh(appt)
    
    # 2. Parse and Schedule Medication Reminders
    parsed_reminders = parse_prescription_reminders(notes_data.prescription)
    now_utc = datetime.now(timezone.utc)
    
    # Clean up any existing reminders for this appointment first
    db.query(MedicationReminder).filter(MedicationReminder.appointment_id == appointment_id).delete()
    
    for med_name, freq in parsed_reminders:
        # First reminder scheduled based on frequency
        if "twice" in freq.lower():
            next_time = now_utc + timedelta(hours=12)
        elif "three" in freq.lower():
            next_time = now_utc + timedelta(hours=8)
        elif "weekly" in freq.lower():
            next_time = now_utc + timedelta(days=7)
        else:
            next_time = now_utc + timedelta(days=1)
            
        reminder = MedicationReminder(
            appointment_id=appt.id,
            patient_id=appt.patient_id,
            medication_name=med_name,
            frequency=freq,
            next_reminder_time=next_time,
            is_active=True
        )
        db.add(reminder)
        
    db.commit()
    
    # 3. Update Calendar Event (sync notes/prescription)
    if appt.google_calendar_event_id:
        update_calendar_event(db, appt)
        
    # 4. Notify Patient via Email
    patient = appt.patient
    email_subject = "Your Post-Visit Summary & Prescription Details"
    email_body = (
        f"Dear {patient.name},\n\n"
        f"Dr. {doctor.name} has completed your visit and submitted notes and prescriptions.\n\n"
        f"Here is a patient-friendly summary of your visit:\n"
        f"{appt.post_visit_summary}\n\n"
        f"Prescribed Medications:\n"
        f"{appt.prescription}\n\n"
        f"You will receive automatic reminders for your medications via email based on the schedule.\n\n"
        f"Best regards,\nHealthcare Appointment Clinic"
    )
    queue_and_send_email(db, patient.email, email_subject, email_body)
    
    return AppointmentResponse(
        id=appt.id,
        patient_id=appt.patient_id,
        patient_name=patient.name,
        doctor_id=appt.doctor_id,
        doctor_name=doctor.name,
        start_time=appt.start_time,
        end_time=appt.end_time,
        status=appt.status,
        symptoms=appt.symptoms,
        urgency_level=appt.urgency_level,
        chief_complaint=appt.chief_complaint,
        suggested_questions=appt.suggested_questions,
        pre_visit_summary=appt.pre_visit_summary,
        doctor_notes=appt.doctor_notes,
        prescription=appt.prescription,
        post_visit_summary=appt.post_visit_summary,
        google_calendar_event_id=appt.google_calendar_event_id
    )
