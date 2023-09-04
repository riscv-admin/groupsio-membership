
# RISC-V Membership Verification via Groups.io

An Automated Self-Service portal based on Python and Flask for verifying RISC-V membership via Groups.io

## Build
```bash
docker build -t groupsio-membership .
```

## Execution
```bash
docker run -e EMAIL_USER='' -e EMAIL_PASSWORD='' -p 5000:5000 groupsio-membership:latest
```
