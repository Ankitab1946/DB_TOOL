"""Streamlit UI. All database operations are performed through the FastAPI layer."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st
from streamlit_modal import Modal

from DataDictionaryAdminApp.service.excel_service import STANDARD_FIELDS
from DataDictionaryAdminApp.utils.normalizers import generate_physical_name, generate_tech_logic


def load_env() -> None:
    candidates = [Path.cwd() / ".env", *[parent / ".env" for parent in Path(__file__).resolve().parents]]
    for path in candidates:
        if path.exists():
            for raw in path.read_text(encoding="utf-8").splitlines():
                raw = raw.strip()
                if raw and not raw.startswith("#") and "=" in raw:
                    key, value = raw.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            break


load_env()
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8503/api/v1").rstrip("/")
API = API_BASE if API_BASE.endswith("/api/v1") else API_BASE + "/api/v1"
READ_TIMEOUT = int(os.getenv("API_READ_TIMEOUT_SECONDS", "120"))
WRITE_TIMEOUT = int(os.getenv("API_WRITE_TIMEOUT_SECONDS", "600"))
CURRENT_USER = os.getenv("USERNAME") or os.getenv("USER") or os.getenv("DEFAULT_USER", "sysuser")
HTTP = requests.Session()

st.set_page_config(page_title="PRJ Data Dictionary Administration Platform", page_icon="📚", layout="wide")
st.markdown(
    """
