"""MDP-45 spike: walk the flows our platform needs against headless Vikunja."""
import sys, os, subprocess
sys.path.insert(0, os.path.dirname(__file__))
from vk import call, multipart, login

def check(label, cond, extra=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label} {extra}")

jwt = login()
perms = {
    "projects": ["create", "read_one", "read_all", "update", "delete", "views_buckets", "views_buckets_tasks"],
    "projects_views": ["read_all"],
    "projects_views_tasks": ["read_all"],
    "projects_webhooks": ["create", "read_all"],
    "tasks": ["create", "read_one", "read_all", "update", "delete"],
    "tasks_attachments": ["create", "read_all", "read_one", "delete"],
    "tasks_comments": ["create", "read_all"],
    "labels": ["create", "read_all"],
    "tasks_labels": ["create", "read_all"],
}
s, tok = call("PUT", "/tokens", jwt, {"title": "agentbarn-api", "permissions": perms,
                                      "expires_at": "2027-10-20T00:00:00Z"})
check("create scoped API token via API (JWT session)", s in (200, 201), f"status={s}")
T = tok["token"]

# Tenancy shape: org project -> agent child project
s, org = call("PUT", "/projects", T, {"title": "org:acme"})
check("create org project", s in (200, 201), f"id={org.get('id')}")
s, agent = call("PUT", "/projects", T, {"title": "agent:a1", "parent_project_id": org["id"]})
check("create agent child project", s in (200, 201) and agent.get("parent_project_id") == org["id"])
s, agent2 = call("PUT", "/projects", T, {"title": "agent:a2", "parent_project_id": org["id"]})

# Task lifecycle
s, t = call("PUT", f"/projects/{agent['id']}/tasks", T,
            {"title": "Prepare Q3 report", "description": "requested via Slack"})
check("create task", s in (200, 201), f"id={t.get('id')} index={t.get('index')}")
s, t2 = call("PUT", f"/projects/{agent2['id']}/tasks", T, {"title": "Other agent task"})

s, views = call("GET", f"/projects/{agent['id']}/views", T)
kanban = next(v for v in views if v["view_kind"] == "kanban")
s, buckets = call("GET", f"/projects/{agent['id']}/views/{kanban['id']}/buckets", T)
print("   default buckets:", [b["title"] for b in buckets], "done_bucket_id:", kanban.get("done_bucket_id"))
b_prog = next(b for b in buckets if b["title"] == "Doing")
s, r = call("POST", f"/projects/{agent['id']}/views/{kanban['id']}/buckets/{b_prog['id']}/tasks", T,
            {"task_id": t["id"]})
check("move task to 'Doing' bucket", s in (200, 201), f"status={s}")

s, c = call("PUT", f"/tasks/{t['id']}/comments", T, {"comment": "Started gathering data"})
check("add comment", s in (200, 201))

# Attachments
pdf = b"%PDF-1.4\n% spike\n" + os.urandom(1024)
body, ct = multipart("files", "q3-report.pdf", pdf)
s, up = call("PUT", f"/tasks/{t['id']}/attachments", T, raw=body, ctype=ct)
check("upload attachment", s in (200, 201), f"status={s} errors={up.get('errors') if isinstance(up, dict) else ''}")
s, atts = call("GET", f"/tasks/{t['id']}/attachments", T)
check("list attachments", s == 200 and len(atts) == 1,
      f"file={atts[0]['file']['name']} size={atts[0]['file']['size']} mime={atts[0]['file'].get('mime')}" if atts else "")
aid, fid = atts[0]["id"], atts[0]["file"]["id"]
s, data = call("GET", f"/tasks/{t['id']}/attachments/{aid}", T)
check("download attachment round-trips bytes", s == 200 and data == pdf)
big, ct = multipart("files", "big.bin", os.urandom(21 * 1024 * 1024), "application/octet-stream")
s, r = call("PUT", f"/tasks/{t['id']}/attachments", T, raw=big, ctype=ct)
check("21MB upload rejected by 20MB limit", s >= 400 or bool(r.get("errors")), f"status={s} resp={str(r)[:120]}")

# Mark done
s, r = call("POST", f"/tasks/{t['id']}", T, {"title": t["title"], "done": True})
check("mark done", s == 200 and r.get("done") is True)

# Cross-project listing with filters
s, r = call("GET", f"/tasks?filter=project+in+{agent['id']},{agent2['id']}&per_page=50", T)
check("list tasks across agent projects", s == 200 and {x['id'] for x in r} == {t['id'], t2['id']}, f"n={len(r) if isinstance(r, list) else r}")
s, r = call("GET", f"/tasks?filter=done+%3D+false&per_page=50", T)
check("filter done=false", s == 200 and [x['id'] for x in r] == [t2['id']], f"ids={[x['id'] for x in r] if isinstance(r, list) else r}")
s, r = call("GET", f"/tasks?filter=project+%3D+{org['id']}&per_page=50", T)
print(f"   filter project=org (parent) returns child tasks? n={len(r) if isinstance(r, list) else r}")

# Webhooks
s, ev = call("GET", "/webhooks/events", T)
print("   webhook events:", ev)
s, wh = call("PUT", f"/projects/{agent['id']}/webhooks", T,
             {"target_url": "http://example.invalid/hook", "events": ["task.created"], "secret": "x"})
check("create project webhook with secret", s in (200, 201), f"status={s} {str(wh)[:120]}")

# Token scope enforcement: token lacks teams perms
s, r = call("GET", "/teams", T)
check("token blocked outside its scopes (/teams)", s in (401, 403), f"status={s}")

# Cascade delete: does deleting the agent project remove tasks + files on disk?
def files_on_disk():
    out = subprocess.run(["docker", "exec", "mdp45_vikunja", "ls", "/app/vikunja/files"], capture_output=True, text=True).stdout.split()
    return [f for f in out if not f.startswith(".")]
before = files_on_disk()
s, r = call("DELETE", f"/projects/{agent['id']}", T)
check("delete agent project", s == 200, f"status={s}")
s, r = call("GET", f"/tasks/{t['id']}", T)
check("task gone after project delete", s == 404, f"status={s}")
after = files_on_disk()
check("attachment file removed from disk", str(fid) in before and str(fid) not in after, f"before={before} after={after}")
