import React, { useEffect, useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8000";

function App() {
  const [user, setUser] = useState(null);
  const [doctors, setDoctors] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedDoctor, setSelectedDoctor] = useState(null);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("10:00");
  const [symptoms, setSymptoms] = useState("");
  const [message, setMessage] = useState("");

  const token = localStorage.getItem("token");

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    if (!token) {
      setLoading(false);
      return;
    }

    try {
      const headers = {
        Authorization: `Bearer ${token}`,
      };

      const [meRes, doctorsRes, appointmentsRes] = await Promise.all([
        fetch(`${API}/auth/me`, { headers }),
        fetch(`${API}/patient/doctors`, { headers }),
        fetch(`${API}/patient/appointments`, { headers }),
      ]);

      if (!meRes.ok) {
        localStorage.removeItem("token");
        setLoading(false);
        return;
      }

      setUser(await meRes.json());
      setDoctors(await doctorsRes.json());
      setAppointments(await appointmentsRes.json());
    } catch (error) {
      console.error(error);
      setMessage("Unable to connect to the backend.");
    }

    setLoading(false);
  }

  async function bookAppointment() {
    if (!selectedDoctor || !date || !time) {
      setMessage("Please select a doctor, date and time.");
      return;
    }

    try {
      const response = await fetch(`${API}/patient/appointments`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          doctor_id: selectedDoctor.id,
          start_time: `${date}T${time}:00`,
          symptoms: symptoms || null,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        setMessage(data.detail || "Unable to book appointment.");
        return;
      }

      setAppointments((prev) => [...prev, data]);
      setSelectedDoctor(null);
      setDate("");
      setTime("10:00");
      setSymptoms("");
      setMessage("Appointment booked successfully.");
    } catch {
      setMessage("Unable to connect to the backend.");
    }
  }

  async function cancelAppointment(id) {
    try {
      const response = await fetch(
        `${API}/patient/appointments/${id}`,
        {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      const data = await response.json();

      if (!response.ok) {
        setMessage(data.detail || "Unable to cancel appointment.");
        return;
      }

      setAppointments((prev) =>
        prev.map((a) =>
          a.id === id ? { ...a, status: "CANCELLED" } : a
        )
      );

      setMessage("Appointment cancelled successfully.");
    } catch {
      setMessage("Unable to connect to the backend.");
    }
  }

  function logout() {
    localStorage.removeItem("token");
    window.location.reload();
  }

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="spinner"></div>
        <p>Loading CareFlow...</p>
      </div>
    );
  }

  if (!token || !user) {
    return <Login />;
  }

  const upcoming = appointments.filter(
    (a) => a.status === "BOOKED" || a.status === "CONFIRMED"
  );

  const completed = appointments.filter(
    (a) => a.status === "COMPLETED"
  );

  return (
    <div className="app">

      {/* SIDEBAR */}
      <aside className="sidebar">

        <div className="brand">
          <div className="brand-icon">✚</div>
          <div>
            <h1>CareFlow</h1>
            <span>Healthcare Manager</span>
          </div>
        </div>

        <nav>
          <div className="nav-item active">
            <span>⌂</span>
            Dashboard
          </div>

          <div className="nav-item">
            <span>📅</span>
            Appointments
          </div>

          <div className="nav-item">
            <span>👨‍⚕️</span>
            Doctors
          </div>

          <div className="nav-item">
            <span>💊</span>
            Reminders
          </div>
        </nav>

        <div className="sidebar-bottom">
          <div className="user-mini">
            <div className="avatar">
              {user.name?.charAt(0)?.toUpperCase()}
            </div>

            <div>
              <strong>{user.name}</strong>
              <small>{user.role}</small>
            </div>
          </div>

          <button className="logout-btn" onClick={logout}>
            Logout
          </button>
        </div>

      </aside>

      {/* MAIN */}
      <main className="main">

        <header className="topbar">
          <div>
            <p className="eyebrow">PATIENT PORTAL</p>
            <h2>Good morning 👋</h2>
            <p className="welcome">
              Welcome back, <strong>{user.name}</strong>.
            </p>
          </div>

          <div className="profile">
            <div className="notification">🔔</div>
            <div className="profile-avatar">
              {user.name?.charAt(0)?.toUpperCase()}
            </div>
          </div>
        </header>

        <section className="hero">
          <div>
            <h3>Manage your healthcare in one place.</h3>
            <p>
              Book appointments, connect with doctors and keep
              track of your follow-ups.
            </p>
          </div>

          <div className="hero-icon">❤️‍🩹</div>
        </section>

        {/* STATS */}
        <section className="stats">

          <Stat
            icon="📅"
            title="Upcoming"
            value={upcoming.length}
          />

          <Stat
            icon="✓"
            title="Completed"
            value={completed.length}
          />

          <Stat
            icon="💊"
            title="Active reminders"
            value="0"
          />

          <Stat
            icon="👨‍⚕️"
            title="Doctors"
            value={doctors.length}
          />

        </section>

        {message && (
          <div className="message">
            {message}
            <button onClick={() => setMessage("")}>×</button>
          </div>
        )}

        {/* DOCTORS */}
        <section className="section">

          <div className="section-header">
            <div>
              <h3>Available doctors</h3>
              <p>Find the right specialist for your consultation.</p>
            </div>
          </div>

          <div className="doctor-grid">

            {doctors.map((doctor) => (

              <div className="doctor-card" key={doctor.id}>

                <div className="doctor-top">

                  <div className="doctor-avatar">
                    {doctor.name
                      ?.replace("Dr.", "")
                      .trim()
                      .charAt(0)}
                  </div>

                  <div>
                    <h4>{doctor.name}</h4>
                    <p>{doctor.specialisation}</p>
                  </div>

                </div>

                <div className="doctor-info">
                  <span>🕘</span>
                  {doctor.working_start_time} –{" "}
                  {doctor.working_end_time}
                </div>

                <button
                  className="primary-btn"
                  onClick={() => setSelectedDoctor(doctor)}
                >
                  Book appointment
                  <span>→</span>
                </button>

              </div>

            ))}

          </div>

        </section>

        {/* APPOINTMENTS */}
        <section className="section">

          <div className="section-header">
            <div>
              <h3>My appointments</h3>
              <p>Your scheduled consultations.</p>
            </div>
          </div>

          {appointments.length === 0 ? (

            <div className="empty">

              <div className="empty-icon">📅</div>

              <h4>No appointments yet</h4>

              <p>
                Book a consultation with one of our doctors
                to get started.
              </p>

            </div>

          ) : (

            <div className="appointments">

              {appointments.map((appointment) => (

                <div className="appointment-card" key={appointment.id}>

                  <div className="appointment-icon">
                    👨‍⚕️
                  </div>

                  <div className="appointment-details">

                    <h4>{appointment.doctor_name}</h4>

                    <p>
                      📅{" "}
                      {new Date(
                        appointment.start_time
                      ).toLocaleString()}
                    </p>

                    {appointment.symptoms && (
                      <small>
                        {appointment.symptoms}
                      </small>
                    )}

                  </div>

                  <div className="appointment-actions">

                    <span
                      className={`status ${appointment.status.toLowerCase()}`}
                    >
                      {appointment.status}
                    </span>

                    {(appointment.status === "BOOKED" ||
                      appointment.status === "CONFIRMED") && (

                      <button
                        className="cancel-btn"
                        onClick={() =>
                          cancelAppointment(appointment.id)
                        }
                      >
                        Cancel
                      </button>

                    )}

                  </div>

                </div>

              ))}

            </div>

          )}

        </section>

      </main>

      {/* BOOKING MODAL */}
      {selectedDoctor && (

        <div className="modal-overlay">

          <div className="modal">

            <button
              className="close"
              onClick={() => setSelectedDoctor(null)}
            >
              ×
            </button>

            <div className="modal-doctor">

              <div className="doctor-avatar large">
                {selectedDoctor.name
                  ?.replace("Dr.", "")
                  .trim()
                  .charAt(0)}
              </div>

              <div>
                <h3>{selectedDoctor.name}</h3>
                <p>{selectedDoctor.specialisation}</p>
              </div>

            </div>

            <h2>Book an appointment</h2>
            <p className="modal-subtitle">
              Choose a convenient date and time.
            </p>

            <label>Date</label>

            <input
              type="date"
              value={date}
              min={new Date().toISOString().split("T")[0]}
              onChange={(e) => setDate(e.target.value)}
            />

            <label>Time</label>

            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
            />

            <label>Reason for visit</label>

            <textarea
              rows="4"
              placeholder="Tell us briefly about your symptoms..."
              value={symptoms}
              onChange={(e) => setSymptoms(e.target.value)}
            />

            <button
              className="primary-btn modal-btn"
              onClick={bookAppointment}
            >
              Confirm appointment
              <span>→</span>
            </button>

          </div>

        </div>

      )}

    </div>
  );
}


