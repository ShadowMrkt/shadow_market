# Shadow Market - Hardened Deployment Guide (v2.0)

**Warning:** This guide is intended for experienced operators and security professionals deploying high-security systems. Each step requires careful consideration and adaptation to your specific environment. **Assume all components are hostile until proven otherwise.** Thoroughly review and audit all code, configurations, and operational procedures before *any* production deployment. Misconfiguration *will* lead to compromise and loss of funds.

**Table of Contents**

1.  [Overview and Hardened Architecture](#1-overview-and-hardened-architecture)
2.  [Secure Development & Infrastructure Prerequisites](#2-secure-development--infrastructure-prerequisites)
    * 2.1. Required Software & Services
    * 2.2. Local Development Environment Setup
3.  [Backend Hardening & Setup (Django)](#3-backend-hardening--setup-django)
    * 3.1. Core Backend Components & Security Focus
    * 3.2. Environment Variables & Secret Management (Vault)
    * 3.3. Database Initialization & Static Files
    * 3.4. Running Locally (Development)
4.  [Frontend Hardening & Setup (Next.js)](#4-frontend-hardening--setup-nextjs)
    * 4.1. Core Frontend Components & Security Focus
    * 4.2. Local Development
5.  [Core Security Features & Implementation Concepts](#5-core-security-features--implementation-concepts)
    * 5.1. Authentication: Mandatory PGP, PGP 2FA (Login & Actions), WebAuthn
    * 5.2. Cryptocurrency Handling & Multi-Sig Escrow (BTC/XMR/ETH)
    * 5.3. Tor Hidden Service Configuration & Security
6.  [Secure Containerization, CI/CD, and Deployment Orchestration](#6-secure-containerization-cicd-and-deployment-orchestration)
    * 6.1. Docker Container Security Principles
    * 6.2. Docker Compose for Secure Local Testing
    * 6.3. Secure CI/CD Pipeline (GitHub Actions Example)
    * 6.4. Kubernetes Deployment Security Principles (Optional)
7.  [Hardened Production Deployment Guide (VPS / Dedicated Hardware)](#7-hardened-production-deployment-guide-vps--dedicated-hardware)
    * 7.1. Infrastructure Isolation Strategy
    * 7.2. Secure Server Setup (Linux Example)
    * 7.3. Application Deployment & Runtime Configuration
    * 7.4. Tor Hidden Service Setup (Production)
8.  [Ongoing Security: Testing, Auditing, Monitoring & Maintenance](#8-ongoing-security-testing-auditing-monitoring--maintenance)
    * 8.1. Comprehensive Testing Strategy
    * 8.2. Security Auditing & Penetration Testing
    * 8.3. Monitoring, Logging, and Alerting
    * 8.4. Maintenance & Incident Response
9.  [CRITICAL: Secret Management & Placeholder Replacement](#9-critical-secret-management--placeholder-replacement)
10. [Operational Security Procedures (Appendix)](#10-operational-security-procedures-appendix)
    * 10.1. Key Management (Market PGP, Multi-Sig Keys, Canary)
    * 10.2. Backup and Recovery
    * 10.3. Dead Man's Switch Procedures

---

## 1. Overview and Hardened Architecture

Shadow Market is architected as a high-security, privacy-centric, cryptocurrency-only marketplace designed exclusively for the Tor network. It draws inspiration from past markets but incorporates modern security paradigms to mitigate historical failure modes. **Security and user privacy are paramount design goals.**

The system is compartmentalized:

* **Backend:** A hardened Django application providing a REST API. It enforces strict validation, manages state via dedicated services (Ledger, Escrow, PGP, Crypto), and relies on PostgreSQL (database) and Redis (cache, task queue). **Direct model manipulation outside services is forbidden.**
* **Frontend:** A Next.js application providing the user interface. It communicates with the backend API, handles client-side state, and incorporates security headers and practices (CSP, CSRF protection).
* **Cryptocurrency Nodes:** **Isolated, dedicated servers** running Bitcoin Core, `monero-wallet-rpc`, and an Ethereum node. Communication is strictly firewalled and secured. **Nodes never run on the application server.**
* **Secrets Management:** HashiCorp Vault is the **single source of truth** for all sensitive configuration (database credentials, API keys, market private keys, RPC passwords).
* **Asynchronous Tasks:** Celery workers handle background jobs like deposit confirmation, order finalization, and ledger reconciliation, interacting via the service layer.
* **Tor:** Provides network-level anonymity for the service endpoint.

Key Security Features:
* Mandatory PGP key for user registration.
* PGP-based 2FA for login.
* **Per-action PGP signature confirmation** for all sensitive operations (withdrawals, settings changes, finalizing orders, admin actions).
* WebAuthn/FIDO2 support as a primary/alternative 2FA.
* Multi-Signature Escrow: 2-of-3 Taproot (P2TR) for Bitcoin, 2-of-3 Native Multi-Sig for Monero. Simple hot-wallet escrow for Ethereum.
* Unique, non-reused deposit addresses (BIP32 derived for BTC, Subaddresses for XMR).
* Internal, immutable double-entry ledger system with robust reconciliation.
* Strict Role-Based Access Control (RBAC) and API permissions.
* Hardened custom Admin Panel with mandatory PGP auth for actions.
* Secure middleware stack (Strict CSP, Rate Limiting, Request Validation).
* Comprehensive security logging and monitoring hooks.
* Dead Man's Switch mechanism.
* Hardened containerization and deployment practices.

**Codebase Organization:** (Illustrative - refer to actual repository)
shadow_market/
├── backend/
│   ├── manage.py             # Django CLI
│   ├── requirements.txt      # Python dependencies
│   ├── pytest.ini            # Test config
│   ├── vault_integration.py  # Vault client logic
│   ├── mymarketplace/        # Django project config
│   │   ├── settings/         # base.py, dev.py, prod.py
│   │   ├── urls.py           # Root URLConf
│   │   └── wsgi.py
│   ├── store/                # Core marketplace app
│   │   ├── models.py         # User, Product, Order, etc.
│   │   ├── views.py          # API Views/Viewsets
│   │   ├── serializers.py    # API data validation/serialization
│   │   ├── permissions.py    # Custom API permissions
│   │   ├── services/         # Business logic (escrow, crypto, reputation, pgp, etc.)
│   │   ├── tasks.py          # Celery tasks for store app
│   │   ├── validators.py     # Custom data validators
│   │   └── ...
│   ├── ledger/               # Internal ledger app
│   │   ├── models.py
│   │   ├── services.py
│   │   └── tasks.py
│   ├── adminpanel/           # Custom secure admin interface
│   │   ├── views.py
│   │   ├── forms.py
│   │   └── templates/
│   ├── notifications/        # User notification system
│   ├── forum/                # Community forum app
│   ├── middleware/           # Custom Django middleware
│   └── tests/                # Backend unit/integration tests
├── frontend/
│   ├── package.json          # Node dependencies
│   ├── next.config.js        # Next.js config (incl. security headers)
│   ├── pages/                # Next.js page components
│   ├── components/           # Reusable React components
│   ├── context/              # React context (e.g., AuthContext)
│   ├── utils/                # Frontend utilities (api.js, formatters)
│   └── styles/               # CSS styles
├── .github/workflows/        # CI/CD pipelines (ci-cd.yml)
├── docker-compose.yml        # Local development orchestration (Optional)
├── backend/Dockerfile        # Backend container build definition
├── frontend/Dockerfile       # Frontend container build definition
└── deploy/                   # Infrastructure/Deployment configs (Optional: Terraform, Ansible, K8s manifests)

*(Note: This guide does not contain the full source code. Refer to the project repository for the actual code files.)*

## 2. Secure Development & Infrastructure Prerequisites

### 2.1. Required Software & Services

* **Python:** 3.10+ (Check `.python-version` or similar).
* **Node.js:** LTS version (e.g., 18.x, check `frontend/package.json`). Use `nvm` for management.
* **PostgreSQL:** Version 13+ recommended.
* **Redis:** Version 6+ recommended.
* **Git:** For version control.
* **Docker & Docker Compose:** Latest stable versions for containerization (local dev & build).
* **Tor:** Latest stable Tor daemon/expert bundle for hosting the hidden service.
* **GnuPG (GPG):** Latest stable version (v2.2+) for backend PGP operations. Ensure it's correctly installed and in the system PATH.
* **HashiCorp Vault:** Latest stable version. Required for **all** secret management. Deploy a dedicated, hardened Vault instance (or cluster).
* **(Optional) Kubernetes:** `kubectl`, and a cluster (Minikube, k3s for local; EKS, GKE, AKS, or self-hosted for production).
* **Code Editor:** With appropriate linters/formatters (e.g., Black, Flake8, Prettier).

### 2.2. Local Development Environment Setup

1.  **Clone Repository:** `git clone <repository_url> shadow_market && cd shadow_market`
2.  **Backend Setup:**
    * Navigate to `backend/`.
    * Create/activate Python virtual env: `python3 -m venv venv && source venv/bin/activate` (or `venv\Scripts\activate` on Windows).
    * Install dependencies: `pip install -r requirements.txt`.
    * **GPG Setup:** Configure `settings.GPG_HOME` to point to a dedicated directory for the development GPG keyring. Ensure GPG is callable.
    * **Vault Setup:** Run a local Vault dev server (`vault server -dev`). Unseal it and configure necessary AppRoles/Tokens and secret paths matching `settings/base.py` and `vault_integration.py`. Export `VAULT_ADDR`. Configure AppRole credentials via environment variables (`VAULT_APPROLE_ROLE_ID`, `VAULT_APPROLE_SECRET_ID`).
    * **Environment Variables:** Create a `.env` file in `backend/` sourcing secrets *from your local Vault dev instance* or setting dev-specific values (See Section 3.2). **Do not commit `.env`.**
    * Run initial migrations: `python manage.py migrate`.
3.  **Frontend Setup:**
    * Navigate to `frontend/`.
    * Install dependencies: `yarn install` (or `npm install`).
    * **Environment Variables:** Set `NEXT_PUBLIC_API_URL` (e.g., `http://localhost:8000/api`).
4.  **(Optional) Docker Compose:** If using `docker-compose.yml` for local services (Postgres, Redis):
    * Ensure Docker is running.
    * Run `docker-compose up -d db redis` (or similar based on your `docker-compose.yml`).

## 3. Backend Hardening & Setup (Django)

### 3.1. Core Backend Components & Security Focus

The backend implements the core logic. Key security aspects addressed in the hardened codebase (referenced from the repository) include:
* **Service Layer:** Business logic encapsulated in services (`store/services/*`, `ledger/services.py`). Views call services, services interact with models/external systems.
* **Input Validation:** Primarily handled by DRF Serializers (`store/serializers.py`) with strict validation rules and custom validators (`store/validators.py`).
* **Authentication:** Handled via DRF/JWT (for API sessions) combined with mandatory PGP 2FA (`pgp_service.py`) for login and per-action confirmation via decorators. WebAuthn support via `webauthn_service.py`.
* **Permissions:** Strict API access control using custom permission classes (`store/permissions.py`).
* **Ledger:** Atomic, immutable transaction recording (`ledger/` app).
* **Escrow:** State machine logic coordinating multi-sig flows (`escrow_service.py`).
* **Crypto:** Isolated interaction logic with blockchains (`bitcoin_service.py`, `monero_service.py`, `ethereum_service.py`).
* **Secrets:** All secrets fetched exclusively from Vault (`vault_integration.py`).

### 3.2. Environment Variables & Secret Management (Vault)

**CRITICAL:** All sensitive configuration MUST be managed via Vault and/or secure environment variable injection at runtime. **NEVER hardcode secrets.**

A `.env` file (for local dev ONLY, sourced from Vault) or runtime environment variables must define:

* `DJANGO_SECRET_KEY`: Generated securely (50+ random chars). **Source from Vault.**
* `DJANGO_ALLOWED_HOSTS`: Comma-separated list (e.g., `.onion address`, potentially proxy IP).
* `DEBUG`: `False` in production.
* `DATABASE_URL`: Full database connection string (e.g., `postgres://user:pass@host:port/db`). **Source user/pass from Vault.**
* `REDIS_URL`: Connection URL for Redis (e.g., `redis://host:port/0`). **Source pass from Vault if applicable.**
* `CELERY_BROKER_URL`: Same as `REDIS_URL` or other broker URL.
* `VAULT_ADDR`: URL of the Vault server.
* `VAULT_APPROLE_ROLE_ID`: AppRole Role ID for the application.
* `VAULT_APPROLE_SECRET_ID`: AppRole Secret ID for the application (provisioned securely).
* `VAULT_SECRET_BASE_PATH`: Base path in Vault KV store (e.g., `kv/data/shadowmarket`).
* `VAULT_KV_VERSION`: `1` or `2`.
* `GPG_HOME`: **Absolute path** to the GPG keyring directory used by the application user. Ensure permissions are strict (0700).
* `*_NODE_RPC_URL`: RPC endpoint URLs for Bitcoin, Monero, Ethereum nodes.
* `*_NODE_RPC_USER` / `*_NODE_RPC_PASS`: Credentials for authenticated RPC access. **Source from Vault.**
* `*_CONFIRMATIONS`: Required block confirmations for deposits.
* `PGP_LOGIN_CHALLENGE_TIMEOUT_SECONDS`: Timeout for login challenge.
* `PGP_ACTION_NONCE_TIMEOUT_SECONDS`: Timeout for action confirmation nonce.
* `SENTRY_DSN`: Optional Sentry endpoint.
* `(Optional) Frontend URL/Domain`: For CORS or other settings.
* ... any other custom settings requiring secure configuration.

Use `django-environ` or similar libraries in `settings/base.py` to load these variables robustly.

### 3.3. Database Initialization & Static Files

1.  **Ensure DB Service is Running:** Start Postgres (locally or via Docker).
2.  **Apply Migrations:** From `backend/` with venv active:
    ```bash
    python manage.py makemigrations store ledger adminpanel notifications forum # Ensure all apps included
    python manage.py migrate
    ```
3.  **Collect Static Files:**
    ```bash
    python manage.py collectstatic --noinput
    ```
    Ensure `settings.STATIC_ROOT` is configured correctly and served appropriately in production (e.g., by Nginx).

### 3.4. Running Locally (Development)

1.  Ensure Postgres, Redis, Vault (dev mode) are running.
2.  Ensure required environment variables (esp. Vault) are set/exported or in `.env`.
3.  From `backend/` with venv active:
    ```bash
    # Run Django development server (uses settings.dev)
    python manage.py runserver 0.0.0.0:8000

    # Run Celery worker (separate terminal)
    celery -A mymarketplace worker --loglevel=info

    # Run Celery beat (separate terminal, if scheduled tasks exist)
    celery -A mymarketplace beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ```
Access via `http://localhost:8000`.

## 4. Frontend Hardening & Setup (Next.js)

### 4.1. Core Frontend Components & Security Focus

The Next.js frontend interacts with the backend API. Key security aspects:
* **API Interaction:** Securely calls backend endpoints via `utils/api.js`, handling errors and CSRF tokens.
* **Input Handling:** Basic client-side validation for UX; relies on backend for security validation. Output encoding via React prevents basic XSS.
* **State Management:** Uses `AuthContext.js` for auth state. Avoids storing sensitive data client-side longer than necessary.
* **Security Headers:** Configured via `next.config.js` (CSP, etc.) to complement backend headers.
* **PGP Flow:** Securely handles displaying challenges and sending user-provided signatures (`PgpChallengeSigner.js`).

### 4.2. Local Development

1.  Ensure backend is running.
2.  From `frontend/`:
    * Install dependencies: `yarn install` (or `npm install`).
    * Set environment variables: `export NEXT_PUBLIC_API_URL=http://localhost:8000/api` (adjust port if needed).
    * Start dev server: `yarn dev` (or `npm run dev`).
Access via `http://localhost:3000`.

## 5. Core Security Features & Implementation Concepts

### 5.1. Authentication: Mandatory PGP, PGP 2FA (Login & Actions), WebAuthn

* **Mandatory PGP:** Registration requires a valid PGP key, verified by `pgp_service` via `validate_pgp_public_key`.
* **PGP 2FA (Login):** `pgp_service.generate_pgp_challenge` issues a unique, timed challenge; `pgp_service.verify_pgp_challenge` verifies the signature using constant-time comparison and immediate cache invalidation.
* **PGP Action Confirmation:** Sensitive API views (decorated) use `pgp_service.generate_action_challenge` and `pgp_service.verify_action_signature` to require a fresh signature for that specific action, preventing session hijacking for critical operations. Relies on nonce-based cache keys deleted immediately on use.
* **WebAuthn/FIDO2:** Supported as primary/alternative 2FA via `webauthn_service.py` and `WebAuthnCredential` model, offering phishing resistance. Attestation should be handled during registration.
* **Brute Force:** `django-axes` configured with Redis backend and strict production limits.
* **CAPTCHA:** Used on registration/login via `django-simple-captcha`.

### 5.2. Cryptocurrency Handling & Multi-Sig Escrow (BTC/XMR/ETH)

* **Isolation:** Crypto nodes **must** be isolated from application servers. Communication via secure RPC calls only.
* **No Address Reuse:** Generate unique deposit addresses per order/deposit (BIP32 derived for BTC, subaddresses for XMR) via crypto services.
* **Secure Key Management:** Market signing keys managed exclusively via Vault.
* **Bitcoin (BTC):** 2-of-3 Taproot (P2TR) multi-sig escrow. `bitcoin_service.py` handles script creation, BIP32 derivation (from Vault master key), PSBTv2 workflow (create, update, finalize, broadcast), fee estimation, and deposit confirmation (via node scanning or indexer).
* **Monero (XMR):** 2-of-3 Native multi-sig escrow. `monero_service.py` handles RPC wallet management (passwords via Vault), `make/prepare/sign/submit_multisig` workflow, subaddress generation, and deposit confirmation (`get_transfers`).
* **Ethereum (ETH):** Simple hot-wallet escrow. `ethereum_service.py` handles secure key loading (Vault), nonce management, gas estimation, transaction signing/broadcasting, and deposit confirmation (event logs/block scanning).
* **Ledger Integration:** All fund movements (deposits, escrow lock/release, fees, withdrawals) managed atomically via `ledger_service`.
* **Reconciliation:** Critical background task (`ledger/tasks.py`) compares internal ledger balances against actual balances reported by isolated crypto nodes, alerting on discrepancies.

### 5.3. Tor Hidden Service Configuration & Security

* **Dedicated Server:** The Tor daemon should run on the same machine as the reverse proxy (e.g., Nginx) fronting the backend application, or potentially on a dedicated gateway machine.
* **`torrc` Configuration:**
    ```ini
    # /etc/tor/torrc or equivalent
    HiddenServiceDir /var/lib/tor/hidden_service/ # Ensure permissions are correct (owned by tor user)
    HiddenServicePort 80 127.0.0.1:80 # Point to reverse proxy listening locally
    # Optional Security Enhancements:
    # HiddenServiceVersion 3 # Default, ensure v2 is disabled
    # HiddenServiceAllowUnknownPorts 0
    # HiddenServiceExportCircuitID General # If needed for logging/correlation (use carefully)
    # Consider Vanguards addon for guard protection if available/applicable
    ```
* **Hidden Service Key Security:** The `hs_ed25519_secret_key` (and potentially `public_key`) file within the `HiddenServiceDir` is extremely sensitive. **Back it up securely offline.** Loss means permanent loss of the .onion address. Compromise allows impersonation. Restrict file permissions.
* **Vanity URL:** Use tools like `mkp224o` to generate custom prefixes. Securely replace the generated `hs_ed25519_secret_key` file.
* **Restart Tor:** `sudo systemctl restart tor` after configuration changes.
* **Retrieve Address:** `sudo cat /var/lib/tor/hidden_service/hostname`.

## 6. Secure Containerization, CI/CD, and Deployment Orchestration

### 6.1. Docker Container Security Principles

* **Minimal Base Images:** Use lean, secure base images (e.g., `python:3.x-slim`, `node:18-alpine`).
* **Non-Root Execution:** Run applications as a dedicated non-root user (`USER appuser`).
* **Multi-Stage Builds:** Reduce final image size and attack surface by discarding build dependencies.
* **No Secrets in Images:** Inject secrets ONLY at runtime (env vars from Vault, K8s Secrets).
* **Image Scanning:** Integrate vulnerability scanning (Trivy, etc.) into CI/CD.
* **Least Privilege:** Minimize permissions within the container.

*(Specific Dockerfile content removed - refer to repository and apply principles.)*

### 6.2. Docker Compose for Secure Local Testing

Use `docker-compose.yml` for orchestrating local development services (Postgres, Redis, maybe Vault). Ensure secrets needed by services are injected via environment variables, potentially sourced from a local `.env` file which itself pulls from a local Vault dev instance. **Do not commit `.env` or hardcode production secrets in `docker-compose.yml`.**

*(Specific docker-compose.yml content removed - refer to repository.)*

### 6.3. Secure CI/CD Pipeline (GitHub Actions Example)

The CI/CD pipeline (`.github/workflows/ci-cd.yml`) should automate:
1.  **Code Checkout.**
2.  **Dependency Installation.**
3.  **Linting & Formatting Checks.**
4.  **Static Analysis (SAST):** Run `bandit` against backend code.
5.  **Dependency Vulnerability Scanning:** Run `pip-audit` (backend), `npm audit` / `yarn audit` (frontend).
6.  **Unit & Integration Tests:** Run `pytest` (backend), `jest`/`vitest` (frontend). **Fail build on test failures.**
7.  **Container Build:** Build backend and frontend images using multi-stage builds.
8.  **Container Vulnerability Scanning:** Scan built images (Trivy, etc.). **Fail build on critical vulnerabilities.**
9.  **(Optional) Image Signing:** Sign images with `cosign`.
10. **Image Push:** Push images to a container registry.
11. **Deployment Trigger:** Trigger deployment to staging/production (manual approval recommended for production).

Manage CI/CD secrets (Docker registry credentials, deployment keys) securely using GitHub Secrets.

*(Specific ci-cd.yml content removed - refer to repository and implement stages.)*

### 6.4. Kubernetes Deployment Security Principles (Optional)

If deploying to Kubernetes:
* **Namespaces:** Use dedicated namespaces for isolation.
* **Secrets Management:** Use Kubernetes Secrets, ideally populated dynamically from Vault using tools like the Vault Agent Injector or External Secrets Operator.
* **Network Policies:** Implement strict NetworkPolicies to control traffic flow between pods (default deny).
* **`securityContext`:** Define `runAsUser`, `runAsGroup`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, and drop unnecessary capabilities for all containers.
* **Resource Limits:** Set CPU and memory requests/limits to prevent resource exhaustion.
* **Ingress:** Configure Ingress controllers securely, handling TLS termination if applicable (though likely handled at Tor level).

*(Specific K8s manifest content removed - refer to repository and apply principles.)*

## 7. Hardened Production Deployment Guide (VPS / Dedicated Hardware)

This assumes deployment directly onto hardened servers, potentially managed via IaC tools (Ansible, Terraform).

### 7.1. Infrastructure Isolation Strategy

* **Application Server(s):** Run the Django backend (Gunicorn), potentially the Next.js server (or serve static files via Nginx), Redis (if not external), Celery workers/beat.
* **Database Server:** Dedicated server running PostgreSQL, firewalled to only allow connections from Application Server(s).
* **Crypto Node Servers:** **Separate, dedicated servers for each cryptocurrency node** (BTC, XMR, ETH). Heavily firewalled, allowing RPC connections *only* from specific Application Server IPs over secure channels.
* **Vault Server:** Dedicated server or cluster, hardened, with strict network access control.
* **Reverse Proxy / Tor Gateway:** Server running Tor daemon and Nginx (or similar) acting as a reverse proxy listening only on localhost and directing traffic to the backend.

### 7.2. Secure Server Setup (Linux Example)

* **Choose Provider Carefully:** Prioritize privacy and security if needed (consider jurisdiction, logging policies).
* **Provision Hardware:** Sufficient resources (CPU, RAM, SSD) per isolated component.
* **OS Hardening:** Use minimal stable Linux distribution (Debian, Ubuntu LTS). Apply security updates promptly. Configure `ufw` or `nftables` firewall (default deny). Secure SSH (key-only auth, disable root login, fail2ban). Configure AppArmor/SELinux if feasible. Install minimal required packages.
* **User Accounts:** Create dedicated low-privilege users for running each application component (e.g., `shadowmarket` user for Django/Gunicorn, `postgres` user for DB, etc.).
* **Install Dependencies:** Install Python, GPG, Tor, Nginx, Supervisor (or use systemd), database client libraries, etc.

### 7.3. Application Deployment & Runtime Configuration

1.  **Clone Repository:** Deploy code via Git clone/pull or secure copy.
2.  **Setup Backend:**
    * Create virtual environment, install dependencies (`requirements.txt`).
    * Configure GPG home directory for the application user with `0700` permissions.
    * **Inject Secrets:** Securely provide environment variables at runtime (e.g., via systemd unit files, Supervisor config, or tools pulling from Vault). **Do NOT write secrets to disk in `.env` files in production.**
    * Apply migrations: `python manage.py migrate`.
    * Collect static files: `python manage.py collectstatic --noinput`.
    * Run Gunicorn using Supervisor/systemd, binding to `127.0.0.1:8000`. Use multiple workers.
3.  **Setup Frontend:** (If serving dynamically via Node)
    * Install dependencies (`yarn install`), build (`yarn build`).
    * Inject `NEXT_PUBLIC_API_URL` (pointing to backend/proxy).
    * Run `yarn start` using Supervisor/systemd, binding to `127.0.0.1:3000`.
4.  **Setup Celery:** Run Celery worker and beat processes using Supervisor/systemd, ensuring they use production settings and have necessary environment variables.
5.  **Configure Reverse Proxy (Nginx):**
    * Configure Nginx to listen on `127.0.0.1:80`.
    * Proxy requests to the backend Gunicorn (`127.0.0.1:8000`).
    * Proxy requests for the frontend (if served dynamically) or serve static frontend build files directly.
    * Serve collected Django static files (`/static/`) and potentially media files.
    * Ensure appropriate proxy headers are set (`X-Forwarded-For`, `X-Forwarded-Proto`) if needed by Django settings (`SECURE_PROXY_SSL_HEADER`), but only trust headers from localhost.

### 7.4. Tor Hidden Service Setup (Production)

* On the Tor Gateway / Reverse Proxy server, configure `/etc/tor/torrc` as described in Section 5.3, pointing `HiddenServicePort 80` to the local Nginx listener (`127.0.0.1:80`).
* Ensure permissions on `/var/lib/tor/hidden_service/` are correct (`drwx------`, owned by Tor user).
* **Securely back up the `hs_ed25519_secret_key` offline.**
* Restart Tor and verify the hidden service is reachable via Tor Browser.

## 8. Ongoing Security: Testing, Auditing, Monitoring & Maintenance

### 8.1. Comprehensive Testing Strategy

* **Unit Tests:** Continue using `pytest` to test individual functions and classes in isolation (mocking dependencies). Aim for high coverage, especially for services, validators, and permissions.
* **Integration Tests:** Write tests that verify the interaction between components (e.g., API view -> service -> ledger -> database). Use fixtures to set up realistic data. Test entire workflows (e.g., full escrow lifecycle).
* **Security Tests:** Write tests specifically targeting security logic: permission failures, invalid input rejection, PGP verification failures, rate limiting triggers.
* **Frontend Tests:** Implement unit/integration tests for frontend components and logic using Jest/Vitest and React Testing Library. Test API interactions and state management.

### 8.2. Security Auditing & Penetration Testing

* **Static Analysis (SAST):** Integrate `bandit` into CI/CD.
* **Dependency Scanning:** Integrate `pip-audit`/`npm audit`/Snyk into CI/CD.
* **Container Scanning:** Integrate Trivy/Clair/etc. into CI/CD.
* **Manual Code Review:** Perform regular, focused manual security reviews of critical components (auth, crypto, escrow, ledger, admin panel).
* **Dynamic Analysis (DAST):** Use tools like OWASP ZAP or Burp Suite (manual and automated scanning) against staging environments.
* **Professional Audits:** Budget for periodic penetration testing and code audits by reputable third-party security professionals specializing in web applications and cryptocurrency systems.

### 8.3. Monitoring, Logging, and Alerting

* **Centralized Logging:** Ship all application logs (Django, Gunicorn, Nginx, Tor), system logs, and potentially database logs to a secure, centralized logging platform (e.g., ELK stack, Graylog).
* **Structured Logging:** Use JSON format for application logs for easier parsing and analysis.
* **Security Event Monitoring:** Specifically monitor security logs (`security_logger`) for failed logins, PGP failures, rate limits exceeded, admin actions, reconciliation errors, Dead Man's Switch alerts.
* **Performance Monitoring:** Monitor CPU, memory, disk I/O, network traffic, database performance, queue lengths.
* **Alerting:** Configure automated alerts (e.g., via ElastAlert, PagerDuty, secure messaging) for critical errors, security events, reconciliation failures, and resource exhaustion.

### 8.4. Maintenance & Incident Response

* **Regular Updates:** Keep all system packages, OS, language runtimes (Python, Node), libraries (Django, Next.js, etc.), databases, and Tor updated with security patches promptly.
* **Incident Response Plan:** Develop a plan outlining steps to take in case of a security breach, major outage, or other critical incident. Include communication channels, roles, data forensics steps, recovery procedures, and post-mortem analysis.

## 9. CRITICAL: Secret Management & Placeholder Replacement

**Before any deployment beyond local testing, ensure every single placeholder value is replaced with a unique, securely generated production secret, managed via Vault or secure environment injection.**

This includes, but is not limited to:
* `DJANGO_SECRET_KEY`
* All Database Credentials
* All Crypto Node RPC Credentials
* Vault Tokens / AppRole Credentials
* Any API Keys (Sentry, etc.)
* Market PGP Private Key Passphrases (if applicable, stored in Vault)
* Market Multi-Sig Private Keys (stored in Vault)

Failure to manage secrets securely *will* lead to compromise.

## 10. Operational Security Procedures (Appendix)

*(This section should be expanded with detailed internal procedures.)*

### 10.1. Key Management

* **Market PGP Keys:** Secure generation, backup (offline), rotation schedule, publication method for public key, procedure for handling compromised keys.
* **Multi-Sig Keys:** Secure generation of market's portion of multi-sig keys (via Vault transit engine?), backup procedures.
* **Warrant Canary:** Procedure for regular updates, signing key management, verification steps for users.
* **Vault Master Keys/Unseal Keys:** Extremely secure storage and distribution according to Vault best practices.

### 10.2. Backup and Recovery

* **Frequency & Scope:** Define what gets backed up (Database, Vault data, GPG keys, Tor HS keys, configurations) and how often.
* **Storage:** Use encrypted, geographically distributed, offline/offsite backups.
* **Testing:** Regularly test the recovery procedure in a staging environment.

### 10.3. Dead Man's Switch Procedures

* **Monitoring:** How is the trigger timestamp/health check monitored? Who is responsible?
* **Activation:** Who is authorized to execute the command? What confirmation steps (PGP signatures?) are required?
* **Post-Activation:** What are the exact steps after the switch is triggered? Communication plan? Recovery (if any)?

---

This updated guide provides a much more robust framework, emphasizing security throughout the architecture and deployment lifecycle. Remember, security is an ongoing process, not a one-time setup. Continuous vigilance, testing, and adaptation are required.

Sources and related content
