from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import HttpResponse

import stripe

stripe.api_key = settings.STRIPE_SECRET_KEY

@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    payload = request.body
    print(payload)
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.WEBHOOK_SECRET
        )
    except ValueError:
        # Invalid payload
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        return HttpResponse(status=400)

    # Handle the checkout.session.completed event
    if event["type"] == "checkout.session.completed":

        session = event["data"]["object"]
        # get reservation
        reservation = get_object_or_404(Reservation, reservation_code=session["metadata"]["reservation_code"])

        # Fulfill the purchase...
        subject = "Payment received: " + session["metadata"]["reservation_code"]
        html_message = render_to_string(
            "payments/email/receipt.html",
            context={
                "user": reservation.user,
                "reservation": reservation,
            },
        )
        plain_message = strip_tags(html_message)
        from_email = "Noreply Bgan <noreply@bgan.be>"
        to = reservation.user.email
        send_mail(
            subject, plain_message, from_email, [to], html_message=html_message
        )
        # Set reservation to paid
        reservation.paid = True
        reservation.save()

    # Passed signature verification
    return HttpResponse(status=200)