import requests

# --- Configuration ---
CONFLUENCE_URL = "http://localhost:8090"  # Keep the trailing slash
CONFLUENCE_USERNAME = "dxdelvin"  # Use your Confluence username
CONFLUENCE_PAT = "MjkwMDQ0MjUxOTYxOrpozlx0RmmteperaDVJExa0HR37"  # Replace with your PAT

# --- Test Endpoints ---
TEST_API_ENDPOINT = f"{CONFLUENCE_URL}/rest/api/user/current"  # User details endpoint
TEST_UI_ENDPOINT = f"{CONFLUENCE_URL}/index.action"  # Main page endpoint

def test_confluence_auth():
    # Set up headers with PAT
    headers = {
        "Authorization": f"Bearer {CONFLUENCE_PAT}",
        "Accept": "application/json"
    }

    # Test 1: REST API Authentication with PAT
    print("Testing REST API Authentication with PAT...")
    try:
        response = requests.get(
            TEST_API_ENDPOINT,
            headers=headers,
            timeout=10
        )

        print(f"HTTP Status Code: {response.status_code}")

        if response.status_code == 200:
            user_data = response.json()
            print("SUCCESS: Authentication Valid")
            print(f"Username: {user_data['username']}")
            print(f"Email: {user_data.get('email', 'Not available')}")
        else:
            print(f"FAILED: Authentication Failed")
            print(f"Response Body: {response.text[:200]}...")  # Show first 200 chars

    except requests.exceptions.RequestException as e:
        print(f"CONNECTION ERROR: {str(e)}")

    # Test 2: UI Session Validation (Note: PATs typically don't work for UI endpoints)
    print("\nTesting UI Session Validation...")
    print("Note: Personal Access Tokens typically don't work for UI endpoints")
    try:
        response = requests.get(
            TEST_UI_ENDPOINT,
            headers=headers,
            timeout=10
        )

        print(f"HTTP Status Code: {response.status_code}")
        if response.status_code == 200:
            if "Log Out" in response.text:
                print("SUCCESS: UI Session Established (unexpected for PAT)")
            else:
                print("UI Loaded but session not established (expected for PAT)")
        else:
            print(f"FAILED: Status {response.status_code}")

    except requests.exceptions.RequestException as e:
        print(f"CONNECTION ERROR: {str(e)}")

if __name__ == "__main__":
    print("=== Confluence PAT Authentication Tester ===")
    test_confluence_auth()