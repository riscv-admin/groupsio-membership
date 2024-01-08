
# RISC-V Membership Verification via Groups.io

An Automated Self-Service portal based on Python and Flask for verifying RISC-V membership via Groups.io

## Build
```bash
docker build -t groupsio-membership .
```

## Execution
```bash
docker run -it --rm \
-e SERVICE_ACCOUNT_FILE="" \
-e GOOGLE_ADMIN_SUBJECT="" \
-e GROUPSIO_USER="" \
-e GROUPSIO_PASSWORD="" \
-e GITHUB_TOKEN="" \
-e JIRA_TOKEN="" \
-e JIRA_URL="" \
-e ORG="" \
-e TEAM_SLUG="" \
-p 5000:5000 \
-v $(pwd):/app \
groupsio-membership:latest
```
