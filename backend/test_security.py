from auth.security import hash_password, verify_password


password = "MyPassword123"

hashed = hash_password(password)

print("Original password:", password)
print("Hashed password:", hashed)

print(
    "Correct password:",
    verify_password(password, hashed)
)

print(
    "Wrong password:",
    verify_password("WrongPassword", hashed)
)
