🛡️ Broker Intelligence Suite: User Manual

**Version:** 1.0 (Live Document)
**Last Updated:** December 2025
**Status:** Active (Rx Module Live / GeoAccess In-Development)

---

## 1. Overview

The **Broker Intelligence Suite** is an automated analytics platform designed to bridge the gap between "dense data" (PDF reports) and "business intelligence."

Instead of manually copying numbers from PDF tables into Excel, this tool uses advanced Python-based extraction engines to:

1. **Read** unstructured PDF reports (Claims, GeoAccess, Census).
2. **Structure** the data into clean, usable formats.
3. **Visualize** key trends, cost drivers, and network gaps instantly.

---

## 2. Key Features

### 🧠 The "Smart Router" (Traffic Controller)

You do not need to tell the system what you are uploading. The application automatically scans the first page of your file to identify the report type:

* **Rx Experience Reports:** Routes to the *Claims Liberator Engine*.
* **GeoAccess Reports:** Routes to the *Network Analysis Engine* (Coming Soon).
* **Census Files:** Routes to the *Member Impact Engine* (Coming Soon).

### 💊 The Claims Liberator (Rx Module)

* **Stacked Row Detection:** Intelligently splits rows where multiple cohorts (e.g., "Actives" and "Retirees") are compressed into a single line.
* **Whitespace Strategy:** Uses optical structure recognition to read tables without gridlines, preventing data concatenation errors.
* **Interactive Dashboards:** Replaces static tables with dynamic charts that allow you to drill down into monthly spend and specific cohort costs.

---

## 3. Quick Start Guide

### Step 1: Access the Portal

Navigate to the secure web link provided (e.g., `https://claims-liberator.streamlit.app`).

* *Note: No software installation is required.*

### Step 2: Upload Your Data

* Locate the **"Drag & Drop"** zone at the top of the dashboard.
* Drag your file (PDF, Excel, or CSV) into the box.
* **Supported Files currently:**
* Aon/Optum Monthly Experience Reports (PDF)
* *GeoAccess & Census support is currently in Alpha testing.*



### Step 3: Review the Intelligence Dashboard

Once the file is processed (approx. 2-5 seconds), the dashboard will generate:

1. **Executive Metrics:** Total Spend, Average Monthly Cost, and Top Cost Driver.
2. **Spend Composition Chart:** A stacked bar chart showing monthly trends broken down by cohort. *Hover over any bar to see exact figures.*
3. **Cohort Leaderboard:** A horizontal bar chart ranking groups by total spend.
4. **Data Grid:** A searchable, filterable view of the raw extracted numbers for verification.

---

## 4. Troubleshooting & FAQ

**Q: The numbers seem too low/understated.**

* **Check:** Ensure the PDF contains the "TOTAL" summary tables at the bottom of the pages. The engine prioritizes these for accuracy.
* **Fix:** If the report format is non-standard, please submit the PDF to the development team to calibrate the "Whitespace Strategy."

**Q: The dashboard text is hard to read.**

* The application is optimized for both **Light Mode** and **Dark Mode**. If you are using Dark Mode on your system, the cards will automatically adjust to semi-transparent glass styling to ensure high contrast.

**Q: Is my data saved?**

* **No.** The application processes data in-memory during your session. Once you close the tab or refresh the page, the data is wiped. No proprietary client data is permanently stored in the application database.

---

## 5. Version History & Roadmap

| Version | Date | Module | Change Log |
| --- | --- | --- | --- |
| **v1.0** | Dec 2025 | **Rx Engine** | Initial Release. Added "Smart Router" for auto-detection. Implemented "Stacked Row" explosion logic. |
| **v1.1** | *Planned* | **GeoAccess** | Visual mapping of network gaps. Distance calculations. |
| **v1.2** | *Planned* | **Census** | Demographics parsing and "Disruption Report" generation. |
