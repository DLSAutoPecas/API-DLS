from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import Order
from .serializers import OrderSerializer
from .services.asaas import create_customer, create_payment

class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()

        try:
            customer_id = create_customer(
                name=order.customer_name,
                email=order.customer_email,
                phone=order.customer_phone
            )
            invoice_url = create_payment(order, customer_id)
            
            return Response(
                {"order": serializer.data, "invoice_url": invoice_url},
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            order.delete()
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )