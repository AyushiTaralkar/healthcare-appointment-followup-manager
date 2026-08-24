from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, ConfigDict


# ============================================================
# AUTHENTICATION
# ============================================================

class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Optional[str] = "PATIENT"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    name: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# ADMIN / DOCTOR MANAGEMENT
# ============================================================

class DoctorCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    specialisation: str
    working_start_time: Optional[str] = "09:00"
    working_end_time: Optional[str] = "17:00"
    slot_duration: Optional[int] = 30


class DoctorProfileUpdate(BaseModel):
    specialisation: Optional[str] = None
    working_start_time: Optional[str] = None
    working_end_time: Optional[str] = None
    slot_duration: Optional[int] = None


class DoctorProfileResponse(BaseModel):
    id: int
    user_id: int
    name: str
    email: str
    specialisation: str
    working_start_time: str
    working_end_time: str
    slot_duration: int

    model_config = ConfigDict(from_attributes=True)


class DoctorLeaveCreate(BaseModel):
    leave_date: date


class DoctorLeaveResponse(BaseModel):
    id: int
    doctor_id: int
    leave_date: date

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# APPOINTMENTS
# ============================================================

class AppointmentCreate(BaseModel):
    doctor_id: int
    start_time: datetime
    symptoms: Optional[str] = None


class AppointmentResponse(BaseModel):
    id: int

    patient_id: int
    patient_name: str

    doctor_id: int
    doctor_name: str

    start_time: datetime
    end_time: datetime

    status: str

    symptoms: Optional[str] = None

    urgency_level: Optional[str] = None
    chief_complaint: Optional[str] = None
    suggested_questions: Optional[List[str]] = None
    pre_visit_summary: Optional[str] = None

    doctor_notes: Optional[str] = None
    prescription: Optional[str] = None
    post_visit_summary: Optional[str] = None

    google_calendar_event_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# DOCTOR CONSULTATION
# ============================================================

class DoctorNotesSubmit(BaseModel):
    notes: str
    prescription: str


# ============================================================
# MEDICATION REMINDERS
# ============================================================

class MedicationReminderResponse(BaseModel):
    id: int
    appointment_id: int
    medication_name: str
    frequency: str
    next_reminder_time: datetime
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# ============================================================
# SLOT HOLD
# ============================================================

class SlotHoldCreate(BaseModel):
    doctor_id: int
    slot_time: datetime


class SlotHoldResponse(BaseModel):
    id: int
    doctor_id: int
    patient_id: int
    slot_time: datetime
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)