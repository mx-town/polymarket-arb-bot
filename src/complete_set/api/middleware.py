"""CORS and middleware setup for the dashboard API."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def setup_middleware(app: FastAPI) -> None:
    """Configure CORS for Next.js dev server and production dashboard."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:4200",   # Next.js dev
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
