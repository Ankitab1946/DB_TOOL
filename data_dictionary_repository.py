"""Dialect-neutral SQLAlchemy repository for SQL Server and PostgreSQL.

Business/LLM rule data and display metadata are stored separately and rejoined
here so the public service/API contract remains backward compatible.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, Table, and_, delete, distinct, false, func, inspect, or_, select, text, true
from sqlalchemy.orm import Session

from DataDictionaryAdminApp.model.entities import (
    AttributeBusinessRule,
    AttributeDisplay,
    AttributeMaster,
    AuditTable,
    PortfolioReference,
    PostgresPortfolioReference,
    RawAttribute,
    StagingAttributeDisplay,
    StagingAttributeMaster,
    StagingBusinessRule,
)
from DataDictionaryAdminApp.utils.normalizers import canonical_portfolio_label, split_pipe_values


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)


def model_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    return {column.key: getattr(obj, column.key) for column in obj.__table__.columns}


def portfolio_label(portfolio_name: str, sector_name: str) -> str:
    return f"{str(portfolio_name).strip()} {str(sector_name).strip()}".strip()


BUSINESS_INPUT_MAP = {
    "prj_id": "prj_id",
    "port_ref_id": "port_ref_id",
    "source_abbr_name": "source_abbr_name",
    "prompt_description": "prompt_description",
    "examples": "examples_for_llm",
    "editable": "editable",
    "symbol": "data_type",
    "mapping_type": "attribute_type",
    "tech_logic": "business_logic",
    "calculation_logic": "calculation_logic",
}
DISPLAY_INPUT_MAP = {
    "display_order": "display_order",
    "prj_id": "prj_id",
    "display_name": "display_name",
    "section": "section",
    "subsection": "subsection",
    "prj_attribute_definition": "prj_attribute_definition",
    "prj_attribute_description": "prj_attribute_description",
    "segment": "segment",
    "report_type": "report_type",
}


def combined_rule_dict(rule: Any, display: Any, *, is_active: bool = True) -> dict[str, Any]:
    """Return the historical combined rule shape used by API/UI/service code."""
    row = model_dict(rule)
    row.update(
        {
            "symbol": rule.data_type,
            "mapping_type": rule.attribute_type,
            "tech_logic": rule.business_logic,
            "examples": rule.examples_for_llm,
            "display_id": display.display_id,
            "display_order": display.display_order,
            "display_name": display.display_name,
            "section": display.section,
            "subsection": display.subsection,
            "prj_attribute_definition": display.prj_attribute_definition,
            "prj_attribute_description": display.prj_attribute_description,
            "segment": display.segment,
            "report_type": display.report_type,
            "is_active": bool(is_active),
        }
    )
    return row


class DataDictionaryRepository:
    _source_table_cache: dict[tuple[int, str], Table | None] = {}

    def __init__(self, db: Session):
        self.db = db

    def _physical_schema(self, logical: str) -> str:
        bind = self.db.get_bind()
        return ({"dbo": "prj_dbd", "stg": "prj_stage"}.get(logical, logical)
                if bind.dialect.name == "postgresql" else logical)

    def portfolio_model(self):
        """Return the physical portfolio-reference ORM model for this engine."""
        bind = self.db.get_bind()
        return PostgresPortfolioReference if bind.dialect.name == "postgresql" else PortfolioReference

    def portfolio_table_name(self) -> str:
        return ("prj_dbd.prj_portfolio_reference"
                if self.db.get_bind().dialect.name == "postgresql"
                else "dbo.prj_portfolio_reference_new_test")

    def hard_delete_dictionary_data(self) -> dict[str, int]:
        deleted: dict[str, int] = {}
        targets = (
            ("stg.prj_attribute_display_test", StagingAttributeDisplay),
            ("stg.prj_attribute_business_rules_new_test", StagingBusinessRule),
            ("dbo.prj_attribute_display_test", AttributeDisplay),
            ("dbo.prj_attribute_business_rules_new_test", AttributeBusinessRule),
            ("stg.prj_attribute_master_new_test", StagingAttributeMaster),
            ("dbo.prj_attribute_master_new_test", AttributeMaster),
            ("dbo.raw_prj_attribute_new_test", RawAttribute),
            ("dbo.audit_table_new_test", AuditTable),
        )
        for table_name, model in targets:
            count = int(self.db.scalar(select(func.count()).select_from(model)) or 0)
            self.db.execute(delete(model))
            deleted[table_name] = count

        portfolio_model = self.portfolio_model()
        custom_filter = ~portfolio_model.port_ref_id.in_([1, 2, 3, 4])
        count = int(self.db.scalar(select(func.count()).select_from(portfolio_model).where(custom_filter)) or 0)
        self.db.execute(delete(portfolio_model).where(custom_filter))
        deleted[f"{self.portfolio_table_name()} (custom rows)"] = count
        return deleted

    def audit(self, schema_name: str, table_name: str, record_key: str, action: str, before: Any,
              after: Any, user: str, source_operation: str = "UI") -> None:
        # Persist the physical schema name in audit history. SQL Server keeps
        # dbo/stg; PostgreSQL translates those logical schemas to prj_dbd/prj_stage.
        physical_schema = self._physical_schema(schema_name)
        self.db.add(
            AuditTable(
                schema_name=physical_schema,
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
        """Return the next PRJ/CFV identifier for the selected database.

        PostgreSQL uses physical schemas ``prj_dbd`` and ``prj_stage``.  This
        bootstrap lookup is invoked before the Create modal can open, so query
        those physical tables explicitly instead of relying on ORM schema
        translation.  SQL Server keeps the established ORM path (dbo/stg).
        """
        bind = self.db.get_bind()
        values: list[str] = []
        if bind.dialect.name == "postgresql":
            inspector = inspect(bind)
            required = (
                ("prj_dbd", "raw_prj_attribute_new_test"),
                ("prj_stage", "prj_attribute_master_new_test"),
                ("prj_dbd", "prj_attribute_master_new_test"),
            )
            missing = [f"{schema}.{table}" for schema, table in required if not inspector.has_table(table, schema=schema)]
            if missing:
                raise RuntimeError(
                    "PostgreSQL Data Dictionary schema is not ready. Missing required table(s): "
                    + ", ".join(missing)
                    + ". Run the PostgreSQL setup/migration scripts and then 002_validate_schema.sql."
                )
            stmt = text(
                "SELECT prj_id FROM prj_dbd.raw_prj_attribute_new_test "
                "UNION ALL SELECT prj_id FROM prj_stage.prj_attribute_master_new_test "
                "UNION ALL SELECT prj_id FROM prj_dbd.prj_attribute_master_new_test"
            )
            values.extend(str(value) for value in self.db.scalars(stmt).all() if value)
        else:
            for model in (RawAttribute, StagingAttributeMaster, AttributeMaster):
                values.extend(str(row[0]) for row in self.db.execute(select(model.prj_id)).all() if row[0])

        maximum = 0
        for value in values:
            match = re.search(r"(\d+)$", value.strip(), flags=re.IGNORECASE)
            if match:
                maximum = max(maximum, int(match.group(1)))
        return f"PRJ{maximum + 1}"

    def existing_prj_ids(self) -> set[str]:
        values: set[str] = set()
        for model in (RawAttribute, StagingAttributeMaster, AttributeMaster):
            values.update(str(value) for value in self.db.scalars(select(model.prj_id)).all() if value and str(value).strip())
        return values

    def physical_name_exists(self, physical_name: str, exclude_prj_id: str | None = None) -> bool:
        wanted = physical_name.strip().casefold()
        if not wanted:
            return False
        for model in (RawAttribute, StagingAttributeMaster, AttributeMaster):
            stmt = select(model.prj_id).where(func.lower(model.prj_physical_attribute_name) == wanted)
            if exclude_prj_id:
                stmt = stmt.where(func.lower(model.prj_id) != str(exclude_prj_id).strip().casefold())
            if self.db.execute(stmt.limit(1)).first():
                return True
        return False

    def physical_name_for_prj(self, prj_id: str) -> str | None:
        wanted = str(prj_id).strip().casefold()
        for model in (StagingAttributeMaster, AttributeMaster, RawAttribute):
            stmt = select(model.prj_physical_attribute_name).where(func.lower(model.prj_id) == wanted)
            if model is RawAttribute:
                stmt = stmt.order_by(model.raw_row_id)
            value = self.db.execute(stmt.limit(1)).scalar_one_or_none()
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    def available_physical_name(self, base_name: str, exclude_prj_id: str | None = None) -> str:
        base = base_name.strip() or "attribute"
        if not self.physical_name_exists(base, exclude_prj_id=exclude_prj_id):
            return base
        for suffix in range(2, 10001):
            suffix_text = f"_{suffix}"
            candidate = f"{base[:500-len(suffix_text)]}{suffix_text}"
            if not self.physical_name_exists(candidate, exclude_prj_id=exclude_prj_id):
                return candidate
        raise ValueError(f"Could not generate a unique PRJ Physical Attribute Name from '{base}'.")

    def _source_table(self) -> Table | None:
        bind = self.db.get_bind()
        schema = self._physical_schema("dbo")
        cache_key = (id(bind), schema)
        if cache_key in self._source_table_cache:
            return self._source_table_cache[cache_key]
        inspector = inspect(bind)
        table: Table | None = None
        for name in ("prj_data_sources", "prj_data_source"):
            if inspector.has_table(name, schema=schema):
                table = Table(name, MetaData(), schema=schema, autoload_with=bind)
                break
        self._source_table_cache[cache_key] = table
        return table

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
        result = []
        for row in self.db.execute(select(*columns).order_by(table.c.source_name)).all():
            mapping = row._mapping
            result.append({
                "src_id": mapping.get(id_col.key) if id_col is not None else None,
                "source_code": mapping["source_code"],
                "source_name": mapping["source_name"],
            })
        return result

    def source_code(self, source_name: str | None, source_abbr_name: str | None = None) -> str:
        requested = str(source_abbr_name or "").strip()
        table = self._source_table()
        if requested:
            if requested.upper() == "SNPAR":
                return "SNPAR"
            if table is None or "source_code" not in table.c:
                return requested
            value = self.db.execute(select(table.c.source_code).where(table.c.source_code == requested).limit(1)).scalar_one_or_none()
            if value is None:
                raise ValueError(f"Unknown source code: {requested}")
            return str(value)
        if not source_name:
            return "SNPAR"
        if table is None or "source_code" not in table.c or "source_name" not in table.c:
            return "SNPAR"
        value = self.db.execute(select(table.c.source_code).where(table.c.source_name == source_name).limit(1)).scalar_one_or_none()
        if value is None:
            raise ValueError(f"Unknown source name: {source_name}")
        return str(value)

    def list_portfolios(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        portfolio_model = self.portfolio_model()
        stmt = select(portfolio_model)
        if not include_inactive:
            stmt = stmt.where(portfolio_model.is_active == true())
        stmt = stmt.order_by(portfolio_model.portfolio_name, portfolio_model.sector_name, portfolio_model.port_ref_id)
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in self.db.scalars(stmt).all():
            row = model_dict(item)
            pair = (str(row["portfolio_name"]).strip().lower(), str(row["sector_name"]).strip().lower())
            if pair in seen:
                continue
            seen.add(pair)
            row["label"] = portfolio_label(row["portfolio_name"], row["sector_name"])
            result.append(row)
        return result

    def portfolio_ref(self, portfolio: str) -> dict[str, Any] | None:
        wanted = canonical_portfolio_label(portfolio).lower()
        return next((row for row in self.list_portfolios(True) if str(row["label"]).lower() == wanted), None)

    @staticmethod
    def _master_model(schema: str):
        if schema == "dbo": return AttributeMaster
        if schema == "stg": return StagingAttributeMaster
        raise ValueError("Invalid schema")

    @staticmethod
    def _rule_model(schema: str):
        if schema == "dbo": return AttributeBusinessRule
        if schema == "stg": return StagingBusinessRule
        raise ValueError("Invalid schema")

    @staticmethod
    def _display_model(schema: str):
        if schema == "dbo": return AttributeDisplay
        if schema == "stg": return StagingAttributeDisplay
        raise ValueError("Invalid schema")

    def get_master(self, prj_id: str, schema: str = "dbo") -> dict[str, Any] | None:
        obj = self.db.get(self._master_model(schema), prj_id)
        return model_dict(obj) if obj else None

    def get_rules(self, prj_id: str, schema: str = "dbo") -> list[dict[str, Any]]:
        rule_model, display_model, master_model = self._rule_model(schema), self._display_model(schema), self._master_model(schema)
        portfolio_model = self.portfolio_model()
        stmt = (
            select(rule_model, display_model, portfolio_model, master_model.is_active)
            .join(display_model, display_model.scope_id == rule_model.scope_id)
            .join(portfolio_model, portfolio_model.port_ref_id == rule_model.port_ref_id)
            .join(master_model, master_model.prj_id == rule_model.prj_id)
            .where(rule_model.prj_id == prj_id)
            .order_by(rule_model.port_ref_id, display_model.display_order, rule_model.scope_id)
        )
        rows = []
        for rule, display, portfolio, active in self.db.execute(stmt).all():
            row = combined_rule_dict(rule, display, is_active=bool(active))
            row.update({
                "portfolio_name": portfolio.portfolio_name,
                "sector_name": portfolio.sector_name,
                "portfolio": portfolio_label(portfolio.portfolio_name, portfolio.sector_name),
            })
            rows.append(row)
        return rows

    def preload_state(self, prj_ids: set[str], schema: str = "dbo") -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        if not prj_ids:
            return {}, {}
        master_model, rule_model, display_model = self._master_model(schema), self._rule_model(schema), self._display_model(schema)
        master_objs = self.db.scalars(select(master_model).where(master_model.prj_id.in_(prj_ids))).all()
        masters = {item.prj_id: model_dict(item) for item in master_objs}
        active_by_prj = {item.prj_id: bool(item.is_active) for item in master_objs}
        rules: dict[str, list[dict[str, Any]]] = {key: [] for key in prj_ids}
        stmt = (
            select(rule_model, display_model)
            .join(display_model, display_model.scope_id == rule_model.scope_id)
            .where(rule_model.prj_id.in_(prj_ids))
            .order_by(rule_model.prj_id, rule_model.port_ref_id, display_model.display_order, rule_model.scope_id)
        )
        for rule, display in self.db.execute(stmt).all():
            rules.setdefault(rule.prj_id, []).append(combined_rule_dict(rule, display, is_active=active_by_prj.get(rule.prj_id, True)))
        return masters, rules

    def preload_final_state(self, prj_ids: set[str]):
        return self.preload_state(prj_ids, "dbo")

    def preload_original_mapping_types(self, prj_ids: set[str]) -> dict[str, str | None]:
        result = {prj_id: None for prj_id in prj_ids}
        if not prj_ids:
            return result
        for prj_id, value in self.db.execute(
            select(AttributeBusinessRule.prj_id, AttributeBusinessRule.attribute_type)
            .where(AttributeBusinessRule.prj_id.in_(prj_ids)).order_by(AttributeBusinessRule.prj_id, AttributeBusinessRule.scope_id)
        ).all():
            if result.get(prj_id) is None and str(value or "").strip().lower() != "repeated":
                result[prj_id] = str(value)
        unresolved = {key for key, value in result.items() if value is None}
        if unresolved:
            for prj_id, value in self.db.execute(
                select(RawAttribute.prj_id, RawAttribute.calculated_or_reported)
                .where(RawAttribute.prj_id.in_(unresolved)).order_by(RawAttribute.prj_id, RawAttribute.raw_row_id)
            ).all():
                if result.get(prj_id) is None and str(value or "").strip().lower() != "repeated":
                    result[prj_id] = str(value)
        return result

    def preload_physical_names(self) -> tuple[dict[str, str], dict[str, str]]:
        owners: dict[str, str] = {}; by_prj: dict[str, str] = {}
        for model in (StagingAttributeMaster, AttributeMaster, RawAttribute):
            stmt = select(model.prj_id, model.prj_physical_attribute_name)
            if model is RawAttribute: stmt = stmt.order_by(model.raw_row_id)
            for prj_id, value in self.db.execute(stmt).all():
                name = str(value or "").strip()
                if name:
                    owners.setdefault(name.casefold(), str(prj_id)); by_prj.setdefault(str(prj_id).strip().casefold(), name)
        return owners, by_prj

    def final_detail(self, prj_id: str) -> dict[str, Any] | None:
        master = self.get_master(prj_id, "dbo")
        if master: master["rules"] = self.get_rules(prj_id, "dbo")
        return master

    def working_detail(self, prj_id: str) -> dict[str, Any] | None:
        master = self.get_master(prj_id, "stg")
        if master:
            master["rules"] = self.get_rules(prj_id, "stg"); master["data_state"] = "STAGED"; return master
        master = self.final_detail(prj_id)
        if master: master["data_state"] = "FINAL"
        return master

    @staticmethod
    def _pipe_token_condition(column: Any, value: str):
        wanted = str(value or "").strip().lower(); lowered = func.lower(column)
        return or_(lowered == wanted, lowered.like(f"{wanted}|%"), lowered.like(f"%|{wanted}|%"), lowered.like(f"%|{wanted}"))

    def filter_final(self, filters: Any, page_size: int) -> dict[str, Any]:
        m, r, d, p = AttributeMaster, AttributeBusinessRule, AttributeDisplay, self.portfolio_model()
        conditions: list[Any] = []
        if not filters.include_deleted: conditions.append(m.is_active == true())
        if filters.prj_id: conditions.append(m.prj_id.ilike(f"%{filters.prj_id.strip()}%"))
        if filters.attribute_name: conditions.append(m.prj_attribute_name.ilike(f"%{filters.attribute_name.strip()}%"))
        if filters.attribute_definition:
            term = f"%{filters.attribute_definition.strip()}%"; conditions.append(or_(d.prj_attribute_definition.ilike(term), m.prj_attribute_definition.ilike(term)))
        if filters.section: conditions.append(self._pipe_token_condition(d.section, filters.section))
        if filters.subsection: conditions.append(self._pipe_token_condition(d.subsection, filters.subsection))
        if filters.portfolios:
            ids = [int(ref["port_ref_id"]) for x in filters.portfolios if (ref := self.portfolio_ref(x))]
            conditions.append(r.port_ref_id.in_(ids) if ids else m.prj_id == "__NO_MATCH__")
        if filters.sources:
            codes = [str(x).strip() for x in filters.sources if str(x).strip()]
            if codes: conditions.append(r.source_abbr_name.in_(codes))
        if filters.overlapped_only:
            scope_stmt = select(func.count(distinct(AttributeBusinessRule.port_ref_id))).where(AttributeBusinessRule.prj_id == m.prj_id)
            conditions.append(scope_stmt.correlate(m).scalar_subquery() > 1)
        if filters.search:
            term = f"%{filters.search.strip()}%"
            conditions.append(or_(
                m.prj_id.ilike(term), m.prj_attribute_name.ilike(term), m.prj_attribute_definition.ilike(term),
                d.prj_attribute_definition.ilike(term), d.prj_attribute_description.ilike(term), d.segment.ilike(term),
                d.report_type.ilike(term), d.section.ilike(term), d.subsection.ilike(term), r.source_abbr_name.ilike(term), d.display_name.ilike(term)
            ))
        count_stmt = select(func.count()).select_from(r).join(d, d.scope_id == r.scope_id).join(m, m.prj_id == r.prj_id).join(p, p.port_ref_id == r.port_ref_id)
        data_stmt = select(m, r, d, p).join(r, r.prj_id == m.prj_id).join(d, d.scope_id == r.scope_id).join(p, p.port_ref_id == r.port_ref_id)
        if conditions:
            pred = and_(*conditions); count_stmt = count_stmt.where(pred); data_stmt = data_stmt.where(pred)
        total = int(self.db.execute(count_stmt).scalar_one()); page = max(1, int(filters.page or 1))
        result_rows = self.db.execute(data_stmt.order_by(m.prj_id, d.display_order, r.scope_id).offset((page-1)*page_size).limit(page_size)).all()
        rows = []
        for master, rule, display, portfolio in result_rows:
            item = model_dict(master)
            c = combined_rule_dict(rule, display, is_active=bool(master.is_active))
            item.update(c)
            item.update({
                "portfolio": portfolio_label(portfolio.portfolio_name, portfolio.sector_name),
                "portfolios": portfolio_label(portfolio.portfolio_name, portfolio.sector_name),
                "sources": str(rule.source_abbr_name),
                "prj_attribute_definition": display.prj_attribute_definition or master.prj_attribute_definition,
                "where_in_financial_statement": display.segment or master.where_in_financial_statement,
                "rule_is_active": bool(master.is_active),
            })
            rows.append(item)
        return {"rows": rows, "total": total, "page": page, "page_size": page_size}

    def soft_deleted_rows(self) -> list[dict[str, Any]]:
        masters = list(self.db.scalars(select(AttributeMaster).where(AttributeMaster.is_active == false()).order_by(AttributeMaster.prj_id)).all())
        if not masters: return []
        prj_ids = [x.prj_id for x in masters]
        by_prj: dict[str, list[tuple[Any, Any, Any]]] = {x: [] for x in prj_ids}
        portfolio_model = self.portfolio_model()
        stmt = (select(AttributeBusinessRule, AttributeDisplay, portfolio_model)
                .join(AttributeDisplay, AttributeDisplay.scope_id == AttributeBusinessRule.scope_id)
                .join(portfolio_model, portfolio_model.port_ref_id == AttributeBusinessRule.port_ref_id)
                .where(AttributeBusinessRule.prj_id.in_(prj_ids))
                .order_by(AttributeBusinessRule.prj_id, AttributeBusinessRule.port_ref_id, AttributeDisplay.display_order))
        for rule, display, portfolio in self.db.execute(stmt).all(): by_prj.setdefault(rule.prj_id, []).append((rule, display, portfolio))
        rows=[]
        for master in masters:
            item=model_dict(master); pairs=by_prj.get(master.prj_id, [])
            if pairs:
                rule, display, _ = pairs[0]; item.update(combined_rule_dict(rule, display, is_active=False))
            item["portfolios"] = ", ".join(dict.fromkeys(portfolio_label(p.portfolio_name,p.sector_name) for _,_,p in pairs))
            item["sources"] = ", ".join(dict.fromkeys(str(r.source_abbr_name) for r,_,_ in pairs)); item["is_active"]=False; rows.append(item)
        return rows

    def active_final_prj_ids(self) -> set[str]:
        return {str(v) for v in self.db.scalars(select(AttributeMaster.prj_id).where(AttributeMaster.is_active == true())).all() if v is not None}

    def editable_rows(self, include_deleted: bool = True) -> list[dict[str, Any]]:
        portfolio_model = self.portfolio_model()
        stmt=(select(AttributeMaster,AttributeBusinessRule,AttributeDisplay,portfolio_model)
              .join(AttributeBusinessRule,AttributeBusinessRule.prj_id==AttributeMaster.prj_id)
              .join(AttributeDisplay,AttributeDisplay.scope_id==AttributeBusinessRule.scope_id)
              .join(portfolio_model,portfolio_model.port_ref_id==AttributeBusinessRule.port_ref_id))
        if not include_deleted: stmt=stmt.where(AttributeMaster.is_active==true())
        stmt=stmt.order_by(AttributeMaster.prj_id,AttributeBusinessRule.port_ref_id,AttributeDisplay.display_order)
        rows=[]
        for master,rule,display,portfolio in self.db.execute(stmt).all():
            rows.append({
                "scope_id":rule.scope_id,"display_id":display.display_id,"prj_id":master.prj_id,
                "portfolio":portfolio_label(portfolio.portfolio_name,portfolio.sector_name),"source_abbr_name":rule.source_abbr_name,
                "prj_attribute_name":master.prj_attribute_name,"prj_physical_attribute_name":master.prj_physical_attribute_name,
                "section":display.section,"sub_section":display.subsection,"data_type":rule.data_type,
                "calculated_or_reported":rule.attribute_type,"calculation_logic":rule.calculation_logic,
                "segment":display.segment or master.where_in_financial_statement,"report_type":display.report_type,
                "prj_attribute_definition":display.prj_attribute_definition or master.prj_attribute_definition,
                "attribute_description":display.prj_attribute_description,"tech_logic":rule.business_logic,
                "display_order":display.display_order,"display_name":display.display_name,"prompt_description":rule.prompt_description,
                "examples":rule.examples_for_llm,"is_active":bool(master.is_active),
            })
        return rows

    def lookup_values(self) -> dict[str, Any]:
        section_values=list(self.db.scalars(select(distinct(AttributeDisplay.section)).join(AttributeMaster,AttributeMaster.prj_id==AttributeDisplay.prj_id).where(AttributeMaster.is_active==true()).order_by(AttributeDisplay.section)).all())
        subsection_values=list(self.db.scalars(select(distinct(AttributeDisplay.subsection)).join(AttributeMaster,AttributeMaster.prj_id==AttributeDisplay.prj_id).where(AttributeMaster.is_active==true()).order_by(AttributeDisplay.subsection)).all())
        sections=sorted({x for v in section_values for x in split_pipe_values(v)},key=str.casefold); subsections=sorted({x for v in subsection_values for x in split_pipe_values(v)},key=str.casefold)
        return {"portfolios":self.list_portfolios(True),"sources":self.list_sources(),"sections":sections,"subsections":subsections}

    def original_mapping_type(self, prj_id: str) -> str | None:
        for value in self.db.scalars(select(AttributeBusinessRule.attribute_type).where(AttributeBusinessRule.prj_id==prj_id).order_by(AttributeBusinessRule.scope_id)).all():
            if str(value or "").strip().lower() != "repeated": return str(value)
        for value in self.db.scalars(select(RawAttribute.calculated_or_reported).where(RawAttribute.prj_id==prj_id).order_by(RawAttribute.raw_row_id)).all():
            if str(value or "").strip().lower() != "repeated": return str(value)
        return None

    def active_raw_for_scope(self, prj_id: str, portfolio: str) -> list[RawAttribute]:
        return list(self.db.scalars(select(RawAttribute).where(RawAttribute.prj_id==prj_id,RawAttribute.portfolio==portfolio,RawAttribute.is_active==true()).order_by(RawAttribute.raw_row_id)).all())

    def preload_pending_objects(self, prj_ids: set[str]) -> dict[str, Any]:
        raw_by_scope: dict[tuple[str,str],list[RawAttribute]]={}; masters:dict[str,StagingAttributeMaster]={}; rules_by_scope:dict[tuple[str,int],list[tuple[StagingBusinessRule,StagingAttributeDisplay]]]={}
        if not prj_ids:return {"raw":raw_by_scope,"masters":masters,"rules":rules_by_scope}
        for item in self.db.scalars(select(RawAttribute).where(RawAttribute.prj_id.in_(prj_ids),RawAttribute.is_active==true()).order_by(RawAttribute.prj_id,RawAttribute.portfolio,RawAttribute.raw_row_id)).all(): raw_by_scope.setdefault((str(item.prj_id),str(item.portfolio)),[]).append(item)
        for item in self.db.scalars(select(StagingAttributeMaster).where(StagingAttributeMaster.prj_id.in_(prj_ids))).all(): masters[str(item.prj_id)]=item
        stmt=(select(StagingBusinessRule,StagingAttributeDisplay).join(StagingAttributeDisplay,StagingAttributeDisplay.scope_id==StagingBusinessRule.scope_id).where(StagingBusinessRule.prj_id.in_(prj_ids)).order_by(StagingBusinessRule.prj_id,StagingBusinessRule.port_ref_id,StagingAttributeDisplay.display_order,StagingBusinessRule.scope_id))
        for rule,display in self.db.execute(stmt).all(): rules_by_scope.setdefault((str(rule.prj_id),int(rule.port_ref_id)),[]).append((rule,display))
        return {"raw":raw_by_scope,"masters":masters,"rules":rules_by_scope}

    @staticmethod
    def _combined_key_match(rule: Any, display: Any, row: dict[str, Any]) -> bool:
        return (rule.source_abbr_name==row["source_abbr_name"] and int(display.display_order)==int(row["display_order"])
                and display.section==row["section"] and display.subsection==row["subsection"] and display.report_type==row.get("report_type","NA"))

    @staticmethod
    def _assign_business(rule: Any, row: dict[str, Any]) -> None:
        for incoming, physical in BUSINESS_INPUT_MAP.items(): setattr(rule,physical,row.get(incoming))

    @staticmethod
    def _assign_display(display: Any, row: dict[str, Any]) -> None:
        for incoming, physical in DISPLAY_INPUT_MAP.items(): setattr(display,physical,row.get(incoming))

    def upsert_raw_cached(self, row, user, source_operation, cache, strict_key: bool = False):
        key=(str(row["prj_id"]),str(row["portfolio"])); existing=cache.setdefault(key,[])
        target=next((x for x in existing if int(x.display_order)==int(row["display_order"]) and x.section==row["section"] and x.sub_section==row["sub_section"] and x.report_type==row.get("report_type","NA")),None)
        if target is None and len(existing)==1 and not strict_key and not source_operation.upper().startswith("BULK_"):target=existing[0]
        if target is None and len(existing)>1 and not strict_key and not source_operation.upper().startswith("BULK_"):raise ValueError(f"Cannot unambiguously update raw row for {row['prj_id']} / {row['portfolio']}; multiple raw rows exist and the edited key no longer matches.")
        if target:
            before=model_dict(target)
            for field,value in row.items():setattr(target,field,value)
            target.is_active=True;target.updated_at=datetime.utcnow();target.updated_by=user
            if target.raw_row_id is not None:self.audit("dbo","raw_prj_attribute_new_test",str(target.raw_row_id),"UPDATE",before,model_dict(target),user,source_operation)
            return None
        target=RawAttribute(**row,is_active=True,created_by=user,updated_by=user);self.db.add(target);existing.append(target)
        return {"schema":"dbo","table":"raw_prj_attribute_new_test","target":target,"key_attr":"raw_row_id","user":user,"source_operation":source_operation}

    def upsert_staging_master_cached(self,row,user,source_operation,cache):
        target=cache.get(str(row["prj_id"]));fields=("prj_attribute_name","prj_attribute_definition","prj_physical_attribute_name","where_in_financial_statement","is_active")
        if target:
            before=model_dict(target)
            for f in fields:setattr(target,f,row.get(f))
            target.updated_at=datetime.utcnow();target.updated_by=user;self.audit("stg","prj_attribute_master_new_test",str(row["prj_id"]),"UPDATE",before,model_dict(target),user,source_operation);return
        target=StagingAttributeMaster(**{f:row.get(f) for f in ("prj_id",*fields)},created_by=user,updated_by=user);self.db.add(target);cache[str(row["prj_id"])]=target;self.audit("stg","prj_attribute_master_new_test",str(row["prj_id"]),"INSERT",None,model_dict(target),user,source_operation)

    def _new_staging_pair(self,row,user):
        rule=StagingBusinessRule(created_by=user,updated_by=user);self._assign_business(rule,row)
        display=StagingAttributeDisplay(created_by=user,updated_by=user);self._assign_display(display,row);rule.display=display
        return rule,display

    def upsert_staging_rule_cached(self, row, user, source_operation, cache, strict_key: bool = False):
        key=(str(row["prj_id"]),int(row["port_ref_id"]));existing=cache.setdefault(key,[])
        pair=next(((r,d) for r,d in existing if self._combined_key_match(r,d,row)),None)
        if pair is None and len(existing)==1 and not strict_key and not source_operation.upper().startswith("BULK_"):pair=existing[0]
        if pair is None and len(existing)>1 and not strict_key and not source_operation.upper().startswith("BULK_"):raise ValueError(f"Cannot unambiguously update staging rule for {row['prj_id']} / port_ref_id {row['port_ref_id']}; multiple staged rules exist and the edited key no longer matches.")
        if pair:
            rule,display=pair;before_rule=model_dict(rule);before_display=model_dict(display);self._assign_business(rule,row);self._assign_display(display,row);now=datetime.utcnow();rule.updated_at=display.updated_at=now;rule.updated_by=display.updated_by=user
            if rule.scope_id is not None:
                self.audit("stg","prj_attribute_business_rules_new_test",str(rule.scope_id),"UPDATE",before_rule,model_dict(rule),user,source_operation)
                self.audit("stg","prj_attribute_display_test",str(display.display_id),"UPDATE",before_display,model_dict(display),user,source_operation)
            return None
        rule,display=self._new_staging_pair(row,user);self.db.add(rule);existing.append((rule,display))
        return {"targets":[
            {"schema":"stg","table":"prj_attribute_business_rules_new_test","target":rule,"key_attr":"scope_id"},
            {"schema":"stg","table":"prj_attribute_display_test","target":display,"key_attr":"display_id"},
        ],"user":user,"source_operation":source_operation}

    def upsert_raw(self, row, user, source_operation, defer_insert_audit=False, strict_key: bool = False):
        existing=self.active_raw_for_scope(row["prj_id"],row["portfolio"]);target=next((x for x in existing if int(x.display_order)==int(row["display_order"]) and x.section==row["section"] and x.sub_section==row["sub_section"] and x.report_type==row.get("report_type","NA")),None)
        if target is None and len(existing)==1 and not strict_key and not source_operation.upper().startswith("BULK_"):target=existing[0]
        if target is None and len(existing)>1 and not strict_key and not source_operation.upper().startswith("BULK_"):raise ValueError(f"Cannot unambiguously update raw row for {row['prj_id']} / {row['portfolio']}; multiple raw rows exist and the edited key no longer matches.")
        if target:
            before=model_dict(target)
            for k,v in row.items():setattr(target,k,v)
            target.is_active=True;target.updated_at=datetime.utcnow();target.updated_by=user;self.audit("dbo","raw_prj_attribute_new_test",str(target.raw_row_id),"UPDATE",before,model_dict(target),user,source_operation);return None
        target=RawAttribute(**row,is_active=True,created_by=user,updated_by=user);self.db.add(target)
        if defer_insert_audit:return {"schema":"dbo","table":"raw_prj_attribute_new_test","target":target,"key_attr":"raw_row_id","user":user,"source_operation":source_operation}
        self.db.flush();self.audit("dbo","raw_prj_attribute_new_test",str(target.raw_row_id),"INSERT",None,model_dict(target),user,source_operation);return None

    def upsert_staging_master(self,row,user,source_operation):
        target=self.db.get(StagingAttributeMaster,row["prj_id"]);fields=("prj_attribute_name","prj_attribute_definition","prj_physical_attribute_name","where_in_financial_statement","is_active")
        if target:
            before=model_dict(target)
            for k in fields:setattr(target,k,row.get(k))
            target.updated_at=datetime.utcnow();target.updated_by=user;self.audit("stg","prj_attribute_master_new_test",row["prj_id"],"UPDATE",before,model_dict(target),user,source_operation)
        else:
            target=StagingAttributeMaster(**{k:row[k] for k in ("prj_id",*fields)},created_by=user,updated_by=user);self.db.add(target);self.audit("stg","prj_attribute_master_new_test",row["prj_id"],"INSERT",None,model_dict(target),user,source_operation)

    def upsert_staging_rule(self, row, user, source_operation, defer_insert_audit=False, strict_key: bool = False):
        stmt=(select(StagingBusinessRule,StagingAttributeDisplay).join(StagingAttributeDisplay,StagingAttributeDisplay.scope_id==StagingBusinessRule.scope_id).where(StagingBusinessRule.prj_id==row["prj_id"],StagingBusinessRule.port_ref_id==row["port_ref_id"]).order_by(StagingBusinessRule.scope_id))
        existing=list(self.db.execute(stmt).all());pair=next(((r,d) for r,d in existing if self._combined_key_match(r,d,row)),None)
        if pair is None and len(existing)==1 and not strict_key and not source_operation.upper().startswith("BULK_"):pair=existing[0]
        if pair is None and len(existing)>1 and not strict_key and not source_operation.upper().startswith("BULK_"):raise ValueError(f"Cannot unambiguously update staging rule for {row['prj_id']} / port_ref_id {row['port_ref_id']}; multiple staged rules exist and the edited key no longer matches.")
        if pair:
            rule,display=pair;before_rule=model_dict(rule);before_display=model_dict(display);self._assign_business(rule,row);self._assign_display(display,row);now=datetime.utcnow();rule.updated_at=display.updated_at=now;rule.updated_by=display.updated_by=user
            self.audit("stg","prj_attribute_business_rules_new_test",str(rule.scope_id),"UPDATE",before_rule,model_dict(rule),user,source_operation);self.audit("stg","prj_attribute_display_test",str(display.display_id),"UPDATE",before_display,model_dict(display),user,source_operation);return None
        rule,display=self._new_staging_pair(row,user);self.db.add(rule)
        if defer_insert_audit:return {"targets":[{"schema":"stg","table":"prj_attribute_business_rules_new_test","target":rule,"key_attr":"scope_id"},{"schema":"stg","table":"prj_attribute_display_test","target":display,"key_attr":"display_id"}],"user":user,"source_operation":source_operation}
        self.db.flush();self.audit("stg","prj_attribute_business_rules_new_test",str(rule.scope_id),"INSERT",None,model_dict(rule),user,source_operation);self.audit("stg","prj_attribute_display_test",str(display.display_id),"INSERT",None,model_dict(display),user,source_operation);return None

    def emit_deferred_insert_audits(self,items):
        if not items:return
        self.db.flush()
        for item in items:
            targets=item.get("targets") or [{"schema":item["schema"],"table":item["table"],"target":item["target"],"key_attr":item["key_attr"]}]
            for entry in targets:self.audit(entry["schema"],entry["table"],str(getattr(entry["target"],entry["key_attr"])),"INSERT",None,model_dict(entry["target"]),item["user"],item["source_operation"])

    def stage_delete_attribute(self,prj_id,active,user,source_operation):
        base=self.get_master(prj_id,"stg") or self.get_master(prj_id,"dbo")
        if not base:raise KeyError(prj_id)
        self.upsert_staging_master({"prj_id":base["prj_id"],"prj_attribute_name":base["prj_attribute_name"],"prj_attribute_definition":base.get("prj_attribute_definition"),"prj_physical_attribute_name":base["prj_physical_attribute_name"],"where_in_financial_statement":base.get("where_in_financial_statement") or "NA","is_active":bool(active)},user,source_operation)
        rules=self.get_rules(prj_id,"stg") or self.get_rules(prj_id,"dbo")
        keys=("prj_id","port_ref_id","source_abbr_name","editable","symbol","mapping_type","calculation_logic","prj_attribute_definition","prj_attribute_description","segment","report_type","tech_logic","display_order","display_name","section","subsection","prompt_description","examples")
        for item in rules:self.upsert_staging_rule({k:item.get(k) for k in keys},user,source_operation)
        for raw in self.db.scalars(select(RawAttribute).where(RawAttribute.prj_id==prj_id)).all():
            before=model_dict(raw);raw.is_active=bool(active);raw.updated_at=datetime.utcnow();raw.updated_by=user;self.audit("dbo","raw_prj_attribute_new_test",str(raw.raw_row_id),"REACTIVATE" if active else "SOFT_DELETE",before,model_dict(raw),user,source_operation)

    def staging_prj_ids(self):return list(self.db.scalars(select(StagingAttributeMaster.prj_id).order_by(StagingAttributeMaster.prj_id)).all())

    def clear_staging(self,prj_ids=None):
        if prj_ids:
            scope_ids=select(StagingBusinessRule.scope_id).where(StagingBusinessRule.prj_id.in_(prj_ids));self.db.execute(delete(StagingAttributeDisplay).where(StagingAttributeDisplay.scope_id.in_(scope_ids)));self.db.execute(delete(StagingBusinessRule).where(StagingBusinessRule.prj_id.in_(prj_ids)));self.db.execute(delete(StagingAttributeMaster).where(StagingAttributeMaster.prj_id.in_(prj_ids)))
        else:self.db.execute(delete(StagingAttributeDisplay));self.db.execute(delete(StagingBusinessRule));self.db.execute(delete(StagingAttributeMaster))

    def clear_raw_and_staging_for_replace(self,user):
        raw_count=int(self.db.execute(select(func.count()).select_from(RawAttribute)).scalar_one());stg_count=int(self.db.execute(select(func.count()).select_from(StagingAttributeMaster)).scalar_one());self.audit("dbo","raw_prj_attribute_new_test","*","REPLACE_CLEAR",{"row_count":raw_count},None,user,"BULK_REPLACE");self.audit("stg","prj_attribute_master_new_test","*","REPLACE_CLEAR",{"row_count":stg_count},None,user,"BULK_REPLACE");self.db.execute(delete(StagingAttributeDisplay));self.db.execute(delete(StagingBusinessRule));self.db.execute(delete(StagingAttributeMaster));self.db.execute(delete(RawAttribute))

    def audit_rows(self,filters,limit=2000):
        stmt=select(AuditTable);conditions=[]
        for field in ("table_name","record_key","action","performed_by","source_operation"):
            value=getattr(filters,field,None)
            if value:conditions.append(getattr(AuditTable,field).ilike(f"%{value}%"))
        if getattr(filters,"search",None):
            term=f"%{filters.search}%";conditions.append(or_(AuditTable.table_name.ilike(term),AuditTable.record_key.ilike(term),AuditTable.before_value.ilike(term),AuditTable.after_value.ilike(term)))
        if conditions:stmt=stmt.where(and_(*conditions))
        stmt=stmt.order_by(AuditTable.performed_at.desc(),AuditTable.audit_id.desc()).limit(limit);return [model_dict(x) for x in self.db.scalars(stmt).all()]
