# MDP-45 tracker spike harness

Throwaway harness behind [`FINDINGS.md`](FINDINGS.md). Every credential in these files is a local-only placeholder.

- **`compose.yml`:** Vikunja and Postgres on `127.0.0.1:13456`, with files on a local volume.
- **`compose.s3.yml` + `s3.json`:** overlay that stores attachments in S3 (SeaweedFS).
- **`k8s.yaml`:** the same stack in a `mdp45-spike` namespace on local k3d, namespaced resources only.
- **`vk.py`, `flow.py`:** the API walk-through that prints PASS/FAIL for each flow. Set `VK_BASE` to point it at a port-forward.

```sh
docker compose up -d   # add -f compose.yml -f compose.s3.yml for S3
docker exec mdp45_vikunja /app/vikunja/vikunja user create -u agentbarn-svc -e svc@spike.local -p spike-local-pass
python3 -I flow.py
```

`flow.py` reads the local file volume to check that deletes cascade. With the S3 overlay, check the bucket instead.
