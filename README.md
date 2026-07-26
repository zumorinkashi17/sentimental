# 🌿 SentiMental - Mental Health Helpline Management System

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
git clone https://github.com/zumorinkashi17/sentimental-app.git
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

## 5. Apply Database Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

---

## 6. Run the Development Server

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
- AI-assisted call summarization workflow
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

# 💻 Tech Stack

## Backend

- Django 6.0
- Python

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
