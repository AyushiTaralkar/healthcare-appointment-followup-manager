import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from database import SessionLocal
from models import EmailQueue, MedicationReminder, User, Appointment
from services.email import send_email_direct

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Control flag for the scheduler thread
_scheduler_running = False
_scheduler_thread = None


def calculate_next_reminder(current_time: datetime, frequency: str) -> datetime:
    """
    Calculate the next occurrence time based on frequency.
    Supported frequencies:
    - 'Daily' or 'Once daily' -> +24 hours
    - 'Twice daily' -> +12 hours
    - 'Three times daily' -> +8 hours
    - 'Weekly' -> +7 days
    """
    freq = frequency.lower().strip()
    if "twice daily" in freq:
        return current_time + timedelta(hours=12)
    elif "three times daily" in freq:
        return current_time + timedelta(hours=8)
    elif "weekly" in freq:
        return current_time + timedelta(days=7)
    else:
        # Default to daily
        return current_time + timedelta(days=1)


def run_scheduler_jobs():
    """Execute background job checks in a loop."""
    global _scheduler_running
    logger.info("Background scheduler thread started.")
    
    while _scheduler_running:
        db: Session = SessionLocal()
        try:
            now_utc = datetime.now(timezone.utc)
            
            # --- JOB 1: Process and retry emails ---
            pending_emails = (
                db.query(EmailQueue)
                .filter(
                    EmailQueue.status.in_(["PENDING", "FAILED"]),
                    EmailQueue.attempts < 3
                )
                .all()
            )
            
            for email in pending_emails:
                logger.info(f"Retrying email {email.id} to {email.recipient} (Attempt {email.attempts + 1})...")
                success, error_msg = send_email_direct(email.recipient, email.subject, email.body)
                email.attempts += 1
                email.updated_at = now_utc
                
                if success:
                    email.status = "SENT"
                else:
                    email.status = "FAILED"
                    email.last_error = error_msg
                db.commit()
                
            # --- JOB 2: Send medication reminders ---
            due_reminders = (
                db.query(MedicationReminder)
                .filter(
                    MedicationReminder.is_active == True,
                    MedicationReminder.next_reminder_time <= now_utc
                )
                .all()
            )
            
            for reminder in due_reminders:
                patient = db.query(User).filter(User.id == reminder.patient_id).first()
                appointment = db.query(Appointment).filter(Appointment.id == reminder.appointment_id).first()
                doctor_name = appointment.doctor.name if appointment else "your doctor"
                
                if patient:
                    subject = f"Medication Reminder: {reminder.medication_name}"
                    body = (
                        f"Hello {patient.name},\n\n"
                        f"This is a reminder to take your medication: {reminder.medication_name}.\n"
                        f"Prescribed Frequency: {reminder.frequency}\n"
                        f"Prescribing Doctor: Dr. {doctor_name}\n\n"
                        "Please follow the dosing schedule provided during your appointment.\n\n"
                        "Best regards,\nHealthcare Appointment Clinic"
                    )
                    
                    # Queue and send the reminder email
                    email_entry = EmailQueue(
                        recipient=patient.email,
                        subject=subject,
                        body=body,
                        status="PENDING",
                        attempts=0
                    )
                    db.add(email_entry)
                    db.commit()
                    
                    # Direct attempt
                    success, error_msg = send_email_direct(patient.email, subject, body)
                    email_entry.attempts += 1
                    email_entry.updated_at = now_utc
                    if success:
                        email_entry.status = "SENT"
                    else:
                        email_entry.status = "FAILED"
                        email_entry.last_error = error_msg
                    db.commit()
                
                # Update next reminder occurrence
                next_time = calculate_next_reminder(reminder.next_reminder_time, reminder.frequency)
                reminder.next_reminder_time = next_time
                db.commit()
                logger.info(f"Medication reminder {reminder.id} processed. Next reminder set to {next_time.isoformat()}")

        except Exception as e:
            logger.error(f"Error in scheduler job loop: {str(e)}")
        finally:
            db.close()
            
        # Sleep for 60 seconds
        time.sleep(60)


def start_scheduler():
    """Start the background scheduler thread."""
    global _scheduler_running, _scheduler_thread
    if _scheduler_running:
        return
        
    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=run_scheduler_jobs, daemon=True)
    _scheduler_thread.start()


def stop_scheduler():
    """Stop the background scheduler thread."""
    global _scheduler_running, _scheduler_thread
    if not _scheduler_running:
        return
        
    _scheduler_running = False
    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)
    logger.info("Background scheduler thread stopped.")
