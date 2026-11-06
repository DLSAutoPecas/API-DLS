import requests
from django.conf import settings
from datetime import date, timedelta

# PNG transparente 1x1 — placeholder exigido pela Asaas no campo imageBase64
# de cada item do Checkout. Pode ser trocado por fotos reais dos produtos depois.
PLACEHOLDER_IMAGE_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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
    """Fluxo antigo (fatura simples). Mantido apenas para referencia/rollback;
    nao e' mais chamado pelo checkout. O fluxo atual usa create_checkout()."""
    url = f"{settings.ASAAS_BASE_URL}/payments"
    due_date = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")

    valor_total = 0.0

    for item in order.items.all():
        preco = float(item.unit_price)
        quantidade = float(item.quantity)
        valor_total += preco * quantidade

    taxa_entrega = float(order.shipping_fee)
    valor_total += taxa_entrega

    payload = {
        "customer": customer_id,
        "billingType": "UNDEFINED",
        "value": valor_total,
        "dueDate": due_date,
        "description": f"Pedido {order.id}",
        "externalReference": str(order.id),
        "callback": {
            "successUrl": "https://www.dlsautopecas.com.br/catalogo",
            "autoRedirect": True
        }
    }

    response = requests.post(url, json=payload, headers=get_headers())

    if not response.ok:
        raise Exception(f"Erro ao criar cobrança no Asaas: {response.text}")

    return response.json()["invoiceUrl"]


def _checkout_items(order):
    items = []
    for item in order.items.all():
        items.append({
            "name": item.product.name[:30],
            "description": item.product.name[:150],
            "quantity": item.quantity,
            "value": float(item.unit_price),
            "imageBase64": PLACEHOLDER_IMAGE_BASE64,
        })

    if order.shipping_fee and float(order.shipping_fee) > 0:
        items.append({
            "name": "Frete",
            "description": order.shipping_service or "Frete",
            "quantity": 1,
            "value": float(order.shipping_fee),
            "imageBase64": PLACEHOLDER_IMAGE_BASE64,
        })

    return items


def create_checkout(order):
    """Cria um Checkout Asaas: Pix ou cartao de credito (a vista ou parcelado
    em ate 12x). Boleto nao e' oferecido. Retorna a URL da pagina de pagamento."""
    url = f"{settings.ASAAS_BASE_URL}/checkouts"

    payload = {
        "billingTypes": ["CREDIT_CARD", "PIX"],
        "chargeTypes": ["DETACHED", "INSTALLMENT"],
        "installment": {"maxInstallmentCount": 12},
        "externalReference": str(order.id),
        "callback": {
            "successUrl": "https://www.dlsautopecas.com.br/catalogo",
            "cancelUrl": "https://www.dlsautopecas.com.br/checkout",
},
        "items": _checkout_items(order),
    }

    response = requests.post(url, json=payload, headers=get_headers())

    if not response.ok:
        raise Exception(f"Erro ao criar checkout no Asaas: {response.text}")

    return response.json()["link"]