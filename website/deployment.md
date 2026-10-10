# Run OpenQR

## Local Development

```sh
poetry install
cp .env.example .env
poetry run uvicorn app.main:app --reload --env-file .env --host 127.0.0.1 --port 8127
```

Review `.env` before running. Never commit keys or session secrets. See the
[repository configuration guide](https://github.com/trbouma/openqr#readme) for
the complete supported variables and reverse-proxy requirements.

Set `OPENQR_PUBLIC_BASE_URL` to the externally reachable HTTPS origin, not the
container address. `OPENQR_RELAYS` controls public anchor lookup;
`OPENQR_HOME_RELAYS` locates identity configuration. Profile publication relays
may differ, so make sure the query scope can find newly published anchors.

## Containers

```sh
docker compose up -d --build
```

The repository also includes `refresh-containers.sh`. Review it before running.
Recreate containers after environment changes; restarting alone does not apply
new container environment values. Protect service-mode registration and configure
HTTPS, session secrets, request size limits, and appropriate proxy timeouts.

## Documentation

```sh
poetry install --with docs
poetry run mkdocs serve --dev-addr 127.0.0.1:8001
poetry run mkdocs build --strict
```

The Pages workflow builds and deploys the site when relevant changes reach
`main`. In GitHub repository Settings, select **Pages > Source > GitHub Actions**.
The published address is `https://trbouma.github.io/openqr/`.
