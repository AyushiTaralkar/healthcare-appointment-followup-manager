from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, time, timezone, timedelta
from typing import List, Optional

from database import get_db
from models import User, DoctorProfile, DoctorLeave, SlotHold, Appointment
from schemas import DoctorProfileResponse, SlotHoldCreate, SlotHoldResponse, AppointmentBook, AppointmentResponse
from auth.dependencies import get_current_patient
from services.llm import generate_pre_visit_summary
from services.email import queue_and_send_email
from services.calendar import create_calendar_event

router = APIRouter(
    prefix="/patient",
    tags=["Patient Operations"]
)


@router.get("/doctors", response_model=List[DoctorProfileResponse])
def search_doctors(
    specialisation: Optional[str] = None,
    db: Session = Depends(get_db),
    patient: User = Depends(get_current_patient)
):
    query = (
        db.query(DoctorProfile, User)
        .join(User, DoctorProfile.user_id == User.id)
    )
    
    if specialisation:
        query = query.filter(DoctorProfile.specialisation.ilike(f"%{specialisation}%"))
        
    results = query.all()
    
    doctors = []
    for profile, user in results:
        doctors.append(
            DoctorProfileResponse(
                id=profile.id,
                user_id=user.id,
                name=user.name,
                email=user.email,
                specialisation=profile.specialisation,
                working_start_time=profile.working_start_time,
                working_end_time=profile.working_end_time,
                slot_duration=profile.slot_duration
            )
        )
    return doctors


@router.get("/doctors/{doctor_id}/slots")
def get_available_slots(
    doctor_id: int,
    slot_date: date,
    db: Session = Depends(get_db),
    patient: User = Depends(get_current_patient)
):
    profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == doctor_id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found"
        )
        
    # Check if doctor is on leave
    is_on_leave = (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.leave_date == slot_date
        )
        .first()
    )
    if is_on_leave:
        return []
        
    # Parse start and end times
    try:
        sh, sm = map(int, profile.working_start_time.split(":"))
        eh, em = map(int, profile.working_end_time.split(":"))
    except ValueError:
        sh, sm = 9, 0
        eh, em = 17, 0
        
    start_dt = datetime.combine(slot_date, time(sh, sm)).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(slot_date, time(eh, em)).replace(tzinfo=timezone.utc)
    
    slot_duration = timedelta(minutes=profile.slot_duration)
    slots = []
    
    # Query booked appointments
    booked_appointments = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.status == "CONFIRMED",
            Appointment.start_time >= start_dt,
            Appointment.start_time < end_dt
        )
        .all()
    )
    booked_starts = {appt.start_time.replace(tzinfo=timezone.utc) for appt in booked_appointments}
    
    # Query active holds
    now_utc = datetime.now(timezone.utc)
    active_holds = (
        db.query(SlotHold)
        .filter(
            SlotHold.doctor_id == doctor_id,
            SlotHold.expires_at > now_utc,
            SlotHold.slot_time >= start_dt,
            SlotHold.slot_time < end_dt
        )
        .all()
    )
    # Map slot_time -> patient_id of hold
    held_slots = {hold.slot_time.replace(tzinfo=timezone.utc): hold.patient_id for hold in active_holds}
    
    curr_dt = start_dt
    while curr_dt + slot_duration <= end_dt:
        slot_end = curr_dt + slot_duration
        
        # Check if already booked
        is_booked = curr_dt in booked_starts
        
        # Check if held by someone else
        held_by = held_slots.get(curr_dt)
        is_held = held_by is not None
        is_held_by_me = held_by == patient.id
        
        is_available = not is_booked and (not is_held or is_held_by_me)
        
        # Filter out slots in the past
        if curr_dt > now_utc:
            slots.append({
                "start_time": curr_dt,
                "end_time": slot_end,
                "is_available": is_available,
                "is_held_by_me": is_held_by_me
            })
            
        curr_dt = slot_end
        
    return slots


