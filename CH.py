import json
import requests
import pandas as pd
import streamlit as st
from requests.auth import HTTPBasicAuth


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Companies House Explorer",
    layout="wide"
)

BASE_URL = "https://api.company-information.service.gov.uk"


# ============================================================
# COMPANIES HOUSE API FUNCTIONS
# ============================================================

def call_companies_house_api(api_key, endpoint, params=None):
    """
    Generic function for calling Companies House API.
    """

    url = f"{BASE_URL}{endpoint}"

    try:
        response = requests.get(
            url,
            params=params,
            auth=HTTPBasicAuth(api_key, ""),
            timeout=30
        )

        if response.status_code == 200:
            return response.json()

        elif response.status_code == 401:
            st.error(
                "401 Unauthorized. Please check your Companies House API key."
            )
            return None

        elif response.status_code == 404:
            st.error("404 - Resource not found.")
            return None

        elif response.status_code == 429:
            st.error(
                "429 - Companies House API rate limit exceeded."
            )
            return None

        else:
            st.error(
                f"API Error {response.status_code}: "
                f"{response.text}"
            )
            return None

    except requests.exceptions.Timeout:
        st.error("Companies House API request timed out.")
        return None

    except requests.exceptions.ConnectionError:
        st.error(
            "Unable to connect to Companies House API."
        )
        return None

    except Exception as e:
        st.error(f"Unexpected error: {str(e)}")
        return None


# ============================================================
# SEARCH COMPANIES
# ============================================================

def search_companies(api_key, company_name):

    return call_companies_house_api(
        api_key,
        "/search/companies",
        params={
            "q": company_name,
            "items_per_page": 20
        }
    )


# ============================================================
# GET COMPANY PROFILE
# ============================================================

def get_company_profile(api_key, company_number):

    return call_companies_house_api(
        api_key,
        f"/company/{company_number}"
    )


# ============================================================
# GET COMPANY OFFICERS
# ============================================================

def get_company_officers(api_key, company_number):

    return call_companies_house_api(
        api_key,
        f"/company/{company_number}/officers",
        params={
            "items_per_page": 100
        }
    )


# ============================================================
# GET FILING HISTORY
# ============================================================

def get_filing_history(api_key, company_number):

    return call_companies_house_api(
        api_key,
        f"/company/{company_number}/filing-history",
        params={
            "items_per_page": 100
        }
    )


# ============================================================
# ADDRESS FORMATTER
# ============================================================

def format_address(address):

    if not address:
        return ""

    fields = [
        address.get("premises"),
        address.get("address_line_1"),
        address.get("address_line_2"),
        address.get("locality"),
        address.get("region"),
        address.get("postal_code"),
        address.get("country")
    ]

    return ", ".join(
        str(value)
        for value in fields
        if value
    )


# ============================================================
# OFFICER DATAFRAME
# ============================================================

def create_officers_dataframe(data):

    rows = []

    if not data:
        return pd.DataFrame()

    for officer in data.get("items", []):

        dob = officer.get("date_of_birth", {})

        dob_value = ""

        if dob:
            month = dob.get("month")
            year = dob.get("year")

            if month and year:
                dob_value = f"{month:02d}/{year}"

        rows.append({
            "Name": officer.get("name"),
            "Role": officer.get("officer_role"),
            "Appointed": officer.get("appointed_on"),
            "Resigned": officer.get("resigned_on"),
            "Nationality": officer.get("nationality"),
            "Country of Residence":
                officer.get("country_of_residence"),
            "Occupation": officer.get("occupation"),
            "Date of Birth": dob_value,
            "Address": format_address(
                officer.get("address", {})
            )
        })

    return pd.DataFrame(rows)


# ============================================================
# FILING HISTORY DATAFRAME
# ============================================================

def create_filing_dataframe(data):

    rows = []

    if not data:
        return pd.DataFrame()

    for filing in data.get("items", []):

        rows.append({
            "Date": filing.get("date"),
            "Type": filing.get("type"),
            "Category": filing.get("category"),
            "Description": filing.get("description"),
            "Barcode": filing.get("barcode"),
            "Transaction ID":
                filing.get("transaction_id")
        })

    return pd.DataFrame(rows)


# ============================================================
# UI
# ============================================================

st.title("UK Companies House Explorer")

st.write(
    "Search UK companies and retrieve company profile, "
    "directors/officers and filing history."
)


# ============================================================
# SIDEBAR - API KEY
# ============================================================

st.sidebar.header("Companies House API")

api_key = st.sidebar.text_input(
    "Companies House API Key",
    type="password",
    placeholder="Paste your API key here"
)

st.sidebar.caption(
    "The API key is used only for the current Streamlit session."
)


# ============================================================
# API KEY VALIDATION
# ============================================================

if not api_key:

    st.info(
        "Enter your Companies House API key in the sidebar."
    )

    st.stop()


# ============================================================
# SEARCH SECTION
# ============================================================

st.subheader("Search Company")

company_name = st.text_input(
    "Company Name",
    placeholder="Example: Barclays"
)

search_button = st.button(
    "Search",
    type="primary"
)


# ============================================================
# SESSION STATE
# ============================================================

if "search_results" not in st.session_state:
    st.session_state.search_results = None


# ============================================================
# SEARCH
# ============================================================

if search_button:

    if not company_name.strip():

        st.warning("Please enter a company name.")

    else:

        with st.spinner(
            "Searching Companies House..."
        ):

            results = search_companies(
                api_key,
                company_name
            )

        st.session_state.search_results = results


# ============================================================
# DISPLAY SEARCH RESULTS
# ============================================================

results = st.session_state.search_results


if results:

    companies = results.get("items", [])

    if len(companies) == 0:

        st.warning("No companies found.")

    else:

        st.success(
            f"{results.get('total_results', len(companies))} "
            f"companies found."
        )


        # ----------------------------------------------------
        # SEARCH RESULTS TABLE
        # ----------------------------------------------------

        rows = []

        for company in companies:

            rows.append({
                "Company Name":
                    company.get("title"),

                "Company Number":
                    company.get("company_number"),

                "Status":
                    company.get("company_status"),

                "Company Type":
                    company.get("company_type"),

                "Created":
                    company.get("date_of_creation"),

                "Address":
                    company.get("address_snippet")
            })


        search_df = pd.DataFrame(rows)


        st.subheader("Search Results")

        st.dataframe(
            search_df,
            use_container_width=True,
            hide_index=True
        )


        # ----------------------------------------------------
        # COMPANY SELECT BOX
        # ----------------------------------------------------

        company_options = {}

        for company in companies:

            label = (
                f"{company.get('title')} "
                f"[{company.get('company_number')}]"
            )

            company_options[label] = (
                company.get("company_number")
            )


        selected_company = st.selectbox(
            "Select Company",
            options=list(company_options.keys())
        )


        selected_company_number = (
            company_options[selected_company]
        )


        # ----------------------------------------------------
        # LOAD COMPANY
        # ----------------------------------------------------

        if st.button("Load Company Details"):

            st.session_state.company_number = (
                selected_company_number
            )


# ============================================================
# COMPANY DETAILS
# ============================================================

