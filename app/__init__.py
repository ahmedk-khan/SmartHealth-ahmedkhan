from fastapi import FastAPI

app = FastAPI(title="app")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "app api is running"}