<style>
.stApp { background:#f8fafc; }
.block-container { padding-top:1rem; max-width:1700px; }
.dd-hero { padding:1rem 1.2rem; background:#eaf2fb; border:1px solid #b7c9db; border-radius:8px; margin-bottom:1rem; }
.dd-hero h1 { margin:0; font-size:1.55rem; color:#24486f; }
.dd-hero p { margin:.25rem 0 0; color:#52677e; }
[data-testid="stSidebar"] { background:#f0f5fa; border-right:1px solid #c6d6e5; }
.stTabs [data-baseweb="tab"] { background:#f0f5fa; border:1px solid #c6d6e5; border-radius:6px; padding:0 .9rem; }
.stTabs [aria-selected="true"] { background:#dceafa !important; border-color:#86a7c8 !important; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border:1px solid #c6d6e5; border-radius:6px; overflow:hidden; }
.small-note { color:#5b6f84; font-size:.84rem; }
</style>
""",
    unsafe_allow_html=True,
)
st.markdown(
    """
<div class="dd-hero">
  <h1>PRJ Data Dictionary Administration Platform</h1>
  <p>Raw → staging → final governance, multi-sheet ingestion, prompt maintenance, audit history and S3 export.</p>
</div>
""",
    unsafe_allow_html=True,
)


def headers() -> dict[str, str]:
    return {
        "X-App-Environment": st.session_state.get("environment", os.getenv("SELECTED_ENVIRONMENT", "LOCAL")),
        "X-DB-Type": st.session_state.get("database_type", os.getenv("SELECTED_DB_TYPE", "SQLSERVER")),
        "X-App-User": CURRENT_USER,
        "X-App-Role": st.session_state.get("role", os.getenv("SELECTED_ROLE", "ADMIN")).upper(),
        "Accept": "application/json",
    }


def api(method: str, path: str, *, quiet: bool = False, binary: bool = False, **kwargs):
    timeout = READ_TIMEOUT if method.upper() == "GET" else WRITE_TIMEOUT
    try:
        response = HTTP.request(method, API + path, headers=headers(), timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        if not quiet:
            st.error(f"API connection failed: {exc}")
        return None
    if not response.ok:
        if not quiet:
            try:
                detail = response.json().get("detail", response.json())
            except Exception:
                detail = response.text
            st.error(f"API error {response.status_code}: {detail}")
        return None
    return response if binary else response.json()


for key, default in {
    "environment": os.getenv("SELECTED_ENVIRONMENT", "LOCAL"),
    "database_type": os.getenv("SELECTED_DB_TYPE", "SQLSERVER").upper(),
    "role": os.getenv("SELECTED_ROLE", "ADMIN").upper(),
    "view_rows": [],
    "view_total": 0,
    "selected_prj": "",
    "upload_preview": None,
    "upload_configs": [],
    "latest_excel": None,
    "show_create": False,
    "show_edit": False,
    "edit_unlocked": False,
    "show_finalize_confirm": False,
}.items():
    st.session_state.setdefault(key, default)

context = api("GET", "/system/context", quiet=True) or {
    "environment": st.session_state["environment"],
    "environments": ["LOCAL", "DEV", "UAT", "PROD"],
    "db_type": st.session_state["database_type"],
    "db_types": ["SQLSERVER", "POSTGRES"],
    "database": "Unknown",
    "server": "Unknown",
    "current_user": CURRENT_USER,
    "role": st.session_state.get("role", "ADMIN"),
    "is_admin": st.session_state.get("role", "ADMIN") == "ADMIN",
}

with st.sidebar:
    st.subheader("Runtime Context")
    environments = context.get("environments") or ["LOCAL"]
    current_env = st.session_state.get("environment", environments[0])
    if current_env not in environments:
        current_env = environments[0]
    selected_env = st.selectbox("Environment", environments, index=environments.index(current_env))
    if selected_env != st.session_state.get("environment"):
        st.session_state["environment"] = selected_env
        st.rerun()

    # Always expose both supported database engines. Whether an engine is enabled
    # for the selected environment is shown below without removing the selector.
    db_types = ["SQLSERVER", "POSTGRES"]
    db_labels = {"SQLSERVER": "SQL Server", "POSTGRES": "PostgreSQL"}
    current_db_type = st.session_state.get("database_type", "SQLSERVER").upper()
    if current_db_type not in db_types:
        current_db_type = "SQLSERVER"
    selected_db_type = st.selectbox(
        "Database Type",
        db_types,
        index=db_types.index(current_db_type),
        format_func=lambda value: db_labels[value],
    )
    if selected_db_type != st.session_state.get("database_type"):
        st.session_state["database_type"] = selected_db_type
        st.rerun()

    roles = ["ADMIN", "USER"]
    current_role = st.session_state.get("role", "ADMIN").upper()
    if current_role not in roles:
        current_role = "ADMIN"
    selected_role = st.selectbox(
        "Application Role",
        roles,
        index=roles.index(current_role),
        format_func=lambda value: "Admin" if value == "ADMIN" else "User",
    )
    if selected_role != st.session_state.get("role"):
        st.session_state["role"] = selected_role
        st.rerun()

    refreshed = api("GET", "/system/context", quiet=True) or context
    st.text_input("Database", value=str(refreshed.get("database", "Unknown")), disabled=True)
    st.text_input("Server", value=str(refreshed.get("server", "Unknown")), disabled=True)
    st.text_input("Current User", value=str(refreshed.get("current_user", CURRENT_USER)), disabled=True)
    st.text_input("Access", value=str(refreshed.get("role", st.session_state.get("role", "USER"))), disabled=True)
    if not refreshed.get("database_enabled", False):
        st.warning("Database access is disabled for this environment.")

lookups = api("GET", "/lookups", quiet=True) or {"portfolios": [], "sources": [], "sections": [], "subsections": []}
portfolio_labels = [item.get("label") for item in lookups.get("portfolios", []) if item.get("label")]
source_options = [item.get("source_code") for item in lookups.get("sources", []) if item.get("source_code")]
source_names = [item.get("source_name") for item in lookups.get("sources", []) if item.get("source_name")]
source_by_code = {item.get("source_code"): item.get("source_name") for item in lookups.get("sources", [])}

create_modal = Modal("Create New Attribute", key="create_attribute_modal", max_width=1050)
edit_modal = Modal("Edit Attribute", key="edit_attribute_modal", max_width=1050)
finalize_modal = Modal("Finalize and Upload", key="finalize_modal", max_width=720)


def attribute_form(prefix: str, detail: dict[str, Any] | None = None, locked: bool = False) -> dict[str, Any] | None:
    detail = detail or {}
    rules = detail.get("rules") or []
    rule_index = 0
    if rules:
        labels = [f"{r.get('portfolio')} | {r.get('source_abbr_name')} | {r.get('section')} / {r.get('subsection')}" for r in rules]
        selected = st.selectbox("Portfolio / Scope record", range(len(rules)), format_func=lambda i: labels[i], key=f"{prefix}_rule")
        rule_index = int(selected)
    rule = rules[rule_index] if rules else {}

    next_id = api("GET", "/lookups/next-prj-id", quiet=True) if not detail else None
    prj_id = detail.get("prj_id") or (next_id or {}).get("prj_id", "Auto")
    st.text_input("PRJID", value=str(prj_id), disabled=True, key=f"{prefix}_prj")
    c1, c2 = st.columns(2)
    attribute_name = c1.text_input("PRJ Attribute Name *", value=str(detail.get("prj_attribute_name") or ""), disabled=locked, key=f"{prefix}_name")
    physical_default = str(detail.get("prj_physical_attribute_name") or "")
    generated_physical = physical_default or (generate_physical_name(attribute_name) if attribute_name else "")
    physical = c2.text_input("PRJ Physical Attribute Name *", value=generated_physical, disabled=locked, key=f"{prefix}_physical")
    if attribute_name and not locked:
        suggestion = api("GET", "/lookups/physical-name-suggestions", quiet=True, params={"attribute_name": attribute_name, "prj_id": detail.get("prj_id") or ""})
        if suggestion:
            alternatives = [item["name"] for item in suggestion.get("suggestions", []) if item.get("available") and item.get("name") != physical]
            if alternatives:
                st.caption("Alternative unique names: " + ", ".join(alternatives[:3]))

    c1, c2, c3 = st.columns(3)
    portfolio_default = str(rule.get("portfolio") or (portfolio_labels[0] if portfolio_labels else ""))
    p_options = list(portfolio_labels)
    if portfolio_default and portfolio_default not in p_options:
        p_options.insert(0, portfolio_default)
    p_options = p_options or ["FI Banks"]
    p_index = p_options.index(portfolio_default) if portfolio_default in p_options else 0
    portfolio = c1.selectbox("Portfolio / Scope *", p_options, index=p_index, disabled=locked, key=f"{prefix}_portfolio")
    src_code = str(rule.get("source_abbr_name") or (source_options[0] if source_options else "SNPAR"))
    s_options = list(source_options)
    if src_code and src_code not in s_options:
        s_options.insert(0, src_code)
    s_options = s_options or ["SNPAR"]
    s_index = s_options.index(src_code) if src_code in s_options else 0
    source_code = c2.selectbox("Source *", s_options, index=s_index, format_func=lambda code: f"{source_by_code.get(code, code)} [{code}]", disabled=locked, key=f"{prefix}_source")
    current_symbol = str(rule.get("symbol") or "Amount")
    dtype_options = ["Amount", "%", "Ratio", "actual", "Other"]
    if current_symbol not in dtype_options:
        dtype_options.insert(0, current_symbol)
    dtype_index = dtype_options.index(current_symbol) if current_symbol in dtype_options else 0
    data_type = c3.selectbox("DATA TYPE", dtype_options, index=dtype_index, disabled=locked, key=f"{prefix}_dtype")

    c1, c2 = st.columns(2)
    section = c1.text_input("Section *", value=str(rule.get("section") or ""), disabled=locked, key=f"{prefix}_section")
    subsection = c2.text_input("Sub-Section *", value=str(rule.get("subsection") or ""), disabled=locked, key=f"{prefix}_subsection")
    mapping_default = str(rule.get("mapping_type") or "Reported")
    mapping_options = ["Calculated", "Reported", "Repeated"]
    mapping_index = mapping_options.index(mapping_default) if mapping_default in mapping_options else 1
    calculated = st.selectbox("Calculated or Reported *", mapping_options, index=mapping_index, disabled=locked, key=f"{prefix}_mapping")
    calculation_logic = st.text_area("Calculation Logic", value=str(rule.get("calculation_logic") or "NA"), disabled=locked, height=120, key=f"{prefix}_calc")
    segment = st.text_input("Segment", value=str(detail.get("where_in_financial_statement") or "NA"), disabled=locked, key=f"{prefix}_segment")
    attribute_definition = st.text_area("Attribute Definition", value=str(detail.get("prj_attribute_definition") or ""), disabled=locked, height=100, key=f"{prefix}_definition")
    attribute_description = st.text_area("Attribute Description / Proposed Prompt", value=str(rule.get("prj_attribute_description") or ""), disabled=locked, height=120, key=f"{prefix}_description")
    c1, c2 = st.columns(2)
    display_order = c1.number_input("Display Order *", min_value=0, value=int(rule.get("display_order") or 0), step=1, disabled=locked, key=f"{prefix}_order")
    display_name = c2.text_input("Display Name", value=str(rule.get("display_name") or detail.get("prj_attribute_name") or ""), disabled=locked, key=f"{prefix}_display")
    tech_preview = str(rule.get("tech_logic") or generate_tech_logic(calculation_logic))
    st.text_area("Tech Logic (read only; auto-generated)", value=tech_preview, disabled=True, height=90, key=f"{prefix}_tech")
    examples = st.text_area("Examples (Prompt Management)", value=str(rule.get("examples") or ""), disabled=locked, height=80, key=f"{prefix}_examples")

    if locked:
        return None
    submitted = st.button("Create Attribute" if not detail else "Upload Changes", type="primary", key=f"{prefix}_submit")
    if not submitted:
        return None
    if not attribute_name.strip() or not section.strip() or not subsection.strip():
        st.error("PRJ Attribute Name, Section and Sub-Section are mandatory.")
        return None
    return {
        "prj_id": None if not detail else detail.get("prj_id"),
        "portfolio": portfolio,
        "source_abbr_name": source_code,
        "prj_attribute_name": attribute_name,
        "prj_physical_attribute_name": physical or None,
        "section": section,
        "sub_section": subsection,
        "data_type": data_type,
        "calculated_or_reported": calculated,
        "calculation_logic": calculation_logic or "NA",
        "segment": segment or "NA",
        "attribute_definition": attribute_definition or None,
        "attribute_description": attribute_description or None,
        "display_order": int(display_order),
        "display_name": display_name or attribute_name,
        "examples": examples or None,
        "is_active": True,
    }


is_admin = bool(refreshed.get("is_admin"))
main_tab_labels = ["Data Dictionary", "Prompt Management", "Audit"] + (["Admin Tools"] if is_admin else [])
main_tabs = st.tabs(main_tab_labels)

with main_tabs[0]:
    workflow_labels = ["View / Edit Latest"] + (["Upload & Edit"] if is_admin else []) + ["Finalize and Upload"]
    workflow_tabs = st.tabs(workflow_labels)
    view_edit_tab = workflow_tabs[0]
    upload_tab = workflow_tabs[1] if is_admin else None
    finalize_tab = workflow_tabs[2] if is_admin else workflow_tabs[1]

    with view_edit_tab:
        st.subheader("View Latest")
        f1, f2, f3, f4 = st.columns(4)
        portfolios = f1.multiselect("Portfolio", portfolio_labels)
        sources = f2.multiselect("Source", source_options, format_func=lambda code: f"{source_by_code.get(code, code)} [{code}]")
        prj_filter = f3.text_input("PRJ_ID")
        name_filter = f4.text_input("Attribute Name")
        f1, f2, f3, f4 = st.columns(4)
        definition_filter = f1.text_input("Attribute Definition")
        section_filter = f2.selectbox("Section", [""] + list(lookups.get("sections", [])))
        subsection_filter = f3.selectbox("Sub-Section", [""] + list(lookups.get("subsections", [])))
        overlapped = f4.checkbox("Overlapped Attribute only")
        c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
        include_deleted = c1.checkbox("Include inactive", value=False)
        page_size = c2.selectbox("Rows", [50, 100, 250, 500], index=1)
        page_number = c3.number_input("Page", min_value=1, value=1, step=1)
        search = c4.text_input("Search")

        payload = {
            "portfolios": portfolios,
            "sources": sources,
            "prj_id": prj_filter or None,
            "attribute_name": name_filter or None,
            "attribute_definition": definition_filter or None,
            "section": section_filter or None,
            "subsection": subsection_filter or None,
            "search": search or None,
            "overlapped_only": overlapped,
            "include_deleted": include_deleted,
            "page": int(page_number),
            "page_size": page_size,
        }

        create_col, _ = st.columns([1.7, 6])
        if create_col.button("Create New Attribute", type="primary", use_container_width=True):
            st.session_state["show_create"] = True
            create_modal.open()

        result = api("POST", "/data-dictionary/filter-page", json=payload, quiet=True)
        if result:
            st.session_state["view_rows"] = result.get("rows", [])
            st.session_state["view_total"] = result.get("total", 0)
        rows = st.session_state.get("view_rows", [])

        b1, b2, b3, b4 = st.columns([1.2, 1.2, 1.2, 4])
        if b1.button("View Latest", use_container_width=True):
            result = api("POST", "/data-dictionary/filter-page", json=payload)
            if result:
                st.session_state["view_rows"] = result.get("rows", [])
                rows = st.session_state["view_rows"]
        if b2.button("Download Latest", use_container_width=True):
            response = api("GET", "/data-dictionary/download-latest", binary=True)
            if response:
                st.session_state["latest_excel"] = response.content
        if st.session_state.get("latest_excel"):
            b3.download_button(
                "Download Excel",
                st.session_state["latest_excel"],
                "prj_master_dictionary_latest.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        b4.caption(f"{st.session_state.get('view_total', 0)} matching attribute(s)")

        if rows:
            grid_columns = [
                "prj_id", "prj_attribute_name", "prj_attribute_definition", "prj_physical_attribute_name",
                "editable", "symbol", "portfolios", "sources", "section", "subsection", "is_active",
            ]
            frame = pd.DataFrame(rows)
            st.dataframe(frame[[c for c in grid_columns if c in frame.columns]], use_container_width=True, hide_index=True, height=430)
            options = [str(row.get("prj_id")) for row in rows]
            selected_prj = st.selectbox("Select one attribute for an action", [""] + options, key="view_selected_prj")
            action1, action2, action3 = st.columns(3)
            if action1.button("Edit Selected", disabled=not selected_prj, use_container_width=True):
                st.session_state["selected_prj"] = selected_prj
                st.session_state["show_edit"] = True
                st.session_state["edit_unlocked"] = False
                edit_modal.open()
            if action2.button("Soft Delete", disabled=not selected_prj, use_container_width=True):
                response = api("DELETE", f"/data-dictionary/attributes/{selected_prj}")
                if response:
                    st.success("Soft delete staged. Review Delta, then Finalize and Upload.")
            if action3.button("Reactivate", disabled=not selected_prj, use_container_width=True):
                response = api("POST", f"/data-dictionary/attributes/{selected_prj}/reactivate")
                if response:
                    st.success("Reactivation staged. Review Delta, then Finalize and Upload.")
        else:
            st.info("No records loaded for the selected filters.")

        st.divider()
        st.subheader("Edit Latest")
        st.caption(
            "Existing PRJ_ID values are read-only. New grid rows receive a PRJ_ID from the API. "
            "Set Is Active to false for a soft delete; all changes remain staged until finalization."
        )
        edit_rows = api("GET", "/data-dictionary/edit-latest?include_deleted=true", quiet=True) or []
        if edit_rows:
            all_edit = pd.DataFrame(edit_rows)
            q1, q2, q3 = st.columns([3, 1, 1])
            edit_search = q1.text_input("Search Edit Latest", key="edit_latest_search")
            edit_page_size = int(q2.selectbox("Rows per page", [25, 50, 100, 250], index=1, key="edit_page_size"))
            if edit_search:
                needle = edit_search.lower()
                mask = all_edit.apply(
                    lambda row: needle in " ".join(str(value).lower() for value in row.values), axis=1
                )
                filtered_edit = all_edit[mask].copy()
            else:
                filtered_edit = all_edit.copy()
            max_page = max(1, (len(filtered_edit) + edit_page_size - 1) // edit_page_size)
            edit_page = int(q3.number_input("Page", min_value=1, max_value=max_page, value=1, step=1, key="edit_page"))
            page_start = (edit_page - 1) * edit_page_size
            page_frame = filtered_edit.iloc[page_start: page_start + edit_page_size].copy()

            display_columns = [
                "scope_id", "prj_id", "portfolio", "source_abbr_name", "prj_attribute_name",
                "prj_physical_attribute_name", "section", "sub_section", "data_type", "calculated_or_reported",
                "calculation_logic", "segment", "prj_attribute_definition", "attribute_description",
                "display_order", "display_name", "prompt_description", "examples", "is_active",
            ]
            for column in display_columns:
                if column not in page_frame.columns:
                    page_frame[column] = None
            editor_df = page_frame[display_columns].reset_index(drop=True)
            edited = st.data_editor(
                editor_df,
                use_container_width=True,
                hide_index=True,
                height=500,
                disabled=["scope_id", "prj_id"],
                num_rows="dynamic",
                key=f"edit_latest_grid_{edit_page}_{edit_search}",
            )

            original_by_scope = {
                int(row["scope_id"]): row
                for _, row in editor_df.iterrows()
                if pd.notna(row.get("scope_id"))
            }
            dirty_rows: list[dict[str, Any]] = []
            new_rows: list[dict[str, Any]] = []
            for _, row_series in edited.iterrows():
                row = row_series.to_dict()
                scope_value = row.get("scope_id")
                if pd.isna(scope_value):
                    if any(pd.notna(value) and str(value).strip() for key, value in row.items() if key != "is_active"):
                        new_rows.append(row)
                    continue
                scope_id = int(scope_value)
                original_row = original_by_scope.get(scope_id)
                if original_row is None:
                    continue
                changed = any(
                    str("" if pd.isna(original_row.get(column)) else original_row.get(column))
                    != str("" if pd.isna(row.get(column)) else row.get(column))
                    for column in display_columns
                    if column not in {"scope_id", "prj_id"}
                )
                if changed:
                    dirty_rows.append(row)

            removed_scope_ids = set(original_by_scope) - {
                int(value) for value in edited["scope_id"].dropna().tolist()
            }
            if removed_scope_ids:
                st.warning(
                    "Rows removed with the grid delete control are not staged automatically. "
                    "Use Is Active = false or the Soft Delete action so deletion is explicit and auditable."
                )
            dirty_count = len(dirty_rows) + len(new_rows)
            st.caption(
                f"Showing {len(editor_df)} of {len(filtered_edit)} rows. Pending grid changes: "
                f"{len(dirty_rows)} existing + {len(new_rows)} new."
            )

            def grid_payload(row: dict[str, Any], *, existing: bool) -> dict[str, Any]:
                def clean(value, default=None):
                    if value is None or (isinstance(value, float) and pd.isna(value)):
                        return default
                    text = str(value).strip()
                    return text if text else default

                return {
                    "prj_id": clean(row.get("prj_id")) if existing else None,
                    "portfolio": clean(row.get("portfolio"), "") or "",
                    "source_abbr_name": clean(row.get("source_abbr_name"), "SNPAR"),
                    "prj_attribute_name": clean(row.get("prj_attribute_name"), "") or "",
                    "prj_physical_attribute_name": clean(row.get("prj_physical_attribute_name")),
                    "section": clean(row.get("section"), "") or "",
                    "sub_section": clean(row.get("sub_section"), "") or "",
                    "data_type": clean(row.get("data_type")),
                    "calculated_or_reported": clean(row.get("calculated_or_reported"), "Reported"),
                    "calculation_logic": clean(row.get("calculation_logic"), "NA"),
                    "segment": clean(row.get("segment"), "NA"),
                    "attribute_definition": clean(row.get("prj_attribute_definition")),
                    "attribute_description": clean(row.get("attribute_description")),
                    "display_order": int(float(0 if pd.isna(row.get("display_order")) else row.get("display_order") or 0)),
                    "display_name": clean(row.get("display_name"), clean(row.get("prj_attribute_name"), "")),
                    "prompt_description": clean(row.get("prompt_description")),
                    "examples": clean(row.get("examples")),
                    "is_active": bool(row.get("is_active", True)),
                }

            if st.button(
                "Stage Grid Changes",
                type="primary",
                disabled=dirty_count == 0,
            ):
                success = 0
                for row in dirty_rows:
                    payload = grid_payload(row, existing=True)
                    response = api("PUT", f"/data-dictionary/attributes/{payload['prj_id']}", json=payload)
                    if response:
                        success += 1
                for row in new_rows:
                    payload = grid_payload(row, existing=False)
                    response = api("POST", "/data-dictionary/attributes", json=payload)
                    if response:
                        success += 1
                if success:
                    st.success(f"{success} row(s) staged. Review the delta before finalization.")
        else:
            st.info("No final records available for editing.")

    if is_admin and upload_tab is not None:
        with upload_tab:
            st.subheader("Bulk Upload: Single Sheet or Multi-Sheet Merger")
            st.caption("Each selected sheet has its own header row, portfolio override and source-column mapping.")
            uploaded = st.file_uploader("Master Dictionary Excel", type=["xlsx"], key="master_upload_file")
            if uploaded:
                file_tuple = (uploaded.name, uploaded.getvalue(), uploaded.type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                sheets_result = api("POST", "/master-upload/sheets", files={"file": file_tuple})
                sheets = sheets_result.get("sheets", []) if sheets_result else []
                mode_type = st.radio("Sheet mode", ["Single Sheet", "Multi-Sheet Merger"], horizontal=True)
                selected_sheets = (
                    [st.selectbox("Sheet", sheets)] if mode_type == "Single Sheet" and sheets
                    else st.multiselect("Sheets to merge", sheets, default=sheets[: min(2, len(sheets))])
                )
                configs: list[dict[str, Any]] = []
                for sheet_name in selected_sheets:
                    with st.expander(f"Mapping: {sheet_name}", expanded=True):
                        c1, c2 = st.columns(2)
                        header_row = c1.number_input("Header row (1-based)", min_value=1, max_value=50, value=2, step=1, key=f"header_{sheet_name}")
                        portfolio_override = c2.selectbox("Portfolio override", [""] + portfolio_labels, key=f"port_{sheet_name}")
                        preview = api(
                            "POST",
                            "/master-upload/preview-sheet",
                            files={"file": file_tuple},
                            data={"sheet_name": sheet_name, "header_row": int(header_row)},
                            quiet=True,
                        )
                        mapping: dict[str, str] = {}
                        if preview:
                            st.caption(f"Detected portfolio from sheet name: {preview.get('portfolio_detected') or 'Not detected'}")
                            columns = [""] + preview.get("columns", [])
                            detected = preview.get("detected_mapping", {})
                            map_cols = st.columns(3)
                            for index, field in enumerate(STANDARD_FIELDS):
                                default_column = detected.get(field, "")
                                default_index = columns.index(default_column) if default_column in columns else 0
                                selected_column = map_cols[index % 3].selectbox(
                                    field,
                                    columns,
                                    index=default_index,
                                    key=f"map_{sheet_name}_{field}",
                                )
                                if selected_column:
                                    mapping[field] = selected_column
                            st.dataframe(pd.DataFrame(preview.get("preview", [])), use_container_width=True, hide_index=True, height=220)
                        configs.append({
                            "sheet_name": sheet_name,
                            "header_row": int(header_row),
                            "portfolio_override": portfolio_override,
                            "mapping": mapping,
                        })
                upload_mode = st.radio("Database raw-load mode", ["MERGE", "REPLACE"], horizontal=True, help="REPLACE clears current raw/staging pending data before loading the workbook. Final tables are untouched until finalization.")
                u1, u2 = st.columns(2)
                if u1.button("Validate and Compare", disabled=not configs):
                    preview = api(
                        "POST",
                        "/master-upload/preview",
                        files={"file": file_tuple},
                        data={"configurations_json": json.dumps(configs), "mode": upload_mode},
                    )
                    st.session_state["upload_preview"] = preview
                if u2.button("Stage Uploaded Data", type="primary", disabled=not configs or not refreshed.get("is_admin")):
                    result = api(
                        "POST",
                        "/master-upload/finalize",
                        files={"file": file_tuple},
                        data={"configurations_json": json.dumps(configs), "mode": upload_mode},
                    )
                    if result:
                        st.success(f"Staged {result.get('staged_count', 0)} rows; rejected {result.get('rejected_count', 0)} rows.")
                        st.session_state["upload_preview"] = result
                if st.session_state.get("upload_preview"):
                    st.json(st.session_state["upload_preview"])

    with finalize_tab:
        st.subheader("Finalize and Upload")
        delta = api("GET", "/data-dictionary/delta", quiet=True) or {"rows": [], "has_changes": False, "count": 0}
        st.caption(f"Pending delta: {delta.get('count', 0)} attribute(s)")
        if delta.get("rows"):
            st.dataframe(pd.DataFrame(delta["rows"]), use_container_width=True, hide_index=True)
        else:
            st.info("No staged changes. Finalize is disabled.")
        if is_admin:
            c1, c2 = st.columns(2)
        else:
            c1 = st.container()
            c2 = None
        if c1.button("Finalize and Upload", type="primary", disabled=not delta.get("has_changes"), use_container_width=True):
            finalize_modal.open()
        if is_admin and c2 is not None:
            if c2.button("Save Final Tables to S3", use_container_width=True):
                result = api("POST", "/s3/export-final")
                if result:
                    st.success(f"Uploaded {len(result.get('files', []))} final-table extract(s) to S3.")
                    st.json(result)

with main_tabs[1]:
    st.subheader("Prompt Management")
    prompts = api("GET", "/prompts?include_deleted=true", quiet=True) or []
    if prompts:
        search_prompt = st.text_input("Search prompts")
        filtered = prompts
        if search_prompt:
            needle = search_prompt.lower()
            filtered = [row for row in prompts if needle in json.dumps(row, default=str).lower()]
        st.dataframe(pd.DataFrame(filtered), use_container_width=True, hide_index=True, height=420)
        scope_ids = [int(row["scope_id"]) for row in filtered]
        selected_scope = st.selectbox("Select scope_id", scope_ids)
        current = next(row for row in filtered if int(row["scope_id"]) == int(selected_scope))
        prompt_description = st.text_area("Prompt Description", value=str(current.get("prompt_description") or ""), height=150)
        examples = st.text_area("Examples", value=str(current.get("examples") or ""), height=120)
        if st.button("Stage Prompt Changes", type="primary"):
            response = api("PUT", f"/prompts/{selected_scope}", json={"scope_id": selected_scope, "prompt_description": prompt_description or None, "examples": examples or None})
            if response:
                st.success("Prompt changes staged. Use Finalize and Upload in Data Dictionary to publish them.")
    else:
        st.info("No prompt/business-rule rows available.")

with main_tabs[2]:
    st.subheader("Audit History")
    a1, a2, a3, a4 = st.columns(4)
    table_name = a1.text_input("Table")
    action = a2.text_input("Action")
    performed_by = a3.text_input("Performed By")
    source_operation = a4.text_input("Source Operation")
    audit_search = st.text_input("Search before/after values")
    audit_rows = api("POST", "/audit/filter", json={
        "table_name": table_name or None,
        "action": action or None,
        "performed_by": performed_by or None,
        "source_operation": source_operation or None,
        "search": audit_search or None,
    }, quiet=True) or []
    if audit_rows:
        st.dataframe(pd.DataFrame(audit_rows), use_container_width=True, hide_index=True, height=520)
    else:
        st.info("No audit rows found for the selected filters.")

if is_admin:
    with main_tabs[3]:
        st.subheader("Admin Tools")
        portfolios_admin = api("GET", "/portfolio-reference", quiet=True) or []
        st.markdown("#### Portfolio Reference")
        if portfolios_admin:
            st.dataframe(pd.DataFrame(portfolios_admin), use_container_width=True, hide_index=True)
        with st.expander("Add Portfolio"):
            c1, c2 = st.columns(2)
            p_name = c1.text_input("Portfolio Name")
            sector = c2.text_input("Sector Name")
            sub_sector = c1.text_input("Sub-Sector")
            remark = c2.text_input("Remark")
            if st.button("Insert Portfolio", disabled=not refreshed.get("is_admin")):
                result = api("POST", "/portfolio-reference", json={
                    "portfolio_name": p_name,
                    "sector_name": sector,
                    "sub_sector": sub_sector or None,
                    "remark": remark or None,
                })
                if result:
                    st.success(f"Created port_ref_id {result.get('port_ref_id')}")
        st.markdown("#### Deployment")
        st.code("poetry run uvicorn DataDictionaryAdminApp.api.swagger_app:app --host 0.0.0.0 --port 8503")
        st.code("poetry run streamlit run src/DataDictionaryAdminApp/streamlit_app.py --server.port 8501")
        if refreshed.get("db_type") == "POSTGRES":
            st.caption("Run sql/postgres/001_create_tables.sql, then sql/postgres/002_validate_schema.sql before enabling PostgreSQL writes.")
        else:
            st.caption("Run sql/001_create_tables.sql, then sql/002_validate_schema.sql before enabling SQL Server writes.")

if st.session_state.get("show_create"):
    if not create_modal.is_open():
        create_modal.open()
    if create_modal.is_open():
        with create_modal.container():
            payload = attribute_form("create")
            if payload:
                result = api("POST", "/data-dictionary/attributes", json=payload)
                if result:
                    st.success(f"{result.get('prj_id')} staged successfully.")
                    st.session_state["show_create"] = False
                    create_modal.close()
                    st.rerun()
            if st.button("Close", key="create_close"):
                st.session_state["show_create"] = False
                create_modal.close()
                st.rerun()

if st.session_state.get("show_edit"):
    selected_prj = st.session_state.get("selected_prj")
    detail = api("GET", f"/data-dictionary/attributes/{selected_prj}", quiet=True) if selected_prj else None
    if not edit_modal.is_open():
        edit_modal.open()
    if edit_modal.is_open():
        with edit_modal.container():
            if detail:
                if not st.session_state.get("edit_unlocked"):
                    attribute_form("edit_locked", detail, locked=True)
                    if st.button("Edit", type="primary", key="unlock_edit"):
                        st.session_state["edit_unlocked"] = True
                        st.rerun()
                else:
                    payload = attribute_form("edit", detail, locked=False)
                    if payload:
                        result = api("PUT", f"/data-dictionary/attributes/{selected_prj}", json=payload)
                        if result:
                            st.success("Changes staged. Review the delta before finalization.")
                            st.session_state["show_edit"] = False
                            st.session_state["edit_unlocked"] = False
                            edit_modal.close()
                            st.rerun()
            if st.button("Close", key="edit_close"):
                st.session_state["show_edit"] = False
                st.session_state["edit_unlocked"] = False
                edit_modal.close()
                st.rerun()

if finalize_modal.is_open():
    with finalize_modal.container():
        st.warning("Do you want to update database tables?")
        c1, c2 = st.columns(2)
        if c1.button("Yes Upload", type="primary", use_container_width=True):
            result = api("POST", "/data-dictionary/finalize", json={"confirm": True})
            if result:
                st.success(result.get("message", "Finalized successfully."))
                finalize_modal.close()
                st.rerun()
        if c2.button("Cancel", use_container_width=True):
            finalize_modal.close()
            st.rerun()