@router.post("/slots/hold", response_model=SlotHoldResponse)
def hold_appointment_slot(
    hold_data: SlotHoldCreate,
    db: Session = Depends(get_db),
    patient: User = Depends(get_current_patient)
):
    doctor_id = hold_data.doctor_id
    slot_time = hold_data.slot_time.replace(tzinfo=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    
    # 1. Fetch Doctor Profile
    profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == doctor_id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found"
        )
        
    # 2. Check if date is on leave
    is_on_leave = (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.leave_date == slot_time.date()
        )
        .first()
    )
    if is_on_leave:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Doctor is on leave on this date"
        )
        
    # 3. Check if slot falls in working hours
    try:
        sh, sm = map(int, profile.working_start_time.split(":"))
        eh, em = map(int, profile.working_end_time.split(":"))
    except ValueError:
        sh, sm = 9, 0
        eh, em = 17, 0
        
    slot_local_time = slot_time.time()
    work_start = time(sh, sm)
    work_end = time(eh, em)
    
    if not (work_start <= slot_local_time < work_end):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requested slot is outside doctor working hours"
        )
        
    # CONCURRENCY LOCK SECTION
    # Using transactional locks (SELECT FOR UPDATE) to ensure slot holds are created safely
    try:
        # A. Lock/Check existing CONFIRMED bookings for this slot
        existing_booking = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id == doctor_id,
                Appointment.start_time == slot_time,
                Appointment.status == "CONFIRMED"
            )
            .with_for_update()
            .first()
        )
        if existing_booking:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This slot is already booked"
            )
            
        # B. Lock/Check active holds for this slot by other patients
        existing_hold = (
            db.query(SlotHold)
            .filter(
                SlotHold.doctor_id == doctor_id,
                SlotHold.slot_time == slot_time,
                SlotHold.expires_at > now_utc,
                SlotHold.patient_id != patient.id
            )
            .with_for_update()
            .first()
        )
        if existing_hold:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This slot is held by another patient"
            )
            
        # C. Upsert slot hold for the current patient
        patient_hold = (
            db.query(SlotHold)
            .filter(
                SlotHold.doctor_id == doctor_id,
                SlotHold.slot_time == slot_time,
                SlotHold.patient_id == patient.id
            )
            .first()
        )
        
        expiry_time = now_utc + timedelta(minutes=10)
        
        if patient_hold:
            patient_hold.expires_at = expiry_time
        else:
            patient_hold = SlotHold(
                doctor_id=doctor_id,
                patient_id=patient.id,
                slot_time=slot_time,
                expires_at=expiry_time
            )
            db.add(patient_hold)
            
        db.commit()
        db.refresh(patient_hold)
        return patient_hold
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Safety lock verification failed: {str(e)}"
        )


