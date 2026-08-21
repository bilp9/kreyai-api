from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.services.email_service import send_linguist_partner_application_email
from app.services.linguist_partner_applications import save_linguist_partner_application


router = APIRouter(prefix="/api/linguist-partner", tags=["linguist-partner"])


class LinguistPartnerApplicationRequest(BaseModel):
    name: str = Field(max_length=120)
    email: str = Field(max_length=254)
    languages: str = Field(max_length=300)
    products: list[str] = Field(default_factory=list, max_length=2)
    platform: str = Field(max_length=20)
    experience: str = Field(max_length=20)
    current_tools: str | None = Field(default=None, max_length=500)
    testing_interests: str = Field(max_length=1500)
    feedback_commitment: bool = False
    privacy_consent: bool = False
    website: str | None = Field(default=None, max_length=200)


@router.post("/apply", status_code=202)
async def apply_for_linguist_partner_program(
    payload: LinguistPartnerApplicationRequest,
    background_tasks: BackgroundTasks,
):
    # A filled hidden field indicates automated submission. Return the normal
    # response shape without retaining or emailing the payload.
    if str(payload.website or "").strip():
        return {"status": "pending"}

    try:
        application = save_linguist_partner_application(
            name=payload.name,
            email=payload.email,
            languages=payload.languages,
            products=payload.products,
            platform=payload.platform,
            experience=payload.experience,
            current_tools=payload.current_tools,
            testing_interests=payload.testing_interests,
            feedback_commitment=payload.feedback_commitment,
            privacy_consent=payload.privacy_consent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(send_linguist_partner_application_email, application)
    return {
        "status": "pending",
        "message": "Application received.",
    }
