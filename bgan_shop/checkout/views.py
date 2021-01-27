from django.conf import settings
from django.contrib.sites.models import Site
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse

from oscar.apps.checkout.views import PaymentDetailsView as CorePaymentDetailsView
from oscar.apps.payment.exceptions import RedirectRequired
from oscar.core.loading import get_model
from oscar.apps.partner.strategy import Selector
strategy = Selector().strategy()

from .facade import Facade

from .forms import PaymentType

from . import PAYMENT_METHOD_STRIPE, PAYMENT_EVENT_PURCHASE, STRIPE_EMAIL, STRIPE_TOKEN

import stripe
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
                print(current_site.domain)
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
        