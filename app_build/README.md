# Mantaw — Technical Setup & Deployment Guide

This guide details the steps required to develop, run, test, and deploy the Mantaw News Radar service.

---

## 1. Local Development

### Prerequisites
- **Python Version**: Python 3.11 or 3.12.
- **Git** installed on your system.

### Installation Steps

1. **Navigate to the Application Directory**:
   ```bash
   cd app_build
   ```

2. **Create a Virtual Environment**:
   ```bash
   python -m venv .venv
   ```

3. **Activate the Virtual Environment**:
   - On **Windows** (PowerShell):
     ```powershell
     .venv\Scripts\Activate.ps1
     ```
   - On **macOS/Linux**:
     ```bash
     source .venv/bin/activate
     ```

4. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Configure Local Environment**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Open the created `.env` file and configure the settings (see the [Environment Variables](#2-environment-variables) section below).

6. **Start the Development Server**:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8080
   ```
   The service will start running locally at `http://localhost:8080`.

### Local Testing

- **Verify Liveness (`/health`)**:
  ```bash
  curl http://localhost:8080/health
  ```
  **Response**: `{"ok": true}`

- **Trigger the News Radar (`/run`)**:
  - If `RUN_SECRET` is not set:
    ```bash
    curl http://localhost:8080/run
    ```
  - If `RUN_SECRET` is configured as `testsecret`:
    ```bash
    curl "http://localhost:8080/run?secret=testsecret"
    ```

---

## 2. Environment Variables

Mantaw loads configuration settings using Pydantic Settings. The following variables are supported:

| Variable Name | Required | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `DISCORD_WEBHOOK_URL` | **Yes** | *None* | Discord channel webhook url to post news alerts. |
| `RUN_SECRET` | No | *None* | Authentication token query parameter required to run `/run`. |
| `MIN_SCORE` | No | `4` | Minimum relevance score required for an article to be alerted. |
| `MAX_ITEMS` | No | `10` | Maximum number of alerts posted to Discord per trigger. |
| `MAX_ITEM_AGE_DAYS` | No | `14` | Discards articles published older than this value (e.g. 14 days). |
| `MAX_ITEMS_PER_SOURCE` | No | `3` | Caps how many items from the same feed source can be sent per execution cycle. |

---

## 3. Local Docker Run

To verify container packaging before deploying:

1. **Build the Docker Image**:
   Execute from the `app_build/` directory:
   ```bash
   docker build -t mantaw:latest .
   ```

2. **Run the Container**:
   Pass the environment variables directly using the `-e` flag:
   ```bash
   docker run -p 8080:8080 \
     -e DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/your-id/your-token" \
     -e RUN_SECRET="container_secret" \
     -e MAX_ITEM_AGE_DAYS=14 \
     -e MAX_ITEMS_PER_SOURCE=3 \
     mantaw:latest
   ```
   You can now query the docker container at `http://localhost:8080/health` or `http://localhost:8080/run?secret=container_secret`.

---

## 4. Google Cloud Platform (GCP) Setup

To host the service, you need a Google Cloud Platform account. Follow these configuration steps:

### Enable Required GCP APIs
Enable the following APIs in your GCP Project:
- **Cloud Run API** (`run.googleapis.com`)
- **Artifact Registry API** (`artifactregistry.googleapis.com`)
- **Cloud Build API** (`cloudbuild.googleapis.com`)
- **IAM Service Account Credentials API** (`iamcredentials.googleapis.com`)

### Create Deployment Service Account
1. Create a service account to handle deployments:
   ```bash
   gcloud iam service-accounts create mantaw-deployer \
     --description="Service account for deploying Mantaw from GitHub Actions" \
     --display-name="Mantaw Deployer"
   ```

2. Grant the service account the required roles:
   - **Cloud Run Admin** (`roles/run.admin`) — to manage the deployment of the Cloud Run service.
   - **Service Account User** (`roles/iam.serviceAccountUser`) — to associate the service account with the Cloud Run instance.
   - **Artifact Registry Admin** (`roles/artifactregistry.admin`) — to create repositories and push Docker images.
   - **Storage Admin** (`roles/storage.admin`) — to upload container layers during Cloud Build.

### Configure Workload Identity Federation (WIF)
Workload Identity Federation allows GitHub Actions to securely authenticate with GCP without managing static service account credentials.

1. **Create an Identity Pool**:
   ```bash
   gcloud iam workload-identity-pools create "github-actions-pool" \
     --project="YOUR_PROJECT_ID" \
     --location="global" \
     --display-name="GitHub Actions Pool"
   ```

2. **Create an Identity Provider**:
   ```bash
   gcloud iam workload-identity-pools providers create-oidc "github-provider" \
     --workload-identity-pool="github-actions-pool" \
     --project="YOUR_PROJECT_ID" \
     --location="global" \
     --issuer-uri="https://token.actions.githubusercontent.com" \
     --attribute-mapping="google.subject=assertion.subject,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
     --display-name="GitHub Actions Provider"
   ```

3. **Bind the Identity Pool to the Service Account**:
   Grant the GitHub repository permission to act as the service account:
   ```bash
   gcloud iam service-accounts add-iam-policy-binding "mantaw-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/iam.workloadIdentityUser" \
     --member="principalSet://iam.googleapis.com/projects/YOUR_PROJECT_NUMBER/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/YOUR_GITHUB_ORG/YOUR_REPO"
   ```
   *(Note: Replace `YOUR_GITHUB_ORG/YOUR_REPO` with your repository name, e.g. `andhikkadd/mantaww`)*

### Required GitHub Secrets
In your GitHub repository, go to **Settings > Secrets and variables > Actions** and add the following repository secrets:
- `GCP_PROJECT_ID`: Your GCP Project ID.
- `GCP_REGION`: Target deployment region (e.g., `us-central1`).
- `GCP_SERVICE_NAME`: The name of the Cloud Run service (e.g., `mantaw`).
- `GCP_SERVICE_ACCOUNT`: The full email of the deployment service account (e.g., `mantaw-deployer@...gserviceaccount.com`).
- `GCP_WORKLOAD_IDENTITY_PROVIDER`: The WIF Provider resource path (e.g., `projects/YOUR_PROJECT_NUMBER/locations/global/workloadIdentityPools/github-actions-pool/providers/github-provider`).
- `DISCORD_WEBHOOK_URL`: The Discord webhook URL.
- `RUN_SECRET`: The authorization token query parameter.

---

## 5. GitHub Actions Deployment

The CI/CD pipeline configuration is located in the repository root at:
👉 **`.github/workflows/deploy.yml`**

- **Triggers**: Executed automatically on every push to the `main` branch.
- **Context Source**: Built and packaged from the `./app_build` directory.
- **WIF Auth**: Uses `google-github-actions/auth@v3` to request ephemeral credentials.
- **Deployment**: Deploys the service using `google-github-actions/deploy-cloudrun@v3`.

---

## 6. Cloud Run Public Access Settings

- **`/health`**: Needs to allow unauthenticated (public) access so that health probes work without configuration.
- **`/run`**: Access is restricted and secured using the `RUN_SECRET` token.
- **Setting up Public Access on Cloud Run**:
  During deploy, or manually in the GCP Cloud Run console, make sure the service is configured to **"Allow unauthenticated invocations"**. Since `/run` checks the query parameter `secret=...` internally, the endpoint remains secure from malicious triggers.

---

## 7. Cloud Scheduler Setup

To trigger the news radar automatically, configure a **Google Cloud Scheduler** HTTP job:

### Cloud Scheduler Trigger Examples
- **Every 3 Hours** (Default suggestion):
  `0 */3 * * *`
- **Every Morning** (e.g., 8:00 AM):
  `0 8 * * *`
- **Twice Daily** (e.g., 8:00 AM and 8:00 PM):
  `0 8,20 * * *`

### Configuration Settings
- **Region/Location**: Same region as your Cloud Run service.
- **Target Type**: `HTTP`
- **URL**: `https://YOUR_CLOUD_RUN_SERVICE_URL/run?secret=YOUR_RUN_SECRET`
- **HTTP Method**: `GET`
- **Auth Header**: `None` (Authentication is handled via the `secret` query parameter validation).
- **Timezone**: `Asia/Jakarta` (or your local timezone).

---

## 8. Troubleshooting Section

### `403 Forbidden` on `/health` or `/run`
- **Cause**: Cloud Run service is set to "Require authentication" (private access only).
- **Solution**: Go to GCP Console -> Cloud Run -> select your service -> Trigger -> select "Allow unauthenticated invocations".

### `401 Unauthorized` on `/run`
- **Cause**: The `secret` parameter was missing, or did not match the `RUN_SECRET` environment variable configured on Cloud Run.
- **Solution**: Check your cron trigger parameters and make sure the query string matches your secret value.

### GitHub Actions: Auth Error / WIF Provider Issue
- **Cause**: The IAM Workload Identity Pool mapping or attribute mapping is incorrect.
- **Solution**: Ensure your GCP secrets match exactly, and the service account binding member is pointing to the correct repository (`attribute.repository/YOUR_GITHUB_ORG/YOUR_REPO`).

### `artifactregistry.repositories.create` denied
- **Cause**: Deployment service account lacks permissions to create repositories.
- **Solution**: Ensure the Service Account has `roles/artifactregistry.admin` in IAM settings. Alternatively, pre-create the Artifact Registry repository (`gcloud-deploy` or match service name) manually.

### `storage.buckets.create` denied
- **Cause**: Deployment service account lacks permission to create storage buckets (used by Cloud Build).
- **Solution**: Ensure the Service Account has `roles/storage.admin`.

### Discord `400 Bad Request`
- **Cause**: Discord Webhook payload is invalid or the Webhook URL is malformed.
- **Solution**: Verify `DISCORD_WEBHOOK_URL` in the environment settings and confirm it is a valid Discord API webhook.

### News Fetch works but no Discord Alert
- **Cause**: No parsed articles met the `MIN_SCORE` threshold (default: 4), or the parsed articles were too old (> `MAX_ITEM_AGE_DAYS`).
- **Solution**: Check logs in Cloud Run Metrics to see the pipeline summary print. Try lowering `MIN_SCORE` or modifying allowlist keywords in `main.py`.

---

## 9. Security Notes
- **Never Commit `.env`**: Make sure the local `.env` configuration file is kept private (it is automatically ignored by `.gitignore`).
- **Use GitHub Secrets**: Static GCP keys or webhooks must only be stored in GitHub Secrets.
- **Webhook Rotation**: If the `DISCORD_WEBHOOK_URL` is leaked, delete the webhook in Discord and rotate/replace the GitHub Secret immediately.
