import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from models import EmailQueue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SMTP configurations
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = os.getenv("SMTP_PORT")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "noreply@healthcare-clinic.com")


def queue_and_send_email(db: Session, recipient: str, subject: str, body: str) -> EmailQueue:
    """
    Save the email to EmailQueue and attempt to send it immediately.
    """
    # Create email queue entry
    email_entry = EmailQueue(
        recipient=recipient,
        subject=subject,
        body=body,
        status="PENDING",
        attempts=0
    )
    db.add(email_entry)
    db.commit()
    db.refresh(email_entry)

    # Attempt to send immediately
    success, error_msg = send_email_direct(recipient, subject, body)
    
    if success:
        email_entry.status = "SENT"
        email_entry.attempts += 1
    else:
        email_entry.status = "FAILED"
        email_entry.attempts += 1
        email_entry.last_error = error_msg
        
    db.commit()
    db.refresh(email_entry)
    return email_entry


def send_email_direct(recipient: str, subject: str, body: str) -> tuple[bool, str]:
    """
    Send SMTP email directly.
    Returns (success: bool, error_message: str).
    If SMTP credentials are not configured, prints email details to log and returns True.
    """
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD]):
        # Fallback to local logs
        logger.info("\n" + "="*50 + "\n"
                    f"EMAIL LOG (SMTP Not Configured)\n"
                    f"To: {recipient}\n"
                    f"From: {SMTP_FROM_EMAIL}\n"
                    f"Subject: {subject}\n"
                    f"Body:\n{body}\n" + "="*50)
        return True, ""

    try:
        # Create email message
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM_EMAIL
        msg['To'] = recipient
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Connect and send
        port = int(SMTP_PORT)
        # Choose connection type based on port
        if port == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, port, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_HOST, port, timeout=10)
            server.starttls()
            
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, recipient, msg.as_string())
        server.quit()
        
        logger.info(f"Email successfully sent to {recipient} with subject '{subject}'.")
        return True, ""
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to send email to {recipient} via SMTP: {error_msg}")
        return False, error_msg
