from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import timedelta
import logging

from database import get_db
from models import User, DoctorProfile, Appointment
from schemas import AppointmentCreate, AppointmentResponse
from auth.dependencies import get_current_user
from services.llm import generate_pre_visit_summary
from services.email import queue_and_send_email


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# ROUTER
# ============================================================

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
            status_code=403,
            detail="Only patients can view doctors"
        )

    doctors = (
        db.query(DoctorProfile)
        .join(User, DoctorProfile.user_id == User.id)
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

    # --------------------------------------------------------
    # Check patient role
    # --------------------------------------------------------

    if current_user.role != "PATIENT":
        raise HTTPException(
            status_code=403,
            detail="Only patients can book appointments"
        )

    # --------------------------------------------------------
    # Find doctor
    # --------------------------------------------------------

    doctor = (
        db.query(DoctorProfile)
        .filter(
            DoctorProfile.id == appointment_data.doctor_id
        )
        .first()
    )

    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Doctor not found"
        )

    # --------------------------------------------------------
    # Calculate appointment end time
    # --------------------------------------------------------

    start_time = appointment_data.start_time

    end_time = start_time + timedelta(
        minutes=doctor.slot_duration
    )

    # --------------------------------------------------------
    # Prevent double booking
    # --------------------------------------------------------

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
            status_code=409,
            detail="This slot is already booked"
        )

    # --------------------------------------------------------
    # AI PRE-VISIT SUMMARY
    # --------------------------------------------------------

    symptoms = (
        appointment_data.symptoms
        or "No symptoms provided."
    )

    try:

        ai_result = generate_pre_visit_summary(
            symptoms
        )

    except Exception as e:

        logger.exception(
            "Pre-visit AI generation failed: %s",
            e
        )

        # Safe fallback
        ai_result = {
            "urgency_level": "Low",

            "chief_complaint": symptoms[:100],

            "suggested_questions": [
                "How long have you had these symptoms?",
                "Are the symptoms getting better or worse?",
                "Are you taking any medication currently?"
            ],

            "summary_text": (
                f"Patient reported: {symptoms}"
            )
        }

    # --------------------------------------------------------
    # CREATE APPOINTMENT
    # --------------------------------------------------------

    appointment = Appointment(
        patient_id=current_user.id,

        doctor_id=doctor.id,

        start_time=start_time,

        end_time=end_time,

        status="BOOKED",

        symptoms=symptoms,

        urgency_level=ai_result.get(
            "urgency_level",
            "Low"
        ),

        chief_complaint=ai_result.get(
            "chief_complaint"
        ),

        suggested_questions=ai_result.get(
            "suggested_questions",
            []
        ),

        pre_visit_summary=ai_result.get(
            "summary_text"
        )
    )

    db.add(appointment)

    # --------------------------------------------------------
    # SAVE APPOINTMENT
    # --------------------------------------------------------

    try:

        db.commit()

        db.refresh(appointment)

    except IntegrityError:

        db.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                "This appointment could not be booked "
                "because the slot was taken."
            )
        )

    # ========================================================
    # EMAIL NOTIFICATIONS
    # ========================================================

    # Email is sent only after the appointment has been
    # successfully committed.
    #
    # If email fails, the appointment remains booked.
    # ========================================================

    try:

        # ----------------------------------------------------
        # Patient confirmation
        # ----------------------------------------------------

        queue_and_send_email(
            to=current_user.email,

            subject="Appointment Booked Successfully",

            template="appointment_confirmation",

            context={
                "patient_name": current_user.name,

                "doctor_name": doctor.user.name,

                "specialisation": doctor.specialisation,

                "start_time": appointment.start_time,

                "end_time": appointment.end_time,

                "urgency_level": (
                    appointment.urgency_level
                ),

                "chief_complaint": (
                    appointment.chief_complaint
                ),

                "pre_visit_summary": (
                    appointment.pre_visit_summary
                ),

                "suggested_questions": (
                    appointment.suggested_questions
                )
            }
        )

        # ----------------------------------------------------
        # Doctor notification
        # ----------------------------------------------------

        queue_and_send_email(
            to=doctor.user.email,

            subject="New Patient Appointment",

            template="doctor_appointment_notification",

            context={
                "doctor_name": doctor.user.name,

                "patient_name": current_user.name,

                "start_time": appointment.start_time,

                "end_time": appointment.end_time,

                "symptoms": appointment.symptoms,

                "urgency_level": (
                    appointment.urgency_level
                ),

                "chief_complaint": (
                    appointment.chief_complaint
                ),

                "suggested_questions": (
                    appointment.suggested_questions
                )
            }
        )

        logger.info(
            "Appointment email notifications sent successfully "
            "for appointment %s",
            appointment.id
        )

    except Exception as e:

        # Email failure must not cancel a successful booking.

        logger.exception(
            "Appointment email notification failed "
            "for appointment %s: %s",
            appointment.id,
            e
        )

    # --------------------------------------------------------
    # RETURN APPOINTMENT
    # --------------------------------------------------------

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

        suggested_questions=(
            appointment.suggested_questions
        ),

        pre_visit_summary=(
            appointment.pre_visit_summary
        ),

        doctor_notes=appointment.doctor_notes,

        prescription=appointment.prescription,

        post_visit_summary=(
            appointment.post_visit_summary
        ),

        google_calendar_event_id=(
            appointment.google_calendar_event_id
        )
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
            status_code=403,
            detail="Only patients can view appointments"
        )

    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == current_user.id
        )
        .order_by(
            Appointment.start_time
        )
        .all()
    )

    return [
        AppointmentResponse(

            id=a.id,

            patient_id=a.patient_id,

            patient_name=current_user.name,

            doctor_id=a.doctor_id,

            # IMPORTANT:
            # Appointment.doctor is already a User object.
            doctor_name=a.doctor.name,

            start_time=a.start_time,

            end_time=a.end_time,

            status=a.status,

            symptoms=a.symptoms,

            urgency_level=a.urgency_level,

            chief_complaint=a.chief_complaint,

            suggested_questions=(
                a.suggested_questions
            ),

            pre_visit_summary=(
                a.pre_visit_summary
            ),

            doctor_notes=a.doctor_notes,

            prescription=a.prescription,

            post_visit_summary=(
                a.post_visit_summary
            ),

            google_calendar_event_id=(
                a.google_calendar_event_id
            )
        )

        for a in appointments
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

    # --------------------------------------------------------
    # Find patient's appointment
    # --------------------------------------------------------

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
            status_code=404,
            detail="Appointment not found"
        )

    # --------------------------------------------------------
    # Check already cancelled
    # --------------------------------------------------------

    if appointment.status == "CANCELLED":
        raise HTTPException(
            status_code=400,
            detail="Appointment is already cancelled"
        )

    # --------------------------------------------------------
    # Cancel appointment
    # --------------------------------------------------------

    appointment.status = "CANCELLED"

    try:

        db.commit()

        db.refresh(appointment)

    except Exception as e:

        db.rollback()

        logger.exception(
            "Failed to cancel appointment %s: %s",
            appointment_id,
            e
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to cancel appointment"
        )

    # --------------------------------------------------------
    # Cancellation email
    # --------------------------------------------------------

    try:

        doctor = appointment.doctor

        # ----------------------------------------------------
        # Notify patient
        # ----------------------------------------------------

        queue_and_send_email(
            to=current_user.email,

            subject="Appointment Cancelled",

            template="appointment_cancelled",

            context={
                "patient_name": current_user.name,

                "doctor_name": doctor.name,

                "start_time": appointment.start_time,

                "end_time": appointment.end_time
            }
        )

        # ----------------------------------------------------
        # Notify doctor
        # ----------------------------------------------------

        queue_and_send_email(
            to=doctor.email,

            subject="Patient Appointment Cancelled",

            template="doctor_appointment_cancelled",

            context={
                "doctor_name": doctor.name,

                "patient_name": current_user.name,

                "start_time": appointment.start_time,

                "end_time": appointment.end_time
            }
        )

        logger.info(
            "Cancellation notifications sent for appointment %s",
            appointment.id
        )

    except Exception as e:

        # Email failure must not undo cancellation.

        logger.exception(
            "Cancellation email notification failed "
            "for appointment %s: %s",
            appointment.id,
            e
        )

    return {
        "message": "Appointment cancelled successfully"
    }