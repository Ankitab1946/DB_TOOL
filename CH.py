import os
import json
import requests
import pandas as pd
import streamlit as st
from requests.auth import HTTPBasicAuth


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="Companies House Explorer",
    page_icon="🏢",
    layout="wide"
)

BASE_URL = "https://api.company-information.service.gov.uk"


# ---------------------------------------------------------
# GET API KEY
# ---------------------------------------------------------

def get_api_key():
    """
    Read API key from:
    1. Environment variable COMPANIES_HOUSE_API_KEY
    2. Streamlit secrets
    """

    api_key = os.getenv("COMPANIES_HOUSE_API_KEY")

    if api_key:
        return api_key

    try:
        return st.secrets["COMPANIES_HOUSE_API_KEY"]
    except Exception:
        return None


API_KEY = get_api_key()


# ---------------------------------------------------------
# GENERIC API CALL
# ---------------------------------------------------------

def companies_house_get(endpoint, params=None):
    """
    Generic GET request to Companies House API.
    """

    if not API_KEY:
        raise ValueError(
            "Companies House API key not configured."
        )

    url = f"{BASE_URL}{endpoint}"

    try:

        response = requests.get(
            url,
            params=params,
            auth=HTTPBasicAuth(API_KEY, ""),
            timeout=30
        )

        if response.status_code == 200:
            return response.json()

        elif response.status_code == 401:
            raise Exception(
                "401 Unauthorized - Check your Companies House API key."
            )

        elif response.status_code == 404:
            raise Exception(
                "404 Not Found - Requested Companies House resource "
                "was not found."
            )

        elif response.status_code == 429:
            raise Exception(
                "429 Too Many Requests - Companies House API "
                "rate limit exceeded."
            )

        else:
            raise Exception(
                f"Companies House API error "
                f"{response.status_code}: {response.text}"
            )

    except requests.exceptions.Timeout:
        raise Exception("Companies House API request timed out.")

    except requests.exceptions.ConnectionError:
        raise Exception(
            "Unable to connect to Companies House API."
        )


# ---------------------------------------------------------
# API FUNCTIONS
# ---------------------------------------------------------

@st.cache_data(ttl=300)
def search_companies(company_name):
    """
    Search company by name.
    """

    return companies_house_get(
        "/search/companies",
        params={
            "q": company_name,
            "items_per_page": 20
        }
    )


@st.cache_data(ttl=300)
def get_company_profile(company_number):
    """
    Get company profile.
    """

    return companies_house_get(
        f"/company/{company_number}"
    )


@st.cache_data(ttl=300)
def get_company_officers(company_number):
    """
    Get company officers/directors.
    """

    return companies_house_get(
        f"/company/{company_number}/officers",
        params={
            "items_per_page": 100
        }
    )


@st.cache_data(ttl=300)
def get_filing_history(company_number):
    """
    Get company filing history.
    """

    return companies_house_get(
        f"/company/{company_number}/filing-history",
        params={
            "items_per_page": 100
        }
    )


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def format_address(address):
    """
    Convert Companies House address object into one string.
    """

    if not address:
        return ""

    address_fields = [
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
        for value in address_fields
        if value
    )


def company_search_dataframe(data):

    rows = []

    for company in data.get("items", []):

        rows.append({
            "Company Name": company.get("title"),
            "Company Number": company.get("company_number"),
            "Status": company.get("company_status"),
            "Company Type": company.get("company_type"),
            "Created": company.get("date_of_creation"),
            "Address": company.get("address_snippet")
        })

    return pd.DataFrame(rows)


def officers_dataframe(data):

    rows = []

    for officer in data.get("items", []):

        dob = officer.get("date_of_birth", {})

        dob_display = ""

        if dob:
            month = dob.get("month")
            year = dob.get("year")

            if month and year:
                dob_display = f"{month:02d}/{year}"

        rows.append({
            "Name": officer.get("name"),
            "Role": officer.get("officer_role"),
            "Appointed On": officer.get("appointed_on"),
            "Resigned On": officer.get("resigned_on"),
            "Nationality": officer.get("nationality"),
            "Country of Residence":
                officer.get("country_of_residence"),
            "DOB": dob_display,
            "Occupation": officer.get("occupation"),
            "Address": format_address(
                officer.get("address", {})
            )
        })

    return pd.DataFrame(rows)


def filing_dataframe(data):

    rows = []

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


# ---------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------

st.title("Companies House Explorer")

st.caption(
    "Search and retrieve UK company information "
    "from the Companies House API."
)


# ---------------------------------------------------------
# CHECK API KEY
# ---------------------------------------------------------

if not API_KEY:

    st.error(
        "Companies House API key has not been configured."
    )

    st.markdown(
        """
Add the following environment variable:

```text
COMPANIES_HOUSE_API_KEY=your_api_key_here