function Stat({ icon, title, value }) {
  return (
    <div className="stat-card">

      <div className="stat-icon">
        {icon}
      </div>

      <div>
        <p>{title}</p>
        <strong>{value}</strong>
      </div>

    </div>
  );
}


function Login() {

  const [email, setEmail] = useState("demo@careflow.com");
  const [password, setPassword] = useState("Demo12345!");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function login(e) {

    e.preventDefault();

    setLoading(true);
    setError("");

    try {

      const response = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email,
          password,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.detail || "Login failed");
        setLoading(false);
        return;
      }

      localStorage.setItem("token", data.access_token);
      window.location.reload();

    } catch {

      setError(
        "Failed to connect to the backend."
      );

    }

    setLoading(false);
  }

  return (

    <div className="login-page">

      <div className="login-card">

        <div className="login-brand">
          <div className="brand-icon">✚</div>
          <div>
            <h1>CareFlow</h1>
            <span>Healthcare Manager</span>
          </div>
        </div>

        <div className="login-heading">
          <h2>Welcome back</h2>
          <p>
            Sign in to manage your healthcare appointments.
          </p>
        </div>

        {error && (
          <div className="error">
            {error}
          </div>
        )}

        <form onSubmit={login}>

          <label>Email</label>

          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />

          <label>Password</label>

          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          <button
            className="login-btn"
            disabled={loading}
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>

        </form>

        <div className="demo">
          <strong>Demo account</strong>
          <span>demo@careflow.com</span>
          <span>Demo12345!</span>
        </div>

      </div>

    </div>

  );
}

export default App;