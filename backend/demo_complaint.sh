TOKEN=$(curl -s -X POST localhost:8010/api/v1/auth/login -d "username=verify-op@example.com&password=ThrowawayPass123!" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST localhost:8010/api/v1/email/ingest -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"sender":"jane@example.com","recipient":"clinic@example.com","subject":"Job application","body":"I want to come for a job interview. Do you guys have any vacancy?"}' | python3 -m json.tool
