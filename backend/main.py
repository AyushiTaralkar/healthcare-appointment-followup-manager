from fastapi import FastAPI
from sqlalchemy import text

from database import engine

app = FastAPI(
    title="Healthcare Appointment & Follow-up Manager"
)


@app.get("/")
def root():
    return {
        "message": "Healthcare Appointment API is running"
    }


@app.get("/test-db")
def test_database():
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))

    return {
        "database": "connected",
        "result": result.scalar()
    }