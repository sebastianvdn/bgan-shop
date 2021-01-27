from django.conf import settings
from django.contrib.sites.models import Site
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar.apps.payment.exceptions import RedirectRequired
from oscar.core.loading import get_model
from oscar.apps.partner.strategy import Selector
strategy = Selector().strategy()

from . import PAYMENT_METHOD_STRIPE, PAYMENT_EVENT_PURCHASE, STRIPE_EMAIL, STRIPE_TOKEN

import stripe, json
import uuid

SourceType = get_model('payment', 'SourceType')
Source = get_model('payment', 'Source')

stripe.api_key = settings.STRIPE_SECRET_KEY

class PaymentDetailsView(CorePaymentDetailsView):

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        current_site = Site.objects.get_current()
        print(self.request.session["payment_method_id"])
        ctx = super().get_context_data(**kwargs)
        if self.preview:
            self.request.session["uuid"] = str(uuid.uuid4())
            ctx['order_total_incl_tax_cents'] = (
                ctx['order_total'].incl_tax * 100
            ).to_integral_value()
            ctx['STRIPE_PUBLIC_KEY'] = settings.STRIPE_PUBLIC_KEY
            if ctx['order_total_incl_tax_cents'] > 0:
                line_items = []
                for line in self.request.basket.all_lines():
                    line_items.append({
                        "price_data": {
                            "currency": "eur",
                            "product_data": {
                                "name": line.product.title,
                                # "images": [
                                #     line.product.primary_image(),
                                # ]
                            },
                            "unit_amount": int(strategy.fetch_for_product(line.product).price.incl_tax * 100)
                        },
                        "quantity": line.quantity
                    })
                session = stripe.checkout.Session.create(
                    payment_method_types=['card', 'bancontact'],
                    line_items=line_items,
                    mode='payment',
                    success_url=f'http://{current_site.domain}/checkout/preview/?completed=1',
                    cancel_url=f'http://{current_site.domain}/checkout/preview/',
                )
                self.request.session["session_id"] = session.id

        else:
            ctx['order_total_incl_tax_cents'] = (
                ctx['order_total'].incl_tax * 100
            ).to_integral_value()
            ctx['STRIPE_PUBLIC_KEY'] = settings.STRIPE_PUBLIC_KEY
        return ctx


    def handle_payment(self, order_number, total, **kwargs):
        print("PAYMEEEEENTTTT...")

        source_type, __ = SourceType.objects.get_or_create(name=PAYMENT_METHOD_STRIPE)
        source = Source(
            source_type=source_type,
            currency=settings.STRIPE_CURRENCY,
            amount_allocated=0,
            amount_debited=0,
            reference="stripe_ref")
        self.add_payment_source(source)

        self.add_payment_event(PAYMENT_EVENT_PURCHASE, total.incl_tax)


    def payment_description(self, order_number, total, **kwargs):
        return self.request.POST[STRIPE_EMAIL]

    def payment_metadata(self, order_number, total, **kwargs):
        return {'order_number': order_number}

        

# AJAX endpoint when `/pay` is called from client
@require_http_methods(["POST"])
@csrf_exempt
def stripe_pay(request):
    data = json.loads(request.body)
    print(data)
    intent = None

    if data.get("paymentsDetail", False):
        request.session["payment_method_id"] = data.get("payment_method_id", None)
        request.session["payment_intent_id"] = data.get("payment_intent_id", None)
        print("added to the session")
        return JsonResponse({'next': True}, status=200)
    else:
        try:
            if 'payment_method_id' in request.session:
                print("payment method id")
                # Create the PaymentIntent
                intent = stripe.PaymentIntent.create(
                    payment_method = request.session['payment_method_id'],
                    amount = int(request.basket.total_incl_tax * 100),
                    currency = 'eur',
                    confirmation_method = 'manual',
                    confirm = True,
                )
                print(intent["id"])
            elif 'payment_intent_id' in request.session:
                intent = stripe.PaymentIntent.confirm(request.session['payment_intent_id'])
        except stripe.error.CardError as e:
            # Display error on client
            return JsonResponse({'error': e.user_message}, status=200)

    return generate_response(intent)

def generate_response(intent):
    # Note that if your API version is before 2019-02-11, 'requires_action'
    # appears as 'requires_source_action'.
    if intent.status == 'requires_action' and intent.next_action.type == 'use_stripe_sdk':
        # Tell the client to handle the action
        print("requires_action")
        return JsonResponse({
            'requires_action': True, 
            'payment_intent_client_secret': intent.client_secret,
        }, status=200)
    elif intent.status == 'succeeded':
        # The payment didn’t need any additional actions and completed!
        # Handle post-payment fulfillment
        print("succeeded")
        return JsonResponse({'success': True}, status=200)
    else:
        # Invalid status
        print("Invalid PaymentIntent status")
        return JsonResponse({'error': 'Invalid PaymentIntent status'}, status=500)
