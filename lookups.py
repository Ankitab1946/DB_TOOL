from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from DataDictionaryAdminApp.core.database import get_db
from DataDictionaryAdminApp.repositories.data_dictionary_repository import DataDictionaryRepository
from DataDictionaryAdminApp.service.data_dictionary_service import DataDictionaryService

router = APIRouter(prefix="/lookups", tags=["Lookups"])

@router.get("")
def lookups(db: Session = Depends(get_db)):
    return DataDictionaryRepository(db).lookup_values()

@router.get("/sources")
def sources(db: Session = Depends(get_db)):
    return DataDictionaryRepository(db).list_sources()

@router.get("/portfolios")
def portfolios(db: Session = Depends(get_db)):
    return DataDictionaryRepository(db).list_portfolios()

@router.get("/next-prj-id")
def next_prj_id(db: Session = Depends(get_db)):
    try:
        return {"prj_id": DataDictionaryService(db).next_prj_id()}
    except RuntimeError as exc:
        # A connected PostgreSQL server is not necessarily an initialized Data
        # Dictionary database. Surface an actionable schema message instead of
        # FastAPI's generic 500 response.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/physical-name-suggestions")
def physical_name_suggestions(attribute_name: str = Query(...), prj_id: str | None = None, db: Session = Depends(get_db)):
    return DataDictionaryService(db).physical_name_suggestions(attribute_name, prj_id)
