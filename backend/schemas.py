from pydantic import BaseModel, EmailStr
from datetime import date, datetime
from typing import List, Optional, Any


class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Optional[str] = "PATIENT"  # PATIENT, DOCTOR, ADMIN


class DoctorCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    specialisation: str
    working_start_time: Optional[str] = "09:00"
    working_end_time: Optional[str] = "17:00"
    slot_duration: Optional[int] = 30


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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


class DoctorLeaveCreate(BaseModel):
    leave_date: date


class DoctorLeaveResponse(BaseModel):
    id: int
    doctor_id: int
    leave_date: date

    class Config:
        from_attributes = True


class SlotHoldCreate(BaseModel):
    doctor_id: int
    slot_time: datetime


class SlotHoldResponse(BaseModel):
    id: int
    doctor_id: int
    patient_id: int
    slot_time: datetime
    expires_at: datetime

    class Config:
        from_attributes = True


class AppointmentBook(BaseModel):
    slot_hold_id: int
    symptoms: str


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

    class Config:
        from_attributes = True


class DoctorNotesSubmit(BaseModel):
    notes: str
    prescription: str


class MedicationReminderResponse(BaseModel):
    id: int
    appointment_id: int
    medication_name: str
    frequency: str
    next_reminder_time: datetime
    is_active: bool

    class Config:
        from_attributes = True