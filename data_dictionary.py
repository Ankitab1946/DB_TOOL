from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from DataDictionaryAdminApp.api.schemas_api import AttributeBatchRequest, AttributeUpsert, FilterRequest, FinalizeRequest
from DataDictionaryAdminApp.core.database import get_db
from DataDictionaryAdminApp.service.data_dictionary_service import DataDictionaryService
from DataDictionaryAdminApp.service.excel_service import ExcelService
from DataDictionaryAdminApp.utils.security import current_user

router = APIRouter(prefix="/data-dictionary", tags=["Data Dictionary"])

@router.post("/filter-page")
def filter_page(payload: FilterRequest, db: Session = Depends(get_db)):
    return DataDictionaryService(db).filter(payload)

@router.get("/edit-latest")
def edit_latest(include_deleted: bool = True, db: Session = Depends(get_db)):
    return DataDictionaryService(db).editable_rows(include_deleted=include_deleted)

@router.get("/attributes/{prj_id}")
def detail(prj_id: str, db: Session = Depends(get_db)):
    return DataDictionaryService(db).detail(prj_id)

@router.post("/attributes")
def create_attribute(payload: AttributeUpsert, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    payload.prj_id = None
    return DataDictionaryService(db).stage_attribute(payload, user, "UI_CREATE")

@router.put("/attributes/{prj_id}")
def edit_attribute(prj_id: str, payload: AttributeUpsert, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    payload.prj_id = prj_id
    return DataDictionaryService(db).stage_attribute(payload, user, "UI_EDIT")

@router.post("/batch-stage")
def batch_stage(payload: AttributeBatchRequest, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return DataDictionaryService(db).stage_batch(payload.rows, user)

@router.delete("/attributes/{prj_id}")
def soft_delete(prj_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return DataDictionaryService(db).stage_delete(prj_id, user)

@router.post("/attributes/{prj_id}/reactivate")
def reactivate(prj_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return DataDictionaryService(db).stage_reactivate(prj_id, user)

@router.get("/delta")
def delta(db: Session = Depends(get_db)):
    return DataDictionaryService(db).delta()

@router.post("/finalize")
def finalize(payload: FinalizeRequest, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return DataDictionaryService(db).finalize(user, payload.confirm)

@router.get("/download-latest")
def download_latest(db: Session = Depends(get_db)):
    service = DataDictionaryService(db)
    all_rows = []
    page = 1
    while True:
        result = service.filter(FilterRequest(page=page, page_size=1000, include_deleted=False))
        all_rows.extend(result["rows"])
        if len(all_rows) >= result["total"] or not result["rows"]:
            break
        page += 1
    content = ExcelService.latest_workbook(all_rows)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="prj_master_dictionary_latest.xlsx"'},
    )
