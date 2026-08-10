"""Pydantic request/response models for the /ask endpoint."""
from __future__ import annotations

from pydantic import BaseModel


class AskRequest(BaseModel):
    repo_url: str
    question: str


class AskResponse(BaseModel):
    answer: str
