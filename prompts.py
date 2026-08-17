from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from DataDictionaryAdminApp.api.schemas_api import PromptUpsert
from DataDictionaryAdminApp.core.database import get_db
from DataDictionaryAdminApp.service.data_dictionary_service import DataDictionaryService
from DataDictionaryAdminApp.utils.security import current_user

router = APIRouter(prefix="/prompts", tags=["Prompt Management"])

@router.get("")
def prompts(include_deleted: bool = True, db: Session = Depends(get_db)):
    return DataDictionaryService(db).prompt_rows(include_deleted=include_deleted)

@router.put("/{scope_id}")
def update_prompt(scope_id: int, payload: PromptUpsert, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if payload.scope_id != scope_id:
        payload.scope_id = scope_id
    return DataDictionaryService(db).stage_prompt(scope_id, payload.prompt_description, payload.examples, user)
