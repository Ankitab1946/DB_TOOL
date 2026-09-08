import requests
import truststore

truststore.inject_into_ssl()

API_KEY = "PASTE_YOUR_API_KEY_HERE".strip()

URL = (
    "https://api.company-information.service.gov.uk"
    "/company/00000006"
)

response = requests.get(
    URL,
    auth=(API_KEY, ""),
    timeout=30
)

print("Status:", response.status_code)
print("Response:")
print(response.text)
