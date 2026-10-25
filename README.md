# SentiMental

SentiMental is a comprehensive web application designed to streamline mental health helpline operations. It provides role-based dashboards for Helpline Managers (Admins) and Responders, real-time call documentation, AI-assisted summarization, geographic heatmapping, analytics, and shift scheduling.

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

- Dedicated dashboards for Helpline Managers and Responders
- Secure authentication and authorization

### 👥 User Management

- Invite responders through email
- Secure token-based account activation
- Password validation and reset functionality

### 👤 Profile Management

- Update personal information
- Upload profile pictures via Supabase Storage
- Secure password changes

### 📞 Call Documentation

- Manual call logging
- Rule-based auto-fill with optional spaCy NER
- TextRank extractive summarization formatted into the Bisaya call-summary template
- Multi-label intervention classification
- Manual responder review of Risk Assessment and Reason for Calling
- Comprehensive documentation interface

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
- TextRank selects the most relevant caller sentences; `apps/callers/nlp/summary.py` formats the final Bisaya summary.
- Risk Assessment and Reason for Calling are intentionally left for responder review.

## Optional: Train the NER Model

Trained models are intentionally excluded from Git. To regenerate the model:

```bash
pip install -r requirements.txt
python -m apps.callers.nlp.train_ner
```

Training reads `apps/callers/nlp/data/annotations.json` and writes the model to `apps/callers/nlp/models/ner`.

## Run NLP Tests

```bash
python manage.py test apps.callers.tests
```

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
