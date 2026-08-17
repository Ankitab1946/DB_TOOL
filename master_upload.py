from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from DataDictionaryAdminApp.config import get_settings
from DataDictionaryAdminApp.core.database import get_db
from DataDictionaryAdminApp.repositories.data_dictionary_repository import DataDictionaryRepository
from DataDictionaryAdminApp.service.data_dictionary_service import DataDictionaryService
from DataDictionaryAdminApp.service.excel_service import ExcelService
from DataDictionaryAdminApp.utils.security import require_admin

router = APIRouter(prefix="/master-upload", tags=["Master Dictionary Upload"])


async def _content(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > get_settings().max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds MAX_UPLOAD_SIZE_MB.")
    return content


def _mode(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in {"MERGE", "INSERT_ONLY", "REPLACE"}:
        raise HTTPException(status_code=422, detail="mode must be MERGE, INSERT_ONLY or REPLACE")
    return normalized


@router.post("/sheets")
async def sheets(request: Request, file: UploadFile = File(...)):
    require_admin(request)
    content = await _content(file)
    return {"sheets": ExcelService.sheet_names(content)}


@router.post("/preview-sheet")
async def preview_sheet(
    request: Request,
    file: UploadFile = File(...),
    sheet_name: str = Form(...),
    header_row: int = Form(2),
    data_start_row: int | None = Form(None),
):
    require_admin(request)
    content = await _content(file)
    try:
        return ExcelService().preview_sheet(content, sheet_name, header_row, data_start_row)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/preview")
async def preview(
    request: Request,
    file: UploadFile = File(...),
    configurations_json: str = Form(...),
    mode: str = Form("MERGE"),
    db: Session = Depends(get_db),
):
    require_admin(request)
    content = await _content(file)
    normalized_mode = _mode(mode)
    try:
        configurations = json.loads(configurations_json)
        parsed = ExcelService().parse_workbook(content, configurations)
        repo = DataDictionaryRepository(db)
        rows_for_compare = parsed["rows"]
        skipped_existing_ids: list[str] = []
        if normalized_mode == "INSERT_ONLY":
            existing_ids = repo.existing_prj_ids()
            skipped_existing_ids = sorted({
                str(row.prj_id) for row in parsed["rows"] if row.prj_id and str(row.prj_id) in existing_ids
            })
            rows_for_compare = [
                row for row in parsed["rows"] if row.prj_id and str(row.prj_id) not in existing_ids
            ]
        delta = DataDictionaryService(db).compare_upload(
            rows_for_compare, include_missing_deleted=normalized_mode == "REPLACE"
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "mode": normalized_mode,
        "valid_count": len(parsed["rows"]),
        "eligible_count": len(rows_for_compare),
        "skipped_existing_count": len(skipped_existing_ids),
        "skipped_existing_prj_ids": skipped_existing_ids,
        "rejected": parsed["rejected"],
        "preview": [row.model_dump() for row in rows_for_compare[:50]],
        "delta": delta,
    }


@router.post("/finalize")
async def upload_and_stage(
    request: Request,
    file: UploadFile = File(...),
    configurations_json: str = Form(...),
    mode: str = Form("MERGE"),
    db: Session = Depends(get_db),
):
    user = require_admin(request)
    content = await _content(file)
    normalized_mode = _mode(mode)
    try:
        configurations = json.loads(configurations_json)
        parsed = ExcelService().parse_workbook(content, configurations)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # REPLACE treats the workbook as authoritative. Never clear current pending/raw
    # data when the workbook itself has parsing/mapping errors.
    if normalized_mode == "REPLACE" and parsed["rejected"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "REPLACE was not staged because the workbook contains rejected rows.",
                "rejected": parsed["rejected"],
            },
        )

    repo = DataDictionaryRepository(db)
    service = DataDictionaryService(db)
    staged: list[dict] = []
    runtime_rejected = list(parsed["rejected"])
    rows_to_stage = parsed["rows"]
    skipped_existing_ids: list[str] = []
    if normalized_mode == "INSERT_ONLY":
        # Capture the baseline before staging so multiple scope rows for the same
        # genuinely new PRJ ID can all be loaded in one workbook.
        existing_ids = repo.existing_prj_ids()
        skipped_existing_ids = sorted({
            str(row.prj_id) for row in parsed["rows"] if row.prj_id and str(row.prj_id) in existing_ids
        })
        rows_to_stage = [
            row for row in parsed["rows"] if row.prj_id and str(row.prj_id) not in existing_ids
        ]

    try:
        if normalized_mode == "REPLACE":
            repo.clear_raw_and_staging_for_replace(user)

        for row in rows_to_stage:
            try:
                with db.begin_nested():
                    staged.append(service.stage_attribute_pending(row, user, f"BULK_{normalized_mode}"))
            except HTTPException as exc:
                runtime_rejected.append({"prj_id": row.prj_id, "reason": exc.detail})
            except IntegrityError as exc:
                runtime_rejected.append({"prj_id": row.prj_id, "reason": str(exc.orig)})

        if normalized_mode == "REPLACE" and runtime_rejected:
            db.rollback()
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "REPLACE was rolled back because one or more rows could not be staged.",
                    "rejected": runtime_rejected,
                },
            )

        if normalized_mode == "REPLACE":
            uploaded_ids = {str(row.prj_id) for row in parsed["rows"] if row.prj_id}
            final_active_ids = {row["prj_id"] for row in repo.editable_rows(include_deleted=False)}
            for prj_id in sorted(final_active_ids - uploaded_ids):
                repo.stage_delete_attribute(prj_id, False, user, "BULK_REPLACE_MISSING")

        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

    return {
        "mode": normalized_mode,
        "staged_count": len(staged),
        "skipped_existing_count": len(skipped_existing_ids),
        "skipped_existing_prj_ids": skipped_existing_ids,
        "rejected_count": len(runtime_rejected),
        "rejected": runtime_rejected,
        "delta": service.delta(),
    }
