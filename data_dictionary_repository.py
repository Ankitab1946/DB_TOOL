"""Dialect-neutral SQLAlchemy repository for SQL Server and PostgreSQL."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, Table, and_, delete, distinct, exists, false, func, inspect, or_, select, true
from sqlalchemy.orm import Session

from DataDictionaryAdminApp.model.entities import (
    AttributeBusinessRule,
    AttributeMaster,
    AuditTable,
    PortfolioReference,
    RawAttribute,
    StagingAttributeMaster,
    StagingBusinessRule,
)
from DataDictionaryAdminApp.utils.normalizers import canonical_portfolio_label


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)


def model_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    return {column.key: getattr(obj, column.key) for column in obj.__table__.columns}


def portfolio_label(portfolio_name: str, sector_name: str) -> str:
    return f"FI {sector_name}" if str(portfolio_name).upper() == "FI" else str(portfolio_name)


class DataDictionaryRepository:
    def __init__(self, db: Session):
        self.db = db

    def audit(
        self,
        schema_name: str,
        table_name: str,
        record_key: str,
        action: str,
        before: Any,
        after: Any,
        user: str,
        source_operation: str = "UI",
    ) -> None:
        self.db.add(
            AuditTable(
                schema_name=schema_name,
                table_name=table_name,
                record_key=str(record_key),
                action=action,
                before_value=_json(before),
                after_value=_json(after),
                source_operation=source_operation,
                performed_by=user,
                performed_at=datetime.utcnow(),
            )
        )

    def next_prj_id(self) -> str:
        values: list[str] = []
        for model in (RawAttribute, StagingAttributeMaster, AttributeMaster):
            values.extend(str(row[0]) for row in self.db.execute(select(model.prj_id)).all() if row[0])
        maximum = 0
        for value in values:
            match = re.search(r"(\d+)$", value.strip(), flags=re.IGNORECASE)
            if match:
                maximum = max(maximum, int(match.group(1)))
        return f"PRJ{maximum + 1}"

    def existing_prj_ids(self) -> set[str]:
        """Return PRJ IDs already present in raw, staging, or final storage."""
        values: set[str] = set()
        for model in (RawAttribute, StagingAttributeMaster, AttributeMaster):
            values.update(
                str(value)
                for value in self.db.scalars(select(model.prj_id)).all()
                if value is not None and str(value).strip()
            )
        return values

    def physical_name_exists(self, physical_name: str, exclude_prj_id: str | None = None) -> bool:
        wanted = physical_name.strip().lower()
        for model in (AttributeMaster, StagingAttributeMaster):
            stmt = select(model.prj_id).where(func.lower(model.prj_physical_attribute_name) == wanted)
            if exclude_prj_id:
                stmt = stmt.where(model.prj_id != exclude_prj_id)
            if self.db.execute(stmt.limit(1)).first():
                return True
        return False

    def _source_table(self) -> Table | None:
        bind = self.db.get_bind()
        inspector = inspect(bind)
        for name in ("prj_data_sources", "prj_data_source"):
            if inspector.has_table(name, schema="dbo"):
                return Table(name, MetaData(), schema="dbo", autoload_with=bind)
        return None

    def source_table_name(self) -> str | None:
        table = self._source_table()
        return table.fullname if table is not None else None

    def list_sources(self) -> list[dict[str, Any]]:
        table = self._source_table()
        if table is None:
            return [{"src_id": None, "source_code": "SNPAR", "source_name": "SNPAR (default)"}]
        id_col = next((table.c[name] for name in ("src_id", "prj_src_id") if name in table.c), None)
        if "source_code" not in table.c or "source_name" not in table.c:
            return [{"src_id": None, "source_code": "SNPAR", "source_name": "SNPAR (default)"}]
        columns = [table.c.source_code, table.c.source_name]
        if id_col is not None:
            columns.insert(0, id_col)
        rows = self.db.execute(select(*columns).order_by(table.c.source_name)).all()
        result = []
        for row in rows:
            mapping = row._mapping
            result.append(
                {
                    "src_id": mapping.get(id_col.key) if id_col is not None else None,
                    "source_code": mapping["source_code"],
                    "source_name": mapping["source_name"],
                }
            )
        return result

    def source_code(self, source_name: str | None, source_abbr_name: str | None = None) -> str:
        requested_code = str(source_abbr_name or "").strip()
        table = self._source_table()
        if requested_code:
            if requested_code.upper() == "SNPAR":
                return "SNPAR"
            if table is None or "source_code" not in table.c:
                return requested_code
            value = self.db.execute(
                select(table.c.source_code).where(table.c.source_code == requested_code).limit(1)
            ).scalar_one_or_none()
            if value is None:
                raise ValueError(f"Unknown source code: {requested_code}")
            return str(value)
        if not source_name:
            return "SNPAR"
        if table is None or "source_code" not in table.c or "source_name" not in table.c:
            return "SNPAR"
        value = self.db.execute(
            select(table.c.source_code).where(table.c.source_name == source_name).limit(1)
        ).scalar_one_or_none()
        if value is None:
            raise ValueError(f"Unknown source name: {source_name}")
        return str(value)

    def list_portfolios(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        stmt = select(PortfolioReference)
        if not include_inactive:
            stmt = stmt.where(PortfolioReference.is_active == true())
        stmt = stmt.order_by(PortfolioReference.port_ref_id)
        result = []
        for item in self.db.scalars(stmt).all():
            row = model_dict(item)
            row["label"] = portfolio_label(row["portfolio_name"], row["sector_name"])
            result.append(row)
        return result

    def portfolio_ref(self, portfolio: str) -> dict[str, Any] | None:
        wanted = canonical_portfolio_label(portfolio).lower()
        return next((row for row in self.list_portfolios(False) if str(row["label"]).lower() == wanted), None)

    @staticmethod
    def _master_model(schema: str):
        if schema == "dbo":
            return AttributeMaster
        if schema == "stg":
            return StagingAttributeMaster
        raise ValueError("Invalid schema")

    @staticmethod
    def _rule_model(schema: str):
        if schema == "dbo":
            return AttributeBusinessRule
        if schema == "stg":
            return StagingBusinessRule
        raise ValueError("Invalid schema")

    def get_master(self, prj_id: str, schema: str = "dbo") -> dict[str, Any] | None:
        obj = self.db.get(self._master_model(schema), prj_id)
        return model_dict(obj) if obj else None

    def get_rules(self, prj_id: str, schema: str = "dbo") -> list[dict[str, Any]]:
        rule_model = self._rule_model(schema)
        stmt = (
            select(rule_model, PortfolioReference)
            .join(PortfolioReference, PortfolioReference.port_ref_id == rule_model.port_ref_id)
            .where(rule_model.prj_id == prj_id)
            .order_by(rule_model.port_ref_id, rule_model.display_order, rule_model.scope_id)
        )
        result = []
        for rule, portfolio in self.db.execute(stmt).all():
            row = model_dict(rule)
            row.update(
                {
                    "portfolio_name": portfolio.portfolio_name,
                    "sector_name": portfolio.sector_name,
                    "portfolio": portfolio_label(portfolio.portfolio_name, portfolio.sector_name),
                }
            )
            result.append(row)
        return result

    def final_detail(self, prj_id: str) -> dict[str, Any] | None:
        master = self.get_master(prj_id, "dbo")
        if master:
            master["rules"] = self.get_rules(prj_id, "dbo")
        return master

    def filter_final(self, filters: Any, page_size: int) -> dict[str, Any]:
        conditions = []
        m = AttributeMaster
        r = AttributeBusinessRule
        if not filters.include_deleted:
            conditions.append(m.is_active == true())
        if filters.prj_id:
            conditions.append(m.prj_id.ilike(f"%{filters.prj_id.strip()}%"))
        if filters.attribute_name:
            conditions.append(m.prj_attribute_name.ilike(f"%{filters.attribute_name.strip()}%"))
        if filters.attribute_definition:
            conditions.append(m.prj_attribute_definition.ilike(f"%{filters.attribute_definition.strip()}%"))
        rule_base = [r.prj_id == m.prj_id]
        if not filters.include_deleted:
            rule_base.append(r.is_active == true())
        if filters.section:
            conditions.append(exists(select(1).where(*rule_base, r.section == filters.section)))
        if filters.subsection:
            conditions.append(exists(select(1).where(*rule_base, r.subsection == filters.subsection)))
        if filters.portfolios:
            port_ref_ids = []
            for portfolio in filters.portfolios:
                ref = self.portfolio_ref(portfolio)
                if ref:
                    port_ref_ids.append(int(ref["port_ref_id"]))
            if port_ref_ids:
                conditions.append(exists(select(1).where(*rule_base, r.port_ref_id.in_(port_ref_ids))))
            else:
                conditions.append(m.prj_id == "__NO_MATCH__")
        if filters.sources:
            source_codes = [str(source).strip() for source in filters.sources if str(source).strip()]
            if source_codes:
                conditions.append(exists(select(1).where(*rule_base, r.source_abbr_name.in_(source_codes))))
        if filters.overlapped_only:
            scope_stmt = select(func.count(distinct(r.port_ref_id))).where(r.prj_id == m.prj_id)
            if not filters.include_deleted:
                scope_stmt = scope_stmt.where(r.is_active == true())
            scope_count = scope_stmt.correlate(m).scalar_subquery()
            conditions.append(scope_count > 1)
        if filters.search:
            term = f"%{filters.search.strip()}%"
            conditions.append(or_(m.prj_id.ilike(term), m.prj_attribute_name.ilike(term), m.prj_attribute_definition.ilike(term)))

        count_stmt = select(func.count()).select_from(m)
        data_stmt = select(m)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
            data_stmt = data_stmt.where(and_(*conditions))
        total = int(self.db.execute(count_stmt).scalar_one())
        page = max(1, int(filters.page or 1))
        masters = self.db.scalars(
            data_stmt.order_by(m.prj_id).offset((page - 1) * page_size).limit(page_size)
        ).all()
        prj_ids = [item.prj_id for item in masters]
        rules_by_prj: dict[str, list[tuple[AttributeBusinessRule, PortfolioReference]]] = {key: [] for key in prj_ids}
        if prj_ids:
            rule_stmt = (
                select(AttributeBusinessRule, PortfolioReference)
                .join(PortfolioReference, PortfolioReference.port_ref_id == AttributeBusinessRule.port_ref_id)
                .where(AttributeBusinessRule.prj_id.in_(prj_ids))
                .order_by(AttributeBusinessRule.prj_id, AttributeBusinessRule.port_ref_id, AttributeBusinessRule.display_order)
            )
            for rule, portfolio in self.db.execute(rule_stmt).all():
                rules_by_prj.setdefault(rule.prj_id, []).append((rule, portfolio))

        rows = []
        for master in masters:
            item = model_dict(master)
            pairs = rules_by_prj.get(master.prj_id, [])
            active_pairs = [pair for pair in pairs if pair[0].is_active]
            first = (active_pairs or pairs or [(None, None)])[0]
            rule, _ = first
            if rule is not None:
                item.update(
                    {
                        "editable": rule.editable,
                        "symbol": rule.symbol,
                        "mapping_type": rule.mapping_type,
                        "calculation_logic": rule.calculation_logic,
                        "prj_attribute_description": rule.prj_attribute_description,
                        "tech_logic": rule.tech_logic,
                        "display_order": rule.display_order,
                        "display_name": rule.display_name,
                        "section": rule.section,
                        "subsection": rule.subsection,
                    }
                )
            scope_pairs = active_pairs if active_pairs else pairs
            item["portfolios"] = ", ".join(dict.fromkeys(portfolio_label(p.portfolio_name, p.sector_name) for _, p in scope_pairs))
            item["sources"] = ", ".join(dict.fromkeys(str(rule.source_abbr_name) for rule, _ in scope_pairs))
            rows.append(item)
        return {"rows": rows, "total": total, "page": page, "page_size": page_size}

    def soft_deleted_rows(self) -> list[dict[str, Any]]:
        """Return finalized soft-deleted attributes for review/reactivation."""
        m = AttributeMaster
        masters = list(
            self.db.scalars(
                select(m).where(m.is_active == false()).order_by(m.prj_id)
            ).all()
        )
        if not masters:
            return []

        prj_ids = [item.prj_id for item in masters]
        rules_by_prj: dict[str, list[tuple[AttributeBusinessRule, PortfolioReference]]] = {key: [] for key in prj_ids}
        stmt = (
            select(AttributeBusinessRule, PortfolioReference)
            .join(PortfolioReference, PortfolioReference.port_ref_id == AttributeBusinessRule.port_ref_id)
            .where(AttributeBusinessRule.prj_id.in_(prj_ids))
            .order_by(AttributeBusinessRule.prj_id, AttributeBusinessRule.port_ref_id, AttributeBusinessRule.display_order)
        )
        for rule, portfolio in self.db.execute(stmt).all():
            rules_by_prj.setdefault(rule.prj_id, []).append((rule, portfolio))

        rows: list[dict[str, Any]] = []
        for master in masters:
            item = model_dict(master)
            pairs = rules_by_prj.get(master.prj_id, [])
            first_rule = pairs[0][0] if pairs else None
            if first_rule is not None:
                item.update(
                    {
                        "editable": first_rule.editable,
                        "symbol": first_rule.symbol,
                        "mapping_type": first_rule.mapping_type,
                        "section": first_rule.section,
                        "subsection": first_rule.subsection,
                        "display_order": first_rule.display_order,
                        "display_name": first_rule.display_name,
                    }
                )
            item["portfolios"] = ", ".join(
                dict.fromkeys(portfolio_label(portfolio.portfolio_name, portfolio.sector_name) for _, portfolio in pairs)
            )
            item["sources"] = ", ".join(
                dict.fromkeys(str(rule.source_abbr_name) for rule, _ in pairs)
            )
            item["is_active"] = False
            rows.append(item)
        return rows

    def editable_rows(self, include_deleted: bool = True) -> list[dict[str, Any]]:
        stmt = (
            select(AttributeMaster, AttributeBusinessRule, PortfolioReference)
            .join(AttributeBusinessRule, AttributeBusinessRule.prj_id == AttributeMaster.prj_id)
            .join(PortfolioReference, PortfolioReference.port_ref_id == AttributeBusinessRule.port_ref_id)
        )
        if not include_deleted:
            stmt = stmt.where(AttributeMaster.is_active == true(), AttributeBusinessRule.is_active == true())
        stmt = stmt.order_by(AttributeMaster.prj_id, AttributeBusinessRule.port_ref_id, AttributeBusinessRule.display_order)
        rows = []
        for master, rule, portfolio in self.db.execute(stmt).all():
            rows.append(
                {
                    "scope_id": rule.scope_id,
                    "prj_id": master.prj_id,
                    "portfolio": portfolio_label(portfolio.portfolio_name, portfolio.sector_name),
                    "source_abbr_name": rule.source_abbr_name,
                    "prj_attribute_name": master.prj_attribute_name,
                    "prj_physical_attribute_name": master.prj_physical_attribute_name,
                    "section": rule.section,
                    "sub_section": rule.subsection,
                    "data_type": rule.symbol,
                    "calculated_or_reported": rule.mapping_type,
                    "calculation_logic": rule.calculation_logic,
                    "segment": master.where_in_financial_statement,
                    "prj_attribute_definition": master.prj_attribute_definition,
                    "attribute_description": rule.prj_attribute_description,
                    "display_order": rule.display_order,
                    "display_name": rule.display_name,
                    "prompt_description": rule.prompt_description,
                    "examples": rule.examples,
                    "is_active": bool(rule.is_active and master.is_active),
                }
            )
        return rows

    def lookup_values(self) -> dict[str, Any]:
        sections = list(self.db.scalars(select(distinct(AttributeBusinessRule.section)).where(AttributeBusinessRule.is_active == true()).order_by(AttributeBusinessRule.section)).all())
        subsections = list(self.db.scalars(select(distinct(AttributeBusinessRule.subsection)).where(AttributeBusinessRule.is_active == true()).order_by(AttributeBusinessRule.subsection)).all())
        return {"portfolios": self.list_portfolios(), "sources": self.list_sources(), "sections": sections, "subsections": subsections}

    def original_mapping_type(self, prj_id: str) -> str | None:
        for value in self.db.scalars(
            select(AttributeBusinessRule.mapping_type)
            .where(AttributeBusinessRule.prj_id == prj_id)
            .order_by(AttributeBusinessRule.scope_id)
        ).all():
            if str(value or "").strip().lower() != "repeated":
                return str(value)
        for value in self.db.scalars(
            select(RawAttribute.calculated_or_reported).where(RawAttribute.prj_id == prj_id).order_by(RawAttribute.raw_row_id)
        ).all():
            if str(value or "").strip().lower() != "repeated":
                return str(value)
        return None

    def active_raw_for_scope(self, prj_id: str, portfolio: str) -> list[RawAttribute]:
        return list(
            self.db.scalars(
                select(RawAttribute)
                .where(RawAttribute.prj_id == prj_id, RawAttribute.portfolio == portfolio, RawAttribute.is_active == true())
                .order_by(RawAttribute.raw_row_id)
            ).all()
        )

    def upsert_raw(self, row: dict[str, Any], user: str, source_operation: str) -> None:
        existing = self.active_raw_for_scope(row["prj_id"], row["portfolio"])
        target = next(
            (
                item for item in existing
                if int(item.display_order) == int(row["display_order"])
                and item.section == row["section"]
                and item.sub_section == row["sub_section"]
            ),
            None,
        )
        if target is None and len(existing) == 1 and not source_operation.upper().startswith("BULK_"):
            target = existing[0]
        if target is None and len(existing) > 1 and not source_operation.upper().startswith("BULK_"):
            raise ValueError(
                f"Cannot unambiguously update raw row for {row['prj_id']} / {row['portfolio']}; "
                "multiple raw rows exist and the edited key no longer matches."
            )
        if target:
            before = model_dict(target)
            for key, value in row.items():
                setattr(target, key, value)
            target.is_active = True
            target.updated_at = datetime.utcnow()
            target.updated_by = user
            self.audit("dbo", "raw_prj_attribute_new_test", str(target.raw_row_id), "UPDATE", before, model_dict(target), user, source_operation)
        else:
            target = RawAttribute(**row, is_active=True, created_by=user, updated_by=user)
            self.db.add(target)
            self.db.flush()
            self.audit("dbo", "raw_prj_attribute_new_test", str(target.raw_row_id), "INSERT", None, model_dict(target), user, source_operation)

    def upsert_staging_master(self, row: dict[str, Any], user: str, source_operation: str) -> None:
        target = self.db.get(StagingAttributeMaster, row["prj_id"])
        if target:
            before = model_dict(target)
            for key in ("prj_attribute_name", "prj_attribute_definition", "prj_physical_attribute_name", "where_in_financial_statement", "is_active"):
                setattr(target, key, row.get(key))
            target.updated_at = datetime.utcnow()
            target.updated_by = user
            self.audit("stg", "prj_attribute_master_new_test", row["prj_id"], "UPDATE", before, model_dict(target), user, source_operation)
        else:
            target = StagingAttributeMaster(**{key: row[key] for key in ("prj_id", "prj_attribute_name", "prj_attribute_definition", "prj_physical_attribute_name", "where_in_financial_statement", "is_active")}, created_by=user, updated_by=user)
            self.db.add(target)
            self.db.flush()
            self.audit("stg", "prj_attribute_master_new_test", row["prj_id"], "INSERT", None, model_dict(target), user, source_operation)

    def upsert_staging_rule(self, row: dict[str, Any], user: str, source_operation: str) -> None:
        existing = list(self.db.scalars(
            select(StagingBusinessRule)
            .where(StagingBusinessRule.prj_id == row["prj_id"], StagingBusinessRule.port_ref_id == row["port_ref_id"])
            .order_by(StagingBusinessRule.scope_id)
        ).all())
        target = next(
            (
                item for item in existing
                if item.source_abbr_name == row["source_abbr_name"]
                and int(item.display_order) == int(row["display_order"])
                and item.section == row["section"]
                and item.subsection == row["subsection"]
            ),
            None,
        )
        if target is None and len(existing) == 1 and not source_operation.upper().startswith("BULK_"):
            target = existing[0]
        if target is None and len(existing) > 1 and not source_operation.upper().startswith("BULK_"):
            raise ValueError(
                f"Cannot unambiguously update staging rule for {row['prj_id']} / port_ref_id {row['port_ref_id']}; "
                "multiple staged rules exist and the edited key no longer matches."
            )
        fields = (
            "prj_id", "port_ref_id", "source_abbr_name", "editable", "symbol", "mapping_type", "calculation_logic",
            "prj_attribute_description", "tech_logic", "display_order", "display_name", "section", "subsection",
            "prompt_description", "examples", "is_active",
        )
        if target:
            before = model_dict(target)
            for key in fields:
                setattr(target, key, row.get(key))
            target.updated_at = datetime.utcnow()
            target.updated_by = user
            self.audit("stg", "prj_attribute_business_rules_new_test", str(target.scope_id), "UPDATE", before, model_dict(target), user, source_operation)
        else:
            target = StagingBusinessRule(**{key: row.get(key) for key in fields}, created_by=user, updated_by=user)
            self.db.add(target)
            self.db.flush()
            self.audit("stg", "prj_attribute_business_rules_new_test", str(target.scope_id), "INSERT", None, model_dict(target), user, source_operation)

    def stage_delete_attribute(self, prj_id: str, active: bool, user: str, source_operation: str) -> None:
        base = self.get_master(prj_id, "stg") or self.get_master(prj_id, "dbo")
        if not base:
            raise KeyError(prj_id)
        self.upsert_staging_master(
            {
                "prj_id": base["prj_id"],
                "prj_attribute_name": base["prj_attribute_name"],
                "prj_attribute_definition": base.get("prj_attribute_definition"),
                "prj_physical_attribute_name": base["prj_physical_attribute_name"],
                "where_in_financial_statement": base.get("where_in_financial_statement") or "NA",
                "is_active": bool(active),
            },
            user,
            source_operation,
        )
        rules = self.get_rules(prj_id, "stg") or self.get_rules(prj_id, "dbo")
        for item in rules:
            row = {key: item.get(key) for key in (
                "prj_id", "port_ref_id", "source_abbr_name", "editable", "symbol", "mapping_type", "calculation_logic",
                "prj_attribute_description", "tech_logic", "display_order", "display_name", "section", "subsection",
                "prompt_description", "examples",
            )}
            row["is_active"] = bool(active)
            self.upsert_staging_rule(row, user, source_operation)
        raw_rows = list(self.db.scalars(select(RawAttribute).where(RawAttribute.prj_id == prj_id)).all())
        for raw in raw_rows:
            before = model_dict(raw)
            raw.is_active = bool(active)
            raw.updated_at = datetime.utcnow()
            raw.updated_by = user
            self.audit("dbo", "raw_prj_attribute_new_test", str(raw.raw_row_id), "REACTIVATE" if active else "SOFT_DELETE", before, model_dict(raw), user, source_operation)

    def staging_prj_ids(self) -> list[str]:
        return list(self.db.scalars(select(StagingAttributeMaster.prj_id).order_by(StagingAttributeMaster.prj_id)).all())

    def clear_staging(self, prj_ids: list[str] | None = None) -> None:
        if prj_ids:
            self.db.execute(delete(StagingBusinessRule).where(StagingBusinessRule.prj_id.in_(prj_ids)))
            self.db.execute(delete(StagingAttributeMaster).where(StagingAttributeMaster.prj_id.in_(prj_ids)))
        else:
            self.db.execute(delete(StagingBusinessRule))
            self.db.execute(delete(StagingAttributeMaster))

    def clear_raw_and_staging_for_replace(self, user: str) -> None:
        raw_count = int(self.db.execute(select(func.count()).select_from(RawAttribute)).scalar_one())
        stg_count = int(self.db.execute(select(func.count()).select_from(StagingAttributeMaster)).scalar_one())
        self.audit("dbo", "raw_prj_attribute_new_test", "*", "REPLACE_CLEAR", {"row_count": raw_count}, None, user, "BULK_REPLACE")
        self.audit("stg", "prj_attribute_master_new_test", "*", "REPLACE_CLEAR", {"row_count": stg_count}, None, user, "BULK_REPLACE")
        self.db.execute(delete(StagingBusinessRule))
        self.db.execute(delete(StagingAttributeMaster))
        self.db.execute(delete(RawAttribute))

    def audit_rows(self, filters: Any, limit: int = 2000) -> list[dict[str, Any]]:
        stmt = select(AuditTable)
        conditions = []
        for field in ("table_name", "record_key", "action", "performed_by", "source_operation"):
            value = getattr(filters, field, None)
            if value:
                conditions.append(getattr(AuditTable, field).ilike(f"%{value}%"))
        if getattr(filters, "search", None):
            term = f"%{filters.search}%"
            conditions.append(or_(AuditTable.table_name.ilike(term), AuditTable.record_key.ilike(term), AuditTable.before_value.ilike(term), AuditTable.after_value.ilike(term)))
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(AuditTable.performed_at.desc(), AuditTable.audit_id.desc()).limit(limit)
        return [model_dict(item) for item in self.db.scalars(stmt).all()]
