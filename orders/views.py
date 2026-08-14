from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated, AllowAny

import logging
import requests
import hashlib
import stripe
from decimal import Decimal
from django.conf import settings
from django.core.cache import cache

from .models import Order
from .serializers import OrderSerializer, ShippingSimulationSerializer
from catalog.models import Product
from .services.stripe import create_stripe_checkout_session

logger = logging.getLogger(__name__)

class CheckoutView(generics.CreateAPIView):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

class OrderListView(generics.ListAPIView):
    queryset = Order.objects.all().order_by('-created_at')
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

class OrderPaymentView(APIView):
    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response({'error': 'Pedido não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            session = create_stripe_checkout_session(order)
            order.payment_method = 'stripe'
            order.save()

            return Response({
                'order_id': str(order.id),
                'session_id': session.id,
                'checkout_url': session.url
            }, status=status.HTTP_200_OK)

        except stripe.error.StripeError as e:
            logger.error("Erro na Stripe: %s", str(e))
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Erro inesperado ao processar pagamento (order %s)", order_id)
            return Response({'error': 'Erro interno ao processar o pagamento.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StripeWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        except stripe.error.SignatureVerificationError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            order_id = session.get('client_reference_id')

            if order_id:
                try:
                    order = Order.objects.get(id=order_id)
                    order.payment_status = 'paid'
                    order.status = 'PAID'
                    order.save()
                except Order.DoesNotExist:
                    pass

        return Response({'status': 'success'}, status=status.HTTP_200_OK)

class ShippingSimulationView(APIView):
    ORIGIN_CEP = "89200000" 

    def post(self, request):
        destination_cep = request.data.get('cep_destino', '').replace('-', '')
        items = request.data.get('items', [])

        if not destination_cep or len(destination_cep) != 8:
            return Response({"error": "CEP de destino inválido."}, status=status.HTTP_400_BAD_REQUEST)
        
        if not items:
            return Response({"error": "O carrinho está vazio."}, status=status.HTTP_400_BAD_REQUEST)

        cache_key_raw = f"{destination_cep}_" + "_".join([f"{item['product_id']}-{item['quantity']}" for item in sorted(items, key=lambda x: x['product_id'])])
        cache_key = hashlib.md5(cache_key_raw.encode('utf-8')).hexdigest()

        cached_shipping = cache.get(cache_key)
        if cached_shipping:
            return Response(cached_shipping, status=status.HTTP_200_OK)

        products_data = []
        for item in items:
            try:
                product = Product.objects.get(id=item['product_id'])
                products_data.append({
                    "id": str(product.id),
                    "width": float(product.width_cm) if getattr(product, 'width_cm', 0) > 0 else 10,
                    "height": float(product.height_cm) if getattr(product, 'height_cm', 0) > 0 else 10,
                    "length": float(product.length_cm) if getattr(product, 'length_cm', 0) > 0 else 10,
                    "weight": float(product.weight_kg) if getattr(product, 'weight_kg', 0) > 0 else 0.1,
                    "insurance_value": float(product.price),
                    "quantity": item['quantity']
                })
            except Product.DoesNotExist:
                return Response({"error": f"Produto ID {item['product_id']} não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        payload = {
            "from": {"postal_code": self.ORIGIN_CEP},
            "to": {"postal_code": destination_cep},
            "products": products_data
        }

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.MELHOR_ENVIO_TOKEN}",
            "User-Agent": "Aplicação DLS (thiago@dlsautopecas.com.br)"
        }

        try:
            url = f"{settings.MELHOR_ENVIO_URL}/api/v2/me/shipment/calculate"
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            
            melhor_envio_data = response.json()
            
            shipping_options = []
            for option in melhor_envio_data:
                if 'error' not in option and option.get('price'):
                    shipping_options.append({
                        "service": option.get("name"),
                        "price": option.get("price"),
                        "deadline_days": option.get("delivery_time")
                    })

            cache.set(cache_key, shipping_options, 3600)

            return Response(shipping_options, status=status.HTTP_200_OK)

        except requests.exceptions.RequestException as e:
            logger.error("Erro na API do Melhor Envio: %s", str(e))
            return Response({"error": "Serviço de frete indisponível no momento."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)