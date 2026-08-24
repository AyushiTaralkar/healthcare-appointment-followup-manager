from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from database import engine, Base

from auth.router import router as auth_router
from routers import patient
from routers import admin
from routers import doctor
app = FastAPI(
    title="Healthcare Appointment & Follow-up Manager",
    description=(
        "AI-powered healthcare appointment, "
        "consultation and follow-up management platform."
    ),
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROUTERS
# ============================================================

app.include_router(auth_router)
app.include_router(patient.router)
app.include_router(admin.router)
app.include_router(doctor.router)


# ============================================================
# DATABASE
# ============================================================

Base.metadata.create_all(bind=engine)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "message": "Healthcare Appointment API is running",
        "version": "1.0.0",
        "docs": "/docs"
    }


# ============================================================
# DATABASE HEALTH CHECK
# ============================================================

@app.get("/test-db")
def test_database():

    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT 1")
        )

    return {
        "database": "connected",
        "result": result.scalar()
    }