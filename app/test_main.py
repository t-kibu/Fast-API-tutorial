from fastapi.testclient import TestClient

from .main import app


client = TestClient


def test_read_main():
  response =  client("/test/")
  assert response.status_code == 200
  assert response.json() == {"msg": "Hello World"}
