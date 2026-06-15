# Linux Setup Guide: AIS Vessel Intelligence System

This guide provides step-by-step instructions on setting up and running the **AIS Vessel Intelligence System** on a Linux environment (specifically optimized for Ubuntu/Debian-based systems).

---

## 📋 Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Step 1: Install PostgreSQL & PostGIS](#step-1-install-postgresql--postgis)
3. [Step 2: Configure PostgreSQL Database & Users](#step-2-configure-postgresql-database--users)
4. [Step 3: Setup Python Environment](#step-3-setup-python-environment)
5. [Step 4: Environment Configuration (.env)](#step-4-environment-configuration-env)
6. [Step 5: Run Database Setup](#step-5-run-database-setup)
7. [Step 6: Data Ingestion](#step-6-data-ingestion)
8. [Step 7: Run the Application](#step-7-run-the-application)
9. [🛡️ Production Deployment (Optional)](#️-production-deployment-optional)

---

## 1. Prerequisites
Before starting, ensure your system is up to date:
```bash
sudo apt update && sudo apt upgrade -y
```
Ensure you have the following installed or available:
* **Python 3.10 or higher**
* **pip** (Python package installer)
* **PostgreSQL (14+)**
* **PostGIS (3+)** extension

---

## Step 1: Install PostgreSQL & PostGIS
PostgreSQL and PostGIS are standard packages on modern Debian/Ubuntu repositories.

1. **Install PostgreSQL and PostGIS packages:**
   ```bash
   sudo apt install -y postgresql postgresql-contrib postgis postgresql-16-postgis-3
   ```
   *(Note: Replace `16` with your installed PostgreSQL version if you are using a different one. Run `psql --version` to check.)*

2. **Verify PostgreSQL is running:**
   ```bash
   sudo systemctl status postgresql
   ```
   If it is not active, start and enable it:
   ```bash
   sudo systemctl start postgresql
   ```

---

## Step 2: Configure PostgreSQL Database & Users

1. **Switch to the postgres user:**
   ```bash
   sudo -i -u postgres
   ```

2. **Access the PostgreSQL shell:**
   ```bash
   psql
   ```

3. **Create the PostgreSQL role and assign a password:**
   Change `cosmic` to your desired secure password.
   ```sql
   CREATE USER postgres WITH SUPERUSER PASSWORD 'cosmic';
   ```
   *(Note: If the `postgres` user already exists, you can set its password using: `ALTER USER postgres WITH PASSWORD 'cosmic';`)*

4. **Exit the PostgreSQL shell and shell session:**
   ```sql
   \q
   exit
   ```

5. **Configure authentication method (If needed):**
   By default, local PostgreSQL connections on Linux use `peer` authentication, which expects the Linux user to match the DB user. To allow password authentication:
   * Open `pg_hba.conf` (location varies, usually `/etc/postgresql/16/main/pg_hba.conf`):
     ```bash
     sudo nano /etc/postgresql/16/main/pg_hba.conf
     ```
   * Change local connection method from `peer` to `md5` or `scram-sha-256`:
     ```text
     # Database administrative login by Unix domain socket
     local   all             postgres                                peer
     
     # TYPE  DATABASE        USER            ADDRESS                 METHOD
     # "local" is for Unix domain socket connections only
     local   all             all                                     scram-sha-256
     ```
   * Restart PostgreSQL to apply changes:
     ```bash
     sudo systemctl restart postgresql
     ```

---

## Step 3: Setup Python Environment

1. **Install Python venv and dev dependencies:**
   ```bash
   sudo apt install -y python3-pip python3-venv python3-dev build-essential
   ```

2. **Navigate to the project root directory:**
   ```bash
   cd /path/to/AIS_Agent
   ```

3. **Create a virtual environment:**
   ```bash
   python3 -m venv venv
   ```

4. **Activate the virtual environment:**
   ```bash
   source venv/bin/activate
   ```

5. **Upgrade pip and install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

---

## Step 4: Environment Configuration (.env)

1. **Create or edit the `.env` file in the root of the project:**
   ```bash
   nano .env
   ```

2. **Populate the file with the database credentials and OpenAI API Key:**
   ```ini
   # PostgreSQL Connection Parameters
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=ais_vessel_intel
   DB_USER=postgres
   DB_PASSWORD=cosmic
   
   # OpenAI API Configuration
   OPENAI_API_KEY=your_openai_api_key_here
   
   # App Directories
   MAPS_DIR=maps
   ```
   Save and close the file (`Ctrl+O`, `Enter`, `Ctrl+X`).

---

## Step 5: Run Database Setup

The project includes an automation script that creates the target database, runs the SQL schema, and verifies that the PostGIS extension is loaded properly.

1. **Run the database setup script:**
   ```bash
   python db/setup_db.py
   ```
   *Expected Output:*
   ```text
   ============================================================
   AIS Vessel Intelligence — Database Setup
   ============================================================
   [OK] Created database 'ais_vessel_intel'.
   [OK] Schema applied successfully.
   [OK] PostGIS version: 3.4.2 ...
   [OK] Tables created: ais_gaps, ais_positions, tracks_simplified, vessels
   
   [SUCCESS] Database is ready.
   ```

---

## Step 6: Data Ingestion

Once the database is initialized, you can ingest the AIS data. Depending on your dataset, use one of the two ingestion scripts:

### Option A: Ingest Sample Data (~500k rows)
Use this for testing and development.
```bash
python ingestion/ingest_sample.py /path/to/your/ais-data.csv
```

### Option B: Bulk CSV Ingestion (Optimized, ~8.6M rows)
Uses optimized pandas buffer streams and chunked `COPY` for fast database writes.
```bash
python ingestion/ingest_csv.py /path/to/your/ais-data.csv
```

### Compute AIS Signal Gaps (Dark Activity)
After importing positions, you need to calculate the signal gaps to enable dark activity detection tools:
```bash
# Calculate gaps exceeding 10 minutes (default is 10)
python ingestion/compute_gaps.py --threshold 10
```

---

## Step 7: Run the Application

Start the interactive Streamlit chat interface:
```bash
streamlit run app.py
```

Streamlit will print the local and network URLs:
```text
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.1.100:8501
```

If you are running this on a headless remote server, you can access the interface by:
1. Opening port `8501` in your cloud provider's firewall.
2. Using SSH local port forwarding from your local machine:
   ```bash
   ssh -L 8501:localhost:8501 user@your-server-ip
   ```
   Then open `http://localhost:8501` on your local web browser.

---

## 🛡️ Production Deployment (Optional)

For a persistent deployment that survives server reboots:

1. **Create a Systemd Service File:**
   ```bash
   sudo nano /etc/systemd/system/ais-agent.service
   ```

2. **Add the following configuration:**
   *(Ensure to update paths and users to match your setup)*
   ```ini
   [Unit]
   Description=AIS Vessel Intelligence Streamlit App
   After=network.target postgresql.service

   [Service]
   User=your-linux-user
   WorkingDirectory=/path/to/AIS_Agent
   Environment="PATH=/path/to/AIS_Agent/venv/bin"
   ExecStart=/path/to/AIS_Agent/venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

3. **Reload systemd daemon, enable, and start the service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable ais-agent.service
   sudo systemctl start ais-agent.service
   ```

4. **Monitor the logs:**
   ```bash
   journalctl -u ais-agent.service -f
   ```
