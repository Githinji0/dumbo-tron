import httpx

client = httpx.Client(base_url="http://127.0.0.1:8502")

try:
    print("--- 1. Login ---")
    resp_login = client.post("/api/auth/login", json={
        "email": "testuser@mock.com",
        "password": "mockpassword",
        "use_mock": True
    })
    print("Login Status:", resp_login.status_code)
    cookies = resp_login.cookies

    print("\n--- 2. Fetch Projects ---")
    resp_proj = client.get("/api/projects", cookies=cookies)
    print("Projects Status:", resp_proj.status_code)
    projects = resp_proj.json()
    print("Projects list length:", len(projects))

    if projects:
        pid = projects[0]["id"]
        proj_name = projects[0]["name"]
        print(f"Using Project: ID={pid}, Name={proj_name}")

        print("\n--- 3. Fetch Logs with Filters ---")
        resp_logs = client.get(f"/api/logs?project_id={pid}&limit=5", cookies=cookies)
        print("Logs (limit=5) Status:", resp_logs.status_code)
        logs_data = resp_logs.json()
        print(f"Retrieved {len(logs_data)} logs.")
        for log in logs_data[:3]:
            print(f"[{log['timestamp']}] [{log['level']}] {log['message'][:100]}...")

        print("\n--- 4. Fetch Diagnostic Report ---")
        resp_report = client.get(f"/api/logs/report?project_id={pid}", cookies=cookies)
        print("Report Status:", resp_report.status_code)
        if resp_report.status_code == 200:
            rep = resp_report.json().get("report", "")
            print("=== Report Output Preview ===")
            print(rep[:600] if len(rep) > 600 else rep)
            print("=============================")

        print("\n--- 5. Fetch Export formats ---")
        for fmt in ["csv", "txt", "md"]:
            resp_exp = client.get(f"/api/logs/export?project_id={pid}&format={fmt}", cookies=cookies)
            print(f"Export {fmt.upper()} Status: {resp_exp.status_code}, Length: {len(resp_exp.text)} bytes")
            if fmt == "csv":
                print("CSV headers:", resp_exp.headers.get("content-disposition"))
    else:
        print("No projects exist in DB. Run tests or launch live server after creating a project.")
        
except Exception as e:
    print("Verification failed with exception:", e)
