"""SQLAlchemy entities shared by SQL Server and PostgreSQL.

Logical ORM schemas remain ``dbo`` (main) and ``stg`` (staging).  PostgreSQL
translates them at engine level to ``prj_dbd`` and ``prj_stage`` respectively.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from DataDictionaryAdminApp.core.database import Base


class ChangeColumns:
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="sysuser")
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False, default="sysuser")


class AuditColumns(ChangeColumns):
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RawAttribute(Base, AuditColumns):
    __tablename__ = "raw_prj_attribute_new_test"
    __table_args__ = {"schema": "dbo"}
    raw_row_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio: Mapped[str] = mapped_column(String(120), nullable=False)
    prj_id: Mapped[str] = mapped_column(String(80), nullable=False)
    prj_attribute_name: Mapped[str] = mapped_column(String(500), nullable=False)
    prj_physical_attribute_name: Mapped[str] = mapped_column(String(500), nullable=False)
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    sub_section: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[str | None] = mapped_column(String(100))
    calculated_or_reported: Mapped[str] = mapped_column(String(50), nullable=False)
    calculation_logic: Mapped[str] = mapped_column(Text, nullable=False, default="NA")
    segment: Mapped[str] = mapped_column(String(255), nullable=False, default="NA")
    report_type: Mapped[str] = mapped_column(String(120), nullable=False, default="NA")
    attribute_definition: Mapped[str | None] = mapped_column(Text)
    attribute_description: Mapped[str | None] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    tech_logic: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(500))


class PortfolioReference(Base, AuditColumns):
    __tablename__ = "prj_portfolio_reference_new_test"
    __table_args__ = (
        UniqueConstraint("portfolio_name", "sector_name", "sub_sector", name="uq_new_portfolio_reference"),
        {"schema": "dbo"},
    )
    port_ref_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sector_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sub_sector: Mapped[str | None] = mapped_column(String(120))
    remark: Mapped[str | None] = mapped_column(String(500))


class PostgresPortfolioReference(Base, AuditColumns):
    """PostgreSQL portfolio reference uses the established physical table name.

    SQL Server retains dbo.prj_portfolio_reference_new_test. PostgreSQL uses
    prj_dbd.prj_portfolio_reference exactly; repository code selects this model
    only for PostgreSQL connections.
    """
    __tablename__ = "prj_portfolio_reference"
    __table_args__ = (
        UniqueConstraint("portfolio_name", "sector_name", "sub_sector", name="uq_pg_portfolio_reference"),
        {"schema": "prj_dbd"},
    )
    port_ref_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sector_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sub_sector: Mapped[str | None] = mapped_column(String(120))
    remark: Mapped[str | None] = mapped_column(String(500))


class StagingAttributeMaster(Base, AuditColumns):
    __tablename__ = "prj_attribute_master_new_test"
    __table_args__ = {"schema": "stg"}
    prj_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    prj_attribute_name: Mapped[str] = mapped_column(String(500), nullable=False)
    prj_attribute_definition: Mapped[str | None] = mapped_column(Text)
    prj_physical_attribute_name: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    where_in_financial_statement: Mapped[str] = mapped_column(String(255), nullable=False, default="NA")


class StagingBusinessRule(Base, ChangeColumns):
    """Business/LLM rule data. Display metadata lives in StagingAttributeDisplay."""
    __tablename__ = "prj_attribute_business_rules_new_test"
    __table_args__ = {"schema": "stg"}

    scope_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prj_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("stg.prj_attribute_master_new_test.prj_id"), nullable=False
    )
    port_ref_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dbo.prj_portfolio_reference_new_test.port_ref_id"), nullable=False
    )
    source_abbr_name: Mapped[str] = mapped_column(String(50), nullable=False, default="SNPAR")
    prompt_description: Mapped[str | None] = mapped_column(Text)
    examples_for_llm: Mapped[str | None] = mapped_column(Text)
    editable: Mapped[str] = mapped_column(String(1), nullable=False)
    data_type: Mapped[str | None] = mapped_column(String(50))
    attribute_type: Mapped[str] = mapped_column(String(50), nullable=False)
    business_logic: Mapped[str | None] = mapped_column(Text)
    calculation_logic: Mapped[str] = mapped_column(Text, nullable=False, default="NA")

    # Backward-compatible Python aliases used by existing service/API code.
    symbol = synonym("data_type")
    mapping_type = synonym("attribute_type")
    tech_logic = synonym("business_logic")
    examples = synonym("examples_for_llm")

    display: Mapped["StagingAttributeDisplay"] = relationship(
        "StagingAttributeDisplay", back_populates="scope", uselist=False, cascade="all, delete-orphan"
    )


class StagingAttributeDisplay(Base, ChangeColumns):
    __tablename__ = "prj_attribute_display_test"
    __table_args__ = (
        UniqueConstraint("scope_id", name="uq_stg_attribute_display_scope"),
        {"schema": "stg"},
    )
    display_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("stg.prj_attribute_business_rules_new_test.scope_id", ondelete="CASCADE"),
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    prj_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("stg.prj_attribute_master_new_test.prj_id"), nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(500))
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    subsection: Mapped[str] = mapped_column(String(255), nullable=False)

    # Existing scope-specific fields are retained here so prior functionality is
    # not lost by the business/display split.
    prj_attribute_definition: Mapped[str | None] = mapped_column(Text)
    prj_attribute_description: Mapped[str | None] = mapped_column(Text)
    segment: Mapped[str] = mapped_column(String(255), nullable=False, default="NA")
    report_type: Mapped[str] = mapped_column(String(120), nullable=False, default="NA")

    scope: Mapped[StagingBusinessRule] = relationship("StagingBusinessRule", back_populates="display")


class AttributeMaster(Base, AuditColumns):
    __tablename__ = "prj_attribute_master_new_test"
    __table_args__ = {"schema": "dbo"}
    prj_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    prj_attribute_name: Mapped[str] = mapped_column(String(500), nullable=False)
    prj_attribute_definition: Mapped[str | None] = mapped_column(Text)
    prj_physical_attribute_name: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    where_in_financial_statement: Mapped[str] = mapped_column(String(255), nullable=False, default="NA")


class AttributeBusinessRule(Base, ChangeColumns):
    """Final business/LLM rule data. Display metadata lives in AttributeDisplay."""
    __tablename__ = "prj_attribute_business_rules_new_test"
    __table_args__ = {"schema": "dbo"}

    scope_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prj_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("dbo.prj_attribute_master_new_test.prj_id"), nullable=False
    )
    port_ref_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dbo.prj_portfolio_reference_new_test.port_ref_id"), nullable=False
    )
    source_abbr_name: Mapped[str] = mapped_column(String(50), nullable=False, default="SNPAR")
    prompt_description: Mapped[str | None] = mapped_column(Text)
    examples_for_llm: Mapped[str | None] = mapped_column(Text)
    editable: Mapped[str] = mapped_column(String(1), nullable=False)
    data_type: Mapped[str | None] = mapped_column(String(50))
    attribute_type: Mapped[str] = mapped_column(String(50), nullable=False)
    business_logic: Mapped[str | None] = mapped_column(Text)
    calculation_logic: Mapped[str] = mapped_column(Text, nullable=False, default="NA")

    symbol = synonym("data_type")
    mapping_type = synonym("attribute_type")
    tech_logic = synonym("business_logic")
    examples = synonym("examples_for_llm")

    display: Mapped["AttributeDisplay"] = relationship(
        "AttributeDisplay", back_populates="scope", uselist=False, cascade="all, delete-orphan"
    )


class AttributeDisplay(Base, ChangeColumns):
    __tablename__ = "prj_attribute_display_test"
    __table_args__ = (
        UniqueConstraint("scope_id", name="uq_attribute_display_scope"),
        {"schema": "dbo"},
    )
    display_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("dbo.prj_attribute_business_rules_new_test.scope_id", ondelete="CASCADE"),
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    prj_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("dbo.prj_attribute_master_new_test.prj_id"), nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(500))
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    subsection: Mapped[str] = mapped_column(String(255), nullable=False)

    prj_attribute_definition: Mapped[str | None] = mapped_column(Text)
    prj_attribute_description: Mapped[str | None] = mapped_column(Text)
    segment: Mapped[str] = mapped_column(String(255), nullable=False, default="NA")
    report_type: Mapped[str] = mapped_column(String(120), nullable=False, default="NA")

    scope: Mapped[AttributeBusinessRule] = relationship("AttributeBusinessRule", back_populates="display")


class AuditTable(Base):
    __tablename__ = "audit_table_new_test"
    __table_args__ = {"schema": "dbo"}
    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    record_key: Mapped[str] = mapped_column(String(500), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    before_value: Mapped[str | None] = mapped_column(Text)
    after_value: Mapped[str | None] = mapped_column(Text)
    source_operation: Mapped[str | None] = mapped_column(String(100))
    performed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
