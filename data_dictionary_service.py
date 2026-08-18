"""Business logic for raw -> staging -> final data dictionary operations."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, true
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from DataDictionaryAdminApp.api.schemas_api import AttributeUpsert, FilterRequest
from DataDictionaryAdminApp.config import get_settings
from DataDictionaryAdminApp.model.entities import (
    AttributeBusinessRule,
    AttributeMaster,
    PortfolioReference,
)
from DataDictionaryAdminApp.repositories.data_dictionary_repository import DataDictionaryRepository, model_dict, portfolio_label
from DataDictionaryAdminApp.utils.normalizers import (
    canonical_portfolio_label,
    editable_from_mapping_type,
    generate_physical_name,
    generate_tech_logic,
    mapping_type_from_value,
    normalize_text,
)


MASTER_COMPARE_FIELDS = (
    "prj_attribute_name",
    "prj_attribute_definition",
    "prj_physical_attribute_name",
    "where_in_financial_statement",
    "is_active",
)
RULE_COMPARE_FIELDS = (
    "port_ref_id",
    "source_abbr_name",
    "editable",
    "symbol",
    "mapping_type",
    "calculation_logic",
    "prj_attribute_description",
    "tech_logic",
    "display_order",
    "display_name",
    "section",
    "subsection",
    "prompt_description",
    "examples",
    "is_active",
)


class DataDictionaryService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DataDictionaryRepository(db)

    def next_prj_id(self) -> str:
        return self.repo.next_prj_id()

    def physical_name_suggestions(self, attribute_name: str, prj_id: str | None = None) -> dict[str, Any]:
        base = generate_physical_name(attribute_name) or "attribute"
        candidates = [base]
        if prj_id:
            candidates.append(f"{base} {prj_id.lower()}"[:500])
        for index in range(2, 8):
            candidates.append(f"{base} {index}"[:500])
        suggestions = []
        for candidate in dict.fromkeys(candidates):
            suggestions.append(
                {"name": candidate, "available": not self.repo.physical_name_exists(candidate, exclude_prj_id=prj_id)}
            )
        selected = next((item["name"] for item in suggestions if item["available"]), None)
        return {"generated": base, "selected": selected, "suggestions": suggestions}

    def filter(self, request: FilterRequest) -> dict[str, Any]:
        settings = get_settings()
        page_size = request.page_size or settings.data_dictionary_default_page_size
        page_size = max(1, min(page_size, settings.data_dictionary_max_page_size))
        return self.repo.filter_final(request, page_size)

    def editable_rows(self, include_deleted: bool = True) -> list[dict[str, Any]]:
        return self.repo.editable_rows(include_deleted=include_deleted)

    def soft_deleted_rows(self) -> list[dict[str, Any]]:
        return self.repo.soft_deleted_rows()

    def detail(self, prj_id: str) -> dict[str, Any]:
        detail = self.repo.final_detail(prj_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"PRJ ID {prj_id} was not found in the final dictionary.")
        return detail

    def _make_rows(self, payload: AttributeUpsert) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        prj_id = normalize_text(payload.prj_id) or self.repo.next_prj_id()
        portfolio_label = canonical_portfolio_label(payload.portfolio)
        portfolio = self.repo.portfolio_ref(portfolio_label)
        if not portfolio:
            raise HTTPException(status_code=422, detail=f"Unknown or inactive portfolio/scope: {payload.portfolio}")

        physical_name = normalize_text(payload.prj_physical_attribute_name)
        physical_source = normalize_text(payload.physical_name_source).upper()
        auto_physical = physical_source == "AUTO" or not physical_name
        if auto_physical:
            # Blank bulk/UI input must not erase an existing physical name. For a
            # new PRJ ID, generate a deterministic unique variant from the acronym.
            existing_physical = self.repo.physical_name_for_prj(prj_id)
            if existing_physical:
                physical_name = existing_physical
            else:
                base_physical_name = physical_name or generate_physical_name(payload.prj_attribute_name)
                if not base_physical_name:
                    raise HTTPException(status_code=422, detail="PRJ Physical Attribute Name could not be generated.")
                try:
                    physical_name = self.repo.available_physical_name(base_physical_name, exclude_prj_id=prj_id)
                except ValueError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
        elif self.repo.physical_name_exists(physical_name, exclude_prj_id=prj_id):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"PRJ Physical Attribute Name '{physical_name}' already exists for another PRJ ID. "
                    "An explicitly supplied Excel/UI physical name is preserved and cannot duplicate another attribute."
                ),
            )

        original_type = self.repo.original_mapping_type(prj_id)
        mapping_type = mapping_type_from_value(payload.calculated_or_reported, original_type)
        editable = editable_from_mapping_type(payload.calculated_or_reported)
        try:
            source_abbr_name = self.repo.source_code(payload.source_name, payload.source_abbr_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        calculation_logic = payload.calculation_logic if payload.calculation_logic is not None else "NA"
        calculation_logic = calculation_logic if str(calculation_logic).strip() else "NA"
        tech_logic = normalize_text(payload.tech_logic) or generate_tech_logic(calculation_logic)
        segment = normalize_text(payload.segment) or "NA"
        display_name = normalize_text(payload.display_name) or normalize_text(payload.prj_attribute_name)

        raw = {
            "portfolio": portfolio["sector_name"] if portfolio["portfolio_name"] == "FI" else portfolio["portfolio_name"],
            "prj_id": prj_id,
            "prj_attribute_name": normalize_text(payload.prj_attribute_name),
            "prj_physical_attribute_name": physical_name,
            "section": normalize_text(payload.section),
            "sub_section": normalize_text(payload.sub_section),
            "data_type": normalize_text(payload.data_type) or None,
            "calculated_or_reported": normalize_text(payload.calculated_or_reported),
            "calculation_logic": str(calculation_logic),
            "segment": segment,
            "attribute_definition": payload.attribute_definition,
            "attribute_description": payload.attribute_description,
            "display_order": int(payload.display_order),
            "tech_logic": tech_logic,
            "display_name": display_name,
        }
        master = {
            "prj_id": prj_id,
            "prj_attribute_name": raw["prj_attribute_name"],
            "prj_attribute_definition": payload.attribute_definition,
            "prj_physical_attribute_name": physical_name,
            # Requirement explicitly maps this master field from Segment.
            "where_in_financial_statement": segment,
            "is_active": bool(payload.is_active),
        }
        rule = {
            "prj_id": prj_id,
            "port_ref_id": int(portfolio["port_ref_id"]),
            "source_abbr_name": source_abbr_name,
            "editable": editable,
            "symbol": normalize_text(payload.data_type) or None,
            "mapping_type": mapping_type,
            "calculation_logic": str(calculation_logic),
            "prj_attribute_description": payload.attribute_description,
            "tech_logic": tech_logic,
            "display_order": int(payload.display_order),
            "display_name": display_name,
            "section": normalize_text(payload.section),
            "subsection": normalize_text(payload.sub_section),
            "prompt_description": payload.prompt_description if payload.prompt_description is not None else payload.attribute_description,
            "examples": payload.examples,
            "is_active": bool(payload.is_active),
        }
        return raw, master, rule

    def stage_attribute_pending(
        self, payload: AttributeUpsert, user: str, source_operation: str = "UI"
    ) -> dict[str, Any]:
        raw, master, rule = self._make_rows(payload)
        try:
            self.repo.upsert_raw(raw, user, source_operation)
            self.repo.upsert_staging_master(master, user, source_operation)
            self.repo.upsert_staging_rule(rule, user, source_operation)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "prj_id": master["prj_id"],
            # UI compatibility label for the generated identifier; the persisted key remains PRJ ID.
            "cfv_id": master["prj_id"],
            "staged": True,
            "portfolio": payload.portfolio,
            "prj_physical_attribute_name": master["prj_physical_attribute_name"],
            "staged_tables": [
                "dbo.raw_prj_attribute_new_test",
                "stg.prj_attribute_master_new_test",
                "stg.prj_attribute_business_rules_new_test",
            ],
        }

    def stage_attribute(self, payload: AttributeUpsert, user: str, source_operation: str = "UI") -> dict[str, Any]:
        try:
            result = self.stage_attribute_pending(payload, user, source_operation)
            self.db.commit()
            return result
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail=f"Unique-key or relational constraint failed: {exc.orig}") from exc
        except OperationalError as exc:
            self.db.rollback()
            raise HTTPException(status_code=503, detail=f"Database connection/operation failed while staging attribute: {exc.orig}") from exc
        except SQLAlchemyError as exc:
            self.db.rollback()
            detail = str(getattr(exc, "orig", exc))
            raise HTTPException(
                status_code=422,
                detail=(
                    "Could not save the attribute to raw/staging tables. "
                    "Verify that dbo.raw_prj_attribute_new_test, stg.prj_attribute_master_new_test and "
                    f"stg.prj_attribute_business_rules_new_test exist and match the supplied SQL scripts. Database error: {detail}"
                ),
            ) from exc
        except Exception:
            self.db.rollback()
            raise

    def stage_batch(
        self, payloads: list[AttributeUpsert], user: str, source_operation: str = "EDIT_LATEST"
    ) -> dict[str, Any]:
        staged = []
        try:
            for payload in payloads:
                staged.append(self.stage_attribute_pending(payload, user, source_operation))
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail=f"Batch staging constraint failed: {exc.orig}") from exc
        except Exception:
            self.db.rollback()
            raise
        return {"staged_count": len(staged), "rows": staged}

    def compare_upload(self, payloads: list[AttributeUpsert], include_missing_deleted: bool = False) -> dict[str, Any]:
        uploaded: dict[str, dict[str, Any]] = {}
        for payload in payloads:
            _, master, rule = self._make_rows(payload)
            bucket = uploaded.setdefault(
                master["prj_id"],
                {"master": master, "rules": [], "attribute_name": master["prj_attribute_name"]},
            )
            bucket["master"] = master
            bucket["rules"].append(rule)

        delta_rows: list[dict[str, Any]] = []
        for prj_id, bucket in uploaded.items():
            staged_master = bucket["master"]
            final_master = self.repo.get_master(prj_id, "dbo")
            master_changes = self._changed_fields(final_master, staged_master, MASTER_COMPARE_FIELDS)
            final_rules = self.repo.get_rules(prj_id, "dbo")
            rule_changes: list[str] = []
            for incoming in bucket["rules"]:
                exact = next(
                    (
                        row
                        for row in final_rules
                        if int(row["port_ref_id"]) == int(incoming["port_ref_id"])
                        and row["source_abbr_name"] == incoming["source_abbr_name"]
                        and int(row["display_order"]) == int(incoming["display_order"])
                        and row["section"] == incoming["section"]
                        and row["subsection"] == incoming["subsection"]
                    ),
                    None,
                )
                same_port = [row for row in final_rules if int(row["port_ref_id"]) == int(incoming["port_ref_id"])]
                before_rule = exact or (same_port[0] if len(same_port) == 1 else None)
                fields = self._changed_fields(before_rule, incoming, RULE_COMPARE_FIELDS)
                if fields:
                    rule_changes.append(
                        f"port_ref_id={incoming['port_ref_id']}:" + ",".join(fields)
                    )

            if final_master is None:
                delta_type = "NEW"
            elif master_changes or rule_changes:
                delta_type = "UPDATED"
            else:
                continue
            delta_rows.append(
                {
                    "prj_id": prj_id,
                    "attribute_name": bucket["attribute_name"],
                    "delta_type": delta_type,
                    "changed_fields": master_changes,
                    "rule_changes": rule_changes,
                }
            )

        if include_missing_deleted:
            uploaded_ids = set(uploaded)
            final_ids = {row["prj_id"] for row in self.repo.editable_rows(include_deleted=False)}
            for prj_id in sorted(final_ids - uploaded_ids):
                final_master = self.repo.get_master(prj_id, "dbo") or {}
                delta_rows.append(
                    {
                        "prj_id": prj_id,
                        "attribute_name": final_master.get("prj_attribute_name"),
                        "delta_type": "DELETED",
                        "changed_fields": ["is_active"],
                        "rule_changes": ["all active scopes"],
                    }
                )

        order = {"NEW": 0, "UPDATED": 1, "DELETED": 2}
        delta_rows.sort(key=lambda row: (order.get(row["delta_type"], 9), str(row["prj_id"])))
        return {"count": len(delta_rows), "rows": delta_rows, "has_changes": bool(delta_rows)}

    def stage_delete(self, prj_id: str, user: str) -> dict[str, Any]:
        try:
            self.repo.stage_delete_attribute(prj_id, False, user, "SOFT_DELETE")
            self.db.commit()
        except KeyError as exc:
            self.db.rollback()
            raise HTTPException(status_code=404, detail=f"PRJ ID {prj_id} not found.") from exc
        except Exception:
            self.db.rollback()
            raise
        return {"prj_id": prj_id, "staged_action": "DELETED"}

    def stage_reactivate(self, prj_id: str, user: str) -> dict[str, Any]:
        try:
            self.repo.stage_delete_attribute(prj_id, True, user, "REACTIVATE")
            self.db.commit()
        except KeyError as exc:
            self.db.rollback()
            raise HTTPException(status_code=404, detail=f"PRJ ID {prj_id} not found.") from exc
        except Exception:
            self.db.rollback()
            raise
        return {"prj_id": prj_id, "staged_action": "UPDATED"}

    @staticmethod
    def _changed_fields(before: dict[str, Any] | None, after: dict[str, Any] | None, fields: tuple[str, ...]) -> list[str]:
        if before is None or after is None:
            return list(fields)
        changed = []
        for field in fields:
            left = before.get(field)
            right = after.get(field)
            if isinstance(left, bool) or isinstance(right, bool):
                left, right = bool(left), bool(right)
            if left != right:
                changed.append(field)
        return changed

    def delta(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for prj_id in self.repo.staging_prj_ids():
            staged_master = self.repo.get_master(prj_id, "stg")
            final_master = self.repo.get_master(prj_id, "dbo")
            if not staged_master:
                continue
            changed = self._changed_fields(final_master, staged_master, MASTER_COMPARE_FIELDS)
            staged_rules = self.repo.get_rules(prj_id, "stg")
            final_rules = self.repo.get_rules(prj_id, "dbo")
            rule_changes: list[str] = []
            for row in staged_rules:
                exact = next(
                    (
                        candidate
                        for candidate in final_rules
                        if int(candidate["port_ref_id"]) == int(row["port_ref_id"])
                        and candidate["source_abbr_name"] == row["source_abbr_name"]
                        and int(candidate["display_order"]) == int(row["display_order"])
                        and candidate["section"] == row["section"]
                        and candidate["subsection"] == row["subsection"]
                    ),
                    None,
                )
                same_port = [
                    candidate
                    for candidate in final_rules
                    if int(candidate["port_ref_id"]) == int(row["port_ref_id"])
                ]
                before_rule = exact or (same_port[0] if len(same_port) == 1 else None)
                fields = self._changed_fields(before_rule, row, RULE_COMPARE_FIELDS)
                if fields:
                    rule_changes.append(f"port_ref_id={row['port_ref_id']}:" + ",".join(fields))
            if final_master is None and staged_master.get("is_active"):
                delta_type = "NEW"
            elif final_master is not None and final_master.get("is_active") and not staged_master.get("is_active"):
                delta_type = "DELETED"
            elif changed or rule_changes:
                delta_type = "UPDATED"
            else:
                continue
            items.append(
                {
                    "prj_id": prj_id,
                    "attribute_name": staged_master.get("prj_attribute_name"),
                    "delta_type": delta_type,
                    "changed_fields": changed,
                    "rule_changes": rule_changes,
                }
            )
        return {"count": len(items), "rows": items, "has_changes": bool(items)}

    def _upsert_final_master(self, staged: dict[str, Any], user: str) -> None:
        target = self.db.get(AttributeMaster, staged["prj_id"])
        fields = (
            "prj_attribute_name",
            "prj_attribute_definition",
            "prj_physical_attribute_name",
            "where_in_financial_statement",
            "is_active",
        )
        if target:
            before = model_dict(target)
            for field in fields:
                setattr(target, field, staged.get(field))
            target.updated_at = datetime.utcnow()
            target.updated_by = user
            self.repo.audit(
                "dbo",
                "prj_attribute_master_new_test",
                staged["prj_id"],
                "UPDATE",
                before,
                model_dict(target),
                user,
                "FINALIZE",
            )
            return

        target = AttributeMaster(
            prj_id=staged["prj_id"],
            **{field: staged.get(field) for field in fields},
            created_by=user,
            updated_by=user,
        )
        self.db.add(target)
        self.db.flush()
        self.repo.audit(
            "dbo",
            "prj_attribute_master_new_test",
            staged["prj_id"],
            "INSERT",
            None,
            model_dict(target),
            user,
            "FINALIZE",
        )

    @staticmethod
    def _same_rule_key(rule: AttributeBusinessRule, staged: dict[str, Any]) -> bool:
        return (
            rule.source_abbr_name == staged.get("source_abbr_name")
            and int(rule.display_order) == int(staged.get("display_order") or 0)
            and rule.section == staged.get("section")
            and rule.subsection == staged.get("subsection")
        )

    def _upsert_final_rule(self, staged: dict[str, Any], user: str) -> None:
        candidates = list(
            self.db.scalars(
                select(AttributeBusinessRule)
                .where(
                    AttributeBusinessRule.prj_id == staged["prj_id"],
                    AttributeBusinessRule.port_ref_id == staged["port_ref_id"],
                )
                .order_by(AttributeBusinessRule.scope_id)
            ).all()
        )
        exact = next((row for row in candidates if self._same_rule_key(row, staged)), None)
        target = exact or (candidates[0] if len(candidates) == 1 else None)
        if len(candidates) > 1 and exact is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot unambiguously update final business rule for {staged['prj_id']} / port_ref_id "
                    f"{staged['port_ref_id']}. Multiple rules exist and the edited unique key no longer matches."
                ),
            )

        fields = (
            "prj_id",
            "port_ref_id",
            "source_abbr_name",
            "editable",
            "symbol",
            "mapping_type",
            "calculation_logic",
            "prj_attribute_description",
            "tech_logic",
            "display_order",
            "display_name",
            "section",
            "subsection",
            "prompt_description",
            "examples",
            "is_active",
        )
        if target:
            before = model_dict(target)
            for field in fields:
                setattr(target, field, staged.get(field))
            target.updated_at = datetime.utcnow()
            target.updated_by = user
            self.repo.audit(
                "dbo",
                "prj_attribute_business_rules_new_test",
                str(target.scope_id),
                "UPDATE",
                before,
                model_dict(target),
                user,
                "FINALIZE",
            )
            return

        target = AttributeBusinessRule(
            **{field: staged.get(field) for field in fields},
            created_by=user,
            updated_by=user,
        )
        self.db.add(target)
        self.db.flush()
        self.repo.audit(
            "dbo",
            "prj_attribute_business_rules_new_test",
            str(target.scope_id),
            "INSERT",
            None,
            model_dict(target),
            user,
            "FINALIZE",
        )

    def finalize(self, user: str, confirm: bool) -> dict[str, Any]:
        if not confirm:
            raise HTTPException(status_code=400, detail="Finalization requires confirm=true.")
        delta = self.delta()
        if not delta["has_changes"]:
            return {"updated": 0, "delta": delta, "message": "No staged changes to finalize."}

        prj_ids = [row["prj_id"] for row in delta["rows"]]
        try:
            for prj_id in prj_ids:
                staged_master = self.repo.get_master(prj_id, "stg")
                if not staged_master:
                    continue
                self._upsert_final_master(staged_master, user)
                if not staged_master["is_active"]:
                    existing_rules = list(
                        self.db.scalars(
                            select(AttributeBusinessRule).where(AttributeBusinessRule.prj_id == prj_id)
                        ).all()
                    )
                    for rule in existing_rules:
                        before = model_dict(rule)
                        rule.is_active = False
                        rule.updated_at = datetime.utcnow()
                        rule.updated_by = user
                        self.repo.audit(
                            "dbo",
                            "prj_attribute_business_rules_new_test",
                            str(rule.scope_id),
                            "SOFT_DELETE",
                            before,
                            model_dict(rule),
                            user,
                            "FINALIZE",
                        )
                else:
                    for staged_rule in self.repo.get_rules(prj_id, "stg"):
                        self._upsert_final_rule(staged_rule, user)
            self.repo.clear_staging(prj_ids)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail=f"Finalization constraint failed: {exc.orig}") from exc
        except Exception:
            self.db.rollback()
            raise
        return {"updated": len(prj_ids), "delta": delta, "message": "Database tables updated successfully."}

    def prompt_rows(self, include_deleted: bool = True) -> list[dict[str, Any]]:
        stmt = (
            select(AttributeBusinessRule, PortfolioReference)
            .join(PortfolioReference, PortfolioReference.port_ref_id == AttributeBusinessRule.port_ref_id)
            .order_by(
                AttributeBusinessRule.prj_id,
                AttributeBusinessRule.port_ref_id,
                AttributeBusinessRule.display_order,
                AttributeBusinessRule.scope_id,
            )
        )
        if not include_deleted:
            stmt = stmt.where(AttributeBusinessRule.is_active == true())
        rows: list[dict[str, Any]] = []
        for rule, portfolio in self.db.execute(stmt).all():
            rows.append(
                {
                    "scope_id": rule.scope_id,
                    "prj_id": rule.prj_id,
                    "port_ref_id": rule.port_ref_id,
                    "portfolio": portfolio_label(portfolio.portfolio_name, portfolio.sector_name),
                    "source_abbr_name": rule.source_abbr_name,
                    "section": rule.section,
                    "subsection": rule.subsection,
                    "display_name": rule.display_name,
                    "prompt_description": rule.prompt_description,
                    "examples": rule.examples,
                    "is_active": bool(rule.is_active),
                }
            )
        return rows

    def stage_prompt(
        self,
        scope_id: int,
        prompt_description: str | None,
        examples: str | None,
        user: str,
    ) -> dict[str, Any]:
        rule = self.db.get(AttributeBusinessRule, scope_id)
        if not rule:
            raise HTTPException(status_code=404, detail=f"scope_id {scope_id} not found.")
        master = self.db.get(AttributeMaster, rule.prj_id)
        if not master:
            raise HTTPException(status_code=409, detail=f"Master record {rule.prj_id} is missing.")

        staged = model_dict(rule)
        staged["prompt_description"] = prompt_description
        staged["examples"] = examples
        staged.pop("scope_id", None)
        for field in ("created_at", "updated_at", "created_by", "updated_by"):
            staged.pop(field, None)

        master_row = model_dict(master)
        for field in ("created_at", "updated_at", "created_by", "updated_by"):
            master_row.pop(field, None)
        try:
            self.repo.upsert_staging_master(master_row, user, "PROMPT_UI")
            self.repo.upsert_staging_rule(staged, user, "PROMPT_UI")
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(status_code=409, detail=f"Prompt staging constraint failed: {exc.orig}") from exc
        except Exception:
            self.db.rollback()
            raise
        return {"scope_id": scope_id, "staged": True}