if "company_number" in st.session_state:

    company_number = (
        st.session_state.company_number
    )

    st.divider()

    with st.spinner(
        "Loading company information..."
    ):

        profile = get_company_profile(
            api_key,
            company_number
        )


    if profile:

        st.header(
            profile.get(
                "company_name",
                company_number
            )
        )


        # ====================================================
        # COMPANY SUMMARY
        # ====================================================

        col1, col2, col3, col4 = st.columns(4)


        col1.metric(
            "Company Number",
            profile.get(
                "company_number",
                "-"
            )
        )


        col2.metric(
            "Status",
            profile.get(
                "company_status",
                "-"
            )
        )


        col3.metric(
            "Company Type",
            profile.get(
                "type",
                "-"
            )
        )


        col4.metric(
            "Incorporated",
            profile.get(
                "date_of_creation",
                "-"
            )
        )


        # ====================================================
        # TABS
        # ====================================================

        tab1, tab2, tab3, tab4 = st.tabs(
            [
                "Company Profile",
                "Directors / Officers",
                "Filing History",
                "Raw JSON"
            ]
        )


        # ====================================================
        # COMPANY PROFILE
        # ====================================================

        with tab1:

            st.subheader("Company Information")


            col1, col2 = st.columns(2)


            with col1:

                st.write(
                    "**Company Name:**",
                    profile.get(
                        "company_name",
                        "-"
                    )
                )

                st.write(
                    "**Company Number:**",
                    profile.get(
                        "company_number",
                        "-"
                    )
                )

                st.write(
                    "**Status:**",
                    profile.get(
                        "company_status",
                        "-"
                    )
                )

                st.write(
                    "**Company Type:**",
                    profile.get(
                        "type",
                        "-"
                    )
                )

                st.write(
                    "**Jurisdiction:**",
                    profile.get(
                        "jurisdiction",
                        "-"
                    )
                )


            with col2:

                st.write(
                    "**Date of Creation:**",
                    profile.get(
                        "date_of_creation",
                        "-"
                    )
                )

                st.write(
                    "**Registered Office Address:**"
                )

                st.write(
                    format_address(
                        profile.get(
                            "registered_office_address",
                            {}
                        )
                    )
                )


            # =================================================
            # SIC CODES
            # =================================================

            st.subheader("SIC Codes")

            sic_codes = profile.get(
                "sic_codes",
                []
            )

            if sic_codes:

                for code in sic_codes:

                    st.write(
                        f"- {code}"
                    )

            else:

                st.info(
                    "No SIC codes available."
                )


            # =================================================
            # ACCOUNTS
            # =================================================

            st.subheader("Accounts")

            accounts = profile.get(
                "accounts",
                {}
            )

            last_accounts = accounts.get(
                "last_accounts",
                {}
            )

            next_accounts = accounts.get(
                "next_accounts",
                {}
            )


            col1, col2 = st.columns(2)


            with col1:

                st.write(
                    "**Last Accounts Made Up To:**",
                    last_accounts.get(
                        "made_up_to",
                        "-"
                    )
                )

                st.write(
                    "**Accounts Type:**",
                    last_accounts.get(
                        "type",
                        "-"
                    )
                )


            with col2:

                st.write(
                    "**Next Accounts Due:**",
                    next_accounts.get(
                        "due_on",
                        "-"
                    )
                )

                st.write(
                    "**Next Accounts Period End:**",
                    next_accounts.get(
                        "period_end_on",
                        "-"
                    )
                )


            # =================================================
            # CONFIRMATION STATEMENT
            # =================================================

            st.subheader(
                "Confirmation Statement"
            )


            confirmation = profile.get(
                "confirmation_statement",
                {}
            )


            st.write(
                "**Last Made Up To:**",
                confirmation.get(
                    "last_made_up_to",
                    "-"
                )
            )


            st.write(
                "**Next Due:**",
                confirmation.get(
                    "next_due",
                    "-"
                )
            )


        # ====================================================
        # OFFICERS
        # ====================================================

        with tab2:

            st.subheader(
                "Directors / Officers"
            )


            with st.spinner(
                "Loading officers..."
            ):

                officers = get_company_officers(
                    api_key,
                    company_number
                )


            officer_df = (
                create_officers_dataframe(
                    officers
                )
            )


            if officer_df.empty:

                st.info(
                    "No officer information found."
                )

            else:

                show_active_only = (
                    st.checkbox(
                        "Show active officers only",
                        value=True
                    )
                )


                display_officers = (
                    officer_df.copy()
                )


                if show_active_only:

                    display_officers = (
                        display_officers[
                            display_officers[
                                "Resigned"
                            ].isna()
                        ]
                    )


                st.dataframe(
                    display_officers,
                    use_container_width=True,
                    hide_index=True
                )


        # ====================================================
        # FILING HISTORY
        # ====================================================

        with tab3:

            st.subheader(
                "Filing History"
            )


            with st.spinner(
                "Loading filing history..."
            ):

                filings = (
                    get_filing_history(
                        api_key,
                        company_number
                    )
                )


            filing_df = (
                create_filing_dataframe(
                    filings
                )
            )


            if filing_df.empty:

                st.info(
                    "No filing history found."
                )

            else:

                st.dataframe(
                    filing_df,
                    use_container_width=True,
                    hide_index=True
                )


                csv = filing_df.to_csv(
                    index=False
                ).encode("utf-8")


                st.download_button(
                    "Download Filing History CSV",
                    csv,
                    file_name=(
                        f"{company_number}"
                        "_filing_history.csv"
                    ),
                    mime="text/csv"
                )


        # ====================================================
        # RAW JSON
        # ====================================================

        with tab4:

            st.subheader(
                "Raw Companies House JSON"
            )


            st.json(profile)


            json_data = json.dumps(
                profile,
                indent=2
            )


            st.download_button(
                "Download Company JSON",
                json_data,
                file_name=(
                    f"{company_number}"
                    "_company.json"
                ),
                mime="application/json"
            )
