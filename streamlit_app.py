"""Streamlit UI. All database operations are performed through the FastAPI layer."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st
from streamlit_modal import Modal

from DataDictionaryAdminApp.service.excel_service import STANDARD_FIELDS
from DataDictionaryAdminApp.utils.normalizers import align_int_pipe_values, align_pipe_values, canonical_portfolio_label, generate_physical_name, generate_tech_logic, pair_pipe_values, portfolio_from_sheet_name


class StateAwareModal(Modal):
    """Modal that synchronizes the application-level open flag on every close.

    ``streamlit-modal`` keeps its own ``<key>-opened`` flag.  Create/Edit also
    have application flags (``show_create``/``show_edit``).  If the built-in
    X only closes the library flag while the application flag stays True, the
    next rerun can reopen the modal.  Keeping both flags synchronized makes X
    dismissal immediate and prevents the modal from being reconstructed.
    """

    def __init__(self, title: str, key: str, *, state_flag: str, padding: int = 20, max_width: int = 744):
        super().__init__(title, key=key, padding=padding, max_width=max_width)
        self.state_flag = state_flag

    def close(self, rerun_condition: bool = True):
        st.session_state[self.state_flag] = False
        return super().close(rerun_condition=rerun_condition)


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
/* Create/Edit modal sizing is injected inside the modal container itself so
   it is rendered after streamlit-modal's own stylesheet and wins reliably. */
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


def request_filter_submit() -> None:
    """Request an immediate View Latest refresh when any filter is committed."""
    st.session_state["filter_submit_requested"] = True


def request_prj_filter_submit() -> None:
    """Backward-compatible PRJ_ID callback; delegates to the shared filter refresh."""
    st.session_state["prj_filter_submit_requested"] = True
    request_filter_submit()


VIEW_FILTER_WIDGET_KEYS = (
    "view_portfolio_filter",
    "view_source_filter",
    "view_prj_id_filter",
    "view_attribute_name_filter",
    "view_attribute_definition_filter",
    "view_section_filter",
    "view_subsection_filter",
    "view_overlapped_filter",
    "view_include_inactive_filter",
    "view_page_size_filter",
    "view_page_number_filter",
    "view_search_filter",
)


def clear_view_filters() -> None:
    """Reset both visible filter widgets and the active View Latest query.

    Assign explicit defaults instead of only deleting widget keys.  This keeps
    Streamlit's frontend widget state and ``st.session_state`` synchronized on
    the same rerun, so a value such as Section=Asset visibly becomes blank as
    soon as Clear Filters is clicked.
    """
    defaults = {
        "view_portfolio_filter": [],
        "view_source_filter": [],
        "view_prj_id_filter": "",
        "view_attribute_name_filter": "",
        "view_attribute_definition_filter": "",
        "view_section_filter": "",
        "view_subsection_filter": "",
        "view_overlapped_filter": False,
        "view_include_inactive_filter": False,
        "view_page_size_filter": 100,
        "view_page_number_filter": 1,
        "view_search_filter": "",
    }
    for key, value in defaults.items():
        st.session_state[key] = value
    st.session_state["view_rows"] = []
    st.session_state["view_total"] = 0
    st.session_state["view_filter_signature"] = ""
    st.session_state["view_loaded"] = False
    st.session_state["prj_filter_submit_requested"] = False
    st.session_state["filter_submit_requested"] = True


def database_status_check() -> dict[str, Any]:
    """Check DB connectivity through FastAPI, with a local diagnostic fallback.

    The fallback is deliberately limited to ``SELECT 1`` connectivity diagnostics;
    normal application reads/writes continue to go through FastAPI only. This also
    gives a useful message when Streamlit has been updated but an older FastAPI
    process is still running without the database-status endpoint.
    """
    api_issue = None
    try:
        response = HTTP.get(API + "/system/database-status", headers=headers(), timeout=READ_TIMEOUT)
        if response.ok:
            result = response.json()
            result["status_source"] = "API"
            return result
        try:
            detail = response.json().get("detail", response.json())
        except Exception:
            detail = response.text
        api_issue = f"HTTP {response.status_code}: {detail}"
    except requests.RequestException as exc:
        api_issue = str(exc)

    try:
        from DataDictionaryAdminApp.core.database import database_connection_status

        result = database_connection_status(
            st.session_state.get("environment", os.getenv("SELECTED_ENVIRONMENT", "LOCAL")),
            st.session_state.get("database_type", os.getenv("SELECTED_DB_TYPE", "SQLSERVER")),
        )
        result["status_source"] = "DIRECT_FALLBACK"
        result["api_issue"] = api_issue
        return result
    except Exception as exc:
        return {
            "connected": False,
            "issue": f"API status check failed: {api_issue or 'unknown error'}; direct database check failed: {exc}",
            "status_source": "FAILED",
            "api_issue": api_issue,
        }


for key, default in {
    "environment": os.getenv("SELECTED_ENVIRONMENT", "LOCAL"),
    "database_type": os.getenv("SELECTED_DB_TYPE", "SQLSERVER").upper(),
    "role": os.getenv("SELECTED_ROLE", "ADMIN").upper(),
    "view_rows": [],
    "view_total": 0,
    "view_loaded": False,
    "view_filter_signature": "",
    "filter_submit_requested": False,
    "prj_filter_submit_requested": False,
    "selected_prj": "",
    "edit_detail": None,
    "upload_preview": None,
    "upload_stage_result": None,
    "upload_configs": [],
    "upload_file_fingerprint": "",
    "upload_sheet_names": [],
    "upload_sheet_preview_cache": {},
    "lookup_cache_key": "",
    "lookup_cache": None,
    "runtime_context_key": "",
    "runtime_context": None,
    "backend_health_key": "",
    "backend_health": None,
    "prompts_cache_key": "",
    "prompts_cache": None,
    "audit_cache_signature": "",
    "audit_cache_rows": None,
    "admin_portfolios_cache_key": "",
    "admin_portfolios_cache": None,
    "soft_deleted_cache_key": "",
    "soft_deleted_cache": None,
    "latest_excel": None,
    "show_create": False,
    "show_edit": False,
    "edit_unlocked": False,
    "show_finalize_confirm": False,
    "show_soft_deleted": False,
    "show_cleanup": False,
    "cleanup_step": 0,
    "database_status_key": "",
    "database_status": None,
    "flash_message": None,
}.items():
    st.session_state.setdefault(key, default)

context_key = f"{st.session_state['environment']}:{st.session_state['database_type']}:{st.session_state['role']}"
if st.session_state.get("runtime_context_key") != context_key or st.session_state.get("runtime_context") is None:
    st.session_state["runtime_context"] = api("GET", "/system/context", quiet=True)
    st.session_state["runtime_context_key"] = context_key
context = st.session_state.get("runtime_context") or {
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
        st.session_state["view_loaded"] = False
        st.session_state["lookup_cache"] = None
        st.session_state["database_status_key"] = ""
        st.session_state["runtime_context"] = None
        st.session_state["prompts_cache"] = None
        st.session_state["audit_cache_rows"] = None
        st.session_state["admin_portfolios_cache"] = None
        st.session_state["soft_deleted_cache"] = None
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
        st.session_state["view_loaded"] = False
        st.session_state["lookup_cache"] = None
        st.session_state["database_status_key"] = ""
        st.session_state["runtime_context"] = None
        st.session_state["prompts_cache"] = None
        st.session_state["audit_cache_rows"] = None
        st.session_state["admin_portfolios_cache"] = None
        st.session_state["soft_deleted_cache"] = None
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
        st.session_state["runtime_context"] = None
        st.session_state["backend_health"] = None
        st.rerun()

    refreshed = context
    st.text_input("Database", value=str(refreshed.get("database", "Unknown")), disabled=True)
    st.text_input("Server", value=str(refreshed.get("server", "Unknown")), disabled=True)
    st.text_input("Current User", value=str(refreshed.get("current_user", CURRENT_USER)), disabled=True)
    st.text_input("Access", value=str(refreshed.get("role", st.session_state.get("role", "USER"))), disabled=True)

    status_key = f"{st.session_state['environment']}:{st.session_state['database_type']}"
    if st.session_state.get("database_status_key") != status_key:
        st.session_state["database_status"] = database_status_check()
        st.session_state["database_status_key"] = status_key
    if st.button("Test Database Connection", width="stretch"):
        st.session_state["database_status"] = database_status_check()
    db_status = st.session_state.get("database_status")
    selected_db_label = db_labels.get(st.session_state["database_type"], st.session_state["database_type"])
    if db_status and db_status.get("connected"):
        st.success(f"{selected_db_label}: Connected")
    elif db_status:
        st.error(f"{selected_db_label}: Not connected")
        st.caption(str(db_status.get("issue") or "Unknown database connection error."))
    if db_status and db_status.get("status_source") == "DIRECT_FALLBACK":
        st.caption(
            "Connectivity was checked directly because the FastAPI database-status endpoint was unavailable. "
            "Restart FastAPI after replacing the latest files."
        )
        if db_status.get("api_issue"):
            st.caption(f"API status issue: {db_status['api_issue']}")

    if not refreshed.get("database_enabled", False):
        st.warning("Database access is disabled for this environment.")

lookup_key = f"{st.session_state['environment']}:{st.session_state['database_type']}"
if st.session_state.get("lookup_cache_key") != lookup_key or st.session_state.get("lookup_cache") is None:
    st.session_state["lookup_cache"] = api("GET", "/lookups", quiet=True) or {
        "portfolios": [], "sources": [], "sections": [], "subsections": []
    }
    st.session_state["lookup_cache_key"] = lookup_key
lookups = st.session_state.get("lookup_cache") or {"portfolios": [], "sources": [], "sections": [], "subsections": []}
portfolio_labels = list(dict.fromkeys(
    item.get("label") for item in lookups.get("portfolios", []) if item.get("label")
))
bulk_portfolio_options = list(portfolio_labels)
source_options = list(dict.fromkeys(
    item.get("source_code") for item in lookups.get("sources", []) if item.get("source_code")
))
source_names = [item.get("source_name") for item in lookups.get("sources", []) if item.get("source_name")]
source_by_code = {item.get("source_code"): item.get("source_name") for item in lookups.get("sources", [])}

def source_label(code: str) -> str:
    return f"{code}[{source_by_code.get(code, code)}]"

create_modal = StateAwareModal(
    "Create New Attribute",
    key="create_attribute_modal",
    state_flag="show_create",
    max_width=1900,
)
edit_modal = StateAwareModal(
    "Edit Attribute",
    key="edit_attribute_modal",
    state_flag="show_edit",
    max_width=1900,
)
finalize_modal = Modal("Finalize and Upload", key="finalize_modal", max_width=720)
cleanup_modal = Modal("Cleanup Database", key="cleanup_database_modal", max_width=980)


def render_attribute_modal_style(modal_key: str) -> None:
    """Center Create/Edit modals and make them nearly full-screen.

    ``streamlit-modal`` injects its stylesheet when ``container()`` is entered,
    so this override is intentionally rendered *inside* the modal afterwards.
    That makes the centering/width rules deterministic instead of depending on
    stylesheet order from the main page.
    """
    st.markdown(
        f"""
