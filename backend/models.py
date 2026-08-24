from sqlalchemy import Column, Integer, String, DateTime, Date, Boolean, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="PATIENT")  # PATIENT, DOCTOR, ADMIN
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    doctor_profile = relationship("DoctorProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    leaves = relationship("DoctorLeave", back_populates="doctor", cascade="all, delete-orphan")
    appointments_as_patient = relationship("Appointment", foreign_keys="[Appointment.patient_id]", back_populates="patient", cascade="all, delete-orphan")
    appointments_as_doctor = relationship("Appointment", foreign_keys="[Appointment.doctor_id]", back_populates="doctor", cascade="all, delete-orphan")
    slot_holds = relationship("SlotHold", foreign_keys="[SlotHold.patient_id]", back_populates="patient", cascade="all, delete-orphan")


class DoctorProfile(Base):
    __tablename__ = "doctor_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    specialisation = Column(String, nullable=False)
    working_start_time = Column(String, nullable=False, default="09:00")  # HH:MM format
    working_end_time = Column(String, nullable=False, default="17:00")    # HH:MM format
    slot_duration = Column(Integer, nullable=False, default=30)          # minutes
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    user = relationship("User", back_populates="doctor_profile")


class DoctorLeave(Base):
    __tablename__ = "doctor_leaves"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    leave_date = Column(Date, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    doctor = relationship("User", back_populates="leaves")


class SlotHold(Base):
    __tablename__ = "slot_holds"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slot_time = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    patient = relationship("User", foreign_keys=[patient_id], back_populates="slot_holds")
    doctor = relationship("User", foreign_keys=[doctor_id])


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False, default="CONFIRMED")  # CONFIRMED, CANCELLED, COMPLETED
    
    # Pre-visit symptoms & AI output
    symptoms = Column(String, nullable=True)
    urgency_level = Column(String, nullable=True)          # Low, Medium, High
    chief_complaint = Column(String, nullable=True)
    suggested_questions = Column(JSON, nullable=True)      # List of strings
    pre_visit_summary = Column(String, nullable=True)
    
    # Post-visit clinical notes & prescription
    doctor_notes = Column(String, nullable=True)
    prescription = Column(String, nullable=True)
    post_visit_summary = Column(String, nullable=True)
    
    # Calendar sync
    google_calendar_event_id = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    patient = relationship("User", foreign_keys=[patient_id], back_populates="appointments_as_patient")
    doctor = relationship("User", foreign_keys=[doctor_id], back_populates="appointments_as_doctor")
    reminders = relationship("MedicationReminder", back_populates="appointment", cascade="all, delete-orphan")


class MedicationReminder(Base):
    __tablename__ = "medication_reminders"

    id = Column(Integer, primary_key=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    medication_name = Column(String, nullable=False)
    frequency = Column(String, nullable=False)             # Daily, Twice daily, Weekly
    next_reminder_time = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    appointment = relationship("Appointment", back_populates="reminders")
    patient = relationship("User", foreign_keys=[patient_id])


class EmailQueue(Base):
    __tablename__ = "email_queue"

    id = Column(Integer, primary_key=True, index=True)
    recipient = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING")  # PENDING, SENT, FAILED
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )


class GoogleCredentials(Base):
    __tablename__ = "google_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # Null if global system credentials
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=True)
    token_expiry = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )