import requests
from django.conf import settings
from datetime import date, timedelta

def get_headers():
    return {
        "access_token": settings.ASAAS_API_KEY,
        "Content-Type": "application/json"
    }

def create_customer(name, email, phone):
    url = f"{settings.ASAAS_BASE_URL}/customers"
    payload = {
        "name": name,
        "email": email,
        "phone": phone
    }
    response = requests.post(url, json=payload, headers=get_headers())
    response.raise_for_status()
    return response.json()["id"]

def create_payment(order, customer_id):
    url = f"{settings.ASAAS_BASE_URL}/payments"
    due_date = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
    
    payload = {
        "customer": customer_id,
        "billingType": "UNDEFINED",
        "value": float(order.total_price),
        "dueDate": due_date,
        "description": f"Pedido {order.id}",
        "externalReference": str(order.id),
        "callback": {
            "successUrl": f"{settings.FRONTEND_URL}/customer-area",
            "autoRedirect": True
        }
    }
    
    response = requests.post(url, json=payload, headers=get_headers())
    response.raise_for_status()
    return response.json()["invoiceUrl"]