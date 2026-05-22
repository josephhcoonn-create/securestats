# SecureStats

[![CI](https://github.com/josephhcoonn-create/SecureStats/actions/workflows/ci.yml/badge.svg)](https://github.com/josephhcoonn-create/SecureStats/actions/workflows/ci.yml)
![Backend coverage ≥ 70%](https://img.shields.io/badge/backend%20coverage-%E2%89%A570%25-success)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![Node 20](https://img.shields.io/badge/node-20-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)

A containerized full-stack MLB analytics platform: FastAPI + Postgres backend
with a daily ETL pipeline against the official MLB Stats API, and a React +
Recharts dashboard with JWT auth and role-based access control.

> Full feature tour, screenshots, architecture diagram, and quickstart
> arrive in **Task 6.3**. This README is currently a placeholder for the CI
> badges so the GitHub Actions workflow status is visible from the repo
> homepage.

## Quickstart

```bash
cp .env.example .env
docker compose up --build
```

Open **http://localhost:8080**.
