import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

def create_stripe_checkout_session(order):
    line_items = []
    for item in order.items.all():
        line_items.append({
            'price_data': {
                'currency': 'brl',
                'product_data': {
                    'name': item.product_name,
                },
                'unit_amount': int(item.unit_price * 100),
            },
            'quantity': item.quantity,
        })

    session = stripe.checkout.Session.create(
        payment_method_types=['card', 'boleto'],
        line_items=line_items,
        mode='payment',
        success_url=f"{settings.FRONTEND_URL}/meus-pedidos",
        cancel_url=f"{settings.FRONTEND_URL}/carrinho",
        client_reference_id=str(order.id),
        customer_email=order.customer_email,
    )
    
    return session