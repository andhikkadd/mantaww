# Mantaw - Personal News Radar

Mantaw is a personal news radar service that runs as a scheduled background worker on Google Cloud Run. It monitors select RSS news feeds, filters them using keywords, scores them, and alerts a Discord webhook with high-importance news.

## Repository Structure

- **`.github/workflows/deploy.yml`**: CI/CD pipeline configuration for automated Google Cloud Run deployments using GitHub Actions and Workload Identity Federation.
- **`app_build/`**: The core application directory, containing all service code, dependencies, container configuration, and documentation.
  - `main.py`: FastAPI server containing the scraping, filtering, and Discord webhook alerting logic.
  - `config.py`: Environment configuration and validation.
  - `requirements.txt`: Python package requirements.
  - `Dockerfile`: Container build configuration.
  - `README.md`: **[Main Setup & Deployment Guide]** - Comprehensive guide covering local environment variable configurations, Docker setup, Google Cloud Workload Identity Federation setup, and Cloud Scheduler triggers.
- **`.gitignore`**: Global rules to prevent local secrets (`.env`) and cache files from being tracked by Git.

## Getting Started

The **main setup and deployment guide** is located inside the application folder:

👉 **[App Setup & Deployment Guide (app_build/README.md)](file:///c:/learm/mantaw/app_build/README.md)**

Please refer to that file for detailed, step-by-step instructions on local development, local Docker testing, IAM workload identity mapping, and scheduling.
