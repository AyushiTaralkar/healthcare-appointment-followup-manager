from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date
from typing import List

from database import get_db
from models import User, DoctorProfile, DoctorLeave, Appointment
from schemas import DoctorCreate, DoctorProfileResponse, DoctorProfileUpdate, DoctorLeaveCreate, DoctorLeaveResponse
from auth.security import hash_password
from auth.dependencies import get_current_admin
from services.email import queue_and_send_email
from services.calendar import delete_calendar_event

router = APIRouter(
    prefix="/admin",
    tags=["Admin Management"]
)


@router.post("/doctors", response_model=DoctorProfileResponse, status_code=status.HTTP_201_CREATED)
def create_doctor(
    doc_data: DoctorCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == doc_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
        
    # Create doctor user
    doctor_user = User(
        name=doc_data.name,
        email=doc_data.email,
        password_hash=hash_password(doc_data.password),
        role="DOCTOR"
    )
    db.add(doctor_user)
    db.commit()
    db.refresh(doctor_user)
    
    # Create doctor profile
    doctor_profile = DoctorProfile(
        user_id=doctor_user.id,
        specialisation=doc_data.specialisation,
        working_start_time=doc_data.working_start_time,
        working_end_time=doc_data.working_end_time,
        slot_duration=doc_data.slot_duration
    )
    db.add(doctor_profile)
    db.commit()
    db.refresh(doctor_profile)
    
    return DoctorProfileResponse(
        id=doctor_profile.id,
        user_id=doctor_user.id,
        name=doctor_user.name,
        email=doctor_user.email,
        specialisation=doctor_profile.specialisation,
        working_start_time=doctor_profile.working_start_time,
        working_end_time=doctor_profile.working_end_time,
        slot_duration=doctor_profile.slot_duration
    )


@router.get("/doctors", response_model=List[DoctorProfileResponse])
def get_all_doctors(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    results = (
        db.query(DoctorProfile, User)
        .join(User, DoctorProfile.user_id == User.id)
        .all()
    )
    
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


@router.put("/doctors/{doctor_id}", response_model=DoctorProfileResponse)
def update_doctor_profile(
    doctor_id: int,
    profile_data: DoctorProfileUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == doctor_id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found"
        )
        
    doctor_user = db.query(User).filter(User.id == doctor_id).first()
    
    if profile_data.specialisation is not None:
        profile.specialisation = profile_data.specialisation
    if profile_data.working_start_time is not None:
        profile.working_start_time = profile_data.working_start_time
    if profile_data.working_end_time is not None:
        profile.working_end_time = profile_data.working_end_time
    if profile_data.slot_duration is not None:
        profile.slot_duration = profile_data.slot_duration
        
    db.commit()
    db.refresh(profile)
    
    return DoctorProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        name=doctor_user.name,
        email=doctor_user.email,
        specialisation=profile.specialisation,
        working_start_time=profile.working_start_time,
        working_end_time=profile.working_end_time,
        slot_duration=profile.slot_duration
    )


@router.post("/doctors/{doctor_id}/leaves", response_model=DoctorLeaveResponse, status_code=status.HTTP_201_CREATED)
def create_doctor_leave(
    doctor_id: int,
    leave_data: DoctorLeaveCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    # Verify doctor user exists
    doctor = db.query(User).filter(User.id == doctor_id, User.role == "DOCTOR").first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor user not found"
        )
        
    # Check if leave date already exists
    existing_leave = (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.leave_date == leave_data.leave_date
        )
        .first()
    )
    if existing_leave:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Leave date already registered for this doctor"
        )
        
    # Save DoctorLeave
    doctor_leave = DoctorLeave(
        doctor_id=doctor_id,
        leave_date=leave_data.leave_date
    )
    db.add(doctor_leave)
    db.commit()
    db.refresh(doctor_leave)
    
    # Identify and process affected appointments on this date
    # Start and end of the leave date
    target_date = leave_data.leave_date
    
    affected_appointments = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.status == "CONFIRMED"
        )
        .all()
    )
    
    cancelled_count = 0
    for appt in affected_appointments:
        appt_date = appt.start_time.date()
        if appt_date == target_date:
            appt.status = "CANCELLED"
            cancelled_count += 1
            
            # Send notification email to Patient
            patient = appt.patient
            patient_subject = "Important: Appointment Cancellation Notice"
            patient_body = (
                f"Dear {patient.name},\n\n"
                f"We regret to inform you that your appointment with Dr. {doctor.name} scheduled "
                f"for {appt.start_time.strftime('%Y-%m-%d at %H:%M UTC')} has been cancelled because "
                f"the doctor will be on leave.\n\n"
                f"Please log in to your patient portal to reschedule your appointment.\n\n"
                f"Sincerely,\nClinic Administration"
            )
            queue_and_send_email(db, patient.email, patient_subject, patient_body)
            
            # Send notification email to Doctor
            doctor_subject = "Leave Schedule Update: Appointment Cancelled"
            doctor_body = (
                f"Dr. {doctor.name},\n\n"
                f"Your appointment with Patient {patient.name} on {appt.start_time.strftime('%Y-%m-%d at %H:%M UTC')} "
                f"has been cancelled due to your scheduled leave on {target_date.strftime('%Y-%m-%d')}.\n\n"
                f"Sincerely,\nClinic Administration"
            )
            queue_and_send_email(db, doctor.email, doctor_subject, doctor_body)
            
            # Delete event from Google Calendar if event_id is saved
            if appt.google_calendar_event_id:
                delete_calendar_event(db, appt.google_calendar_event_id)
                appt.google_calendar_event_id = None
                
    db.commit()
    
    return doctor_leave


@router.get("/doctors/{doctor_id}/leaves", response_model=List[DoctorLeaveResponse])
def get_doctor_leaves(
    doctor_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    leaves = db.query(DoctorLeave).filter(DoctorLeave.doctor_id == doctor_id).all()
    return leaves


@router.delete("/doctors/{doctor_id}/leaves/{leave_id}")
def delete_doctor_leave(
    doctor_id: int,
    leave_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    leave = (
        db.query(DoctorLeave)
        .filter(DoctorLeave.id == leave_id, DoctorLeave.doctor_id == doctor_id)
        .first()
    )
    if not leave:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave day not found"
        )
        
    db.delete(leave)
    db.commit()
    return {"message": "Leave day removed successfully"}
