import requests
from django.conf import settings
from datetime import date, timedelta
from decimal import Decimal

def get_headers():
    return {
        "access_token": settings.ASAAS_API_KEY,
        "Content-Type": "application/json"
    }

def create_customer(name, email, phone, cpf):
    url = f"{settings.ASAAS_BASE_URL}/customers"
    payload = {
        "name": name,
        "email": email,
        "phone": phone,
        "cpfCnpj": cpf
    }
    response = requests.post(url, json=payload, headers=get_headers())
    
    if not response.ok:
        raise Exception(f"Erro ao criar cliente no Asaas: {response.text}")
        
    return response.json()["id"]

def create_payment(order, customer_id):
    url = f"{settings.ASAAS_BASE_URL}/payments"
    due_date = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
    
    total_items = sum((item.unit_price * item.quantity for item in order.items.all()), Decimal('0.00'))
    shipping = Decimal(str(order.shipping_fee))
    valor_total = total_items + shipping
    
    payload = {
        "customer": customer_id,
        "billingType": "UNDEFINED",
        "value": float(valor_total),
        "dueDate": due_date,
        "description": f"Pedido {order.id}",
        "externalReference": str(order.id),
        "callback": {
            "successUrl": f"{settings.FRONTEND_URL}/customer-area",
            "autoRedirect": True
        }
    }
    
    response = requests.post(url, json=payload, headers=get_headers())
    
    if not response.ok:
        raise Exception(f"Erro ao criar cobrança no Asaas: {response.text}")
        
    return response.json()["invoiceUrl"]