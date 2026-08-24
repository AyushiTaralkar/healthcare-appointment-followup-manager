from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import User, DoctorProfile, Appointment
from schemas import AppointmentCreate, AppointmentResponse
from auth.dependencies import get_current_user


router = APIRouter(
    prefix="/patient",
    tags=["Patient"]
)


# ============================================================
# GET DOCTORS
# ============================================================

@router.get("/doctors")
def get_doctors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "PATIENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can view doctors"
        )

    doctors = (
        db.query(DoctorProfile)
        .join(
            User,
            DoctorProfile.user_id == User.id
        )
        .all()
    )

    return [
        {
            "id": doctor.id,
            "name": doctor.user.name,
            "email": doctor.user.email,
            "specialisation": doctor.specialisation,
            "working_start_time": str(
                doctor.working_start_time
            ),
            "working_end_time": str(
                doctor.working_end_time
            ),
            "slot_duration": doctor.slot_duration
        }
        for doctor in doctors
    ]


# ============================================================
# BOOK APPOINTMENT
# ============================================================

@router.post(
    "/appointments",
    response_model=AppointmentResponse
)
def book_appointment(
    appointment_data: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "PATIENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can book appointments"
        )

    doctor = (
        db.query(DoctorProfile)
        .filter(
            DoctorProfile.id == appointment_data.doctor_id
        )
        .first()
    )

    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found"
        )

    start_time = appointment_data.start_time

    end_time = (
        start_time
        + timedelta(minutes=doctor.slot_duration)
    )

    # Prevent overlapping bookings
    existing = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.status.in_(
                ["BOOKED", "CONFIRMED"]
            ),
            Appointment.start_time < end_time,
            Appointment.end_time > start_time
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This slot is already booked"
        )

    appointment = Appointment(
        patient_id=current_user.id,
        doctor_id=doctor.id,
        start_time=start_time,
        end_time=end_time,
        status="BOOKED",
        symptoms=appointment_data.symptoms
    )

    db.add(appointment)

    try:
        db.commit()
        db.refresh(appointment)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This appointment could not be booked because the slot was taken"
        )

    return AppointmentResponse(
        id=appointment.id,
        patient_id=appointment.patient_id,
        patient_name=current_user.name,
        doctor_id=appointment.doctor_id,
        doctor_name=doctor.user.name,
        start_time=appointment.start_time,
        end_time=appointment.end_time,
        status=appointment.status,
        symptoms=appointment.symptoms,
        urgency_level=appointment.urgency_level,
        chief_complaint=appointment.chief_complaint,
        suggested_questions=appointment.suggested_questions,
        pre_visit_summary=appointment.pre_visit_summary,
        doctor_notes=appointment.doctor_notes,
        prescription=appointment.prescription,
        post_visit_summary=appointment.post_visit_summary,
        google_calendar_event_id=appointment.google_calendar_event_id
    )


# ============================================================
# GET MY APPOINTMENTS
# ============================================================

@router.get(
    "/appointments",
    response_model=list[AppointmentResponse]
)
def get_my_appointments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "PATIENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can view appointments"
        )

    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == current_user.id
        )
        .order_by(Appointment.start_time)
        .all()
    )

    return [
        AppointmentResponse(
            id=appt.id,
            patient_id=appt.patient_id,
            patient_name=current_user.name,
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
        for appt in appointments
    ]


# ============================================================
# CANCEL APPOINTMENT
# ============================================================

@router.delete(
    "/appointments/{appointment_id}"
)
def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "PATIENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only patients can cancel appointments"
        )

    appointment = (
        db.query(Appointment)
        .filter(
            Appointment.id == appointment_id,
            Appointment.patient_id == current_user.id
        )
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found"
        )

    if appointment.status == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Appointment is already cancelled"
        )

    appointment.status = "CANCELLED"

    db.commit()

    return {
        "message": "Appointment cancelled successfully",
        "appointment_id": appointment_id
    }