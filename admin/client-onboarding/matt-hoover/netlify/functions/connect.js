const SERVICES = {
  calendar: {
    label: 'Google Calendar',
    auth_config_id: 'ac_amtPp5u1t_vq',
    user_id: 'client:matt-hoover:calendar',
    alias: 'matt-hoover-calendar',
  },
  gmail: {
    label: 'Gmail',
    auth_config_id: 'ac_FIJfsDVS9vzN',
    user_id: 'client:matt-hoover:gmail',
    alias: 'matt-hoover-gmail',
  },
  googledocs: {
    label: 'Google Docs',
    auth_config_id: 'ac_cggYp2Yv7KUF',
    user_id: 'client:matt-hoover:googledocs',
    alias: 'matt-hoover-googledocs',
  },
  googlesheets: {
    label: 'Google Sheets',
    auth_config_id: 'ac_GTPbFlzJeqJv',
    user_id: 'client:matt-hoover:googlesheets',
    alias: 'matt-hoover-googlesheets',
  },
  googletasks: {
    label: 'Google Tasks',
    auth_config_id: 'ac_xNK_Tayicjw9',
    user_id: 'client:matt-hoover:googletasks',
    alias: 'matt-hoover-googletasks',
  },
};

exports.handler = async (event) => {
  const service = event.queryStringParameters && event.queryStringParameters.service;
  const config = SERVICES[service];

  if (!config) {
    return {
      statusCode: 400,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      body: 'Unknown service. Please go back and choose one of the listed connect buttons.',
    };
  }

  const apiKey = process.env.COMPOSIO_API_KEY;
  if (!apiKey) {
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      body: 'Setup is missing a server-side Composio key. Please contact Jake.',
    };
  }

  try {
    let authConfigId = config.auth_config_id;

    if (!authConfigId && config.toolkit_slug) {
      const authResponse = await fetch('https://backend.composio.dev/api/v3/auth_configs', {
        method: 'POST',
        headers: {
          'x-api-key': apiKey,
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          toolkit: { slug: config.toolkit_slug },
          auth_config: {
            type: 'use_composio_managed_auth',
            credentials: {},
            restrict_to_following_tools: [],
          },
        }),
      });

      const authText = await authResponse.text();
      let authData = {};
      try {
        authData = authText ? JSON.parse(authText) : {};
      } catch (_) {
        authData = {};
      }

      authConfigId = authData.auth_config && authData.auth_config.id;

      if (!authResponse.ok || !authConfigId) {
        console.error('Composio auth config creation failed', {
          status: authResponse.status,
          service,
          body: authText.slice(0, 500),
        });
        return {
          statusCode: 502,
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
          body: `Could not create the ${config.label} authentication setup. Please contact Jake.`,
        };
      }
    }

    const response = await fetch('https://backend.composio.dev/api/v3/connected_accounts/link', {
      method: 'POST',
      headers: {
        'x-api-key': apiKey,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        auth_config_id: authConfigId,
        user_id: config.user_id,
        alias: config.alias,
      }),
    });

    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_) {
      data = {};
    }

    if (!response.ok || !data.redirect_url) {
      console.error('Composio link creation failed', {
        status: response.status,
        service,
        body: text.slice(0, 500),
      });
      return {
        statusCode: 502,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        body: `Could not create a fresh ${config.label} connection link. Please contact Jake.`,
      };
    }

    return {
      statusCode: 302,
      headers: {
        Location: data.redirect_url,
        'Cache-Control': 'no-store',
      },
      body: '',
    };
  } catch (error) {
    console.error('Unexpected connect error', { service, message: error && error.message });
    return {
      statusCode: 500,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      body: `Could not start ${config.label} connection. Please contact Jake.`,
    };
  }
};
