# SentiMental

SentiMental is a comprehensive web application designed to streamline mental health helpline operations. It provides role-based dashboards for Helpline Managers (Admins), Responders, and Mental Health Professionals, real-time call documentation, AI-assisted summarization, geographic heatmapping, analytics, shift scheduling, and internal caller escalation.

---

# 📂 Project Configuration

> **Important**
>
> This project requires an environment configuration file (`.env`) and the default **Admin account credentials** to run successfully.
>
> These files are securely provided through Google Drive.

## 🔑 Download Project Configuration

**Google Drive Folder:**  
https://drive.google.com/drive/folders/1YPkMLHX4TO8ImV3OTOv1mbb014GSweNX?usp=drive_link

The Google Drive folder contains:

- **`.env`**
  - Django Secret Key
  - PostgreSQL (Supabase) Database URL
  - Supabase API Keys
  - Email Configuration
  - Other required environment variables

- **`ADMIN_CREDENTIALS.txt`**
  - Admin login credentials

---

# 🛠️ Local Installation Guide

## 1. Clone the repository

```bash
git clone https://github.com/zumorinkashi17/sentimental.git
cd sentimental
```

---

## 2. Create a Virtual Environment

```bash
python -m venv .venv
```

### Windows

```bash
.venv\Scripts\activate
```

### macOS / Linux

```bash
source .venv/bin/activate
```

---

## 3. Install Dependencies

Make sure you're inside the project directory where `requirements.txt` is located.

```bash
pip install -r requirements.txt
```

---

## 4. Add the `.env` File

1. Download the `.env` file from the Google Drive folder above.
2. Place it in the project root directory (the same folder as `manage.py`).

Example:

```
SentiMental/
│── manage.py
│── .env
│── requirements.txt
│── ...
```

---

## 5. Run the Development Server

```bash
python manage.py runserver
```

Open your browser and visit:

```
http://127.0.0.1:8000/
```

Log in using the **Admin credentials** provided in the Google Drive folder.

---

# ✨ Key Features

### 🔐 Role-Based Access Control

- Dedicated dashboards for Helpline Managers (Admins), Responders, and Mental Health Professionals
- Secure authentication and authorization
- Role-scoped escalation permissions: responders request, managers assign, and professionals assess

### 👥 User Management

- Invite responders, managers, or mental health professionals through email
- Secure token-based account activation
- Password validation and reset functionality

### 👤 Profile Management

- Update personal information
- Upload profile pictures via Supabase Storage
- Secure password changes

### 📞 Call Documentation

- Manual call logging
- Rule-based auto-fill with optional spaCy NER
- TextRank extractive summarization formatted into the call-summary template and translated into English
- Multi-label intervention classification
- Manual responder review of Risk Assessment and Reason for Calling
- Comprehensive documentation interface

### ⬆️ Caller Escalation

- Escalate a saved call session from the session history modal
- Managers assign escalations to active mental health professionals
- Professionals acknowledge, request information from responders, and record assessments
- Full audit trail of created, assigned, acknowledged, information, assessment, and cancellation events
- Caller phone numbers are masked in the professional review view

### 📊 Analytics Dashboard

- Call volume statistics
- Caller demographics
- Risk assessment visualization
- Interactive charts powered by Chart.js

### 🗺️ Geographic Heatmapping

- Visualize caller distribution geographically

### 📅 Shift Scheduling

- Calendar-based responder shift management

---

# 🤖 NLP Auto-Fill and Summarization

The NLP layer runs locally and does not call an external AI API.

- Rule-based extraction works out of the box.
- The trained spaCy NER model is optional. If `apps/callers/nlp/models/ner` is missing, the pipeline automatically falls back to rules-only mode.
- TextRank selects the most relevant caller sentences; `apps/callers/nlp/summary.py` builds the Bisaya template, then translates it into the English summary returned to the UI. The original Bisaya version remains available as `summary_bisaya`.
- Risk Assessment and Reason for Calling are intentionally left for responder review.

## Optional: Train the NER Model

Trained models are intentionally excluded from Git. To regenerate the model:

```bash
pip install -r requirements.txt
python -m apps.callers.nlp.train_ner
```

Training reads `apps/callers/nlp/data/annotations.json` and writes the model to `apps/callers/nlp/models/ner`.

## Optional: Train the Risk Classifier

The rule engine in `apps/callers/nlp/risk.py` remains the safety fallback. The optional spaCy text classifier learns from counselor-corrected labels and can only raise a flag, never lower one.

```bash
python -m apps.callers.nlp.train_risk
python -m apps.callers.nlp.train_risk --epochs 40 --seed 7
```

Training reads `apps/callers/nlp/data/suicide_risk_annotations.json` and writes the model to `apps/callers/nlp/models/risk`. Add more records in this format to teach new phrasings:

```json
{"text": "moinom og daghang tambal para makatulog ug di na momata", "label": "HIGH_RISK", "category": "Method - Ingestion/Poison"}
```

Valid labels are `LOW`, `MODERATE_RISK`, and `HIGH_RISK`. Restart the server after training so the new model is loaded.

## Run NLP Tests

```bash
python manage.py test apps.callers.tests
```

## Run Application Tests

```bash
python manage.py test tests
```

Role and escalation behavior is covered by `tests/test_escalations.py`.

---

# 💻 Tech Stack

## Backend

- Django 6.0
- Python
- spaCy (optional NER)
- TextRank (local extractive summarization)

## Database

- PostgreSQL (Supabase)

## Storage

- Supabase Storage Buckets

## Frontend

- Tailwind CSS
- JavaScript (AJAX)
- Chart.js
- Phosphor Icons
- SweetAlert2

---

# 📁 Project Requirements

- Python 3.12+
- PostgreSQL Database (Supabase)
- pip
- Virtual Environment (recommended)

---

# 🔒 Security Notice

The `.env` file contains sensitive information including:

- Django Secret Key
- Database Credentials
- Supabase Keys
- Email Credentials

**Do not commit the `.env` file to GitHub or share it publicly.**

---

# 📜 License

This project is intended for educational and academic purposes unless otherwise specified.