<style>
/* streamlit-modal positions its card independently of the overlay.  Center
   the actual card explicitly against the browser viewport; centering only the
   overlay is not sufficient because the library applies its own top/left and
   transform rules to the first child. */
div[data-modal-container='true'][key='{modal_key}'],
div[data-modal-container='true'] {{
    position: fixed !important;
    inset: 0 !important;
    width: 100vw !important;
    height: 100vh !important;
    min-height: 100vh !important;
    display: grid !important;
    place-items: center !important;
    overflow: hidden !important;
}}
div[data-modal-container='true'][key='{modal_key}'] > div:first-child,
div[data-modal-container='true'] > div:first-child {{
    position: absolute !important;
    top: 50% !important;
    left: 50% !important;
    right: auto !important;
    bottom: auto !important;
    transform: translate(-50%, -50%) !important;
    width: 96vw !important;
    max-width: 1900px !important;
    max-height: 90vh !important;
    margin: 0 !important;
    align-self: center !important;
    justify-self: center !important;
}}
div[data-modal-container='true'][key='{modal_key}'] > div:first-child > div:first-child,
div[data-modal-container='true'] > div:first-child > div:first-child {{
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    max-height: 90vh !important;
}}
div[data-modal-container='true'][key='{modal_key}'] > div:first-child > div:first-child > div:first-child,
div[data-modal-container='true'] > div:first-child > div:first-child > div:first-child {{
    max-height: 88vh !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
}}
</style>
""",
        unsafe_allow_html=True,
    )


def attribute_form(prefix: str, detail: dict[str, Any] | None = None, locked: bool = False) -> dict[str, Any] | None:
    detail = detail or {}
    rules = detail.get("rules") or []
    rule_index = 0
    if rules:
        labels = [f"{r.get('portfolio')} | {r.get('source_abbr_name')} | {r.get('section')} / {r.get('subsection')}" for r in rules]
        selected = st.selectbox("Portfolio / Scope record", range(len(rules)), format_func=lambda i: labels[i], key=f"{prefix}_rule")
        rule_index = int(selected)
    rule = rules[rule_index] if rules else {}

    next_id = None
    if not detail:
        # Streamlit reruns on every widget interaction. Keep the generated ID in
        # session state so typing in the form does not rescan the DB repeatedly.
        next_id_key = f"{prefix}_next_prj_id"
        if next_id_key not in st.session_state:
            st.session_state[next_id_key] = api("GET", "/lookups/next-prj-id", quiet=True) or {}
        next_id = st.session_state.get(next_id_key)
    prj_id = detail.get("prj_id") or (next_id or {}).get("prj_id", "")
    st.text_input(
        "CFV ID",
        value=str(prj_id),
        disabled=True,
        key=f"{prefix}_prj",
        help="Generated automatically by the application and stored as the PRJ ID database key.",
    )
    if not detail and not prj_id:
        st.error("CFV ID could not be generated. Close and reopen the form after checking the API/database connection.")
    c1, c2 = st.columns(2)
    attribute_name = c1.text_input("PRJ Attribute Name *", value=str(detail.get("prj_attribute_name") or ""), disabled=locked, key=f"{prefix}_name")
    physical_default = str(detail.get("prj_physical_attribute_name") or "").strip()
    physical = physical_default or (generate_physical_name(attribute_name) if attribute_name else "")
    suggestion_key = f"{prefix}_physical_suggestion"
    suggestion = st.session_state.get(suggestion_key)
    if suggestion and suggestion.get("attribute_name") != attribute_name:
        suggestion = None
        st.session_state.pop(suggestion_key, None)

    if attribute_name and not locked:
        if st.button("Check physical name availability", key=f"{prefix}_check_physical"):
            checked = api(
                "GET",
                "/lookups/physical-name-suggestions",
                quiet=True,
                params={"attribute_name": attribute_name, "prj_id": detail.get("prj_id") or str(prj_id)},
            ) or {}
            checked["attribute_name"] = attribute_name
            st.session_state[suggestion_key] = checked
            suggestion = checked
        if suggestion and not physical_default:
            physical = str(suggestion.get("selected") or suggestion.get("generated") or physical)

    if detail:
        physical = c2.text_input(
            "PRJ Physical Attribute Name *",
            value=physical,
            disabled=locked,
            key=f"{prefix}_physical",
        )
    else:
        # New UI attributes are generated by the application. The backend repeats
        # the uniqueness check before staging, so concurrent users are also safe.
        physical_key = f"{prefix}_physical_{physical or 'blank'}"
        c2.text_input(
            "PRJ Physical Attribute Name *",
            value=physical,
            disabled=True,
            key=physical_key,
            help="Auto-generated from Attribute Name and checked for uniqueness across raw, staging and final tables.",
        )
    if suggestion and not locked:
        alternatives = [
            item["name"] for item in suggestion.get("suggestions", [])
            if item.get("available") and item.get("name") != physical
        ]
        if alternatives:
            st.caption("Alternative unique physical names: " + ", ".join(alternatives[:3]))

    c1, c2, c3 = st.columns(3)
    portfolio_default = str(rule.get("portfolio") or (portfolio_labels[0] if portfolio_labels else ""))
    p_options = list(portfolio_labels)
    if portfolio_default and portfolio_default not in p_options:
        p_options.insert(0, portfolio_default)
    if not p_options:
        c1.error("No portfolio values returned from dbo.prj_portfolio_reference_new_test.")
        p_options = [""]
    p_index = p_options.index(portfolio_default) if portfolio_default in p_options else 0
    portfolio = c1.selectbox("Portfolio / Scope *", p_options, index=p_index, disabled=locked, key=f"{prefix}_portfolio")
    src_code = str(rule.get("source_abbr_name") or (source_options[0] if source_options else "SNPAR"))
    s_options = list(source_options)
    if src_code and src_code not in s_options:
        s_options.insert(0, src_code)
    s_options = s_options or ["SNPAR"]
    s_index = s_options.index(src_code) if src_code in s_options else 0
    source_code = c2.selectbox("Source *", s_options, index=s_index, format_func=source_label, disabled=locked, key=f"{prefix}_source")
    current_symbol = str(rule.get("symbol") or "Amount")
    dtype_options = ["Amount", "%", "Ratio", "actual", "Other"]
    if current_symbol not in dtype_options:
        dtype_options.insert(0, current_symbol)
    dtype_index = dtype_options.index(current_symbol) if current_symbol in dtype_options else 0
    data_type = c3.selectbox("DATA TYPE", dtype_options, index=dtype_index, disabled=locked, key=f"{prefix}_dtype")

    c1, c2 = st.columns(2)
    section = c1.text_input(
        "Section *",
        value=str(rule.get("section") or ""),
        disabled=locked,
        key=f"{prefix}_section",
        placeholder="e.g. Assets|Liabilities",
        help="Separate multiple values with | (pipe). Section and Sub-Section values are paired positionally (for example Total|Liabilities with Current|Current2 creates Total/Current and Liabilities/Current2).",
    )
    subsection = c2.text_input(
        "Sub-Section *",
        value=str(rule.get("subsection") or ""),
        disabled=locked,
        key=f"{prefix}_subsection",
        placeholder="e.g. Current|Non-Current",
        help="Separate multiple values with | (pipe). Values are paired positionally with Section values; a single value on one side is reused when the other side contains multiple values.",
    )
    mapping_default = str(rule.get("mapping_type") or "Reported")
    mapping_options = ["Calculated", "Reported", "Repeated"]
    mapping_index = mapping_options.index(mapping_default) if mapping_default in mapping_options else 1
    calculated = st.selectbox("Calculated or Reported *", mapping_options, index=mapping_index, disabled=locked, key=f"{prefix}_mapping")
    segment = st.text_input(
        "Segment",
        value=str(rule.get("segment") or detail.get("where_in_financial_statement") or "NA"),
        disabled=locked,
        key=f"{prefix}_segment",
        placeholder="e.g. Balance Sheet|Income Statement",
        help=(
            "Segment supports positional pipe-separated values exactly like Section/Sub-Section. "
            "For Total|Liabilities and Current|Current2, SegmentA|SegmentB maps SegmentA to Total/Current "
            "and SegmentB to Liabilities/Current2. A single Segment is reused for every pair."
        ),
    )

    try:
        form_pairs = pair_pipe_values(section, subsection)
    except ValueError:
        form_pairs = []
    pair_count = len(form_pairs)

    with st.expander("Calculation and Attribute Details", expanded=False):
        definition_source = rule.get("prj_attribute_definition") or detail.get("prj_attribute_definition") or ""
        description_source = rule.get("prj_attribute_description") or ""
        calculation_source = rule.get("calculation_logic") or "NA"
        report_type_source = rule.get("report_type") or "NA"
        tech_source = rule.get("tech_logic") or ""
        examples_source = rule.get("examples") or ""
        display_order_source = rule.get("display_order") if rule.get("display_order") is not None else 0
        display_name_source = rule.get("display_name") or detail.get("prj_attribute_name") or attribute_name

        if pair_count > 1:
            st.caption(
                "Attribute Definition and Attribute Description are captured per Section/Sub-Section pair. Scope-specific fields include Calculation Logic, "
                "Attribute Description, Display Order, Report Type, Tech Logic, Examples and Display Name are staged/finalized "
                "as separate business-rule values for each pair."
            )

            def _aligned(source: object, field: str, default: str | None = None) -> list[str | None]:
                try:
                    return align_pipe_values(source, pair_count, field, default=default)
                except ValueError:
                    return [str(source) if index == 0 and source is not None else default for index in range(pair_count)]

            definition_defaults = _aligned(definition_source, "Attribute Definition")
            description_defaults = _aligned(description_source, "Attribute Description")
            calculation_defaults = _aligned(calculation_source, "Calculation Logic", "NA")
            report_type_defaults = _aligned(report_type_source, "Report Type", "NA")
            tech_defaults = _aligned(tech_source, "Tech Logic")
            examples_defaults = _aligned(examples_source, "Examples")
            display_name_defaults = _aligned(display_name_source, "Display Name", attribute_name)
            try:
                display_order_defaults = align_int_pipe_values(display_order_source, pair_count, "Display Order", default=0)
            except ValueError:
                display_order_defaults = [int(rule.get("display_order") or 0) for _ in range(pair_count)]

            definition_entries: list[str] = []
            description_entries: list[str] = []
            calculation_entries: list[str] = []
            report_type_entries: list[str] = []
            tech_entries: list[str] = []
            examples_entries: list[str] = []
            display_order_entries: list[int] = []
            display_name_entries: list[str] = []

            for pair_index, (pair_section, pair_subsection) in enumerate(form_pairs):
                st.markdown(f"**{pair_section} / {pair_subsection}**")
                calc_col, report_col, order_col = st.columns([2.4, 1.1, 0.8])
                pair_calc = calc_col.text_area(
                    "Calculation Logic",
                    value=str(calculation_defaults[pair_index] or "NA"),
                    disabled=locked,
                    height=105,
                    key=f"{prefix}_calc_{pair_index}",
                    help=f"Calculation Logic for {pair_section} / {pair_subsection}.",
                )
                calculation_entries.append(pair_calc)
                report_type_entries.append(
                    report_col.text_input(
                        "Report Type",
                        value=str(report_type_defaults[pair_index] or "NA"),
                        disabled=locked,
                        key=f"{prefix}_report_type_{pair_index}",
                        help=f"Report Type for {pair_section} / {pair_subsection}.",
                    )
                )
                display_order_entries.append(
                    int(order_col.number_input(
                        "Display Order *",
                        min_value=0,
                        value=int(display_order_defaults[pair_index]),
                        step=1,
                        disabled=locked,
                        key=f"{prefix}_order_{pair_index}",
                    ))
                )

                detail_left, detail_right = st.columns(2)
                definition_entries.append(
                    detail_left.text_area(
                        "Attribute Definition",
                        value=str(definition_defaults[pair_index] or ""),
                        disabled=locked,
                        height=100,
                        key=f"{prefix}_definition_{pair_index}",
                    )
                )
                description_entries.append(
                    detail_right.text_area(
                        "Attribute Description",
                        value=str(description_defaults[pair_index] or ""),
                        disabled=locked,
                        height=100,
                        key=f"{prefix}_description_{pair_index}",
                    )
                )

                tech_key = f"{prefix}_tech_{pair_index}"
                tech_context_key = f"{prefix}_tech_context_{pair_index}"
                tech_calc_key = f"{prefix}_tech_source_calc_{pair_index}"
                tech_context = f"{prj_id}:{rule_index}:{pair_index}"
                stored_tech = str(tech_defaults[pair_index] or "").strip()
                if st.session_state.get(tech_context_key) != tech_context:
                    st.session_state[tech_key] = stored_tech or generate_tech_logic(pair_calc)
                    st.session_state[tech_context_key] = tech_context
                    st.session_state[tech_calc_key] = pair_calc
                elif st.session_state.get(tech_calc_key) != pair_calc:
                    st.session_state[tech_key] = generate_tech_logic(pair_calc)
                    st.session_state[tech_calc_key] = pair_calc

                tech_left, tech_right = st.columns(2)
                tech_entries.append(
                    tech_left.text_area(
                        "Tech Logic",
                        disabled=locked,
                        height=100,
                        key=tech_key,
                        help="Auto-generated from this scope's Calculation Logic; can be adjusted before saving.",
                    )
                )
                examples_entries.append(
                    tech_right.text_area(
                        "Examples (Prompt Management)",
                        value=str(examples_defaults[pair_index] or ""),
                        disabled=locked,
                        height=100,
                        key=f"{prefix}_examples_{pair_index}",
                    )
                )
                display_name_entries.append(
                    st.text_input(
                        "Display Name",
                        value=str(display_name_defaults[pair_index] or attribute_name),
                        disabled=locked,
                        key=f"{prefix}_display_{pair_index}",
                    )
                )
                st.divider()

            calculation_logic = "|".join(calculation_entries)
            report_type = "|".join(report_type_entries)
            attribute_definition = "|".join(definition_entries)
            attribute_description = "|".join(description_entries)
            tech_logic = "|".join(tech_entries)
            examples = "|".join(examples_entries)
            display_order = "|".join(str(value) for value in display_order_entries)
            display_name = "|".join(display_name_entries)
        else:
            calculation_logic = st.text_area(
                "Calculation Logic",
                value=str(calculation_source),
                disabled=locked,
                height=125,
                key=f"{prefix}_calc",
                help="Tech Logic is regenerated whenever Calculation Logic changes.",
            )
            report_type = st.text_input(
                "Report Type",
                value=str(report_type_source),
                disabled=locked,
                key=f"{prefix}_report_type",
                help="Report Type is part of the unique Scope key.",
            )
            detail_left, detail_right = st.columns(2)
            attribute_definition = detail_left.text_area(
                "Attribute Definition",
                value=str(definition_source),
                disabled=locked,
                height=125,
                key=f"{prefix}_definition",
            )
            attribute_description = detail_right.text_area(
                "Attribute Description",
                value=str(description_source),
                disabled=locked,
                height=125,
                key=f"{prefix}_description",
            )

            tech_key = f"{prefix}_tech"
            tech_context_key = f"{prefix}_tech_context"
            tech_calc_key = f"{prefix}_tech_source_calc"
            tech_context = f"{prj_id}:{rule_index}"
            stored_tech = str(tech_source or "").strip()
            if st.session_state.get(tech_context_key) != tech_context:
                st.session_state[tech_key] = stored_tech or generate_tech_logic(calculation_logic)
                st.session_state[tech_context_key] = tech_context
                st.session_state[tech_calc_key] = calculation_logic
            elif st.session_state.get(tech_calc_key) != calculation_logic:
                st.session_state[tech_key] = generate_tech_logic(calculation_logic)
                st.session_state[tech_calc_key] = calculation_logic

            tech_left, tech_right = st.columns(2)
            tech_logic = tech_left.text_area(
                "Tech Logic",
                disabled=locked,
                height=125,
                key=tech_key,
                help="Auto-populated from Calculation Logic and editable before saving.",
            )
            examples = tech_right.text_area(
                "Examples (Prompt Management)",
                value=str(examples_source),
                disabled=locked,
                height=100,
                key=f"{prefix}_examples",
            )
            c1, c2 = st.columns(2)
            display_order = int(c1.number_input(
                "Display Order *", min_value=0, value=int(display_order_source or 0), step=1,
                disabled=locked, key=f"{prefix}_order"
            ))
            display_name = c2.text_input(
                "Display Name", value=str(display_name_source), disabled=locked, key=f"{prefix}_display"
            )

    if locked:
        return None
    submitted = st.button(
        "Create Attribute" if not detail else "Save Changes",
        type="primary",
        key=f"{prefix}_submit",
        width="stretch",
    )
    if not submitted:
        return None
    if not prj_id:
        st.error("CFV ID is mandatory and must be generated before creating the attribute.")
        return None
    if not attribute_name.strip() or not section.strip() or not subsection.strip():
        st.error("PRJ Attribute Name, Section and Sub-Section are mandatory.")
        return None
    try:
        validated_pairs = pair_pipe_values(section, subsection)
        align_pipe_values(segment, len(validated_pairs), "Segment", default="NA")
        align_pipe_values(attribute_definition, len(validated_pairs), "Attribute Definition", default=None)
        align_pipe_values(attribute_description, len(validated_pairs), "Attribute Description", default=None)
        align_pipe_values(calculation_logic, len(validated_pairs), "Calculation Logic", default="NA")
        align_pipe_values(report_type, len(validated_pairs), "Report Type", default="NA")
        align_int_pipe_values(display_order, len(validated_pairs), "Display Order", default=0)
        align_pipe_values(tech_logic, len(validated_pairs), "Tech Logic", default=None)
        align_pipe_values(examples, len(validated_pairs), "Examples", default=None)
        align_pipe_values(display_name, len(validated_pairs), "Display Name", default=attribute_name)
    except ValueError as exc:
        st.error(str(exc))
        return None
    return {
        "prj_id": str(prj_id),
        "portfolio": portfolio,
        "source_abbr_name": source_code,
        "prj_attribute_name": attribute_name,
        "prj_physical_attribute_name": physical or None,
        "physical_name_source": "SUPPLIED" if detail else "AUTO",
        "section": section,
        "sub_section": subsection,
        "data_type": data_type,
        "calculated_or_reported": calculated,
        "calculation_logic": calculation_logic or "NA",
        "segment": segment or "NA",
        "report_type": report_type or "NA",
        "attribute_definition": attribute_definition or None,
        "attribute_description": attribute_description or None,
        "tech_logic": tech_logic or None,
        "display_order": display_order,
        "display_name": display_name or attribute_name,
        "examples": examples or None,
        "is_active": True,
    }


is_admin = bool(refreshed.get("is_admin"))
modal_active = bool(
    st.session_state.get("show_create")
    or st.session_state.get("show_edit")
    or st.session_state.get("show_cleanup")
)
main_tab_labels = ["Data Dictionary", "Prompt Management", "Audit"] + (["Admin Tools"] if is_admin else [])
main_tabs = st.tabs(main_tab_labels)

if st.session_state.get("flash_message"):
    st.success(st.session_state.pop("flash_message"))

with main_tabs[0]:
    workflow_labels = ["View / Edit Latest"] + (["Upload & Edit"] if is_admin else []) + ["Finalize and Upload"]
    workflow_tabs = st.tabs(workflow_labels)
    view_edit_tab = workflow_tabs[0]
    upload_tab = workflow_tabs[1] if is_admin else None
    finalize_tab = workflow_tabs[2] if is_admin else workflow_tabs[1]

    with view_edit_tab:
        title_col, clear_col = st.columns([6, 1.4])
        title_col.subheader("View Latest")
        clear_col.button(
            "Clear Filters",
            key="clear_view_filters",
            width="stretch",
            on_click=clear_view_filters,
            help="Clear all View Latest filters and reload the active grid.",
        )
        f1, f2, f3, f4 = st.columns(4)
        portfolios = f1.multiselect(
            "Portfolio",
            portfolio_labels,
            key="view_portfolio_filter",
            on_change=request_filter_submit,
            help="Select one or more portfolios; the grid refreshes immediately when the selection is committed.",
        )
        sources = f2.multiselect(
            "Source",
            source_options,
            format_func=source_label,
            key="view_source_filter",
            on_change=request_filter_submit,
            help="Select one or more sources; the grid refreshes immediately when the selection is committed.",
        )
        prj_filter = f3.text_input(
            "PRJ_ID",
            key="view_prj_id_filter",
            on_change=request_prj_filter_submit,
            help="Enter a PRJ_ID and press Enter to refresh View Latest immediately.",
        )
        name_filter = f4.text_input(
            "Attribute Name",
            key="view_attribute_name_filter",
            on_change=request_filter_submit,
            help="Enter an Attribute Name and press Enter to refresh the grid.",
        )
        f1, f2, f3, f4 = st.columns(4)
        definition_filter = f1.text_input(
            "Attribute Definition",
            key="view_attribute_definition_filter",
            on_change=request_filter_submit,
            help="Enter an Attribute Definition and press Enter to refresh the grid.",
        )
        section_filter = f2.selectbox(
            "Section",
            [""] + list(lookups.get("sections", [])),
            key="view_section_filter",
            on_change=request_filter_submit,
        )
        subsection_filter = f3.selectbox(
            "Sub-Section",
            [""] + list(lookups.get("subsections", [])),
            key="view_subsection_filter",
            on_change=request_filter_submit,
        )
        overlapped = f4.checkbox(
            "Overlapped Attribute only",
            key="view_overlapped_filter",
            on_change=request_filter_submit,
        )
        c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
        include_deleted = c1.checkbox(
            "Include inactive",
            value=False,
            key="view_include_inactive_filter",
            on_change=request_filter_submit,
        )
        page_size = c2.selectbox(
            "Rows",
            [50, 100, 250, 500],
            index=1,
            key="view_page_size_filter",
            on_change=request_filter_submit,
        )
        page_number = c3.number_input(
            "Page",
            min_value=1,
            value=1,
            step=1,
            key="view_page_number_filter",
            on_change=request_filter_submit,
        )
        search = c4.text_input(
            "Search",
            key="view_search_filter",
            on_change=request_filter_submit,
            help="Enter search text and press Enter to refresh the grid.",
        )

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

        create_col, deleted_col, _ = st.columns([1.7, 2.0, 5])
        if create_col.button("Create New Attribute", type="primary", width="stretch"):
            next_id = api("GET", "/lookups/next-prj-id")
            if next_id and next_id.get("prj_id"):
                st.session_state["create_next_prj_id"] = next_id
                st.session_state["show_create"] = True
                create_modal.open()
        if deleted_col.button(
            "Hide Soft Deleted Records" if st.session_state.get("show_soft_deleted") else "View Soft Deleted Records",
            width="stretch",
        ):
            st.session_state["show_soft_deleted"] = not st.session_state.get("show_soft_deleted", False)
            st.rerun()

        if st.session_state.get("show_soft_deleted"):
            soft_deleted_key = f"{st.session_state['environment']}:{st.session_state['database_type']}"
            if st.session_state.get("soft_deleted_cache_key") != soft_deleted_key or st.session_state.get("soft_deleted_cache") is None:
                st.session_state["soft_deleted_cache"] = api("GET", "/data-dictionary/soft-deleted", quiet=True) or []
                st.session_state["soft_deleted_cache_key"] = soft_deleted_key
            deleted_rows = st.session_state.get("soft_deleted_cache") or []
            st.markdown("#### Soft Deleted Records")
            st.caption(
                "These records are inactive in the final tables. Pending soft deletes remain in Delta until finalized."
            )
            if deleted_rows:
                deleted_frame = pd.DataFrame(deleted_rows)
                deleted_columns = [
                    "prj_id", "prj_attribute_name", "prj_attribute_definition",
                    "prj_physical_attribute_name", "portfolios", "sources",
                    "section", "subsection", "report_type", "is_active",
                ]
                deleted_visible_frame = deleted_frame[
                    [column for column in deleted_columns if column in deleted_frame.columns]
                ].reset_index(drop=True)
                deleted_grid_event = st.dataframe(
                    deleted_visible_frame,
                    width="stretch",
                    hide_index=True,
                    height=330,
                    key="soft_deleted_grid",
                    on_select="rerun",
                    selection_mode="single-row",
                )
                deleted_selected_indexes = list(getattr(deleted_grid_event.selection, "rows", []) or [])
                deleted_selected_row = (
                    deleted_frame.iloc[deleted_selected_indexes[0]].to_dict()
                    if deleted_selected_indexes
                    else None
                )
                reactivate_prj = (
                    str(deleted_selected_row.get("prj_id"))
                    if deleted_selected_row and deleted_selected_row.get("prj_id")
                    else ""
                )
                if reactivate_prj:
                    st.caption(
                        f"Selected soft-deleted attribute: {reactivate_prj} - "
                        f"{deleted_selected_row.get('prj_attribute_name', '')}"
                    )
                if st.button(
                    "Reactivate Selected Soft Deleted Record",
                    disabled=not reactivate_prj,
                    key="reactivate_soft_deleted",
                    type="primary",
                ):
                    response = api("POST", f"/data-dictionary/attributes/{reactivate_prj}/reactivate")
                    if response:
                        st.session_state["audit_cache_rows"] = None
                        st.success(
                            "Reactivation staged. The record remains in this soft-deleted grid until Finalize and Upload completes."
                        )
            else:
                st.info("No finalized soft deleted records found.")
            st.divider()

        filter_signature = json.dumps(payload, sort_keys=True, default=str)

        # Every View Latest filter shares the same refresh path. Text inputs
        # (PRJ_ID, Attribute Name/Definition, Search) submit when Enter is pressed;
        # selection widgets refresh as soon as their selection is committed.
        if st.session_state.get("prj_filter_submit_requested"):
            # Preserve the original PRJ_ID Enter-submit contract while routing
            # the actual refresh through the shared all-filter path.
            st.session_state["filter_submit_requested"] = True
            st.session_state["prj_filter_submit_requested"] = False

        if st.session_state.get("filter_submit_requested"):
            result = api("POST", "/data-dictionary/filter-page", json=payload)
            st.session_state["filter_submit_requested"] = False
            if result:
                st.session_state["view_rows"] = result.get("rows", [])
                st.session_state["view_total"] = result.get("total", 0)
                st.session_state["view_filter_signature"] = filter_signature
                st.session_state["view_loaded"] = True

        if not st.session_state.get("view_loaded"):
            result = api("POST", "/data-dictionary/filter-page", json=payload, quiet=True)
            if result:
                st.session_state["view_rows"] = result.get("rows", [])
                st.session_state["view_total"] = result.get("total", 0)
                st.session_state["view_filter_signature"] = filter_signature
                st.session_state["view_loaded"] = True
        rows = st.session_state.get("view_rows", [])

        b1, b2, b3, b4 = st.columns([1.2, 1.2, 1.2, 4])
        if b1.button("View Latest", width="stretch"):
            result = api("POST", "/data-dictionary/filter-page", json=payload)
            if result:
                st.session_state["view_rows"] = result.get("rows", [])
                st.session_state["view_total"] = result.get("total", 0)
                st.session_state["view_filter_signature"] = filter_signature
                st.session_state["view_loaded"] = True
                rows = st.session_state["view_rows"]
        if b2.button("Download Latest", width="stretch"):
            response = api("GET", "/data-dictionary/download-latest", binary=True)
            if response:
                st.session_state["latest_excel"] = response.content
        if st.session_state.get("latest_excel"):
            b3.download_button(
                "Download Excel",
                st.session_state["latest_excel"],
                "prj_master_dictionary_latest.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
        b4.caption(f"{st.session_state.get('view_total', 0)} matching attribute(s)")
        if st.session_state.get("view_filter_signature") and st.session_state.get("view_filter_signature") != filter_signature:
            st.caption(
                "Filters changed. Press **Enter** in a text filter or commit the selection to refresh; "
                "**View Latest** remains available as a manual refresh."
            )

        if rows:
            grid_columns = [
                "scope_id", "prj_id", "prj_attribute_name", "prj_attribute_definition",
                "prj_attribute_description", "prj_physical_attribute_name", "editable", "symbol", "portfolios", "sources",
                "section", "subsection", "segment", "report_type", "display_order", "is_active",
            ]
            frame = pd.DataFrame(rows)
            visible_frame = frame[[c for c in grid_columns if c in frame.columns]].reset_index(drop=True)
            grid_event = st.dataframe(
                visible_frame,
                width="stretch",
                hide_index=True,
                height=430,
                key="view_latest_grid",
                on_select="rerun",
                selection_mode="single-row",
            )
            selected_indexes = list(getattr(grid_event.selection, "rows", []) or [])
            selected_row = frame.iloc[selected_indexes[0]].to_dict() if selected_indexes else None
            selected_prj = str(selected_row.get("prj_id")) if selected_row and selected_row.get("prj_id") else ""
            if selected_prj:
                st.caption(f"Selected attribute: {selected_prj} - {selected_row.get('prj_attribute_name', '')}")

            action1, action2, action3, _ = st.columns([1.2, 1.2, 1.2, 4])
            if action1.button("Edit", disabled=not selected_prj, width="stretch"):
                detail = api("GET", f"/data-dictionary/attributes/{selected_prj}") if selected_prj else None
                if detail:
                    st.session_state["selected_prj"] = selected_prj
                    st.session_state["edit_detail"] = detail
                    selected_scope_id = selected_row.get("scope_id") if selected_row else None
                    if selected_scope_id is not None:
                        for index, rule_row in enumerate(detail.get("rules") or []):
                            if str(rule_row.get("scope_id")) == str(selected_scope_id):
                                st.session_state["edit_rule"] = index
                                break
                    st.session_state["show_edit"] = True
                    st.session_state["edit_unlocked"] = True
                    edit_modal.open()
            if action2.button("Soft Delete", disabled=not selected_prj, width="stretch"):
                response = api("DELETE", f"/data-dictionary/attributes/{selected_prj}")
                if response:
                    st.session_state["flash_message"] = (
                        f"{selected_prj} soft delete staged successfully. Review Delta, then Finalize and Upload."
                    )
                    st.session_state["audit_cache_rows"] = None
                    st.session_state["soft_deleted_cache"] = None
                    st.rerun()
            if action3.button("Reactivate", disabled=not selected_prj, width="stretch"):
                response = api("POST", f"/data-dictionary/attributes/{selected_prj}/reactivate")
                if response:
                    st.session_state["flash_message"] = (
                        f"{selected_prj} reactivation staged successfully. Review Delta, then Finalize and Upload."
                    )
                    st.session_state["audit_cache_rows"] = None
                    st.session_state["soft_deleted_cache"] = None
                    st.rerun()
        else:
            st.info("No records loaded for the selected filters.")

    if is_admin and upload_tab is not None:
        with upload_tab:
            st.subheader("Bulk Upload: Single Sheet or Multi-Sheet Merger")
            st.caption(
                "Each selected sheet has its own header row, data-start row, portfolio and source-column mapping. "
                "Portfolio is auto-detected from the sheet name when possible and can be changed from the dropdown."
            )
            uploaded = st.file_uploader("Master Dictionary Excel", type=["xlsx"], key="master_upload_file")
            if uploaded:
                file_bytes = uploaded.getvalue()
                file_fingerprint = hashlib.sha256(file_bytes).hexdigest()
                file_tuple = (uploaded.name, file_bytes, uploaded.type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                if st.session_state.get("upload_file_fingerprint") != file_fingerprint:
                    st.session_state["upload_file_fingerprint"] = file_fingerprint
                    st.session_state["upload_sheet_names"] = []
                    st.session_state["upload_sheet_preview_cache"] = {}
                    st.session_state["upload_preview"] = None
                    st.session_state["upload_stage_result"] = None
                if not st.session_state.get("upload_sheet_names"):
                    sheets_result = api("POST", "/master-upload/sheets", files={"file": file_tuple})
                    st.session_state["upload_sheet_names"] = sheets_result.get("sheets", []) if sheets_result else []
                sheets = st.session_state.get("upload_sheet_names", [])
                mode_type = st.radio("Sheet mode", ["Single Sheet", "Multi-Sheet Merger"], horizontal=True)
                selected_sheets = (
                    [st.selectbox("Sheet", sheets)] if mode_type == "Single Sheet" and sheets
                    else st.multiselect("Sheets to merge", sheets, default=sheets[: min(2, len(sheets))])
                )
                configs: list[dict[str, Any]] = []
                for sheet_name in selected_sheets:
                    with st.expander(f"Mapping: {sheet_name}", expanded=True):
                        c1, c2, c3 = st.columns(3)
                        header_row = c1.number_input(
                            "Header row (1-based)",
                            min_value=1,
                            max_value=50,
                            value=2,
                            step=1,
                            key=f"header_{sheet_name}",
                            help="Excel row containing the actual column names.",
                        )
                        data_start_key = f"data_start_{sheet_name}"
                        minimum_data_row = int(header_row) + 1
                        if data_start_key not in st.session_state:
                            st.session_state[data_start_key] = minimum_data_row
                        elif int(st.session_state[data_start_key]) < minimum_data_row:
                            st.session_state[data_start_key] = minimum_data_row
                        data_start_row = c2.number_input(
                            "Data starts at row (1-based)",
                            min_value=minimum_data_row,
                            max_value=500,
                            step=1,
                            key=data_start_key,
                            help="Use this to skip second/third header or explanatory rows after the selected header row.",
                        )
                        detected_portfolio = portfolio_from_sheet_name(sheet_name)
                        detected_portfolio_label = canonical_portfolio_label(detected_portfolio) if detected_portfolio else ""
                        portfolio_choices = [""] + list(bulk_portfolio_options)
                        portfolio_index = (
                            portfolio_choices.index(detected_portfolio_label)
                            if detected_portfolio_label in portfolio_choices
                            else 0
                        )
                        portfolio_override = c3.selectbox(
                            "Portfolio",
                            portfolio_choices,
                            index=portfolio_index,
                            key=f"port_{sheet_name}",
                            format_func=lambda value: value or "Auto-detect from sheet name",
                            help=(
                                "Automatically defaults from the sheet name: e.g. 'Insurance Attribute' → FI Insurance, "
                                "'Bank Attribute' → FI Banks. Select another value only when you want to override detection."
                            ),
                        )
                        preview_cache_key = f"{file_fingerprint}:{sheet_name}:{int(header_row)}:{int(data_start_row)}"
                        preview_cache = st.session_state.setdefault("upload_sheet_preview_cache", {})
                        if preview_cache_key not in preview_cache:
                            preview_cache[preview_cache_key] = api(
                                "POST",
                                "/master-upload/preview-sheet",
                                files={"file": file_tuple},
                                data={
                                    "sheet_name": sheet_name,
                                    "header_row": int(header_row),
                                    "data_start_row": int(data_start_row),
                                },
                                quiet=True,
                            )
                        preview = preview_cache.get(preview_cache_key)
                        mapping: dict[str, str] = {}
                        if preview:
                            st.caption(
                                f"Portfolio from sheet name: {preview.get('portfolio_detected') or 'Not detected'} | "
                                f"Rows skipped after header: {preview.get('skipped_rows_after_header', 0)}"
                            )
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
                            st.dataframe(pd.DataFrame(preview.get("preview", [])), width="stretch", hide_index=True, height=220)
                        configs.append({
                            "sheet_name": sheet_name,
                            "header_row": int(header_row),
                            "data_start_row": int(data_start_row),
                            "portfolio_override": portfolio_override,
                            "mapping": mapping,
                        })
                upload_mode = st.radio(
                    "Database raw-load mode",
                    ["MERGE", "INSERT_ONLY", "REPLACE"],
                    horizontal=True,
                    help=(
                        "MERGE inserts new and updates matching staged/raw records. "
                        "INSERT_ONLY skips PRJ IDs already present in raw, staging or final tables. "
                        "REPLACE clears current raw/staging pending data before loading; final tables remain unchanged until finalization."
                    ),
                )
                health_key = f"{API}:{st.session_state['environment']}:{st.session_state['database_type']}"
                if st.session_state.get("backend_health_key") != health_key or st.session_state.get("backend_health") is None:
                    st.session_state["backend_health"] = api("GET", "/health", quiet=True) or {}
                    st.session_state["backend_health_key"] = health_key
                backend_health = st.session_state.get("backend_health") or {}
                backend_modes = backend_health.get("upload_modes") or []
                backend_supports_current_mode = upload_mode in backend_modes
                if backend_health and not backend_supports_current_mode:
                    st.error(
                        "The FastAPI process is running an older application build and does not advertise support for "
                        f"{upload_mode}. Restart FastAPI using the latest project files before validating or staging."
                    )
                u1, u2 = st.columns(2)
                if u1.button(
                    "Validate and Compare",
                    disabled=not configs or (bool(backend_health) and not backend_supports_current_mode),
                ):
                    preview = api(
                        "POST",
                        "/master-upload/preview",
                        files={"file": file_tuple},
                        data={"configurations_json": json.dumps(configs), "mode": upload_mode},
                    )
                    st.session_state["upload_preview"] = preview
                if u2.button(
                    "Stage Uploaded Data",
                    type="primary",
                    disabled=(
                        not configs
                        or not refreshed.get("is_admin")
                        or (bool(backend_health) and not backend_supports_current_mode)
                    ),
                ):
                    result = api(
                        "POST",
                        "/master-upload/finalize",
                        files={"file": file_tuple},
                        data={"configurations_json": json.dumps(configs), "mode": upload_mode},
                    )
                    if result:
                        st.session_state["upload_stage_result"] = result
                        st.session_state["audit_cache_rows"] = None
                        st.session_state["prompts_cache"] = None
                        st.success(
                            f"Staged {result.get('staged_count', 0)} rows; "
                            f"skipped existing {result.get('skipped_existing_count', 0)} PRJ ID(s); "
                            f"rejected {result.get('rejected_count', 0)} rows. "
                            "Final dbo master/business-rule tables are unchanged until Finalize and Upload."
                        )

                validation = st.session_state.get("upload_preview")
                if validation:
                    st.markdown("#### Validate & Compare Summary")
                    delta = validation.get("delta") or {}
                    summary = delta.get("summary") or {}
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Records to Insert", int(summary.get("inserted", 0)))
                    m2.metric("Records to Update", int(summary.get("updated", 0)))
                    m3.metric("Records to Delete", int(summary.get("deleted", 0)))
                    m4.metric("Unchanged", int(summary.get("unchanged", 0)))
                    st.caption(
                        f"Valid rows: {validation.get('valid_count', 0)} | "
                        f"Eligible rows: {validation.get('eligible_count', 0)} | "
                        f"Skipped existing: {validation.get('skipped_existing_count', 0)} | "
                        f"Rejected: {len(validation.get('rejected') or [])}"
                    )
                    delta_rows = delta.get("rows") or []
                    if delta_rows:
                        st.markdown("##### Changed PRJ IDs")
                        st.dataframe(pd.DataFrame(delta_rows), width="stretch", hide_index=True, height=260)
                    change_rows = delta.get("changes") or []
                    if change_rows:
                        st.markdown("##### Before / After Changes")
                        st.dataframe(
                            pd.DataFrame(change_rows)[
                                ["prj_id", "change_type", "scope", "field", "before_value", "after_value"]
                            ],
                            width="stretch",
                            hide_index=True,
                            height=420,
                        )
                    rejected_rows = validation.get("rejected") or []
                    if rejected_rows:
                        with st.expander(f"Rejected rows ({len(rejected_rows)})"):
                            st.dataframe(pd.DataFrame(rejected_rows), width="stretch", hide_index=True)

                stage_result = st.session_state.get("upload_stage_result")
                if stage_result:
                    st.caption(
                        f"Last stage: {stage_result.get('staged_count', 0)} staged, "
                        f"{stage_result.get('skipped_existing_count', 0)} skipped, "
                        f"{stage_result.get('rejected_count', 0)} rejected."
                    )

    with finalize_tab:
        st.subheader("Finalize and Upload")
        delta = (
            {"rows": [], "has_changes": False, "count": 0}
            if modal_active
            else (api("GET", "/data-dictionary/delta", quiet=True) or {"rows": [], "has_changes": False, "count": 0})
        )
        st.caption(f"Pending delta: {delta.get('count', 0)} attribute(s)")
        if delta.get("rows"):
            st.dataframe(pd.DataFrame(delta["rows"]), width="stretch", hide_index=True)
        else:
            st.info("No staged changes. Finalize is disabled.")
        if is_admin:
            c1, c2 = st.columns(2)
        else:
            c1 = st.container()
            c2 = None
        if c1.button("Finalize and Upload", type="primary", disabled=not delta.get("has_changes"), width="stretch"):
            finalize_modal.open()
        if is_admin and c2 is not None:
            if c2.button("Save Final Tables to S3", width="stretch"):
                result = api("POST", "/s3/export-final")
                if result:
                    st.success(f"Uploaded {len(result.get('files', []))} final-table extract(s) to S3.")
                    st.json(result)

with main_tabs[1]:
    st.subheader("Prompt Management")
    prompts_key = f"{st.session_state['environment']}:{st.session_state['database_type']}"
    if not modal_active and (
        st.session_state.get("prompts_cache_key") != prompts_key or st.session_state.get("prompts_cache") is None
    ):
        st.session_state["prompts_cache"] = api("GET", "/prompts?include_deleted=true", quiet=True) or []
        st.session_state["prompts_cache_key"] = prompts_key
    prompts = st.session_state.get("prompts_cache") or []
    if prompts:
        search_prompt = st.text_input("Search prompts")
        filtered = prompts
        if search_prompt:
            needle = search_prompt.lower()
            filtered = [row for row in prompts if needle in json.dumps(row, default=str).lower()]
        st.dataframe(pd.DataFrame(filtered), width="stretch", hide_index=True, height=420)
        scope_ids = [int(row["scope_id"]) for row in filtered]
        selected_scope = st.selectbox("Select scope_id", scope_ids)
        current = next(row for row in filtered if int(row["scope_id"]) == int(selected_scope))
        prompt_description = st.text_area("Prompt Description", value=str(current.get("prompt_description") or ""), height=150)
        examples = st.text_area("Examples", value=str(current.get("examples") or ""), height=120)
        if st.button("Stage Prompt Changes", type="primary"):
            response = api("PUT", f"/prompts/{selected_scope}", json={"scope_id": selected_scope, "prompt_description": prompt_description or None, "examples": examples or None})
            if response:
                st.session_state["prompts_cache"] = None
                st.session_state["audit_cache_rows"] = None
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
    audit_payload = {
        "table_name": table_name or None,
        "action": action or None,
        "performed_by": performed_by or None,
        "source_operation": source_operation or None,
        "search": audit_search or None,
    }
    audit_signature = f"{st.session_state['environment']}:{st.session_state['database_type']}:" + json.dumps(audit_payload, sort_keys=True)
    if not modal_active and (
        st.session_state.get("audit_cache_signature") != audit_signature or st.session_state.get("audit_cache_rows") is None
    ):
        st.session_state["audit_cache_rows"] = api("POST", "/audit/filter", json=audit_payload, quiet=True) or []
        st.session_state["audit_cache_signature"] = audit_signature
    audit_rows = st.session_state.get("audit_cache_rows") or []
    if audit_rows:
        st.dataframe(pd.DataFrame(audit_rows), width="stretch", hide_index=True, height=520)
    else:
        st.info("No audit rows found for the selected filters.")

if is_admin:
    with main_tabs[3]:
        st.subheader("Admin Tools")
        admin_portfolios_key = f"{st.session_state['environment']}:{st.session_state['database_type']}"
        if not modal_active and (
            st.session_state.get("admin_portfolios_cache_key") != admin_portfolios_key
            or st.session_state.get("admin_portfolios_cache") is None
        ):
            st.session_state["admin_portfolios_cache"] = api("GET", "/portfolio-reference", quiet=True) or []
            st.session_state["admin_portfolios_cache_key"] = admin_portfolios_key
        portfolios_admin = st.session_state.get("admin_portfolios_cache") or []
        st.markdown("#### Portfolio Reference")
        if portfolios_admin:
            st.dataframe(pd.DataFrame(portfolios_admin), width="stretch", hide_index=True)
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
                    st.session_state["lookup_cache"] = None
                    st.session_state["admin_portfolios_cache"] = None
                    st.session_state["audit_cache_rows"] = None
                    st.success(f"Created port_ref_id {result.get('port_ref_id')}")
        st.divider()
        st.markdown("#### Database Cleanup")
        st.warning(
            "Cleanup permanently hard-deletes Data Dictionary raw, staging, final and audit rows "
            "for the currently selected Environment/Database. The four required Portfolio seed rows and the read-only Source reference table are preserved."
        )
        if st.button("Cleanup Database", key="open_cleanup_database", width="stretch"):
            st.session_state["show_cleanup"] = True
            st.session_state["cleanup_step"] = 1
            st.session_state.pop("cleanup_confirmation_text", None)
            st.session_state.pop("cleanup_irreversible_ack", None)
            cleanup_modal.open()
            st.rerun()

        st.markdown("#### Deployment")
        st.code("poetry run uvicorn DataDictionaryAdminApp.api.swagger_app:app --host 0.0.0.0 --port 8503")
        st.code("poetry run streamlit run src/DataDictionaryAdminApp/streamlit_app.py --server.port 8501")
        if refreshed.get("db_type") == "POSTGRES":
            st.caption("Run sql/postgres/001_create_tables.sql, then sql/postgres/002_validate_schema.sql before enabling PostgreSQL writes.")
        else:
            st.caption("Run sql/001_create_tables.sql, then sql/002_validate_schema.sql before enabling SQL Server writes.")

if st.session_state.get("show_create") and create_modal.is_open():
    with create_modal.container():
        render_attribute_modal_style("create_attribute_modal")
        payload = attribute_form("create")
        if payload:
            result = api("POST", "/data-dictionary/attributes", json=payload)
            if result:
                staged_tables = ", ".join(result.get("staged_tables", []))
                generated_id = result.get("cfv_id") or result.get("prj_id")
                st.session_state["flash_message"] = (
                    f"CFV ID generated: {generated_id}. Attribute staged successfully. "
                    f"Physical name: {result.get('prj_physical_attribute_name')}. "
                    f"Saved to: {staged_tables}"
                )
                st.session_state["audit_cache_rows"] = None
                st.session_state["prompts_cache"] = None
                st.session_state.pop("create_next_prj_id", None)
                st.session_state.pop("create_prj", None)
                st.session_state.pop("create_physical_suggestion", None)
                create_modal.close()
        if st.button("Close", key="create_close"):
            st.session_state.pop("create_next_prj_id", None)
            st.session_state.pop("create_prj", None)
            st.session_state.pop("create_physical_suggestion", None)
            create_modal.close()

if st.session_state.get("show_edit") and edit_modal.is_open():
    selected_prj = st.session_state.get("selected_prj")
    detail = st.session_state.get("edit_detail")
    with edit_modal.container():
        render_attribute_modal_style("edit_attribute_modal")
        if detail:
            payload = attribute_form("edit", detail, locked=False)
            if payload:
                result = api("PUT", f"/data-dictionary/attributes/{selected_prj}", json=payload)
                if result:
                    st.session_state["flash_message"] = (
                        f"{selected_prj} changes staged successfully. Review the delta before finalization."
                    )
                    st.session_state["audit_cache_rows"] = None
                    st.session_state["prompts_cache"] = None
                    st.session_state["edit_unlocked"] = False
                    st.session_state["edit_detail"] = None
                    edit_modal.close()
        if st.button("Close", key="edit_close"):
            st.session_state["edit_unlocked"] = False
            st.session_state["edit_detail"] = None
            edit_modal.close()

if st.session_state.get("show_cleanup"):
    if not cleanup_modal.is_open():
        cleanup_modal.open()
    if cleanup_modal.is_open():
        with cleanup_modal.container():
            selected_environment = st.session_state.get("environment", "LOCAL")
            selected_database_type = st.session_state.get("database_type", "SQLSERVER")
            selected_database_name = str((st.session_state.get("runtime_context") or {}).get("database", "Unknown"))
            st.error("Destructive operation: hard delete")
            st.write(
                f"**Environment:** {selected_environment}  |  "
                f"**Database Type:** {selected_database_type}  |  "
                f"**Database:** {selected_database_name}"
            )
            st.caption(
                "The following data is permanently deleted: raw attributes, staging master/rules, "
                "final master/rules, audit history and custom Portfolio rows. Required Portfolio seed rows (IDs 1-4) and Data Sources are preserved."
            )

            if int(st.session_state.get("cleanup_step", 1)) == 1:
                st.markdown("### Confirmation 1 of 2")
                st.warning(
                    "This cannot be undone from the application. Confirm that you want to continue to the final cleanup confirmation."
                )
                c1, c2 = st.columns(2)
                if c1.button("Yes, continue", key="cleanup_first_confirm", type="primary", width="stretch"):
                    st.session_state["cleanup_step"] = 2
                    st.rerun()
                if c2.button("Cancel", key="cleanup_cancel_first", width="stretch"):
                    st.session_state["show_cleanup"] = False
                    st.session_state["cleanup_step"] = 0
                    cleanup_modal.close()
                    st.rerun()
            else:
                st.markdown("### Confirmation 2 of 2")
                st.error("Final confirmation: type **DELETE ALL DATA** exactly, then acknowledge the irreversible delete.")
                confirmation_text = st.text_input(
                    "Type DELETE ALL DATA",
                    key="cleanup_confirmation_text",
                    placeholder="DELETE ALL DATA",
                )
                irreversible_ack = st.checkbox(
                    "I understand this permanently hard-deletes the selected database's dictionary data.",
                    key="cleanup_irreversible_ack",
                )
                valid_confirmation = confirmation_text.strip().upper() == "DELETE ALL DATA" and irreversible_ack
                c1, c2 = st.columns(2)
                if c1.button(
                    "Permanently Delete Data",
                    key="cleanup_final_confirm",
                    type="primary",
                    disabled=not valid_confirmation,
                    width="stretch",
                ):
                    result = api(
                        "POST",
                        "/system/cleanup",
                        json={
                            "first_confirmation": True,
                            "second_confirmation": True,
                            "confirmation_text": confirmation_text,
                        },
                    )
                    if result:
                        deleted_total = int(result.get("deleted_total", 0))
                        st.session_state["view_rows"] = []
                        st.session_state["view_total"] = 0
                        st.session_state["view_loaded"] = False
                        st.session_state["selected_prj"] = ""
                        st.session_state["edit_detail"] = None
                        st.session_state["upload_preview"] = None
                        st.session_state["upload_stage_result"] = None
                        st.session_state["prompts_cache"] = None
                        st.session_state["audit_cache_rows"] = None
                        st.session_state["soft_deleted_cache"] = None
                        st.session_state["show_soft_deleted"] = False
                        st.session_state["lookup_cache"] = None
                        st.session_state["show_cleanup"] = False
                        st.session_state["cleanup_step"] = 0
                        st.session_state["flash_message"] = (
                            f"Database cleanup completed. {deleted_total} row(s) were permanently deleted. "
                            "Required Portfolio seed rows (IDs 1-4) and Data Sources were preserved."
                        )
                        cleanup_modal.close()
                        st.rerun()
                if c2.button("Cancel", key="cleanup_cancel_final", width="stretch"):
                    st.session_state["show_cleanup"] = False
                    st.session_state["cleanup_step"] = 0
                    cleanup_modal.close()
                    st.rerun()


if finalize_modal.is_open():
    with finalize_modal.container():
        st.warning("Do you want to update database tables?")
        c1, c2 = st.columns(2)
        if c1.button("Yes Upload", type="primary", width="stretch"):
            result = api("POST", "/data-dictionary/finalize", json={"confirm": True})
            if result:
                st.session_state["view_loaded"] = False
                st.session_state["lookup_cache"] = None
                st.session_state["prompts_cache"] = None
                st.session_state["audit_cache_rows"] = None
                st.session_state["admin_portfolios_cache"] = None
                st.session_state["soft_deleted_cache"] = None
                st.session_state["upload_preview"] = None
                st.session_state["upload_stage_result"] = None
                st.success(result.get("message", "Finalized successfully."))
                finalize_modal.close()
                st.rerun()
        if c2.button("Cancel", width="stretch"):
            finalize_modal.close()
            st.rerun()
