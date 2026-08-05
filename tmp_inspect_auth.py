from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
response = client.post(
    "/auth/register",
    json={"email": "alice@example.com", "password": "secret123", "role": "patient"},
)
print(response.status_code)
print(response.headers)
print(response.text)
