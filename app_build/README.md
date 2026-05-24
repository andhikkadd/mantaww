# Mantaw - Personal News Radar Service

Mantaw is a scheduled, lightweight backend service designed to run on Google Cloud Run. It collects RSS news updates from selected tech and AI sources, filters and scores them based on allowlist and blocklist keywords, deduplicates them, and publishes the highest-scoring updates as beautiful rich embeds to a Discord channel via a Webhook.

---

## Folder Structure

```text
app_build/
├── .github/
│   └── workflows/
│       └── deploy.yml   # CI/CD deployment configuration via GitHub Actions
├── main.py              # FastAPI application & news radar pipeline
├── config.py            # Configuration parser via pydantic-settings
├── requirements.txt     # Python application dependencies
├── Dockerfile           # Standard containerization config for Cloud Run
├── .env.example         # Example local environment variable configuration
└── README.md            # Documentation
```

---

## Local Setup & Run

### 1. Prerequisite
- Python 3.11 or 3.12 installed locally.

### 2. Installation
Navigate into the `app_build` directory and install the required dependencies:
```bash
cd app_build
pip install -r requirements.txt
```

### 3. Environment Variables
Copy `.env.example` to `.env` and fill in the required variables:
```bash
cp .env.example .env
```
Edit `.env`:
- `DISCORD_WEBHOOK_URL`: Your Discord webhook URL.
- `RUN_SECRET`: (Optional) A secret token to protect the `/run` endpoint.
- `MIN_SCORE`: (Optional, default 4) The threshold score for qualifying news.
- `MAX_ITEMS`: (Optional, default 10) Maximum number of alerts sent per run.

### 4. Running the App
Run the application locally using Uvicorn:
```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```
The application will start on `http://localhost:8080`.

---

## Endpoint Testing

You can test the endpoints locally using `curl` or any API client (e.g., Postman).

### Health Check
```bash
curl http://localhost:8080/health
```
**Response:**
```json
{"ok": true}
```

### Run News Radar Pipeline
If `RUN_SECRET` is not set:
```bash
curl http://localhost:8080/run
```

If `RUN_SECRET` is set to `my_secret_token` in your `.env`:
```bash
curl "http://localhost:8080/run?secret=my_secret_token"
```
**Response:**
```json
{
  "status": "success",
  "processed_count": 14,
  "alerted_count": 3,
  "items": [
    {
      "title": "OpenAI Launches GPT-4o Mini",
      "score": 8,
      "category": "AI",
      "source": "OpenAI",
      "link": "https://openai.com/news/gpt-4o-mini"
    }
  ]
}
```

---

## Local Docker Build & Test

### 1. Build the Docker Image
```bash
docker build -t mantaw:latest .
```

### 2. Run the Container
Pass the environment variables directly:
```bash
docker run -p 8080:8080 \
  -e DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
  -e RUN_SECRET="my_secret_token" \
  mantaw:latest
```
Test using `curl http://localhost:8080/health` or `curl "http://localhost:8080/run?secret=my_secret_token"`.

---

## CI/CD Deployment via GitHub Actions (Workload Identity Federation)

Deployment to Google Cloud Run is fully automated on every push to the `main` branch.

### 1. Workload Identity Federation (WIF) Setup (High Level)
To authorize GitHub Actions to deploy to Google Cloud without static credential keys:
1. Create a Google Cloud Identity Pool and Provider for GitHub:
   ```bash
   gcloud iam workload-identity-pools create "github-actions-pool" \
     --project="YOUR_PROJECT_ID" \
     --location="global" \
     --display-name="GitHub Actions Pool"
   ```
2. Create an IAM Service Account with permission to build images (Artifact Registry, Cloud Build) and deploy to Cloud Run:
   ```bash
   gcloud iam service-accounts create mantaw-deployer \
     --description="Service account for deploying Mantaw from GitHub Actions" \
     --display-name="Mantaw Deployer"
   ```
3. Grant the required roles to the service account:
   - `roles/run.admin` (Cloud Run Administrator)
   - `roles/iam.serviceAccountUser` (Service Account User)
   - `roles/artifactregistry.admin` (Artifact Registry Admin)
   - `roles/storage.admin` (Google Cloud Storage Admin, for build logs/artifacts)
4. Bind the GitHub repository to the Service Account through WIF:
   ```bash
   gcloud iam service-accounts add-iam-policy-binding "mantaw-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/iam.workloadIdentityUser" \
     --member="principalSet://iam.googleapis.com/projects/YOUR_PROJECT_NUMBER/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/YOUR_GITHUB_ORG/YOUR_REPO"
   ```

### 2. Configure GitHub Secrets
In your GitHub repository, navigate to **Settings > Secrets and variables > Actions** and add the following repository secrets:

| Secret Name | Description | Example |
| :--- | :--- | :--- |
| `GCP_PROJECT_ID` | Your Google Cloud project ID | `my-gcp-project-12345` |
| `GCP_REGION` | Target Cloud Run deployment region | `us-central1` |
| `GCP_SERVICE_NAME` | Name of the Cloud Run service | `mantaw` |
| `GCP_SERVICE_ACCOUNT` | Deployer Service Account Email | `mantaw-deployer@...gserviceaccount.com` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full resource path of the WIF Provider | `projects/.../locations/global/workloadIdentityPools/.../providers/...` |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL | `https://discord.com/api/webhooks/...` |
| `RUN_SECRET` | Secret token query param for `/run` | `my_secret_token` |

### 3. Push to Deploy
Push your changes to the `main` branch of your repository:
```bash
git add .
git commit -m "Deploying news radar service"
git push origin main
```
The GitHub Action will build, upload, and deploy the service to Cloud Run.

---

## Cloud Scheduler Integration

Once deployed, set up **Google Cloud Scheduler** to run the job periodically.

### Create Cloud Scheduler Job via `gcloud`
Run the following command to schedule a trigger every 3 hours (adjust cron syntax and URL as necessary):

```bash
gcloud scheduler jobs create http mantaw-trigger \
  --schedule="0 */3 * * *" \
  --uri="https://YOUR_CLOUD_RUN_SERVICE_URL/run?secret=YOUR_RUN_SECRET" \
  --http-method=GET \
  --location="YOUR_GCP_REGION"
```

Replace:
- `YOUR_CLOUD_RUN_SERVICE_URL` with the URL generated by Cloud Run.
- `YOUR_RUN_SECRET` with the configured `RUN_SECRET`.
- `YOUR_GCP_REGION` with your Cloud Run deployment region.
