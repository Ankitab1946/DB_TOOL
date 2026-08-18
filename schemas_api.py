from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from DataDictionaryAdminApp.utils.normalizers import normalize_pipe_values


class AttributeUpsert(BaseModel):
    prj_id: str | None = None
    portfolio: str
    source_name: str | None = None
    source_abbr_name: str | None = None
    prj_attribute_name: str
    prj_physical_attribute_name: str | None = None
    physical_name_source: str | None = None
    section: str
    sub_section: str
    data_type: str | None = None
    calculated_or_reported: str
    calculation_logic: str = "NA"
    segment: str = "NA"
    attribute_definition: str | None = None
    attribute_description: str | None = None
    display_order: int
    tech_logic: str | None = None
    display_name: str | None = None
    prompt_description: str | None = None
    examples: str | None = None
    is_active: bool = True

    @field_validator("portfolio", "prj_attribute_name", "calculated_or_reported")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field cannot be blank")
        return value

    @field_validator("section", "sub_section")
    @classmethod
    def pipe_separated_text(cls, value: str) -> str:
        value = normalize_pipe_values(value)
        if not value:
            raise ValueError("field cannot be blank")
        return value


class AttributeBatchRequest(BaseModel):
    rows: list[AttributeUpsert] = Field(default_factory=list)


class FilterRequest(BaseModel):
    portfolios: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    prj_id: str | None = None
    attribute_name: str | None = None
    attribute_definition: str | None = None
    section: str | None = None
    subsection: str | None = None
    search: str | None = None
    overlapped_only: bool = False
    include_deleted: bool = False
    page: int = 1
    page_size: int | None = None


class AuditFilterRequest(BaseModel):
    table_name: str | None = None
    record_key: str | None = None
    action: str | None = None
    performed_by: str | None = None
    source_operation: str | None = None
    search: str | None = None


class PortfolioUpsert(BaseModel):
    portfolio_name: str
    sector_name: str
    sub_sector: str | None = None
    remark: str | None = None


class PromptUpsert(BaseModel):
    scope_id: int
    prompt_description: str | None = None
    examples: str | None = None


class FinalizeRequest(BaseModel):
    confirm: bool = False


class CleanupRequest(BaseModel):
    first_confirmation: bool = False
    second_confirmation: bool = False
    confirmation_text: str = ""
