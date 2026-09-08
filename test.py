import socket
import requests
from getpass import getpass


LIVE_URL = "https://api.company-information.service.gov.uk"
SANDBOX_URL = "https://api-sandbox.company-information.service.gov.uk"


print("=" * 70)
print("COMPANIES HOUSE CONNECTION TEST")
print("=" * 70)

environment = input(
    "Environment - LIVE or SANDBOX [LIVE]: "
).strip().upper()

if environment == "SANDBOX":
    BASE_URL = SANDBOX_URL
else:
    BASE_URL = LIVE_URL

API_KEY = getpass("Enter Companies House API key: ")

hostname = BASE_URL.replace("https://", "")

print("\n1. Testing DNS...")
print(f"Hostname: {hostname}")

try:
    ip = socket.gethostbyname(hostname)
    print(f"DNS OK")
    print(f"Resolved IP: {ip}")
except Exception as e:
    print("DNS FAILED")
    print(type(e).__name__)
    print(str(e))
    exit()


print("\n2. Testing HTTPS connection...")

try:
    response = requests.get(
        f"{BASE_URL}/company/00000006",
        auth=(API_KEY, ""),
        timeout=30
    )

    print("Connection successful")
    print(f"HTTP Status: {response.status_code}")

    if response.status_code == 200:

        print("\nSUCCESS - API KEY AND CONNECTION ARE WORKING")

        data = response.json()

        print("\nCompany:")
        print(data.get("company_name"))

        print("\nCompany Number:")
        print(data.get("company_number"))

        print("\nStatus:")
        print(data.get("company_status"))

    elif response.status_code == 401:

        print("\nAUTHENTICATION FAILED")
        print("The server was reached successfully.")
        print("Check:")
        print("- API key")
        print("- Live vs Sandbox environment")
        print("- API key restrictions")

        print("\nResponse:")
        print(response.text)

    elif response.status_code == 403:

        print("\nACCESS FORBIDDEN")
        print("Check IP/domain restrictions on the API key.")

        print("\nResponse:")
        print(response.text)

    elif response.status_code == 429:

        print("\nRATE LIMIT EXCEEDED")

    else:

        print("\nUnexpected HTTP response")
        print(response.text)


except requests.exceptions.SSLError as e:

    print("\nSSL ERROR")
    print("Your machine does not trust the SSL certificate.")

    print("\nActual error:")
    print(repr(e))

    print(
        "\nThis commonly happens when a corporate proxy/VPN "
        "performs HTTPS inspection."
    )


except requests.exceptions.ProxyError as e:

    print("\nPROXY ERROR")

    print("\nActual error:")
    print(repr(e))

    print(
        "\nPython is unable to connect through your configured proxy."
    )


except requests.exceptions.ConnectTimeout as e:

    print("\nCONNECTION TIMEOUT")

    print("\nActual error:")
    print(repr(e))


except requests.exceptions.ConnectionError as e:

    print("\nCONNECTION ERROR")

    print("\nActual error:")
    print(repr(e))


except requests.exceptions.RequestException as e:

    print("\nREQUEST ERROR")

    print("\nActual error:")
    print(repr(e))


except Exception as e:

    print("\nUNEXPECTED ERROR")
    print(type(e).__name__)
    print(repr(e))
