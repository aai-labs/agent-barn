import httpx
import getpass

def main():
    print("Atlassian Service Account Tester")
    print("-" * 32)
    site_url = "https://aai-labs.atlassian.net"
    
    token = getpass.getpass(prompt='Paste your API token (input will be hidden): ').strip()
    if not token:
        return

    print("\n1. Fetching Cloud ID from _edge/tenant_info...")
    try:
        tenant_resp = httpx.get(f"{site_url}/_edge/tenant_info", timeout=10)
        tenant_resp.raise_for_status()
        cloud_id = tenant_resp.json().get("cloudId")
        print(f"✅ Success! Cloud ID: {cloud_id}")
    except Exception as e:
        print(f"❌ Failed to get Cloud ID: {e}")
        return

    print("\n2. Testing Bearer Token against Jira API Gateway...")
    gateway_url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project"
    print(f"URL: {gateway_url}")
    
    try:
        api_resp = httpx.get(
            gateway_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        print(f"Status: {api_resp.status_code}")
        if api_resp.status_code == 200:
            projects = api_resp.json()
            print(f"✅ Token is VALID! Found {len(projects)} accessible projects.")
        else:
            print(f"❌ Failed: {api_resp.text[:500]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
