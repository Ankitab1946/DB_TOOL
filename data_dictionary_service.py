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
    normalize_pipe_values,
    normalize_text,
    pair_pipe_values,
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
        self._portfolio_cache: dict[str, dict[str, Any]] | None = None
        self._source_name_cache: dict[str, str] | None = None
        self._source_code_cache: set[str] | None = None
        self._original_type_cache: dict[str, str | None] | None = None
        self._physical_owner_cache: dict[str, str] | None = None
        self._physical_by_prj_cache: dict[str, str] | None = None

    def prepare_bulk_cache(self, payloads: list[AttributeUpsert]) -> None:
        """Preload stable reference/uniqueness data once for large workbook operations."""
        portfolios = self.repo.list_portfolios(True)
        self._portfolio_cache = {str(row["label"]).casefold(): row for row in portfolios}
        if self.repo.source_table_name() is None:
            # Preserve the existing fallback behavior when the external read-only
            # source table is not available in a local/test environment.
            self._source_name_cache = None
            self._source_code_cache = None
        else:
            sources = self.repo.list_sources()
            self._source_name_cache = {str(row.get("source_name") or "").casefold(): str(row.get("source_code") or "") for row in sources}
            self._source_code_cache = {str(row.get("source_code") or "").casefold() for row in sources if row.get("source_code")}
        prj_ids = {str(item.prj_id) for item in payloads if item.prj_id}
        self._original_type_cache = self.repo.preload_original_mapping_types(prj_ids)
        self._physical_owner_cache, self._physical_by_prj_cache = self.repo.preload_physical_names()

    def _portfolio_ref_cached(self, value: str) -> dict[str, Any] | None:
        label = canonical_portfolio_label(value)
        if self._portfolio_cache is not None:
            return self._portfolio_cache.get(label.casefold())
        return self.repo.portfolio_ref(label)

    def _source_code_cached(self, source_name: str | None, source_abbr_name: str | None) -> str:
        if self._source_name_cache is None or self._source_code_cache is None:
            return self.repo.source_code(source_name, source_abbr_name)
        requested = normalize_text(source_abbr_name)
        if requested:
            if requested.casefold() == "snpar":
                return "SNPAR"
            if requested.casefold() not in self._source_code_cache:
                raise ValueError(f"Unknown source code: {requested}")
            # Preserve the canonical DB spelling from the source list.
            for name, code in self._source_name_cache.items():
                if code.casefold() == requested.casefold():
                    return code
            return requested
        if not source_name:
            return "SNPAR"
        code = self._source_name_cache.get(str(source_name).casefold())
        if not code:
            raise ValueError(f"Unknown source name: {source_name}")
        return code

    def _original_mapping_type_cached(self, prj_id: str) -> str | None:
        if self._original_type_cache is not None:
            return self._original_type_cache.get(prj_id)
        return self.repo.original_mapping_type(prj_id)

    def _physical_name_cached(self, prj_id: str) -> str | None:
        if self._physical_by_prj_cache is not None:
            return self._physical_by_prj_cache.get(prj_id)
        return self.repo.physical_name_for_prj(prj_id)

    def _physical_exists_cached(self, name: str, exclude_prj_id: str | None = None) -> bool:
        if self._physical_owner_cache is None:
            return self.repo.physical_name_exists(name, exclude_prj_id=exclude_prj_id)
        owner = self._physical_owner_cache.get(name.casefold())
        return bool(owner and owner != exclude_prj_id)

    def _available_physical_cached(self, base_name: str, prj_id: str) -> str:
        if self._physical_owner_cache is None:
            return self.repo.available_physical_name(base_name, exclude_prj_id=prj_id)
        base = base_name.strip() or "attribute"
        for suffix in range(1, 10001):
            candidate = base if suffix == 1 else f"{base[:500-len(str(suffix))-1]} {suffix}"
            owner = self._physical_owner_cache.get(candidate.casefold())
            if not owner or owner == prj_id:
                self._physical_owner_cache[candidate.casefold()] = prj_id
                if self._physical_by_prj_cache is not None:
                    self._physical_by_prj_cache[prj_id] = candidate
                return candidate
        raise ValueError(f"Could not generate a unique PRJ Physical Attribute Name from '{base}'.")

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
        detail = self.repo.working_detail(prj_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"PRJ ID {prj_id} was not found in staging or the final dictionary.")
        return detail

    def _make_rows(self, payload: AttributeUpsert) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        prj_id = normalize_text(payload.prj_id) or self.repo.next_prj_id()
        portfolio_label = canonical_portfolio_label(payload.portfolio)
        portfolio = self._portfolio_ref_cached(portfolio_label)
        if not portfolio:
            raise HTTPException(status_code=422, detail=f"Unknown or inactive portfolio/scope: {payload.portfolio}")

        physical_name = normalize_text(payload.prj_physical_attribute_name)
        physical_source = normalize_text(payload.physical_name_source).upper()
        auto_physical = physical_source == "AUTO" or not physical_name
        if auto_physical:
            # Blank bulk/UI input must not erase an existing physical name. For a
            # new PRJ ID, generate a deterministic unique variant from the acronym.
            existing_physical = self._physical_name_cached(prj_id)
            if existing_physical:
                physical_name = existing_physical
            else:
                base_physical_name = physical_name or generate_physical_name(payload.prj_attribute_name)
                if not base_physical_name:
                    raise HTTPException(status_code=422, detail="PRJ Physical Attribute Name could not be generated.")
                try:
                    physical_name = self._available_physical_cached(base_physical_name, prj_id)
                except ValueError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
        elif self._physical_exists_cached(physical_name, exclude_prj_id=prj_id):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"PRJ Physical Attribute Name '{physical_name}' already exists for another PRJ ID. "
                    "An explicitly supplied Excel/UI physical name is preserved and cannot duplicate another attribute."
                ),
            )

        original_type = self._original_mapping_type_cached(prj_id)
        mapping_type = mapping_type_from_value(payload.calculated_or_reported, original_type)
        editable = editable_from_mapping_type(payload.calculated_or_reported)
        try:
            source_abbr_name = self._source_code_cached(payload.source_name, payload.source_abbr_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        calculation_logic = payload.calculation_logic if payload.calculation_logic is not None else "NA"
        calculation_logic = calculation_logic if str(calculation_logic).strip() else "NA"
        tech_logic = normalize_text(payload.tech_logic) or generate_tech_logic(calculation_logic)
        segment = normalize_text(payload.segment) or "NA"
        display_name = normalize_text(payload.display_name) or normalize_text(payload.prj_attribute_name)
        section = normalize_pipe_values(payload.section)
        subsection = normalize_pipe_values(payload.sub_section)
        if not section or not subsection:
            raise HTTPException(status_code=422, detail="Section and Sub-Section cannot be blank.")

        raw = {
            "portfolio": portfolio["sector_name"] if portfolio["portfolio_name"] == "FI" else portfolio["portfolio_name"],
            "prj_id": prj_id,
            "prj_attribute_name": normalize_text(payload.prj_attribute_name),
            "prj_physical_attribute_name": physical_name,
            "section": section,
            "sub_section": subsection,
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
            "section": section,
            "subsection": subsection,
            "prompt_description": payload.prompt_description if payload.prompt_description is not None else payload.attribute_description,
            "examples": payload.examples,
            "is_active": bool(payload.is_active),
        }
        return raw, master, rule

    @staticmethod
    def _expand_rule_pairs(rule: dict[str, Any]) -> list[dict[str, Any]]:
        """Expand pipe-separated Section/Sub-Section values into positional rule rows."""
        try:
            pairs = pair_pipe_values(rule.get("section"), rule.get("subsection"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not pairs:
            raise HTTPException(status_code=422, detail="Section and Sub-Section cannot be blank.")
        rows: list[dict[str, Any]] = []
        for section, subsection in pairs:
            expanded = dict(rule)
            expanded["section"] = section
            expanded["subsection"] = subsection
            rows.append(expanded)
        return rows

    def stage_attribute_pending(
        self, payload: AttributeUpsert, user: str, source_operation: str = "UI"
    ) -> dict[str, Any]:
        raw, master, rule = self._make_rows(payload)
        rules = self._expand_rule_pairs(rule)
        try:
            if hasattr(self.repo, "emit_deferred_insert_audits"):
                pending_audits: list[dict[str, Any]] = []
                raw_audit = self.repo.upsert_raw(raw, user, source_operation, defer_insert_audit=True)
                if raw_audit:
                    pending_audits.append(raw_audit)
                self.repo.upsert_staging_master(master, user, source_operation)
                for index, expanded_rule in enumerate(rules):
                    rule_audit = self.repo.upsert_staging_rule(
                        expanded_rule,
                        user,
                        source_operation,
                        defer_insert_audit=True,
                        strict_key=index > 0,
                    )
                    if rule_audit:
                        pending_audits.append(rule_audit)
                self.repo.emit_deferred_insert_audits(pending_audits)
            else:
                # Compatibility for lightweight repository substitutes used by
                # tests/integrations that implement the original interface.
                self.repo.upsert_raw(raw, user, source_operation)
                self.repo.upsert_staging_master(master, user, source_operation)
                for expanded_rule in rules:
                    self.repo.upsert_staging_rule(expanded_rule, user, source_operation)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "prj_id": master["prj_id"],
            # UI compatibility label for the generated identifier; the persisted key remains PRJ ID.
            "cfv_id": master["prj_id"],
            "staged": True,
            "final_tables_updated": False,
            "portfolio": payload.portfolio,
            "prj_physical_attribute_name": master["prj_physical_attribute_name"],
            "business_rule_rows_staged": len(rules),
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

    def stage_bulk_pending(
        self, payloads: list[AttributeUpsert], user: str, source_operation: str
    ) -> list[dict[str, Any]]:
        """Stage a workbook in a fixed number of lookup queries.

        This is the high-throughput path used by bulk upload. It preloads all raw
        and staging objects once, updates them through in-memory caches, and flushes
        generated identity values once at the end instead of issuing savepoints and
        lookup queries for every workbook row.
        """
        if not payloads:
            return []
        self.prepare_bulk_cache(payloads)
        prepared: list[tuple[AttributeUpsert, dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = []
        for payload in payloads:
            raw, master, rule = self._make_rows(payload)
            prepared.append((payload, raw, master, self._expand_rule_pairs(rule)))

        caches = self.repo.preload_pending_objects({master["prj_id"] for _, _, master, _ in prepared})
        pending_audits: list[dict[str, Any]] = []
        staged: list[dict[str, Any]] = []
        with self.db.no_autoflush:
            for payload, raw, master, rules in prepared:
                raw_audit = self.repo.upsert_raw_cached(raw, user, source_operation, caches["raw"])
                if raw_audit:
                    pending_audits.append(raw_audit)
                self.repo.upsert_staging_master_cached(master, user, source_operation, caches["masters"])
                for index, expanded_rule in enumerate(rules):
                    rule_audit = self.repo.upsert_staging_rule_cached(
                        expanded_rule,
                        user,
                        source_operation,
                        caches["rules"],
                        strict_key=index > 0,
                    )
                    if rule_audit:
                        pending_audits.append(rule_audit)
                staged.append(
                    {
                        "prj_id": master["prj_id"],
                        "cfv_id": master["prj_id"],
                        "staged": True,
                        "final_tables_updated": False,
                        "portfolio": payload.portfolio,
                        "prj_physical_attribute_name": master["prj_physical_attribute_name"],
                        "business_rule_rows_staged": len(rules),
                    }
                )
        self.repo.emit_deferred_insert_audits(pending_audits)
        return staged

    @staticmethod
    def _readable_value(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        text = str(value)
        return text if text.strip() else "—"

    @classmethod
    def _field_change_rows(
        cls,
        prj_id: str,
        delta_type: str,
        scope: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        fields: list[str],
    ) -> list[dict[str, Any]]:
        labels = {
            "prj_attribute_name": "Attribute Name",
            "prj_attribute_definition": "Attribute Definition",
            "prj_physical_attribute_name": "Physical Attribute Name",
            "where_in_financial_statement": "Segment",
            "source_abbr_name": "Source",
            "editable": "Editable",
            "symbol": "Data Type",
            "mapping_type": "Calculated / Reported",
            "calculation_logic": "Calculation Logic",
            "prj_attribute_description": "Attribute Description",
            "tech_logic": "Tech Logic",
            "display_order": "Display Order",
            "display_name": "Display Name",
            "section": "Section",
            "subsection": "Sub-Section",
            "prompt_description": "Prompt Description",
            "examples": "Examples",
            "is_active": "Active",
            "port_ref_id": "Portfolio Ref ID",
        }
        result = []
        for field in fields:
            left = None if before is None else before.get(field)
            right = None if after is None else after.get(field)
            result.append(
                {
                    "prj_id": prj_id,
                    "change_type": delta_type,
                    "scope": scope,
                    "field": labels.get(field, field.replace("_", " ").title()),
                    "before_value": cls._readable_value(left),
                    "after_value": cls._readable_value(right),
                }
            )
        return result

    def compare_upload(self, payloads: list[AttributeUpsert], include_missing_deleted: bool = False) -> dict[str, Any]:
        self.prepare_bulk_cache(payloads)
        uploaded: dict[str, dict[str, Any]] = {}
        for payload in payloads:
            _, master, rule = self._make_rows(payload)
            bucket = uploaded.setdefault(
                master["prj_id"],
                {"master": master, "rules": [], "attribute_name": master["prj_attribute_name"]},
            )
            bucket["master"] = master
            bucket["rules"].extend(self._expand_rule_pairs(rule))

        final_masters, final_rules_by_prj = self.repo.preload_final_state(set(uploaded))
        delta_rows: list[dict[str, Any]] = []
        change_rows: list[dict[str, Any]] = []
        unchanged_count = 0

        for prj_id, bucket in uploaded.items():
            incoming_master = bucket["master"]
            final_master = final_masters.get(prj_id)
            master_changes = self._changed_fields(final_master, incoming_master, MASTER_COMPARE_FIELDS)
            final_rules = final_rules_by_prj.get(prj_id, [])
            rule_changes: list[str] = []
            local_changes: list[dict[str, Any]] = []

            for incoming in bucket["rules"]:
                exact = next(
                    (
                        row for row in final_rules
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
                    rule_changes.append(f"port_ref_id={incoming['port_ref_id']}:" + ",".join(fields))
                    local_changes.extend(
                        self._field_change_rows(
                            prj_id,
                            "NEW" if final_master is None else "UPDATED",
                            f"Business Rule / port_ref_id={incoming['port_ref_id']}",
                            before_rule,
                            incoming,
                            fields,
                        )
                    )

            if final_master is None:
                delta_type = "NEW"
            elif master_changes or rule_changes:
                delta_type = "UPDATED"
            else:
                unchanged_count += 1
                continue

            change_rows.extend(
                self._field_change_rows(
                    prj_id, delta_type, "Attribute Master", final_master, incoming_master, master_changes
                )
            )
            # Ensure rule rows use the final PRJ-level change type.
            for row in local_changes:
                row["change_type"] = delta_type
            change_rows.extend(local_changes)
            delta_rows.append(
                {
                    "prj_id": prj_id,
                    "attribute_name": bucket["attribute_name"],
                    "delta_type": delta_type,
                    "changed_field_count": len(master_changes) + sum(1 for row in local_changes),
                }
            )

        if include_missing_deleted:
            uploaded_ids = set(uploaded)
            final_ids = self.repo.active_final_prj_ids()
            missing_ids = final_ids - uploaded_ids
            missing_masters, _ = self.repo.preload_final_state(missing_ids)
            for prj_id in sorted(missing_ids):
                final_master = missing_masters.get(prj_id) or {}
                delta_rows.append(
                    {
                        "prj_id": prj_id,
                        "attribute_name": final_master.get("prj_attribute_name"),
                        "delta_type": "DELETED",
                        "changed_field_count": 1,
                    }
                )
                change_rows.extend(
                    self._field_change_rows(
                        prj_id,
                        "DELETED",
                        "Attribute Master",
                        {"is_active": True},
                        {"is_active": False},
                        ["is_active"],
                    )
                )

        order = {"NEW": 0, "UPDATED": 1, "DELETED": 2}
        delta_rows.sort(key=lambda row: (order.get(row["delta_type"], 9), str(row["prj_id"])))
        change_rows.sort(
            key=lambda row: (order.get(row["change_type"], 9), str(row["prj_id"]), row["scope"], row["field"])
        )
        summary = {
            "inserted": sum(1 for row in delta_rows if row["delta_type"] == "NEW"),
            "updated": sum(1 for row in delta_rows if row["delta_type"] == "UPDATED"),
            "deleted": sum(1 for row in delta_rows if row["delta_type"] == "DELETED"),
            "unchanged": unchanged_count,
        }
        return {
            "count": len(delta_rows),
            "rows": delta_rows,
            "changes": change_rows,
            "summary": summary,
            "has_changes": bool(delta_rows),
        }

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
        prj_ids = self.repo.staging_prj_ids()
        if not prj_ids:
            return {"count": 0, "rows": [], "has_changes": False}

        id_set = set(prj_ids)
        staged_masters, staged_rules_by_prj = self.repo.preload_state(id_set, "stg")
        final_masters, final_rules_by_prj = self.repo.preload_state(id_set, "dbo")
        items: list[dict[str, Any]] = []

        for prj_id in prj_ids:
            staged_master = staged_masters.get(prj_id)
            final_master = final_masters.get(prj_id)
            if not staged_master:
                continue
            changed = self._changed_fields(final_master, staged_master, MASTER_COMPARE_FIELDS)
            staged_rules = staged_rules_by_prj.get(prj_id, [])
            final_rules = final_rules_by_prj.get(prj_id, [])
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

    def _upsert_final_rule(self, staged: dict[str, Any], user: str, strict_key: bool = False) -> None:
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
        target = exact or (candidates[0] if len(candidates) == 1 and not strict_key else None)
        if len(candidates) > 1 and exact is None and not strict_key:
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
                    staged_rules = self.repo.get_rules(prj_id, "stg")
                    seen_ports: dict[int, int] = {}
                    for staged_rule in staged_rules:
                        port_ref_id = int(staged_rule["port_ref_id"])
                        occurrence = seen_ports.get(port_ref_id, 0)
                        self._upsert_final_rule(staged_rule, user, strict_key=occurrence > 0)
                        seen_ports[port_ref_id] = occurrence + 1
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
