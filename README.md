# Universal Solutions - Billing System

Python + Tkinter + SQLite billing application.

## UI
The Home dashboard has been updated to closely match the supplied Universal Solutions reference image:
- Dark navy left sidebar
- Blue active Home button
- Universal Solutions branding/logo area
- White/light dashboard workspace
- Welcome/Admin header
- Today's Date and Financial Year cards
- Four summary cards
- Quick Actions tiles
- Recent Documents table
- Financial-year sales and outstanding cards
- Footer and matching spacing/borders/colors

## First-time setup (Windows)
1. Extract the ZIP.
2. Open the project folder.
3. Double-click `setup.bat`.
4. Wait until installation finishes.
5. Double-click `start.bat`.

Or use CMD inside the project folder:

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

## Next time
Double-click `start.bat`, or run:

```bat
venv\Scripts\activate
python run.py
```

## Main modules
- Customer Master
- Product Master
- Route Rate Master
- Quotation
- Delivery Challan
- Tax Invoice (Bill)
- Challan-to-Invoice flow
- Original/Duplicate PDF output
- Reports
- Email / WhatsApp hand-off

## Data
SQLite database: `data/billing.db`

Generated PDFs: `exports/`

## Company details
Edit `config.py` to enter the actual company address, phone, email, GSTIN and bank details.
