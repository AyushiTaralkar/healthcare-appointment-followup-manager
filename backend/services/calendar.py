import os
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import googleapiclient.discovery

from models import GoogleCredentials, Appointment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/google/callback")


def get_stored_credentials(db: Session) -> GoogleCredentials | None:
    """Fetch the latest global Google credentials (user_id is Null or admin's)."""
    return db.query(GoogleCredentials).order_by(GoogleCredentials.id.desc()).first()


def build_credentials_object(cred_model: GoogleCredentials) -> Credentials:
    """Construct a google-auth Credentials object from the DB record."""
    return Credentials(
        token=cred_model.access_token,
        refresh_token=cred_model.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        expiry=cred_model.token_expiry.replace(tzinfo=timezone.utc) if cred_model.token_expiry else None
    )


def save_credentials(db: Session, creds: Credentials, original_id: int | None = None) -> GoogleCredentials:
    """Save or update Google OAuth credentials in the database."""
    expiry = creds.expiry.replace(tzinfo=timezone.utc) if creds.expiry else datetime.now(timezone.utc) + timedelta(hours=1)
    
    if original_id:
        db_creds = db.query(GoogleCredentials).filter(GoogleCredentials.id == original_id).first()
        if db_creds:
            db_creds.access_token = creds.token
            if creds.refresh_token:
                db_creds.refresh_token = creds.refresh_token
            db_creds.token_expiry = expiry
            db.commit()
            db.refresh(db_creds)
            return db_creds
            
    # Create new record
    db_creds = GoogleCredentials(
        access_token=creds.token,
        refresh_token=creds.refresh_token,
        token_expiry=expiry
    )
    db.add(db_creds)
    db.commit()
    db.refresh(db_creds)
    return db_creds


def get_calendar_service(db: Session):
    """
    Get the authenticated Google Calendar API client service.
    Handles token refreshing automatically and updates the DB if refreshed.
    Returns the service object, or None if credentials are not configured.
    """
    if not CLIENT_ID or not CLIENT_SECRET:
        logger.warning("Google Calendar OAuth credentials not fully set in environment variables.")
        return None

    db_creds = get_stored_credentials(db)
    if not db_creds:
        logger.warning("Google Calendar OAuth has not been authorized yet by the Admin.")
        return None

    try:
        creds = build_credentials_object(db_creds)
        
        # Check if expired and refresh
        if creds.expired or (creds.expiry and creds.expiry <= datetime.now(timezone.utc)):
            logger.info("Google Calendar access token expired. Refreshing...")
            request = Request()
            creds.refresh(request)
            # Save updated tokens
            save_credentials(db, creds, db_creds.id)
            logger.info("Google Calendar token refreshed and updated in DB.")

        service = googleapiclient.discovery.build("calendar", "v3", credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Failed to build Google Calendar service: {str(e)}")
        return None


def create_calendar_event(db: Session, appointment: Appointment) -> str | None:
    """
    Create a calendar event for the appointment.
    Invites patient and doctor as attendees.
    Returns the created Google Calendar Event ID, or None on failure.
    """
    service = get_calendar_service(db)
    if not service:
        return None

    try:
        # Load patient and doctor info
        patient = appointment.patient
        doctor = appointment.doctor
        
        description = (
            f"Pre-visit Symptoms: {appointment.symptoms or 'None'}\n"
            f"Urgency Level: {appointment.urgency_level or 'Low'}\n"
            f"Chief Complaint: {appointment.chief_complaint or 'None'}\n"
            f"Appointment status: {appointment.status}"
        )

        event_body = {
            'summary': f"Medical Appointment: Patient {patient.name} & Dr. {doctor.name}",
            'location': 'Clinic Office / Telehealth',
            'description': description,
            'start': {
                'dateTime': appointment.start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': appointment.end_time.isoformat(),
                'timeZone': 'UTC',
            },
            'attendees': [
                {'email': patient.email, 'displayName': patient.name},
                {'email': doctor.email, 'displayName': f"Dr. {doctor.name}"},
            ],
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 30},
                ],
            },
        }

        # Call Calendar API
        # We use 'primary' calendar.
        event = service.events().insert(calendarId='primary', body=event_body, sendUpdates='all').execute()
        event_id = event.get('id')
        logger.info(f"Google Calendar event created successfully: {event_id}")
        return event_id
        
    except Exception as e:
        logger.error(f"Error creating Google Calendar event: {str(e)}")
        return None


def update_calendar_event(db: Session, appointment: Appointment) -> bool:
    """
    Update an existing Google Calendar event.
    """
    if not appointment.google_calendar_event_id:
        return False
        
    service = get_calendar_service(db)
    if not service:
        return False

    try:
        patient = appointment.patient
        doctor = appointment.doctor
        
        description = (
            f"Pre-visit Symptoms: {appointment.symptoms or 'None'}\n"
            f"Urgency Level: {appointment.urgency_level or 'Low'}\n"
            f"Chief Complaint: {appointment.chief_complaint or 'None'}\n"
            f"Appointment status: {appointment.status}"
        )
        if appointment.doctor_notes:
            description += f"\n\nDoctor Notes: {appointment.doctor_notes}\nPrescription: {appointment.prescription}"

        # Fetch existing event
        event = service.events().get(calendarId='primary', eventId=appointment.google_calendar_event_id).execute()
        
        # Update details
        event['summary'] = f"Medical Appointment: Patient {patient.name} & Dr. {doctor.name} ({appointment.status})"
        event['description'] = description
        event['start'] = {
            'dateTime': appointment.start_time.isoformat(),
            'timeZone': 'UTC',
        }
        event['end'] = {
            'dateTime': appointment.end_time.isoformat(),
            'timeZone': 'UTC',
        }
        
        service.events().update(
            calendarId='primary',
            eventId=appointment.google_calendar_event_id,
            body=event,
            sendUpdates='all'
        ).execute()
        
        logger.info(f"Google Calendar event updated successfully: {appointment.google_calendar_event_id}")
        return True
    except Exception as e:
        logger.error(f"Error updating Google Calendar event {appointment.google_calendar_event_id}: {str(e)}")
        return False


def delete_calendar_event(db: Session, event_id: str) -> bool:
    """
    Delete an event from Google Calendar.
    """
    if not event_id:
        return False
        
    service = get_calendar_service(db)
    if not service:
        return False

    try:
        service.events().delete(calendarId='primary', eventId=event_id, sendUpdates='all').execute()
        logger.info(f"Google Calendar event deleted successfully: {event_id}")
        return True
    except Exception as e:
        logger.error(f"Error deleting Google Calendar event {event_id}: {str(e)}")
        return False
