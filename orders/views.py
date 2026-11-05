import logging

import secrets
from django.conf import settings
from django.db import transaction
from django.core.exceptions import ValidationError

from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response


from catalog.models import Product
from .models import Order
from .serializers import OrderSerializer, ShippingSimulationSerializer
from .services.asaas import create_checkout
from .services import superfrete

logger = logging.getLogger(__name__)


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.prefetch_related('items__product').order_by('-created_at')
    serializer_class = OrderSerializer

    def get_permissions(self):
        # O checkout (criar pedido) é público: o cliente compra sem login.
        # Listar, ver, editar e excluir pedidos é só para administrador.
        if self.action == 'create':
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()

        try:
            checkout_link = create_checkout(order)
            order.invoice_url = checkout_link
            order.save(update_fields=['invoice_url'])
            return Response(
                {"order": serializer.data, "invoice_url": checkout_link},
                status=status.HTTP_201_CREATED,
            )
        except Exception:
            order.delete()
            logger.exception("Falha no checkout do pedido")
            return Response(
                {"error": "Não foi possível processar o pagamento. Tente novamente."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class ShippingQuoteView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = ShippingSimulationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        quantities = {}
        for item in data['items']:
            pid = item['product_id']
            quantities[pid] = quantities.get(pid, 0) + item['quantity']

        products = Product.objects.filter(id__in=quantities.keys())
        if len(products) != len(quantities):
            return Response(
                {'error': 'Um ou mais produtos do carrinho não foram encontrados.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cart_lines = [(p, quantities[p.id]) for p in products]

        try:
            options = superfrete.quote(data['zip_code'], cart_lines)
        except superfrete.SuperFreteError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not options:
            return Response(
                {'error': 'Nenhuma opção de entrega disponível para este CEP. '
                          'Entre em contato pelo WhatsApp.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(options)


PAID_EVENTS = {'PAYMENT_RECEIVED', 'PAYMENT_CONFIRMED'}
CHECKOUT_PAID_EVENT = 'CHECKOUT_PAID'


def _mark_order_paid(order_id, payment_status, payment_method, event_label):
    """Idempotente: só processa a primeira vez que o pedido é pago.
    Dá baixa no estoque de forma segura (sem deixar negativo)."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(id=order_id).first()

        if order is None:
            logger.error('Webhook %s: pedido %s nao encontrado.', event_label, order_id)
            return

        if order.status != 'PENDING':
            return

        items = list(order.items.all())
        product_ids = [item.product_id for item in items]
        products = {
            p.id: p
            for p in Product.objects.select_for_update().filter(id__in=product_ids)
        }

        for item in items:
            product = products.get(item.product_id)
            if product is None:
                logger.error(
                    'Pedido %s: produto %s nao encontrado ao dar baixa no estoque.',
                    order_id, item.product_id,
                )
                continue

            novo_estoque = product.stock - item.quantity
            if novo_estoque < 0:
                logger.warning(
                    'Pedido %s: baixa de %s un. do produto %s levaria o '
                    'estoque a %s. Estoque zerado; verificar divergencia '
                    'manualmente.',
                    order_id, item.quantity, product.id, novo_estoque,
                )
                novo_estoque = 0

            Product.objects.filter(id=product.id).update(stock=novo_estoque)

        order.status = 'PAID'
        order.payment_status = payment_status
        order.payment_method = payment_method
        order.save(update_fields=['status', 'payment_status', 'payment_method'])

    logger.info('Pedido %s marcado como PAGO via %s.', order_id, event_label)


class AsaasWebhookView(APIView):
    """Recebe notificações do Asaas (cobranças avulsas antigas e Checkout).
    Sempre responde 200 quando o token é válido, para o Asaas não reenviar
    indefinidamente."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        expected = settings.ASAAS_WEBHOOK_TOKEN
        received = request.headers.get('asaas-access-token', '')
        if not expected or not secrets.compare_digest(received, expected):
            logger.warning('Webhook Asaas recusado: token invalido.')
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        event = request.data.get('event')

        # --- Fluxo novo: Checkout (Pix / cartao a vista ou parcelado) ---
        if event == CHECKOUT_PAID_EVENT:
            checkout = request.data.get('checkout') or {}
            order_id = checkout.get('externalReference')
            if not order_id:
                logger.error(
                    'Webhook CHECKOUT_PAID sem externalReference. Campos recebidos: %s',
                    list(checkout.keys()),
                )
                return Response({'received': True})

            billing_types = checkout.get('billingTypes') or []
            try:
                _mark_order_paid(
                    order_id,
                    payment_status='CHECKOUT_PAID',
                    payment_method=','.join(billing_types),
                    event_label=event,
                )
            except (ValueError, ValidationError):
                logger.exception(
                    'Webhook CHECKOUT_PAID com externalReference invalido: %s', order_id
                )
            return Response({'received': True})

        # --- Fluxo antigo: cobranca avulsa (fatura simples) ---
        payment = request.data.get('payment') or {}

        if event not in PAID_EVENTS:
            return Response({'received': True})

        order_id = payment.get('externalReference')
        if not order_id:
            logger.error(
                'Webhook %s sem externalReference. Campos recebidos: %s',
                event, list(payment.keys()),
            )
            return Response({'received': True})

        try:
            _mark_order_paid(
                order_id,
                payment_status=payment.get('status') or event,
                payment_method=payment.get('billingType') or '',
                event_label=event,
            )
        except (ValueError, ValidationError):
            logger.exception('Webhook %s com externalReference invalido: %s', event, order_id)

        return Response({'received': True})