@router.post("/appointments/book", response_model=AppointmentResponse)
def book_appointment(
    booking_data: AppointmentBook,
    db: Session = Depends(get_db),
    patient: User = Depends(get_current_patient)
):
    now_utc = datetime.now(timezone.utc)
    
    # 1. Fetch and validate hold
    hold = db.query(SlotHold).filter(SlotHold.id == booking_data.slot_hold_id).first()
    if not hold:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Slot hold reservation not found"
        )
        
    if hold.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This slot hold belongs to another patient"
        )
        
    if hold.expires_at < now_utc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your slot hold reservation has expired. Please select the slot again."
        )
        
    doctor_id = hold.doctor_id
    slot_time = hold.slot_time.replace(tzinfo=timezone.utc)
    
    # Fetch doctor and profile
    doctor = db.query(User).filter(User.id == doctor_id, User.role == "DOCTOR").first()
    profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == doctor_id).first()
    if not doctor or not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found"
        )
        
    # Re-verify that no one else booked it in a race condition
    double_booking = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.start_time == slot_time,
            Appointment.status == "CONFIRMED"
        )
        .first()
    )
    if double_booking:
        db.delete(hold)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This slot was recently booked. Please choose another."
        )
        
    # Calculate end time
    end_time = slot_time + timedelta(minutes=profile.slot_duration)
    
    # 2. LLM Call for Pre-Visit summary
    try:
        ai_summary = generate_pre_visit_summary(booking_data.symptoms)
    except Exception as e:
        # Resilient engineering: Fallback if LLM raises unexpected exception
        ai_summary = {
            "urgency_level": "Low",
            "chief_complaint": "Symptom check requested",
            "suggested_questions": ["How long have you felt these symptoms?"],
            "summary_text": f"Symptom summary fallback. Patient symptoms: {booking_data.symptoms}"
        }
        
    # 3. Create Appointment
    appt = Appointment(
        patient_id=patient.id,
        doctor_id=doctor_id,
        start_time=slot_time,
        end_time=end_time,
        status="CONFIRMED",
        symptoms=booking_data.symptoms,
        urgency_level=ai_summary.get("urgency_level", "Low"),
        chief_complaint=ai_summary.get("chief_complaint", ""),
        suggested_questions=ai_summary.get("suggested_questions", []),
        pre_visit_summary=ai_summary.get("summary_text", "")
    )
    
    db.add(appt)
    db.delete(hold)  # Release the slot hold
    db.commit()
    db.refresh(appt)
    
    # 4. Integrate Google Calendar
    event_id = create_calendar_event(db, appt)
    if event_id:
        appt.google_calendar_event_id = event_id
        db.commit()
        db.refresh(appt)
        
    # 5. Email Notifications
    time_str = appt.start_time.strftime('%Y-%m-%d at %H:%M UTC')
    
    # Email to Patient
    patient_subject = "Appointment Confirmation"
    patient_body = (
        f"Dear {patient.name},\n\n"
        f"Your appointment with Dr. {doctor.name} has been successfully confirmed!\n\n"
        f"Details:\n"
        f"- Doctor: Dr. {doctor.name} ({profile.specialisation})\n"
        f"- Date/Time: {time_str}\n"
        f"- Symptoms Reported: {appt.symptoms}\n\n"
        f"An AI pre-visit summary has been shared with your doctor.\n"
        f"If you need to reschedule or cancel, please contact the admin office or use your portal.\n\n"
        f"Best regards,\nHealthcare Appointment Clinic"
    )
    queue_and_send_email(db, patient.email, patient_subject, patient_body)
    
    # Email to Doctor
    doctor_subject = f"New Appointment Booked: {patient.name}"
    doctor_body = (
        f"Dr. {doctor.name},\n\n"
        f"A new appointment has been scheduled with you.\n\n"
        f"Details:\n"
        f"- Patient: {patient.name}\n"
        f"- Date/Time: {time_str}\n"
        f"- Urgency Level: {appt.urgency_level}\n"
        f"- Chief Complaint: {appt.chief_complaint}\n"
        f"- Pre-visit Summary: {appt.pre_visit_summary}\n\n"
        f"Suggested clinical interview questions:\n"
        f"1. {appt.suggested_questions[0] if len(appt.suggested_questions) > 0 else 'N/A'}\n"
        f"2. {appt.suggested_questions[1] if len(appt.suggested_questions) > 1 else 'N/A'}\n"
        f"3. {appt.suggested_questions[2] if len(appt.suggested_questions) > 2 else 'N/A'}\n\n"
        f"Please view your doctor portal to check details.\n\n"
        f"Sincerely,\nClinic Notification Desk"
    )
    queue_and_send_email(db, doctor.email, doctor_subject, doctor_body)
    
    # Return structured details
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
        google_calendar_event_id=appt.google_calendar_event_id
    )


@router.get("/appointments", response_model=List[AppointmentResponse])
def get_patient_appointments(
    db: Session = Depends(get_db),
    patient: User = Depends(get_current_patient)
):
    appts = (
        db.query(Appointment)
        .filter(Appointment.patient_id == patient.id)
        .order_by(Appointment.start_time.desc())
        .all()
    )
    
    responses = []
    for appt in appts:
        responses.append(
            AppointmentResponse(
                id=appt.id,
                patient_id=appt.patient_id,
                patient_name=patient.name,
                doctor_id=appt.doctor_id,
                doctor_name=appt.doctor.name,
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


@router.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    patient: User = Depends(get_current_patient)
):
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found"
        )
        
    if appt.patient_id != patient.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This appointment does not belong to you"
        )
        
    if appt.status == "CANCELLED":
        return {"message": "Appointment is already cancelled"}
        
    appt.status = "CANCELLED"
    db.commit()
    
    # Delete Calendar Event
    if appt.google_calendar_event_id:
        delete_calendar_event(db, appt.google_calendar_event_id)
        appt.google_calendar_event_id = None
        db.commit()
        
    # Notify Doctor
    doctor = appt.doctor
    doctor_subject = "Appointment Cancelled by Patient"
    doctor_body = (
        f"Dr. {doctor.name},\n\n"
        f"The appointment with Patient {patient.name} on {appt.start_time.strftime('%Y-%m-%d at %H:%M UTC')} "
        f"has been cancelled by the patient.\n\n"
        f"Sincerely,\nClinic Notification Desk"
    )
    queue_and_send_email(db, doctor.email, doctor_subject, doctor_body)
    
    return {"message": "Appointment cancelled successfully"}
