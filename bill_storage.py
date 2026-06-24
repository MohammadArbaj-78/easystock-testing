"""
Bill History Storage
======================
Yeh file bills ko laptop ki hard disk pe ek JSON file mein
PERMANENTLY save karti hai, taaki browser tab band karne ke
baad bhi data wapas mil sake.

Saare bills "bills_history.json" naam ki file mein save hote hain,
jo isी folder mein बनती hai jahan medical_app.py hai.
"""

import json
import os
from datetime import datetime

HISTORY_FILE = "bills_history.json"


def load_all_bills():
    """Saare save kiye hue bills file se load karta hai."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_bill(bill_name, items_df, total_amount, total_cgst, total_sgst, total_gst):
    """
    Ek naya bill record permanently save karta hai.

    items_df mein columns hone chahiye:
    Dawai Ka Naam, Quantity (Stock), Price (₹), GST Rate (%)
    """
    bills = load_all_bills()

    new_bill = {
        "bill_id": len(bills) + 1,
        "bill_name": bill_name,
        "date_saved": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_amount": round(float(total_amount), 2),
        "total_cgst": round(float(total_cgst), 2),
        "total_sgst": round(float(total_sgst), 2),
        "total_gst": round(float(total_gst), 2),
        "grand_total": round(float(total_amount + total_gst), 2),
        "items": items_df.to_dict(orient="records")
    }

    bills.append(new_bill)

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(bills, f, indent=2, ensure_ascii=False)

    return new_bill


def delete_bill(bill_id):
    """Ek specific bill ko history se hata deta hai."""
    bills = load_all_bills()
    bills = [b for b in bills if b["bill_id"] != bill_id]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(bills, f, indent=2, ensure_ascii=False)


def get_monthly_summary():
    """Mahine-wise GST total nikalta hai saare saved bills se."""
    bills = load_all_bills()
    monthly_data = {}

    for bill in bills:
        month_key = bill["date_saved"][:7]  # "2026-06" jaisa format
        if month_key not in monthly_data:
            monthly_data[month_key] = {
                "total_bills": 0,
                "total_amount": 0.0,
                "total_cgst": 0.0,
                "total_sgst": 0.0,
                "total_gst": 0.0
            }
        monthly_data[month_key]["total_bills"] += 1
        monthly_data[month_key]["total_amount"] += bill["total_amount"]
        monthly_data[month_key]["total_cgst"] += bill["total_cgst"]
        monthly_data[month_key]["total_sgst"] += bill["total_sgst"]
        monthly_data[month_key]["total_gst"] += bill["total_gst"]

    return monthly_data
