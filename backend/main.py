from fastapi import FastAPI

app = FastAPI(
    title="Healthcare Appointment & Follow-up Manager"
)


@app.get("/")
def root():
    return {
        "message": "Healthcare Appointment yAPI is running"
    }