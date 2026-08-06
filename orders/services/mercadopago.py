import uuid
import logging
import requests
from decimal import Decimal
from django.conf import settings
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

class MercadoPagoService:
    BASE_URL = "https://api.mercadopago.com"

    @classmethod
    def get_headers(cls):
        return {
            "Authorization": f"Bearer {settings.MERCADOPAGO_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": str(uuid.uuid4())
        }

    @classmethod
    def create_order(cls, order, payment_data):
        """
        Cria uma Order no Mercado Pago usando o endpoint POST /v1/orders
        """
        url = f"{cls.BASE_URL}/v1/orders"
        
        # Limpeza e formatação de dados do cliente
        clean_cpf = order.customer_cpf.replace('.', '').replace('-', '').replace('/', '')
        doc_type = "CNPJ" if len(clean_cpf) > 11 else "CPF"

        name_parts = order.customer_name.strip().split(' ', 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        # --- NOVO CÁLCULO DE TOTAL ISOLADO ---
        # Soma os itens e calcula o valor base
        items_total = sum(item.quantity * item.unit_price for item in order.items.all())
        base_total = items_total + order.shipping_fee
        total_value = float(base_total)
        
        payment_method_type = payment_data.get('payment_method')

        # Se for PIX, aplica 5% de desconto APENAS sobre o valor dos produtos
        if payment_method_type == 'pix':
            total_value = float((items_total * Decimal('0.95')) + order.shipping_fee)
        # -------------------------------------

        transaction_payload = {
            "amount": round(total_value, 2)
        }

        if payment_method_type == 'card':
            card_info = payment_data.get('card', {})
            transaction_payload["payment_method"] = {
                "id": card_info.get("payment_method_id"),  
                "type": card_info.get("payment_type_id", "credit_card"),
                "token": card_info.get("token")
            }
            transaction_payload["installments"] = int(payment_data.get("installments", 1))

        elif payment_method_type == 'pix':
            transaction_payload["payment_method"] = {
                "id": "pix"
            }

        payload = {
            "type": "online",
            "processing_mode": "automatic",
            "external_reference": str(order.id),
            "transactions": [transaction_payload],
            "payer": {
                "email": order.customer_email,
                "first_name": first_name,
                "last_name": last_name,
                "identification": {
                    "type": doc_type,
                    "number": clean_cpf
                }
            }
        }

        response = requests.post(url, json=payload, headers=cls.get_headers(), timeout=10)
        
        if response.status_code not in (200, 201):
            logger.error("Erro Mercado Pago Orders API: %s - %s", response.status_code, response.text)
            response.raise_for_status()

        return response.json()

    @classmethod
    def get_order(cls, mp_order_id):
        """
        Busca os dados de uma Order pelo ID do Mercado Pago (usado no webhook)
        """
        url = f"{cls.BASE_URL}/v1/orders/{mp_order_id}"
        headers = {
            "Authorization": f"Bearer {settings.MERCADOPAGO_ACCESS_TOKEN}"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()