import requests
import certifi

print(certifi.where())

response = requests.get(
    "https://api.company-information.service.gov.uk/company/00000006",
    auth=("YOUR_API_KEY", ""),
    verify=certifi.where(),
    timeout=30
)

print(response.status_code)
print(response.text)
