from fastapi import FastAPI
import models
from database import engine
from routers import tickets, users

models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Helpdesk AI Agent — Backend Dev",
    description="Backend SQLite local para testeo del Agente IA de tickets",
    version="2.0.0",
    redirect_slashes=False,
)

app.include_router(tickets.router)
app.include_router(users.router)


@app.get("/")
def read_root():
    return {"message": "Helpdesk Backend v2 corriendo. Visita /docs para explorar la API."}


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}
