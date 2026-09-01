from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from DataDictionaryAdminApp.api.schemas_api import PortfolioUpsert
from DataDictionaryAdminApp.core.database import get_db
from DataDictionaryAdminApp.repositories.data_dictionary_repository import DataDictionaryRepository, model_dict
from DataDictionaryAdminApp.utils.security import require_admin

router = APIRouter(prefix="/portfolio-reference", tags=["Portfolio Reference"])


@router.get("")
def list_portfolios(db: Session = Depends(get_db)):
    return DataDictionaryRepository(db).list_portfolios(include_inactive=True)


@router.post("")
def add_portfolio(payload: PortfolioUpsert, request: Request, db: Session = Depends(get_db)):
    user = require_admin(request)
    repo = DataDictionaryRepository(db)
    portfolio_model = repo.portfolio_model()
    row = portfolio_model(
        **payload.model_dump(),
        is_active=True,
        created_by=user,
        updated_by=user,
    )
    try:
        db.add(row)
        db.flush()
        repo.audit(
            "dbo",
            "prj_portfolio_reference" if db.get_bind().dialect.name == "postgresql" else "prj_portfolio_reference_new_test",
            str(row.port_ref_id),
            "INSERT",
            None,
            model_dict(row),
            user,
            "UI",
        )
        db.commit()
        return {"port_ref_id": row.port_ref_id}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Portfolio reference must be unique.") from exc
