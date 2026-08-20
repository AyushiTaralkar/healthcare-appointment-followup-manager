from fastapi import FastAPI
from sqlalchemy import text
from auth.router import router as auth_router

from database import engine, Base
from models import User

app = FastAPI(
    title="Healthcare Appointment & Follow-up Manager"
)
app.include_router(auth_router)

Base.metadata.create_all(bind=engine)


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